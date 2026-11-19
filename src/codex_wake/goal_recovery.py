"""Explicit same-allowance recovery after a qualified native observation fault."""
from __future__ import annotations
from contextlib import nullcontext, ExitStack
import json
from pathlib import Path
from uuid import uuid4

from .session_permissions import PermissionDenied, Principal


def recover(root, policy, thread, *, principal, task_id=None, operation_id=None, allocation_id=None):
    from . import goal_supervision as g
    from .goal_time import upper, GoalTimeUnavailable
    from .permission_enforcement import authorize, controller_permission
    permission=authorize(root,'enforcement.recover',principal,task_id=task_id,operation_id=operation_id)
    if permission['permission']=='legacy' and principal.role!='operator':
        raise PermissionDenied('recovery_explicit_authority_required')
    directory=g._directory(root);path=directory/(g._name(thread)+'.json')
    with g._lock(directory,'recovery'), g._lock(directory,path.stem), ExitStack() as locks:
        if not path.exists():raise PermissionDenied('recovery_not_enrolled',permission)
        g._private(path);receipt=json.loads(path.read_text())
        def refuse(reason):
            raise PermissionDenied(reason,permission)
        if receipt.get('thread_id')!=thread:refuse('recovery_target_mismatch')
        if allocation_id is not None and receipt['allocation_id']!=allocation_id:refuse('recovery_allocation_mismatch')
        if receipt.get('reason') in (None,'recovery_pending_reconciliation') and receipt.get('allocation_path'):
            retained_path=Path(receipt['allocation_path']);g._private(retained_path)
            with g._lock(retained_path.parent,retained_path.stem):
                retained=json.loads(retained_path.read_text()).get('pending_recovery')
            if retained and retained.get('receipt_generation')==receipt['generation'] and retained.get('operation_id')==operation_id:
                receipt['reason']='observation_unavailable'
                receipt['active_stop_id']=retained.get('stop_episode_id')
        if receipt.get('reason')!='observation_unavailable':refuse('recovery_requires_observation_fault')
        if receipt.get('winddown_deadline') is not None:refuse('recovery_accounting_winddown')
        grant=g._grant(policy,thread,receipt['allocation_id'],root)
        if grant!=receipt['grant']:refuse('recovery_host_policy_changed')
        if receipt['boot_id']!=g.boot_id_value():refuse('recovery_boot_identity_changed')
        heartbeat=g._heartbeat(directory)
        if not heartbeat['fresh']:refuse('recovery_controller_unavailable')
        if controller_permission(root,receipt)['permission'] not in ('allow','legacy'):refuse('recovery_continuation_denied')
        participants={thread:(path,receipt)}
        allocation_path=Path(receipt['allocation_path']) if receipt.get('allocation_path') else None
        member_ids={thread}
        if allocation_path:
            g._private(allocation_path)
            with g._lock(allocation_path.parent,allocation_path.stem):
                member_ids=set(json.loads(allocation_path.read_text())['members'])
            if member_ids!={thread}:
                if principal.role!='operator' or allocation_id!=receipt['allocation_id']:
                    refuse('recovery_shared_allocation_requires_explicit_operator_scope')
                for member in sorted(member_ids-{thread}):
                    peer_path=directory/(g._name(member)+'.json')
                    locks.enter_context(g._lock(directory,peer_path.stem))
                    if not peer_path.exists():refuse('recovery_member_not_enrolled')
                    g._private(peer_path);peer=json.loads(peer_path.read_text())
                    if (peer.get('allocation_path')!=str(allocation_path) or peer.get('thread_id')!=member
                            or peer.get('reason') not in (None,'continuation_held','observation_unavailable')
                            or peer.get('winddown_deadline') is not None):
                        refuse('recovery_member_stop_conflict')
                    if peer['boot_id']!=g.boot_id_value():refuse('recovery_boot_identity_changed')
                    if g._grant(policy,member,receipt['allocation_id'],root)!=peer['grant']:
                        refuse('recovery_host_policy_changed')
                    authorize(root,'enforcement.recover',Principal(member,'operator'))
                    if controller_permission(root,peer)['permission'] not in ('allow','legacy'):
                        refuse('recovery_continuation_denied')
                    participants[member]=(peer_path,peer)
        # Exact observations agree across the aggregate nondecreasing usage scan.
        first={member:g._native(item['grant'],member) for member,(_,item) in participants.items()}
        observation=g._usage(receipt)
        second={member:g._native(item['grant'],member) for member,(_,item) in participants.items()}
        identity=('threadId','createdAt','status')
        for member,(_,item) in participants.items():
            before,active=first[member];after,again=second[member]
            if (not before or not after or any(before.get(k)!=after.get(k) for k in identity)
                    or set(active)!=set(again) or after.get('status')!='paused'
                    or 'stop_turns' not in item or set(active).intersection(item['stop_turns'])
                    or (active and not item.get('stop_scope_observed',False))):
                refuse('recovery_native_stop_unverified')
            if after.get('createdAt')!=item['goal_created_at']:refuse('recovery_goal_identity_changed')

        if (observation.get('state')!='qualified' or type(observation.get('used_tokens')) is not int
                or any(g._accounting_decreased(item,observation) for _,item in participants.values())):
            refuse('recovery_accounting_unqualified')
        try:
            current_upper = upper(receipt)
        except GoalTimeUnavailable:
            refuse('recovery_clock_unqualified')
        if current_upper>=receipt['deadline'] or observation['used_tokens']>=receipt['token_limit']:
            refuse('recovery_resources_exhausted')
        current=g._heartbeat(directory)
        if not current['fresh'] or current['generation']!=heartbeat['generation']:
            refuse('recovery_controller_unavailable')
        authorize(root,'enforcement.recover',principal,task_id=task_id,operation_id=operation_id)
        guard=g._lock(allocation_path.parent,allocation_path.stem) if allocation_path else nullcontext()
        with guard:
            allocation=None
            if allocation_path:
                g._private(allocation_path);allocation=json.loads(allocation_path.read_text())
                if allocation.get('stop_reason')!='observation_unavailable':refuse('recovery_allocation_stop_changed')
                if allocation.get('winddown_deadline') is not None:refuse('recovery_accounting_winddown')
                if set(allocation['members'])!=member_ids:refuse('recovery_allocation_members_changed')
                if allocation['used_tokens']!=observation['used_tokens']:refuse('recovery_accounting_changed')
                if any(allocation[key]!=receipt[key] for key in ('token_limit','deadline','boot_id','grant')):
                    refuse('recovery_resource_authority_changed')
            pending=allocation.get('pending_recovery') if allocation is not None else None
            if pending and (pending.get('operation_id')!=operation_id or pending.get('receipt_generation')!=receipt['generation']):
                refuse('recovery_pending_operation_mismatch')
            authorize(root,'enforcement.recover',principal,task_id=task_id,operation_id=operation_id)
            if controller_permission(root,receipt)['permission'] not in ('allow','legacy'):refuse('recovery_continuation_denied')
            for member in member_ids-{thread}:authorize(root,'enforcement.recover',Principal(member,'operator'))
            for member,(_,item) in participants.items():
                if g._grant(policy,member,receipt['allocation_id'],root)!=item['grant']:
                    refuse('recovery_host_policy_changed')
                if controller_permission(root,item)['permission'] not in ('allow','legacy'):
                    refuse('recovery_continuation_denied')
                final,active=g._native(item['grant'],member)
                if (not final or final.get('createdAt')!=item['goal_created_at']
                        or final.get('status')!='paused' or set(active).intersection(item['stop_turns'])
                        or (active and not item.get('stop_scope_observed',False))):
                    refuse('recovery_native_stop_unverified')
            current=g._heartbeat(directory)
            if not current['fresh'] or current['generation']!=heartbeat['generation']:
                refuse('recovery_controller_unavailable')
            try:
                final_upper = upper(receipt)
            except GoalTimeUnavailable:
                refuse('recovery_clock_unqualified')
            if final_upper>=receipt['deadline']:
                refuse('recovery_resources_exhausted')
            event=pending or dict(id=uuid4().hex,receipt_generation=receipt['generation'],stop_episode_id=receipt.get('active_stop_id'),operation_id=operation_id,kind='recovery',reason='observation_recovered',
                subject=principal.subject,participants=sorted(member_ids),authority=permission,controller_generation=heartbeat['generation'],
                observed_boottime=None, observed_upper=final_upper,
                clock_basis=receipt.get('time_basis', 'qualified_utc'), used_tokens=observation['used_tokens'],
                deadline=receipt['deadline'],goal_created_at=receipt['goal_created_at'])
            if allocation is not None:
                allocation['pending_recovery']=event;g._save(allocation_path,allocation)
            for member,(member_path,item) in participants.items():
                if not any(old['id']==event['id'] for old in item.setdefault('recovery_events',[])):
                    item['recovery_events'].append(event)
                item.pop('active_stop_id',None)
                item.update(stop_latched=False,state='armed',reason=None,accounting=observation,
                    used_tokens=observation['used_tokens'],native_goal_status='paused',recovery_permission=permission)
                # Evidence/effects remain append-only; goal activation is separate.
                g._record_supervision_notice(member_path,item,'recovery',current)
                g._save(member_path,item)
            if allocation is not None:
                if not any(old['id']==event['id'] for old in allocation.setdefault('recovery_events',[])):
                    allocation['recovery_events'].append(event)
                allocation.update(stop_latched=False,stop_reason=None)
                allocation.pop('pending_recovery',None);g._save(allocation_path,allocation)
        return g._public(receipt)
