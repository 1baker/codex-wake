"""Owned durable agent lifecycle transitions using host-approved launch profiles."""
from __future__ import annotations

import json
import fcntl
import hashlib
import os
import shlex
import stat
from uuid import uuid4
from pathlib import Path
from types import SimpleNamespace

from .records import WakeError, parse_timestamp


from .wake_control import guard_command


@guard_command
def spawn_command(args, root):
    try:
        config = json.loads(Path(args.profiles).read_text())
        profile = config['profiles'][args.profile]
        if config['version'] != 1 or not isinstance(profile, dict):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise WakeError('an approved launch profile is required') from None
    permission_receipt=getattr(args,'_handoff_permission_receipt',None)
    if permission_receipt is not None:
        from .permission_handoff import revalidate
        revalidate(root,permission_receipt)
    if args.caller_thread_id and permission_receipt is None:
        grants = config.get('callers', {}).get(args.caller_thread_id, [])
        if not isinstance(grants, list) or args.profile not in grants:
            raise WakeError('host caller grant does not authorize this launch profile')
    required = {'cwd', 'app_server', 'codex_path', 'tmux_session', 'timeout'}
    strings = (required - {'timeout'}) | (set(profile) & {'tmux_socket', 'codex_home'})
    if (not required <= set(profile) or set(profile) - required - {'tmux_socket', 'codex_home', 'resources', 'strict_execution', 'governance_preflight'}
            or ('resources' in profile and not isinstance(profile['resources'], dict))
            or any(not isinstance(profile.get(k), str) or not profile[k]
                   or '\x00' in profile[k] for k in strings)
            or not Path(profile['cwd']).is_dir()):
        raise WakeError('approved launch profile is incomplete')
    if 'codex_home' in profile and not Path(profile['codex_home']).is_dir():
        raise WakeError('approved Codex home is unavailable')
    if (type(profile['timeout']) not in (int, float) or not 0 < profile['timeout'] <= 60):
        raise WakeError('launch profile timeout must be between zero and 60 seconds')
    if not args.intent or len(args.intent) > 200 or not args.task or len(args.task) > 32768:
        raise WakeError('bounded intent and task are required')
    if not args.name or len(args.name) > 200 or any(c in args.name for c in '\r\n\t'):
        raise WakeError('tab name must be bounded and single-line')
    expiry = parse_timestamp(args.expires_at).timestamp()
    intent = dict(operation='spawn', profile=args.profile, launch=profile, name=args.name,
                  task=args.task, expires_at=args.expires_at, source_thread_id=args.caller_thread_id)
    from .lifecycle_budget import operation_binding
    binding=operation_binding(config,args,_permission_checked=bool(permission_receipt))
    if 'strict_execution' in profile and not binding:
        raise WakeError('strict execution requires an approved objective')
    if binding:intent.update(binding)
    replacement=getattr(args,'replacement',None)
    if replacement is not None:
        if not isinstance(replacement,dict) or not replacement.get('source_thread_id') or not isinstance(replacement.get('attachment'),dict):
            raise WakeError('same-tab spawn requires an exact source attachment')
        intent['replacement']=replacement
    approved = None
    pin = None
    admission = None
    compatibility = None
    if 'governance_preflight' in profile:
        from .goal_host_preflight import inspect_host
        compatibility = inspect_host(root, profile, args.caller_thread_id)
        if not compatibility['admitted']:
            from .sessions_cli import emit
            emit(dict(state='held', reason=compatibility['reason'], compatibility_preflight=compatibility), args.as_json)
            return 5
    task_id = getattr(args, 'task_id', None)
    assignment_id = getattr(args, 'assignment_id', None)
    carried_pin = getattr(args, 'task_brief_pin', None)
    brief_revision = getattr(args, 'revision', None)
    if task_id is not None or assignment_id is not None or carried_pin is not None or brief_revision is not None:
        from .task_briefs import BriefAuthority, TaskBriefStore
        if (carried_pin is not None and (task_id is not None or assignment_id is not None or brief_revision is not None)
                or carried_pin is None and (not task_id or not assignment_id)):
            raise WakeError('task brief requires one paired task/assignment or a carried checkpoint pin')
        from .session_permissions import PermissionStore
        briefs = TaskBriefStore(PermissionStore(root).root if permission_receipt else root)
        if carried_pin is not None:
            pin = briefs.validate_pin(carried_pin)
        else:
            caller = (BriefAuthority('native:' + args.caller_thread_id, 'worker', (task_id,))
                      if args.caller_thread_id else BriefAuthority('operator:local-cli', 'operator'))
            briefs.admit(task_id, assignment_id, authority=caller, revision=brief_revision)
            pin = briefs.assignment_pin(task_id, assignment_id, authority=caller)
        brief_state = briefs.inspect(pin['task_id'])
        approved = brief_state['revisions'][pin['revision'] - 1]['content']
        admission = next(item for item in brief_state['admissions'] if item['assignment_id'] == pin['assignment_id'])
        if Path(approved['workspace']).resolve() != Path(profile['cwd']).resolve():
            raise WakeError('approved task brief workspace differs from the launch profile')
        if approved['permission_ref'] != args.profile:
            raise WakeError('approved task brief permission reference differs from the launch profile')
        if binding:
            from .lifecycle_budget import objective_identity
            if approved['allocation_ref'] != objective_identity(binding['continuation']):
                raise WakeError('approved task brief allocation differs from the existing objective')
        intent['task_brief'] = pin
    legacy_intent = dict(intent)
    if approved is not None:
        legacy_intent['task'] = ('Assignment instructions, subject to the approved task brief:\n' + args.task
            + '\n\nAPPROVED_TASK_BRIEF=' + json.dumps(dict(pin=pin, content=approved), sort_keys=True))
    journal = Path(root) / 'lifecycle'
    key = hashlib.sha256(args.intent.encode()).hexdigest()
    path = journal / (key + '.json')
    previous = json.loads(path.read_text()) if path.exists() else None
    request_fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
    legacy_fingerprint = hashlib.sha256(json.dumps(legacy_intent, sort_keys=True).encode()).hexdigest()
    if previous and previous.get('request_fingerprint') == request_fingerprint:
        # A status change or renderer upgrade cannot rewrite an admitted task.
        intent, dispatch = previous['intent'], previous.get('dispatch')
    elif previous and 'dispatch' not in previous and previous['fingerprint'] == legacy_fingerprint:
        intent, dispatch = legacy_intent, None
    else:
        from .dispatch_packet import render_assignment
        from .goal_governance import snapshot
        intent['governance_snapshot'] = snapshot(root, intent.get('source_thread_id'))
        if compatibility is not None:
            intent['preflight_snapshot'] = {key: compatibility.get(key) for key in
                ('mode', 'reason', 'requested_mode', 'message', 'authorization', 'observed_at')}
            intent['preflight_snapshot']['static_receipt'] = compatibility['static'].get('receipt_path')
            intent['governance_snapshot'] = compatibility['governance']
        intent['task'], dispatch = render_assignment(intent, root=root, brief=approved, pin=pin,
                                                    admission=admission, receipt_path=path)
    fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
    if not path.exists() and 'strict_execution' not in profile:
        endpoint=profile['app_server']
        try:
            socket=Path(endpoint[7:])
            info=socket.lstat()
            if (not endpoint.startswith('unix://') or not socket.is_absolute()
                    or not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.geteuid()):raise ValueError
        except (OSError,ValueError):
            raise WakeError('launch profile requires an existing owned Unix socket') from None
    journal.mkdir(mode=0o700, parents=True, exist_ok=True)
    # One external owner, including observation and uncertain-effect reconciliation.
    with (journal / (key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            receipt = json.loads(path.read_text())
            if receipt['fingerprint'] != fingerprint:
                # Historical admission stays byte-for-byte stable across upgrades.
                legacy_fingerprint = hashlib.sha256(json.dumps(legacy_intent, sort_keys=True).encode()).hexdigest()
                if 'dispatch' in receipt or receipt['fingerprint'] != legacy_fingerprint:
                    raise WakeError('intent key already binds a different lifecycle assignment')
        else:
            receipt = dict(version=1, intent_key=args.intent, fingerprint=fingerprint,
                           intent=intent, state='prepared', thread_id=None, dispatch=dispatch,
                           request_fingerprint=request_fingerprint)
            if permission_receipt:
                receipt['permission_context']=permission_receipt['permission_context']
            if not binding:receipt['budget_mode']='explicit_expiry_only_legacy_profile'
            save(path, receipt)
        if compatibility is not None:
            receipt['compatibility_preflight'] = compatibility
        if receipt['state'] == 'starting' and receipt['thread_id'] is None:
            receipt.update(state='uncertain', uncertain_effect='thread/start')
            save(path, receipt)
        if receipt['state'] == 'prepared':
            if (binding and not intent.get('budget_inherited')
                    and (compatibility or {}).get('mode') != 'manual'):
                from .lifecycle_supervision import supervision_ready
                if not supervision_ready(root,profile['timeout']):
                    receipt['reason']='resident_objective_supervisor_required'
                    save(path,receipt)
                    from .sessions_cli import emit
                    emit(receipt,args.as_json)
                    return 5
                receipt.pop('reason',None)
            if binding:
                from .strict_runtime import preflight_execution
                preflight_execution(root,receipt)
                from .lifecycle_budget import admit_spawn
                from .native_protocol import native_request
                from .app_server import resolve_codex_cmd
                def budget_request(method,params):
                    return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                        method,params,profile['timeout'])
                if not admit_spawn(root,receipt,budget_request):
                    save(path,receipt)
                    from .sessions_cli import emit
                    emit(receipt,args.as_json)
                    return 5
            if 'strict_execution' in profile:
                save(path,receipt)
                from .strict_runtime import ensure_execution
                ensure_execution(root,receipt)
                save(path,receipt)
            from .native_clock import snapshot
            observation = snapshot()
            bounds = observation.get('utc')
            if not bounds or bounds['upper'] >= expiry:
                receipt.update(state='expired' if bounds else 'blocked',
                               reason='expiry_reached' if bounds else 'admissible_time_unavailable')
                save(path, receipt)
            else:
                from .app_server import resolve_codex_cmd
                from .session_lifecycle import tmux_command
                from .native_protocol import native_request
                runtime = SimpleNamespace(**(dict(tmux_socket=None) | profile),
                                          codex=resolve_codex_cmd(profile['codex_path'], required=True))
                tmux_command(runtime, 'has-session', '-t', runtime.tmux_session)
                if (permission_receipt or compatibility is not None) and not before_effect(path,receipt):
                    from .sessions_cli import emit
                    emit(receipt,args.as_json)
                    return 5
                receipt.update(state='starting', uncertain_effect='thread/start')
                save(path, receipt)
                try:
                    response = native_request(runtime.app_server, runtime.codex, 'thread/start',
                        {'cwd': str(Path(runtime.cwd).resolve()), 'ephemeral': False}, runtime.timeout)
                    receipt.update(thread_id=response['thread']['id'], state='awaiting_preflight')
                    receipt.pop('uncertain_effect', None)
                except Exception as exc:
                    # The peer may have created the thread before its connection failed.
                    receipt.update(state='uncertain', uncertain_effect='thread/start',
                        native_start_error=type(exc).__name__+': '+str(exc)[:240])
                save(path, receipt)
        if receipt['thread_id'] is not None and receipt['state']!='completed':
            advance_spawn(path, receipt, profile)
        from .sessions_cli import emit
        emit(receipt, args.as_json)
        return 0 if receipt['state'] == 'completed' else 5


def advance_spawn(path, receipt, profile):
    from .app_server import resolve_codex_cmd
    from .native_protocol import native_request
    from .session_lifecycle import tmux_command
    from .sessions import observe, revalidate_attachment, in_session
    from .native_delivery import native_evidence
    runtime = SimpleNamespace(**(dict(tmux_socket=None) | profile),
                              codex=resolve_codex_cmd(profile['codex_path'], required=True))
    target = dict(endpoint=runtime.app_server, codex_cmd=runtime.codex,
                  thread_id=receipt['thread_id'])
    def request(method, params):
        return native_request(runtime.app_server, runtime.codex, method, params, runtime.timeout)
    try:
        if receipt.get('uncertain_effect') in ('tmux/new-window','tmux/respawn-pane'):
            snapshot = observe(endpoint=runtime.app_server, socket_path=runtime.tmux_socket, timeout=runtime.timeout)
            rows = [r for r in snapshot['sessions'] if r['thread_id'] == receipt['thread_id']
                    and r['name'] == receipt['thread_name']]
            panes = [p for r in rows for p in r['attachments']
                     if in_session(p, runtime.tmux_session)]
            if not snapshot['complete'] or len(rows) != 1 or len(panes) != 1:
                receipt.update(state='uncertain', reason='no_unique_existing_owned_tab')
                save(path, receipt)
                return
            pane = panes[0]
            replacement=receipt['intent'].get('replacement')
            if replacement and (pane['pane_id']!=replacement['attachment']['pane_id']
                    or pane['window_id']!=replacement['attachment']['window_id']
                    or pane['client_pid']==replacement['attachment']['client_pid']):
                receipt.update(state='uncertain',reason='same_tab_generation_not_observed');save(path,receipt);return
            if not revalidate_attachment(pane):
                receipt.update(state='uncertain', reason='tab_generation_unavailable')
                save(path, receipt)
                return
            receipt.update(state='awaiting_preflight', pane_id=pane['pane_id'],
                           window_id=pane['window_id'])
            receipt.pop('uncertain_effect', None)
            save(path, receipt)
        if receipt.get('uncertain_effect') in ('thread/queue/add', 'thread/queue/start'):
            evidence, reason = native_evidence(target, receipt['intent']['task'])
            if not evidence or evidence.get('client_message_id') != receipt['submission_id']:
                receipt.update(state='uncertain', reason=reason or 'submission_identity_mismatch')
                save(path, receipt)
                return
            if evidence['source'] == 'native_queue':
                if receipt['uncertain_effect'] == 'thread/queue/start':
                    receipt.update(state='uncertain', reason='queue_start_not_yet_observed')
                    save(path, receipt)
                    return
                receipt.update(state='ready', queue_id=evidence['queue_id'])
            else:
                receipt['state'] = 'awaiting_preflight'
            receipt.pop('uncertain_effect', None)
            save(path, receipt)
        if receipt['state'] == 'awaiting_preflight' and not receipt.get('pane_id'):
            if not before_effect(path, receipt):
                return
            # Set an exact correlation name before the non-idempotent tab effect.
            name = receipt['intent']['name'] + '-' + receipt['fingerprint'][:12]
            request('thread/name/set', {'threadId': receipt['thread_id'], 'name': name})
            replacement=receipt['intent'].get('replacement')
            if replacement:
                from .agent_handoff import source_guard
                guard=dict(thread_id=replacement['source_thread_id'],reason='successor_preflight_not_verified')
                source_guard(guard,profile,path.parent.parent)
                source_goal=request('thread/goal/get',{'threadId':replacement['source_thread_id']})['goal']
                if (guard.get('source_attachment')!=replacement['attachment'] or not source_goal
                        or source_goal['status']!='paused'):
                    receipt.update(state='blocked',reason='same_tab_source_changed');save(path,receipt);return
            receipt.update(state='starting', uncertain_effect='tmux/respawn-pane' if replacement else 'tmux/new-window', thread_name=name)
            save(path, receipt)
            removed = ['CODEX_THREAD_ID', 'TMUX_PANE', 'CODEX_WAKE_A2A_CAPABILITY',
                       'CODEX_WAKE_A2A_BUS_ROOT', 'CODEX_WAKE_SENDER_RECEIPT_AUTHORITY']
            home = ['CODEX_HOME=' + profile['codex_home']] if 'codex_home' in profile else []
            command = shlex.join(['env', *[part for name in removed for part in ('-u', name)], *home,
                                  runtime.codex, 'resume', '--no-alt-screen', '-C',
                                  str(Path(runtime.cwd).resolve()), receipt['thread_id'],
                                  '--remote', runtime.app_server])
            if replacement:
                old=replacement['attachment']
                tmux_command(runtime,'respawn-pane','-k','-t',old['pane_id'],'-c',runtime.cwd,command)
                window,pane=old['window_id'],old['pane_id']
            else:
                created = tmux_command(runtime, 'new-window', '-d', '-P', '-F',
                                       '#{window_id}\t#{pane_id}', '-t', runtime.tmux_session + ':',
                                       '-n', receipt['intent']['name'], '-c', runtime.cwd, command)
                window, pane = created.split('\t')
            receipt.update(window_id=window, pane_id=pane, state='awaiting_preflight')
            receipt.pop('uncertain_effect', None)
            save(path, receipt)
        if receipt['state'] == 'starting':
            receipt.update(state='uncertain')
            save(path, receipt)
            return
        if ((receipt['state'] == 'awaiting_preflight' and not receipt.get('submission_id'))
                or (receipt['state'] == 'ready' and not receipt.get('queue_id'))):
            snapshot = observe(endpoint=runtime.app_server, socket_path=runtime.tmux_socket, timeout=runtime.timeout)
            rows = [r for r in snapshot['sessions'] if r['thread_id'] == receipt['thread_id']]
            attachments = [p for r in rows for p in r['attachments']]
            if (not snapshot['complete'] or len(rows) != 1 or len(attachments) != 1
                    or attachments[0]['pane_id'] != receipt['pane_id']
                    or rows[0]['cwd'] != str(Path(runtime.cwd).resolve())
                    or rows[0]['runtime_state'] != 'idle'
                    or rows[0]['can_accept_direct_input'] is not True
                    or rows[0]['active_flags'] or not revalidate_attachment(attachments[0])):
                receipt['reason'] = 'exact_idle_owned_client_not_ready'
                save(path, receipt)
                return
            panes = tmux_command(runtime, 'list-panes', '-t', receipt['window_id'], '-F', '#{pane_id}')
            if panes.splitlines() != [receipt['pane_id']]:
                receipt['reason'] = 'split_or_changed_tab'
                save(path, receipt)
                return
            # Native idle does not expose the local composer's draft. Require
            # the observed Codex empty-composer rendering at the actual cursor.
            # Unknown layouts fail closed; never clear or submit local input.
            frame = tmux_command(runtime, 'capture-pane', '-e', '-p', '-t', receipt['pane_id'],
                                 preserve_output=True)
            cursor = tmux_command(runtime, 'display-message', '-p', '-t', receipt['pane_id'],
                                  '#{cursor_x},#{cursor_y}')
            lines = frame.splitlines()
            try:
                x, y = map(int, cursor.strip().split(','))
                from .refresh_goal import empty_composer_line
                empty = x == 2 and 0 <= y < len(lines) and empty_composer_line(lines[y])
            except ValueError:
                empty = False
            if not empty:
                receipt['reason'] = 'local_composer_not_proven_empty'
                save(path, receipt)
                return
            receipt.update(state='ready', attachment=attachments[0],
                           submission_id=receipt.get('submission_id') or str(uuid4()))
            save(path, receipt)
        if receipt['state'] == 'ready':
            if not before_effect(path, receipt):
                return
            if not receipt.get('queue_id'):
                receipt.update(state='starting', uncertain_effect='thread/queue/add')
                save(path, receipt)
                response = request('thread/queue/add', dict(threadId=receipt['thread_id'],
                    clientUserMessageId=receipt['submission_id'],
                    input=[dict(type='text', text=receipt['intent']['task'])]))
                queued = response['queuedSubmission']
                items = queued['input']
                if (queued['clientUserMessageId'] != receipt['submission_id']
                        or len(items) != 1 or items[0].get('type') != 'text'
                        or items[0].get('text') != receipt['intent']['task']
                        or items[0].get('text_elements', []) != []):
                    raise WakeError('native task receipt identity mismatch')
                receipt['queue_id'] = queued['id']
            save(path, receipt)
            evidence, reason = native_evidence(target, receipt['intent']['task'])
            if not evidence or evidence.get('client_message_id') != receipt['submission_id']:
                receipt.update(state='uncertain', uncertain_effect='thread/queue/add',
                               reason=reason or 'submission_identity_mismatch')
                save(path, receipt)
                return
            if evidence['source'] == 'native_queue':
                if not before_effect(path, receipt):
                    return
                receipt.update(state='starting', uncertain_effect='thread/queue/start')
                save(path, receipt)
                request('thread/queue/start', dict(threadId=receipt['thread_id'],
                                                queuedSubmissionId=receipt['queue_id']))
            receipt.update(state='awaiting_preflight')
            receipt.pop('uncertain_effect', None)
            save(path, receipt)
        if receipt.get('submission_id'):
            evidence, reason = native_evidence(target, receipt['intent']['task'])
            if evidence and evidence.get('client_message_id') == receipt['submission_id']:
                receipt['execution'] = evidence
                if evidence.get('execution') == 'turn_completed':
                    receipt['state'] = 'completed'
                    receipt.pop('reason', None)
                elif evidence.get('execution') in ('turn_failed', 'turn_interrupted'):
                    receipt.update(state='blocked', reason='initial_task_' + evidence['execution'])
                else:
                    receipt['state'] = 'awaiting_preflight'
                if receipt.get('budget_actor'):
                    from .lifecycle_budget import observe_spawn
                    native=request('thread/read',{'threadId':receipt['thread_id'],'includeTurns':True})['thread']
                    view=observe_spawn(path.parent.parent,receipt,native,profile,
                        settled=evidence.get('execution') in ('turn_completed','turn_failed','turn_interrupted'))
                    actor=view['actors'][receipt['budget_actor']]
                    if not receipt['intent'].get('budget_inherited') and actor['used']>actor['reservation']:
                        receipt.update(state='blocked',reason='session_token_allowance_exceeded')
                    if receipt['state']=='completed' and not view['accounting_known']:
                        receipt.update(state='awaiting_preflight',reason='final_usage_unknown')
                save(path, receipt)
    except Exception as exc:
        receipt.update(state='uncertain' if receipt.get('uncertain_effect') else 'blocked',
                       reason=type(exc).__name__)
        save(path, receipt)


def before_effect(path, receipt):
    # Refresh/handoff guards share this seam without a spawn launch profile.
    profile = receipt['intent'].get('launch', {})
    if 'governance_preflight' in profile:
        from .goal_host_preflight import inspect_host
        preflight = inspect_host(path.parent.parent, profile, receipt['intent'].get('source_thread_id'))
        receipt['compatibility_preflight'] = preflight
        if not preflight['admitted']:
            receipt['reason'] = preflight['reason']
            save(path, receipt)
            return False
    if receipt.get('permission_context'):
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
    if (receipt['intent']['operation']=='spawn' and receipt['intent'].get('configuration')
            and not receipt['intent'].get('budget_inherited')
            and receipt.get('compatibility_preflight', {}).get('mode') != 'manual'):
        from .lifecycle_supervision import supervision_ready
        if not supervision_ready(path.parent.parent,receipt['intent']['launch']['timeout']):
            receipt['reason']='resident_objective_supervisor_required'
            save(path,receipt)
            return False
    if receipt['intent']['operation']=='spawn' and receipt.get('budget_actor'):
        from .lifecycle_budget import admit_spawn
        from .native_protocol import native_request
        from .app_server import resolve_codex_cmd
        profile=receipt['intent']['launch']
        def request(method,params):
            return native_request(profile['app_server'],resolve_codex_cmd(profile['codex_path'],required=True),
                method,params,profile['timeout'])
        if not admit_spawn(path.parent.parent,receipt,request):
            save(path,receipt)
            return False
    from .native_clock import snapshot
    observation = snapshot()
    bounds = observation.get('utc')
    deadline=min(parse_timestamp(receipt['intent']['expires_at']).timestamp(),receipt.get('assignment_deadline',float('inf')))
    if not bounds or bounds['upper'] >= deadline:
        receipt.update(state='expired' if bounds else 'blocked',
                       reason='expiry_reached' if bounds else 'admissible_time_unavailable')
        save(path, receipt)
        return False
    return True


def save(path, receipt):
    event = dict(state=receipt['state'], effect=receipt.get('uncertain_effect'),
                 reason=receipt.get('reason'))
    if receipt.get('rollback'):
        event['rollback_state'] = receipt['rollback']['state']
    history = receipt.setdefault('history', [])
    if not history or history[-1] != event:
        history.append(event)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(receipt, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
