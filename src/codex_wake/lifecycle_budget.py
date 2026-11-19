"""Bind native lifecycle observations to one durable objective allowance."""
import hashlib
import json
from pathlib import Path

from .objective_ledger import ObjectiveLedger


def operation_binding(config, args, source_ref=None, *, _permission_checked=False):
    """Only host registry context can bind an assignment to an objective."""
    from .lifecycle_configuration import effective_configuration
    from .records import WakeError
    inherited=getattr(args,'budget_context',None)
    reference=source_ref or (inherited or {}).get('source_ref') or getattr(args,'objective_ref',None) or args.caller_thread_id
    policies=config.get('continuations',{})
    configured=bool(config.get('lifecycle_defaults')) or bool(policies.get(reference,{}).get('configuration'))
    if not configured and not getattr(args,'objective_ref',None) and not inherited:return None
    if not reference or reference not in policies:
        raise WakeError('configured spawn requires an approved objective reference')
    if args.caller_thread_id and reference!=args.caller_thread_id:
        raise WakeError('caller cannot select another objective reference')
    effective=effective_configuration(config,reference,args.profile,args.caller_thread_id,_permission_checked=_permission_checked)
    lower=policies[reference].get('spawn_token_limit',effective['session_token_limit'])
    if type(lower) is not int or not 0<lower<=effective['session_token_limit']:
        raise WakeError('host spawn token limit must be within the configured session allowance')
    binding=dict(continuation=policies[reference],configuration=effective,objective_ref=reference)
    if inherited:
        if inherited.get('configuration_revision')!=effective['revision']:
            raise WakeError('inherited objective configuration changed')
        binding['budget_inherited']=inherited['actor_id']
    return binding


def ledger_for(root, receipt):
    policy = receipt['intent']['continuation']
    return ObjectiveLedger(root, objective_identity(policy))


def objective_identity(policy):
    return policy.get('objective_id') or hashlib.sha256(json.dumps(
        [policy['objective'], policy['started_at']], sort_keys=True).encode()).hexdigest()


def trusted_upper():
    from .measurements import utc_bounds, TimeUnavailable
    try:
        return utc_bounds()[1]
    except TimeUnavailable:
        raise ValueError('admissible time unavailable') from None


def configured_ledger(root,receipt):
    policy=receipt['intent']['continuation']
    configuration={key:value for key,value in receipt['intent']['configuration'].items()
                   if key not in ('source_thread_id','profile')}
    ledger=ledger_for(root,receipt)
    ledger.configure(configuration,policy['approval'],policy.get('tokens_before_source',0),now=trusted_upper())
    return ledger


def record_goal_observation(ledger,key,goal,profile,request,*,settled,now):
    """Native goal counters may discount cache; owned session rollouts do not."""
    view=ledger.view(now=now);binding=view['goal_aliases'].get(key)
    native=None
    if not binding and 'strict_execution' in profile:
        # A paused native goal may be created after an owned spawn finishes.
        # Bind it only at an exact, verified budget boundary; display counters
        # cannot be subtracted from cumulative usage to invent an offset.
        candidates=set()
        for path in (ledger.directory.parent/'lifecycle').glob('*.json'):
            if path.name=='supervision.json' or path.name.startswith('owner-'):continue
            receipt=json.loads(path.read_text());intent=receipt.get('intent',{})
            launch=intent.get('launch',{})
            thread=(receipt.get('successor_thread_id') if intent.get('operation')=='handoff'
                    else receipt.get('thread_id') if intent.get('operation')=='spawn' else None)
            configuration=receipt.get('configuration') or intent.get('configuration',{})
            if (thread==goal['threadId'] and objective_identity(intent.get('continuation',{}))==ledger.objective_id
                    and configuration.get('revision')==view['revision']
                    and launch.get('app_server')==profile.get('app_server')
                    and Path(launch.get('codex_home','')).resolve()==Path(profile.get('codex_home','')).resolve()
                    and receipt.get('budget_actor') in view['actors']):
                candidates.add(receipt['budget_actor'])
        if len(candidates)!=1:
            raise ValueError('strict native goal has no unique owned accounting binding')
        actor_id=next(iter(candidates));actor=view['actors'][actor_id]
        native=request('thread/read',dict(threadId=goal['threadId'],includeTurns=True))['thread']
        turns=native.get('turns',[])
        if (native.get('id')!=goal['threadId'] or not turns
                or any(t.get('status') not in ('completed','failed','interrupted') for t in turns)):
            raise ValueError('owned native goal work is not settled')
        usage=native_usage(native,profile,settled_turn_id=turns[-1]['id'])
        if (not actor['known'] or not actor['settled'] or usage is None or usage!=actor['used']
                or key!='goal:'+goal['threadId']+':'+str(goal['createdAt'])
                or goal.get('status')!='paused' or type(goal.get('tokensUsed')) is not int
                or goal['tokensUsed']!=0 or type(goal.get('timeUsedSeconds')) is not int
                or goal['timeUsedSeconds']!=0
                or type(goal.get('tokenBudget')) is not int or goal['tokenBudget']<=0
                or goal['tokenBudget']!=actor['tokens_remaining']):
            raise ValueError('owned native goal budget binding unavailable')
        view=ledger.bind_goal(key,actor_id,usage,now=now)
        binding=view['goal_aliases'][key]
    if not binding:
        return ledger.record_goal(key,goal.get('tokensUsed'),settled=settled,now=now)
    if native is None:native=request('thread/read',dict(threadId=goal['threadId'],includeTurns=True))['thread']
    if native.get('id')!=goal['threadId']:raise ValueError('source rollout identity changed')
    return ledger.record(binding['actor_id'],native_usage(native,profile),
        settled=settled and not any(t.get('status')=='inProgress' for t in native['turns']),now=now)


def track_refresh_budget(root,receipt,goal):
    """Refresh observes the same goal; it never reserves a replacement session."""
    from .records import parse_timestamp
    ledger=configured_ledger(root,receipt);now=trusted_upper()
    policy=receipt['intent']['continuation'];cfg=receipt['intent']['configuration']
    if (not goal or goal.get('threadId')!=receipt['thread_id'] or goal.get('objective')!=policy['objective']
            or type(goal.get('tokensUsed')) is not int or goal['tokensUsed']<0):
        receipt.update(state='blocked',reason='source_goal_accounting_unknown');return False
    key='goal:'+goal['threadId']+':'+str(goal['createdAt'])
    from .native_protocol import native_request
    from .app_server import resolve_codex_cmd
    profile=receipt['intent']['launch']
    def request(method,params):
        return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),method,params,profile['timeout'])
    view=record_goal_observation(ledger,key,goal,profile,request,settled=goal['status']=='paused',now=now)
    alias=view['goal_aliases'].get(key)
    actor=view['actors'][alias['actor_id'] if alias else key]
    session_deadline=actor.get('session_deadline') or (parse_timestamp(
        policy.get('session_started_at',policy['started_at'])).timestamp()+cfg['session_time_limit_seconds'])
    receipt['objective_budget']=view
    receipt['assignment_deadline']=min(receipt.get('assignment_deadline',float('inf')),
        session_deadline,parse_timestamp(cfg['objective_deadline']).timestamp())
    if (not view['accounting_known'] or view['tokens_used']>=cfg['objective_token_limit']
            or now>=receipt['assignment_deadline'] or goal['tokensUsed']>=cfg['session_token_limit']):
        receipt.update(state='blocked',reason='objective_budget_or_accounting_stop');return False
    return True


def admit_spawn(root,receipt,request):
    """Reserve one assignment without renewing its terms on replay."""
    from uuid import UUID
    from .records import parse_timestamp
    ledger=configured_ledger(root,receipt);now=trusted_upper()
    cfg=receipt['intent']['configuration'];policy=receipt['intent']['continuation']
    reference=receipt['intent']['objective_ref']
    try:UUID(reference)
    except ValueError:pass  # Operator bootstrap reference has no native parent.
    else:
        goal=request('thread/goal/get',{'threadId':reference})['goal']
        if not goal or goal.get('threadId')!=reference or goal.get('objective')!=policy['objective']:
            receipt['reason']='source_goal_identity_unverified';return False
        key='goal:'+reference+':'+str(goal['createdAt'])
        view=record_goal_observation(ledger,key,goal,receipt['intent']['launch'],request,settled=goal['status']!='active',now=now)
        if goal['status']=='active':
            if type(goal.get('tokenBudget')) is not int or goal['tokenBudget']<=0:
                receipt.update(reason='source_session_allowance_unverified',objective_budget=view);return False
            deadline=parse_timestamp(policy.get('session_started_at',policy['started_at'])).timestamp()+cfg['session_time_limit_seconds']
            view=ledger.adopt_active_goal(key,goal.get('tokenBudget'),deadline,now=now)
            if not view['admitted']:
                receipt.update(reason='source_session_allowance_unverified',objective_budget=view);return False
    view=ledger.view(now=now)
    actor_id=receipt['intent'].get('budget_inherited') or 'spawn:'+receipt['fingerprint']
    actor=view['actors'].get(actor_id)
    if receipt['intent'].get('budget_inherited'):
        admitted=bool(actor and actor['known'] and not actor['settled'] and actor['tokens_remaining']>0
            and view['accounting_known'] and now<actor['session_deadline']
            and view['tokens_used']+view['tokens_reserved']<=cfg['objective_token_limit'])
    else:
        if actor:tokens,seconds=actor['terms']
        else:
            tokens=min(cfg['session_token_limit'],policy.get('spawn_token_limit',cfg['session_token_limit']),view['remaining_tokens'])
            seconds=int(min(cfg['session_time_limit_seconds'],view['remaining_seconds'],
                parse_timestamp(receipt['intent']['expires_at']).timestamp()-now))
        view=ledger.reserve(actor_id,tokens,max(0,seconds),now=now) if tokens>0 and seconds>0 else dict(view,admitted=False)
        admitted=view['admitted'];actor=view['actors'].get(actor_id)
    receipt.update(objective_budget=view,budget_actor=actor_id)
    if actor:receipt['assignment_deadline']=actor['session_deadline']
    if not admitted:receipt['reason']='objective_admission_denied'
    return admitted


def observe_spawn(root,receipt,native,profile,settled=False):
    ledger=configured_ledger(root,receipt)
    inherited=bool(receipt['intent'].get('budget_inherited'))
    turn_id=receipt.get('execution',{}).get('turn_id') or receipt.get('supervisor_owned_turn_id')
    usage=native_usage(native,profile,settled_turn_id=turn_id if settled and not inherited else None)
    if usage is not None and native.get('turns'):
        receipt['native_usage_observed']=True
    view=ledger.record(receipt['budget_actor'],usage,
                       settled=settled and not inherited,now=trusted_upper())
    receipt['objective_budget']=view
    return view


def admit_handoff(root, receipt):
    now = trusted_upper()
    config = {key: value for key, value in receipt['configuration'].items()
              if key not in ('source_thread_id', 'profile')}
    policy = receipt['intent']['continuation']
    ledger = ledger_for(root, receipt)
    ledger.configure(config, policy['approval'], policy['tokens_before_source'], now=now)
    source = receipt['source_goal']
    actor = 'goal:' + source['threadId'] + ':' + str(source['createdAt'])
    from .native_protocol import native_request
    from .app_server import resolve_codex_cmd
    profile=receipt['intent']['launch']
    def request(method,params):
        return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
            method,params,profile['timeout'])
    view = record_goal_observation(ledger,actor,source,profile,request,settled=True,now=now)
    source_binding=view['goal_aliases'].get(actor)
    source_actor=view['actors'][source_binding['actor_id'] if source_binding else actor]
    if source_actor.get('terms') is not None:
        receipt['source_remaining_tokens']=min(receipt['source_remaining_tokens'],source_actor['tokens_remaining'])
    if source_actor.get('session_deadline') is not None:
        receipt['continuation_deadline']=min(receipt['continuation_deadline'],source_actor['session_deadline'])
    successor = 'handoff:' + receipt['fingerprint']
    existing = view['actors'].get(successor)
    if existing and existing.get('terms'):
        tokens, seconds = existing['terms']
    else:
        tokens = min(config['session_token_limit'], view['remaining_tokens'], receipt['source_remaining_tokens'])
        seconds = int(min(config['session_time_limit_seconds'], view['remaining_seconds'],
                          receipt['continuation_deadline'] - now))
    if tokens <= 0 or seconds <= 0:
        receipt.update(state='blocked', reason='objective_allowance_exhausted', objective_budget=view)
        return False
    view = ledger.reserve(successor, tokens, seconds, now=now)
    receipt['objective_budget'] = view
    receipt['budget_actor'] = successor
    if not view['admitted']:
        receipt.update(state='blocked', reason='objective_admission_denied')
        return False
    owned = view['actors'][successor]
    receipt['continuation_deadline'] = min(receipt['continuation_deadline'], owned['session_deadline'])
    receipt['remaining_tokens'] = owned['tokens_remaining']
    return True


def record_successor(root, receipt, cumulative_tokens, *, settled=False):
    view = ledger_for(root, receipt).record(receipt['budget_actor'], cumulative_tokens,
                                          settled=settled, now=trusted_upper())
    receipt['objective_budget'] = view
    receipt['remaining_tokens'] = view['actors'][receipt['budget_actor']]['tokens_remaining']
    return view


def native_usage(native, profile,settled_turn_id=None):
    if native.get('turns') == []:
        return 0
    if not native.get('path'):
        return None
    rollout = Path(native['path']).resolve()
    rollout.relative_to(Path(profile.get('codex_home', Path.home() / '.codex')) / 'sessions')
    if not rollout.is_file():
        return None
    usage = None
    final=False
    for line in rollout.read_text().splitlines():
        event = json.loads(line)
        payload = event.get('payload', {})
        info = payload.get('info') or {}
        if (event.get('type')=='event_msg' and payload.get('type') in ('task_complete','turn_aborted')
                and payload.get('turn_id')==settled_turn_id):
            final=True
            if settled_turn_id is not None:break
        if event.get('type') == 'event_msg' and payload.get('type') == 'token_count' and info.get('total_token_usage'):
            value = info['total_token_usage'].get('total_tokens')
            usage = value if type(value) is int and value >= 0 else None
    return usage if settled_turn_id is None or final else None
