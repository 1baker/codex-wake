"""Explicitly approved shared-server MCP reload, without replacing conversations."""
from pathlib import Path
import math
from uuid import UUID

from .records import WakeError

MODE = 'shared_mcp_idle'
CLIENT_MODE = 'client_idle'
THREAD_MODE = 'thread_mcp_idle'
_stopping = False


def _effect_guard():
    if _stopping:
        raise WakeError('refresh controller is stopping')


def _managed_binding(profile):
    import os,socket,struct
    from websockets.sync.client import unix_connect
    from .shared_app_server import locate_shared_endpoint
    from .process import process_identity
    endpoint=locate_shared_endpoint(timeout=profile['timeout'],codex_cmd=profile['codex_path'],codex_home=profile['codex_home'])
    if endpoint!='unix://'+str(Path(profile['app_server'][7:]).resolve(strict=True)):
        raise WakeError('managed default daemon differs from approved endpoint')
    with unix_connect(endpoint[7:],open_timeout=profile['timeout'],close_timeout=1) as peer:
        pid,uid,_=struct.unpack('3i',peer.socket.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    if uid!=os.geteuid() or not process_identity(pid):
        raise WakeError('managed daemon peer unavailable')
    return dict(endpoint=endpoint,pid=pid,identity=process_identity(pid))


def _client_effect_guard(receipt):
    _effect_guard()
    if receipt['profile'].get('client_connection')=='managed_default':
        if _managed_binding(receipt['profile'])!=receipt.get('managed_client_binding'):
            raise WakeError('managed daemon generation changed')
    _effect_guard()


def configuration(config, profile_name, thread_id, caller_thread_id, *, _permission_checked=False):
    if _permission_checked:
        from .permission_migration import profile_ceiling
        profile_ceiling(config,profile_name,caller_thread_id)
    from . import __version__
    try:
        profile = config['profiles'][profile_name]
        if (config['version'] != 1 or profile['refresh_mode'] not in (MODE, CLIENT_MODE, THREAD_MODE)
                or not profile['scope_approval'] or str(UUID(thread_id)) != thread_id
                or caller_thread_id != thread_id
                or (not _permission_checked and profile_name not in config.get('callers',{}).get(caller_thread_id,[]))
                or not isinstance(profile['resources'], dict) or not profile['resources']):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise WakeError('shared refresh requires exact host caller and explicit scope approval') from None
    value=dict(version=__version__, profile=profile_name, thread_id=thread_id,
                refresh_scope={CLIENT_MODE:'single_client',MODE:'shared_server_mcp',THREAD_MODE:'current_connection'}[profile['refresh_mode']], idle_required=True,
                resources=sorted(profile['resources']), operations=['configuration', 'refresh'])
    if profile['refresh_mode']==THREAD_MODE:
        _validate_profile(profile)
        from .scoped_refresh import inspect_capability
        value.update(inspect_capability(profile,thread_id))
    return value


def _directory(root):
    from .goal_supervision import _private
    root = Path(root).absolute()
    if root != root.resolve():
        raise WakeError('shared refresh root must be canonical')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private(root, True)
    directory = root/'shared-refresh'
    directory.mkdir(exist_ok=True, mode=0o700)
    _private(directory, True)
    return directory


def _public(receipt):
    return {key: value for key, value in receipt.items()
            if key not in ('profile', 'policy_path', 'checkpoint_path', 'goals_before', 'last_busy_thread', 'permission_context', 'policy_root')}


def _validate_profile(profile):
    import math
    try:
        required={'refresh_mode', 'scope_approval', 'cwd', 'app_server', 'codex_path', 'timeout', 'resources'}
        client=profile.get('refresh_mode')==CLIENT_MODE
        if client:required.add('tmux_session')
        optional={'tmux_socket','codex_home','goal_supervision','client_connection'} if client else ({'goal_supervision'} if profile.get('refresh_mode')==THREAD_MODE else set())
        if (not required <= set(profile) or set(profile)-required-optional
                or profile['refresh_mode'] not in (MODE,CLIENT_MODE,THREAD_MODE) or not isinstance(profile['scope_approval'], str)
                or not profile['scope_approval'].strip()
                or not Path(profile['cwd']).is_absolute() or not Path(profile['cwd']).is_dir()
                or not Path(profile['codex_path']).is_absolute() or not Path(profile['codex_path']).is_file()
                or not profile['app_server'].startswith('unix:///')
                or type(profile['timeout']) not in (int, float)
                or not math.isfinite(profile['timeout']) or not 0 < profile['timeout'] <= 5
                or (client and (not isinstance(profile['tmux_session'],str) or not profile['tmux_session']))):
            raise ValueError
        if client and (profile.get('client_connection','existing_endpoint') not in ('managed_default','existing_endpoint')
                or (profile.get('client_connection')=='managed_default' and
                    (not Path(profile.get('codex_home','')).is_absolute() or not Path(profile['codex_home']).is_dir()))):
            raise ValueError
        for check in profile['resources'].values():
            if profile['refresh_mode']==THREAD_MODE and check.get('kind') not in ('mcp','mcp_catalog'):
                raise ValueError
            fields = ({'kind','server','version','tools'} if check['kind']=='mcp_catalog' else
                      {'kind', 'path', 'description', 'sha256'} if check['kind'] == 'skill' else
                      {'kind', 'server', 'tool', 'arguments', 'read_only', 'expected_content'})
            if set(check) != fields or check['kind'] not in ('skill', 'mcp','mcp_catalog'):
                raise ValueError
            if check['kind']=='mcp_catalog' and (not isinstance(check['version'],str)
                    or not check['version'] or not isinstance(check['tools'],dict)
                    or not check['tools'] or len(check['tools'])>32
                    or any(not isinstance(name,str) or not isinstance(names,list) or len(names)>64
                           or any(not isinstance(field,str) for field in names) for name,names in check['tools'].items())):
                raise ValueError
            if check['kind'] == 'mcp' and check['read_only'] is not True:
                raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise WakeError('shared refresh profile or read-only resource proof is invalid') from None


def command(args, root, config, profile, checkpoint, content, *, permission_context=None, emit_result=None):
    import hashlib
    import json
    from .goal_supervision import _heartbeat, _lock, _private, _save
    from .lifecycle_budget import trusted_upper
    from .process import boot_id_value
    from .records import parse_timestamp
    from .sessions_cli import emit
    if permission_context:
        from .permission_refresh import revalidate
        revalidate(root,permission_context)
    info=configuration(config, args.profile, args.thread_id, args.caller_thread_id, _permission_checked=bool(permission_context))
    if profile['refresh_mode']==THREAD_MODE and info.get('capability')!='supported':
        raise WakeError('native scoped MCP reload dependency unavailable')
    _validate_profile(profile)
    policy = Path(args.profiles).absolute()
    _private(policy)
    if policy != policy.resolve():
        raise WakeError('shared refresh policy must be canonical')
    if args.rollback:
        raise WakeError('shared MCP refresh never replaces a client; rollback is unavailable')
    body = json.loads(content)
    if (body.get('source_thread_id') != args.thread_id or body.get('pending_obligations') != []
            or any(not body.get(key) for key in ('objective', 'authority', 'next_packet'))):
        raise WakeError('source checkpoint must preserve work and account for obligations')
    if not args.intent or len(args.intent) > 200 or len(set(args.resource)) != len(args.resource):
        raise WakeError('shared refresh requires a bounded stable intent and unique resources')
    if not args.resource or any(name not in profile['resources'] for name in args.resource):
        raise WakeError('requested resources require host-approved proof checks')
    if profile.get('client_connection')=='managed_default':
        catalogs={name for name,check in profile['resources'].items() if check['kind']=='mcp_catalog'}
        if not catalogs or not catalogs<=set(args.resource):
            raise WakeError('managed client refresh requires its actual MCP catalog checks')
    directory = _directory(root)
    intent = dict(thread_id=args.thread_id, profile_name=args.profile, profile=profile,
                  policy_path=str(policy), checkpoint_path=str(checkpoint),
                  checkpoint_sha256=args.checkpoint_sha256, resources=args.resource,
                  expires_at=args.expires_at)
    if profile['refresh_mode']==CLIENT_MODE:
        from .lifecycle_budget import operation_binding
        intent['client_binding']=operation_binding(config,args,source_ref=args.thread_id,_permission_checked=bool(permission_context))
    fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
    name = hashlib.sha256(args.intent.encode()).hexdigest()
    path = directory/(name+'.json')
    with _lock(directory, name):
        if path.exists():
            _private(path)
            receipt = json.loads(path.read_text())
            if receipt['fingerprint'] != fingerprint:
                raise WakeError('intent already binds a different shared refresh')
        else:
            if not _heartbeat(directory).get('fresh'):
                raise WakeError('independent sessions refresh-watch controller required')
            upper = trusted_upper()
            deadline = parse_timestamp(args.expires_at).timestamp()
            if deadline <= upper:
                raise WakeError('shared refresh expiry reached')
            receipt = dict(intent, fingerprint=fingerprint, intent_key=args.intent,
                           refresh_scope=info['refresh_scope'], state='queued', reason='waiting_for_idle',
                           started_upper=upper, started_boottime=None, clock_basis='qualified_utc',
                           boot_id=boot_id_value(), deadline=deadline)
            if profile['refresh_mode']==THREAD_MODE:
                receipt['native_scope']=info['native_scope']
            if profile['refresh_mode']==CLIENT_MODE:
                from .lifecycle_budget import operation_binding
                receipt['intent']=dict(operation='refresh',source_thread_id=args.thread_id,
                    launch=profile,checkpoint=str(checkpoint),checkpoint_sha256=args.checkpoint_sha256,
                    resources=args.resource,expires_at=args.expires_at)
                binding=intent['client_binding']
                if binding:receipt['intent'].update(binding)
                if profile.get('client_connection')=='managed_default':
                    receipt['managed_client_binding']=_managed_binding(profile)
            if permission_context:
                receipt['permission_context']=permission_context
                receipt['policy_root']=str(Path(root).absolute())
            _save(path, receipt)
            if profile['refresh_mode']==CLIENT_MODE or (profile['refresh_mode']==THREAD_MODE and profile.get('goal_supervision')):
                from .refresh_goal import pause
                def request(method,params):
                    if profile['refresh_mode']==CLIENT_MODE:_client_effect_guard(receipt)
                    return _request(receipt,method,params)
                value=request('thread/read',dict(threadId=args.thread_id,includeTurns=False))['thread']
                if not _source_workspace(receipt,value):
                    receipt.update(state='blocked',reason='source_workspace_mismatch')
                else:
                    goal=request('thread/goal/get',dict(threadId=args.thread_id))['goal']
                    receipt['goal_before']=goal
                    if pause(path,receipt,profile,goal,request):
                        receipt.update(state='queued',reason='waiting_for_source_idle')
                _save(path,receipt)
        (emit_result or emit)(_public(receipt), args.as_json)
        return 0 if receipt['state'] in ('queued','prepared','stopping','starting','awaiting_preflight','restoring_goal','verifying','completed') else 5


def _remaining(receipt):
    from .process import boot_id_value
    from .lifecycle_budget import trusted_upper
    if boot_id_value() != receipt['boot_id']:
        raise WakeError('boot identity changed')
    if (receipt.get('clock_basis', 'qualified_utc') != 'qualified_utc'
            or any(type(receipt.get(key)) not in (int, float) or not math.isfinite(receipt[key])
                   for key in ('started_upper', 'deadline'))):
        raise WakeError('shared_refresh_clock_unqualified')
    try:
        return receipt['deadline'] - trusted_upper()
    except (ValueError, OSError):
        raise WakeError('shared_refresh_clock_unqualified') from None


def _request(receipt, method, params):
    if _stopping:
        raise WakeError('refresh controller is stopping')
    if receipt.get('permission_context'):
        from .permission_refresh import revalidate
        revalidate(Path(receipt['policy_root']),receipt['permission_context'])
    from .native_protocol import native_request
    remaining = _remaining(receipt)
    if remaining <= 0:
        raise TimeoutError('shared refresh expiry reached')
    profile = receipt['profile']
    return native_request(profile['app_server'], profile['codex_path'], method, params,
                          min(profile['timeout'], remaining))


def _continuity(before, after):
    if before is None or after is None:
        return before == after
    counters = {'tokensUsed', 'timeUsedSeconds', 'updatedAt'}
    return ({key: value for key, value in before.items() if key not in counters}
            == {key: value for key, value in after.items() if key not in counters}
            and all(type(before.get(key)) in (int, float) and type(after.get(key)) in (int, float)
                    and after[key] >= before[key] for key in counters))


def _source_workspace(receipt, value):
    try:
        cwd = value.get('cwd')
        return (value.get('id') == receipt['thread_id'] and isinstance(cwd, str)
                and Path(cwd).is_absolute()
                and Path(cwd).resolve(strict=True) == Path(receipt['profile']['cwd']).resolve(strict=True))
    except (OSError, ValueError, TypeError):
        return False


def _resources(receipt,*,request=None):
    import hashlib
    transport=request or (lambda method,params:_request(receipt,method,params))
    profile = receipt['profile']
    source = transport('thread/read', dict(threadId=receipt['thread_id'], includeTurns=False))['thread']
    if not _source_workspace(receipt, source):
        return None
    checks = {}
    catalog = None
    for name in receipt['resources']:
        check = profile['resources'][name]
        if check['kind'] == 'skill':
            if catalog is None:
                catalog = transport('skills/list', dict(cwds=[profile['cwd']], forceReload=True))['data']
            selected = [skill for row in catalog if row['cwd'] == profile['cwd'] and not row['errors']
                        for skill in row['skills'] if skill['path'] == check['path'] and skill['enabled']]
            ready = (len(selected) == 1 and selected[0]['description'] == check['description']
                     and hashlib.sha256(Path(check['path']).read_bytes()).hexdigest() == check['sha256'])
        elif check['kind']=='mcp_catalog':
            from .refresh_resources import catalog_ready
            ready=catalog_ready(check,transport,receipt['thread_id'],
                                runtime_only=profile.get('refresh_mode')==THREAD_MODE)
        else:
            result = transport('mcpServer/tool/call', dict(threadId=receipt['thread_id'],
                server=check['server'], tool=check['tool'], arguments=check['arguments']))
            ready = result.get('isError') is not True and result['content'] == check['expected_content']
        checks[name] = dict(state='ready' if ready else 'stale', kind=check['kind'])
    return checks


def _poll_one(path, receipt):
    import hashlib
    import json
    from .goal_supervision import _private, _save
    from .wake_control import paused
    if paused(path.parent.parent):
        receipt['reason'] = 'emergency_paused'
        return
    if _remaining(receipt) <= 0:
        receipt.update(state='expired', reason='expiry_reached')
        return
    policy = Path(receipt['policy_path'])
    _private(policy)
    config = json.loads(policy.read_text())
    context=receipt.get('permission_context')
    if context:
        from .permission_refresh import revalidate
        try:revalidate(path.parent.parent,context)
        except WakeError:
            receipt.update(state='blocked',reason='permission_revoked');return
    try:
        configuration(config, receipt['profile_name'], receipt['thread_id'], receipt['thread_id'], _permission_checked=bool(context))
    except WakeError as exc:
        receipt.update(state='blocked',reason=getattr(exc,'code','host_refresh_authority_changed'));return
    if config['profiles'][receipt['profile_name']] != receipt['profile']:
        receipt.update(state='blocked', reason='host_refresh_policy_changed')
        return
    if hashlib.sha256(Path(receipt['checkpoint_path']).read_bytes()).hexdigest() != receipt['checkpoint_sha256']:
        receipt.update(state='blocked', reason='source_checkpoint_changed')
        return
    if receipt['profile'].get('refresh_mode')==THREAD_MODE:
        from .scoped_refresh import poll_one
        poll_one(path,receipt)
        return
    if receipt['profile'].get('refresh_mode')==CLIENT_MODE:
        from .agent_refresh import preflight, advance_refresh
        from .lifecycle_budget import operation_binding
        from types import SimpleNamespace
        current_binding=operation_binding(config,SimpleNamespace(profile=receipt['profile_name'],
            caller_thread_id=receipt['thread_id']),source_ref=receipt['thread_id'],_permission_checked=bool(context))
        if current_binding!=receipt.get('client_binding'):
            receipt.update(state='blocked',reason='host_budget_policy_changed');return
        if receipt['state']=='pausing_goal':
            from .refresh_goal import continuous
            transition=receipt['operational_goal_pause']
            goal=_request(receipt,'thread/goal/get',dict(threadId=receipt['thread_id']))['goal']
            if not continuous(transition['original'],goal,'paused'):
                receipt.update(state='blocked',reason='refresh_goal_pause_unverified');return
            transition.update(state='acknowledged',paused=goal)
            receipt.update(state='prepared',goal_before=goal)
        if receipt['state'] in ('queued','prepared'):
            value=_request(receipt,'thread/read',dict(threadId=receipt['thread_id'],includeTurns=False))['thread']
            if not _source_workspace(receipt,value):
                receipt.update(state='blocked',reason='source_workspace_mismatch');return
            if value['status']['type']!='idle' or value['status'].get('activeFlags'):
                receipt.update(reason='waiting_for_source_idle',busy_count=1);return
            receipt.update(state='prepared',busy_count=0,reason=None)
            preflight(path,receipt,receipt['profile'],effect_guard=lambda:_client_effect_guard(receipt))
        if receipt['state'] in ('stopping','starting','awaiting_preflight','restoring_goal','uncertain'):
            advance_refresh(path,receipt,receipt['profile'],effect_guard=lambda:_client_effect_guard(receipt))
        return
    if receipt['state'] == 'queued':
        loaded = []
        cursor = None
        for page in range(4):
            params = dict(limit=100)
            if cursor:params['cursor'] = cursor
            result = _request(receipt, 'thread/loaded/list', params)
            loaded.extend(result['data']);cursor = result.get('nextCursor')
            if not cursor:break
        if cursor or len(loaded) > 256 or len(loaded) != len(set(loaded)):
            raise WakeError('loaded conversation inventory is incomplete')
        if receipt['thread_id'] not in loaded:
            raise WakeError('source conversation is not loaded')
        busy = 0
        order = list(dict.fromkeys([receipt['thread_id'], receipt.get('last_busy_thread'), *loaded]))
        for thread in (thread for thread in order if thread in loaded):
            value = _request(receipt, 'thread/read', dict(threadId=thread, includeTurns=False))['thread']
            if thread == receipt['thread_id'] and not _source_workspace(receipt, value):
                receipt.update(state='blocked', reason='source_workspace_mismatch')
                return
            if value['id'] != thread or value['status']['type'] not in ('idle', 'active'):
                raise WakeError('conversation state is unknown')
            if value['status']['type'] != 'idle' or value['status'].get('activeFlags'):
                busy = 1
                receipt['last_busy_thread'] = thread
                break
        receipt.update(loaded_count=len(loaded), busy_count=busy)
        if busy:
            receipt['reason'] = 'waiting_for_idle'
            return
        goals = {thread: _request(receipt, 'thread/goal/get', dict(threadId=thread))['goal'] for thread in loaded}
        # Recheck after goal observations; the native API supplies no atomic idle CAS.
        current_loaded = []
        cursor = None
        for page in range(4):
            params = dict(limit=100)
            if cursor:params['cursor'] = cursor
            current = _request(receipt, 'thread/loaded/list', params)
            current_loaded.extend(current['data']);cursor = current.get('nextCursor')
            if not cursor:break
        if cursor or set(current_loaded) != set(loaded) or len(current_loaded) != len(loaded):
            receipt['reason'] = 'inventory_changed_during_preflight'
            return
        for thread in loaded:
            value = _request(receipt, 'thread/read', dict(threadId=thread, includeTurns=False))['thread']
            if thread == receipt['thread_id'] and not _source_workspace(receipt, value):
                receipt.update(state='blocked', reason='source_workspace_mismatch')
                return
            if value['id'] != thread or value['status']['type'] != 'idle' or value['status'].get('activeFlags'):
                receipt.update(reason='waiting_for_idle', last_busy_thread=thread, busy_count=1)
                return
        receipt.update(goals_before=goals, goal_before=goals[receipt['thread_id']], state='reloading',
                       reason=None, reload_attempted=True)
        _save(path, receipt)  # Intent precedes the single external effect; never blindly replay it.
        try:
            from .wake_control import delivery_guard
            with delivery_guard(path.parent.parent):
                _request(receipt, 'config/mcpServer/reload', None)
            receipt.update(state='verifying', reload_acknowledged=True)
        except Exception as exc:
            receipt.update(state='uncertain', reason='reload_outcome_uncertain', observation_error=type(exc).__name__)
            return
        _save(path, receipt)
    if receipt['state'] in ('reloading', 'verifying', 'uncertain'):
        after = {thread: _request(receipt, 'thread/goal/get', dict(threadId=thread))['goal']
                 for thread in receipt['goals_before']}
        if not all(_continuity(before, after[thread]) for thread, before in receipt['goals_before'].items()):
            receipt.update(state='blocked', reason='goal_continuity_unverified')
            return
        receipt.update(goal_after=after[receipt['thread_id']], goal_continuity_verified=True)
        checks = _resources(receipt)
        if checks is None:
            receipt.update(state='blocked', reason='source_workspace_mismatch')
            return
        receipt['resource_status'] = checks
        if all(value['state'] == 'ready' for value in receipt['resource_status'].values()):
            receipt.update(state='completed', reason=None)
        elif receipt['state'] != 'uncertain':
            receipt.update(state='verifying', reason='requested_resources_not_ready')


def poll(root):
    import json
    from .goal_supervision import _lock, _private, _save
    directory = _directory(root)
    for path in directory.glob('*.json'):
        if path.name == 'controller.json':continue
        with _lock(directory, path.stem):
            _private(path)
            receipt = json.loads(path.read_text())
            if receipt['state'] not in ('queued','prepared','pausing_goal','stopping','starting','awaiting_preflight','restoring_goal','reloading','verifying','uncertain'):continue
            try:
                _poll_one(path, receipt)
            except Exception as exc:
                receipt.update(reason='observation_unavailable', observation_error=type(exc).__name__)
                try:
                    if _remaining(receipt) <= 0:receipt.update(state='expired', reason='expiry_reached')
                except WakeError as guard:
                    receipt.update(state='blocked', reason=str(guard))
            _save(path, receipt)


def watch(root, interval=1):
    global _stopping
    _stopping = False
    import fcntl
    import math
    import os
    import signal
    import time
    from uuid import uuid4
    from .goal_supervision import _controller_clock, _save
    from .process import boot_id_value, process_identity
    if type(interval) not in (int, float) or not math.isfinite(interval) or not .05 <= interval <= 5:
        raise WakeError('refresh interval must be between 0.05 and 5 seconds')
    directory = _directory(root)
    descriptor = os.open(directory/'watch.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        running = True
        def finish(signum, frame):
            global _stopping
            nonlocal running
            _stopping = True
            running = False
        prior = {sig: signal.signal(sig, finish) for sig in (signal.SIGTERM, signal.SIGINT)}
        heartbeat = dict(generation=uuid4().hex, pid=os.getpid(), identity=process_identity(os.getpid()),
                         boot_id=boot_id_value(), interval=interval)
        try:
            while running:
                _save(directory/'controller.json', dict(heartbeat, active=True,
                    observed_boottime=None, clock_observation=_controller_clock()))
                poll(root)
                time.sleep(interval)
        finally:
            _save(directory/'controller.json', dict(heartbeat, active=False,
                observed_boottime=None, clock_observation=_controller_clock()))
            for sig, handler in prior.items():signal.signal(sig, handler)
