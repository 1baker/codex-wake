"""Independent native supervision for one exact existing Codex session.

This module requests checkpoints, pauses goals and interrupts exact turns. It
never kills a shared executor, promises tool termination, or renews an allocation.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import tempfile
import time
from uuid import UUID, uuid4

from .native_protocol import native_request
from .process import boot_id_value, process_exists, process_identity

NATIVE_GOAL_STATUSES={'active','paused','blocked','complete','budgetLimited','usageLimited'}


def _private(path, directory=False):
    info=path.lstat()
    if path.is_symlink() or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077:
        raise ValueError('goal supervision paths must be private and owned')
    if directory and not stat.S_ISDIR(info.st_mode):raise ValueError('goal supervision directory unavailable')
    if not directory and not stat.S_ISREG(info.st_mode):raise ValueError('goal supervision file unavailable')


def _directory(root):
    root=Path(root).absolute()
    if root!=root.resolve():raise ValueError('supervision root cannot traverse symlinks')
    root.mkdir(parents=True,exist_ok=True,mode=0o700);_private(root,True)
    directory=root/'goal-supervision';directory.mkdir(exist_ok=True,mode=0o700);_private(directory,True)
    return directory


def _save(path,value):
    descriptor,temporary=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as stream:
            json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        descriptor=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


@contextmanager
def _lock(directory,name):
    descriptor=os.open(directory/(name+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        yield


def _name(thread):
    if not isinstance(thread,str) or str(UUID(thread))!=thread:raise ValueError('exact caller UUID required')
    return hashlib.sha256(thread.encode()).hexdigest()


class CallerGrantMissing(ValueError):
    """The host policy has no authority for this caller; no effect was attempted."""


def _delegated_grant(policy,thread,allocation_id,root):
    allocations=policy['allocations']
    if not isinstance(allocations,dict):raise ValueError('host allocations must be an object')
    template=policy.get('self_enrollment')
    selected=allocation_id
    directory=None
    if root is not None:
        base=Path(root).absolute()
        if base!=base.resolve():raise ValueError('supervision root cannot traverse symlinks')
        directory=base/'goal-supervision'
        receipt=directory/(_name(thread)+'.json')
        if selected is None and template is not None and receipt.exists():
            _private(receipt);current=json.loads(receipt.read_text())
            if current['thread_id']!=thread:raise ValueError('stored caller identity changed')
            selected=current['allocation_id']
    selected=selected or policy.get('default_allocation')
    if selected in allocations:
        return dict(allocations[selected],allocation_id=selected,host_delegated=True)
    if template is None:raise ValueError('select an existing host objective allocation')
    fields={'app_server','codex_path','codex_home','max_tokens','max_seconds','rpc_timeout','requires_enforcement'}
    if not isinstance(template,dict) or set(template)-fields or not fields-{'rpc_timeout','requires_enforcement'}<=set(template):
        raise ValueError('host self-enrollment envelope is invalid')
    own='native-'+thread
    selected=selected or own
    if not isinstance(selected,str) or not selected.startswith('native-'):
        raise ValueError('select an existing host objective allocation')
    _name(selected[len('native-'):])
    grant=dict(template,allocation_id=selected,host_delegated=True,auto_enrolled=True)
    if selected!=own:
        if directory is None:raise ValueError('existing objective ledger required')
        path=directory/'allocations'/(hashlib.sha256(selected.encode()).hexdigest()+'.json')
        _private(path);existing=json.loads(path.read_text())
        if (existing['allocation_id']!=selected or
                existing['grant']!=dict(grant,rpc_timeout=grant.get('rpc_timeout',5))):
            raise ValueError('existing objective envelope changed')
    return grant


def _load_grant(policy_path,thread,allocation_id=None,root=None):
    path=Path(policy_path).absolute();_private(path)
    if path!=path.resolve():raise ValueError('policy cannot traverse symlinks')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate host policy key')
            result[key]=value
        return result
    policy=json.loads(path.read_text(),object_pairs_hook=unique)
    version=policy.get('version')
    if type(version) is not int or version not in (1,2):raise ValueError('unsupported goal limits policy')
    callers=policy['callers'] if version==1 else policy.get('callers',{})
    if not isinstance(callers,dict):raise ValueError('host callers must be an object')
    if version==1 or thread in callers:
        if thread not in callers:raise CallerGrantMissing('host caller grant unavailable or malformed')
        grant=callers[thread]
        if allocation_id is not None and allocation_id!=grant.get('allocation_id'):
            raise ValueError('explicit caller grant cannot select the requested allocation; qualified migration required for the selected allocation')
    else:
        if policy.get('native_caller_binding') is not True:
            raise ValueError('host must require native caller binding')
        grant=_delegated_grant(policy,thread,allocation_id,root)
    for key in ('max_tokens','max_seconds'):
        if type(grant[key]) is not int or grant[key]<=0:raise ValueError('invalid host allocation cap')
    if not isinstance(grant['allocation_id'],str) or not grant['allocation_id']:raise ValueError('allocation identity unavailable')
    for key in ('codex_path','codex_home'):
        selected=Path(grant[key])
        if not selected.is_absolute() or (key=='codex_home' and selected!=selected.resolve()):raise ValueError('host path must be exact and absolute')
    if not Path(grant['codex_path']).is_file():raise ValueError('host Codex executable unavailable')
    endpoint=grant['app_server']
    if not isinstance(endpoint,str) or not endpoint.startswith('unix:///') or not Path(endpoint[7:]).is_absolute():
        raise ValueError('host must approve an exact absolute Unix endpoint')
    timeout=grant.get('rpc_timeout',5)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=5:raise ValueError('invalid RPC timeout')
    return dict(grant,rpc_timeout=timeout)


def _grant(policy_path,thread,allocation_id=None,root=None):
    try:return _load_grant(policy_path,thread,allocation_id,root)
    except (KeyError,TypeError,AttributeError) as exc:raise ValueError('host caller grant unavailable or malformed') from exc


def verified_native_caller(context,claimed):
    """Accept metadata from the host's private native MCP connection only.

    Transport ownership belongs to the host installation; this is not an
    authentication mechanism for arbitrary HTTP clients or hostile same-UID code.
    """
    if not isinstance(context,dict):raise ValueError('verified native caller metadata required')
    turn=context.get('x-codex-turn-metadata')
    if not isinstance(turn,dict):raise ValueError('verified native caller turn required')
    # Native successors have their own thread identity but retain the source's
    # session identity. Neither transport field may contradict its turn metadata.
    if (context.get('threadId') != claimed or turn.get('thread_id') != claimed
            or context.get('sessionId') != turn.get('session_id')):
        raise ValueError('native caller identity does not match claim')
    _name(claimed)
    _name(context.get('sessionId'))
    if not all(isinstance(value,str) and value for value in (context.get('callId'),turn.get('turn_id'))):
        raise ValueError('native caller call and turn required')
    return dict(thread_id=claimed,turn_id=turn['turn_id'],call_id=context['callId'])


def _public(receipt):
    receipt=dict(receipt)
    receipt.setdefault('governor_enabled',True)
    if receipt['governor_enabled'] is False:
        receipt.update(campaign_state=receipt.get('state'),state='inactive')
    if type(receipt.get('used_tokens')) is int:
        receipt['lifetime_used_tokens']=receipt.get('lifetime_tokens_before_window',0)+receipt['used_tokens']
    from .goal_time import public_time
    receipt.update(public_time(receipt))
    return dict({key:value for key,value in receipt.items() if key not in ('grant','policy_path','prior_allocation')},
        stop_scope='qualified_task_tree' if receipt.get('descendant_stop_verified') else 'registered_goal_campaign',descendant_stop_verified=receipt.get('descendant_stop_verified',False))


def _request(grant,method,params):
    return native_request(grant['app_server'],grant['codex_path'],method,params,grant['rpc_timeout'])


class NativeObservationUnavailable(ValueError):
    def __init__(self,method,cause,duration=None):
        super().__init__(method+': '+cause)
        self.method=method
        self.cause=cause
        self.duration=duration


def _native(grant,thread):
    started=time.monotonic();deadline=started+grant['rpc_timeout']
    def observe(method,params):
        remaining=deadline-time.monotonic()
        try:
            if remaining<=0:raise TimeoutError('native observation budget exhausted')
            return _request(dict(grant,rpc_timeout=remaining),method,params)
        except Exception as exc:
            raise NativeObservationUnavailable(method,type(exc).__name__,time.monotonic()-started) from exc
    goal=observe('thread/goal/get',dict(threadId=thread))['goal']
    native=observe('thread/read',dict(threadId=thread,includeTurns=False))['thread']
    if native.get('id')!=thread or (goal and goal.get('threadId')!=thread):raise ValueError('native thread identity changed')
    cursor=None;seen_cursors=set();seen_turns=set();active=[]
    for _ in range(32):
        params=dict(threadId=thread,limit=128,sortDirection='desc',itemsView='notLoaded')
        if cursor is not None:params['cursor']=cursor
        page=observe('thread/turns/list',params)
        turns=page.get('data')
        if not isinstance(turns,list):raise ValueError('native turn state unavailable')
        for turn in turns:
            identity=turn.get('id');status=turn.get('status')
            if (not isinstance(identity,str) or not identity or identity in seen_turns
                    or status not in ('completed','interrupted','failed','inProgress')):
                raise ValueError('native turn state ambiguous')
            seen_turns.add(identity)
            if status=='inProgress':active.append(identity)
        if len(active)>1:raise ValueError('native active turn ambiguous')
        cursor=page.get('nextCursor')
        if cursor is None:return goal,active
        if not isinstance(cursor,str) or not cursor or cursor in seen_cursors:
            raise ValueError('native turn cursor ambiguous')
        seen_cursors.add(cursor)
    raise ValueError('native turn observation page limit exceeded')


def _allocation_path(directory,allocation_id):
    child=directory/'allocations';child.mkdir(exist_ok=True,mode=0o700);_private(child,True)
    return child/(hashlib.sha256(allocation_id.encode()).hexdigest()+'.json')


def _save_request_accounting(path, receipt):
    """Persist shared accounting before its session projection.

    Caller holds maintenance then session locks; allocation lock is innermost.
    A failed qualification must not overwrite the allocation or source receipt.
    """
    if receipt.get('allocation_path'):
        allocation_path = Path(receipt['allocation_path'])
        with _lock(allocation_path.parent, allocation_path.stem):
            _private(allocation_path)
            allocation = json.loads(allocation_path.read_text())
            allocation['request_accounting'] = receipt['request_accounting']
            _save(allocation_path, allocation)
    _save(path, receipt)


def _allocation_admit(directory,receipt,old,*,commit=True):
    renewal=bool(old and old['allocation_id']!=receipt['allocation_id'])
    anchor=receipt.get('reset_anchor')
    if renewal:
        if receipt['grant'].get('renews_allocation')!=old['allocation_id']:
            raise ValueError('changing allocation requires explicit host renewal of the prior allocation')
        from .goal_usage import observe_usage
        original=observe_usage(receipt['grant']['codex_home'],receipt['thread_id'],receipt['goal_created_at'],
            token_accounting=receipt['token_accounting'])
        if original.get('state')!='qualified' or not original.get('anchor'):
            raise ValueError('explicit host renewal requires qualified original history')
        anchor=original['anchor']
    path=_allocation_path(directory,receipt['allocation_id'])
    with _lock(path.parent,path.stem):
        if path.exists():
            _private(path);allocation=json.loads(path.read_text())
            if allocation.get('pending_recovery'):raise ValueError('allocation recovery is pending reconciliation')
            if allocation['grant']!=receipt['grant']:raise ValueError('host allocation changed; explicit renewal required')
            if not receipt.get('task_window') and (receipt['token_limit']>allocation['token_limit'] or
                    receipt['time_limit_seconds']>allocation['time_limit_seconds']):
                raise ValueError('same allocation may only tighten limits')
            if receipt['token_accounting']!=allocation['token_accounting']:
                raise ValueError('allocation accounting basis cannot change during self enrollment')
        else:
            initial=receipt['grant'].get('initial_boundary')
            members={};origin=receipt['time_origin']
            if initial is not None:
                if not isinstance(initial,dict) or initial.get('token_accounting')!=receipt['token_accounting']:
                    raise ValueError('host initial boundary accounting basis unavailable')
                origin=initial.get('started_at');initial_anchor=initial.get('reset_anchor')
                if (type(origin) not in (int,float) or not math.isfinite(origin)
                        or not isinstance(initial_anchor,dict)):
                    raise ValueError('host initial boundary unavailable')
                root_thread=initial_anchor.get('thread_id');_name(root_thread)
                created=initial_anchor.get('goal_created_at')
                if (type(created) not in (int,float) or not math.isfinite(created)
                        or not created<=origin<=receipt['started_upper']):
                    raise ValueError('host initial boundary time is unqualified')
                from .goal_usage import observe_usage
                qualified=observe_usage(receipt['grant']['codex_home'],root_thread,created,
                    reset_anchor=initial_anchor,token_accounting=receipt['token_accounting'])
                if qualified.get('state')!='qualified':
                    raise ValueError('host initial boundary requires qualified original history')
                # Register the boundary owner even if a successor enrolls first;
                # otherwise spending between renewal and enrollment disappears.
                members[root_thread]=dict(goal_created_at=created,reset_anchor=initial_anchor)
            allocation=dict(version=1,allocation_id=receipt['allocation_id'],grant=receipt['grant'],
                token_limit=receipt['grant']['max_tokens'] if receipt.get('task_window') else receipt['token_limit'],
                time_limit_seconds=receipt['grant']['max_seconds'] if receipt.get('task_window') else receipt['time_limit_seconds'],
                token_accounting=receipt['token_accounting'],time_origin=origin,
                deadline=origin+(receipt['grant']['max_seconds'] if receipt.get('task_window') else receipt['time_limit_seconds']),members=members,charges={},used_tokens=0,stop_latched=False,boot_id=boot_id_value())
        from .goal_time import relative, FIELDS, merge_allocation
        if not allocation['members'] and relative(receipt) and 'time_basis' not in allocation:
            allocation.update({key:receipt[key] for key in FIELDS})
        merge_allocation(receipt,allocation)
        if receipt['thread_id'] not in allocation['members'] and len(allocation['members'])>=32:
            raise ValueError('allocation member limit reached')
        if not receipt.get('task_window'):
            allocation['token_limit']=min(receipt['token_limit'],allocation['token_limit'])
            allocation['time_limit_seconds']=min(receipt['time_limit_seconds'],allocation['time_limit_seconds'])
        allocation['deadline']=min(allocation['deadline'],allocation['time_origin']+allocation['time_limit_seconds'])
        allocation['members'].setdefault(receipt['thread_id'],dict(goal_created_at=receipt['goal_created_at'],reset_anchor=anchor,
            **{key:receipt[key] for key in ('usage_thread_id','usage_goal_created_at','usage_reset_anchor','session_scope','lifetime_tokens_before_window','activation_baseline','task_window','task_owner_thread_id') if key in receipt}))
        member=allocation['members'][receipt['thread_id']]
        task_owner=member.get('task_owner_thread_id',receipt['thread_id'])
        if task_owner!=receipt['thread_id'] and allocation['members'].get(task_owner,{}).get('task_window'):
            task=allocation['members'][task_owner]['task_window']
            task['token_limit']=min(task['token_limit'],receipt['token_limit'])
            task['time_limit_seconds']=min(task['time_limit_seconds'],receipt['time_limit_seconds'])
            task['deadline']=min(task['deadline'],task['time_origin']+task['time_limit_seconds'])
            receipt['task_window']=task
        for key in ('lifetime_tokens_before_window','activation_baseline'):
            if key in member:receipt[key]=member[key]
        if member.get('activation_baseline'):receipt['reset_anchor']=member.get('reset_anchor')
        if receipt.get('task_window') and old:
            member['task_window']=receipt['task_window']
        if member.get('task_window'):receipt['task_window']=member['task_window']
        if renewal and member.get('reset_anchor')!=anchor:
            raise ValueError('renewal boundary changed; reconcile the persisted target allocation before continuing')
        receipt.update(goal_created_at=member['goal_created_at'],time_origin=allocation['time_origin'],
            deadline=allocation['deadline'],token_limit=allocation['token_limit'],
            time_limit_seconds=allocation['time_limit_seconds'],allocation_path=str(path),
            used_tokens=old.get('used_tokens',0) if receipt.get('task_window') and old else 0 if receipt.get('task_window') else allocation['used_tokens'])
        if allocation.get('boot_id')!=boot_id_value():allocation['stop_latched']=True
        if allocation['stop_latched']:
            receipt['stop_latched']=True
            if receipt.get('reason') is None:receipt['reason']=allocation.get('stop_reason','continuation_held')
        if allocation.get('pending_recovery'):
            receipt['reason']='observation_unavailable'
            receipt['active_stop_id']=allocation['pending_recovery'].get('stop_episode_id')
        if 'winddown_deadline' in allocation:
            receipt['allocation_winddown_deadline']=allocation['winddown_deadline']
        if commit:_save(path,allocation)
    if renewal and commit:
        # Finalize the departed member, not the entire previous allocation.
        # Its qualified snapshot remains chargeable without charging new work
        # to both allowances. A crash before the caller receipt is replaced
        # makes that old receipt hold until the exact renewal is reconciled.
        previous=Path(old['allocation_path']);_private(previous)
        with _lock(previous.parent,previous.stem):
            prior=json.loads(previous.read_text());member=prior['members'][receipt['thread_id']]
            if 'finalized_charges' not in member:
                from .goal_usage import observe_usage
                final=observe_usage(old['grant']['codex_home'],receipt['thread_id'],member['goal_created_at'],
                    token_accounting=prior['token_accounting'],reset_anchor=member.get('reset_anchor'))
                if final.get('state')!='qualified' or any(
                        final['anchor'].get(key)!=anchor[key] for key in
                        ('version','thread_id','goal_created_at','boundary')) or any(
                        final['anchor']['response_hashes'].get(key)!=value
                        for key,value in anchor['response_hashes'].items()):
                    raise ValueError('renewal boundary changed; reconcile before continuing')
                # History can grow after target admission. Freeze old charges
                # at that admitted boundary; later responses belong to the new
                # allowance, even if another watcher sampled them in the old one.
                frozen={key:value for key,value in final['charges'].items()
                        if key in anchor['response_hashes']}
                transferred=set(final['charges'])-set(frozen)
                prior.setdefault('renewed_out_charges',{}).update(
                    {key:final['charges'][key] for key in transferred})
                prior['charges']={key:value for key,value in prior['charges'].items()
                                  if key not in transferred}
                prior['used_tokens']=sum(value['tokens'] for value in prior['charges'].values())
                member.update(finalized_charges=frozen,final_anchor=anchor,
                    renewed_into=receipt['allocation_id'])
                _save(previous,prior)


def _usage(receipt):
    if receipt.get('advisory_without_window'):
        from .goal_usage import observe_session_usage
        return observe_session_usage(receipt['grant']['codex_home'],receipt['thread_id'])
    if receipt.get('request_accounting'):
        from .objective_ledger import ObjectiveLedger
        from .lifecycle_budget import trusted_upper
        binding=receipt['request_accounting']
        view=ObjectiveLedger(binding['root'],binding['objective_id']).inspect(now=trusted_upper())
        return dict(state='qualified' if view['accounting_known'] else 'unknown',
            used_tokens=view['tokens_used'],token_accounting='fresh',sampled=False,
            reason=None if view['accounting_known'] else 'request_completion_unknown',request_accounting=binding)
    from .goal_usage import observe_usage
    if not receipt.get('grant',{}).get('host_delegated'):
        return observe_usage(receipt['grant']['codex_home'],receipt['thread_id'],receipt['goal_created_at'],
            reset_anchor=receipt.get('reset_anchor'),token_accounting=receipt.get('token_accounting','cache_inclusive'),
            session_scope=receipt.get('session_scope',False))
    path=Path(receipt['allocation_path']);_private(path)
    with _lock(path.parent,path.stem):
        allocation=json.loads(path.read_text());charges={};qualified_threads=set()
        if 'finalized_charges' in allocation['members'][receipt['thread_id']]:
            return dict(state='unknown',used_tokens=None,reason='member_renewal_pending')
        for thread,member in allocation['members'].items():
            if 'finalized_charges' in member:
                observation=dict(state='qualified',charges=member['finalized_charges'])
            else:
                observation=observe_usage(receipt['grant']['codex_home'],member.get('usage_thread_id',thread),
                    member.get('usage_goal_created_at',member['goal_created_at']),
                    token_accounting=allocation['token_accounting'],
                    reset_anchor=member.get('usage_reset_anchor',member.get('reset_anchor')),
                    session_scope=member.get('session_scope',False))
                if member.get('usage_thread_id') and thread not in observation.get('thread_ids',[]):
                    return dict(state='unknown',used_tokens=None,reason='successor_lineage_unavailable')
            if observation['state']!='qualified':
                return dict(state='unknown',used_tokens=None,reason='allocation_member_accounting_unknown',
                    member_thread_id=thread,member_reason=observation.get('reason'))
            qualified_threads.update(observation.get('thread_ids', [thread]))
            for key,value in observation['charges'].items():
                if key in charges and charges[key]!=value:
                    return dict(state='unknown',used_tokens=None,reason='allocation_response_conflict')
                charges[key]=value
        if any(charges.get(key)!=value for key,value in allocation['charges'].items()):
            return dict(state='unknown',used_tokens=None,reason='allocation_history_changed')
        used=sum(value['tokens'] for value in charges.values())
        allocation.update(charges=charges,used_tokens=used)
        from .goal_time import merge_allocation
        merge_allocation(receipt,allocation)
        _save(path,allocation)
        task_observation=None
        task_owner=allocation['members'][receipt['thread_id']].get('task_owner_thread_id',receipt['thread_id'])
        if allocation['members'].get(task_owner,{}).get('task_window'):
            task=allocation['members'][task_owner]['task_window']
            task_observation=observe_usage(receipt['grant']['codex_home'],task.get('thread_id',task_owner),task['goal_created_at'],
                reset_anchor=task['reset_anchor'],token_accounting=allocation['token_accounting'],session_scope=True)
            if task_observation.get('state')!='qualified':return task_observation
            receipt.update(task_window=task,shared_limits=dict(token_limit=allocation['token_limit'],
                deadline=allocation['deadline'],used_tokens=used,time_limit_seconds=allocation['time_limit_seconds']),
                token_limit=task['token_limit'],deadline=task['deadline'],time_origin=task['time_origin'],
                time_limit_seconds=task['time_limit_seconds'],lifetime_tokens_before_window=task['lifetime_tokens_before_window'])
            receipt['limiting_scope']='shared' if used>=allocation['token_limit'] else 'task'
        else:
            receipt.update(token_limit=allocation['token_limit'],deadline=allocation['deadline'])
        if allocation.get('first_stop'):
            key='first_stop' if allocation['first_stop'].get('receipt_generation')==receipt['generation'] else 'allocation_first_stop'
            receipt.setdefault(key,allocation['first_stop'])
        if allocation['stop_latched']:
            receipt['stop_latched']=True
            if receipt.get('reason') is None:receipt['reason']=allocation.get('stop_reason','continuation_held')
        if allocation.get('pending_recovery'):
            receipt['reason']='observation_unavailable'
            receipt['active_stop_id']=allocation['pending_recovery'].get('stop_episode_id')
        if 'winddown_deadline' in allocation:
            receipt['allocation_winddown_deadline']=allocation['winddown_deadline']
        if task_observation is not None:
            return dict(task_observation,shared_used_tokens=used,member_thread_ids=sorted(allocation['members']))
        return dict(state='qualified',used_tokens=used,token_accounting=allocation['token_accounting'],
            renewed_out_tokens=sum(value['tokens'] for value in allocation.get('renewed_out_charges',{}).values()),
            member_thread_ids=sorted(allocation['members']),thread_ids=sorted(qualified_threads),sampled=True,reason=None)


def _accounting_decreased(receipt,observation):
    # Net spending can fall only when explicit host renewal transfers response
    # charges out. Compare gross spending so each receipt consumes that durable
    # transfer once, without hiding an unexplained loss of accounting history.
    prior=receipt.get('accounting',{}).get('renewed_out_tokens',0)
    current=observation.get('renewed_out_tokens',0)
    if type(prior) is not int or type(current) is not int or not 0<=prior<=current:
        return True
    return observation['used_tokens']+current<receipt['used_tokens']+prior


def _heartbeat(directory):
    from . import measurements
    try:
        path=directory/'controller.json';_private(path)
        value=json.loads(path.read_text())
        age=measurements.elapsed_bounds(value['clock_observation'],measurements.snapshot())[1]
        valid=(value['active'] is True and value['pid']!=os.getpid()
            and value['boot_id']==boot_id_value() and process_exists(value['pid'])
            and process_identity(value['pid'])==value['identity']
            and 0<=age<=max(3,3*value['interval']))
        return dict(value,fresh=valid,age_seconds=age,process_alive=process_exists(value['pid']) and process_identity(value['pid'])==value['identity'])
    except (OSError,ValueError,KeyError,TypeError):return dict(fresh=False,reason='controller_unavailable')


def _controller_clock():
    from . import measurements
    try:
        return measurements.snapshot()
    except measurements.TimeUnavailable:
        return None


def show(root,policy_path,caller_thread_id,allocation_id=None,*,permission_principal=None,native_context=None):
    from .permission_enforcement import principal_for, authorize, describe
    principal=principal_for(root,caller_thread_id,native_context=native_context,principal=permission_principal)
    if principal:authorize(root,"session.inspect",principal)
    name=_name(caller_thread_id);grant=_grant(policy_path,caller_thread_id,allocation_id,root)
    directory=_directory(root);path=directory/(name+'.json')
    if not path.exists():
        controller=_heartbeat(directory)
        from .goal_readiness import engagement
        return dict(state='held',reason='not_enrolled',thread_id=caller_thread_id,controller=controller,
            engagement=engagement({},controller))
    with _lock(directory,'maintenance'), _lock(directory,name):
        _private(path);receipt=json.loads(path.read_text())
        pending_recovery=None
        if receipt.get('allocation_path'):
            ledger_path=Path(receipt['allocation_path']);_private(ledger_path)
            with _lock(ledger_path.parent,ledger_path.stem):
                ledger=json.loads(ledger_path.read_text())
            from .goal_governance import sync
            sync(receipt)
            pending_recovery=ledger.get('pending_recovery')
            if pending_recovery:
                receipt.update(state='held',reason='recovery_pending_reconciliation',stop_latched=True)
            elif ledger.get('stop_latched'):
                receipt['stop_latched']=True
                if receipt['state'] in ('armed','checkpoint_requested'):
                    receipt.update(state='held',reason=ledger.get('stop_reason','continuation_held'))
        from .goal_renewal import renewal_hold
        pending=renewal_hold(root,receipt)
        if pending and not pending_recovery:
            from .goal_readiness import engagement
            return dict(_public(receipt),**pending,engagement=engagement(dict(receipt,**pending),_heartbeat(directory)))
        if receipt['grant']!=grant:
            receipt.update(state='held',reason='host_policy_changed')
        receipt['controller']=_heartbeat(directory)
        permit_path=directory/'maintenance/permit.json'
        if permit_path.exists():
            _private(permit_path)
            permit=json.loads(permit_path.read_text())
            if (permit.get('state') in ('prepared','handoff','unqualified')
                    and receipt.get('state') in ('armed','checkpoint_requested')
                    and not receipt.get('stop_latched')):
                from .goal_maintenance import window
                decision=window(directory,permit)
                if decision['state']!='expired' or permit.get('state')=='unqualified':
                    receipt.update(state='held',reason='maintenance_clock_unqualified'
                        if decision['state']=='unqualified' or permit.get('state')=='unqualified' else 'controller_maintenance')
        if receipt['state'] in ('armed','checkpoint_requested') and not receipt['controller']['fresh']:
            receipt.update(state='held',reason='controller_unavailable')
        receipt['sampled']=True;receipt['maximum_token_overshoot']=None
        from .goal_readiness import engagement
        result=_public(receipt)
        from .goal_notices import governor_status
        result['governor']=governor_status(root,receipt)
        if receipt.get('stop_latched'):
            observation_fault=receipt.get('reason')=='observation_unavailable'
            result['recovery']=dict(status='requires_authorized_recovery' if observation_fault else 'not_recoverable',
                action='wake_goal_limits_recover' if observation_fault else None,
                next_action='Request explicit scoped recovery; healthy reads or native resume alone do not clear supervision. Original resource limits remain.' if observation_fault else 'Keep this stop; observation recovery cannot clear exhaustion, accounting, policy or clock failures.')
        if pending_recovery:
            result['recovery']=dict(status='pending_reconciliation',action='wake_goal_limits_recover',
                operation_id=pending_recovery.get('operation_id'),
                next_action='Retry the same explicitly authorized recovery operation; the allocation remains held.')

        result['engagement']=engagement(receipt,receipt['controller'])
        event_id=receipt.get('notice_ids',{}).get('engagement')
        if event_id:
            try:
                from .goal_notices import read_notice
                notice=read_notice(root,event_id)
                result['engagement']['presentation']=notice['delivery']['state']
                result['engagement']['presentation_proof']=notice['proof']
                if notice['delivery']['state']=='unsupported':
                    result['engagement']['visibility_status']='runtime_visibility_unsupported'
                    result['engagement']['presentation_next_action']=notice['delivery'].get('next_action')
            except (OSError,ValueError,KeyError):
                result['engagement']['presentation']='unavailable'
        if principal:result['enforcement_permissions']=describe(root,caller_thread_id,principal=principal)
        return result


class AccountingUnavailable(ValueError):
    code='goal_accounting_unavailable'

    def __init__(self,message,observation):
        super().__init__(message)
        self.accounting_reason=observation.get('member_reason') or observation.get('reason') or 'unqualified_history'


def diagnose(root,policy_path,caller_thread_id,allocation_id=None,*,permission_principal=None,native_context=None):
    """Read original history and actual watcher without enrolling or changing authority."""
    from .permission_enforcement import principal_for,authorize
    principal=principal_for(root,caller_thread_id,native_context=native_context,principal=permission_principal)
    if principal:authorize(root,'session.inspect',principal)
    grant=_grant(policy_path,caller_thread_id,allocation_id,root)
    if grant.get('host_delegated'):verified_native_caller(native_context,caller_thread_id)
    goal,active=_native(grant,caller_thread_id)
    from .goal_usage import observe_usage
    if not goal:
        accounting=dict(state='unknown',reason='native_goal_missing')
    else:
        accounting=observe_usage(grant['codex_home'],caller_thread_id,goal['createdAt'],token_accounting='fresh')
    controller=_heartbeat(_directory(root))
    status=('accounting_unavailable' if accounting.get('state')!='qualified' else
            'watcher_ready' if controller.get('fresh') else 'watcher_unavailable')
    action=('Inspect original response-level usage and native writer compatibility. first_usage_unavailable can mean no completed response or an unsupported native usage writer; display totals cannot qualify accounting. Preserve history without synthesizing records or resetting usage.'
            if status=='accounting_unavailable' else
            'Enroll the existing session with the user-approved limits; registration does not itself prove engagement.'
            if status=='watcher_ready' else
            'Run goal-limits watcher-status, then start-watcher with existing authority if the configured service is unmasked.')
    return dict(thread_id=caller_thread_id,allocation_id=grant['allocation_id'],
        enrolled=(_directory(root)/(_name(caller_thread_id)+'.json')).exists(),
        native_goal_status=goal.get('status') if goal else None,active_turn_count=len(active),
        accounting={key:accounting[key] for key in ('state','reason','used_tokens','token_accounting') if key in accounting},
        controller=controller,readiness=dict(status=status,next_action=action),effect_attempted=False)


def enroll(root,policy_path,caller_thread_id,token_limit,time_limit_seconds,
           checkpoint_token_percent=5,checkpoint_seconds=60,token_accounting=None,
           allocation_id=None,native_context=None,permission_principal=None,task_id=None,operation_id=None,session_scope=False,prepare_only=False,activation_baseline=False,requires_native_guard=False,replace_advisory=False):
    from .permission_enforcement import principal_for,authorize,enrollment_action
    principal=principal_for(root,caller_thread_id,native_context=native_context,principal=permission_principal)
    name=_name(caller_thread_id);grant=_grant(policy_path,caller_thread_id,allocation_id,root)
    binding=verified_native_caller(native_context,caller_thread_id) if grant.get('host_delegated') else None
    for key,value,maximum in [('tokens',token_limit,grant['max_tokens']),('seconds',time_limit_seconds,grant['max_seconds'])]:
        if type(value) is not int or not 0<value<=maximum:raise ValueError('requested '+key+' exceed host allocation')
    if type(checkpoint_token_percent) not in (int,float) or not math.isfinite(checkpoint_token_percent) or not 0<=checkpoint_token_percent<=100:
        raise ValueError('invalid checkpoint token reserve')
    if type(checkpoint_seconds) not in (int,float) or not math.isfinite(checkpoint_seconds) or checkpoint_seconds<0:raise ValueError('invalid checkpoint time reserve')
    directory=_directory(root);path=directory/(name+'.json')
    if not path.exists() and not replace_advisory:
        from .goal_governance import control_path,control_snapshot
        if control_path(root,caller_thread_id).exists():return control_snapshot(root,caller_thread_id)
        if session_scope:
            native_control=_request(grant,'thread/read',dict(threadId=caller_thread_id,includeTurns=False))['thread']
            parent=native_control.get('parentThreadId')
            if not parent:
                from .goal_usage import observe_session_usage
                parent=observe_session_usage(grant['codex_home'],caller_thread_id).get('parent_thread_id')
            if parent and control_path(root,parent).exists() and not (directory/(_name(parent)+'.json')).exists():
                inherited=control_snapshot(root,parent)
                return dict(inherited,thread_id=caller_thread_id,control_inherited_from=parent,
                    reason='inherited_operator_'+inherited.get('governor_mode','disabled'),used_tokens=None,lifetime_used_tokens=None,
                    last_verified_usage={},accounting=dict(state='unknown',reason='inherited_inactive_control'))
    # Configured service repair is a distinct common-policy action. Never undo a
    # mask or infer authority from enrollment permission alone.
    from .goal_governance import sync
    if path.exists():
        with _lock(directory,name):
            _private(path);retained=json.loads(path.read_text())
            if sync(retained) and not (replace_advisory and retained.get('advisory_without_window')):return _public(retained)
    watcher_setup=None
    if not session_scope and principal and not _heartbeat(directory).get('fresh'):
        from .session_permissions import PermissionStore
        store=PermissionStore(root)
        if store.active() and store.evaluate('enforcement.watcher_start',principal,
                target=principal.subject,task_id=task_id,operation_id=operation_id)['permission']=='allow':
            from .goal_watcher import start_watcher
            watcher_setup=start_watcher(root,principal=principal,task_id=task_id,operation_id=operation_id)
    with _lock(directory,'maintenance'), _lock(directory,name):
        from .goal_maintenance import admission_guard
        admission_guard(directory)
        old=None
        if path.exists():_private(path);old=json.loads(path.read_text())
        prior_advisory=old if old and old.get('advisory_without_window') and replace_advisory else None
        if prior_advisory:old=None
        if old:
            if sync(old):return _public(old)
            from .goal_renewal import renewal_hold
            pending=renewal_hold(root,old)
            if pending:return dict(_public(old),**pending)
        permission=None
        if principal:
            action=enrollment_action(old,token_limit,time_limit_seconds,token_accounting,grant['allocation_id'])
            permission=authorize(root,action,principal,task_id=task_id,operation_id=operation_id)
        same=bool(old and old['allocation_id']==grant['allocation_id'])
        previous_basis=old.get('token_accounting','cache_inclusive') if old else None
        basis=token_accounting or (previous_basis if same else 'fresh')
        if basis not in ('fresh','cache_inclusive'):raise ValueError('unsupported token accounting')
        basis_changed=bool(same and previous_basis!=basis)
        if old and any(old['grant'][key]!=grant[key] for key in ('app_server','codex_home')):
            raise ValueError('cross-native session migration is unsupported')
        if same and (token_limit>old['token_limit'] or time_limit_seconds>old['time_limit_seconds']):
            raise ValueError('same allocation may only tighten limits')
        goal,active=_native(grant,caller_thread_id)
        if not goal and not session_scope:raise ValueError('existing native goal required')
        created=old['goal_created_at'] if old else goal['createdAt'] if goal else None
        if created is not None and (type(created) not in (int,float) or not math.isfinite(created)):raise ValueError('native goal start unavailable')
        # Qualify original history and time before persisting enrollment or
        # starting enforcement. Session scope does not require a native goal.
        fresh_usage=None;native_session=None
        if session_scope and not old:
            from .goal_usage import observe_session_usage
            fresh_usage=observe_session_usage(grant['codex_home'],caller_thread_id,token_accounting=basis)
            if fresh_usage.get('state')!='qualified':
                raise AccountingUnavailable('initial session accounting unavailable',fresh_usage)
            native_session=_request(grant,'thread/read',dict(threadId=caller_thread_id,includeTurns=False))['thread']
            if native_session.get('id')!=caller_thread_id:raise ValueError('native thread identity changed')
        allocation_path=directory/'allocations'/(hashlib.sha256(grant['allocation_id'].encode()).hexdigest()+'.json')
        allow_counter=bool(session_scope and not old and grant.get('auto_enrolled')
            and grant['allocation_id']=='native-'+caller_thread_id and not allocation_path.exists()
            and not grant.get('initial_boundary') and not (native_session or {}).get('parentThreadId')
            and not (fresh_usage or {}).get('parent_thread_id'))
        # A crash may publish the allocation before its session projection.
        # Its existing clock remains authoritative; retry never creates a window.
        clock_previous=old
        if session_scope and not old and allocation_path.exists():
            _private(allocation_path);retained_allocation=json.loads(allocation_path.read_text())
            if (retained_allocation.get('allocation_id')!=grant['allocation_id']
                    or retained_allocation.get('grant')!=grant
                    or caller_thread_id not in retained_allocation.get('members',{}) and not activation_baseline):
                raise ValueError('qualified existing allocation clock required')
            clock_previous=retained_allocation
        from .goal_time import admit, relative
        now,time_fields=admit(clock_previous,allow_counter=allow_counter)
        from .goal_time import controller_compatible, singleton_held
        controller=_heartbeat(directory)
        new_semantics=relative(time_fields) or session_scope and goal is None
        if new_semantics:
            held=singleton_held(directory)
            compatible=controller_compatible(dict(time_fields,session_scope=session_scope,
                native_goal_status=goal.get('status') if goal else None),controller)
            if held or controller.get('process_alive'):
                if not controller.get('fresh') or not compatible or not held:
                    raise ValueError('existing watcher owner is stale or lacks required session/time capabilities; upgrade its exact owner without starting a competing watcher')
            elif not prepare_only:
                raise ValueError('compatible watcher must be qualified before publishing session/time enrollment')
        boottime=time.clock_gettime(time.CLOCK_BOOTTIME)
        if not relative(time_fields) and created is not None and created>now:
            raise ValueError('native goal start is after qualified current time')
        receipt=dict(old) if same else dict(thread_id=caller_thread_id,generation=uuid4().hex,
            allocation_id=grant['allocation_id'],goal_created_at=created,used_tokens=0,
            started_upper=now,started_boottime=boottime,boot_id=boot_id_value(),
            time_origin=now if old or created is None or allow_counter or activation_baseline else created,effects={},checkpoint=None,
            prior_allocation=old if old else None)
        receipt.update(time_fields)
        if prior_advisory:receipt['prior_advisory_control']=prior_advisory
        if requires_native_guard:receipt['requires_native_guard']=True
        if session_scope and not old:
            receipt['session_scope']=True
        receipt.update(caller_binding=binding,grant=grant,policy_path=str(Path(policy_path).absolute()),token_limit=token_limit,
            time_limit_seconds=time_limit_seconds,checkpoint_token_percent=checkpoint_token_percent,
            checkpoint_seconds=checkpoint_seconds)
        if basis_changed:
            receipt.setdefault('accounting_basis_history',[]).append(dict(
                token_accounting=previous_basis,used_tokens=old['used_tokens'],accounting=old.get('accounting')))
        receipt['token_accounting']=basis
        receipt['deadline']=receipt['time_origin']+time_limit_seconds
        authority_fields=('generation','token_limit','deadline','token_accounting','checkpoint_token_percent','checkpoint_seconds')
        if not same or any(old.get(key)!=receipt.get(key) for key in authority_fields):
            receipt['enrollment_revision']=old.get('enrollment_revision',0)+1 if same else 1
            receipt.pop('poll_ack',None)
        else:receipt.setdefault('enrollment_revision',1)
        prior_guard=(old or {}).get('native_guard',{})
        from .goal_native_guard import qualified as guard_qualified
        guard_stale=(prior_guard.get('status') in ('expired','lost','released') or
            prior_guard.get('status')=='armed' and
            (prior_guard.get('controller_generation')!=controller.get('generation') or
             not guard_qualified(old)))
        if old and requires_native_guard and guard_stale:
            receipt['enrollment_revision']+=1
            receipt.pop('poll_ack',None)
        if grant.get('auto_enrolled') and grant['allocation_id']=='native-'+caller_thread_id and not old:
            from .goal_usage import observe_usage
            native=_request(grant,'thread/read',dict(threadId=caller_thread_id,includeTurns=False))['thread']
            if native.get('id')!=caller_thread_id:raise ValueError('native thread identity changed')
            parent=native.get('parentThreadId')
            if not parent:
                first=observe_usage(grant['codex_home'],caller_thread_id,created,token_accounting=basis,
                    session_scope=receipt.get('session_scope',False))
                if first.get('state')!='qualified':raise AccountingUnavailable('first enrollment requires qualified original history',first)
                parent=first.get('parent_thread_id')
            if parent:
                if allocation_id is not None:
                    raise ValueError('successor must continue its existing objective allocation, not select a fresh one')
                source=directory/(_name(parent)+'.json')
                if not source.exists():
                    raise ValueError('successor allocation is unavailable; inspect the verified source continuation')
                _private(source);predecessor=json.loads(source.read_text())
                if predecessor.get('thread_id')!=parent:
                    raise ValueError('successor source identity changed')
                if native.get('parentThreadId'):
                    usage_thread=predecessor.get('usage_thread_id',parent)
                    usage_created=predecessor.get('usage_goal_created_at',predecessor['goal_created_at'])
                    usage_anchor=predecessor.get('usage_reset_anchor',predecessor.get('reset_anchor'))
                    original=observe_usage(grant['codex_home'],usage_thread,usage_created,
                        reset_anchor=usage_anchor,token_accounting=predecessor['token_accounting'],
                        session_scope=predecessor.get('session_scope',False))
                    if original.get('state')!='qualified' or caller_thread_id not in original.get('thread_ids',[]):
                        raise AccountingUnavailable('successor requires qualified original objective lineage',original)
                    receipt.update(usage_thread_id=usage_thread,usage_goal_created_at=usage_created,
                        usage_reset_anchor=usage_anchor)
                if predecessor.get('requires_native_guard'):receipt['requires_native_guard']=True
                if predecessor.get('task_window'):
                    receipt.update(task_window=predecessor['task_window'],
                        task_owner_thread_id=predecessor.get('task_owner_thread_id',parent))
                inherited=_grant(policy_path,caller_thread_id,predecessor['allocation_id'],root)
                if any(inherited[key]!=grant[key] for key in ('app_server','codex_home','codex_path')):
                    raise ValueError('cross-native successor allocation is unsupported')
                # This remains the caller's explicit supervision request. Select
                # its qualified existing allocation without creating a new window
                # or asking the operator to copy an internal allocation identity.
                grant=inherited
                if token_accounting is None:
                    basis=predecessor.get('token_accounting','cache_inclusive')
                    receipt['token_accounting']=basis
                receipt.update(grant=grant,allocation_id=grant['allocation_id'],
                    continuation_source_thread_id=parent)
        # A new ordinary window excludes qualified pre-activation charges while
        # retaining lifetime evidence. Existing allocations/continuations keep
        # their original owner boundary; activation cannot renew shared limits.
        if activation_baseline and not old and not receipt.get('continuation_source_thread_id') and not allocation_path.exists():
            if not session_scope or not fresh_usage or fresh_usage.get('state')!='qualified':
                raise ValueError('activation baseline requires qualified session accounting')
            receipt.update(goal_created_at=fresh_usage['anchor']['goal_created_at'],reset_anchor=fresh_usage['anchor'],
                lifetime_tokens_before_window=fresh_usage['used_tokens'],
                activation_baseline=True)
        if activation_baseline and grant.get('host_delegated') and not old and not receipt.get('continuation_source_thread_id'):
            receipt['activation_baseline']=True
            receipt['task_window']=dict(thread_id=caller_thread_id,token_limit=token_limit,time_limit_seconds=time_limit_seconds,
                time_origin=now,deadline=now+time_limit_seconds,reset_anchor=fresh_usage['anchor'],
                goal_created_at=fresh_usage['anchor']['goal_created_at'],session_scope=True,
                lifetime_tokens_before_window=fresh_usage['used_tokens'],generation=receipt['generation'],revision=1)
        elif old and old.get('task_window'):
            receipt['task_window']=dict(old['task_window'],token_limit=token_limit,
                time_limit_seconds=time_limit_seconds,deadline=old['task_window']['time_origin']+time_limit_seconds)
        if grant.get('host_delegated'):_allocation_admit(directory,receipt,old,commit=not prepare_only)
        if receipt.get('task_window'):
            receipt.update({key:receipt['task_window'][key] for key in ('token_limit','deadline','time_limit_seconds','time_origin','lifetime_tokens_before_window')})
        retained_allocation=not receipt.get('allocation_path') or Path(receipt['allocation_path']).exists()
        if retained_allocation and sync(receipt):
            if not prepare_only:
                _record_supervision_notice(path,receipt,'deactivation')
                _save(path,receipt)
            return _public(receipt)
        observation=fresh_usage if prepare_only and (not retained_allocation or session_scope and not old) else _usage(receipt)
        if prepare_only and receipt.get('activation_baseline') and not old:
            observation=dict(observation,used_tokens=0,charges={})
        # Enrollment is not admitted until the first complete observation is
        # qualified. A transient setup scan must not publish a stop receipt that
        # only a resource renewal could clear. Existing campaigns still fail
        # closed through their normal accounting/winddown path.
        if (not old and observation.get('state')!='qualified' and
                (observation.get('reason')=='usage_scan_time_limit' or
                 observation.get('reason')=='allocation_member_accounting_unknown' and
                 observation.get('member_reason')=='usage_scan_time_limit')):
            raise AccountingUnavailable('initial accounting unavailable; enrollment not admitted',observation)
        if basis_changed and observation.get('state')!='qualified':
            raise ValueError('accounting basis change requires qualified original history')
        if old and not same and not grant.get('host_delegated'):
            if observation.get('state')!='qualified' or not observation.get('anchor'):
                raise ValueError('explicit reset requires qualified response history')
            receipt['reset_anchor']=observation['anchor']
            observation=_usage(receipt)
        if prepare_only:
            if observation.get('state')!='qualified' or _accounting_decreased(receipt,observation):
                raise AccountingUnavailable('initial session accounting unavailable',observation)
            if receipt.get('stop_latched'):
                return dict(_public(old or receipt),state='held',reason=receipt.get('reason') or 'continuation_held')
            receipt.update(accounting=observation,used_tokens=observation['used_tokens'],
                native_goal_status=goal.get('status') if goal else None)
            return dict(_public(receipt),state='prepared',reason=None,admitted=False,effect_attempted=False)
        def hold(reason):
            _first_stop(path,receipt,reason)
            receipt.update(state='held',reason=reason,stop_latched=True)
        if observation.get('state')=='qualified' and type(observation.get('used_tokens')) is int:
            if not basis_changed and _accounting_decreased(receipt,observation):
                receipt['accounting']=observation;hold('accounting_decreased')
            else:
                receipt.update(used_tokens=observation['used_tokens'],accounting=observation,state='armed',reason=None,
                    qualified_task_members=observation.get('thread_ids',[caller_thread_id]))
                receipt['last_verified_usage']=dict(generation=receipt['generation'],used_tokens=receipt['used_tokens'],
                    lifetime_used_tokens=receipt.get('lifetime_tokens_before_window',0)+receipt['used_tokens'],elapsed_seconds=max(0,now-receipt['time_origin']))
        else:
            receipt['accounting']=observation;hold('accounting_unknown')
        controller=_heartbeat(directory);receipt['controller_generation']=controller.get('generation')
        if not controller['fresh']:receipt.update(state='held',reason='controller_unavailable')
        shared=receipt.get('shared_limits')
        if shared and (shared['used_tokens']>=shared['token_limit'] or now>=shared['deadline']):
            hold('allocation_exhausted')
        elif receipt.get('used_tokens',0)>=token_limit or now>=receipt['deadline']:
            hold('task_exhausted' if receipt.get('task_window') else 'allocation_exhausted')
        if receipt.get('stop_latched') or (same and old['state'] in ('stopped','stop_unverified')):
            hold('continuation_held')
        if receipt['boot_id']!=boot_id_value():
            hold('boot_identity_changed')
        if permission:
            receipt['enforcement_permission']=permission
            receipt['permission_subject']=principal.subject
        receipt['native_goal_status']=goal.get('status') if goal else None
        if watcher_setup is not None:receipt['watcher_setup']=watcher_setup
        if (goal is not None or not session_scope) and (goal or {}).get('status') not in NATIVE_GOAL_STATUSES:
            hold('native_goal_state_unknown')
        _record_supervision_notice(path,receipt,'activation',controller)
        _save(path,receipt)
        if receipt.get('requires_native_guard'):
            from .goal_native_guard import arm
            exhausted=receipt.get('first_stop',{}).get('reason') in ('allocation_exhausted','task_exhausted','continuation_held')
            retain_guard=bool(same and old.get('state') in ('armed','checkpoint_requested')
                and receipt.get('state') in ('armed','checkpoint_requested')
                and not receipt.get('stop_latched')
                and old.get('enrollment_revision')==receipt.get('enrollment_revision')
                and prior_guard.get('controller_generation')==controller.get('generation')
                and guard_qualified(receipt))
            if retain_guard:guarded=True
            elif not receipt.get('stop_latched') or exhausted:
                guarded=arm(path,receipt,force=True,stop=bool(receipt.get('stop_latched')))
            else:guarded=False
            if not guarded:
                receipt.update(state='held',reason=receipt.get('native_guard',{}).get('reason','native_guard_unavailable'))
                _save(path,receipt)
        from .goal_readiness import engagement
        from .goal_notices import governor_status
        return dict(_public(receipt),controller=controller,sampled=True,maximum_token_overshoot=None,
            governor=governor_status(root,receipt),engagement=engagement(receipt,controller))


def _effect(path,receipt,key,method,params,*,locked_allocation=None):
    from .goal_governance import sync
    if sync(receipt,locked_allocation=locked_allocation):return False
    if method=='turn/steer':
        from .permission_enforcement import controller_permission
        permission=controller_permission(path.parent.parent,receipt)
        receipt['enforcement_continuation_permission']=permission
        if permission['permission'] not in ('allow','legacy'):
            receipt['permission_effect_blocked']=True
            _save(path,receipt)
            return False
    effects=receipt.setdefault('effects',{})
    if key in effects:return effects[key]['state']=='acknowledged'
    effects[key]=dict(state='intended',method=method,params=params)
    _save(path,receipt)
    try:
        _request(receipt['grant'],method,params)
        effects[key]['state']='acknowledged';_save(path,receipt)
        return True
    except Exception as exc:
        effects[key].update(state='uncertain',error=type(exc).__name__);_save(path,receipt)
        return False


def _allocation_latch(receipt,reason,deadline=None):
    if not receipt.get('allocation_path'):return deadline
    if reason=='task_exhausted' or reason=='continuation_held' and receipt.get('first_stop',{}).get('reason')=='task_exhausted':return deadline
    path=Path(receipt['allocation_path']);_private(path)
    with _lock(path.parent,path.stem):
        allocation=json.loads(path.read_text())
        if receipt.get('first_stop'):
            allocation.setdefault('first_stop',receipt['first_stop'])
        known={event['id'] for event in allocation.setdefault('stop_episodes',[])}
        allocation['stop_episodes'].extend(event for event in receipt.get('stop_episodes',[]) if event['id'] not in known)
        inherited=reason in (None,'continuation_held') and allocation.get('stop_latched')
        allocation.update(stop_latched=True)
        if not inherited:allocation['stop_reason']=reason
        if deadline is not None:
            deadline=min(deadline,allocation.get('winddown_deadline',deadline))
            allocation['winddown_deadline']=deadline
            receipt['allocation_winddown_deadline']=deadline
        _save(path,allocation)
    return deadline


def _stop_clock(receipt,reason):
    """A protective stop remains writable without a qualified timestamp."""
    from .goal_time import upper, relative, GoalTimeUnavailable
    observed=None
    clock_reason='clock_unqualified'
    if receipt['boot_id']!=boot_id_value():
        clock_reason='boot_identity_changed'
    elif reason!='clock_unqualified' and receipt.get('clock_failure')!='clock_unqualified':
        try:
            observed=upper(receipt)
            clock_reason='authenticated_host_counter' if relative(receipt) else 'qualified_utc'
        except GoalTimeUnavailable as error:
            clock_reason=error.code
    return dict(observed_boottime=None,
        observed_upper=observed if not relative(receipt) else None,
        clock_qualified=observed is not None,clock_reason=clock_reason)


def _stop_episode(path,receipt,reason):
    """Retain distinct faults across recovery without rewriting the first stop."""
    episodes=receipt.setdefault('stop_episodes',[])
    active=next((event for event in episodes if event['id']==receipt.get('active_stop_id')),None)
    if active is not None and active['reason']==reason:return
    controller=_heartbeat(path.parent)
    event=dict(id=uuid4().hex,kind='stop',reason=reason,receipt_generation=receipt['generation'],
        allocation_id=receipt['allocation_id'],boot_id=boot_id_value(),
        controller_generation=controller.get('generation'),used_tokens=receipt.get('used_tokens'),
        token_limit=receipt['token_limit'],deadline=receipt['deadline'],
        native_method=receipt.get('observation_method') if reason=='observation_unavailable' else None,
        cause=receipt.get('observation_error') if reason=='observation_unavailable' else None)
    from .goal_time import public_time
    event.update(_stop_clock(receipt,reason))
    event.update(public_time(receipt))
    episodes.append(event);receipt['active_stop_id']=event['id']


def _first_stop(path,receipt,reason):
    if 'first_stop' in receipt:return
    original=None
    if receipt.get('allocation_path'):
        allocation_path=Path(receipt['allocation_path']);_private(allocation_path)
        with _lock(allocation_path.parent,allocation_path.stem):
            retained=json.loads(allocation_path.read_text()).get('first_stop')
            if retained and retained.get('receipt_generation')==receipt['generation']:
                original=retained
    clock=_stop_clock(receipt,reason) if original is None else original
    qualified=clock['clock_qualified']
    clock_unqualified=not qualified
    try:
        controller_path=path.parent/'controller.json';_private(controller_path)
        controller=json.loads(controller_path.read_text())
    except (OSError,ValueError):controller={}
    # Old latches cannot reveal their original fault retrospectively. Label the
    # first retained diagnostic explicitly instead of inventing that history.
    receipt['first_stop']=original or dict(version=1,reason=reason,
        provenance='existing_latch_observed' if receipt.get('stop_latched') else 'stop_decision',
        observed_boottime=None,boot_id=boot_id_value(),
        observed_upper=clock.get('observed_upper'),
        clock_qualified=qualified,clock_reason=clock['clock_reason'],
        last_usage_observed_boottime=receipt.get('observed_boottime'),
        controller_observed_boottime=controller.get('observed_boottime'),
        controller_generation=controller.get('generation',receipt.get('controller_generation')),
        controller_pid=controller.get('pid'),controller_identity=controller.get('identity'),
        receipt_generation=receipt['generation'],allocation_id=receipt['allocation_id'],
        used_tokens=receipt.get('used_tokens'),token_limit=receipt['token_limit'],
        deadline=receipt['deadline'],token_accounting=receipt.get('token_accounting'),
        accounting_state=receipt.get('accounting',{}).get('state'),
        native_method=receipt.get('observation_method') if reason=='observation_unavailable' else None,
        cause=receipt.get('observation_error') if reason=='observation_unavailable' else None,
        observation_duration_seconds=receipt.get('observation_duration_seconds') if reason=='observation_unavailable' else None)
    from .goal_time import relative, public_time
    if relative(receipt) and original is None:
        diagnostic=receipt['first_stop']
        diagnostic.update(public_time(receipt), observed_upper=None,
            observed_elapsed_upper=receipt.get('clock_elapsed_upper'),
            clock_qualified=qualified and reason not in ('counter_continuity_lost','authenticated_elapsed_unavailable'),
            clock_reason='clock_unqualified' if clock_unqualified else reason if reason in ('counter_continuity_lost','authenticated_elapsed_unavailable') else 'authenticated_host_counter')
    receipt.update(stop_latched=True,state='stop_unverified',reason=reason)
    # The shared ledger is the authority for successor admission. Commit its
    # latch first, so a crash during the caller receipt write cannot reopen it.
    _allocation_latch(receipt,reason)
    _save(path,receipt)


def _record_supervision_notice(path,receipt,kind,controller=None):
    # Local durable intent only. Delivery is a separate worker so native/UI
    # failure cannot delay this campaign's or a peer's pause/interrupt.
    try:
        from .goal_notices import record_notice
        event=record_notice(path.parent.parent,receipt,kind,controller=controller)
        receipt.setdefault('notice_ids',{})[kind]=event['event_id']
    except Exception as error:
        receipt['notice_record_error']=type(error).__name__



def _stop(path,receipt,reason,goal=None,active=None):
    from .goal_governance import sync
    if sync(receipt):return dict(receipt,state='inactive')
    _stop_episode(path,receipt,reason)
    _first_stop(path,receipt,reason)
    receipt.update(reason=reason,state='stop_unverified',stop_latched=True)
    if receipt.get('requires_native_guard'):
        # The native owner retains actual goal identity and automatic-turn
        # attribution. Never recapture a later operator reply from this session.
        from .goal_native_guard import expire
        _allocation_latch(receipt,reason)
        expire(path,receipt,reason)
        _record_supervision_notice(path,receipt,'stop')
        _save(path,receipt)
        return receipt
    _allocation_latch(receipt,reason)
    try:
        if active is None:goal,active=_native(receipt['grant'],receipt['thread_id'])
        # Enforcement owns the campaign turn observed at stop, not every later
        # operator turn in this conversation. Persist before native effects.
        if 'stop_turns' not in receipt or (receipt.get('pause_observed') and goal and goal.get('status')=='active'):
            legacy_turns = {effect.get('params', {}).get('turnId') or
                effect.get('params', {}).get('expectedTurnId') for effect in receipt.get('effects', {}).values()
                if effect.get('method') in ('turn/interrupt', 'turn/steer')}
            owned_scope=bool(receipt.get('session_scope') or goal and goal.get('status')=='active')
            receipt['stop_scope_observed']=owned_scope
            receipt['stop_turns']=list(active) if owned_scope else sorted(legacy_turns - {None})
            _save(path,receipt)
        if receipt.get('pause_observed') and goal and goal.get('status')!='paused':
            # Observed paused -> active is a new enforcement event, even if a
            # previous interrupt was unverified. Retain the old effect ledger.
            receipt['pause_epoch']=receipt.get('pause_epoch',0)+1
            receipt['pause_observed']=False
        if receipt.get('stop_proof') and ((goal and goal.get('status')!='paused') or active):
            receipt['stop_proof']=False
        thread=receipt['thread_id']
        if goal and goal.get('status')!='paused':
            _effect(path,receipt,'pause:'+str(goal['createdAt'])+':'+str(receipt.get('pause_epoch',0)),
                'thread/goal/set',dict(threadId=thread,status='paused',origin='automatic'))
        for turn in active:
            if turn not in receipt['stop_turns']:continue
            _effect(path,receipt,'interrupt:'+turn,'turn/interrupt',dict(threadId=thread,turnId=turn))
        final_goal,final_active=_native(receipt['grant'],thread)
        proven=((not final_goal or final_goal.get('status')=='paused')
            and not set(final_active).intersection(receipt['stop_turns'])
            and (receipt.get('stop_scope_observed',False) or not final_active))
        receipt.update(state='stopped' if proven else 'stop_unverified',stop_proof=proven,
            pause_observed=not final_goal or final_goal.get('status')=='paused')
    except Exception as exc:receipt['control_error']=type(exc).__name__
    descendants = _stop_descendants(path, receipt)
    receipt['descendant_stop_verified'] = descendants
    if not descendants and receipt.get('qualified_task_members'):
        receipt.update(state='stop_unverified',stop_proof=False)
    _record_supervision_notice(path,receipt,'stop')
    _save(path,receipt)
    return receipt



def _stop_descendants(path, receipt):
    """Stop only the original-history qualified tree, journaling exact turns.

    Later operator replies are outside captured campaign work. Unknown lineage
    cannot be substituted with a process kill or an unrelated loaded session.
    """
    members = receipt.get('qualified_task_members')
    if not isinstance(members, list) or receipt['thread_id'] not in members:
        return False
    verified = True
    for member in members:
        if member == receipt['thread_id']:
            continue
        try:
            _name(member)
            goal, active = _native(receipt['grant'], member)
            stop = receipt.setdefault('descendant_stops', {}).setdefault(member,
                dict(turns=list(active), goal_created_at=goal.get('createdAt') if goal else None))
            _save(path, receipt)
            if (goal.get('createdAt') if goal else None) != stop['goal_created_at']:
                raise ValueError('descendant native goal changed; preserve the captured scope')
            if goal and goal.get('status') != 'paused':
                _effect(path, receipt, 'descendant-pause:'+member, 'thread/goal/set',
                    dict(threadId=member,status='paused',origin='automatic'))
            for turn in set(active).intersection(stop['turns']):
                _effect(path, receipt, 'descendant-interrupt:'+member+':'+turn, 'turn/interrupt',
                    dict(threadId=member,turnId=turn))
            observed, running = _native(receipt['grant'], member)
            stop['verified'] = ((not observed or observed.get('status') == 'paused')
                and not set(running).intersection(stop['turns']))
            verified = verified and stop['verified']
        except Exception as error:
            receipt.setdefault('descendant_stop_errors', {})[member] = type(error).__name__
            verified = False
    return verified

def _wind_down(path, receipt, reason, goal, active, upper):
    """Pause autonomous continuation, allow a bounded checkpoint, then stop work.

    Qualification loss cannot authorize more product work. The reserve permits
    only winddown, never extends the original deadline, and survives retries.
    """
    if receipt.get('requires_native_guard'):return _stop(path,receipt,reason,goal,active)
    if 'winddown_deadline' not in receipt:
        _first_stop(path,receipt,reason)
        deadline=min(receipt['deadline'],upper+min(60,receipt['checkpoint_seconds']))
        receipt['winddown_deadline']=_allocation_latch(receipt,reason,deadline)
        receipt['stop_turns'] = list(active) if receipt.get('session_scope') or goal and goal.get('status') == 'active' else []
        receipt['winddown_reason'] = reason
        _save(path, receipt)
    owned = set(active).intersection(receipt['stop_turns'])
    if upper >= receipt['winddown_deadline'] or not owned:
        return _stop(path, receipt, reason, goal, active)
    receipt.update(state='winding_down', reason=reason, stop_latched=True)
    if not receipt.get('checkpoint'):
        receipt['checkpoint'] = dict(state='queued', message=
            'Campaign enforcement cannot qualify continuation. Stop product work and write a '
            'restart-safe checkpoint within the remaining grace period. The goal is paused; '
            'operator messages remain available. Do not reset or resume the allocation.')
        _save(path, receipt)
    if goal and goal.get('status') == 'active':
        if receipt.get('pause_observed'):
            receipt['pause_epoch'] = receipt.get('pause_epoch', 0) + 1
            receipt['pause_observed'] = False
            _save(path, receipt)
        _effect(path, receipt, 'pause:' + str(goal['createdAt']) + ':' + str(receipt.get('pause_epoch', 0)),
            'thread/goal/set', dict(threadId=receipt['thread_id'], status='paused', origin='automatic'))
        observed, _ = _native(receipt['grant'], receipt['thread_id'])
        receipt['pause_observed'] = not observed or observed.get('status') == 'paused'
        _save(path, receipt)
    if receipt['checkpoint']['state'] == 'queued':
        turn = next(turn for turn in active if turn in owned)
        delivered = _effect(path, receipt, 'checkpoint:' + turn, 'turn/steer',
            dict(threadId=receipt['thread_id'], expectedTurnId=turn,
                 input=[dict(type='text', text=receipt['checkpoint']['message'])]))
        receipt['checkpoint']['state'] = 'acknowledged' if delivered else 'uncertain'
    _save(path, receipt)
    return receipt


def poll(root):
    directory=_directory(root);results=[]
    for path in directory.glob('*.json'):
        if path.name=='controller.json':continue
        with _lock(directory,path.stem):
            _private(path);receipt=json.loads(path.read_text())
            try:
                from .goal_governance import sync
                if sync(receipt):
                    if receipt.get('governor_mode')=='advisory':
                        observation=_usage(receipt);receipt['accounting']=observation
                        if observation.get('state')=='qualified':
                            if receipt.get('advisory_without_window'):receipt['lifetime_used_tokens']=observation['used_tokens']
                            elif not _accounting_decreased(receipt,observation):receipt['used_tokens']=observation['used_tokens']
                        _save(path,receipt)
                    results.append(dict(receipt,state='inactive'));continue
                from .goal_renewal import renewal_hold
                pending=renewal_hold(root,receipt)
                if pending:
                    results.append(dict(receipt,**pending));continue
                if receipt.get('requires_native_guard') and receipt.get('native_guard',{}).get('lease_id'):
                    from .goal_native_guard import qualified, matches, reconcile_expiry
                    guard=receipt['native_guard']
                    if matches(receipt) and (guard.get('status') in ('lost','expired') or guard.get('status')=='armed' and not qualified(receipt)):
                        reconcile_expiry(path,receipt)
                        results.append(receipt);continue
                from .permission_enforcement import controller_permission
                permission=controller_permission(root,receipt)
                receipt['enforcement_continuation_permission']=permission
                grant=_grant(receipt['policy_path'],receipt['thread_id'],receipt['allocation_id'],root)
                if grant!=receipt['grant']:
                    results.append(_stop(path,receipt,'host_policy_changed'));continue
                if boot_id_value()!=receipt['boot_id']:
                    results.append(_stop(path,receipt,'boot_identity_changed'));continue
                from .goal_time import upper as time_upper, GoalTimeUnavailable
                try:
                    upper=time_upper(receipt)
                except GoalTimeUnavailable as error:
                    receipt['clock_failure']=error.code
                    results.append(_stop(path,receipt,error.code));continue
                goal,active=_native(grant,receipt['thread_id'])
                receipt['native_goal_status']=goal.get('status') if goal else None
                if 'winddown_deadline' in receipt:
                    results.append(_wind_down(path,receipt,receipt['winddown_reason'],goal,active,upper));continue
                observation=_usage(receipt)
                used=observation.get('used_tokens')
                invalid=(observation.get('state')!='qualified' or type(used) is not int
                    or _accounting_decreased(receipt,observation))
                receipt['accounting']=observation
                if invalid:
                    results.append(_wind_down(path,receipt,'accounting_unknown',goal,active,upper));continue
                receipt['qualified_task_members']=observation.get('thread_ids',[receipt['thread_id']])
                receipt['used_tokens']=used;receipt['observed_boottime']=time.clock_gettime(time.CLOCK_BOOTTIME)
                receipt['last_verified_usage']=dict(generation=receipt['generation'],used_tokens=used,
                    lifetime_used_tokens=receipt.get('lifetime_tokens_before_window',0)+used,elapsed_seconds=max(0,upper-receipt['time_origin']))
                shared=receipt.get('shared_limits')
                if shared and (shared['used_tokens']>=shared['token_limit'] or upper>=shared['deadline']):
                    receipt['limiting_scope']='shared'
                    results.append(_stop(path,receipt,'allocation_exhausted',goal,active));continue
                task_disabled=receipt.get('task_governor_enabled') is False
                if not task_disabled and (used>=receipt['token_limit'] or upper>=receipt['deadline']):
                    receipt['limiting_scope']='task'
                    results.append(_stop(path,receipt,'task_exhausted' if receipt.get('task_window') else 'allocation_exhausted',goal,active));continue
                if (receipt.get('stop_latched') or receipt.get('state') in ('stopped','stop_unverified')) and not (task_disabled and receipt.get('first_stop',{}).get('reason')=='task_exhausted'):
                    results.append(_stop(path,receipt,receipt.get('reason','continuation_held'),goal,active));continue
                if permission['permission'] not in ('allow','legacy'):
                    receipt.update(state='held',reason='permission_revoked',campaign_continuation='held')
                    _save(path,receipt);results.append(receipt);continue
                receipt.pop('campaign_continuation',None)
                if receipt.get('requires_native_guard'):
                    from .goal_native_guard import arm
                    if not arm(path,receipt):
                        receipt.update(state='held',reason=receipt.get('native_guard',{}).get('reason','native_guard_unavailable'))
                        _save(path,receipt);results.append(receipt);continue
                if receipt.get('requires_native_guard'):
                    captured=next((item['turnIds'] for item in receipt.get('native_guard',{}).get('member_turns',[]) if item['threadId']==receipt['thread_id']),[])
                    active=[turn for turn in active if turn in captured]
                checkpoint=not task_disabled and (receipt['token_limit']-used<=receipt['token_limit']*receipt['checkpoint_token_percent']/100
                    or receipt['deadline']-upper<=receipt['checkpoint_seconds'])
                if checkpoint:
                    if not receipt.get('checkpoint'):
                        receipt['checkpoint']=dict(state='queued',message='Stop work and write a restart-safe checkpoint now. The original resource allowance remains in force.')
                        _save(path,receipt)
                    if active and receipt['checkpoint']['state']=='queued':
                        key='checkpoint:'+active[0]
                        delivered=_effect(path,receipt,key,'turn/steer',dict(threadId=receipt['thread_id'],expectedTurnId=active[0],
                            input=[dict(type='text',text=receipt['checkpoint']['message'])]))
                        receipt['checkpoint']['state']=('acknowledged' if delivered else
                            'blocked' if receipt.pop('permission_effect_blocked',False) else 'uncertain')
                    receipt.update(state='checkpoint_requested',reason='checkpoint_reserve')
                    _record_supervision_notice(path,receipt,'checkpoint')
                else:receipt.update(state='armed',reason=None)
                _save(path,receipt);results.append(receipt)
            except Exception as exc:
                receipt['observation_error']=exc.cause if isinstance(exc,NativeObservationUnavailable) else type(exc).__name__
                receipt['observation_method']=exc.method if isinstance(exc,NativeObservationUnavailable) else None
                receipt['observation_duration_seconds']=exc.duration if isinstance(exc,NativeObservationUnavailable) else None
                results.append(_stop(path,receipt,'observation_unavailable'))
    return results


def _acknowledge_enrollments(directory,controller,observations):
    for observed in observations:
        path=directory/(_name(observed['thread_id'])+'.json')
        with _lock(directory,path.stem):
            _private(path);receipt=json.loads(path.read_text())
            from .goal_governance import sync
            if sync(receipt):continue
            if any(receipt.get(key)!=observed.get(key) for key in
                    ('generation','enrollment_revision','token_limit','deadline','used_tokens')):continue
            if (observed.get('state')=='held' and observed.get('reason')=='idle_session_future_task_isolation_unsupported'
                    and receipt.get('requires_native_guard') and not receipt.get('stop_latched')
                    and receipt.get('accounting',{}).get('state')=='qualified'):
                clock=_controller_clock()
                if clock is None:continue
                receipt['prepared_poll_ack']=dict(enrollment_revision=receipt['enrollment_revision'],receipt_generation=receipt['generation'],
                    controller_generation=controller['generation'],observed_boottime=None,clock_observation=clock)
                _save(path,receipt)
                continue
            if (observed.get('state') not in ('armed','checkpoint_requested') or
                    receipt.get('state') not in ('armed','checkpoint_requested') or receipt.get('stop_latched')
                    or (receipt.get('accounting') or {}).get('state')!='qualified'):
                continue
            clock=_controller_clock()
            if clock is None:continue
            receipt['poll_ack']=dict(enrollment_revision=receipt.get('enrollment_revision',1),
                receipt_generation=receipt['generation'],controller_generation=controller['generation'],
                observed_boottime=None,clock_observation=clock)
            receipt['controller_generation']=controller['generation']
            _record_supervision_notice(path,receipt,'engagement',controller)
            _save(path,receipt)


def watch(root,interval=1):
    if type(interval) not in (int,float) or not .05<=interval<=5:raise ValueError('invalid controller interval')
    directory=_directory(root);generation=uuid4().hex
    descriptor=os.open(directory/'watch.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        running=True
        def finish(signum,frame):
            nonlocal running
            running=False
        prior={sig:signal.signal(sig,finish) for sig in (signal.SIGTERM,signal.SIGINT)}
        heartbeat=dict(generation=generation,pid=os.getpid(),identity=process_identity(os.getpid()),
            boot_id=boot_id_value(),interval=interval,time_bases=['qualified_utc','authenticated_host_counter'],
            session_scope_without_goal=True,governor_protocol=1)
        import threading
        from .goal_notices import run_presenter
        presentation_stop=threading.Event()
        presenter=threading.Thread(target=run_presenter,args=(root,presentation_stop),daemon=True,
            name='goal-notice-presenter')
        presenter.start()
        try:
            while running:
                _save(directory/'controller.json',dict(heartbeat,active=True,observed_boottime=None,
                    clock_observation=_controller_clock()))
                observations=poll(root)
                _acknowledge_enrollments(directory,heartbeat,observations)
                from .goal_maintenance import replacement_observed
                replacement_observed(directory,heartbeat)
                time.sleep(interval)
        finally:
            from .goal_maintenance import authorize_exit
            with _lock(directory,'maintenance'):
                maintained=not running and authorize_exit(directory,heartbeat)
                if not maintained:
                    for path in directory.glob('*.json'):
                        if path.name=='controller.json':continue
                        with _lock(directory,path.stem):
                            _private(path);receipt=json.loads(path.read_text())
                            if receipt.get('requires_native_guard'):
                                from .goal_native_guard import expire
                                expire(path,receipt)
                            else:_stop(path,receipt,'controller_stopped')
            _save(directory/'controller.json',dict(heartbeat,active=False,observed_boottime=None,
                clock_observation=_controller_clock()))
            # Stop control precedes presentation. Drain the newly journaled stop
            # once; stalled native I/O must not hold controller exit indefinitely.
            presentation_stop.set()
            presenter.join(timeout=2)
            for sig,handler in prior.items():signal.signal(sig,handler)
