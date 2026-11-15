"""Frozen wake routes and permission checks at registration/effect boundaries."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from .records import WakeError, append_event, replace_record
from .runtime_delivery import RuntimeSubmission, RuntimeTargetError
from .session_permissions import PermissionStore, Principal, PermissionDenied, check_operation

ROUTES={'background':'wake.background','existing_tab':'wake.existing_tab',
        'new_tab':'wake.new_tab','fresh_task':'wake.fresh_task'}
DEFAULT_ROUTES={'active_tab':['existing_tab'],'background_saved':['background'],
                'create_load_run':['existing_tab','background','new_tab']}


def _principal(args):
    value=getattr(args,'_permission_principal',None)
    if value is None:
        from .permission_commands import verified_cli_principal
        value=verified_cli_principal(args)
    if not isinstance(value,Principal):raise PermissionDenied('wake_identity_unverified')
    return value


def _target(conversation):
    return conversation.split(':',1)[1] if conversation.startswith(('codex:','grok:')) else conversation


def valid_context(context):
    return (isinstance(context,dict) and set(context)=={'subject','role','tasks','target','task_id','revision'}
        and all(isinstance(context.get(k),str) and context[k] for k in ('subject','target'))
        and context['role'] in ('operator','session','controller')
        and isinstance(context['tasks'],list) and len(context['tasks'])<=256
        and all(isinstance(x,str) and x for x in context['tasks'])
        and (context['task_id'] is None or isinstance(context['task_id'],str) and bool(context['task_id']))
        and type(context['revision']) is int and context['revision']>0)


def valid_routes(routes):
    return (isinstance(routes,list) and 0<len(routes)<=len(ROUTES)
        and all(isinstance(x,str) and x in ROUTES for x in routes) and len(set(routes))==len(routes))


def valid_progress(record):
    routes=record['wake_policy']['routes']
    progress=record.get('wake_route_progress',{'next':0,'history':[]})
    if (not isinstance(progress,dict) or set(progress)!={'next','history'}
            or type(progress['next']) is not int or not 0<=progress['next']<=len(routes)
            or not isinstance(progress['history'],list) or len(progress['history'])>len(routes)):
        return False
    previous=-1
    for entry in progress['history']:
        if (not isinstance(entry,dict) or set(entry)!={'route','state','pre_io','reason','submission_id'}
                or entry['route'] not in routes or entry['state']!='not_sent' or entry['pre_io'] is not True
                or (entry['reason'] is not None and not isinstance(entry['reason'],str))):return False
        index=routes.index(entry['route'])
        if index<=previous:return False
        previous=index
        try:UUID(entry['submission_id'])
        except (TypeError,ValueError,AttributeError):return False
    if progress['next']!=previous+1:return False
    delivery=record.get('native_delivery') or record.get('runtime_delivery')
    if delivery and delivery.get('route') not in routes[progress['next']:]:return False
    return True


def validate_retry(root,args,policy,conversation):
    explicit=getattr(args,'wake_routes',None)
    if explicit is not None and (policy.get('version')!=2 or explicit!=policy['routes']):
        raise WakeError('idempotency_conflict: wake route list differs')
    if policy.get('version')==2:
        principal=_principal(args);context=policy['permission_context']
        if context['target']!=_target(conversation) or (principal.role!='operator' and principal.subject!=context['subject']):
            raise PermissionDenied('wake_identity_changed')


def decorate_policy(root,args,conversation,policy):
    store=PermissionStore(root)
    if not store.active():
        if getattr(args,'wake_routes',None) is not None:raise PermissionDenied('wake_permission_policy_required')
        return policy
    principal=_principal(args);target=_target(conversation)
    if principal.role=='session' and principal.subject!=target:
        raise PermissionDenied('wake_exact_self_required')
    mode = getattr(args, 'session_mode', None)
    mode_routes = {'session_only': ['existing_tab'], 'reopen_live': ['existing_tab', 'new_tab'],
                   'background': ['existing_tab', 'background']}
    routes = getattr(args, 'wake_routes', None) or mode_routes.get(mode, DEFAULT_ROUTES[policy['startup']])
    if mode in mode_routes and routes != mode_routes[mode]:
        raise WakeError('session_mode_routes_conflict')
    if not valid_routes(routes):raise WakeError('invalid_wake_routes')
    if policy['startup']=='active_tab' and routes!=['existing_tab']:
        raise WakeError('active_tab_conflicts_with_routes')
    if policy['startup']=='background_saved' and set(routes)-{'background','existing_tab'}:
        raise WakeError('background_policy_conflicts_with_routes')
    task_id=policy['owner']['id'] if policy['owner'] and policy['owner']['kind']=='task' else None
    if 'fresh_task' in routes and not task_id:
        raise PermissionDenied('fresh_task_requires_declared_task')
    decision=None
    for route in routes:
        decision=check_operation(store.root,ROUTES[route],principal,target=target,task_id=task_id)
    context=dict(subject=principal.subject,role=principal.role,tasks=list(principal.tasks),
        target=target,task_id=task_id,revision=decision['revision'])
    return dict(policy,version=2,routes=list(routes),permission_context=context)


def check_route(root,record,route):
    policy=record['wake_policy'];context=policy['permission_context']
    store=PermissionStore(root)
    if not store.active():raise PermissionDenied('wake_permission_policy_unavailable')
    expected=record['target'].get('thread_id') or record['target'].get('session_id')
    if context['target']!=expected:raise PermissionDenied('wake_recipient_changed')
    principal=Principal(context['subject'],context['role'],tuple(context['tasks']))
    return check_operation(store.root,ROUTES[route],principal,target=expected,task_id=context['task_id'])


def common_record(record):
    return record.get('schema_version')==8 and record.get('wake_policy',{}).get('version')==2


class RouteAdapter:
    """Keep the actual exact target; route selection never substitutes identity."""
    def __init__(self,adapter,route):self.adapter,self.route=adapter,route
    def resolve(self,target):
        # observe must remain read-only. Saved resume/new-tab launch belongs to a
        # separately qualified route adapter, not a guessed fallback here.
        return self.adapter.resolve(dict(target,wake_route=self.route,resume_policy='hold',
            startup_policy='active_tab' if self.route=='existing_tab' else 'background_saved'))
    def observe(self,recipient):return self.adapter.observe(recipient)
    def submit(self,recipient,prompt):return self.adapter.submit(recipient,prompt)
    def reconcile(self,recipient,prompt):return self.adapter.reconcile(recipient,prompt)


def supported(route,observation,runtime='codex'):
    explicit=observation.capabilities.get(ROUTES[route])
    if explicit is not None:return explicit.state=='supported'
    if route=='existing_tab':
        cap=observation.capabilities.get('active_tab')
        return cap is not None and cap.state=='supported'
    if route=='background' and runtime=='codex':
        cap=observation.capabilities.get('submit')
        return cap is not None and cap.state=='supported'
    return False


def dispatch_native(root,found,now,*,clock_provider,adapter):
    from .injector import DispatchResult
    from .native_intents import dispatch_gate
    from .native_delivery import native_prompt,reconcile_native
    record=dict(found.record);routes=record['wake_policy']['routes']
    existing=record.get('native_delivery',{})
    if existing.get('state')=='uncertain':
        route=existing.get('route')
        if route not in routes:return DispatchResult('skipped','uncertain wake route invalid; no resend')
        # Read-only reconciliation remains allowed after revocation. It cannot
        # submit or select a new route, and uses the original exact target.
        return reconcile_native(root,found,now,runtime_adapter=RouteAdapter(adapter,route))
    progress=record.get('wake_route_progress',{'next':0,'history':[]})
    start=progress.get('next',0)
    if type(start) is not int or not 0<=start<=len(routes):
        return DispatchResult('skipped','wake route progress invalid')
    reasons=[]
    for index in range(start,len(routes)):
        route=routes[index]
        try:
            record['permission_check']=check_route(root,record,route)
            verdict=dispatch_gate(record,clock_provider())
            if verdict['state']!='due':
                record.update(status='failed' if verdict['state']=='missed_deadline' else 'pending',time_recovery=verdict)
                replace_record(root,found,record)
                return DispatchResult('failed' if record['status']=='failed' else 'requeued',verdict['reason'])
            selected=RouteAdapter(adapter,route)
            recipient=selected.resolve(record['target'])
            if recipient.version!=1 or recipient.runtime!='codex' or recipient.session_id!=record['target']['thread_id']:
                raise RuntimeTargetError('unavailable','resolved_recipient_changed')
            # Permission precedes even observation, so an adapter cannot use a
            # denied route to resume/load a recipient as a side effect.
            observation=selected.observe(recipient)
            record['runtime_observation']=observation.summary(recipient)
            if not supported(route,observation):
                reasons.append(route+':unsupported');continue
            if observation.state!='ready':
                reasons.append(route+':'+observation.reason);break
            record['permission_check']=check_route(root,record,route)
            verdict=dispatch_gate(record,clock_provider())
            if verdict['state']!='due':
                record.update(status='failed' if verdict['state']=='missed_deadline' else 'pending',time_recovery=verdict)
                replace_record(root,found,record)
                return DispatchResult('failed' if record['status']=='failed' else 'requeued',verdict['reason'])
        except PermissionDenied as exc:
            reasons.append(route+':'+exc.code);continue
        except Exception:
            reasons.append(route+':observation_unavailable');break
        delivery=dict(state='uncertain',execution='not_observed',acknowledgment='not_observed',
            submission_id=str(uuid4()),route=route)
        record.pop('policy_outcome',None)
        record['native_delivery']=delivery
        prompt=native_prompt(root,record)
        import hashlib
        delivery['prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest()
        record['attempts']+=1
        record=append_event(record,'native_submission_started','wake route '+route+' submission intent',now)
        replace_record(root,found,record)
        try:
            record['permission_check']=check_route(root,record,route)
            submitted=selected.submit(recipient,prompt)
            from .runtime_delivery import validate_native_submission
            validate_native_submission(submitted, record['target']['thread_id'],
                allow_background=route == 'background' and record['target'].get('session_mode') == 'background')
        except PermissionDenied as exc:
            submitted=RuntimeSubmission('not_sent',reason=exc.code,pre_io=True)
        except Exception:
            submitted=RuntimeSubmission('uncertain',reason='adapter_outcome_unknown')
        if submitted.state=='not_sent' and submitted.pre_io is True and record['target'].get('session_mode'):
            record.pop('native_delivery', None)
            record.update(status='cancelled' if submitted.reason == 'session_closed' else 'pending',
                          policy_outcome=dict(state='retired' if submitted.reason == 'session_closed' else 'held', reason=submitted.reason))
            replace_record(root, found, record)
            return DispatchResult('requeued', submitted.reason or 'mode_route_changed')
        if submitted.state=='not_sent' and submitted.pre_io is True:
            progress={'next':index+1,'history':[*progress['history'],dict(route=route,
                state='not_sent',pre_io=True,reason=submitted.reason,submission_id=delivery['submission_id'])]}
            record['wake_route_progress']=progress
            record.pop('native_delivery',None)
            record=append_event(record,'wake_route_not_sent','definitive pre-I/O non-submission on '+route,now)
            replace_record(root,found,record)
            continue
        if submitted.state!='accepted':
            record['last_error']='uncertain wake route submission; reconcile before fallback'
            delivery['submission_failure']=submitted.failure or {'reason':submitted.reason or 'unknown'}
            replace_record(root,found,record)
            return DispatchResult('skipped',record['last_error'])
        record['status']='submitted'
        receipt_field = 'turn_id' if submitted.evidence_kind == 'native_turn_acceptance' else 'queue_id'
        delivery.update(state='accepted', **{receipt_field: submitted.receipt_id}, accepted_at=None)
        record=append_event(record,'native_accepted','exact native queue accepted on '+route,now)
        replace_record(root,found,record)
        return DispatchResult('submitted','native queue accepted')
    record['status']='pending'
    outcome=dict(state='held',reason='wake_route_unavailable',routes=reasons)
    if record.get('policy_outcome')!=outcome:
        record=append_event(record,'wake_routes_held',','.join(reasons),now)
    record['policy_outcome']=outcome
    replace_record(root,found,record)
    return DispatchResult('requeued','wake route unavailable: '+','.join(reasons))


def runtime_route(root,record,observation):
    """Current qualified Grok adapter controls only its exact already-open TUI."""
    reasons=[]
    routes=record['wake_policy']['routes']
    start=record.get('wake_route_progress',{}).get('next',0)
    if type(start) is not int or not 0<=start<=len(routes):raise PermissionDenied('wake_route_progress_invalid')
    for route in routes[start:]:
        try:check_route(root,record,route)
        except PermissionDenied as exc:
            reasons.append(route+':'+exc.code);continue
        if route=='existing_tab' and observation.state=='ready':return route
        reasons.append(route+':unsupported')
    raise PermissionDenied('wake_route_unavailable:'+','.join(reasons))
