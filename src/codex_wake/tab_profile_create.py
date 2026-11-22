"""Finite selected-profile terminal creation through existing build custody.

ControllerRuntime is the sole operation journal. Private launch manifests and
wrapper birth markers only bind the returned pane to its owned native child;
these files never admit a retry or contain credentials, prompts or transcripts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import tomllib
import uuid

from codex_profiles.build_channels import BuildError,load_build,run_build,validate_history
from .controller_accounts import ControllerAccounts,launch_overrides
from .managed_inventory import InventoryError
from .process import process_identity
from .shortcut_store import read,write


def _hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _foreground_role(pid,wrapper,selected):
    """Recognize only run_build's direct, pinned foreground-client invocation.

    Same-image app-server helpers are never client evidence. Command arguments
    stay inside this bounded local check; the public witness contains no argv.
    """
    base=Path('/proc')/str(pid)
    status=base.joinpath('status').read_text()
    parent=next(line.split()[1] for line in status.splitlines() if line.startswith('PPid:'))
    if int(parent)!=wrapper['pid']:return None
    raw=base.joinpath('cmdline').read_bytes()
    if not raw or len(raw)>65536:return None
    argv=raw.rstrip(b'\0').decode().split('\0')
    import re
    if not re.fullmatch(r'/proc/self/fd/[0-9]+',argv[0]):return None
    backend=selected['target']['backend']
    if backend=='private':
        if argv[1:2]!=['--no-daemon']:return None
        tail=argv[2:]
    elif backend=='managed':
        if len(argv)<3 or argv[1]!='--remote':return None
        # The existing launch owner qualifies this exact private account socket.
        endpoint=Path(selected['target']['home'])/'app-server-control/app-server-control.sock'
        if argv[2]!='unix://'+str(endpoint.resolve(strict=True)):return None
        tail=argv[3:]
    else:return None
    if tail not in (selected['args'],['-c','tui.terminal_title=[]',*selected['args']]):return None
    if process_identity(wrapper['pid'])!={k:v for k,v in wrapper.items() if k!='pid'}:return None
    return dict(role='foreground_tui_client',source='exact_run_build_direct_child_invocation',
                wrapper_process=wrapper,backend=backend)


class TabProfileCreate:
    def __init__(self,root,*,host,environment,channel='modded',python=None):
        self.root=Path(root)
        self.host,self.environment=host,environment
        self.channel=channel
        self.python=python or sys.executable

    def authorization_target(self,profile):
        accounts=ControllerAccounts(self.root/"controller-accounts.toml",host=self.host,environment=self.environment)
        return accounts.execute("accounts.resolve",{"selector":profile})["account"]["target"]

    def selection(self,profile):
        """Resolve only an enabled existing account selector and pinned build."""
        accounts=ControllerAccounts(self.root/'controller-accounts.toml',host=self.host,environment=self.environment)
        account=accounts.execute('accounts.resolve',{'selector':profile})['account']
        if account.get('kind')=='stock' or account.get('independent') is False:
            raise InventoryError('unsupported_target','selected profile requires an independent Wake account')
        from .controller_registry import resolve_registry
        registry=resolve_registry(accounts.path,host=self.host,environment=self.environment)
        try:
            data=tomllib.loads(registry.read_text());manifest=Path(data['builds']['manifest'])
            if not manifest.is_absolute():raise ValueError()
            home=Path(account['home']);build=load_build(manifest,self.channel,home)
            validate_history(build,home)
            if _hash(build.executable)!=build.sha256:
                raise InventoryError('stale_target','registered executable bytes changed')
            view=accounts.execute('configuration.explain',dict(selector=account['id'],expected_target=account['target']))
            # Existing configuration owner alone materializes scoped overrides.
            args=launch_overrides(view)
            target=dict(account['target'],build_channel=build.channel,build_sha256=build.sha256,
                        build_revision=build.revision,executable=str(build.executable),backend=build.backend)
            return dict(target=target,profile=account['id'],manifest=str(manifest),args=args)
        except InventoryError:raise
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise InventoryError('profile_launch_held','selected profile/build is unavailable or incompatible') from error

    def create(self,profile,*,transport,name,cwd,deadline,guard,preview=False,placement=None):
        if not hasattr(transport,'socket') or not hasattr(transport,'command'):
            return dict(status='unsupported',reason='selected_profile_creation_unqualified_for_backend')
        selected=self.selection(profile)
        if not Path(cwd).is_absolute() or not Path(cwd).is_dir():
            raise InventoryError('invalid_argument','profile working directory must exist and be absolute')
        if preview:return dict(status='preview',profile=selected['profile'],profile_target=selected['target'])
        if time.monotonic()>=deadline:raise InventoryError('deadline','profile create deadline elapsed before submission')
        directory=self.root/'tab-profile-launches';directory.mkdir(mode=0o700,exist_ok=True)
        intent=uuid.uuid4().hex;manifest=directory/(intent+'.json');marker=directory/(intent+'.process.json')
        record=dict(version=1,root=str(self.root),host=self.host,environment=self.environment,channel=self.channel,
                    selection=selected,marker=str(marker),uid=os.getuid())
        write(manifest,record);sha=_hash(manifest)
        # This fixed host package loader works from any chosen tab cwd. Neither
        # Python source nor native argv can be supplied by the caller.
        loader='import sys;sys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]))+');from codex_wake.tab_profile_create import main;main()'
        command=shlex.join([self.python,'-c',loader,'--manifest',str(manifest),'--sha256',sha])
        guard()
        if self.selection(profile)!=selected:
            raise InventoryError('stale_target','profile/account/build changed before launch')
        try:
            flags = [placement[0], '-t', transport.session + ':' + placement[1]] if placement else ['-t', transport.session + ':']
            rendered=transport.command(deadline,'new-window','-d','-P','-F','#{window_id}\t#{pane_id}',
                                       *flags,'-n',name,'-c',cwd,command)
            wid,pane=rendered.strip().split('\t')
        except (OSError,ValueError,subprocess.SubprocessError) as error:
            return dict(status='uncertain',reason='profile_window_submission_outcome_unknown',
                        profile_target=selected['target'],intent=intent)
        result=dict(profile=selected['profile'],profile_target=selected['target'],intent=intent)
        while time.monotonic()<deadline:
            try:
                state=read(marker)
                if state.get('status') in ('held','exited'):
                    return dict(result,status='held',reason=state.get('reason','selected_profile_exited_before_verification'),exit_code=state.get('exit_code'))
                snapshot=transport.snapshot(deadline)
                window=next(w for w in snapshot['windows'] if w['window_id']==wid)
                result['window']=window
                wrapper=state['process'];actual=process_identity(wrapper['pid'])
                if actual!={k:v for k,v in wrapper.items() if k!='pid'}:
                    raise InventoryError('stale_target','selected profile wrapper generation changed')
                from .tab_traits import _processes
                rows,complete=_processes(window['panes'][0]['pid'],deadline)
                if not complete:continue
                if not any(r['pid']==wrapper['pid'] for r in rows):
                    raise InventoryError('stale_target','launch wrapper is not owned by destination pane')
                for row in rows:
                    pid=row['pid']
                    if pid==wrapper['pid']:continue
                    if row['executable']!=str(Path(selected['target']['executable']).resolve()):continue
                    role=_foreground_role(pid,wrapper,selected)
                    if role is None:continue
                    env=Path('/proc',str(pid),'environ').read_bytes().split(b'\0')
                    required=[('CODEX_HOME='+selected['target']['home']).encode(),('CODEX_PROFILE_NAME='+selected['profile']).encode(),
                              ('CODEX_BUILD_CHANNEL='+self.channel).encode()]
                    if not all(value in env for value in required):continue
                    generation=process_identity(pid)
                    if not generation or _hash(Path('/proc',str(pid),'exe'))!=selected['target']['build_sha256']:continue
                    if generation!=process_identity(pid) or _foreground_role(pid,wrapper,selected)!=role:continue
                    return dict(result,status='applied',process=dict(pid=pid,**generation),foreground=role,
                                account_identity='selected_home_verified_remote_identity_unverified')
            except FileNotFoundError:pass
            except (OSError,ValueError,KeyError,StopIteration,subprocess.SubprocessError):
                pass
            time.sleep(min(.05,max(0,deadline-time.monotonic())))
        return dict(result,status='uncertain',reason='selected_profile_child_not_verified')


def launch_child(manifest,sha):
    path=Path(manifest);info=path.lstat()
    if path.is_symlink() or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>1048576 or _hash(path)!=sha:
        raise InventoryError('unauthorized_target','private exact launch manifest required')
    record=read(path)
    if record['uid']!=os.getuid():raise InventoryError('unauthorized_target','launch execution owner changed')
    owner=TabProfileCreate(record['root'],host=record['host'],environment=record['environment'],channel=record['channel'])
    marker=Path(record['marker']);generation=process_identity(os.getpid())
    write(marker,dict(status='launching',process=dict(pid=os.getpid(),**generation)))
    try:
        selected=owner.selection(record['selection']['profile'])
        if selected!=record['selection']:raise InventoryError('stale_target','selected profile/account/build changed before launch')
    except (OSError,ValueError,KeyError,TypeError) as error:
        write(marker,dict(status='held',reason=getattr(error,'code','profile_launch_held'),exit_code=2))
        return 2
    for key in ('CODEX_THREAD_ID','CODEX_SESSION_ID','CODEX_WAKE_ATTACHMENT_ID'):
        os.environ.pop(key,None)
    try:
        build=load_build(Path(selected['manifest']),record['channel'],Path(selected['target']['home']))
        code=run_build(build,Path(selected['target']['home']),selected['profile'],selected['args'])
    except (BuildError,OSError,ValueError):code=2
    write(marker,dict(status='exited',exit_code=code))
    return code


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True);parser.add_argument('--sha256',required=True)
    args=parser.parse_args()
    raise SystemExit(launch_child(args.manifest,args.sha256))
