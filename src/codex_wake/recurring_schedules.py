"""Wake-owned schedules; each original occurrence feeds the existing native core."""
from __future__ import annotations

import contextlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from .records import WakeError, WakeLifecycleLock, all_records
from .wake_policy import _read, _write

MAX_POLL_OCCURRENCES = 256
TERMINAL = {'cancelled', 'failed', 'expired', 'archived', 'skipped', 'coalesced'}


def timestamp(value):
    from .network_wakes import precise_deadline
    return precise_deadline(value).astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def positive(value, name, *, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or value <= 0:
        raise WakeError('invalid_' + name)
    return value


def validate_request(request):
    required = {'idempotency_key', 'thread_id', 'prompt', 'session_mode', 'cadence', 'end', 'missed', 'overlap', 'delivery_window_seconds'}
    if not isinstance(request, dict) or set(request) != required:
        raise WakeError('explicit_schedule_fields_required: ' + ','.join(sorted(required)))
    from .wake_session_modes import MODES
    if request['session_mode'] not in MODES:
        raise WakeError('explicit_session_mode_required')
    try:
        if str(UUID(request['thread_id'])) != request['thread_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise WakeError('exact_schedule_thread_required') from None
    for key, maximum in (('prompt', 32768), ('idempotency_key', 160)):
        if not isinstance(request[key], str) or not request[key].strip() or len(request[key].encode()) > maximum:
            raise WakeError('invalid_schedule_' + key)
    positive(request['delivery_window_seconds'], 'delivery_window', integer=True)
    cadence = request['cadence']
    if not isinstance(cadence, dict):
        raise WakeError('invalid_cadence')
    if cadence.get('kind') == 'interval':
        if set(cadence) != {'kind', 'seconds', 'start_at'}:
            raise WakeError('explicit_interval_fields_required')
        positive(cadence['seconds'], 'interval', integer=True)
        start = timestamp(cadence['start_at'])
        try:
            start + timedelta(seconds=cadence['seconds'])
        except (OverflowError, ValueError):
            raise WakeError('interval_outside_supported_calendar') from None
    elif cadence.get('kind') == 'clock':
        from .recurring_calendar import validate_cadence
        validate_cadence(cadence)
    else:
        raise WakeError('unsupported_schedule_cadence')
    end = request['end']
    if not isinstance(end, dict):
        raise WakeError('explicit_end_required')
    if end.get('kind') == 'count' and set(end) == {'kind', 'count'}:
        positive(end['count'], 'occurrence_count', integer=True)
    elif end.get('kind') == 'until' and set(end) == {'kind', 'at'}:
        timestamp(end['at'])
    elif end != {'kind': 'until_cancelled'}:
        raise WakeError('explicit_end_required')
    for key, policies in (('missed', {'skip', 'latest', 'catch_up'}), ('overlap', {'skip', 'latest', 'queue'})):
        policy = request[key]
        if not isinstance(policy, dict) or policy.get('policy') not in policies:
            raise WakeError('explicit_' + key + '_policy_required')
        fields = {'policy', 'max_lateness_seconds'} if key == 'missed' else {'policy'}
        if key == 'missed':
            positive(policy['max_lateness_seconds'], 'maximum_lateness')
        if policy['policy'] in ('catch_up', 'queue'):
            fields.add('limit')
            positive(policy.get('limit'), key + '_bound', integer=True)
            if policy['limit'] > MAX_POLL_OCCURRENCES:
                raise WakeError('schedule_bound_exceeds_256')
        if set(policy) != fields:
            raise WakeError('invalid_' + key + '_fields')
    return deepcopy(request)


def first_due(cadence):
    if cadence['kind'] == 'interval':
        return timestamp(cadence['start_at'])
    from .recurring_calendar import first_due as calendar_first
    return timestamp(calendar_first(cadence))


def next_due(cadence, due):
    if cadence['kind'] == 'interval':
        return due + timedelta(seconds=cadence['seconds'])
    from .recurring_calendar import next_due as calendar_next
    return timestamp(calendar_next(cadence, iso(due)))


class ScheduleStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / 'schedules'

    def path(self, schedule_id):
        if not isinstance(schedule_id, str) or len(schedule_id) != 41 or not schedule_id.startswith('schedule_') or any(c not in '0123456789abcdef' for c in schedule_id[9:]):
            raise WakeError('invalid_schedule_id')
        return self.directory / (schedule_id + '.json')

    def read(self, schedule_id):
        value = _read(self.path(schedule_id))
        if value.get('version') != 1 or value.get('id') != schedule_id or value.get('root') != str(self.root):
            raise WakeError('invalid_schedule_record')
        validate_request(value['request'])
        return value

    def records(self):
        return [self.read(p.stem) for p in sorted(self.directory.glob('schedule_*.json'))]

    def save(self, value):
        stored = deepcopy(value)
        # Revision context is retained once. Repeating a large prompt for every
        # missed occurrence would make a healthy schedule exceed store capacity.
        for item in stored['occurrences']:
            for field in ('request', 'target', 'wake_policy'):
                item.pop(field, None)
        _write(self.path(value['id']), stored)

    @staticmethod
    def context(value, occurrence):
        if 'request' in occurrence:
            return occurrence
        if occurrence['revision'] == value['revision']:
            return value
        for revision in value['revisions']:
            if revision['revision'] == occurrence['revision']:
                return revision
        raise WakeError('occurrence_revision_context_missing')

    def register(self, request, *, codex_path='codex', endpoint='unix://', principal=None, authorize=None):
        request = validate_request(request)
        from .session_permissions import PermissionStore
        if authorize is not None: authorize(request['thread_id'])
        if authorize is None and principal is not None and principal.role != 'operator' and principal.subject != request['thread_id']:
            raise WakeError('schedule_exact_self_required')
        if PermissionStore(self.root).active() and principal is None:
            raise WakeError('schedule_verified_principal_required')
        key = request['idempotency_key']
        identifier = 'schedule_' + hashlib.sha256(key.encode()).hexdigest()[:32]
        with WakeLifecycleLock(self.root, 'recurring-schedules'):
            if self.path(identifier).exists():
                old = self.read(identifier)
                if old['request'] != request:
                    raise WakeError('idempotency_conflict: schedule differs')
                self.authorize(old, principal, authorize)
                return self.receipt(old)
            due = first_due(request['cadence'])
            args = self.native_args(request, due, 'schedule-admission:' + identifier, codex_path, endpoint)
            args._permission_principal = principal
            from .native_intents import _request
            _, content, *_ = _request(args, self.root)
            # Policy provenance is frozen once; dispatch rechecks current permissions.
            policy = content.get('wake_policy')
            value = dict(version=1, id=identifier, root=str(self.root), revision=1, state='enabled',
                request=request, target=content['target'], wake_policy=policy,
                next_due_at=iso(due), next_index=0, occurrences=[], revisions=[], last_poll_generation=monitor_generation(self.root))
            self.save(value)
            return self.receipt(value)

    @staticmethod
    def native_args(request, due, key, codex_path, endpoint):
        return SimpleNamespace(native_command='at', thread_id=request['thread_id'], trigger=iso(due),
            ttl=str(request['delivery_window_seconds'])+'s', prompt=[request['prompt']],
            codex_path=codex_path, endpoint=endpoint, resume_missing=False,
            wake_policy_enabled=True, wake_lifetime=None, recipient_startup=None,
            owner_id=None, owner_end=None, session_mode=request['session_mode'],
            wake_routes=None, idempotency_key=key, time_tolerance='5m', stop_at=None,
            as_json=True, require_monitor=False, busy_policy='wait')

    def authorize(self, value, principal, authorize=None):
        if authorize is not None:
            authorize(value["request"]["thread_id"])
            return
        if principal is not None and principal.role != 'operator' and principal.subject != value['request']['thread_id']:
            raise WakeError('schedule_authority_denied')
        context = (value.get('wake_policy') or {}).get('permission_context')
        if context and (principal is None or principal.role != 'operator' and principal.subject != context['subject']):
            raise WakeError('schedule_authority_denied')

    def revise(self, identifier, request, expected_revision, *, principal=None, codex_path='codex', endpoint='unix://', authorize=None):
        request = validate_request(request)
        with WakeLifecycleLock(self.root, 'recurring-schedules'):
            value = self.read(identifier)
            self.authorize(value, principal, authorize)
            if value['revision'] != expected_revision:
                raise WakeError('schedule_revision_conflict')
            if value['state'] == 'cancelled':
                raise WakeError('cancelled_schedule_requires_new_registration')
            if any(request[k] != value['request'][k] for k in ('idempotency_key', 'thread_id')):
                raise WakeError('schedule_identity_immutable')
            due = first_due(request['cadence'])
            # Cadence edits never regenerate occurrences already planned. Mode
            # edits retain the next original due when cadence is unchanged.
            if request['cadence'] == value['request']['cadence']:
                due = timestamp(value['next_due_at'])
            elif value['occurrences']:
                latest = max(timestamp(o['due_at']) for o in value['occurrences'])
                if due <= latest:
                    if request['cadence']['kind'] == 'interval':
                        step = timedelta(seconds=request['cadence']['seconds'])
                        due += ((latest - due) // step + 1) * step
                    else:
                        due = next_due(request['cadence'], latest)
            args = self.native_args(request, due, 'schedule-revision:' + identifier + ':' + str(expected_revision+1), codex_path, endpoint)
            args._permission_principal = principal
            from .app_server import resolve_codex_cmd
            if (request['session_mode'] == value['request']['session_mode']
                    and endpoint == value['target']['endpoint']
                    and resolve_codex_cmd(codex_path, required=True, preserve_launcher=True) == value['target']['codex_cmd']):
                # A cadence/end edit keeps the exact existing binding. Recheck
                # permissions below, without new runtime discovery or rebinding.
                from .wake_session_modes import STARTUP
                args._schedule_target = dict(value['target'])
                args.wake_lifetime = 'persistent'
                args.recipient_startup = STARTUP[request['session_mode']]
            from .native_intents import _request
            _, content, *_ = _request(args, self.root)
            value['revisions'].append(dict(revision=value['revision'], request=value['request'], target=value['target'], wake_policy=value['wake_policy']))
            value.update(revision=value['revision']+1, request=request, target=content['target'], wake_policy=content.get('wake_policy'), next_due_at=iso(due), state='enabled')
            value.pop('attention', None)
            self.save(value)
            return self.receipt(value)

    def cancel(self, identifier, expected_revision, *, principal=None, authorize=None):
        with WakeLifecycleLock(self.root, 'recurring-schedules'):
            value = self.read(identifier)
            self.authorize(value, principal, authorize)
            if value['revision'] != expected_revision:
                raise WakeError('schedule_revision_conflict')
            value['state'] = 'cancelled'
            self.save(value)  # Future occurrence admission stops before child sweep.
            self.cancel_pending(value)
            self.save(value)
            return self.receipt(value)

    def cancel_pending(self, value):
        from .records import find_record, replace_record, append_event
        for item in value['occurrences']:
            if item['state'] == 'queued':
                item['state'] = 'cancelled'
            if not item.get('wake_id'):
                continue
            with WakeLifecycleLock(self.root, item['wake_id']):
                found = find_record(self.root, item['wake_id'])
                record = dict(found.record)
                if record['status'] not in ('pending', 'firing') or record.get('native_delivery', {}).get('state') in ('accepted', 'uncertain'):
                    continue
                record['status'] = 'cancelled'
                record = append_event(record, 'schedule_cancelled', value['id'], None)
                replace_record(self.root, found, record)
                item['state'] = 'cancelled'

    def bind_restoration(self, identifier, *, profiles, managed_agent_id, profile, principal, authorize=None):
        from .wake_live_restore import LiveWakeRestorer
        if principal is None or principal.role != 'operator':
            raise WakeError('live_restore_operator_required')
        with WakeLifecycleLock(self.root, 'recurring-schedules'):
            value = self.read(identifier)
            self.authorize(value, principal, authorize)
            LiveWakeRestorer(self.root).bind(value['target'], profiles=profiles,
                                            managed_agent_id=managed_agent_id, profile=profile,
                                            authorize=lambda: self.authorize(value, principal, authorize))
        return self.receipt(value)

    def receipt(self, value, *, wake_records=None):
        from .monitor import read_monitor_health
        from .signal_records import probe_managed_reader_capability
        health = read_monitor_health(self.root) or {}
        reader = probe_managed_reader_capability(self.root)
        ready = bool(reader and 8 in reader.schema_versions and health.get('mode') == 'loop'
                     and all(c in health.get('reader_capabilities', []) for c in ('recurring_schedules_v1', 'wake_session_modes_v1')))
        from .wake_live_restore import LiveWakeRestorer
        identifiers = {item['wake_id']: item['id'] for item in value['occurrences'] if item.get('wake_id')}
        uncertain = []
        held = []
        if identifiers:
            if wake_records is None:
                wake_records = {item.record['id']: item.record for item in all_records(self.root, include_archive=True)}
            for wake_id, occurrence_id in identifiers.items():
                wake = wake_records.get(wake_id, {})
                delivery = wake.get('native_delivery', {})
                outcome = wake.get('policy_outcome', {})
                if delivery.get('state') != 'uncertain' and outcome.get('state') == 'held':
                    observed = wake.get('runtime_observation', {})
                    held.append(dict(occurrence_id=occurrence_id, wake_id=wake_id,
                        wake_status=wake.get('status'), reason=outcome.get('reason'),
                        recipient_state=observed.get('state'), recipient_reason=observed.get('reason'),
                        native_status=observed.get('native_status'),
                        observation_recorded_by=observed.get('recorded_by'),
                        next_check_at=wake.get('next_attempt_at'),
                        timing_reason=wake.get('time_recovery', {}).get('reason')))
                if delivery.get('state') == 'uncertain':
                    reason = delivery.get('reconciliation', {}).get('reason') or 'delivery_outcome_unknown'
                    uncertain.append(dict(occurrence_id=occurrence_id, wake_id=wake_id,
                        reconciliation=dict(reason=reason, command=['native', 'reconcile', wake_id])))
        return dict(value, session_mode=value['request']['session_mode'],
            persistence=dict(saved=True),
            restoration=LiveWakeRestorer(self.root).inspect(
                dict(value['target'], session_mode=value['request']['session_mode'])),
            delivery=dict(uncertain=bool(uncertain), uncertain_occurrences=uncertain, held_occurrences=held),
            armed=ready and value['state'] == 'enabled',
            scheduling_status='armed' if ready and value['state']=='enabled' else 'retained_unmonitored' if not ready and value['state']=='enabled' else value['state'],
            monitor=dict(ready=ready, wake_root=str(self.root)))

    def emit(self, value, occurrence, clock):
        due = timestamp(occurrence['due_at'])
        context = self.context(value, occurrence)
        request = context['request']
        target = context['target']
        args = self.native_args(request, due, occurrence['id'], target['codex_cmd'], target['endpoint'])
        args._schedule_clock = clock
        args._schedule_target = target
        args._schedule_wake_policy = context['wake_policy']
        from .native_intents import retain
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            retain(args, self.root)
        occurrence['wake_id'] = json.loads(output.getvalue())['id']
        occurrence['state'] = 'pending'


def poll_schedules(root, clock, *, runtime_adapter=None):
    """Bounded scheduling only; existing daemon owns native dispatch and evidence."""
    store = ScheduleStore(root)
    if not store.directory.exists():
        return []
    from .native_intents import valid_utc
    if not valid_utc(clock.get('utc')):
        return []
    now = clock['utc']['lower']
    results = []
    generation = scheduler_generation()
    with WakeLifecycleLock(store.root, 'recurring-schedules'):
        wakes = {w.record['id']: w.record for w in all_records(store.root, include_archive=True)}
        for value in store.records():
            if value['state'] == 'cancelled':
                store.cancel_pending(value)
                store.save(value)
                continue
            if value['state'] not in ('enabled', 'exhausted'):
                continue
            from .wake_session_modes import session_state
            state = session_state(value['target'])
            if state == 'closed':
                value['state'] = 'cancelled'
                value['reason'] = 'session_closed'
                store.cancel_pending(value)
                store.save(value)
                continue
            if state == 'unknown':
                value['attention'] = 'session_owner_unverified'
                store.save(value)
                continue
            recovering = value.get('last_poll_generation') is None or value.get('last_poll_generation') != generation
            value['last_poll_generation'] = generation
            for item in value['occurrences']:
                wake = wakes.get(item.get('wake_id'))
                if wake and item['state'] not in ('completed', 'turn_failed', 'turn_interrupted'):
                    item['state'] = wake['status']
                    delivery = wake.get('native_delivery', {})
                    if delivery.get('state') == 'uncertain':
                        item['reconciliation_reason'] = 'delivery_outcome_unknown'
                        continue
                    item.pop('reconciliation_reason', None)
                    execution = delivery.get('execution')
                    if delivery.get('state') == 'accepted' and execution not in ('turn_completed', 'turn_failed', 'turn_interrupted'):
                        try:
                            from .native_delivery import _codex_adapter, native_prompt
                            adapter = runtime_adapter or _codex_adapter()
                            recipient = adapter.resolve(wake['target'])
                            evidence = adapter.reconcile(recipient, native_prompt(store.root, wake)).evidence
                            if (recipient.runtime == 'codex' and recipient.session_id == wake['target']['thread_id'] and evidence
                                    and evidence.get('source') == 'native_turn' and all(evidence.get(k) for k in ('turn_id', 'user_message_id', 'client_message_id'))):
                                execution = evidence.get('execution')
                        except Exception:
                            pass
                    if execution in ('turn_completed', 'turn_failed', 'turn_interrupted'):
                        item['state'] = 'completed' if execution == 'turn_completed' else execution
                    outcome = wake.get('policy_outcome', {})
                    observation = wake.get('runtime_observation', {})
                    reason = outcome.get('reason') or observation.get('reason')
                    transient_route = (
                        reason == 'wake_route_unavailable'
                        and observation.get('reason') in ('recipient_ownership_unknown', 'mode_route_not_selected')
                        and all(route.endswith(':unsupported') for route in outcome.get('routes', ()))
                    )
                    if (reason and not transient_route
                            and reason not in ('conversation_check_in_progress', 'recipient_busy', 'mode_route_not_selected')
                            and observation.get('state') in ('unavailable', 'unsupported')):
                        item['state'] = 'attention'
                        item['reason'] = reason
                        value['attention'] = reason
                        # Keep deadline/identity; require explicit schedule revision
                        # after resolving configuration before another launch.
                        value['state'] = 'attention'
                        store.cancel_pending(value)
                        item['state'] = 'attention'
                        publish_attention(store, value, item, now)

            request = value['request']
            newly_due = []
            if value['state'] == 'attention':
                store.save(value)
                results.append(store.receipt(value, wake_records=wakes))
                continue
            for _ in range(MAX_POLL_OCCURRENCES):
                due = timestamp(value['next_due_at'])
                end = request['end']
                if (end['kind'] == 'count' and value['next_index'] >= end['count'] or
                        end['kind'] == 'until' and due >= timestamp(end['at'])):
                    value['state'] = 'exhausted'
                    break
                if due.timestamp() > now:
                    break
                index = value['next_index']
                occurrence = dict(id=f"{value['id']}:{value['revision']}:{index}", revision=value['revision'], index=index,
                    due_at=iso(due), expires_at=iso(due+timedelta(seconds=request['delivery_window_seconds'])),
                    state='queued', arrival_pending=True, recovered=recovering, request=deepcopy(request), target=deepcopy(value['target']), wake_policy=deepcopy(value['wake_policy']))
                value['occurrences'].append(occurrence)
                newly_due.append(occurrence)
                value['next_index'] += 1
                try:
                    value['next_due_at'] = iso(next_due(request['cadence'], due))
                except (ValueError, OverflowError):
                    value['state'] = 'attention'
                    value['attention'] = 'cadence_outside_supported_calendar'
                    break
            # Save occurrence identity before any downstream registration.
            store.save(value)
            eligible = []
            for item in value['occurrences']:
                if item['state'] != 'queued':
                    continue
                lateness = now - timestamp(item['due_at']).timestamp()
                if now >= timestamp(item['expires_at']).timestamp() or lateness > store.context(value, item)['request']['missed']['max_lateness_seconds']:
                    item['state'] = 'expired'
                else:
                    eligible.append(item)
            caught_up = value['state'] == 'exhausted' or timestamp(value['next_due_at']).timestamp() > now
            if not caught_up:
                store.save(value)
                continue
            # Classify only newly arrived/recovered occurrences. An overlap queue
            # has already passed its missed-run decision and must keep that choice.
            arrivals = [item for item in eligible if item.get('arrival_pending')]
            groups = {}
            for item in arrivals:
                groups.setdefault(item['revision'], []).append(item)
            for group in groups.values():
                missed = store.context(value, group[0])['request']['missed']
                recovered = any(item.get('recovered') for item in group)
                behind = [item for item in group if timestamp(item['due_at']).timestamp() < now]
                if not recovered and len(group) <= 1:
                    behind = []  # ordinary polling jitter within the window
                elif not recovered:
                    behind = group[:-1]
                if missed['policy'] == 'skip':
                    for item in behind:
                        item['state'] = 'skipped'
                elif missed['policy'] == 'latest' and len(group) > 1:
                    for item in group[:-1]:
                        item['state'] = 'coalesced'
                elif missed['policy'] == 'catch_up':
                    for item in group[:-missed['limit']]:
                        item['state'] = 'skipped'
                for item in group:
                    item['arrival_pending'] = False
            pending = [item for item in value['occurrences'] if item['state'] == 'queued']
            active = any(item['state'] in ('pending', 'firing', 'submitted') for item in value['occurrences'])
            overlap = request['overlap']
            if active:
                if overlap['policy'] == 'skip':
                    for item in pending: item['state'] = 'skipped'
                elif overlap['policy'] == 'latest':
                    for item in pending[:-1]: item['state'] = 'coalesced'
                elif len(pending) > overlap['limit']:
                    for item in pending[:-overlap['limit']]: item['state'] = 'skipped'
            elif pending and (value['state'] == 'exhausted' or timestamp(value['next_due_at']).timestamp() > now):
                candidate = pending[0]
                store.save(value)
                try:
                    store.emit(value, candidate, clock)
                except (WakeError, OSError, ValueError) as exc:
                    candidate['state'] = 'attention'
                    candidate['reason'] = str(exc)
                    value['attention'] = str(exc)
            store.save(value)
            results.append(store.receipt(value, wake_records=wakes))
    return results


def publish_attention(store, value, occurrence, now):
    """A notice grants no resume authority; failure remains inspectable in schedule."""
    from .attention_queue import AttentionQueue
    from .session_permissions import Principal, PermissionStore
    context = (store.context(value, occurrence).get('wake_policy') or {}).get('permission_context') or {}
    principal = Principal(context.get('subject', value['request']['thread_id']), context.get('role', 'session'), tuple(context.get('tasks', [])))
    permissions = PermissionStore(store.root)
    try:
        revision = permissions._read()['revision'] if permissions.active() else 1
        request = dict(key='schedule:' + occurrence['id'], kind='notice',
            question='Scheduled check needs attention: ' + occurrence.get('reason', 'recipient unavailable'),
            options=['acknowledge'], evidence=[value['id'], occurrence['id']], priority='normal',
            expires_at=timestamp(occurrence['expires_at']).timestamp(), permission_decision=False,
            context=dict(owner=principal.subject, operation_id=occurrence['id'], attempt=1,
                task_id=context.get('task_id'), allocation_id='unchanged', runtime='codex',
                conversation_id=value['request']['thread_id'], account='not_attested', target=value['request']['thread_id'],
                action='wake.background' if value['request']['session_mode']=='background' else 'wake.new_tab',
                effect_scope='resume_existing_scope', policy_root=str(permissions.root), policy_revision=revision, operation_state='blocked'))
        occurrence['attention_id'] = AttentionQueue(store.root, now=lambda: now).request(principal, request)['request_id']
    except (WakeError, OSError, ValueError, KeyError) as exc:
        occurrence['attention_error'] = str(exc)


def scheduler_generation():
    import multiprocessing
    import os
    from .process import process_identity
    parent = multiprocessing.parent_process()
    pid = parent.pid if parent is not None else os.getpid()
    identity = process_identity(pid)
    return dict(pid=pid, identity=identity) if identity else None


def monitor_generation(root):
    from .monitor import read_monitor_health
    from .signal_records import probe_managed_reader_capability
    from .process import process_identity
    health = read_monitor_health(root) or {}
    generation = health.get('recurring_monitor_generation')
    if not isinstance(generation, dict) or type(generation.get('pid')) is not int:
        return None
    identity = process_identity(generation['pid'])
    if (probe_managed_reader_capability(root) and health.get('mode') == 'loop'
            and 'recurring_schedules_v1' in health.get('reader_capabilities', [])
            and identity and identity == generation.get('identity')):
        return generation
    return None
