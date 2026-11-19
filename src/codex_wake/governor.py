"""Ordinary-session controls over Wake's existing supervision authority.

The local operator marker is a private adapter input, never a JSON role field.
Remote adapters must supply a verified session Principal and cannot loosen limits.
"""
import json
import os
import time
from pathlib import Path

from . import goal_supervision as supervision
from . import goal_time, measurements
from .session_permissions import Principal


class _LocalOperator:
    pass


_LOCAL_OPERATOR = _LocalOperator()
_STATUS_ROWS = {}


class _NativePrincipal:
    def __init__(self, principal, policy):
        self.principal=principal
        self.policy=policy


def native_principal(thread, *, policy=None, principal=None):
    """Private verified native adapter binding; never deserialize from JSON."""
    actor=principal or Principal(thread)
    if not isinstance(actor,Principal) or actor.subject!=thread or actor.role!='session':
        raise ValueError('verified exact native session principal required')
    return _NativePrincipal(actor, str(Path(policy).absolute()) if policy is not None else None)



def local_operator_principal():
    """Trusted local CLI/native operator adapter only; never expose as an RPC."""
    return _LOCAL_OPERATOR


def _normalize(receipt, thread):
    controller = receipt.get('controller', {})
    disabled = receipt.get('governor_enabled') is False or receipt.get('task_governor_enabled') is False
    reason = receipt.get('reason')
    exhausted = reason in ('token_limit', 'time_limit', 'token_limit_reached', 'deadline_reached', 'allocation_exhausted', 'continuation_held', 'task_exhausted')
    engagement = receipt.get('engagement', {})
    from .goal_native_guard import qualified
    guarded=qualified(receipt) and controller.get('governor_protocol')==1 if receipt.get('enrollment_revision') else False
    state = ('advisory' if disabled and receipt.get('governor_mode') == 'advisory' else 'disabled' if disabled else 'limit_reached' if exhausted else
             'enforced' if engagement.get('engaged') and guarded else 'disconnected')
    if not disabled and engagement.get('engaged') and not guarded:
        reason=receipt.get('native_guard',{}).get('reason') or ('native_guard_unqualified' if receipt.get('requires_native_guard') else 'watcher_only_native_guard_unqualified')
    if not disabled and receipt.get('requires_native_guard') and controller.get('fresh') and controller.get('governor_protocol')!=1:
        reason='watcher_protocol_upgrade_required'
    same_boot=receipt.get('boot_id')==supervision.boot_id_value()
    faults={reason,receipt.get('first_stop',{}).get('reason'),receipt.get('clock_failure')}
    clock_ok=same_boot and not faults.intersection({'counter_continuity_lost','authenticated_elapsed_unavailable','boot_identity_changed','elapsed_time_invalid','clock_unqualified'})
    accounting=receipt.get('accounting',{})
    current_usage=(same_boot and accounting.get('state')=='qualified' and
        not faults.intersection({'accounting_unknown','accounting_decreased','observation_unavailable'}) and
        not (receipt.get('requires_native_guard') and receipt.get('task_window') and controller.get('governor_protocol')!=1))
    counter=receipt.get('time_basis')=='authenticated_host_counter'
    desired_state=state
    release_pending=disabled and receipt.get('native_guard',{}).get('release_verified') is False
    if release_pending:state='disconnected';reason='native_lease_release_pending'
    elapsed=None
    if clock_ok:
        elapsed=receipt.get('elapsed_upper_seconds') if counter else None
        if not counter:
            try:
                elapsed=max(0,goal_time.upper(receipt)-receipt['time_origin'])
            except goal_time.GoalTimeUnavailable:
                clock_ok=False
        if elapsed is not None and counter and receipt.get('task_window'):
            elapsed=max(0,elapsed-receipt['task_window']['time_origin'])
    used=receipt.get('used_tokens') if current_usage else None
    lifetime=receipt.get('lifetime_used_tokens') if current_usage else None
    limit=receipt.get('token_limit')
    last=receipt.get('last_verified_usage',{})
    if last.get('generation')!=receipt.get('generation'):last={}
    last_verified=dict(used_tokens=last.get('used_tokens'),lifetime_used_tokens=last.get('lifetime_used_tokens'),elapsed_seconds=last.get('elapsed_seconds'),deadline=None if counter else receipt.get('deadline'))
    shared=receipt.get('shared_limits')
    shared_public=dict(shared) if shared else None
    if shared_public:
        shared_public['deadline_basis']='authenticated_host_counter' if counter else 'qualified_utc' if clock_ok else 'unknown'
        if counter:shared_public.update(deadline=None,elapsed_deadline=shared['deadline'])
    remaining_tokens=max(0,limit-used) if type(used) is int and type(limit) is int else None
    if current_usage and shared and type(shared.get('used_tokens')) is int:
        shared_remaining=max(0,shared['token_limit']-shared['used_tokens'])
        remaining_tokens=shared_remaining if receipt.get('task_governor_enabled') is False else min(remaining_tokens,shared_remaining) if remaining_tokens is not None else None
    remaining_seconds=None
    if elapsed is not None and type(receipt.get('time_limit_seconds')) in (int,float):
        remaining_seconds=max(0,receipt['time_limit_seconds']-elapsed)
        if shared:
            coordinate=receipt.get('elapsed_upper_seconds') if counter else receipt['time_origin']+elapsed
            shared_remaining=max(0,shared['deadline']-coordinate)
            remaining_seconds=shared_remaining if receipt.get('task_governor_enabled') is False else min(remaining_seconds,shared_remaining)
    deadline_basis='authenticated_host_counter' if counter else 'qualified_utc' if clock_ok and receipt.get('deadline') is not None else 'unknown'
    return dict(schema_version=1,state=state,desired_state=desired_state if release_pending else None,release_verified=not release_pending if disabled else None,
        scope=dict(thread_id=thread, allocation_id=receipt.get('allocation_id'),
            members=receipt.get('accounting', {}).get('member_thread_ids', [thread]),
            kind='task' if receipt.get('task_window') else 'shared' if len(receipt.get('accounting', {}).get('member_thread_ids', [thread])) > 1 else 'task',
            limiting_scope=receipt.get('limiting_scope'),shared=shared_public),
        usage=dict(used_tokens=used,lifetime_used_tokens=lifetime,remaining_tokens=remaining_tokens,
            elapsed_seconds=elapsed,remaining_seconds=remaining_seconds,last_verified=last_verified,accounting=accounting),
        limits=dict(token_limit=limit,time_limit_seconds=receipt.get('time_limit_seconds'),shared=shared_public),
        deadline=None if counter or not clock_ok else receipt.get('deadline'),deadline_basis=deadline_basis,remaining_seconds=remaining_seconds, watcher=dict(controller,native_guard=receipt.get('native_guard'),native_guard_qualified=guarded),
        revision=receipt.get('budget_revision', receipt.get('enrollment_revision', 0)),
        actions=['activate'] if reason == 'not_enrolled' else ['activate', 'extend', 'reset', 'resume'] if disabled else ['extend', 'reset', 'disable', 'resume', 'advisory'],
        reason=reason, owner_receipt=receipt)


def _execute(root, verb, arguments, *, principal=None):
    host_policy=None
    if isinstance(principal,_NativePrincipal):
        host_policy=principal.policy
        principal=principal.principal
    if not isinstance(arguments, dict):
        raise ValueError('governor arguments must be an object')
    allowed = {'selector', 'endpoint', 'policy', 'request_id', 'expected_revision'}
    allowed |= {'token_limit', 'time_limit_seconds'} if verb in ('activate', 'reset') else set()
    allowed |= {'add_tokens', 'add_seconds'} if verb == 'extend' else set()
    allowed |= {'resume'} if verb in ('extend','reset','disable','advisory') else set()
    if verb not in ('status', 'activate', 'extend', 'reset', 'disable', 'resume', 'advisory') or set(arguments)-allowed:
        raise ValueError('unsupported governor verb or arguments; operator fields never authenticate authority')
    if 'resume' in arguments and type(arguments['resume']) is not bool:raise ValueError('explicit boolean resume choice required')
    selector = arguments.get('selector') or os.environ.get('CODEX_THREAD_ID')
    if not isinstance(selector, str) or not selector:
        raise ValueError('choose a session selector, or run inside a session with CODEX_THREAD_ID')
    from .local_sessions import resolve
    row = None
    if verb == 'status' or principal is _LOCAL_OPERATOR and verb in ('disable','advisory'):
        exact = selector[7:] if selector.startswith('thread:') else selector
        try:
            name = supervision._name(exact)
            retained_path = Path(root) / 'goal-supervision' / (name+'.json')
            if not retained_path.exists():
                from .goal_governance import control_path
                retained_path=control_path(root,exact)
            if retained_path.exists():
                supervision._private(retained_path)
                retained_status = json.loads(retained_path.read_text())
                if retained_status.get('thread_id') != exact:
                    raise ValueError('retained governor target identity changed')
                row = dict(thread_id=exact,endpoint=arguments.get('endpoint','unix://'))
        except ValueError:
            # Only a non-UUID selector may fall back to inventory discovery.
            from uuid import UUID
            try: UUID(exact)
            except ValueError: pass
            else: raise
    if row is None:
        row = _resolve_status(root, selector, arguments.get('endpoint', 'unix://')) if verb == 'status' else resolve(root, selector, endpoint=arguments.get('endpoint', 'unix://'))
    thread = row['thread_id']
    if principal is not None and principal is not _LOCAL_OPERATOR:
        if not isinstance(principal, Principal) or principal.role != 'session' or principal.subject != thread:
            raise ValueError('verified exact-session principal required')
    path = Path(root) / 'goal-supervision' / (supervision._name(thread)+'.json')
    from .goal_governance import control_path,control_snapshot
    control=control_path(root,thread)
    if not path.exists():
        if control.exists():
            supervision._private(control);retained=json.loads(control.read_text())
            if host_policy is not None and Path(retained['policy_path']).absolute()!=Path(host_policy):raise ValueError('retained inactive governor host binding changed; reconcile the selected scope')
            receipt=control_snapshot(root,thread)
        else:receipt = dict(thread_id=thread, reason='not_enrolled')
    else:
        supervision._private(path)
        retained = json.loads(path.read_text())
        if host_policy is not None and Path(retained['policy_path']).absolute()!=Path(host_policy):
            raise ValueError('retained governor host policy differs from authenticated native binding; reconcile without renewing')
        if principal is _LOCAL_OPERATOR and verb in ('disable','advisory'):
            from .goal_governance import sync
            sync(retained);receipt=dict(supervision._public(retained),controller=supervision._heartbeat(path.parent))
        else:
            receipt = supervision.show(root,retained['policy_path'],thread,
                permission_principal=Principal(thread,'operator') if principal is _LOCAL_OPERATOR else principal)
    if verb == 'status':
        return _normalize(receipt, thread)
    if principal is None:
        raise ValueError('verified session identity or authenticated local operator required')
    expected = arguments.get('expected_revision')
    if expected is not None and (type(expected) is not int or expected != _normalize(receipt, thread)['revision']):
        raise ValueError('governor revision changed; inspect current status')
    operator = principal is _LOCAL_OPERATOR
    if verb != 'activate' and not operator:
        raise ValueError('authenticated operator required to extend, reset, disable, resume or choose advisory')
    if arguments.get('policy') is not None and not operator:
        raise ValueError('only the local operator may select an existing policy')
    if verb=='activate' and control.exists() and not path.exists() and not operator:
        raise ValueError('authenticated operator required to reactivate an explicitly disabled governor')
    if verb == 'activate' and path.exists() and (receipt.get('governor_enabled') is False or receipt.get('task_governor_enabled') is False):
        if not operator:
            raise ValueError('authenticated operator required to reactivate a disabled governor')
        from .goal_governance import change
        change(root, thread, enabled=True, principal=Principal(thread, 'operator'),task_only=bool(receipt.get('task_window')))
        return _normalize(supervision.show(root,retained['policy_path'],thread,permission_principal=Principal(thread,'operator')), thread)
    if verb == 'activate':
        from .local_self_limits import policy_for
        from .self_limits import local_execute
        policy = retained['policy_path'] if path.exists() or control.exists() else policy_for(root,row,host_policy or arguments.get('policy'))
        limits = {key: arguments.get(key,receipt.get(key) if operator and (path.exists() or control.exists()) else None) for key in ('token_limit', 'time_limit_seconds')}
        for value in limits.values():
            if type(value) is not int or value <= 0:
                raise ValueError('positive token_limit and time_limit_seconds required')
        result = local_execute(root,policy,'set',limits,thread_id=thread,activation_baseline=True,replace_advisory=bool(control.exists() and operator))
        if control.exists() and path.exists():
            with supervision._lock(path.parent,path.stem):
                active=json.loads(path.read_text());active.setdefault('prior_control',json.loads(control.read_text()))
                supervision._save(path,active)
        return _normalize(result, thread)
    authority = Principal(thread,'operator')
    if not path.exists():
        if verb in ('disable','advisory'):
            from .local_self_limits import policy_for
            from .goal_governance import admit_advisory
            policy=retained['policy_path'] if control.exists() else policy_for(root,row,host_policy or arguments.get('policy'))
            result=admit_advisory(root,policy,thread,principal=authority,intended_limits=_declared_limits(root,thread),mode='disabled' if verb=='disable' else 'advisory')
            normalized=_normalize(result,thread)
            if arguments.get('resume'):return _resume(root,json.loads(control.read_text()),arguments,authority)
            return normalized
        if verb=='resume' and control.exists():return _resume(root,retained,arguments,authority)
        raise ValueError('activate this session before changing its governor')
    if verb in ('disable', 'advisory'):
        from .goal_governance import change
        result = change(root, thread, enabled=False, principal=authority, mode='advisory' if verb == 'advisory' else None,task_only=bool(receipt.get('task_window')))
        normalized=_normalize(result,thread)
        if normalized.get('reason')=='native_lease_release_pending':normalized['operation']=dict(resumed=False,resume_state='native_lease_release_pending',release_verified=False)
        if arguments.get('resume'):return _resume(root,json.loads(path.read_text()),arguments,authority)
        return normalized
    if verb in ('extend', 'reset'):
        result = _renew(root, retained, verb, arguments, authority)
        current = supervision.show(root, retained['policy_path'], thread,permission_principal=authority)
        normalized = _normalize(current, thread)
        normalized['operation'] = result
        if result.get('resumed') is False and result.get('resume_state'):normalized['reason']=result['resume_state']
        return normalized
    if verb == 'resume':
        return _resume(root, retained, arguments, authority)
    raise ValueError('unsupported governor action')


def _renew(root, receipt, verb, arguments, principal):
    from . import goal_renewal as renewal
    from uuid import uuid4
    request = arguments.get('request_id') or uuid4().hex
    if receipt.get('task_window'):
        result=renewal.renew_task_window(root,receipt['policy_path'],receipt['thread_id'],
            principal=principal,operation_id=request,mode=verb,
            token_limit=arguments.get('token_limit'),time_limit_seconds=arguments.get('time_limit_seconds'),
            add_tokens=arguments.get('add_tokens',0),add_seconds=arguments.get('add_seconds',0),resume=arguments.get('resume',False))
        if arguments.get('resume') and result.get('resume_state') in ('awaiting_first_poll','native_lease_release_pending'):
            result.update(renewal.resume_existing(root,receipt['policy_path'],receipt['thread_id'],
                principal=principal,operation_id=request+':resume'))
        return result
    identifier = renewal._id(receipt['thread_id'], request)
    directory = supervision._directory(root)
    path = renewal._journal_path(directory, identifier)
    intent = {key: value for key, value in arguments.items() if key not in ('selector', 'endpoint', 'expected_revision')}
    if path.exists():
        journal = renewal._read(path)
        if journal.get('governor_intent') != dict(verb=verb, arguments=intent):
            raise ValueError('request_id already names a different governor operation')
        packet = journal
    else:
        if verb == 'extend':
            adds = [arguments.get('add_tokens', 0), arguments.get('add_seconds', 0)]
            if any(type(value) is not int or value < 0 for value in adds) or not any(adds):
                raise ValueError('extension requires positive add_tokens or add_seconds')
            tokens = receipt['token_limit'] + adds[0]
            deadline = receipt['deadline'] + adds[1]
            window = dict(deadline=deadline)
        else:
            tokens = arguments.get('token_limit', receipt['token_limit'])
            seconds = arguments.get('time_limit_seconds', receipt['time_limit_seconds'])
            window = dict(remaining_seconds=seconds)
        packet = renewal.propose(root, receipt['policy_path'], receipt['thread_id'],
            principal=principal, operation_id=request, mode=verb, token_limit=tokens,
            expires_at=renewal._now()+300, shared=False,
            resume=arguments.get('resume', False), **window)
        journal = renewal._read(path)
        journal['governor_intent'] = dict(verb=verb, arguments=intent)
        supervision._save(path, journal)
    return renewal.apply(root, receipt['policy_path'], receipt['thread_id'], packet['proposal_id'],
        principal=principal, expected_fingerprint=packet['fingerprint'], explicit=True)


def _resume(root, receipt, arguments, principal):
    from .goal_renewal import resume_existing
    from uuid import uuid4
    from .goal_governance import independent_constraint,control_snapshot
    inactive=receipt.get('governor_enabled') is False or receipt.get('task_governor_enabled') is False
    restriction=independent_constraint(supervision._directory(root),receipt)
    if inactive and restriction and receipt.get('advisory_without_window'):raise ValueError(restriction)
    if inactive and not restriction:
        from .goal_renewal import resume_unenforced
        result=resume_unenforced(root,receipt,principal=principal,operation_id=arguments.get('request_id') or uuid4().hex)
    else:
        result=resume_existing(root,receipt['policy_path'],receipt['thread_id'],principal=principal,operation_id=arguments.get('request_id') or uuid4().hex)
    current=control_snapshot(root,receipt['thread_id']) if receipt.get('advisory_without_window') else supervision.show(root,receipt['policy_path'],receipt['thread_id'],permission_principal=principal)
    normalized=_normalize(current,receipt['thread_id'])
    normalized['operation'] = result
    if result.get('resumed') is False and result.get('resume_state'):normalized['reason']=result['resume_state']
    return normalized


def execute(root, verb, arguments, *, principal=None):
    """Execute one qualified intent; request IDs reconcile the owner receipt."""
    if verb == 'status' or not isinstance(arguments, dict):
        return _execute(root, verb, arguments, principal=principal)
    arguments=dict(arguments)
    if arguments.get('request_id') is None:
        from uuid import uuid4
        arguments['request_id']=uuid4().hex
    identifier = arguments['request_id']
    if not isinstance(identifier, str) or not identifier or len(identifier) > 256:
        raise ValueError('bounded nonempty request_id required')
    if principal is None:
        raise ValueError('verified session identity or authenticated local operator required')
    from .local_sessions import resolve
    selector = arguments.get('selector') or os.environ.get('CODEX_THREAD_ID')
    if not isinstance(selector, str) or not selector:
        raise ValueError('choose a session selector, or run inside a session with CODEX_THREAD_ID')
    exact=selector[7:] if selector.startswith('thread:') else selector
    retained_control=False
    if principal is _LOCAL_OPERATOR and verb in ('disable','advisory'):
        try:
            name=supervision._name(exact)
            from .goal_governance import control_path
            retained_control=(Path(root)/'goal-supervision'/(name+'.json')).exists() or control_path(root,exact).exists()
        except ValueError:pass
    row=dict(thread_id=exact,endpoint=arguments.get('endpoint','unix://')) if retained_control else resolve(root,selector,endpoint=arguments.get('endpoint','unix://'))
    thread = row['thread_id']
    actor=principal.principal if isinstance(principal,_NativePrincipal) else principal
    if actor is not _LOCAL_OPERATOR and (not isinstance(actor, Principal) or actor.role != 'session' or actor.subject != thread):
        raise ValueError('verified exact-session principal required')
    import hashlib
    digest = hashlib.sha256(json.dumps(dict(verb=verb, arguments=arguments), sort_keys=True, default=str).encode()).hexdigest()
    directory = supervision._directory(root)
    path = directory / (supervision._name(thread)+'.json')
    with supervision._lock(directory, 'governor-request-'+supervision._name(thread)):
        requests=directory/'governor-requests'
        requests.mkdir(mode=0o700,exist_ok=True);supervision._private(requests,True)
        request_path=requests/(hashlib.sha256((thread+'\0'+identifier).encode()).hexdigest()+'.json')
        prior=None
        if request_path.exists():
            supervision._private(request_path);prior=json.loads(request_path.read_text())
        if path.exists() and prior is None:
            supervision._private(path)
            retained = json.loads(path.read_text())
            prior = retained.get('governor_requests', {}).get(identifier)
        if prior and prior['fingerprint'] != digest:
            raise ValueError('request_id already names a different governor operation')
        if prior and prior.get('operation'):
            # Resume may wait for the existing watcher acknowledgement.
            # Reconcile only that same approved operation, never new budget.
            if prior['operation'].get('resume_state') in ('awaiting_first_poll','native_lease_release_pending'):
                retry = {key: value for key, value in arguments.items() if key != 'expected_revision'}
                result = _execute(root, verb, retry, principal=principal)
                result = _await_continuation(root,verb,dict(retry,selector=thread,endpoint=row['endpoint']),principal,result)
                with supervision._lock(directory, supervision._name(thread)):
                    retained = json.loads(path.read_text())
                    retained['governor_requests'][identifier]['operation'] = result.get('operation',dict(state=result['state'],revision=result['revision'],reason=result.get('reason')))
                    supervision._save(path, retained)
            else:
                result = _execute(root, 'status', {'selector': thread, 'endpoint': row['endpoint']}, principal=principal)
                result['operation'] = prior['operation']
                if prior['operation'].get('resumed') is False and prior['operation'].get('resume_state'):result['reason']=prior['operation']['resume_state']
            result['request_id'] = identifier
            supervision._save(request_path,dict(fingerprint=digest,thread_id=thread,verb=verb,declared_limits=result.get('limits'),operation=result.get('operation',dict(state=result['state'],revision=result['revision'],reason=result.get('reason')))))
            return result
        if prior is None:supervision._save(request_path,dict(fingerprint=digest,thread_id=thread,verb=verb,
            declared_limits={key:arguments.get(key) for key in ('token_limit','time_limit_seconds')} if verb=='activate' else None,operation=None))
        result = _execute(root, verb, arguments, principal=principal)
        result = _await_continuation(root,verb,dict(arguments,selector=thread,endpoint=row['endpoint']),principal,result)
        if result['scope']['thread_id'] != thread:
            raise ValueError('selected target changed during governor operation; inspect retained owner receipts')
        with supervision._lock(directory, supervision._name(thread)):
            if path.exists():
                supervision._private(path)
                retained = json.loads(path.read_text())
                retained.setdefault('governor_requests', {})[identifier] = dict(fingerprint=digest,
                    operation=result.get('operation', dict(state=result['state'], revision=result['revision'])))
                supervision._save(path, retained)
        operation=result.get('operation',dict(state=result['state'],revision=result['revision'],reason=result.get('reason')))
        supervision._save(request_path,dict(fingerprint=digest,thread_id=thread,verb=verb,declared_limits=result.get('limits'),operation=operation))
        result['request_id'] = identifier
        return result


def _status_identity(row):
    """Cheap current owner identity, never a mutation or liveness promise."""
    from .process import process_identity
    target = row['target']
    process = target['process']
    birth = process_identity(process['pid'])
    if not birth or birth.get('boot_id') != process['boot_id'] or birth.get('start_time_ticks') != process['start_ticks']:
        raise ValueError('cached native peer exited or changed identity')
    home = Path(target['home']).stat()
    endpoint = Path(row['endpoint'][7:]).stat()
    image = Path('/proc', str(process['pid']), 'exe')
    executable = image.stat()
    if (home.st_uid != os.getuid() or endpoint.st_uid != os.getuid()
            or f'{home.st_dev}:{home.st_ino}' != target['home_generation']
            or f'{endpoint.st_dev}:{endpoint.st_ino}' != target['socket_generation']
            or str(image.resolve()) != target['executable']):
        raise ValueError('cached native target ownership changed')
    return (executable.st_dev, executable.st_ino, executable.st_mtime_ns, executable.st_size)


def _resolve_status(root, selector, endpoint):
    from .local_sessions import resolve
    key = (str(Path(root).absolute()), selector, endpoint)
    cached = _STATUS_ROWS.get(key)
    if cached:
        try:
            if _status_identity(cached[0]) == cached[1]:
                return cached[0]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        _STATUS_ROWS.pop(key, None)
    row = resolve(root, selector, endpoint=endpoint)
    try:
        identity = _status_identity(row)
    except (OSError, ValueError, KeyError, TypeError):
        return row
    if len(_STATUS_ROWS) >= 128:
        _STATUS_ROWS.pop(next(iter(_STATUS_ROWS)))
    _STATUS_ROWS[key] = (row, identity)
    return row


def _await_continuation(root,verb,arguments,principal,result):
    """One operator action waits briefly on the same approved continuation."""
    pending=('awaiting_first_poll','native_lease_release_pending')
    if result.get('operation',{}).get('resume_state') not in pending:
        return result
    try:
        deadline=measurements.deadline(3)
        while result.get('operation',{}).get('resume_state') in pending:
            remaining=deadline.remaining()
            if remaining<=0:
                break
            time.sleep(min(.05,remaining))
            if deadline.expired():
                break
            retry={key:value for key,value in arguments.items() if key!='expected_revision'}
            result=_execute(root,verb,retry,principal=principal)
    except measurements.TimeUnavailable:
        result=dict(result,wait_status='qualified_time_unavailable')
    return result


def _declared_limits(root,thread):
    directory=Path(root)/'goal-supervision/governor-requests'
    if not directory.exists():return None
    for path in sorted(directory.glob('*.json'),key=lambda item:item.stat().st_mtime_ns,reverse=True)[:64]:
        supervision._private(path);row=json.loads(path.read_text())
        if row.get('thread_id')==thread and row.get('verb')=='activate' and row.get('declared_limits'):
            return {key:row['declared_limits'].get(key) for key in ('token_limit','time_limit_seconds')}
    return None
