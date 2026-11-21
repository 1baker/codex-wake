"""Checkpoint-bound fresh-context continuation; unknown allowance holds effects."""
from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
from contextlib import redirect_stdout
from datetime import UTC,datetime
from io import StringIO
import sys
from types import SimpleNamespace

from .agent_lifecycle import save
from .app_server import resolve_codex_cmd
from .native_protocol import native_request
from .records import WakeError, parse_timestamp
from .lifecycle_review import instruction_read, validate_work_review


from .wake_control import guard_command


@guard_command
def handoff_command(args, root):
    try:
        config=json.loads(Path(args.profiles).read_text())
        profile=config['profiles'][args.profile]
        policy=config['continuations'][args.thread_id]
        workspace=Path(profile['cwd']).resolve(strict=True)
        checkpoint=(workspace/args.checkpoint).resolve(strict=True)
        checkpoint.relative_to(workspace)
        content=checkpoint.read_bytes()
        body=json.loads(content)
        if (config['version']!=1 or body['source_thread_id']!=args.thread_id
                or body['objective']!=policy['objective']
                or not policy['approval'] or not body['authority'] or not body['next_packet']
                or body.get('pending_obligations')!=[]):raise ValueError
    except (OSError,ValueError,KeyError,TypeError):
        raise WakeError('handoff requires an approved continuation and source checkpoint') from None
    if hashlib.sha256(content).hexdigest()!=args.checkpoint_sha256:
        raise WakeError('checkpoint hash changed; original checkpoint must be preserved')
    fields=('token_cap','time_cap_seconds','tokens_before_source','seconds_before_source')
    if (any(not isinstance(policy.get(k),int) or isinstance(policy[k],bool)
            or policy[k]<0 for k in fields)
            or policy['token_cap']==0 or policy['time_cap_seconds']==0):
        raise WakeError('host continuation allowance must contain explicit bounded counters')
    parse_timestamp(policy.get('started_at',''))
    try:
        text_fields=('repo','worktree','commit','dirty_work','reply_route','authority','next_packet')
        if any(not isinstance(body.get(k),str) or not body[k].strip() for k in text_fields):raise ValueError
        if (not Path(body['repo']).is_absolute() or not Path(body['repo']).is_dir()
                or Path(body['worktree']).resolve(strict=True)!=workspace
                or len(body['commit'])!=40 or any(c not in '0123456789abcdef' for c in body['commit'])):raise ValueError
        for field in ('acceptance_remaining','evidence','hard_stops'):
            if (not isinstance(body.get(field),list) or not body[field]
                    or any(not isinstance(v,str) or not v.strip() for v in body[field])):raise ValueError
        if any(body.get(k)!=[] for k in ('pending_wakes','pending_messages','claim_holders')):raise ValueError
        resources=body['resources']
        if (not isinstance(resources,dict)
                or any(type(resources.get(k)) is not int or resources[k]!=policy[k] for k in fields[:2])
                or any(type(resources.get(k)) is not int or not 0<=resources[k]<=policy[k] for k in fields[2:])
                or resources.get('started_at')!=policy['started_at']
                or body.get('expires_at')!=args.expires_at):raise ValueError
    except (KeyError,TypeError,ValueError,OSError):
        raise WakeError('handoff requires a complete restart-safe checkpoint matching the host intent') from None
    from .permission_handoff import admission_context
    try:
        permission_context=admission_context(root,args,policy,body)
    except WakeError as error:
        from .permission_handoff import read_only_reconcile
        observed=read_only_reconcile(root,args,error)
        if observed is None:raise
        from .sessions_cli import emit
        emit(observed,args.as_json)
        return 5
    if permission_context:args.caller_thread_id=args.thread_id
    if permission_context is None and args.caller_thread_id and (args.caller_thread_id!=args.thread_id or args.profile not in
            config.get('callers',{}).get(args.caller_thread_id,[])):
        raise WakeError('handoff requires the host-granted source caller')
    parse_timestamp(args.expires_at)
    intent=dict(operation='handoff',source_thread_id=args.thread_id,launch=profile,
        continuation=policy,checkpoint=str(checkpoint),checkpoint_sha256=args.checkpoint_sha256,
        mode=args.mode,expires_at=args.expires_at)
    if permission_context:intent['handoff_trigger']=permission_context['trigger']
    if body.get('task_brief') is not None:
        from .task_briefs import TaskBriefStore
        from .session_permissions import PermissionStore
        briefs = TaskBriefStore(PermissionStore(root).root if permission_context else root)
        pin = briefs.validate_pin(body['task_brief'])
        approved = briefs.inspect(pin['task_id'])['revisions'][pin['revision'] - 1]['content']
        if (approved['objective'] != body['objective'] or approved['workspace'] != str(workspace)
                or approved['permission_ref'] != args.profile):
            raise WakeError('checkpoint task brief differs from the approved handoff scope')
        intent['task_brief'] = pin
    if config.get('lifecycle_defaults') or policy.get('configuration'):
        from .lifecycle_configuration import effective_configuration
        intent['configuration'] = effective_configuration(config, args.thread_id, args.profile, args.caller_thread_id,_permission_checked=bool(permission_context))
        if intent.get('task_brief') is not None:
            from .lifecycle_budget import objective_identity
            if approved['allocation_ref'] != objective_identity(policy):
                raise WakeError('checkpoint task brief allocation differs from the existing objective')
    fingerprint=hashlib.sha256(json.dumps(intent,sort_keys=True).encode()).hexdigest()
    journal=Path(root)/'lifecycle';journal.mkdir(mode=0o700,parents=True,exist_ok=True)
    key=hashlib.sha256(args.intent.encode()).hexdigest();path=journal/(key+'.json')
    with (journal/(key+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if path.exists():
            receipt=json.loads(path.read_text())
            if receipt['fingerprint']!=fingerprint:
                raise WakeError('intent key already binds a different lifecycle assignment')
        else:
            receipt=dict(version=1,intent_key=args.intent,fingerprint=fingerprint,
                intent=intent,thread_id=args.thread_id,state='prepared')
        if permission_context and 'permission_context' not in receipt:
            receipt['permission_context']=permission_context
        if 'configuration' in intent:
            receipt['configuration'] = intent['configuration']
        if getattr(args,'rollback',False):
            rollback_handoff(path,receipt,profile,policy,root)
            save(path,receipt)
            from .sessions_cli import emit
            emit(receipt,args.as_json)
            return 0 if receipt.get('rollback',{}).get('state')=='completed' else 5
        if receipt.get('terminal_review'):
            try:
                from .lifecycle_budget import record_successor, native_usage
                observed=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                    'thread/read',dict(threadId=receipt['successor_thread_id'],includeTurns=True),profile['timeout'])['thread']
                if observed.get('id')!=receipt['successor_thread_id']:raise ValueError('terminal actor changed')
                record_successor(root,receipt,native_usage(observed,profile),
                    settled=not any(turn.get('status')=='inProgress' for turn in observed.get('turns',[])))
            except Exception as exc:
                receipt['terminal_accounting_error']=type(exc).__name__
            save(path,receipt)
            from .sessions_cli import emit
            emit(receipt,args.as_json)
            return 5
        if receipt.get('deadline_fence'):
            from .process import process_identity,process_exists
            fence=receipt['deadline_fence']
            goals={}
            for thread in (args.thread_id,receipt['successor_thread_id']):
                goals[thread]=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                    'thread/goal/get',{'threadId':thread},profile['timeout'])['goal']
            alive=process_exists(fence['pid']) and process_identity(fence['pid'])==fence['identity']
            receipt['readback']=dict(monitor_alive=alive,goals=goals)
            save(path,receipt)
            from .sessions_cli import emit
            emit(receipt,args.as_json)
            source=goals[args.thread_id];target=goals[receipt['successor_thread_id']]
            ready=bool(source and target and source.get('status')=='paused' and
                all(target.get(k)==receipt['successor_goal'].get(k) for k in ('threadId','objective','tokenBudget','createdAt')))
            return 0 if ready and (receipt['state']=='completed' or
                receipt['state']=='active' and alive and target.get('status')=='active') else 5
        goal=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
            'thread/goal/get',{'threadId':args.thread_id},profile['timeout'])['goal']
        previous=receipt.get('source_goal')
        receipt['observed_source_goal']=goal
        known=bool(goal) and all(isinstance(goal.get(k),int) and not isinstance(goal[k],bool)
            and goal[k]>=0 for k in ('tokensUsed','timeUsedSeconds'))
        receipt.update(state='blocked',reason=('successor_preflight_not_verified' if known
                                              else 'source_usage_unknown'))
        if known and (goal.get('threadId')!=args.thread_id or goal.get('objective')!=policy['objective']
                or goal.get('status') not in ('active','paused')
                or 'tokenBudget' not in goal or (goal['tokenBudget'] is not None
                    and (type(goal['tokenBudget']) is not int or goal['tokenBudget']<=0))):
            receipt['reason']='source_goal_authority_changed'
        if known and previous:
            if any(goal.get(k)!=previous.get(k) for k in ('threadId','objective','tokenBudget','createdAt')):
                receipt['reason']='source_goal_authority_changed'
            elif any(type(previous.get(k)) is int and goal[k]<previous[k] for k in ('tokensUsed','timeUsedSeconds')):
                receipt['reason']='source_goal_accounting_changed'
        if not previous or receipt['reason']=='successor_preflight_not_verified':receipt['source_goal']=goal
        if known and receipt['reason']=='successor_preflight_not_verified':
            used=policy['tokens_before_source']+goal['tokensUsed']
            receipt['cumulative_tokens_used']=used
            native_remaining=policy['token_cap']-used if goal['tokenBudget'] is None else goal['tokenBudget']-goal['tokensUsed']
            receipt['remaining_tokens']=max(0,min(policy['token_cap']-used,native_remaining))
            receipt['source_remaining_tokens']=receipt['remaining_tokens']
            elapsed=policy['seconds_before_source']+goal['timeUsedSeconds']
            receipt['cumulative_seconds_used']=elapsed
            if receipt['remaining_tokens']==0:
                receipt['reason']='cumulative_token_budget_exhausted'
            elif elapsed>=policy['time_cap_seconds']:
                receipt['reason']='cumulative_time_budget_exhausted'
            else:
                from .native_clock import snapshot
                bounds=snapshot().get('utc')
                if not bounds:
                    receipt['reason']='admissible_time_unavailable'
                else:
                    deadline=min(parse_timestamp(args.expires_at).timestamp(),
                        parse_timestamp(policy['started_at']).timestamp()+policy['time_cap_seconds'],
                        bounds['upper']+policy['time_cap_seconds']-elapsed,
                        receipt.get('continuation_deadline',float('inf')))
                    receipt['continuation_deadline']=deadline
                    receipt['remaining_seconds']=max(0,deadline-bounds['upper'])
                    if bounds['upper']>=deadline:
                        receipt['reason']='continuation_time_exhausted'
        if receipt['reason']=='successor_preflight_not_verified':
            thread=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                'thread/read',{'threadId':args.thread_id,'includeTurns':True},profile['timeout'])['thread']
            marker='checkpoint:'+args.thread_id+':'+args.checkpoint_sha256
            writers=[{'turn_id':turn['id'],'item_id':item['id']}
                for turn in thread.get('turns',[]) for item in turn.get('items',[])
                if turn.get('status')=='completed' and item.get('type')=='commandExecution'
                and item.get('status')=='completed' and item.get('exitCode')==0
                and item.get('cwd')==str(workspace) and marker in (item.get('aggregatedOutput') or '')]
            if thread.get('id')!=args.thread_id or len(writers)!=1:
                receipt['reason']='checkpoint_writer_unverified'
            elif receipt.get('configuration') and not instruction_read(
                    thread, receipt['configuration']['handoff_writer'], workspace):
                receipt['reason']='handoff_writer_instructions_unverified'
            else:
                receipt['checkpoint_writer']=writers[0]
                source_guard(receipt,profile,root)
        if receipt['reason']=='successor_preflight_not_verified' and receipt.get('source_attachment'):
            advance_handoff(path,receipt,profile,policy,args,root)
        save(path,receipt)
        from .sessions_cli import emit
        emit(receipt,args.as_json)
        return 5


def rollback_handoff(path,receipt,profile,policy,root):
    """Fence the owned successor before restoring the original paused owner."""
    result=receipt.setdefault('rollback',dict(state='prepared',thread_id=receipt['thread_id']))
    owner_lock=None
    def request(method,params):
        return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),method,params,profile['timeout'])
    try:
        target=receipt.get('successor_thread_id')
        if not target or receipt.get('successor',{}).get('state')!='completed':
            result.update(state='blocked',reason='successor_assignment_not_settled');return
        key=hashlib.sha256(receipt['thread_id'].encode()).hexdigest();owner_path=path.parent/('owner-'+key+'.json')
        owner_lock=(path.parent/('owner-'+key+'.lock')).open('a')
        fcntl.flock(owner_lock,fcntl.LOCK_EX)
        owner=json.loads(owner_path.read_text())
        if (owner.get('intent_fingerprint')!=receipt['fingerprint'] or owner.get('source_thread_id')!=receipt['thread_id']
                or owner.get('successor_thread_id')!=target):
            result.update(state='blocked',reason='source_owned_by_another_transition');return
        target_goal=request('thread/goal/get',{'threadId':target})['goal']
        source=receipt['thread_id'];goal=request('thread/goal/get',{'threadId':source})['goal']
        before=result.get('source_goal_before',receipt['source_goal'])
        if (not goal or goal['status']!='paused'
                or any(goal.get(k)!=before.get(k) for k in ('threadId','objective','createdAt'))
                or any(type(goal.get(k)) is not int or goal[k]<before[k] for k in ('tokensUsed','timeUsedSeconds'))):
            result.update(state='blocked',reason='source_goal_authority_changed');return
        saved=receipt.get('successor_goal')
        if target_goal and (not saved or any(target_goal.get(k)!=saved.get(k)
                for k in ('threadId','objective','tokenBudget','createdAt'))):
            result.update(state='blocked',reason='successor_goal_authority_changed');return
        if target_goal and target_goal['status']=='active':
            if owner.get('state') not in ('active','rolling_back'):
                result.update(state='blocked',reason='successor_not_owned_active');return
            receipt['state']='rolling_back';owner['state']='rolling_back'
            save(owner_path,owner);save(path,receipt)
            if result.get('uncertain_effect')=='thread/goal/rollback_pause_successor':
                result.update(state='uncertain',reason='successor_pause_unobserved');return
            result.update(state='stopping_successor',uncertain_effect='thread/goal/rollback_pause_successor');save(path,receipt)
            request('thread/goal/set',dict(threadId=target,status='paused',origin='automatic'))
            target_goal=request('thread/goal/get',{'threadId':target})['goal']
        if target_goal and target_goal['status'] not in ('paused','complete','budgetLimited','usageLimited','blocked'):
            result.update(state='blocked',reason='successor_not_paused');return
        if target_goal and any(target_goal.get(k)!=saved.get(k) for k in
                               ('threadId','objective','tokenBudget','createdAt')):
            result.update(state='blocked',reason='successor_goal_authority_changed');return
        if result.get('uncertain_effect')=='thread/goal/rollback_pause_successor':result.pop('uncertain_effect',None)
        native=request('thread/read',{'threadId':target,'includeTurns':True})['thread']
        turns=[turn for turn in native['turns'] if turn['status']=='inProgress']
        if native['id']!=target or len(turns)>1:
            result.update(state='blocked',reason='successor_assignment_not_settled');return
        if turns:
            if owner.get('state') not in ('active','rolling_back'):
                result.update(state='blocked',reason='successor_assignment_not_settled');return
            receipt['state']='rolling_back';owner['state']='rolling_back';save(owner_path,owner)
            if result.get('uncertain_effect')=='turn/rollback_interrupt':
                result.update(state='uncertain',reason='successor_stop_unobserved');return
            result.update(state='stopping_successor',uncertain_effect='turn/rollback_interrupt',stop_turn_id=turns[0]['id']);save(path,receipt)
            request('turn/interrupt',dict(threadId=target,turnId=turns[0]['id']))
            native=request('thread/read',{'threadId':target,'includeTurns':True})['thread']
            if native['id']!=target or any(t['status']=='inProgress' for t in native['turns']):
                result.update(state='uncertain',reason='successor_stop_unobserved');return
        if result.get('uncertain_effect')=='turn/rollback_interrupt':result.pop('uncertain_effect',None)
        receipt['state']='rolling_back';owner['state']='rolling_back';save(owner_path,owner);save(path,receipt)
        guard=dict(thread_id=source,reason='successor_preflight_not_verified')
        source_guard(guard,profile,root)
        if not guard.get('source_attachment') and result.get('restoration'):
            from .lifecycle_rollback_ui import leave_restored_goal_paused
            if leave_restored_goal_paused(path,receipt,profile,before,request):
                guard=dict(thread_id=source,reason='successor_preflight_not_verified')
                source_guard(guard,profile,root)
        if not guard.get('source_attachment'):
            from .sessions import observe
            from .session_lifecycle import pending_thread_work,tmux_command
            import shlex
            snapshot=observe(endpoint=profile['app_server'],socket_path=profile.get('tmux_socket'),timeout=profile['timeout'])
            sources=[row for row in snapshot['sessions'] if row['thread_id']==source]
            if (not snapshot['complete'] or len(sources)!=1 or sources[0]['attachments']
                    or sources[0]['runtime_state'] not in ('idle','not_loaded') or sources[0]['active_flags']
                    or sources[0]['cwd']!=str(Path(profile['cwd']).resolve())):
                result.update(state='blocked',reason=guard['reason']);return
            old=receipt['source_attachment']
            try:
                fields=Path('/proc',str(old['client_pid']),'stat').read_text().rsplit(')',1)[1].split()
                gone=fields[0]=='Z' or int(fields[19])!=old['client_start_time_ticks']
            except FileNotFoundError:gone=True
            except (PermissionError,ValueError,IndexError):gone=False
            work=pending_thread_work(sources[0],root)
            if not gone or work['pending'] or work['messages']:
                result.update(state='blocked',reason='original_source_not_safe_to_restore');return
            if result.get('uncertain_effect')=='tmux/rollback_respawn':
                result.update(state='uncertain',reason='restored_source_not_yet_observed');return
            target_guard=dict(thread_id=target,reason='successor_preflight_not_verified')
            source_guard(target_guard,profile,root)
            pane=target_guard.get('source_attachment')
            owned=receipt['successor'].get('attachment')
            if not pane or not owned or any(pane.get(k)!=owned.get(k) for k in
                    ('client_pid','client_start_time_ticks','pane_id','window_id','session_name')):
                result.update(state='blocked',reason='successor_pane_not_owned_and_ready');return
            if not before_handoff_effect(path,receipt):
                result.update(state='blocked',reason=receipt['reason']);return
            runtime=SimpleNamespace(tmux_socket=profile.get('tmux_socket'),timeout=profile['timeout'])
            removed=['CODEX_THREAD_ID','TMUX_PANE','CODEX_WAKE_A2A_CAPABILITY','CODEX_WAKE_A2A_BUS_ROOT','CODEX_WAKE_SENDER_RECEIPT_AUTHORITY']
            home=['CODEX_HOME='+profile['codex_home']] if 'codex_home' in profile else []
            command=shlex.join(['env',*[v for k in removed for v in ('-u',k)],*home,
                resolve_codex_cmd(profile['codex_path'],required=True),'resume','--no-alt-screen','-C',profile['cwd'],source,'--remote',profile['app_server']])
            result.update(state='restoring_source',uncertain_effect='tmux/rollback_respawn',
                restoration=dict(pane_id=pane['pane_id'],window_id=pane['window_id'],previous_client_pid=pane['client_pid']))
            save(path,receipt)
            tmux_command(runtime,'respawn-pane','-k','-t',pane['pane_id'],'-c',profile['cwd'],command)
            guard=dict(thread_id=source,reason='successor_preflight_not_verified');source_guard(guard,profile,root)
            if not guard.get('source_attachment'):
                result.update(state='uncertain',reason='restored_source_not_yet_observed');return
        if result.get('restoration'):
            restored=guard['source_attachment'];expected=result['restoration']
            if (restored['pane_id']!=expected['pane_id'] or restored['window_id']!=expected['window_id']
                    or restored['client_pid']==expected['previous_client_pid']):
                result.update(state='uncertain',reason='exact_restored_source_generation_unverified');return
            if result.get('uncertain_effect') in ('tmux/rollback_respawn','tmux/rollback_leave_paused'):
                result.pop('uncertain_effect',None)
        goal=request('thread/goal/get',{'threadId':source})['goal']
        if (not goal or goal['status']!='paused'
                or any(goal.get(k)!=before.get(k) for k in ('threadId','objective','createdAt'))
                or any(type(goal.get(k)) is not int or goal[k]<before[k] for k in ('tokensUsed','timeUsedSeconds'))):
            result.update(state='blocked',reason='source_goal_authority_changed');return
        prior_budget=result.get('requested_budget')
        if prior_budget is not None and goal['tokenBudget']!=prior_budget:
            result.update(state='uncertain' if result.get('uncertain_effect') else 'blocked',
                reason='source_budget_change_unobserved' if result.get('uncertain_effect') else 'source_goal_authority_changed');return
        if prior_budget is None and goal.get('tokenBudget')!=before.get('tokenBudget'):
            result.update(state='blocked',reason='source_goal_authority_changed');return
        if result.get('uncertain_effect')=='thread/goal/rollback_source_budget':result.pop('uncertain_effect',None)
        native=request('thread/read',{'threadId':target,'includeTurns':True})['thread']
        if native['id']!=target or native['status']['type'] not in ('idle','notLoaded') or any(t['status']=='inProgress' for t in native['turns']):
            result.update(state='blocked',reason='successor_assignment_not_settled');return
        rollout=Path(native['path']).resolve(strict=True)
        rollout.relative_to(Path(profile.get('codex_home',Path.home()/'.codex'))/'sessions')
        used=None
        for line in rollout.read_text().splitlines():
            e=json.loads(line);p=e.get('payload',{});i=p.get('info') or {}
            if e.get('type')=='event_msg' and p.get('type')=='token_count' and i.get('total_token_usage'):
                used=i['total_token_usage'].get('total_tokens')
        if type(used) is not int or used<result.get('successor_tokens_used',0):
            result.update(state='blocked',reason='successor_usage_unknown_or_regressed');return
        remaining=policy['token_cap']-policy['tokens_before_source']-goal['tokensUsed']-used
        if before['tokenBudget'] is not None:remaining=min(remaining,before['tokenBudget']-goal['tokensUsed']-used)
        remaining=max(0,remaining)
        result.update(source_goal_before=before,successor_tokens_used=used,remaining_tokens=remaining,
            requested_budget=goal['tokensUsed']+remaining,attachment=guard['source_attachment'])
        if receipt.get('budget_actor'):
            from .lifecycle_budget import record_successor
            record_successor(root,receipt,used,settled=True)
        save(path,receipt)
        expected=result['requested_budget']
        if goal['tokenBudget']!=expected:
            if result.get('uncertain_effect'):
                result.update(state='uncertain',reason='source_budget_change_unobserved');return
            if not before_handoff_effect(path,receipt):
                result.update(state='blocked',reason=receipt['reason']);return
            result.update(state='budgeting_source',uncertain_effect='thread/goal/rollback_source_budget');save(path,receipt)
            request('thread/goal/set',dict(threadId=source,status='paused',tokenBudget=expected,origin='automatic'))
            goal=request('thread/goal/get',{'threadId':source})['goal']
        if (not goal or goal['status']!='paused' or goal['tokenBudget']!=expected
                or any(goal.get(k)!=before.get(k) for k in ('threadId','objective','createdAt'))
                or any(type(goal.get(k)) is not int or goal[k]<before[k] for k in ('tokensUsed','timeUsedSeconds'))):
            result.update(state='uncertain',reason='source_budget_change_unobserved');return
        result.pop('uncertain_effect',None)
        result.update(state='completed',reason='original_paused_conversation_reused',source_goal_after=goal)
        receipt.update(state='blocked',reason='handoff_rolled_back')
        owner=json.loads(owner_path.read_text())
        if owner['intent_fingerprint']!=receipt['fingerprint']:raise ValueError('owner changed')
        owner['state']='rolled_back';save(owner_path,owner)
    except Exception as exc:
        result.update(state='uncertain' if result.get('uncertain_effect') else 'blocked',reason=type(exc).__name__)
    finally:
        if owner_lock is not None:owner_lock.close()


def source_guard(receipt,profile,root):
    from .sessions import observe,revalidate_attachment,in_session
    from .session_lifecycle import pending_thread_work,tmux_command
    from types import SimpleNamespace
    snapshot=observe(endpoint=profile['app_server'],socket_path=profile.get('tmux_socket'),
        timeout=profile['timeout'])
    rows=[r for r in snapshot['sessions'] if r['thread_id']==receipt['thread_id']]
    retired=False
    if (snapshot['complete'] and not rows and receipt.get('intent',{}).get('mode')=='same-tab'
            and receipt.get('successor_thread_id') and receipt.get('source_attachment')):
        # A replaced TUI may unload its old conversation. Loaded-session
        # inventory is then insufficient; prove retirement from native state.
        try:
            native=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                'thread/read',dict(threadId=receipt['thread_id'],includeTurns=True),profile['timeout'])['thread']
            goal=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                'thread/goal/get',dict(threadId=receipt['thread_id']),profile['timeout'])['goal']
            saved=receipt['source_goal']
            if (native.get('id')!=receipt['thread_id'] or native.get('cwd')!=str(Path(profile['cwd']).resolve())
                    or any(t.get('status') not in ('completed','failed','interrupted') for t in native['turns'])
                    or not goal or goal.get('status')!='paused'
                    or any(goal.get(k)!=saved.get(k) for k in ('threadId','objective','tokenBudget','createdAt'))
                    or any(type(goal.get(k)) is not int or goal[k]<saved[k] for k in ('tokensUsed','timeUsedSeconds'))):
                raise ValueError('detached source retirement unverified')
            receipt['source_detached_readback']=dict(goal=goal,active_turns=0,cwd=native['cwd'])
            rows=[dict(thread_id=receipt['thread_id'],cwd=native['cwd'],attachments=[],active_flags=[])]
            retired=True
        except (ValueError,KeyError,TypeError,OSError):
            receipt['reason']='detached_source_retirement_unverified';return
    if (not snapshot['complete'] or len(rows)!=1
            or rows[0]['cwd']!=str(Path(profile['cwd']).resolve()) or rows[0]['active_flags']
            or (not retired and (rows[0]['runtime_state']!='idle'
                or rows[0]['can_accept_direct_input'] is not True))):
        receipt['reason']='source_client_not_uniquely_ready'
        return
    if not rows[0]['attachments'] and receipt.get('intent',{}).get('mode')=='same-tab' and receipt.get('successor_thread_id'):
        old=receipt['source_attachment']
        targets=[r for r in snapshot['sessions'] if r['thread_id']==receipt['successor_thread_id']]
        panes=[p for r in targets for p in r['attachments']]
        if (len(targets)!=1 or len(panes)!=1 or panes[0]['pane_id']!=old['pane_id']
                or panes[0]['window_id']!=old['window_id'] or not in_session(panes[0], profile['tmux_session'])
                or panes[0]['client_pid']==old['client_pid'] or not revalidate_attachment(panes[0])):
            receipt['reason']='same_tab_successor_not_uniquely_ready';return
        try:
            fields=Path('/proc',str(old['client_pid']),'stat').read_text().rsplit(')',1)[1].split()
            gone=fields[0]=='Z' or int(fields[19])!=old['client_start_time_ticks']
        except FileNotFoundError:gone=True
        except (PermissionError,ValueError,IndexError):gone=False
        work=pending_thread_work(rows[0],root);receipt['pending_work']=work
        if not gone:receipt['reason']='same_tab_source_exit_not_observed'
        elif work['pending'] or work['messages']:receipt['reason']='pending_thread_work'
        else:receipt['source_detached']=True
        return
    if len(rows[0]['attachments'])!=1:
        receipt['reason']='source_client_not_uniquely_ready';return
    attachment=rows[0]['attachments'][0]
    old=receipt.get('source_attachment')
    if old and any(attachment.get(k)!=old.get(k) for k in
                   ('client_pid','client_start_time_ticks','pane_id','window_id','session_name')):
        receipt['reason']='source_attachment_generation_changed';return
    if not in_session(attachment, profile['tmux_session']) or not revalidate_attachment(attachment):
        receipt['reason']='source_client_not_uniquely_ready'
        return
    work=pending_thread_work(rows[0],root)
    receipt['pending_work']=work
    if work['pending'] or work['messages']:
        receipt['reason']='pending_thread_work'
        return
    runtime=SimpleNamespace(tmux_socket=profile.get('tmux_socket'),timeout=profile['timeout'])
    panes=tmux_command(runtime,'list-panes','-t',attachment['window_id'],'-F','#{pane_id}')
    if panes.splitlines()!=[attachment['pane_id']]:
        receipt['reason']='split_or_changed_source_tab'
        return
    frame=tmux_command(runtime,'capture-pane','-e','-p','-t',attachment['pane_id'],preserve_output=True)
    cursor=tmux_command(runtime,'display-message','-p','-t',attachment['pane_id'],'#{cursor_x},#{cursor_y}')
    lines=frame.splitlines()
    try:
        x,y=map(int,cursor.strip().split(','))
        empty=x==2 and 0<=y<len(lines) and lines[y]=='\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m'
    except ValueError:empty=False
    if not empty:
        receipt['reason']='local_composer_not_proven_empty'
        return
    receipt['source_attachment']=attachment


def advance_handoff(path,receipt,profile,policy,args,root):
    """One fenced successor assignment; activation stays independently held."""
    from .agent_lifecycle import spawn_command
    preflight=policy.get('preflight',{})
    try:
        effective = receipt['configuration']
        script=Path(preflight['script'])
        output=(Path(profile['cwd'])/preflight['receipt']).resolve()
        output.relative_to(Path(profile['cwd']).resolve())
        if (not script.is_absolute() or hashlib.sha256(script.read_bytes()).hexdigest()!=preflight['sha256']
                or preflight['workflow']!=effective['preflight_reviewer']['name']
                or not preflight['required_checks']):raise ValueError
    except (OSError,ValueError,KeyError,TypeError):
        receipt.update(state='blocked',reason='preflight_policy_unavailable')
        return
    if (type(preflight.get('token_allowance')) is not int or preflight['token_allowance']<=0
            or preflight['token_allowance']>receipt['source_remaining_tokens']):
        receipt.update(state='blocked',reason='preflight_allowance_insufficient')
        return
    if args.mode not in ('new-tab','same-tab'):
        receipt.update(state='blocked',reason='same_tab_transition_not_implemented')
        return
    key=hashlib.sha256(receipt['thread_id'].encode()).hexdigest()
    owner_path=path.parent/('owner-'+key+'.json')
    with (path.parent/('owner-'+key+'.lock')).open('a') as owner_lock:
        fcntl.flock(owner_lock,fcntl.LOCK_EX)
        if owner_path.exists():
            owner=json.loads(owner_path.read_text())
            if owner['intent_fingerprint']!=receipt['fingerprint']:
                receipt.update(state='blocked',reason='source_owned_by_another_transition')
                return
            if owner.get('state') in ('rolling_back','rolled_back'):
                receipt.update(state='blocked',reason='handoff_rollback_pending_or_completed');return
        else:
            owner=dict(version=1,state='prepared',intent_fingerprint=receipt['fingerprint'],
                source_thread_id=receipt['thread_id'],state_history=['prepared'])
            save(owner_path,owner)
        def request(method,params):
            return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                method,params,profile['timeout'])
        try:
            source_goal=receipt['source_goal']
            if receipt.get('preflight_stop'):
                stop=receipt['preflight_stop']
                observed=request('thread/read',{'threadId':stop['thread_id'],'includeTurns':True})['thread']
                if observed.get('id')!=stop['thread_id']:raise WakeError('preflight stop identity mismatch')
                stop['settled']=not any(turn.get('status')=='inProgress' and turn.get('id') in stop['turn_ids']
                                        for turn in observed.get('turns',[]))
                if stop['settled']:receipt.pop('uncertain_effect',None)
                if receipt.get('budget_actor'):
                    from .lifecycle_budget import record_successor, native_usage
                    record_successor(root, receipt, native_usage(observed, profile), settled=stop['settled'])
                receipt.update(state='blocked' if stop['settled'] else 'uncertain',reason='preflight_allowance_exhausted')
                return
            if receipt.get('successor_thread_id') and source_goal['status']!='paused':
                receipt.update(state='blocked',reason='source_resumed_after_transfer')
                return
            if source_goal['status']!='paused':
                if receipt.get('uncertain_effect')=='thread/goal/pause':
                    receipt.update(state='uncertain',reason='source_pause_unobserved')
                    return
                if not before_handoff_effect(path,receipt):return
                receipt.update(state='pausing_source',uncertain_effect='thread/goal/pause');save(path,receipt)
                request('thread/goal/set',dict(threadId=receipt['thread_id'],status='paused',origin='automatic'))
                paused=request('thread/goal/get',{'threadId':receipt['thread_id']})['goal']
                if (paused is None or paused['status']!='paused'
                        or any(paused.get(k)!=source_goal.get(k) for k in
                               ('threadId','objective','tokenBudget','createdAt'))
                        or any(type(paused.get(k)) is not int or paused[k]<source_goal[k]
                               for k in ('tokensUsed','timeUsedSeconds'))):
                    receipt.update(state='blocked',reason='source_pause_unverified');return
                receipt['source_goal']=paused
                used=policy['tokens_before_source']+paused['tokensUsed']
                native_remaining=policy['token_cap']-used if paused['tokenBudget'] is None else paused['tokenBudget']-paused['tokensUsed']
                remaining=max(0,min(policy['token_cap']-used,native_remaining))
                receipt.update(cumulative_tokens_used=used,remaining_tokens=remaining,source_remaining_tokens=remaining)
                elapsed=policy['seconds_before_source']+paused['timeUsedSeconds']
                receipt['cumulative_seconds_used']=elapsed
                if elapsed>=policy['time_cap_seconds']:
                    receipt.update(state='blocked',reason='cumulative_time_budget_exhausted');return
                if remaining<preflight['token_allowance']:
                    receipt.update(state='blocked',reason='preflight_allowance_insufficient');return
            if receipt.get('uncertain_effect')=='thread/goal/pause':receipt.pop('uncertain_effect',None)
            from .lifecycle_budget import admit_handoff, record_successor, native_usage
            if receipt.get('budget_actor') and receipt.get('successor_thread_id'):
                observed=request('thread/read',dict(threadId=receipt['successor_thread_id'],includeTurns=True))['thread']
                if observed.get('id')!=receipt['successor_thread_id']:raise ValueError('successor usage identity changed')
                usage=native_usage(observed, profile)
                record_successor(root, receipt, usage)
                owned=[turn for turn in observed.get('turns',[]) if turn.get('status')=='inProgress'
                    and any(item.get('type')=='userMessage' and item.get('clientId')==
                            receipt.get('successor',{}).get('submission_id') for item in turn.get('items',[]))]
                if usage is None and len(owned)==1:
                    if not before_handoff_effect(path,receipt):return
                    receipt.update(state='awaiting_preflight',reason='successor_usage_unknown')
                    # Observe the existing reserved turn. No queue, goal or actor
                    # admission may occur until actual accounting is available.
                    return
            if not admit_handoff(root, receipt):return
            receipt.update(state='starting_successor');save(path,receipt)
            contract=dict(source_thread_id=receipt['thread_id'],checkpoint=str(Path(profile['cwd'])/args.checkpoint),
                checkpoint_sha256=args.checkpoint_sha256,intent_fingerprint=receipt['fingerprint'],
                selected_workflow=preflight['workflow'],script=str(script),receipt=str(output),
                token_allowance=preflight['token_allowance'], configuration_revision=effective['revision'],
                handoff_writer={k:v for k,v in effective['handoff_writer'].items() if k!='instructions'},
                preflight_reviewer={k:v for k,v in effective['preflight_reviewer'].items() if k!='instructions'},
                acceptance_criteria=policy.get('acceptance_criteria', []),
                work_review_fields=['verdict','selected_review','changes','acceptance_progress',
                    'scope_deviations','unsupported_claims','unfinished_work','next_packet'])
            if receipt['intent'].get('task_brief') is not None:
                contract['task_brief'] = receipt['intent']['task_brief']
            receipt.setdefault('preflight_task',
                'Preflight only. Read and apply the exact instruction files selected in PREFLIGHT_CONTRACT '
                'and the exact source checkpoint. Record the actual downstream review selected by any router. '
                'Assess changes against the approved criteria and hash-bound evidence; test counts alone '
                'do not prove progress. Return runtime checks separately from work_review with accept/correct/blocked. '
                'Acceptance requires criterion-specific evidence; unsupported claims or scope drift cannot accept. '
                'Run the host-approved Python preflight script with source_thread_id, intent_fingerprint and '
                'checkpoint_sha256 as its three arguments. Read its actual checks; do not fabricate results. '
                'Do not create/activate a goal, enroll in A2A, copy claims or send to another actor. '
                'Continuation requires a separate verified deadline fence.\nPREFLIGHT_CONTRACT='+
                json.dumps(contract,sort_keys=True)+'\nPython executable: '+sys.executable)
            save(path,receipt)
            if not before_handoff_effect(path,receipt):return
            child=SimpleNamespace(profiles=args.profiles,profile=args.profile,
                intent='handoff-preflight:'+receipt['fingerprint'],name='handoff-'+receipt['fingerprint'][:12],
                task=receipt['preflight_task'],expires_at=datetime.fromtimestamp(receipt['continuation_deadline'],UTC).isoformat(),
                caller_thread_id=args.caller_thread_id,as_json=True)
            if receipt['intent'].get('task_brief') is not None:
                child.task_brief_pin = receipt['intent']['task_brief']
            if receipt.get('permission_context'):
                child._handoff_permission_receipt=receipt
            child.budget_context=dict(source_ref=receipt['thread_id'],actor_id=receipt['budget_actor'],
                configuration_revision=effective['revision'])
            if args.mode=='same-tab':
                child.replacement=dict(source_thread_id=receipt['thread_id'],attachment=receipt['source_attachment'])
            if receipt.get('correction_assignment'):
                from .lifecycle_correction import advance_correction
                worker=advance_correction(path,receipt,profile,request)
            else:
                emitted=StringIO()
                with redirect_stdout(emitted):spawn_command(child,root)
                worker=json.loads(emitted.getvalue())
            receipt['successor']=worker
            receipt['successor_thread_id']=worker.get('thread_id')
            if worker.get('thread_id'):
                if owner.get('successor_thread_id') not in (None,worker['thread_id']):
                    receipt.update(state='blocked',reason='successor_ownership_changed');return
                owner['successor_thread_id']=worker['thread_id'];save(owner_path,owner)
            if worker.get('thread_id') and worker.get('submission_id'):
                running=request('thread/read',{'threadId':worker['thread_id'],'includeTurns':True})['thread']
                if running.get('id')!=worker['thread_id']:raise WakeError('preflight usage identity mismatch')
                record_successor(root, receipt, native_usage(running, profile))
                spent=None
                lines=[]
                if running.get('path'):
                    rollout=Path(running['path']).resolve()
                    rollout.relative_to(Path(profile.get('codex_home',Path.home()/'.codex'))/'sessions')
                    if rollout.is_file():lines=rollout.read_text().splitlines()
                for line in lines:
                    event=json.loads(line);payload=event.get('payload',{});info=payload.get('info') or {}
                    if event.get('type')=='event_msg' and payload.get('type')=='token_count' and info.get('total_token_usage'):
                        spent=info['total_token_usage'].get('total_tokens')
                if type(spent) is int and spent>preflight['token_allowance']:
                    owned=[turn for turn in running.get('turns',[]) if turn.get('status')=='inProgress'
                           and any(item.get('type')=='userMessage' and item.get('clientId')==worker['submission_id']
                                   for item in turn.get('items',[]))]
                    receipt.update(state='blocked',reason='preflight_allowance_exhausted',preflight_tokens_used=spent,
                                   preflight_stop=dict(thread_id=worker['thread_id'],turn_ids=[turn['id'] for turn in owned]))
                    save(path,receipt)
                    for turn in owned:
                        receipt['uncertain_effect']='turn/interrupt_preflight';save(path,receipt)
                        request('turn/interrupt',dict(threadId=worker['thread_id'],turnId=turn['id']))
                    receipt.pop('uncertain_effect',None)
                    receipt['preflight_stop']['interrupt_response_received']=True
                    return
            if worker['state']!='completed':
                receipt.update(state=worker['state'],reason='successor_assignment_'+worker['state']);return
            target=worker['thread_id']
            native=request('thread/read',{'threadId':target,'includeTurns':True})['thread']
            record_successor(root, receipt, native_usage(native, profile))
            proof=json.loads(output.read_text())
            required=dict(source_thread_id=receipt['thread_id'],successor_thread_id=target,
                checkpoint_sha256=args.checkpoint_sha256,intent_fingerprint=receipt['fingerprint'],
                selected_workflow=preflight['workflow'],state='passed',
                configuration_revision=effective['revision'])
            marker='preflight:'+target+':'+receipt['fingerprint']+':'+args.checkpoint_sha256
            executions=[i for turn in native['turns'] for i in turn['items']
                if turn['status']=='completed' and i.get('type')=='commandExecution' and i.get('status')=='completed'
                and i.get('exitCode')==0 and i.get('cwd')==str(Path(profile['cwd']).resolve())
                and any(item.get('type')=='userMessage' and item.get('clientId')==worker['submission_id']
                        for item in turn['items'])
                and str(script) in i.get('command','') and marker in (i.get('aggregatedOutput') or '')]
            if (any(proof.get(k)!=v for k,v in required.items()) or len(executions)!=1
                    or any(proof.get('checks',{}).get(k,{}).get('state')!='passed' for k in preflight['required_checks'])):
                receipt.update(state='blocked',reason='successor_preflight_unverified');return
            if not instruction_read(native, effective['preflight_reviewer'], Path(profile['cwd'])):
                receipt.update(state='blocked', reason='reviewer_instructions_unverified');return
            rollout=Path(native['path']).resolve(strict=True)
            rollout.relative_to(Path(profile.get('codex_home',Path.home()/'.codex'))/'sessions')
            usage=None
            for line in rollout.read_text().splitlines():
                event=json.loads(line);payload=event.get('payload',{});info=payload.get('info') or {}
                if event.get('type')=='event_msg' and payload.get('type')=='token_count' and info.get('total_token_usage'):
                    usage=info['total_token_usage'].get('total_tokens')
            if type(usage) is not int or usage<0:
                receipt.update(state='blocked',reason='successor_usage_unknown');return
            if usage>preflight['token_allowance']:
                receipt.update(state='blocked',reason='preflight_allowance_exhausted',preflight_tokens_used=usage);return
            receipt.update(preflight=proof,preflight_tokens_used=usage)
            record_successor(root, receipt, usage)
            receipt['runtime_readiness'] = dict(state='passed', checks=proof['checks'])
            review = proof.get('work_review', {})
            receipt['work_review'] = review
            if review.get('verdict') in ('correct', 'blocked'):
                if review['verdict']=='correct':
                    from .lifecycle_correction import prepare_correction
                    if prepare_correction(path,receipt,policy,profile,review):
                        if receipt['state']=='blocked':
                            receipt['terminal_review']=True
                            record_successor(root,receipt,usage,settled=True)
                        return
                record_successor(root, receipt, usage, settled=True)
                receipt['terminal_review']=True
                receipt.update(state='blocked', reason='work_review_' + review['verdict'])
                return
            if review.get('verdict') != 'accept':
                record_successor(root, receipt, usage, settled=True)
                receipt['terminal_review']=True
                receipt.update(state='blocked', reason='substantive_work_review_unverified')
                return
            if not validate_work_review(review, policy, Path(profile['cwd']),
                                        json.loads(Path(contract['checkpoint']).read_text())):
                record_successor(root, receipt, usage, settled=True)
                receipt['terminal_review']=True
                receipt.update(state='blocked', reason='substantive_work_review_unverified')
                return
            if receipt['remaining_tokens']==0:
                receipt.update(state='blocked',reason='cumulative_token_budget_exhausted');return
            goal=request('thread/goal/get',{'threadId':target})['goal']
            if goal is None:
                if receipt.get('uncertain_effect')=='thread/goal/prepare_successor':
                    receipt.update(state='uncertain',reason='successor_goal_creation_unobserved');return
                if not before_handoff_effect(path,receipt):return
                receipt['uncertain_effect']='thread/goal/prepare_successor';save(path,receipt)
                goal=request('thread/goal/set',dict(threadId=target,objective=policy['objective'],
                    status='paused',tokenBudget=receipt['remaining_tokens'],origin='automatic'))['goal']
            if (goal['objective']!=policy['objective'] or goal['status']!='paused'
                    or goal['tokenBudget']!=receipt['remaining_tokens']):
                receipt.update(state='blocked',reason='successor_goal_authority_changed');return
            receipt.pop('uncertain_effect',None);receipt['successor_goal']=goal
            from .lifecycle_budget import ledger_for, trusted_upper
            receipt['objective_budget']=ledger_for(root,receipt).bind_goal(
                'goal:'+target+':'+str(goal['createdAt']),receipt['budget_actor'],usage,now=trusted_upper())
            receipt.update(state='awaiting_activation',reason='deadline_fence_unverified')
            from .permission_handoff import record_succession
            record_succession(root,receipt,target)
            owner.update(state='successor_prepared',successor_thread_id=target);save(owner_path,owner)
        except Exception as exc:
            receipt.update(state='uncertain' if receipt.get('uncertain_effect') else 'blocked',reason=type(exc).__name__)


def before_handoff_effect(path,receipt):
    from .permission_handoff import before_effect as permission_before_effect
    if not permission_before_effect(path,receipt):return False
    if receipt['intent'].get('task_brief') is not None:
        from .task_briefs import TaskBriefStore
        from .session_permissions import PermissionStore
        TaskBriefStore(PermissionStore(path.parent.parent).root if receipt.get('permission_context') else path.parent.parent).validate_pin(receipt['intent']['task_brief'])
    from .strict_runtime import guard_execution
    if not guard_execution(path.parent.parent,receipt):
        save(path,receipt)
        return False
    from .native_clock import snapshot
    bounds=snapshot().get('utc')
    if not bounds or bounds['upper']>=receipt['continuation_deadline']:
        receipt.update(state='expired' if bounds else 'blocked',reason=(
            'continuation_time_exhausted' if bounds else 'admissible_time_unavailable'))
        save(path,receipt)
        return False
    return True


def poll_handoffs(root,supervision=None,stop_reason=None):
    """Reconcile expiry of owned paused preparations; never infer activation."""
    directory=Path(root)/'lifecycle'
    for path in directory.glob('*.json'):
        if path.name.startswith('owner-'):continue
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            receipt=None
            try:
                receipt=json.loads(path.read_text())
                if receipt.get('intent',{}).get('operation')!='handoff' or receipt.get('state') not in ('awaiting_activation','activating','active','pausing_continuation'):continue
                source=receipt['thread_id'];target=receipt['successor_thread_id']
                key=hashlib.sha256(source.encode()).hexdigest()
                owner=json.loads((directory/('owner-'+key+'.json')).read_text())
                if (owner.get('intent_fingerprint')!=receipt['fingerprint']
                        or owner.get('source_thread_id')!=source or owner.get('successor_thread_id')!=target
                        or owner.get('state') not in (('successor_prepared','active') if receipt['state']=='activating'
                            else ('successor_prepared',) if receipt['state']=='awaiting_activation' else ('active',))):continue
                if receipt.get('deadline_fence'):
                    from .process import process_identity,process_exists
                    import os
                    fence=receipt['deadline_fence']
                    if fence['pid']!=os.getpid() and process_exists(fence['pid']) and process_identity(fence['pid'])==fence['identity']:
                        continue
                    identity=process_identity(os.getpid())
                    if not identity:continue
                    if stop_reason and fence['pid']!=os.getpid():continue
                    fence.update(pid=os.getpid(),identity=identity)
                    save(path,receipt)
                profile=receipt['intent']['launch']
                observed={}
                for thread,saved in ((source,receipt['source_goal']),(target,receipt['successor_goal'])):
                    goal=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                        'thread/goal/get',{'threadId':thread},profile['timeout'])['goal']
                    allowed=('active','paused','complete','budgetLimited','usageLimited') if thread==target and receipt['state']!='awaiting_activation' else ('paused',)
                    if (not goal or goal.get('status') not in allowed
                            or any(goal.get(k)!=saved.get(k) for k in ('threadId','objective','tokenBudget','createdAt'))):
                        raise ValueError('owned paused goal changed')
                    observed[thread]=goal
                receipt['monitor_observed_goals']=observed
                objective_stop=None
                if receipt.get('budget_actor'):
                    from .lifecycle_budget import ledger_for, record_successor, trusted_upper,native_usage,record_goal_observation
                    from .native_clock import snapshot
                    if not snapshot().get('utc'):
                        objective_stop='objective_accounting_time_unavailable'
                    else:
                        now=trusted_upper()
                        ledger=ledger_for(root,receipt)
                        source_goal=observed[source]
                        def observe_request(method,params):
                            return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                                method,params,profile['timeout'])
                        record_goal_observation(ledger,'goal:'+source+':'+str(source_goal['createdAt']),
                            source_goal,profile,observe_request,settled=True,now=now)
                        rollout=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                            'thread/read',dict(threadId=target,includeTurns=True),profile['timeout'])['thread']
                        if rollout.get('id')!=target:raise ValueError('owned rollout identity changed')
                        total=native_usage(rollout,profile)
                        terminal=not any(t.get('status')=='inProgress' for t in rollout['turns'])
                        view=record_successor(root,receipt,total,settled=observed[target]['status']=='complete' and terminal)
                        actor=view['actors'][receipt['budget_actor']]
                        if (not view['accounting_known'] or
                                view['tokens_used']+view['tokens_reserved']>view['objective_token_limit'] or
                                actor['tokens_remaining']==0 or now>=actor['session_deadline'] or
                                now>=parse_timestamp(view['objective_deadline']).timestamp()):
                            objective_stop='objective_budget_or_accounting_stop'
                        if now>=actor['session_deadline'] or now>=parse_timestamp(view['objective_deadline']).timestamp():
                            objective_stop='continuation_time_exhausted'
                saved_source=receipt['source_goal'];current_source=observed[source]
                accounting_stop=objective_stop
                for counter in ('tokensUsed','timeUsedSeconds'):
                    value=current_source.get(counter);previous=saved_source.get(counter)
                    if type(value) is not int or type(previous) is not int or value<previous:
                        accounting_stop='source_accounting_unverified';break
                    if value>previous:accounting_stop='source_accounting_advanced'
                if accounting_stop:
                    receipt['continuation_stop_reason']=accounting_stop
                    if receipt['state']=='awaiting_activation' or observed[target]['status']=='complete':
                        receipt.update(state='expired' if accounting_stop=='continuation_time_exhausted' else 'blocked',reason=accounting_stop)
                        owner['state']='stopped';save(directory/('owner-'+key+'.json'),owner)
                        save(path,receipt);continue
                if receipt['state']=='activating':
                    if observed[target]['status']!='active':
                        receipt['monitor_error']='successor_activation_unobserved';save(path,receipt);continue
                    receipt.update(state='active',reason='continuation_active',successor_goal=observed[target])
                    receipt.pop('uncertain_effect',None);receipt.pop('monitor_error',None)
                    owner['state']='active';save(directory/('owner-'+key+'.json'),owner);save(path,receipt)
                activation=receipt['intent']['continuation'].get('activation',{})
                if receipt['state'] in ('active','pausing_continuation'):
                    from .native_clock import snapshot
                    bounds=snapshot().get('utc')
                    target_goal=observed[target]
                    if target_goal['status']=='complete':
                        if receipt.get('budget_actor') and (not terminal or not view['accounting_known']):
                            receipt['monitor_error']='goal_complete_final_accounting_pending';save(path,receipt);continue
                        receipt.update(state='completed',reason='successor_goal_complete',successor_goal=target_goal)
                        owner['state']='completed';save(directory/('owner-'+key+'.json'),owner);save(path,receipt)
                        continue
                    if (accounting_stop or stop_reason or not bounds or bounds['upper']+activation['deadline_margin_seconds']>=receipt['continuation_deadline']
                            or target_goal['tokensUsed']>=target_goal['tokenBudget']
                            or target_goal['status']!='active'):
                        reason=receipt.get('continuation_stop_reason') or stop_reason or ('admissible_time_unavailable' if not bounds else
                            'deadline_safety_stop' if bounds['upper']+activation['deadline_margin_seconds']>=receipt['continuation_deadline']
                            else 'continuation_budget_or_status_stop')
                        receipt.update(state='pausing_continuation',reason=reason,continuation_stop_reason=reason)
                        def request(method,params):
                            return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                                method,params,profile['timeout'])
                        if target_goal['status']=='paused':
                            paused=target_goal
                        else:
                            if receipt.get('uncertain_effect')=='thread/goal/pause_successor':
                                receipt['monitor_error']='successor_pause_unobserved';save(path,receipt);continue
                            receipt['uncertain_effect']='thread/goal/pause_successor';save(path,receipt)
                            paused=request('thread/goal/set',dict(threadId=target,status='paused',origin='automatic'))['goal']
                        if (paused.get('status')!='paused' or any(paused.get(k)!=target_goal.get(k)
                                for k in ('threadId','objective','tokenBudget','createdAt'))):
                            raise ValueError('successor pause unverified')
                        receipt['successor_goal']=paused
                        if receipt.get('uncertain_effect')=='thread/goal/pause_successor':receipt.pop('uncertain_effect',None)
                        save(path,receipt)
                        thread=request('thread/read',dict(threadId=target,includeTurns=True))['thread']
                        turns=[t for t in thread['turns'] if t['status']=='inProgress']
                        if thread['id']!=target or len(turns)>1:raise ValueError('active turn ambiguous')
                        if turns:
                            if receipt.get('uncertain_effect')=='turn/interrupt':
                                receipt['monitor_error']='turn_interrupt_unobserved';save(path,receipt);continue
                            receipt.update(uncertain_effect='turn/interrupt',stop_turn_id=turns[0]['id']);save(path,receipt)
                            request('turn/interrupt',dict(threadId=target,turnId=turns[0]['id']))
                            final=request('thread/read',dict(threadId=target,includeTurns=True))['thread']
                            if any(t['status']=='inProgress' for t in final['turns']):raise ValueError('turn stop unverified')
                        receipt.pop('uncertain_effect',None)
                        receipt.pop('monitor_error',None)
                        if receipt.get('budget_actor') and bounds:
                            final_native=request('thread/read',dict(threadId=target,includeTurns=True))['thread']
                            total=native_usage(final_native,profile)
                            record_successor(root,receipt,total,settled=True)
                        receipt['state']='expired' if reason=='deadline_safety_stop' else 'blocked'
                        owner['state']='stopped';save(directory/('owner-'+key+'.json'),owner)
                    save(path,receipt)
                    continue
                if not before_handoff_effect(path,receipt):continue
                if (supervision and activation.get('approved') is True
                        and type(activation.get('max_poll_seconds')) in (int,float)
                        and 0<supervision['interval']<=activation['max_poll_seconds']<=5
                        and type(activation.get('deadline_margin_seconds')) in (int,float)
                        and activation['deadline_margin_seconds']>=activation['max_poll_seconds']+4*profile['timeout']):
                    from .native_clock import snapshot
                    from .process import process_identity
                    import os
                    bounds=snapshot().get('utc')
                    if not bounds or bounds['upper']+activation['deadline_margin_seconds']>=receipt['continuation_deadline']:continue
                    identity=process_identity(os.getpid())
                    if not identity:continue
                    from .wake_control import delivery_guard
                    with delivery_guard(root):
                        if not before_handoff_effect(path,receipt):continue
                        receipt.update(state='activating',uncertain_effect='thread/goal/activate_successor',
                            deadline_fence=dict(pid=os.getpid(),identity=identity,utc=bounds,
                                interval=supervision['interval'],deadline=receipt['continuation_deadline']))
                        save(path,receipt)
                        active=native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                            'thread/goal/set',dict(threadId=target,status='active',origin='automatic'),profile['timeout'])['goal']
                    if active.get('status')!='active':raise ValueError('goal activation unverified')
                    receipt.update(state='active',reason='continuation_active',successor_goal=active)
                    receipt.pop('uncertain_effect',None)
                    owner['state']='active';save(directory/('owner-'+key+'.json'),owner)
                save(path,receipt)
            except Exception as exc:
                # Failed observation cannot certify enforcement or authorize activation.
                if isinstance(receipt,dict) and receipt.get('intent',{}).get('operation')=='handoff':
                    receipt['monitor_error']=type(exc).__name__;save(path,receipt)
                continue
