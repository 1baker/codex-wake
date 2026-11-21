"""Stage pinned complete packages; activation is a separate, reversible selection.

Recipes are host-authorized build instructions, never downloaded executable code.
Official source URLs and pinned source hashes are provenance inputs, not a claim
of an upstream signature. Capability qualification is bound to resulting bytes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import tarfile
import time
import threading
from urllib.request import Request, urlopen
from urllib.parse import urlparse


class UpgradeError(ValueError):
    pass


REQUIRED_CAPABILITIES = {
    'modded': ('scoped_reload', 'durable_notices', 'caller_accounting', 'orphan_output'),
    'stock': ('official_cli',),
}


def _json(path):
    return json.loads(Path(path).read_text())


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as stream:
        os.chmod(stream.name, 0o600)
        json.dump(value, stream, indent=2)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
        temporary=stream.name
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def _name(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',value):
        raise UpgradeError('invalid stage identifier')
    return value


def _files(directory):
    result={}
    for p in sorted(directory.rglob('*')):
        if p.is_symlink():raise UpgradeError('package/source symlinks are unsupported')
        if p.is_file():
            result[str(p.relative_to(directory))]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':p.stat().st_mode & 0o777}
    return result


def _source_regular(path, root):
    try:target=path.resolve(strict=True)
    except (OSError,RuntimeError) as error:
        raise UpgradeError('source link target unavailable or cyclic') from error
    if not target.is_relative_to(root):raise UpgradeError('source link target escapes source root')
    if not stat.S_ISREG(target.stat().st_mode):raise UpgradeError('source links must resolve to regular files')
    return target


def _source_inventory(directory):
    """Describe normalized source bytes, retaining the original link graph."""
    root=directory.resolve(strict=True);files={};links={}
    for path in sorted(root.rglob('*')):
        mode=path.lstat().st_mode
        if stat.S_ISDIR(mode):continue
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            raise UpgradeError('source special files unsupported')
        target=_source_regular(path,root)
        relative=str(path.relative_to(root))
        files[relative]={'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'mode':target.stat().st_mode & 0o777}
        if stat.S_ISLNK(mode):
            links[relative]={'target':os.readlink(path),'resolved_target':str(target.relative_to(root)),'link_mode':mode & 0o777,**files[relative]}
    return files,links


def _copy_source(tree, work, inventory, links):
    """Materialize only checked regular source files into an owned build tree."""
    work.mkdir(mode=0o700)
    for path in sorted(tree.rglob('*')):
        if path.is_dir() and not path.is_symlink():
            (work/path.relative_to(tree)).mkdir(parents=True,exist_ok=True)
    for relative in inventory:
        target=_source_regular(tree/relative,tree)
        destination=work/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(target,destination)
    current,current_links=_source_inventory(tree)
    if current!=inventory or current_links!=links or _files(work)!=inventory:
        raise UpgradeError('source changed while staging; pinned snapshot unavailable')


def _package(directory):
    files=_files(directory)
    for name in ['bin/codex','bin/codex-code-mode-host','codex-resources/bwrap','codex-path/rg']:
        if name not in files or not files[name]['mode'] & 0o111:
            raise UpgradeError('complete executable package required: '+name)
    if 'codex-package.json' not in files:raise UpgradeError('complete package manifest required')
    return files


@contextmanager
def _locked(root, *, blocking=True):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o022:raise UpgradeError('store ownership invalid')
    descriptor=os.open(root/'.upgrade.lock',os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True
    finally:os.close(descriptor)


def _commands(commands,cwd,receipt,phase, *, timeout=600):
    if type(timeout)!=int or not 1<=timeout<=21600:raise UpgradeError('command timeout must be one second to six hours')
    if not isinstance(commands,list):raise UpgradeError('command list required')
    reports=[]
    for command in commands:
        if not isinstance(command,list) or not command or any(not isinstance(x,str) for x in command):
            raise UpgradeError('commands must be explicit argv arrays')
        env={key:os.environ[key] for key in ('PATH','LANG','LC_ALL','CARGO_BUILD_JOBS','CARGO_TARGET_DIR','CODEX_UPGRADE_OWNED_GROUP','CODEX_UPGRADE_TEMP_ROOT') if key in os.environ}
        env['CODEX_UPGRADE_PACKAGE']=str(cwd)
        try:
            with tempfile.TemporaryDirectory(prefix='codex-upgrade-home-', dir=env.get('CODEX_UPGRADE_TEMP_ROOT')) as home:
                env.update(HOME=home,CODEX_HOME=str(Path(home)/'.codex'),XDG_CONFIG_HOME=str(Path(home)/'.config'),XDG_DATA_HOME=str(Path(home)/'.local/share'))
                Path(env['CODEX_HOME']).mkdir(mode=0o700)
                process=subprocess.Popen(command,cwd=cwd,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=env.get('CODEX_UPGRADE_OWNED_GROUP') != '1')
                try:
                    stdout,stderr=process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    (process.kill() if env.get('CODEX_UPGRADE_OWNED_GROUP') == '1' else os.killpg(process.pid,signal.SIGKILL));process.communicate();raise
                finally:
                    try:
                        if env.get('CODEX_UPGRADE_OWNED_GROUP') != '1':os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                run=subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
        except subprocess.TimeoutExpired as error:
            raise UpgradeError(phase+' command timed out') from error
        receipt.setdefault('commands',[]).append({'phase':phase,'argv':command,'exit':run.returncode,'stdout_sha256':hashlib.sha256(run.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(run.stderr.encode()).hexdigest()})
        if run.returncode:raise UpgradeError(phase+' command failed with exit '+str(run.returncode))
        reports.append(run.stdout)
    return reports


def _source_tree(source, destination, receipt):
    if 'tree' in source:
        receipt['source_transport']='pinned_local_tree'
        return Path(source['tree']).resolve(strict=True),source.get('files')
    expected=source.get('sha256','')
    if not re.fullmatch(r'[0-9a-f]{64}',expected):raise UpgradeError('pinned upstream archive SHA256 required')
    archive_path=destination/'source.tar.gz'
    maximum=2*1024**3
    fixture=source.get('archive_file')
    stream=Path(fixture).open('rb') if fixture else urlopen(Request(source['official_url'],headers={'User-Agent':'codex-profiles'}),timeout=30)
    receipt['source_transport']='fixture_archive' if fixture else 'official_https_archive'
    receipt['source_archive_sha256']=expected
    try:
        if not fixture:
            final=urlparse(stream.geturl())
            if final.scheme!='https' or not (final.hostname in ('github.com','codeload.github.com') or final.hostname.endswith('.githubusercontent.com')):
                raise UpgradeError('upstream archive redirected outside official hosting')
        digest=hashlib.sha256();size=0;deadline=time.monotonic()+300
        with archive_path.open('xb') as output:
            while True:
                if time.monotonic()>deadline:raise UpgradeError('source download deadline exceeded')
                chunk=stream.read(1024*1024)
                if not chunk:break
                size+=len(chunk)
                if size>maximum:raise UpgradeError('source download exceeds two GiB limit')
                digest.update(chunk);output.write(chunk)
            output.flush();os.fsync(output.fileno())
        if digest.hexdigest()!=expected:raise UpgradeError('source archive digest mismatch')
        tree=destination/'unpacked-source';tree.mkdir(mode=0o700)
        strip=source.get('strip_components',0)
        if type(strip)!=int or not 0<=strip<=10:raise UpgradeError('invalid source strip_components')
        count=0;unpacked=0;links={};members=set()
        with tarfile.open(archive_path,'r:*') as archive:
            for member in archive:
                count+=1;unpacked+=member.size
                if count>100000 or unpacked>maximum:raise UpgradeError('source extraction exceeds bounded limit')
                relative=Path(member.name)
                if relative.is_absolute() or '..' in relative.parts:raise UpgradeError('source archive path escape')
                if len(relative.parts)<=strip:continue
                relative=Path(*relative.parts[strip:]);target=tree/relative
                if relative in members:raise UpgradeError('duplicate source archive path')
                members.add(relative)
                if member.issym():
                    if Path(member.linkname).is_absolute():raise UpgradeError('source link target escapes source root')
                    links[relative]=member.linkname
                    continue
                if member.isdir():target.mkdir(parents=True,exist_ok=True,mode=0o700)
                elif member.isfile():
                    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    with archive.extractfile(member) as data,target.open('xb') as output:shutil.copyfileobj(data,output)
                    target.chmod(member.mode & 0o777)
                else:raise UpgradeError('source archive hard links and special files unsupported')
        for relative,target in links.items():
            if any(parent in links for parent in relative.parents):raise UpgradeError('source directory links unsupported')
            if any(relative in path.parents for path in members):raise UpgradeError('source directory links unsupported')
            resolved=(tree/relative).parent.joinpath(target).resolve(strict=False)
            if not resolved.is_relative_to(tree):raise UpgradeError('source link target escapes source root')
        for relative,target in links.items():
            link=tree/relative;link.parent.mkdir(parents=True,exist_ok=True);link.symlink_to(target)
        inventory,_=_source_inventory(tree)
        return tree,{key:value['sha256'] for key,value in inventory.items()}
    finally:
        stream.close()
        if archive_path.exists():archive_path.unlink()


def official_source_url(value):
    """Official release assets or a source archive pinned to an exact commit."""
    if not isinstance(value, str):return False
    parsed=urlparse(value)
    return (parsed.scheme=='https' and parsed.netloc=='github.com' and not parsed.query and not parsed.fragment
        and (parsed.path.startswith('/openai/codex/releases/download/')
             or re.fullmatch(r'/openai/codex/archive/[0-9a-f]{40}\.tar\.gz', parsed.path) is not None))


def stage(root:Path, recipe_path:Path):
    root=root.resolve();recipe_path=recipe_path.resolve()
    recipe=_json(recipe_path)
    if recipe.get('schema_version')!=1:raise UpgradeError('unsupported recipe version')
    identifier=_name(recipe.get('id'));channel=recipe.get('channel')
    if channel not in ('stock','modded'):raise UpgradeError('invalid channel')
    source=recipe.get('source',{})
    if not official_source_url(source.get('official_url', '')):
        raise UpgradeError('official upstream source provenance required')
    for key in ['upstream_version','revision']:_name(recipe.get(key))
    receipt={'schema_version':1,'id':identifier,'channel':channel,'status':'building','phase':'source','recipe_sha256':hashlib.sha256(recipe_path.read_bytes()).hexdigest(),'source':source['official_url'],'created_at':time.time()}
    with _locked(root):
        destination=root/'stages'/identifier
        if destination.exists():
            existing=_json(destination/'receipt.json')
            if existing.get('recipe_sha256')==receipt['recipe_sha256'] and existing.get('status')=='staged':
                if _package(destination/'package')!=existing['files']:raise UpgradeError('staged package bytes changed')
                return existing
            raise UpgradeError('stage id already exists; reconcile previous outcome')
        destination.mkdir(parents=True,mode=0o700)
        try:
            tree,expected_source=_source_tree(source,destination,receipt)
            inventory,links=_source_inventory(tree)
            observed={key:value['sha256'] for key,value in inventory.items()}
            if observed!=expected_source:raise UpgradeError('source pin mismatch')
            receipt['source_links']=links
            receipt['source_links_sha256']=hashlib.sha256(json.dumps(links,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            receipt['source_snapshot_sha256']=hashlib.sha256(json.dumps({'files':inventory,'links':links},sort_keys=True,separators=(',',':')).encode()).hexdigest()
            work=destination/'work';_copy_source(tree,work,inventory,links)
            if tree==destination/'unpacked-source':shutil.rmtree(tree)
            receipt['phase']='patch'
            for patch in recipe.get('patches',[]):
                path=Path(patch['path'])
                if hashlib.sha256(path.read_bytes()).hexdigest()!=patch['sha256']:raise UpgradeError('patch pin mismatch')
                _commands([['git','apply','--check',str(path.resolve())],['git','apply',str(path.resolve())]],work,receipt,'patch')
            receipt['phase']='build';_commands(recipe.get('build',[]),work,receipt,'build',timeout=recipe.get('command_timeout_seconds',600))
            package_source=(work/recipe['package']).resolve(strict=True)
            if not package_source.is_relative_to(work):raise UpgradeError('package output escapes source')
            files=_package(package_source)
            package=destination/'package';shutil.copytree(package_source,package)
            receipt['phase']='qualify'
            reports=_commands(recipe.get('qualify',[]),package,receipt,'qualify',timeout=recipe.get('command_timeout_seconds',600))
            if not reports:raise UpgradeError('installed package qualification required')
            checks={}
            for report in reports:
                parsed=json.loads(report)
                if parsed.get('schema_version')!=1:raise UpgradeError('unsupported qualification report')
                receipt.setdefault('qualification_reports',[]).append(parsed)
                checks.update(parsed.get('checks',{}))
            required=REQUIRED_CAPABILITIES[channel]
            if any(checks.get(check) is not True for check in required):raise UpgradeError('required native capability failed or unqualified')
            if _package(package)!=files:raise UpgradeError('qualification changed package bytes')
            schemas=recipe.get('read_schemas');write=recipe.get('write_schema')
            if not isinstance(schemas,list) or not schemas or any(type(x)!=int for x in schemas) or type(write)!=int or write not in schemas:
                raise UpgradeError('explicit compatible history schema required')
            receipt.update(status='staged',phase='complete',files=files,checks=checks,source_identity={'upstream_version':recipe['upstream_version'],'revision':recipe['revision'],'source_files':observed},evidence_scope=recipe.get('evidence_scope','source_fixture'),eligibility={'stage':True,'private_selection':True,'production_cutover':False},read_schemas=schemas,write_schema=write,build={'executable':str(package/'bin/codex'),'sha256':files['bin/codex']['sha256'],'upstream_version':recipe['upstream_version'],'revision':recipe['revision'],'source':source['official_url']})
            shutil.rmtree(work)
        except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
            receipt.update(status='failed',failed_stage=receipt['phase'],reason=str(error))
        _atomic(destination/'receipt.json',receipt)
        return receipt


def _qualified(root, identifier):
    directory=root/'stages'/_name(identifier)
    receipt=_json(directory/'receipt.json')
    required=REQUIRED_CAPABILITIES.get(receipt.get('channel'))
    if required is None:raise UpgradeError('unknown staged build channel')
    if (receipt.get('status')!='staged' or not receipt.get('qualification_reports')
            or any(receipt.get('checks',{}).get(key) is not True for key in required)
            or _package(directory/'package')!=receipt.get('files')):
        raise UpgradeError('staged package qualification is missing or stale')
    return receipt


def _schemas(home):
    result=set()
    for path in home.glob('state_*.sqlite'):
        match=re.fullmatch(r'state_(\d+)\.sqlite',path.name)
        if not match:raise UpgradeError('unknown history schema')
        result.add(int(match.group(1)))
    return result


def _hold_unmanaged_native(home, *, allow_private=None):
    """Same-user native processes outside our lock also fence selection."""
    if not Path('/proc').is_dir():raise UpgradeError('native process census unavailable')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name)==os.getpid():continue
        try:
            if process.stat().st_uid!=os.getuid():continue
            if not (process/'comm').read_text().strip().startswith('codex'):continue
            executable=Path(os.readlink(process/'exe')).name
            if not executable.startswith('codex'):continue
            values=dict(item.split(b'=',1) for item in (process/'environ').read_bytes().split(b'\0') if b'=' in item)
            selected=values.get(b'CODEX_HOME')
            if not selected:
                user_home=values.get(b'HOME')
                if not user_home:raise UpgradeError('native home ownership unknown; selection held')
                selected=user_home+b'/.codex'
            if Path(os.fsdecode(selected)).resolve()==home.resolve():
                if allow_private is not None and allow_private(process):continue
                raise UpgradeError('unmanaged native client owns tenant home; selection held')
        except (FileNotFoundError,ProcessLookupError):continue
        except PermissionError as error:raise UpgradeError('native process census incomplete') from error


def select(root:Path, home:Path, *, identifier=None, channel=None, rollback=False):
    from .build_channels import _home_ownership
    root=root.resolve();home=home.absolute()
    with _locked(root), _home_ownership(home):
        _hold_unmanaged_native(home)
        active_path=root/'builds.json'
        active=_json(active_path) if active_path.exists() else {'schema_version':1,'builds':{},'stages':{},'history':{}}
        if active.get('schema_version')!=1:raise UpgradeError('unknown active registry schema')
        tenant_home=str(home.resolve())
        selection=active.get('tenants',{}).get(tenant_home)
        if selection is None:
            selection={'builds':{},'stages':{},'history':{key:list(value) for key,value in active.get('history',{}).items()}}
        if rollback:
            channel=channel or 'modded'
            history=selection.get('history',{}).get(channel,[])
            if not history:raise UpgradeError('no qualified rollback retained')
            identifier=history[-1]
        receipt=_qualified(root,identifier)
        channel=receipt['channel']
        observed=_schemas(home)
        if not observed.issubset(set(receipt['read_schemas'])):
            raise UpgradeError('package cannot read current tenant schema; activation held')
        previous_id=selection.get('stages',{}).get(channel,active.get('stages',{}).get(channel))
        if previous_id==identifier:return {'status':'already_selected','id':identifier,'channel':channel}
        previous=_qualified(root,previous_id) if previous_id else None
        if previous and receipt['write_schema'] not in previous['read_schemas']:
            raise UpgradeError('upgrade would make rollback incompatible; compatible recovery route required')
        operation={'schema_version':1,'operation':'rollback' if rollback else 'activate','id':identifier,'previous_id':previous_id,'channel':channel,'status':'prepared','tenant_home':str(home.resolve()),'observed_schemas':sorted(observed),'at':time.time()}
        _atomic(root/'operation.json',operation)
        selection.setdefault('builds',{})[channel]=dict(receipt['build'],tenant_home=tenant_home,read_schemas=receipt['read_schemas'],write_schema=receipt['write_schema'])
        selection.setdefault('stages',{})[channel]=identifier
        histories=selection.setdefault('history',{}).setdefault(channel,[])
        if rollback:histories.pop()
        elif previous_id:histories.append(previous_id)
        active.setdefault('tenants',{})[tenant_home]=selection
        _atomic(active_path,active)
        operation['status']='selected';_atomic(root/'operation.json',operation)
        return operation


def _future_private_writer(root,home,selection,active,channel):
    """Observe the exact active private launcher without taking its ownership."""
    from .build_channels import _process_start_ticks
    path=home/'.build-channel.lock'
    try:descriptor=os.open(path,os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
    except FileNotFoundError:return None,None
    try:
        metadata=os.fstat(descriptor)
        if metadata.st_uid!=os.getuid() or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode)!=0o600:
            raise UpgradeError('private launcher ownership metadata is not qualified')
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return None,None
        except BlockingIOError:pass
        record=json.loads(os.pread(descriptor,4096,0))
        pid=record.get('pid');sha=record.get('build_sha256')
        if type(pid) is not int or record.get('start_ticks')!=_process_start_ticks(pid) or not isinstance(sha,str) or re.fullmatch('[0-9a-f]{64}',sha) is None:
            raise UpgradeError('active legacy private launcher identity is unqualified; future selection held')
        identifiers=list(selection.get('history',{}).get(channel,[]))
        current=selection.get('stages',{}).get(channel,active.get('stages',{}).get(channel))
        if current:identifiers.append(current)
        for identifier in identifiers:
            receipt=_qualified(root,identifier)
            if receipt['build']['sha256']==sha:
                return receipt,dict(record,device=metadata.st_dev,inode=metadata.st_ino)
        raise UpgradeError('active private launcher build is absent from retained qualified catalog')
    finally:os.close(descriptor)


def _owned_private_native(process,receipt,owner):
    if receipt is None or owner is None:return False
    try:
        if Path(os.readlink(process/'exe')).resolve()!=Path(receipt['build']['executable']).resolve():return False
        # Inherited exact ownership descriptor, immutable build pin and living
        # launcher ancestry jointly prove this private instance. SHA alone does not.
        if not any((entry.stat().st_dev,entry.stat().st_ino)==(owner['device'],owner['inode']) for entry in (process/'fd').iterdir()):return False
        pid=int(process.name)
        for _ in range(64):
            if pid==owner['pid']:return True
            fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            parent=int(fields[1])
            if parent<=1 or parent==pid:return False
            pid=parent
    except (OSError,ValueError,IndexError):return False
    return False


def select_future(root:Path, home:Path, *, identifier=None, channel=None, rollback=False,
                  operation_id, expected_registry_sha256=None, guard=None):
    """Atomically select only future private launches; active clients are pinned.

    Caller owns admission authority. ``guard`` runs with the registry lock held
    and must not acquire locks ordered outside this registry (notably job locks).
    No home ownership lock, daemon operation or process signal is performed.
    """
    root=root.resolve();home=home.absolute();guard=guard or (lambda:None)
    _name(operation_id)
    if not home.is_dir() or home.is_symlink() or home.stat().st_uid!=os.getuid():
        raise UpgradeError('existing owned real tenant home required')
    with _locked(root):
        guard()
        if os.path.lexists(home/'packages/app-server-daemon/current') or os.path.lexists(home/'app-server-control/app-server-control.sock'):
            raise UpgradeError('existing managed account backend requires qualified cutover; #413/#380 remain held')
        active_path=root/'builds.json'
        raw=active_path.read_bytes() if active_path.exists() else None
        active=json.loads(raw) if raw else {'schema_version':1,'builds':{},'stages':{},'history':{}}
        if active.get('schema_version')!=1:raise UpgradeError('unknown active registry schema')
        tenant_home=str(home.resolve())
        selection=active.get('tenants',{}).get(tenant_home)
        if selection is None:
            selection=dict(builds={},stages={},history={key:list(value) for key,value in active.get('history',{}).items()})
        channel=channel or 'modded'
        if channel not in ('stock','modded'):raise UpgradeError('unknown build channel')
        marker=selection.get('future_operations',{}).get(channel)
        if marker==operation_id:
            selected=selection.get('stages',{}).get(channel)
            if identifier is not None and selected!=identifier:raise UpgradeError('future selection operation identity changed')
            receipt=_qualified(root,selected)
            return dict(status='already_selected',id=selected,channel=channel,operation_id=operation_id,
                        tenant_home=tenant_home,build_sha256=receipt['build']['sha256'])
        actual=hashlib.sha256(raw).hexdigest() if raw is not None else 'absent'
        if expected_registry_sha256 is not None and expected_registry_sha256!=actual:
            raise UpgradeError('future registry selection changed during preparation')
        if rollback:
            history=selection.get('history',{}).get(channel,[])
            if not history:raise UpgradeError('no qualified rollback retained')
            identifier=history[-1]
        receipt=_qualified(root,identifier)
        if receipt['channel']!=channel:raise UpgradeError('candidate channel differs from requested future scope')
        # Validate exactly the registration future launchers will read before
        # publishing it, including channel provenance and metadata constraints.
        from .build_channels import load_build
        registration=root/'stages'/identifier/'future-build.json'
        _atomic(registration,dict(schema_version=1,builds={channel:receipt['build']}))
        load_build(registration,channel,home)
        current=selection.get('builds',{}).get(channel,active.get('builds',{}).get(channel))
        previous_id=selection.get('stages',{}).get(channel,active.get('stages',{}).get(channel))
        previous=_qualified(root,previous_id) if previous_id else None
        if current and current.get('backend','private')!='private':
            raise UpgradeError('managed backend cutover is not qualified; #413/#380 remain held')
        if receipt['build'].get('backend','private')!='private':
            raise UpgradeError('managed candidate requires separately qualified daemon cutover')
        reads=receipt.get('read_schemas');write=receipt.get('write_schema')
        if not isinstance(reads,list) or not reads or any(type(v) is not int or v<1 for v in reads) or type(write) is not int or write not in reads:
            raise UpgradeError('explicit candidate history read/write compatibility required')
        observed=_schemas(home)
        if not observed.issubset(reads):raise UpgradeError('candidate cannot read current tenant schemas')
        if current:
            old_reads=(previous or current).get('read_schemas')
            old_write=(previous or current).get('write_schema')
            if not isinstance(old_reads,list) or type(old_write) is not int:
                raise UpgradeError('existing build history read/write compatibility is unqualified')
            if write not in old_reads or old_write not in reads or not observed.issubset(old_reads):
                raise UpgradeError('future selection or rollback is incompatible with pinned existing sessions')
        writer,ownership=_future_private_writer(root,home,selection,active,channel)
        if writer is not None and (write not in writer['read_schemas'] or writer['write_schema'] not in reads):
            raise UpgradeError('candidate is incompatible with an older still-pinned private writer')
        _hold_unmanaged_native(home,allow_private=lambda process:_owned_private_native(process,writer,ownership))
        operation=dict(schema_version=1,operation='future_rollback' if rollback else 'future_activate',
            operation_id=operation_id,id=identifier,previous_id=previous_id,channel=channel,
            tenant_home=tenant_home,status='prepared',registry_before_sha256=actual,
            observed_schemas=sorted(observed),build_sha256=receipt['build']['sha256'],at=time.time())
        _atomic(root/'future-operation.json',operation)
        selection.setdefault('builds',{})[channel]=dict(receipt['build'],tenant_home=tenant_home,
            read_schemas=reads,write_schema=write,backend='private')
        selection.setdefault('stages',{})[channel]=identifier
        history=selection.setdefault('history',{}).setdefault(channel,[])
        if rollback:history.pop()
        elif previous_id and previous_id!=identifier:history.append(previous_id)
        selection.setdefault('future_operations',{})[channel]=operation_id
        active.setdefault('tenants',{})[tenant_home]=selection
        guard()
        _atomic(active_path,active)
        operation['status']='selected';_atomic(root/'future-operation.json',operation)
        return operation


def check(root:Path, release_json:Path|None=None, *, ttl=21600):
    """Refresh official release metadata at most once per cache interval."""
    root=root.resolve()
    with _locked(root,blocking=False) as acquired:
        if not acquired:return {'status':'deferred','reason':'upgrade_store_busy','activated':False}
        path=root/'release-check.json'
        origin='fixture:'+str(release_json.resolve()) if release_json else 'https://api.github.com/repos/openai/codex/releases/latest'
        previous=_json(path) if path.exists() else None
        if previous and previous.get('origin')==origin and 0<=time.time()-previous.get('checked_at',0)<ttl:
            return dict(previous,cached=True)
        try:
            if release_json:release=_json(release_json)
            else:
                request=Request(origin,headers={'Accept':'application/vnd.github+json','User-Agent':'codex-profiles'})
                with urlopen(request,timeout=5) as response:
                    release=json.loads(response.read(2_000_000))
            tag=release.get('tag_name','')
            if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'(?:rust-)?v?\d+\.\d+\.\d+',tag):
                raise UpgradeError('stable upstream release metadata required')
            if not release.get('html_url','').startswith('https://github.com/openai/codex/releases/tag/'):
                raise UpgradeError('unexpected upstream release provenance')
            latest=re.sub(r'^(?:rust-)?v?','',tag)
            selected=_json(root/'builds.json').get('builds',{}) if (root/'builds.json').exists() else {}
            if (root/'builds.json').exists():
                for home, selection in _json(root/'builds.json').get('tenants',{}).items():
                    for channel, build in selection.get('builds',{}).items():
                        selected[str(home)+'::'+channel]=build
            version=lambda v:tuple(int(x) for x in v.split('.')) if re.fullmatch(r'\d+\.\d+\.\d+',v) else None
            lag={channel:(version(build.get('upstream_version','')) or (0,))<version(latest) for channel,build in selected.items()}
            result={'schema_version':1,'status':'available','origin':origin,'checked_at':time.time(),'latest_version':latest,'release_url':release['html_url'],'lag':lag,'cached':False,'activated':False}
        except (OSError,ValueError,KeyError) as error:
            result={'schema_version':1,'status':'unavailable','origin':origin,'checked_at':time.time(),'reason':str(error),'activated':False}
        _atomic(path,result)
        return result


def schedule_check(root:Path, release_json:Path|None=None):
    """Schedule one bounded metadata job, visibly deferring during staging."""
    root=Path(root).resolve()
    origin='fixture:'+str(release_json.resolve()) if release_json else 'https://api.github.com/repos/openai/codex/releases/latest'
    with _locked(root,blocking=False) as acquired:
        if not acquired:return {'status':'deferred','reason':'upgrade_store_busy'}
        cache=root/'release-check.json'
        if cache.exists():
            try:
                previous=_json(cache)
                if previous.get('origin')==origin and 0<=time.time()-previous.get('checked_at',0)<21600:
                    return {'status':'cached','release':previous}
            except (OSError,ValueError):pass
        job=os.open(root/'.release-check-job.lock',os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            fcntl.flock(job,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(job)
            return {'status':'checking','deduplicated':True}
    try:
        command=[sys.executable,'-c','import runpy,signal; signal.alarm(15); runpy.run_module("codex_profiles.upgrades",run_name="__main__")','check','--root',str(root)]
        if release_json:command+=['--release-json',str(release_json.resolve())]
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1])+os.pathsep+os.environ.get('PYTHONPATH',''))
        process=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(job,))
    except OSError:
        os.close(job)
        raise

    def reap():
        try:
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()
        finally:os.close(job)
    threading.Thread(target=reap,name='codex-release-check',daemon=True).start()
    return {'status':'checking','pid':process.pid,'deadline_seconds':15}


def archive(root:Path, identifier:str, destination:Path, storage_proof:Path):
    """Copy inactive bytes to an attested HDD; never delete the staged source."""
    root=root.resolve()
    destination=destination.resolve(strict=True)
    info=storage_proof.stat()
    if info.st_uid!=os.getuid() or info.st_mode & 0o022:
        raise UpgradeError('storage attestation must be host-owned and not writable by others')
    proof=_json(storage_proof)
    if (proof.get('schema_version')!=1 or proof.get('media_type')!='hdd'
            or proof.get('source')!='host-volume-attestation'
            or proof.get('destination')!=str(destination)
            or proof.get('device')!=destination.stat().st_dev
            or not 0<=time.time()-proof.get('verified_at',0)<86400):
        raise UpgradeError('fresh verified HDD destination attestation required')
    with _locked(root):
        receipt=_qualified(root,identifier)
        active=_json(root/'builds.json') if (root/'builds.json').exists() else {}
        selections=[active,*active.get('tenants',{}).values()]
        if any(identifier in selection.get('stages',{}).values() for selection in selections):
            raise UpgradeError('active package cannot be archived')
        stage_dir=(root/'stages'/identifier).resolve()
        if destination.is_relative_to(stage_dir):raise UpgradeError('archive destination is inside source stage')
        payload=destination/(identifier+'.tar.gz')
        if payload.exists():raise UpgradeError('archive already exists; reconcile before retry')
        descriptor,temp=tempfile.mkstemp(prefix='.'+identifier+'-',suffix='.tar.gz',dir=destination);os.close(descriptor)
        try:
            with tarfile.open(temp,'w:gz') as tar:
                tar.add(stage_dir/'receipt.json',arcname=identifier+'/receipt.json')
                tar.add(stage_dir/'package',arcname=identifier+'/package')
            digest=hashlib.sha256(Path(temp).read_bytes()).hexdigest()
            # Reconcile source after capture; do not label a mixed snapshot accepted.
            if _package(stage_dir/'package')!=receipt['files']:raise UpgradeError('source changed during archive')
            os.rename(temp,payload)
            result={'schema_version':1,'status':'archived_copy','id':identifier,'archive':str(payload),'sha256':digest,'files':receipt['files'],'source_preserved':True,'storage_proof_sha256':hashlib.sha256(storage_proof.read_bytes()).hexdigest()}
            _atomic(Path(str(payload)+'.json'),result)
            return result
        finally:
            if Path(temp).exists():Path(temp).unlink()


def restore(payload:Path,destination:Path):
    receipt=_json(Path(str(payload)+'.json'))
    if hashlib.sha256(payload.read_bytes()).hexdigest()!=receipt.get('sha256'):
        raise UpgradeError('archive checksum mismatch')
    identifier=_name(receipt['id'])
    if destination.exists():raise UpgradeError('restore destination must be new')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix='.restore-',dir=destination.parent))
    try:
        with tarfile.open(payload,'r:gz') as tar:
            for member in tar:
                relative=Path(member.name)
                if not relative.parts or relative.is_absolute() or '..' in relative.parts or relative.parts[0]!=identifier:
                    raise UpgradeError('archive path escapes stage')
                target=temporary/relative
                if member.isdir():target.mkdir(parents=True,exist_ok=True,mode=0o700)
                elif member.isfile():
                    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    with tar.extractfile(member) as source, target.open('xb') as out:shutil.copyfileobj(source,out)
                    target.chmod(member.mode & 0o777)
                else:raise UpgradeError('archive links and special files unsupported')
        files=_package(temporary/identifier/'package')
        if files!=receipt.get('files'):raise UpgradeError('restored package differs from qualified archive')
        stage_receipt=_json(temporary/identifier/'receipt.json')
        if stage_receipt.get('files')!=files or stage_receipt.get('status')!='staged':raise UpgradeError('restored qualification receipt mismatched')
        os.rename(temporary,destination)
        return {'status':'restored_verified','id':identifier,'destination':str(destination),'files':files}
    finally:
        if temporary.exists():shutil.rmtree(temporary)


def cache(root:Path, budget_bytes:int=268435456, *, prune=False):
    root=root.resolve()
    if budget_bytes<0:raise UpgradeError('cache budget must not be negative')
    with _locked(root):
        candidates=[]
        for directory in sorted((root/'stages').glob('*')):
            receipt_path=directory/'receipt.json'
            if not receipt_path.is_file():continue
            receipt=_json(receipt_path)
            if receipt.get('status')!='failed':continue
            for name in ['work','package','unpacked-source']:
                work=directory/name
                if not work.is_dir() or work.is_symlink():continue
                files=_files(work);size=sum((work/item).stat().st_size for item in files)
                candidates.append({'path':str(work),'logical_bytes':size,'created_at':receipt.get('created_at',0)})
        candidates.sort(key=lambda r:r['created_at'])
        total=sum(row['logical_bytes'] for row in candidates);removed=[]
        if prune:
            for row in candidates:
                if total<=budget_bytes:break
                shutil.rmtree(row['path']);total-=row['logical_bytes'];removed.append(row['path'])
        return {'status':'cache_pruned' if prune else 'cache_preview','budget_bytes':budget_bytes,'remaining_logical_bytes':total,'removed':removed,'candidates':candidates,'retained':'qualified packages, active registry, archives and terminal receipts'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('stage');p.add_argument('--root',type=Path,required=True);p.add_argument('--recipe',type=Path,required=True)
    for action in ['activate','rollback']:
        p=commands.add_parser(action);p.add_argument('--root',type=Path,required=True);p.add_argument('--home',type=Path,required=True)
        if action=='activate':p.add_argument('--stage',required=True)
        else:p.add_argument('--channel',choices=['stock','modded'],default='modded')
    p=commands.add_parser('check');p.add_argument('--root',type=Path,required=True);p.add_argument('--release-json',type=Path)
    p=commands.add_parser('archive');p.add_argument('--root',type=Path,required=True);p.add_argument('--stage',required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--storage-proof',type=Path,required=True)
    p=commands.add_parser('restore');p.add_argument('--archive',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    p=commands.add_parser('cache');p.add_argument('--root',type=Path,required=True);p.add_argument('--budget-bytes',type=int,default=268435456);p.add_argument('--prune',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='stage':
            result=stage(args.root,args.recipe)
        elif args.command=='check':
            result=check(args.root,args.release_json)
        elif args.command=='archive':
            result=archive(args.root,args.stage,args.destination,args.storage_proof)
        elif args.command=='restore':
            result=restore(args.archive,args.destination)
        elif args.command=='cache':
            result=cache(args.root,args.budget_bytes,prune=args.prune)
        else:
            result=select(args.root,args.home,identifier=getattr(args,'stage',None),channel=getattr(args,'channel',None),rollback=args.command=='rollback')
        print(json.dumps(result));return 2 if result['status']=='failed' else 0
    except (OSError,ValueError,KeyError) as error:
        print(json.dumps({'status':'held','reason':str(error)}));return 2


if __name__=='__main__':raise SystemExit(main())
