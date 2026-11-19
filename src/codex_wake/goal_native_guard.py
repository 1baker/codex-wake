"""Native loss leases projected into the existing supervision receipt.

The native app server owns expiry and exact-turn interruption. This module never
creates a goal or turn, and a lease acknowledgement is not stop proof.
"""
import math

from . import goal_supervision as supervision
from . import measurements


def _identity(receipt):
    return receipt['thread_id']+':'+receipt['generation']+':'+str(receipt['enrollment_revision'])


def matches(receipt):
    return receipt.get('native_guard',{}).get('lease_id')==_identity(receipt)


def qualified(receipt):
    guard=receipt.get('native_guard',{})
    if guard.get('status')!='armed' or guard.get('lease_id')!=_identity(receipt):
        return False
    try:
        return measurements.fresh(guard['ack_clock'],math.nextafter(guard.get('ttl_ms',0)/1000,-math.inf))
    except (measurements.TimeUnavailable,KeyError,TypeError):
        return False


def arm(path,receipt,*,force=False,stop=False):
    """Caller holds the existing member lock; renew only qualified live work."""
    if not receipt.get('requires_native_guard'):return True
    identifier=_identity(receipt)
    prior=receipt.get('native_guard',{})
    if prior.get('lease_id') and prior['lease_id']!=identifier:
        history=receipt.setdefault('native_guard_history',[])
        if not history or history[-1]!=prior:history.append(dict(prior))
    if (not force and prior.get('lease_id')==identifier
            and prior.get('status') in ('unsupported','expired','lost','released')):
        return False
    controller=supervision._heartbeat(path.parent)
    generation=controller.get('generation')
    if controller.get('governor_protocol')!=1:
        receipt['native_guard']=dict(status='unsupported',reason='watcher_protocol_upgrade_required',lease_id=identifier)
        supervision._save(path,receipt);return False
    if not generation:
        receipt['native_guard']=dict(status='unavailable',reason='watcher_identity_unavailable',lease_id=identifier)
        supervision._save(path,receipt);return False
    from .goal_time import upper
    observed=upper(receipt)
    task=receipt.get('task_window')
    task_disabled=receipt.get('task_governor_enabled') is False or task and task.get('governor_enabled') is False
    shared=receipt.get('shared_limits')
    remaining=(shared['deadline'] if task_disabled and shared else receipt['deadline'])-observed
    if task and not task_disabled:remaining=min(remaining,task['deadline']-observed)
    if shared:remaining=min(remaining,shared['deadline']-observed)
    if remaining<=0 and not stop:return False
    members=[]
    intent=dict(prior)
    try:
        identities=receipt.get('qualified_task_members')
        if not identities or receipt['thread_id'] not in identities:
            raise ValueError('qualified task membership unavailable')
        for thread in identities:
            goal,active=supervision._native(receipt['grant'],thread)
            # A paused goal's later operator reply is outside campaign work.
            turns=list(active) if not goal or goal.get('status')!='paused' else []
            if goal is None and not force and prior.get('lease_id')==identifier:
                captured=next((item['turnIds'] for item in prior.get('member_turns',[]) if item['threadId']==thread),None)
                if captured is not None:turns=[turn for turn in turns if turn in captured]
            members.append(dict(threadId=thread,turnIds=turns,
                goalCreatedAt=goal.get('createdAt') if goal else None))
        if not any(item['goalCreatedAt'] is not None or item['turnIds'] for item in members):
            receipt['native_guard']=dict(status='unsupported',lease_id=identifier,
                reason='idle_session_future_task_isolation_unsupported')
            supervision._save(path,receipt);return False
        ttl=1 if stop else max(1,min(10000,math.floor(remaining*1000)))
        params=dict(threadId=receipt['thread_id'],leaseId=identifier,
            controllerGeneration=generation,enrollmentRevision=receipt['enrollment_revision'],
            ttlMs=ttl,memberTurns=members)
        intent=dict(prior,status='arming',lease_id=identifier,controller_generation=generation,
            enrollment_revision=receipt['enrollment_revision'],ttl_ms=ttl,member_turns=members)
        receipt['native_guard']=intent
        supervision._save(path,receipt)
        sent=measurements.snapshot()
        acknowledgement=supervision._request(receipt['grant'],'thread/governorLease/set',params)
        if acknowledgement.get('leaseId')!=identifier:
            raise ValueError('native governor lease acknowledgement changed identity')
        if acknowledgement.get('expired'):
            receipt['native_guard']=dict(prior,status='expired',lease_id=identifier,
                reason='native_guard_expired',stop_verified=acknowledgement.get('stopVerified') is True)
            supervision._save(path,receipt);return False
        if acknowledgement.get('armed') is not True:
            raise ValueError('native governor lease was not armed')
        if not measurements.fresh(sent,math.nextafter(ttl/1000,-math.inf)):
            raise measurements.TimeUnavailable('native lease acknowledgement expired')
        receipt['native_guard']=dict(status='armed',lease_id=identifier,
            controller_generation=generation,enrollment_revision=receipt['enrollment_revision'],
            ttl_ms=ttl,member_turns=members,ack_boottime=None,ack_clock=sent)
        supervision._save(path,receipt)
        return True
    except Exception as error:
        from .native_protocol import NativeCapabilityUnavailable
        unsupported=isinstance(error,(NativeCapabilityUnavailable,NotImplementedError))
        receipt['native_guard']=dict(intent,status='unsupported' if unsupported else 'lost',
            lease_id=identifier,reason='native_guard_capability_unavailable' if unsupported else 'native_guard_connection_lost',
            error=type(error).__name__)
        supervision._save(path,receipt)
        return False


def release(path,receipt):
    guard=receipt.get('native_guard',{})
    if not guard.get('lease_id'):return
    params=dict(threadId=receipt['thread_id'],leaseId=guard['lease_id'],
        controllerGeneration=guard.get('controller_generation'),
        enrollmentRevision=guard.get('enrollment_revision',receipt.get('enrollment_revision')),release=True)
    try:
        result=supervision._request(receipt['grant'],'thread/governorLease/set',params)
        if result.get('leaseId')!=guard['lease_id'] or result.get('armed') is not False or result.get('releaseVerified') is not True:
            raise ValueError('native lease release unverified')
        receipt['native_guard']=dict(guard,status='released',release_verified=True)
    except Exception as error:
        receipt['native_guard']=dict(guard,release_verified=False,release_error=type(error).__name__)
    supervision._save(path,receipt)


def reconcile_expiry(path,receipt):
    """Read native expiry without adopting a later operator turn as task work."""
    guard=receipt.get('native_guard',{})
    params=dict(threadId=receipt['thread_id'],leaseId=guard['lease_id'],
        controllerGeneration=guard.get('controller_generation'),
        enrollmentRevision=guard.get('enrollment_revision',receipt.get('enrollment_revision')),query=True)
    try:
        result=supervision._request(receipt['grant'],'thread/governorLease/set',params)
        expired=result.get('leaseId')==guard['lease_id'] and result.get('expired') is True
        receipt['native_guard']=dict(guard,status='expired' if expired else 'lost',
            reason='native_guard_expired' if expired else 'native_guard_lease_unqualified',
            stop_verified=expired and result.get('stopVerified') is True,
            member_outcomes=result.get('memberOutcomes',[]))
    except Exception as error:
        receipt['native_guard']=dict(guard,status='lost',reason='native_guard_connection_lost',error=type(error).__name__)
    if receipt.get('boot_id')==supervision.boot_id_value():
        try:
            from .goal_time import upper
            observed=upper(receipt);shared=receipt.get('shared_limits');task=receipt.get('task_window')
            inactive=receipt.get('task_governor_enabled') is False or task and task.get('governor_enabled') is False
            resource=None
            if shared and (observed>=shared['deadline'] or shared.get('used_tokens',0)>=shared['token_limit']):resource='allocation_exhausted'
            elif not inactive and (observed>=receipt['deadline'] or type(receipt.get('used_tokens')) is int and receipt['used_tokens']>=receipt['token_limit']):resource='task_exhausted' if task else 'allocation_exhausted'
            if resource:
                supervision._stop_episode(path,receipt,resource)
                supervision._first_stop(path,receipt,resource)
                supervision._allocation_latch(receipt,resource)
                receipt.update(stop_latched=True,reason=resource)
        except (ValueError,TypeError,KeyError):pass
    exhausted=receipt.get('stop_latched') and receipt.get('first_stop',{}).get('reason') in ('allocation_exhausted','task_exhausted','continuation_held')
    if receipt.get('stop_latched') and receipt['native_guard'].get('stop_verified'):
        receipt.update(state='stopped',stop_proof=True,pause_observed=True,descendant_stop_verified=True)
    elif not exhausted:receipt.update(state='held',reason=receipt['native_guard']['reason'])
    supervision._save(path,receipt)


def expire(path,receipt,reason='controller_stopped'):
    """Graceful watcher exit shortens its last native scope, never recaptures."""
    guard=receipt.get('native_guard',{})
    if guard.get('status')=='released':return
    if guard.get('status')=='unsupported':
        receipt.update(state='held',reason='native_guard_capability_unavailable')
        supervision._save(path,receipt);return
    if not guard.get('controller_generation') or not guard.get('member_turns'):
        receipt.update(state='held',reason='native_guard_unqualified')
        supervision._save(path,receipt);return
    try:
        supervision._request(receipt['grant'],'thread/governorLease/set',dict(
            threadId=receipt['thread_id'],leaseId=guard['lease_id'],
            controllerGeneration=guard['controller_generation'],
            enrollmentRevision=guard['enrollment_revision'],ttlMs=1,memberTurns=guard['member_turns']))
        receipt['native_guard']=dict(guard,status='lost',reason=reason,ttl_ms=1)
    except Exception as error:
        receipt['native_guard']=dict(guard,status='lost',reason=reason,error=type(error).__name__)
    receipt.update(state='stop_unverified' if receipt.get('stop_latched') else 'held',reason=reason)
    supervision._save(path,receipt)


def preflight(root,grant,thread):
    """Read capability and watcher health before a first budget clock exists."""
    from uuid import uuid4
    controller=supervision._heartbeat(supervision._directory(root))
    if not controller.get('fresh'):
        return dict(ready=False,reason='watcher_unavailable_before_activation')
    if controller.get('governor_protocol')!=1:
        return dict(ready=False,reason='watcher_protocol_upgrade_required')
    identifier='preflight:'+thread+':'+uuid4().hex
    try:
        reply=supervision._request(grant,'thread/governorLease/set',dict(threadId=thread,
            leaseId=identifier,controllerGeneration=controller['generation'],enrollmentRevision=1,query=True))
        if reply.get('leaseId')!=identifier or reply.get('supported') is not True:
            return dict(ready=False,reason=reply.get('reason','native_guard_capability_unavailable'))
        return dict(ready=True,reason='native_guard_capability_qualified')
    except Exception as error:
        from .native_protocol import NativeCapabilityUnavailable
        reason='native_guard_capability_unavailable' if isinstance(error,(NativeCapabilityUnavailable,NotImplementedError)) else 'native_guard_preflight_unavailable'
        return dict(ready=False,reason=reason,error=type(error).__name__)


def guarded_start(path,receipt,operation_id,controller):
    """Native reserves and arms the exact new turn before model inference."""
    identifier=_identity(receipt)
    from .goal_time import upper
    observed=upper(receipt);task=receipt.get('task_window');shared=receipt.get('shared_limits')
    disabled=receipt.get('task_governor_enabled') is False or task and task.get('governor_enabled') is False
    remaining=(shared['deadline'] if disabled and shared else receipt['deadline'])-observed
    if task and not disabled:remaining=min(remaining,task['deadline']-observed)
    if shared:remaining=min(remaining,shared['deadline']-observed)
    if remaining<=0:return dict(resumed=False,resume_state='allowance_exhausted',renewed_resources=False)
    ttl=max(1,min(10000,math.floor(remaining*1000)))
    start=dict(requestId=operation_id,text='Continue the interrupted task within its existing governor allowance.')
    common=dict(threadId=receipt['thread_id'],leaseId=identifier,controllerGeneration=controller['generation'],
        enrollmentRevision=receipt['enrollment_revision'],guardedStart=start)
    key='guarded-start:'+operation_id
    effects=receipt.setdefault('effects',{});submitted=False
    try:
        reply=supervision._request(receipt['grant'],'thread/governorLease/set',dict(common,query=True))
        if reply.get('guardRequestId')!=operation_id:
            return dict(resumed=False,resume_state='native_guarded_resume_unsupported',renewed_resources=False)
        if reply.get('startState')=='not_started':
            effects[key]=dict(state='intended',guard_request_id=operation_id)
            supervision._save(path,receipt)
            sent=measurements.snapshot();submitted=True
            reply=supervision._request(receipt['grant'],'thread/governorLease/set',dict(common,ttlMs=ttl,
                memberTurns=[dict(threadId=receipt['thread_id'],turnIds=[],goalCreatedAt=None)]))
        else:sent=None  # Querying an earlier start never renews its clock anchor.
        turn=reply.get('startedTurnId')
        started=reply.get('guardRequestId')==operation_id and reply.get('startState')=='started' and isinstance(turn,str) and bool(turn)
        effects[key]=dict(state='acknowledged' if started else reply.get('startState','uncertain'),
            guard_request_id=operation_id,started_turn_id=turn if started else None)
        if started and reply.get('armed') is True and reply.get('leaseId')==identifier:
            receipt['native_guard']=dict(status='armed' if submitted else 'query_verified',lease_id=identifier,controller_generation=controller['generation'],
                enrollment_revision=receipt['enrollment_revision'],ttl_ms=min(ttl,reply.get('ttlMs',ttl)),ack_boottime=None,ack_clock=sent,
                member_turns=[dict(threadId=receipt['thread_id'],turnIds=[turn],goalCreatedAt=None)],guard_request_id=operation_id)
            receipt.update(state='armed',reason=None,stop_latched=False)
            receipt['poll_ack']=dict(receipt.get('prepared_poll_ack',{}))
        supervision._save(path,receipt)
        return dict(resumed=started,resume_state='submitted' if started else reply.get('startState','uncertain'),
            started_turn_id=turn if started else None,guard_request_id=operation_id,renewed_resources=False)
    except Exception as error:
        effects[key]=dict(state='uncertain',guard_request_id=operation_id,error=type(error).__name__)
        supervision._save(path,receipt)
        return dict(resumed=False,resume_state='uncertain',guard_request_id=operation_id,renewed_resources=False)
