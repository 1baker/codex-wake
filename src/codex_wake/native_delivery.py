"""Native queue delivery for durable wakes; acceptance is not execution proof."""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID, uuid4

from .native_protocol import native_request
from .codex_runtime import CodexRuntimeAdapter, read_codex_thread, submission_failure
from .runtime_delivery import RuntimeAdapter, RuntimeReconciliation, RuntimeSubmission, RuntimeTargetError
from .records import WakeError, append_event, format_utc, parse_duration, parse_timestamp, replace_record, utc_now


def add_native_parser(subparsers):
    native = subparsers.add_parser('native', help='schedule an exact-thread native Codex wake')
    commands = native.add_subparsers(dest='native_command', required=True)
    reconcile = commands.add_parser('reconcile', help='inspect native evidence without resubmitting')
    reconcile.add_argument('wake_id')
    reconcile.add_argument('--read-codex-path', help='qualified read-only replacement for a removed historical executable; accepted completion only')
    migrate = commands.add_parser('migrate', help='inspect/promote earlier candidate native records without delivery')
    migrate.add_argument('wake_id')
    migrate.add_argument('--apply', action='store_true', help='save original and promote schema1 native record to schema4')
    for verb in ('after', 'at', 'file'):
        command = commands.add_parser(verb)
        from .wake_policy import add_options
        add_options(command)
        from .wake_session_modes import MODES
        command.add_argument('--session-mode', choices=MODES, help='explicit session lifecycle mode; legacy CLI calls retain their policy contract')
        command.add_argument('--codex-path', default='codex')
        command.add_argument('--endpoint', default='unix://')
        command.add_argument('--ttl', default='24h', help='expiry after time due, or after file registration')
        command.add_argument('--idempotency-key', help='stable original scheduling intent; reuse only for that request')
        command.add_argument('--time-tolerance', help='maximum admitted clock interval, at most 5m')
        command.add_argument('--stop-at', help='absolute UTC stop; requires qualified UTC before any dispatch')
        command.add_argument('--json', dest='as_json', action='store_true', help='structured native intent receipt')
        command.add_argument('--busy-policy',choices=['wait','queue','interrupt'],default='wait')
        command.add_argument('--require-monitor', action='store_true', help='require an active worker compatible with this record')
        command.add_argument('--resume-missing', action='store_true',
                             help='explicitly resume the same saved thread when it is not loaded')
        command.add_argument('thread_id')
        command.add_argument('trigger')
        command.add_argument('prompt', nargs=argparse.REMAINDER)


from .wake_policy import guard_registration


@guard_registration
def create_native(args, root):
    from .runtime_policies import require_wait_policy
    require_wait_policy(getattr(args,"busy_policy","wait"))
    from .app_server import resolve_codex_cmd
    from .cli import create_record
    try:
        args.thread_id = str(UUID(args.thread_id))
    except ValueError:
        raise WakeError('native target requires an exact thread UUID') from None
    if not args.endpoint.startswith('unix://'):
        raise WakeError('native target requires a local unix:// endpoint')
    from .network_wakes import read_time, creation_time, precise_deadline
    # Validate the request before accepting an intent, even during acquisition failure.
    from .cli import normalize_prompt
    normalize_prompt(args.prompt)
    resolve_codex_cmd(args.codex_path, required=True)
    parse_duration(args.ttl)
    if args.native_command == 'after':
        parse_duration(args.trigger)
    elif args.native_command == 'at':
        precise_deadline(args.trigger)
    if getattr(args, 'require_monitor', False):
        from .monitor import monitor_readiness, require_monitor_ready
        require_monitor_ready(monitor_readiness(wake_root=root, repo_root=Path.cwd()))
    from .native_intents import existing_receipt, retain
    existing = existing_receipt(args, root)
    if existing is not None:
        return existing
    from .native_clock import configuration
    if getattr(args, 'wake_policy_enabled', False) or configuration() or any(getattr(args, name, None) for name in ('idempotency_key', 'time_tolerance', 'stop_at', 'as_json')):
        return retain(args, root)
    try:
        observation = read_time()
    except WakeError:
        from .native_intents import retain
        return retain(args, root)
    now = creation_time(observation)
    if args.native_command == 'file':
        predicate = {'type': 'file_exists', 'path': str(Path(args.trigger).resolve())}
        due = now
    else:
        due = now + parse_duration(args.trigger) if args.native_command == 'after' else precise_deadline(args.trigger)
        predicate = {'type': 'not_before', 'due_at': due.isoformat().replace('+00:00', 'Z')}
    ttl = parse_duration(args.ttl)
    if ttl.total_seconds() <= 0:
        raise WakeError('native expiry must be positive')
    target = {'transport': 'native', 'thread_id': args.thread_id,
              'codex_cmd': resolve_codex_cmd(args.codex_path, required=True),
              'endpoint': args.endpoint, 'expires_at': (due + ttl).isoformat().replace('+00:00', 'Z'),
              'resume_policy': 'same_thread' if args.resume_missing else 'hold'}
    return create_record(args.prompt, predicate, root, now, args, target=target,
                         time_observation=observation)


def read_native_thread(target):
    """Compatibility entrypoint; the adapter owns Codex protocol access."""
    return read_codex_thread(target)


def expire_native(root, found, now):
    target = found.record.get('target', {})
    if target.get('transport') != 'native' or now < parse_timestamp(target['expires_at']):
        return False
    from .records import WakeLifecycleLock, find_record
    with WakeLifecycleLock(root, found.record['id']):
        current = find_record(root, found.record['id'])
        if current.record['status'] != 'pending':
            return False
        record = dict(current.record, status='failed', last_error='native wake expired')
        record = append_event(record, 'expired', 'native wake expired without submission', now)
        replace_record(root, current, record)
    return True


def _codex_adapter():
    return CodexRuntimeAdapter(
        read_thread=read_native_thread, request=native_request,
        run=subprocess.run, project_failure=submission_failure,
    )


from .wake_mode_runtime import guard_mode_dispatch


@guard_mode_dispatch
def dispatch_native(root, found, now, *, clock_provider=None, runtime_adapter: RuntimeAdapter | None = None):
    from .injector import DispatchResult
    record = dict(found.record)
    target = record['target']
    from .permission_migration import legacy_wake_held
    if legacy_wake_held(root,record):return DispatchResult('skipped','legacy_permission_adoption_required: retain original intent; resolve operator adoption')
    from .permission_wake import common_record, dispatch_native as dispatch_permission_native
    if common_record(record):
        return dispatch_permission_native(root,found,now,clock_provider=clock_provider,adapter=runtime_adapter or _codex_adapter())
    existing = record.get('native_delivery', {})
    if existing.get('state') == 'uncertain':
        return reconcile_native(root, found, now, runtime_adapter=runtime_adapter)
    from .network_wakes import precise_deadline
    intent = record.get('schema_version') in (6, 8)
    if intent:
        from .native_intents import dispatch_gate
        verdict = dispatch_gate(record, clock_provider())
        if verdict['state'] != 'due':
            record['status'] = 'failed' if verdict['state'] == 'missed_deadline' else 'pending'
            record['time_recovery'] = verdict
            record = append_event(record, 'native_time_held', verdict['reason'], None)
            replace_record(root, found, record)
            return DispatchResult('failed' if record['status'] == 'failed' else 'requeued', verdict['reason'])
        expiry = None
    else:
        expiry = precise_deadline(target['expires_at']) if record.get('schema_version') == 5 else parse_timestamp(target['expires_at'])
    if not intent and now >= expiry:
        record['status'] = 'failed'
        record = append_event(record, 'expired', 'native recipient deadline elapsed', now)
        replace_record(root, found, record)
        return DispatchResult('failed', 'native recipient deadline elapsed')
    adapter = runtime_adapter if runtime_adapter is not None else _codex_adapter()
    try:
        recipient = adapter.resolve(target)
        if recipient.version != 1:
            raise RuntimeTargetError('unsupported', 'unsupported_runtime_envelope_version')
        if recipient.runtime != 'codex' or recipient.session_id != target['thread_id']:
            raise RuntimeTargetError('unavailable', 'resolved_recipient_changed')
        observation = adapter.observe(recipient)
        record['runtime_observation'] = observation.summary(recipient)
        from .wake_policy import startup_reason
        policy_reason = startup_reason(record, observation)
        ready = observation.state == 'ready' and policy_reason is None
        if policy_reason or (target.get('session_mode') and observation.state != 'ready'):
            record['policy_outcome'] = dict(state='held', reason=policy_reason or observation.reason)
        if observation.resumed:
            record = append_event(record, 'native_same_thread_resumed',
                                  'explicit workflow policy resumed its exact saved thread', now)
    except Exception as exc:
        if not isinstance(exc, RuntimeTargetError):
            exc = RuntimeTargetError('unavailable', 'runtime_observation_unavailable')
        ready = False
        record['runtime_observation'] = dict(
            version=1, runtime=target.get('runtime', 'codex'),
            session_id=target.get('thread_id'), state=exc.state, reason=exc.reason,
            capabilities={},
        )
    if not ready:
        record['status'] = 'pending'
        if intent:
            record['next_attempt_at'] = None
        else:
            retry = now + timedelta(seconds=5)
            record['next_attempt_at'] = retry.isoformat().replace('+00:00', 'Z') if record.get('schema_version') == 5 else format_utc(retry)
        record = append_event(record, 'native_held', 'exact recipient is not available and idle', now)
        replace_record(root, found, record)
        return DispatchResult('requeued', 'exact recipient is not available and idle')
    if intent:
        # Runtime reads/resume can take time: refresh immediately before queueing.
        verdict = dispatch_gate(record, clock_provider())
        if verdict['state'] != 'due':
            record['status'] = 'failed' if verdict['state'] == 'missed_deadline' else 'pending'
            record['time_recovery'] = verdict
            record = append_event(record, 'native_time_held', verdict['reason'], None)
            replace_record(root, found, record)
            return DispatchResult('failed' if record['status'] == 'failed' else 'requeued', verdict['reason'])
    # Persist ambiguity BEFORE making the external effect. A crashed caller must
    # never assume the queue did not accept its submission.
    record['native_delivery'] = {'state': 'uncertain', 'execution': 'not_observed',
                                 'acknowledgment': 'not_observed',
                                 'submission_id': str(uuid4())}
    if target.get('session_mode'):
        for route in ('existing_tab', 'background', 'new_tab'):
            capability = observation.capabilities.get('wake.' + route)
            if capability is not None and capability.state == 'supported':
                record['native_delivery']['route'] = route
                break
    prompt = native_prompt(root, record)
    record['native_delivery']['prompt_sha256'] = hashlib.sha256(prompt.encode()).hexdigest()
    # Count the durable submission intent, including a crash before queueing.
    # Reconciliation observes that intent and never consumes another attempt.
    record['attempts'] += 1
    record = append_event(record, 'native_submission_started', 'native queue submission started', now)
    replace_record(root, found, record)
    try:
        submitted = adapter.submit(recipient, prompt)
        from .runtime_delivery import validate_native_submission
        validate_native_submission(submitted, target['thread_id'], allow_background=target.get('session_mode') == 'background')
    except Exception as exc:
        submitted = RuntimeSubmission(
            'uncertain', reason='runtime_adapter_exception', exception_type=type(exc).__name__,
            failure=submission_failure('runtime_adapter_exception', None, exc),
        )
    if submitted.state == 'not_sent' and submitted.pre_io is True:
        record.pop('native_delivery', None)
        record.update(status='cancelled' if submitted.reason == 'session_closed' else 'pending',
                      policy_outcome=dict(state='retired' if submitted.reason == 'session_closed' else 'held', reason=submitted.reason))
        replace_record(root, found, record)
        return DispatchResult('requeued', submitted.reason or 'native mode changed before submission')
    if submitted.state != 'accepted':
        record['native_delivery']['submission_failure'] = submitted.failure or {
            'reason': submitted.reason or 'runtime_submission_unconfirmed',
        }
        record['last_error'] = 'uncertain native submission: ' + (submitted.exception_type or 'RuntimeSubmission')
        record = append_event(record, 'native_uncertain', record['last_error'], now)
        replace_record(root, found, record)
        return DispatchResult('skipped', record['last_error'])
    record['status'] = 'submitted'
    receipt_field = 'turn_id' if submitted.evidence_kind == 'native_turn_acceptance' else 'queue_id'
    record['native_delivery'].update(state='accepted', **{receipt_field: submitted.receipt_id}, accepted_at=None if intent else format_utc(now))
    record = append_event(record, 'native_accepted', 'native queue accepted; execution not yet observed', now)
    replace_record(root, found, record)
    return DispatchResult('submitted', 'native queue accepted')


def native_prompt(root, record):
    prefix = f"WAKE_TRIGGER_ID={record['id']}\nWAKE_TRIGGER_ROOT={root.resolve()}\n"
    submission = record.get('native_delivery', {}).get('submission_id')
    if submission:
        prefix += f"WAKE_NATIVE_SUBMISSION_ID={submission}\n"
    return prefix + record['prompt']


def native_evidence(target, prompt):
    """Compatibility entrypoint for exact native evidence inspection."""
    adapter = _codex_adapter()
    observed = adapter.reconcile(adapter.resolve(dict(target, transport='native')), prompt)
    return observed.evidence, observed.reason


def reconcile_native(root, found, now, *, force=False, runtime_adapter: RuntimeAdapter | None = None):
    from .injector import DispatchResult
    record = dict(found.record)
    delivery = dict(record.get('native_delivery', {}))
    if delivery.get('state') != 'uncertain':
        return DispatchResult('skipped', 'native submission is not uncertain')
    if now is not None and not force and delivery.get('next_reconciliation_at') and now < parse_timestamp(delivery['next_reconciliation_at']):
        return DispatchResult('skipped', 'native reconciliation observation deferred')
    prompt = native_prompt(root, record)
    try:
        if delivery.get('prompt_sha256') and delivery['prompt_sha256'] != hashlib.sha256(prompt.encode()).hexdigest():
            raise WakeError('native submission payload changed')
        if runtime_adapter is None:
            evidence, reason = native_evidence(record['target'], prompt)
        else:
            recipient = runtime_adapter.resolve(record['target'])
            if (recipient.version != 1 or recipient.runtime != 'codex'
                    or recipient.session_id != record['target']['thread_id']):
                raise WakeError('reconciliation recipient changed')
            observed = runtime_adapter.reconcile(recipient, prompt)
            if not isinstance(observed, RuntimeReconciliation):
                raise WakeError('invalid runtime reconciliation outcome')
            evidence, reason = observed.evidence, observed.reason
        if evidence is not None:
            if not isinstance(evidence, dict) or evidence.get('source') not in ('native_queue', 'native_turn'):
                raise WakeError('runtime evidence does not confirm native acceptance')
            required = ('client_message_id', 'execution') + (
                ('queue_id',) if evidence['source'] == 'native_queue' else ('turn_id', 'user_message_id')
            )
            if not all(isinstance(evidence.get(key), str) and evidence[key] for key in required):
                raise WakeError('incomplete native acceptance evidence')
    except Exception as exc:
        evidence, reason = None, 'native_evidence_unavailable:' + type(exc).__name__
    if evidence is None:
        previous_reason = delivery.get('reconciliation', {}).get('reason')
        delivery.update(reconciliation=dict(state='unresolved', reason=reason, checked_at=format_utc(now) if now else None),
                        next_reconciliation_at=format_utc(now + timedelta(seconds=5)) if now else None)
        record['native_delivery'] = delivery
        if reason != previous_reason:
            record = append_event(record, 'native_unresolved', reason, now)
            if now is None:
                record['events'][-1].update(at=None, time_status='not_observed')
        replace_record(root, found, record)
        return DispatchResult('skipped', 'native submission unresolved; no resend')
    delivery.update(state='accepted', reconciled=True, evidence=evidence,
                    execution=evidence['execution'], acknowledgment='not_observed',
                    reconciliation=dict(state='resolved', checked_at=format_utc(now) if now else None))
    if evidence.get('queue_id'):
        delivery['queue_id'] = evidence['queue_id']
    record.update(status='submitted', native_delivery=delivery)
    record = append_event(record, 'native_reconciled', 'exact native evidence confirms acceptance; no resend', now)
    if now is None:
        record['events'][-1].update(at=None, time_status='not_observed')
    replace_record(root, found, record)
    return DispatchResult('submitted', 'native acceptance reconciled')


def reconcile_accepted_completion(root, record, read_codex_path=None):
    """Inspect terminal history without changing accepted intent or submitting input."""
    from .wake_mode_runtime import _peer_read_target, _terminal_evidence, _terminal_receipt
    prompt = native_prompt(root, record)
    expected = record['native_delivery'].get('prompt_sha256')
    if expected and expected != hashlib.sha256(prompt.encode()).hexdigest():
        return dict(state='unresolved', reason='native_submission_payload_changed')
    if _terminal_receipt(root, record) is not None:
        return dict(state='resolved', reason='terminal_evidence_already_recorded')
    try:
        target = record['target']
        if read_codex_path is not None:
            target = _peer_read_target(target, dict(target, codex_cmd=read_codex_path))
        evidence, _ = native_evidence(target, prompt)
    except Exception:
        return dict(state='unresolved', reason='native_evidence_unavailable')
    if not _terminal_evidence(evidence):
        return dict(state='unresolved', reason='native_terminal_evidence_unavailable')
    _terminal_receipt(root, record, evidence)
    return dict(state='resolved', reason='native_terminal_evidence_verified')


def reconcile_command(args, root):
    from .records import WakeLifecycleLock, find_record
    # Time recovery is a separate no-dispatch operation from submission recovery.
    # evaluate takes its own lifecycle lock and rechecks the current record.
    initial = find_record(root, args.wake_id)
    from .records import classify_record
    time_reconciled = (classify_record(initial.record) == 'native_intent_v6'
        and initial.record.get('status') == 'pending'
        and not initial.record.get('native_delivery'))
    if time_reconciled:
        from .native_clock import snapshot
        from .native_intents import evaluate
        evaluate(root, args.wake_id, snapshot())
    with WakeLifecycleLock(root, args.wake_id):
        found = find_record(root, args.wake_id)
        if found.record.get('target', {}).get('transport') != 'native':
            raise WakeError('reconciliation requires a native wake')
        if found.record.get('native_delivery', {}).get('state') == 'accepted':
            completion = reconcile_accepted_completion(root, found.record, getattr(args, 'read_codex_path', None))
            print(json.dumps(dict(wake_id=args.wake_id,
                result='completion_reconciled' if completion['state'] == 'resolved' else 'skipped',
                status=found.record['status'], native_delivery=found.record['native_delivery'],
                terminal_reconciliation=completion, dispatch_attempted=False), sort_keys=True))
            return 0
        if time_reconciled and not found.record.get('native_delivery'):
            from .native_intents import schedule_projection
            print(json.dumps(dict(wake_id=args.wake_id, result='time_reconciled',
                status=found.record['status'], native_delivery=None, dispatch_attempted=False,
                time_recovery=found.record['time_recovery'],
                next_action='Verify an active compatible monitor for this root; time recovery alone is not delivery.',
                **schedule_projection(found.record)), sort_keys=True))
            return 0
        if classify_record(found.record) == 'native_intent_v6':
            current = None
        elif classify_record(found.record) == 'native_network_v5':
            from .network_wakes import read_time, evaluation_time
            try:
                current = evaluation_time(read_time())
            except WakeError:
                current = None
        else:
            current = utc_now()
        result = reconcile_native(root, found, current, force=True)
        current = find_record(root, args.wake_id).record
    print(json.dumps(dict(wake_id=args.wake_id, result=result.status,
                         status=current['status'], native_delivery=current.get('native_delivery')), sort_keys=True))
    return 0


def migrate_command(args, root):
    """Metadata-only promotion. Never translate transport or replay an effect."""
    from .records import WakeLifecycleLock, find_record, classify_record, NATIVE_SCHEMA_VERSION
    with WakeLifecycleLock(root, args.wake_id):
        found = find_record(root, args.wake_id)
        record = found.record
        if record.get('schema_version') in (NATIVE_SCHEMA_VERSION, 5):
            if classify_record(record) == 'hold':
                raise WakeError('current native record is malformed; inspect before continuing')
            print(json.dumps({'id': args.wake_id, 'state': 'already_current', 'submitted': False}))
            return 0
        promoted = dict(record, schema_version=NATIVE_SCHEMA_VERSION)
        if record.get('schema_version') != 1 or classify_record(promoted) == 'hold':
            raise WakeError('migration requires an earlier schema1 native time/file record')
        backup = root / 'migration' / (args.wake_id + '.schema1.json')
        if args.apply:
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            original = found.path.read_bytes()
            try:
                descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                if backup.read_bytes() != original:
                    raise WakeError('migration backup differs; inspect before continuing') from None
            for directory_path in (backup.parent, root):
                directory = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            replace_record(root, found, promoted)
        print(json.dumps({'id': args.wake_id, 'state': 'migrated' if args.apply else 'would_migrate',
                          'schema_version': NATIVE_SCHEMA_VERSION, 'backup': str(backup),
                          'submitted': False}))
        return 0
