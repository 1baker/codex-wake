"""Dedicated-account native Codex adapter for upgrade coding and review roles.

Host-owned configuration chooses a pinned native executable and an existing
account strictly inside a designated disposable test root. Credentials are never
read or copied by this adapter. It launches fresh ephemeral native contexts,
keeps review read-only, validates the final structured response, and records the
actual binary/account/role boundary separately from behavioral qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import sys

from codex_profiles.build_channels import Build, _home_ownership, _pinned_executable
from codex_profiles.upgrades import _atomic
from .upgrade_repair import _identities, _inventory


class CodexAdapterHeld(ValueError):
    """The configured coding/review process did not establish a valid result."""


def _text(value,name,*,maximum=4096):
    if not isinstance(value,str) or not value or len(value)>maximum or any(ord(c)<32 for c in value):
        raise CodexAdapterHeld('invalid '+name)
    return value


def _read(path):
    if path.stat().st_size>1024**2:
        raise CodexAdapterHeld('JSON input exceeds one MiB')
    return json.loads(path.read_text())


def _configuration(path,role):
    if path.is_symlink():
        raise CodexAdapterHeld('host configuration must be a private regular file')
    metadata=path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.getuid() or metadata.st_mode&0o077:
        raise CodexAdapterHeld('host configuration must be a private owned regular file')
    config=_read(path)
    if config.get('schema_version')!=1 or role not in ('worker','reviewer') or config.get('role')!=role:
        raise CodexAdapterHeld('configured coding role differs')
    _text(config.get('identity'),'role identity',maximum=200)
    root=Path(_text(config.get('test_root'),'designated test root'))
    home=Path(_text(config.get('codex_home'),'dedicated Codex home'))
    executable=Path(_text(config.get('executable'),'native executable'))
    if not root.is_absolute() or not home.is_absolute() or not executable.is_absolute():
        raise CodexAdapterHeld('test root, account and executable must be absolute')
    if root.is_symlink() or home.is_symlink():
        raise CodexAdapterHeld('test root and dedicated account must be real directories')
    root=root.resolve(strict=True);home=home.resolve(strict=True)
    if not root.is_dir() or not home.is_dir() or root==home or not home.is_relative_to(root):
        raise CodexAdapterHeld('dedicated account must be strictly inside the designated test root')
    if root==Path('/') or root==Path.home().resolve() or root.stat().st_uid!=os.getuid() or home.stat().st_uid!=os.getuid():
        raise CodexAdapterHeld('designated test root/account ownership unavailable')
    if root.stat().st_mode&0o022 or home.stat().st_mode&0o022:
        raise CodexAdapterHeld('test account or test root is writable by another principal')
    if not re.fullmatch('[a-f0-9]{64}',config.get('sha256','')):
        raise CodexAdapterHeld('explicit executable SHA256 required')
    timeout=config.get('timeout_seconds',600)
    if type(timeout) is not int or not 1<=timeout<=7200:
        raise CodexAdapterHeld('native timeout must be between one second and two hours')
    if 'model' in config:_text(config['model'],'model',maximum=200)
    config.update(test_root=str(root),codex_home=str(home),executable=str(executable),timeout_seconds=timeout)
    return config


def _packet(path,role):
    packet=_read(path)
    if packet.get('schema_version')!=1 or packet.get('role')!=role:
        raise CodexAdapterHeld('packet role or version differs')
    _text(packet.get('job_id'),'job identity',maximum=200)
    workspace=Path(_text(packet.get('workspace'),'workspace'))
    if not workspace.is_absolute() or workspace.is_symlink() or not workspace.is_dir():
        raise CodexAdapterHeld('absolute existing source workspace required')
    for key in ('candidate_digest','tests_digest'):
        if not re.fullmatch('[a-f0-9]{64}',packet.get(key,'')):
            raise CodexAdapterHeld('packet content identity required')
    capabilities=packet.get('required_capabilities')
    patches=packet.get('patches')
    if not isinstance(capabilities,list) or not capabilities or len(capabilities)>64 or len(set(capabilities))!=len(capabilities):
        raise CodexAdapterHeld('explicit unique required capabilities required')
    for value in capabilities:_text(value,'required capability',maximum=200)
    if not isinstance(patches,list) or len(patches)>128:
        raise CodexAdapterHeld('bounded pinned patch intents required')
    ids=[]
    for patch in patches:
        ids.append(_text(patch.get('id'),'patch identity',maximum=200))
        _text(patch.get('intent'),'patch intent')
        _text(patch.get('path'),'patch input path')
        if not re.fullmatch('[a-f0-9]{64}',patch.get('sha256','')):
            raise CodexAdapterHeld('patch content identity required')
    if len(ids)!=len(set(ids)):
        raise CodexAdapterHeld('patch identities must be unique')
    actual=_identities(_inventory(workspace.resolve()))
    if actual!=(packet['candidate_digest'],packet['tests_digest']):
        raise CodexAdapterHeld('source changed before coding role started')
    return packet


def output_schema(role,identity,packet):
    """Generate a fixed-key native structured-output contract for this packet."""
    string=dict(type='string')
    evidence=dict(type='string',minLength=1)
    def mapping(properties):
        return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
    patch_ids=[p['id'] for p in packet['patches']]
    properties=dict(schema_version=dict(type='integer',const=1),
        status=dict(type='string',enum=['repaired'] if role=='worker' else ['approved','rejected']),
        candidate_digest=dict(type='string',**({'const':packet['candidate_digest']} if role=='reviewer' else {})),
        tests_digest=dict(type='string',**({'const':packet['tests_digest']} if role=='reviewer' else {})),
        capabilities=mapping({name:evidence for name in packet['required_capabilities']}),
        retirements=mapping({name:string for name in patch_ids}))
    if role=='worker':
        properties['identity']=dict(type='string',const=identity)
        disposition=mapping(dict(disposition=dict(type='string',enum=['applied','rewritten','retired']),evidence=evidence))
        properties['patch_dispositions']=mapping({name:disposition for name in patch_ids})
    else:
        properties['reviewer']=dict(type='string',const=identity)
        properties['findings']=dict(type='array',items=string)
        if packet.get('require_patch_dispositions') is True:
            properties['patch_dispositions']=mapping({patch['id']:mapping(dict(
                disposition=dict(type='string',enum=['applied','rewritten','retired']),
                intent=dict(type='string',const=patch['intent']),evidence=evidence,equivalence=string)) for patch in packet['patches']})
    return mapping(properties)


def _validate(value,schema):
    """Validate the exact generated contract without a runtime SDK dependency."""
    if not isinstance(value,dict) or set(value)!=set(schema['properties']):
        raise CodexAdapterHeld('native final response fields differ from the role contract')
    def check(item,shape):
        kind=shape.get('type')
        if kind=='object':
            if not isinstance(item,dict) or set(item)!=set(shape['properties']):return False
            return all(check(item[k],v) for k,v in shape['properties'].items())
        if kind=='string' and (not isinstance(item,str) or len(item)<shape.get('minLength',0)):return False
        if kind=='integer' and type(item) is not int:return False
        if kind=='array' and (not isinstance(item,list) or any(not check(x,shape['items']) for x in item)):return False
        if 'const' in shape and item!=shape['const']:return False
        if 'enum' in shape and item not in shape['enum']:return False
        return True
    if not check(value,schema):
        raise CodexAdapterHeld('native final response failed structured role validation')


NONRETRYABLE_REASONS=frozenset(('authentication_needed','coding_capacity_unavailable',
    'configuration_unavailable','native_coding_failed'))


def _native_failure(events,errors):
    def tail(path):
        with path.open('rb') as stream:
            stream.seek(0,2);stream.seek(max(0,stream.tell()-65536))
            return stream.read(65536).decode('utf-8',errors='replace')
    messages=[]
    for line in tail(events).splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if not isinstance(value,dict):continue
        if value.get('type') in ('error','turn.failed') or isinstance(value.get('error'),dict):
            error=value.get('error',value)
            if isinstance(error,dict):
                messages.extend(str(error.get(k,'')) for k in ('code','type','message','status'))
    # Unstructured stderr is diagnostic only; recognize explicit native ERROR
    # records, never arbitrary model/user prose printed among JSON events.
    messages.extend(line for line in tail(errors).splitlines() if re.search(r'\bERROR\b',line))
    text='\n'.join(messages).lower()
    if re.search(r'\b401\b|authentication_error|not\s*logged\s*in|notloggedin',text):
        return 'authentication_needed'
    if re.search(r'usage[_ ]limit|quota|rate[_ ]limit',text):
        return 'coding_capacity_unavailable'
    return 'native_coding_failed'


def run(config_path,role,packet_path,response_path):
    """Run a host-configured source-maintenance role; never perform login."""
    config=_configuration(Path(config_path),role)
    packet=_packet(Path(packet_path),role)
    workspace=Path(packet['workspace']).resolve()
    home=Path(config['codex_home'])
    if workspace==home or workspace.is_relative_to(home) or home.is_relative_to(workspace):
        raise CodexAdapterHeld('candidate and authenticated account must remain separate')
    response=Path(response_path).absolute()
    if response==workspace or response.is_relative_to(workspace):
        raise CodexAdapterHeld('wrapper response must be outside candidate source')
    schema=output_schema(role,config['identity'],packet)
    response.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory=Path(tempfile.mkdtemp(prefix='codex-'+role+'-',dir=response.parent))
    schema_path=directory/'output-schema.json';_atomic(schema_path,schema)
    final=directory/'native-final.json';events=directory/'native-events.jsonl';errors=directory/'native-errors.log'
    role_instructions=(
        'You are the source repair worker. Inspect the pinned upstream source, ALL patch intents and current Git conflicts. '
        'Resolve by behavioral intent, preserve acceptance tests, regenerate applicable bindings/schema/lockfiles, and account for EVERY patch. '
        'A retired patch requires concrete equivalence evidence. Do not remove required capabilities or weaken tests.'
        if role=='worker' else
        'You are the independent read-only source reviewer, in a fresh context. Independently inspect the actual candidate, Git diff from HEAD, '
        'tests, patch intents, generated bindings/schema and lockfiles. Do not trust worker assertions as proof. '
        'Identify missing behavior or weakened tests. Supply evidence for every required capability and independently justify each retirement. '
        'Reject when preservation is unproved; do not edit source.')
    if role=='reviewer' and packet.get('require_patch_dispositions') is True:
        role_instructions+=' Independently disposition EVERY original patch using its exact intent plus source/test evidence; a retired patch needs equivalence evidence. Return patch_dispositions for every patch ID; equivalence may be empty only for non-retired patches.'
        if packet.get('interrupted_worker',{}).get('kind')=='interrupted_worker_no_completion_report':
            role_instructions+=' The original worker was interrupted without a completed report. Never claim the worker completed.'
    prompt=(role_instructions+'\nThis is upgrade source maintenance, not authenticated acceptance or a model-turn canary. '
        'Do not log in, copy/read credentials, use production state, enable a governor, renew resources, submit business work or activate a build. '
        'Return only the required final JSON. For non-retired patches use an empty retirement string.\n\nCanonical upgrade packet:\n'+json.dumps(packet,sort_keys=True))
    env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','CARGO_BUILD_JOBS','CARGO_TARGET_DIR')}
    ephemeral_home=directory/'home';ephemeral_home.mkdir(mode=0o700)
    env.update(HOME=str(ephemeral_home),CODEX_HOME=str(home),XDG_CONFIG_HOME=str(ephemeral_home/'.config'),XDG_DATA_HOME=str(ephemeral_home/'.local/share'))
    build=Build('modded',Path(config['executable']),config['sha256'],'host-configured','coding-adapter','host-authorized dedicated native coding account')
    process=None
    previous_handler=None
    def interrupted(signum,unused):
        raise InterruptedError('coding adapter interrupted')
    try:
        previous_handler=signal.signal(signal.SIGTERM,interrupted)
        with _home_ownership(home,channel='modded') as ownership,_pinned_executable(build) as executable:
            command=[f'/proc/self/fd/{executable}','--no-daemon','--ask-for-approval','never','exec',
                '--ephemeral','--ignore-user-config','--sandbox','workspace-write' if role=='worker' else 'read-only',
                '--cd',str(workspace),'--output-schema',str(schema_path),'--json','--color','never','--output-last-message',str(final)]
            if config.get('model'):command.extend(['--model',config['model']])
            command.append('-')
            with events.open('wb') as out,errors.open('wb') as err:
                process=subprocess.Popen(command,cwd=workspace,env=env,pass_fds=(executable,ownership),stdin=subprocess.PIPE,
                    stdout=out,stderr=err,text=True,start_new_session=True)
                process.communicate(prompt,timeout=config['timeout_seconds'])
                if process.returncode:
                    raise CodexAdapterHeld(_native_failure(events,errors))
        report=_read(final);_validate(report,schema)
        current=_identities(_inventory(workspace))
        if role=='reviewer' and current!=(packet['candidate_digest'],packet['tests_digest']):
            raise CodexAdapterHeld('read-only reviewer candidate changed')
        if role=='worker':report.update(candidate_digest=current[0],tests_digest=current[1])
        report['adapter_provenance']=dict(role=role,identity=config['identity'],executable_sha256=config['sha256'],
            codex_home=config['codex_home'],ephemeral=True,sandbox='workspace-write' if role=='worker' else 'read-only',
            events_sha256=hashlib.sha256(events.read_bytes()).hexdigest(),events=str(events),errors=str(errors),
            evidence_scope='native_source_maintenance_execution_not_installed_qualification')
        _atomic(response,report)
        return report
    finally:
        if process is not None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:pass
            finally:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()
        if previous_handler is not None:signal.signal(signal.SIGTERM,previous_handler)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--role',choices=('worker','reviewer'),required=True)
    args=parser.parse_args(argv)
    packet=os.environ.get('CODEX_UPGRADE_PACKET');response=os.environ.get('CODEX_UPGRADE_RESPONSE')
    if not packet or not response:parser.error('CODEX_UPGRADE_PACKET and CODEX_UPGRADE_RESPONSE are required')
    try:
        run(args.config,args.role,Path(packet),Path(response))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
        # Invalid source/output paths must not gain a write merely because an
        # error is being reported. The outer executor retains stderr and exit.
        reason=str(error) if str(error) in NONRETRYABLE_REASONS else 'configuration_unavailable'
        print(json.dumps(dict(schema_version=1,status='held',reason=reason,retryable=False)),file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':
    raise SystemExit(main())
