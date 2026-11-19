"""Owned resident lifecycle supervision; a one-shot poll cannot admit model work."""
import json
import os
import fcntl
from pathlib import Path

from . import measurements
from .agent_lifecycle import save
from .lifecycle_budget import trusted_upper
from .process import process_exists,process_identity,boot_id_value


def publish_supervision(root,interval,active=True):
    path=Path(root)/'lifecycle/supervision.json'
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:clock=measurements.snapshot() if active else None
    except measurements.TimeUnavailable:clock=None
    observed_at=clock['utc']['upper'] if clock and clock.get('reason')=='authenticated_utc' else None
    current=dict(state='active' if active else 'stopped',pid=os.getpid(),identity=process_identity(os.getpid()),interval=interval,
                 active=active,observed_at=observed_at,
                 observed_boottime=None,clock_observation=clock,
                 clock_status='qualified' if clock else 'unavailable',boot_id=boot_id_value())
    if not current['identity']:raise ValueError('supervisor process generation unavailable')
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if path.exists():
            previous=json.loads(path.read_text())
            if (previous.get('active') and previous['pid']!=current['pid'] and
                    process_exists(previous['pid']) and process_identity(previous['pid'])==previous['identity']):
                raise ValueError('another live lifecycle supervisor owns this root')
        save(path,current)
    return current


def supervision_ready(root,timeout):
    try:
        path=Path(root)/'lifecycle/supervision.json'
        info=path.lstat()
        if path.is_symlink() or info.st_uid!=os.geteuid() or info.st_mode&0o777!=0o600:return False
        proof=json.loads(path.read_text())
        return (proof.get('active') is True and 0<proof['interval']<=5
            and process_exists(proof['pid']) and process_identity(proof['pid'])==proof['identity']
            and Path('/proc',str(proof['pid']),'stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
            and proof.get('boot_id')==boot_id_value()
            and measurements.fresh(proof.get('clock_observation'),5*proof['interval']+4*timeout))
    except (OSError,ValueError,KeyError,TypeError,IndexError):return False


def poll_spawns(root,stop_reason=None):
    """Observe reservations; never queue tasks or acquire a new actor."""
    from .native_protocol import native_request
    from .app_server import resolve_codex_cmd
    from .lifecycle_budget import observe_spawn
    directory=Path(root)/'lifecycle'
    for path in directory.glob('*.json'):
        if path.name.startswith('owner-') or path.name=='supervision.json':continue
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            receipt=None
            try:
                receipt=json.loads(path.read_text());intent=receipt.get('intent',{})
                if (intent.get('operation')!='spawn' or intent.get('budget_inherited')
                        or not receipt.get('budget_actor') or not receipt.get('thread_id')
                        or receipt.get('state')=='completed'):continue
                profile=intent['launch'];codex=resolve_codex_cmd(profile['codex_path'],required=True)
                def request(method,params):
                    return native_request(profile['app_server'],codex,method,params,profile['timeout'])
                native=request('thread/read',{'threadId':receipt['thread_id'],'includeTurns':True})['thread']
                if native.get('id')!=receipt['thread_id']:raise ValueError('native thread identity changed')
                owned=[turn for turn in native.get('turns',[]) if any(
                    item.get('type')=='userMessage' and item.get('clientId')==receipt.get('submission_id')
                    for item in turn.get('items',[]))]
                if receipt.get('cancelled_queue_id') and native.get('turns')==[]:
                    observe_spawn(root,receipt,native,profile,settled=True)
                    save(path,receipt)
                    continue
                if not owned and receipt.get('submission_id'):
                    try:expired=trusted_upper()>=receipt['assignment_deadline']
                    except ValueError:expired=True
                    if expired or stop_reason:
                        queue=request('thread/queue/list',{'threadId':receipt['thread_id']})
                        matches=[item for item in queue['data'] if item.get('clientUserMessageId')==receipt['submission_id']
                            and len(item.get('input',[]))==1 and item['input'][0].get('type')=='text'
                            and item['input'][0].get('text')==intent['task']
                            and item['input'][0].get('text_elements',[])==[]]
                        if queue.get('nextCursor') is None and len(matches)==1:
                            deleted=request('thread/queue/delete',{'threadId':receipt['thread_id'],
                                'queuedSubmissionId':matches[0]['id']})
                            if deleted.get('deleted') is True:
                                receipt.update(state='blocked',reason=stop_reason or 'expired_queued_assignment_cancelled',
                                    cancelled_queue_id=matches[0]['id'])
                                receipt.pop('uncertain_effect',None)
                                save(path,receipt)
                    continue
                if len(owned)!=1:continue
                turn=owned[0]
                receipt['supervisor_owned_turn_id']=turn['id']
                if any(t.get('status')=='inProgress' and t['id']!=turn['id'] for t in native.get('turns',[])):
                    receipt.update(state='blocked',reason='foreign_turn_preserved');save(path,receipt);continue
                previous=receipt.get('objective_budget',{}).get('accounting_known')
                if receipt['intent'].get('configuration',{}).get('strict_execution'):
                    previous=receipt.get('native_usage_observed',False)
                terminal=turn['status'] in ('completed','failed','interrupted')
                view=None
                try:
                    from uuid import UUID
                    from .lifecycle_budget import configured_ledger,record_goal_observation
                    try:UUID(intent['objective_ref'])
                    except ValueError:pass
                    else:
                        parent=request('thread/goal/get',{'threadId':intent['objective_ref']})['goal']
                        if (not parent or parent.get('threadId')!=intent['objective_ref']
                                or parent.get('objective')!=intent['continuation']['objective']):
                            raise ValueError('source goal identity changed')
                        record_goal_observation(configured_ledger(root,receipt),
                            'goal:'+parent['threadId']+':'+str(parent['createdAt']),parent,profile,request,
                            settled=parent['status']!='active',now=trusted_upper())
                    view=observe_spawn(root,receipt,native,profile,settled=terminal)
                    actor=view['actors'][receipt['budget_actor']];now=trusted_upper()
                    reason=stop_reason
                    if (now>=actor['session_deadline'] or view['remaining_seconds']<=0
                            or actor['tokens_remaining']==0
                            or view['tokens_used']+view['tokens_reserved']>view['objective_token_limit']):
                        reason=reason or 'objective_budget_exhausted'
                    if previous and not view['accounting_known']:reason=reason or 'objective_accounting_unknown'
                except ValueError:
                    view=None
                    reason=stop_reason or 'objective_accounting_unverified'
                if reason and turn['status']=='inProgress':
                    request('turn/interrupt',{'threadId':receipt['thread_id'],'turnId':turn['id']})
                    receipt.update(state='blocked',reason=reason,supervisor_owned_turn_id=turn['id'])
                elif terminal and reason:
                    receipt.update(state='blocked',reason=reason)
                elif terminal and view is not None and view['accounting_known']:
                    receipt.update(state='completed' if turn['status']=='completed' else 'blocked',
                        reason=None if turn['status']=='completed' else 'initial_task_turn_'+turn['status'])
                save(path,receipt)
            except Exception as exc:
                if receipt and receipt.get('budget_actor'):
                    receipt['supervisor_observation_error']=type(exc).__name__
                    save(path,receipt)
                continue
