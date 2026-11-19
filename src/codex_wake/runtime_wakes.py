"""Schema7 durable runtime intents; clock/lifecycle semantics shared with schema6."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from . import measurements
from .grok_runtime import GrokRuntimeAdapter
from .grok_terminal import GrokTerminalHost, digest
from .session_permissions import PermissionDenied
from .native_intents import eligibility, dispatch_gate, valid_counter, valid_utc, valid_scheduling_record
from .records import (WakeError, WakeLifecycleLock, all_records, find_record,
                      parse_duration, replace_record, write_record)


def event(record, kind, message, now=None):
    return dict(record, updated_at=None, events=list(record['events'])+[
        dict(at=None,time_status='not_observed',type=kind,message=message)])


def valid_target(target):
    return (type(target.get('version')) is int and target.get('version') == 1 and target.get('policy') == 'wait' and target.get('transport') == 'runtime'
            and target.get('runtime') == 'grok' and target.get('method') in ('terminal_observation', 'native_preferred')
            and isinstance(target.get('session_id'),str) and 0 < len(target['session_id']) <= 200
            and re.fullmatch(r'grok_[0-9a-f]{32}', target.get('binding_id','')) is not None
            and re.fullmatch(r'[0-9a-f]{64}', target.get('binding_sha256','')) is not None)


def valid_record(record):
    return valid_scheduling_record(record, 7, valid_target)


def binding_digest(root, binding_id):
    if not re.fullmatch(r'grok_[0-9a-f]{32}',binding_id):
        raise WakeError('invalid_binding_id')
    return digest((Path(root)/'runtime-bindings'/(binding_id+'.json')).read_bytes())


from .wake_policy import guard_registration


@guard_registration
def retain(args, root):
    from .cli import normalize_prompt
    from .native_clock import snapshot
    from .network_wakes import precise_deadline
    from .runtime_policies import require_wait_policy
    require_wait_policy(getattr(args, "busy_policy", "wait"))
    root = Path(root).resolve()
    approved_digest = binding_digest(root,args.binding_id)
    binding = GrokTerminalHost(root).load_binding(args.binding_id,approved_digest)
    schedule = ({'kind':'after','delay_seconds':parse_duration(args.trigger).total_seconds()}
                if args.grok_command == 'after' else
                {'kind':'at','due_at':precise_deadline(args.trigger).isoformat()} if args.grok_command == 'at' else
                {'kind':'file','path':str(Path(args.trigger).resolve())})
    target = dict(transport='runtime', version=1, runtime='grok', session_id=binding['session_id'],
                  method='native_preferred' if binding.get('allow_terminal_fallback') is True else 'terminal_observation', binding_id=args.binding_id,
                  binding_sha256=approved_digest, policy='wait')
    ttl = parse_duration(args.ttl).total_seconds()
    prompt = normalize_prompt(args.prompt)
    if (not 0 < ttl or schedule.get('delay_seconds',1) <= 0
            or len(prompt.encode()) > 32768 or any((ord(c)<32 or 127<=ord(c)<=159) and c not in '\n\t' for c in prompt)):
        raise WakeError('invalid_runtime_wake_request')
    if not args.idempotency_key.strip() or len(args.idempotency_key)>200:
        raise WakeError('stable_idempotency_key_required')
    intent = dict(canonical_root=str(root), schedule=schedule, ttl_seconds=ttl,
                  tolerance_seconds=1.0, stop_at=None, idempotency_key=args.idempotency_key)
    from .wake_policy import request_policy, decorate, register_owner
    policy = request_policy(root, args, "grok:" + binding["session_id"])
    canonical = dict(target=target, prompt=prompt, **intent)
    if policy is not None:
        canonical["wake_policy"] = policy
    intent['fingerprint'] = digest(json.dumps(canonical, sort_keys=True).encode())
    with WakeLifecycleLock(root, 'runtime-arm-'+args.idempotency_key):
        for item in all_records(root, include_archive=True):
            old = item.record.get('scheduling_intent',{})
            if old.get('idempotency_key') == args.idempotency_key:
                if old.get('fingerprint') != intent['fingerprint'] or not valid_record(item.record):
                    raise WakeError('idempotency_conflict')
                return item.record, item.path, True
        clock=snapshot()
        intent.update(counter_anchor=clock.get('counter') if valid_counter(clock.get('counter')) else None,
                      utc_anchor=clock.get('utc') if valid_utc(clock.get('utc')) else None,
                      origin_state='at_request' if valid_counter(clock.get('counter')) or valid_utc(clock.get('utc')) else 'awaiting_qualified_clock')
        record=dict(schema_version=7,id='wake_intent_'+uuid4().hex,created_at='',updated_at='',
                    cwd=str(Path.cwd().resolve()),target=target,prompt=prompt,
                    predicate={'type':'not_before','due_at':None} if schedule['kind']!='file' else {'type':'file_exists','path':schedule['path']},
                    scheduling_intent=intent,time_recovery={},status='pending',attempts=0,max_attempts=3,
                    ack_timeout_seconds=30,next_attempt_at=None,events=[])
        decorate(record, policy, 7)
        register_owner(root, policy)
        from .wake_policy import apply_owner_state
        apply_owner_state(root, record)
        record['time_recovery']=eligibility(record,clock)
        record=event(record,'runtime_intent_retained','Original Grok scheduling intent retained',None)
        path=write_record(root,record)
        return record,path,False


def runtime_prompt(record):
    return 'WAKE_RUNTIME_SUBMISSION_ID='+record['runtime_delivery']['submission_id']+'\n'+record['prompt']


def dispatch(root, found, *, time_provider=None):
    from .injector import DispatchResult
    from .native_clock import snapshot
    from .service import user_state_dir
    provider = (lambda:dict(utc=asdict(time_provider()),counter=None)) if time_provider else snapshot
    with WakeLifecycleLock(root,found.record['id']):
        current=find_record(root,found.record['id'])
        record=dict(current.record)
        if (not valid_record(record) or record['status']!='firing' or record!=found.record
                or record['scheduling_intent']['canonical_root']!=str(Path(root).resolve())):
            return DispatchResult('skipped','runtime intent changed')
        from .permission_migration import legacy_wake_held
        if legacy_wake_held(root,record):return DispatchResult('skipped','legacy_permission_adoption_required: retain original intent; resolve operator adoption')
        adapter=GrokRuntimeAdapter(GrokTerminalHost(root), preferred_method=record['target']['method'])
        delivery=record.get('runtime_delivery',{})
        uncertain=delivery.get('state')=='uncertain'
        try:
            recipient=adapter.resolve(record['target'])
            if recipient.version!=1 or recipient.runtime!='grok' or recipient.session_id!=record['target']['session_id']:
                raise WakeError('recipient_changed')
            lock_id='grok-pane-'+str(recipient.binding.get('socket'))+':'+str(recipient.binding.get('pane'))
            with WakeLifecycleLock(user_state_dir()/'runtime-recipient-locks',lock_id):
                if uncertain:
                    prompt=runtime_prompt(record)
                    if digest(prompt.encode())!=delivery['prompt_sha256']:
                        raise WakeError('original_payload_changed')
                    observed=adapter.reconcile(recipient,prompt)
                    if not observed.evidence or observed.evidence.get('source')!='terminal_observation':
                        return DispatchResult('skipped','runtime submission unresolved; no resend')
                    delivery=dict(delivery,state='accepted',evidence=observed.evidence,
                                  evidence_kind='terminal_observation',reconciled=True,reason='terminal_acceptance_observed')
                else:
                    verdict=dispatch_gate(record,provider())
                    if verdict['state']!='due':
                        record.update(status='failed' if verdict['state']=='missed_deadline' else 'pending',time_recovery=verdict)
                        replace_record(root,current,record)
                        return DispatchResult('failed' if record['status']=='failed' else 'requeued',verdict['reason'])
                    observation=adapter.observe(recipient)
                    record['runtime_observation']=observation.summary(recipient)
                    from .permission_wake import common_record,runtime_route
                    chosen_route=runtime_route(root,record,observation) if common_record(record) else None
                    from .wake_policy import startup_reason
                    policy_reason = startup_reason(record, observation)
                    if policy_reason:
                        record['policy_outcome'] = dict(state='held', reason=policy_reason)
                    if observation.state!='ready' or policy_reason:
                        record['status']='pending'
                        replace_record(root,current,record)
                        return DispatchResult('requeued','exact Grok recipient not ready')
                    # Anchor before revalidation and durable intent writes; never renew their latency.
                    timer=measurements.deadline(verdict['dispatch_window_seconds'])
                    verdict=dispatch_gate(record,provider())
                    if verdict['state']!='due':
                        record.update(status='failed' if verdict['state']=='missed_deadline' else 'pending',time_recovery=verdict)
                        replace_record(root,current,record)
                        return DispatchResult('failed' if record['status']=='failed' else 'requeued',verdict['reason'])
                    timer.restrict(verdict['dispatch_window_seconds'])
                    adapter.host.deadline=timer
                    if chosen_route:
                        from .permission_wake import check_route
                        record['permission_check']=check_route(root,record,chosen_route)
                    delivery=dict(state='uncertain',submission_id=str(uuid4()),method='terminal_observation',
                                  execution='not_observed',acknowledgment='not_observed',reason='submission_outcome_not_observed')
                    if chosen_route:delivery['route']=chosen_route
                    record.pop('policy_outcome',None)
                    record['runtime_delivery']=delivery
                    delivery['prompt_sha256']=digest(runtime_prompt(record).encode())
                    record['attempts']+=1
                    record=event(record,'runtime_submission_started','Durable intent before terminal input',None)
                    replace_record(root,current,record)
                    try:
                        if chosen_route:check_route(root,record,chosen_route)
                        submitted=GrokRuntimeAdapter(adapter.host,deadline=timer, preferred_method=record['target']['method']).submit(recipient,runtime_prompt(record))
                    except Exception:
                        return DispatchResult('skipped','runtime submission uncertain; no resend')
                    if chosen_route and submitted.state=='not_sent' and submitted.pre_io is True:
                        index=record['wake_policy']['routes'].index(chosen_route)
                        previous=record.get('wake_route_progress',{'history':[]})
                        record['wake_route_progress']=dict(next=index+1,history=[*previous['history'],dict(
                            route=chosen_route,state='not_sent',pre_io=True,reason=submitted.reason,submission_id=delivery['submission_id'])])
                        record.pop('runtime_delivery',None)
                        record['status']='pending'
                        replace_record(root,current,record)
                        return DispatchResult('requeued','definitive pre-I/O runtime non-submission')
                    if submitted.state!='accepted' or submitted.evidence_kind!='terminal_observation':
                        return DispatchResult('skipped','runtime submission uncertain; no resend')
                    delivery=dict(delivery,state='accepted',evidence_kind='terminal_observation',
                                  evidence=submitted.evidence,reason='terminal_acceptance_observed')
        except PermissionDenied as exc:
            record['policy_outcome']=dict(state='held',reason=exc.code)
            if not uncertain and record.get('runtime_delivery',{}).get('state')!='uncertain':
                record['status']='pending'
            replace_record(root,current,record)
            return DispatchResult('skipped' if record.get('runtime_delivery',{}).get('state')=='uncertain' else 'requeued',exc.code)
        except Exception:
            if uncertain or record.get('runtime_delivery',{}).get('state')=='uncertain':
                return DispatchResult('skipped','runtime evidence unavailable; no resend')
            record.update(status='pending',runtime_observation=dict(version=1,runtime='grok',
                          state='unavailable',reason='binding_unavailable',capabilities={}))
            replace_record(root,current,record)
            return DispatchResult('requeued','runtime binding unavailable')
        record.update(status='submitted',runtime_delivery=delivery)
        record=event(record,'runtime_observed','Terminal acceptance observed; execution and acknowledgment not established',None)
        replace_record(root,current,record)
        return DispatchResult('submitted','terminal acceptance observed')


def add_grok_parser(subparsers):
    group=subparsers.add_parser('grok',help='structured Grok control and explicit legacy terminal wakes')
    commands=group.add_subparsers(dest='grok_command',required=True)
    from .grok_provider_auth import register_parser as register_auth
    register_auth(commands)
    from .grok_model_catalog import register_parser as register_models
    register_models(commands)
    from .grok_commands import register_verbs
    register_verbs(commands)
    from .grok_stdio_host import register_host
    register_host(commands)
    bind=commands.add_parser('bind',help='operator-only approval of an exact already-open minimal TUI')
    for key in ('socket','pane','session-id','executable'):
        bind.add_argument('--'+key,required=True)
    bind.add_argument('--pid',type=int,required=True)
    bind.add_argument('--allow-terminal-input',action='store_true')
    bind.add_argument('--allow-terminal-fallback',action='store_true',
                      help='host approval for native-unavailable pre-I/O terminal fallback')
    bind.add_argument('--json',action='store_true')
    show=commands.add_parser('show')
    show.add_argument('wake_id')
    show.add_argument('--json',action='store_true')
    sessions=commands.add_parser('sessions')
    sessions.add_argument('--json',action='store_true')
    for verb in ('after','at','file'):
        cmd=commands.add_parser(verb)
        from .wake_policy import add_options
        add_options(cmd)
        cmd.add_argument('--busy-policy', choices=('wait','queue','interrupt'), default='wait')
        cmd.add_argument('--ttl',default='24h')
        cmd.add_argument('--idempotency-key',required=True)
        cmd.add_argument('--require-monitor',action='store_true')
        cmd.add_argument('--json',action='store_true')
        cmd.add_argument('binding_id')
        cmd.add_argument('trigger')
        cmd.add_argument('prompt',nargs=argparse.REMAINDER)


def command(args,root):
    if args.grok_command == 'models':
        from .grok_model_catalog import command as models_command
        return models_command(args, root)
    if args.grok_command == 'auth':
        from .grok_provider_auth import command as auth_command
        return auth_command(args,root)
    if args.grok_command == 'stdio-host':
        from .grok_stdio_host import command as host_command
        return host_command(args,root)
    if args.grok_command in ('capabilities','create','load','prompt','wait','cancel','health','checkpoint','fork'):
        from .grok_commands import command as structured_command
        return structured_command(args,root)
    host=GrokTerminalHost(root)
    if args.grok_command=='bind':
        value=host.enroll(socket=args.socket,pane=args.pane,pid=args.pid,session_id=args.session_id,
                          executable=args.executable,allow_terminal_input=args.allow_terminal_input,
                          allow_terminal_fallback=args.allow_terminal_fallback)
    elif args.grok_command=='show':
        record=find_record(root,args.wake_id).record
        if not valid_record(record):
            raise WakeError('not_a_recognized_runtime_intent')
        value={key:record.get(key) for key in ('id','status','target','attempts','time_recovery','runtime_observation','runtime_delivery')}
    elif args.grok_command=='sessions':
        values=[]
        for path in sorted((Path(root)/'runtime-bindings').glob('grok_*.json'))[:100]:
            try:
                binding=host.load_binding(path.stem)
                target=dict(transport='runtime',version=1,runtime='grok',method='native_preferred' if binding.get('allow_terminal_fallback') is True else 'terminal_observation',
                            session_id=binding['session_id'],binding_id=path.stem,binding_sha256=digest(path.read_bytes()))
                adapter=GrokRuntimeAdapter(host)
                recipient=adapter.resolve(target)
                values.append(dict(binding_id=path.stem,method=target['method'],**adapter.observe(recipient).summary(recipient)))
            except Exception:
                values.append(dict(binding_id=path.stem,state='unavailable'))
        value=dict(runtime='grok',sessions=values,scope='host_approved_bindings_only',complete=len(values)<100)
    else:
        record,path,deduplicated=retain(args,root)
        value=dict(id=record['id'],path=str(path),status=record['status'],deduplicated=deduplicated,
                   target=record['target'],time_recovery=record['time_recovery'],requires_worker_schema=record['schema_version'], wake_policy=record.get('wake_policy'))
        if args.require_monitor:
            from .signal_records import probe_managed_reader_capability
            worker=probe_managed_reader_capability(Path(root))
            if worker is None or record['schema_version'] not in worker.schema_versions:
                print(json.dumps(dict(value,state='held',reason='compatible_monitor_unavailable'),sort_keys=True))
                return 3
    print(json.dumps(value,sort_keys=True))
    return 0
