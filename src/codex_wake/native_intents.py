"""Durable native scheduling intent, independent of acquisition availability."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4
from datetime import UTC, datetime
import math
import re

from .records import WakeError, WakeLifecycleLock, all_records, parse_duration, write_record

SCHEMA_VERSION = 6
EVENT_SCHEMA_VERSION = 9
EVENT_CAPABILITY = "native_file_until_event_v1"


def _save(root, record):
    return write_record(root, record)


def _request(args, root):
    from .app_server import resolve_codex_cmd
    from .cli import normalize_prompt
    from .network_wakes import precise_deadline

    root = Path(root).resolve()
    prompt = normalize_prompt(args.prompt)
    ttl = parse_duration(args.ttl).total_seconds()
    observation = getattr(args, 'observation_policy', 'registration_window')
    if observation not in ('registration_window', 'until_event_or_cancel') or observation != 'registration_window' and args.native_command != 'file':
        raise WakeError('invalid_native_observation_policy')
    if args.native_command == "after":
        schedule = {"kind": "after", "delay_seconds": parse_duration(args.trigger).total_seconds()}
        predicate = {"type": "not_before", "due_at": None}
    elif args.native_command == "at":
        due = precise_deadline(args.trigger).isoformat().replace("+00:00", "Z")
        schedule = {"kind": "at", "due_at": due}
        predicate = {"type": "not_before", "due_at": due}
    else:
        schedule = {"kind": "file", "path": str(Path(args.trigger).resolve())}
        predicate = {"type": "file_exists", "path": schedule["path"]}
        if observation == 'until_event_or_cancel':
            schedule['observation_policy'] = observation
    tolerance = getattr(args, "time_tolerance", None)
    tolerance = parse_duration(tolerance).total_seconds() if tolerance else max(1.0, min(300.0, schedule.get("delay_seconds", 0) / 50))
    if tolerance > 300:
        raise WakeError("native time tolerance must be at most 5m")
    stop = getattr(args, "stop_at", None)
    stop = precise_deadline(stop).isoformat().replace("+00:00", "Z") if stop else None
    target = {"transport": "native", "thread_id": args.thread_id,
              "codex_cmd": resolve_codex_cmd(args.codex_path, required=True, preserve_launcher=True),
              "endpoint": args.endpoint, "expires_at": None,
              "resume_policy": "same_thread" if args.resume_missing else "hold"}
    from .wake_session_modes import bind_mode
    if hasattr(args, "_schedule_target"):
        target = dict(args._schedule_target)
    else:
        bind_mode(args, root, target)
    from .runtime_policies import require_native_policy
    busy_policy = getattr(args, 'busy_policy', 'wait')
    require_native_policy(busy_policy)
    # Absence is the historical immutable wait default. Preserve old request
    # fingerprints on replay; queue must be retained explicitly.
    if busy_policy == 'queue':
        target['busy_policy'] = busy_policy
    else:
        target.pop('busy_policy', None)
    cwd = args._registration_cwd if hasattr(args, "_registration_cwd") else Path.cwd().resolve()
    content = {"root": str(root), "cwd": str(cwd), "target": target,
               "schedule": schedule, "ttl_seconds": ttl, "prompt": prompt,
               "tolerance_seconds": tolerance, "stop_at": stop}
    from .wake_policy import request_policy
    policy = (args._schedule_wake_policy if hasattr(args, "_schedule_wake_policy")
              else request_policy(root, args, "codex:" + args.thread_id))
    if policy is not None:
        content["wake_policy"] = policy
        target["startup_policy"] = policy["startup"]
        if policy["startup"] == "active_tab" and args.resume_missing:
            raise WakeError("active_tab_conflicts_with_resume_missing")
        target["resume_policy"] = "hold" if policy["startup"] == "active_tab" else "same_thread"
    key = getattr(args, "idempotency_key", None)
    if key is not None and (not key.strip() or len(key) > 200):
        raise WakeError("idempotency key must contain 1..200 characters")
    fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    lock = hashlib.sha256((str(root) + "\n" + key).encode()).hexdigest() if key else fingerprint
    return root, content, predicate, fingerprint, key, lock


def _existing(root, fingerprint, key):
    for item in all_records(root, include_archive=key is not None):
        intent = item.record.get("scheduling_intent", {})
        if not isinstance(intent, dict):
            continue
        matches = intent.get("idempotency_key") == key if key else intent.get("fingerprint") == fingerprint and item.record.get("status") in {"pending", "firing"}
        if matches and intent.get("canonical_root") == str(root):
            if intent.get("fingerprint") != fingerprint:
                raise WakeError("idempotency_conflict: original scheduling request differs")
            if not valid_record(item.record):
                raise WakeError("original scheduling intent is invalid; reconcile instead of retrying")
            return item
    return None


def until_event(record):
    return record.get('scheduling_intent', {}).get('schedule', {}).get('observation_policy') == 'until_event_or_cancel'


def _observe_event_match(record, clock):
    intent = record['scheduling_intent']
    if not until_event(record) or intent.get('event_match') is not None:
        return
    if not Path(intent['schedule']['path']).exists():
        return
    utc, counter = clock.get('utc'), clock.get('counter')
    if not valid_utc(utc) and not valid_counter(counter):
        return  # The durable state can be rechecked; no match time is fabricated.
    intent['event_match'] = dict(utc_anchor=dict(utc) if valid_utc(utc) else None,
                                counter_anchor=dict(counter) if valid_counter(counter) else None)
    record['events'] = list(record['events']) + [dict(at=None, type='event_matched', message='Original file condition observed; delivery window anchored once')]


def schedule_projection(record):
    """Display original anchored dates; never rebase or grant dispatch authority."""
    intent = record['scheduling_intent']
    schedule = intent['schedule']
    if until_event(record):
        match = intent.get('event_match')
        if match is None:
            return dict(due_at=None, expires_at=None, basis='awaiting_event')
        intent = dict(intent, **match)
    due = None
    if schedule['kind'] == 'at':
        from .network_wakes import precise_deadline
        due = precise_deadline(schedule['due_at']).timestamp()
    elif valid_utc(intent.get('utc_anchor')):
        due = intent['utc_anchor']['upper'] + schedule.get('delay_seconds', 0)
    if due is None:
        return dict(due_at=None, expires_at=None, basis='original_utc_unavailable')
    try:
        dates = [datetime.fromtimestamp(value, UTC).isoformat().replace('+00:00', 'Z')
                 for value in (due, due + intent['ttl_seconds'])]
    except (OverflowError, ValueError, OSError):
        return dict(due_at=None, expires_at=None, basis='outside_supported_calendar')
    return dict(due_at=dates[0], expires_at=dates[1], basis='original_utc_anchor')


def project_schedule(record):
    projection = schedule_projection(record)
    if record['predicate']['type'] == 'not_before':
        record['predicate']['due_at'] = projection['due_at']
    return projection


def _receipt(args, record, path, deduplicated):
    from .signal_records import probe_managed_reader_capability
    root = Path(record['scheduling_intent']['canonical_root'])
    reader = probe_managed_reader_capability(root)
    from .monitor import read_monitor_health
    health = read_monitor_health(root) or {}
    required_capabilities = ['wake_session_modes_v1'] if record.get('target', {}).get('session_mode') else []
    if until_event(record):
        required_capabilities.append(EVENT_CAPABILITY)
    monitored = (reader is not None and record['schema_version'] in reader.schema_versions and health.get('mode') == 'loop'
                 and all(c in health.get('reader_capabilities', []) for c in required_capabilities))
    if getattr(args, 'require_monitor', False) and not monitored:
        raise WakeError(f"schema{record['schema_version']} intent retained as {record['id']}; active compatible worker unavailable; upgrade or enroll the owning monitor")
    intent = record['scheduling_intent']
    anchors = intent.get('event_match') or intent
    unanchored = (not until_event(record) and intent['schedule']['kind'] != 'at' and anchors.get('counter_anchor') is None
                  and anchors.get('utc_anchor') is None)
    recovery = 'requires_original_clock_evidence' if unanchored else 'on_monitor_poll'
    value = {"id": record["id"], "path": str(path), "status": record["status"],
             "time_recovery": record["time_recovery"], "deduplicated": deduplicated,
             "automatic_recovery": recovery, "requires_original_clock_evidence": unanchored,
             "requires_worker_schema": record["schema_version"], "requires_worker_capabilities": required_capabilities, "wake_policy": record.get("wake_policy")}
    projection = schedule_projection(record)
    current_time = record['time_recovery']
    if until_event(record) and intent.get('event_match') is not None:
        from .native_clock import snapshot
        current_time = eligibility(record, args._schedule_clock if hasattr(args, '_schedule_clock') else snapshot())
        value['time_recovery'] = current_time
    value.update(capabilities=[EVENT_CAPABILITY],
                 observation_policy='until_event_or_cancel' if until_event(record) else 'registration_window')
    if until_event(record):
        value['observation_state'] = 'matched' if intent.get('event_match') is not None else 'waiting'
        value['delivery_window_seconds'] = intent['ttl_seconds']
    if record.get("target", {}).get("session_mode"):
        value["session_mode"] = record["target"]["session_mode"]
    owner_held = record.get('policy_outcome', {}).get('state') in ('held', 'retired')
    unsupported = projection['basis'] == 'outside_supported_calendar'
    harness = None
    if monitored and record.get('target', {}).get('session_mode'):
        from .wake_mode_runtime import registration_harness_readiness
        harness = registration_harness_readiness(root, record)
        value['harness'] = harness
    harness_held = harness is not None and harness['state'] != 'ready'
    armed = bool(monitored and not harness_held and not unanchored and not owner_held and not unsupported
                 and current_time.get('state') not in ('pending_time', 'missed_deadline')
                 and record['status'] in ('pending', 'firing'))
    value.update(projection, armed=armed,
        scheduling_status=('held_harness' if harness_held else 'held_owner_policy' if owner_held else 'unsupported_calendar' if unsupported else 'armed' if armed else 'retained_unmonitored' if not monitored
            else 'retained_pending_time' if record['status'] == 'pending' else record['status']),
        monitor=dict(ready=monitored, wake_root=str(root), required_schema=record['schema_version']),
        next_action=('Inspect harness readiness and original peer receipts; retain this wake and recheck after recovery.' if harness_held else
            'Choose a representable due time and delivery expiry within ISO calendar years1–9999.' if unsupported else
            'Inspect owner completion policy; this intent remains held or retired.' if owner_held else
            'Monitor owns this intent; inspect delivery separately.' if armed else
            'Enroll a compatible monitor for this exact wake root; then reconcile this retained ID, do not create a duplicate.'
            if not monitored else 'Inspect retained time/owner state; preserve the original origin and deadline.'))
    if getattr(args, "as_json", False):
        print(json.dumps(value, sort_keys=True))
    else:
        print(f"{record['id']} {path} state={record['time_recovery']['state']} reason={record['time_recovery']['reason']} recovery={recovery} requires_worker_schema={record['schema_version']}")
    return 0


def existing_receipt(args, root):
    root, content, predicate, fingerprint, key, lock = _request(args, root)
    with WakeLifecycleLock(root, "native-intent-" + lock):
        found = _existing(root, fingerprint, key)
        if found:
            return _receipt(args, found.record, found.path, True)
    return None


def retain(args, root):
    from .native_clock import snapshot
    root, content, predicate, fingerprint, key, lock = _request(args, root)
    with WakeLifecycleLock(root, "native-intent-" + lock):
        found = _existing(root, fingerprint, key)
        if found:
            return _receipt(args, found.record, found.path, True)
        clock = args._schedule_clock if hasattr(args, "_schedule_clock") else snapshot()
        version = EVENT_SCHEMA_VERSION if content['schedule'].get('observation_policy') == 'until_event_or_cancel' else SCHEMA_VERSION
        record = {"schema_version": version, "id": "wake_intent_" + uuid4().hex,
                  "created_at": "", "updated_at": "", "cwd": content["cwd"],
                  "target": content["target"], "predicate": predicate, "prompt": content["prompt"],
                  "status": "pending", "attempts": 0, "max_attempts": 3,
                  "ack_timeout_seconds": 30, "next_attempt_at": None,
                  "events": [{"at": None, "type": "intent_retained", "message": "Scheduling request retained independently of UTC precision"}],
                  "scheduling_intent": {"fingerprint": fingerprint, "idempotency_key": key,
                                        "canonical_root": str(root), "schedule": content["schedule"],
                                        "ttl_seconds": content["ttl_seconds"], "tolerance_seconds": content["tolerance_seconds"],
                                        "stop_at": content["stop_at"],
                                        "counter_anchor": clock.get("counter") if valid_counter(clock.get("counter")) else None,
                                        "utc_anchor": clock.get("utc") if valid_utc(clock.get("utc")) else None,
                                        "origin_state": "at_request" if valid_counter(clock.get("counter")) or valid_utc(clock.get("utc")) else "awaiting_qualified_clock"},
                  "time_recovery": {"state": "pending_time", "reason": "scheduling_time_unavailable",
                                    "alert": "Retained intent needs an active monitor to recover; no dispatch authorized"}}
        from .wake_policy import decorate, register_owner
        policy = content.get("wake_policy")
        decorate(record, policy, version)
        register_owner(root, policy)
        from .wake_policy import apply_owner_state
        apply_owner_state(root, record)
        _observe_event_match(record, clock)
        record['time_recovery'] = eligibility(record, clock)
        project_schedule(record)
        path = _save(root, record)
        return _receipt(args, record, path, False)


def valid_utc(value):
    return (isinstance(value, dict) and value.get("status") in {"network", "windows"}
            and isinstance(value.get("sources"), (tuple, list))
            and all(isinstance(x, str) and x for x in value["sources"])
            and len(set(value["sources"])) == len(value["sources"])
            and len(value["sources"]) >= (2 if value["status"] == "network" else 1)
            and all(type(value.get(key)) in (int, float) and math.isfinite(value[key]) for key in ("lower", "upper"))
            and 0 < value["lower"] <= value["upper"] and value["upper"] - value["lower"] <= 300)


def valid_counter(value):
    return (isinstance(value, dict) and isinstance(value.get("epoch"), str)
            and 0 < len(value["epoch"]) <= 200
            and all(type(value.get(key)) is int for key in ("counter", "frequency", "rate_ppm"))
            and 0 <= value["counter"] <= 18446744073709551615 and 0 < value["frequency"] <= 18446744073709551615
            and 0 <= value["rate_ppm"] <= 5000)


def valid_record(record):
    version = record.get('intent_schema_version') if record.get('schema_version') == 8 else record.get('schema_version')
    return version in (6, EVENT_SCHEMA_VERSION) and valid_scheduling_record(record, version, _valid_native_target)


def _valid_native_target(target):
    return (target['transport'] == 'native' and str(UUID(target['thread_id'])) == target['thread_id']
            and target.get('busy_policy', 'wait') in ('wait', 'queue')
            and target['endpoint'].startswith('unix://') and Path(target['codex_cmd']).is_absolute())


def valid_scheduling_record(record, version, target_validator):
    from .network_wakes import precise_deadline
    try:
        from .wake_policy import core_record
        record = core_record(record, version)
        intent = record["scheduling_intent"]
        schedule = intent["schedule"]
        target = record["target"]
        if (record.get("schema_version") != version or record["status"] not in {"pending", "firing", "submitted", "failed", "cancelled", "expired", "archived"}
                or not isinstance(record["id"], str) or not re.fullmatch(r'wake_intent_[0-9a-f]{32}', record['id'])
                or not isinstance(record.get('events'), list) or any(not isinstance(event, dict) for event in record['events'])
                or not isinstance(intent.get('fingerprint'), str) or not re.fullmatch(r'[0-9a-f]{64}', intent['fingerprint'])
                or intent.get('origin_state') not in {'at_request', 'awaiting_qualified_clock'}
                or type(record["attempts"]) is not int or record["attempts"] < 0
                or not isinstance(record["prompt"], str) or not record["prompt"].strip()
                or not target_validator(target)
                or not Path(intent["canonical_root"]).is_absolute()
                or type(intent["ttl_seconds"]) not in (int, float) or not math.isfinite(intent["ttl_seconds"]) or intent["ttl_seconds"] <= 0
                or type(intent["tolerance_seconds"]) not in (int, float) or not 0 < intent["tolerance_seconds"] <= 300
                or not isinstance(record["time_recovery"], dict)):
            return False
        if intent.get("counter_anchor") is not None and not valid_counter(intent["counter_anchor"]):
            return False
        if intent.get("utc_anchor") is not None and not valid_utc(intent["utc_anchor"]):
            return False
        if intent.get("stop_at") is not None:
            precise_deadline(intent["stop_at"])
        delivery = record.get('native_delivery' if version in (6, EVENT_SCHEMA_VERSION) else 'runtime_delivery')
        if delivery is not None:
            if not isinstance(delivery, dict) or delivery.get('state') not in {'uncertain', 'accepted'}:
                return False
            if str(UUID(delivery['submission_id'])) != delivery['submission_id']:
                return False
        if version == EVENT_SCHEMA_VERSION:
            if schedule.get('observation_policy') != 'until_event_or_cancel' or schedule.get('kind') != 'file':
                return False
            match = intent.get('event_match')
            if match is not None and (not isinstance(match, dict) or set(match) != {'utc_anchor', 'counter_anchor'}
                    or match['utc_anchor'] is not None and not valid_utc(match['utc_anchor'])
                    or match['counter_anchor'] is not None and not valid_counter(match['counter_anchor'])
                    or not (valid_utc(match['utc_anchor']) or valid_counter(match['counter_anchor']))):
                return False
        elif 'observation_policy' in schedule or 'event_match' in intent:
            return False
        if schedule["kind"] == "after":
            return type(schedule["delay_seconds"]) in (int, float) and math.isfinite(schedule["delay_seconds"]) and schedule["delay_seconds"] > 0
        if schedule["kind"] == "at":
            precise_deadline(schedule["due_at"])
            return True
        return schedule["kind"] == "file" and Path(schedule["path"]).is_absolute()
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def eligibility(record, clock):
    """Pure conservative bounds; never manufacture UTC from a counter."""
    intent = record["scheduling_intent"]
    schedule = intent["schedule"]
    kind = schedule["kind"]
    waiting_event = until_event(record) and intent.get('event_match') is None
    if until_event(record) and not waiting_event:
        intent = dict(intent, **intent['event_match'])
        kind = 'after'  # A durable match is not erased when a one-shot file disappears.
    origin = intent.get("counter_anchor")
    observed = clock.get("counter")
    delay = schedule.get("delay_seconds", 0)
    utc = clock.get("utc")
    result = {"state": "pending_time", "reason": clock.get("reason", "clock_unavailable"), "alert": "Trusted scheduling time unavailable; original intent retained"}
    stop_remaining = None
    if intent.get("stop_at"):
        if not valid_utc(utc):
            return dict(result, reason="absolute_stop_time_unavailable")
        from .network_wakes import precise_deadline
        stop = precise_deadline(intent["stop_at"]).timestamp()
        if utc["lower"] >= stop:
            return dict(result, state="missed_deadline", reason="stop_reached", alert="Monitoring stop reached; dispatch prohibited")
        if utc["upper"] >= stop:
            return dict(result, reason="stop_boundary_uncertain")
        stop_remaining = stop - utc["upper"]
    if waiting_event:
        exists = Path(schedule['path']).exists()
        return dict(result, state='pending_time' if exists else 'pending',
                    reason='event_match_time_unavailable' if exists else 'awaiting_event',
                    alert='Original match needs a qualified clock' if exists else None)
    if kind != 'at' and not valid_counter(origin) and not valid_utc(intent.get('utc_anchor')):
        return dict(result, reason='relative_origin_unanchored',
                    alert='Original relative origin unavailable; reconcile the original deadline before creating a replacement intent')
    continuous = (valid_counter(origin) and valid_counter(observed)
                  and observed['epoch'] == origin['epoch'] and observed['frequency'] == origin['frequency']
                  and observed['counter'] >= origin['counter'])
    if kind != "at" and valid_counter(origin) and valid_counter(observed) and not continuous:
        if not (valid_utc(utc) and valid_utc(intent.get('utc_anchor'))):
            return dict(result, reason="counter_continuity_lost", alert="Original relative clock continuity lost; no rebase or dispatch authorized")
    # A saved UTC origin lets recovered UTC qualify the original deadline even
    # when accumulated counter rate error no longer fits this wake's precision.
    if kind != "at" and continuous and not (valid_utc(utc) and valid_utc(intent.get('utc_anchor'))):
        delta = observed["counter"] - origin["counter"]
        rate = max(origin["rate_ppm"], observed["rate_ppm"]) / 1000000
        lower = max(0.0, math.nextafter((delta - 1) / (origin["frequency"] * (1 + rate)), -math.inf))
        upper = math.nextafter((delta + 1) / (origin["frequency"] * (1 - rate)), math.inf)
        due, expiry, mode = delay, delay + intent["ttl_seconds"], "host_counter"
    elif valid_utc(utc):
        lower, upper = utc.get("lower"), utc.get("upper")
        if not all(type(x) in (int, float) and math.isfinite(x) for x in (lower, upper)) or lower > upper:
            return dict(result, reason="invalid_utc_bounds")
        if kind == "at":
            from .network_wakes import precise_deadline
            due = precise_deadline(schedule["due_at"]).timestamp()
        else:
            anchor = intent.get("utc_anchor")
            if not isinstance(anchor, dict):
                return dict(result, reason="relative_origin_unanchored")
            due = anchor["upper"] + delay
        expiry, mode = due + intent["ttl_seconds"], "bounded_utc"
    else:
        return result
    base = {"state": "pending", "reason": "not_due", "alert": None, "mode": mode, "lower": lower, "upper": upper, "expires": expiry, "dispatch_window_seconds": min(expiry - upper, stop_remaining) if stop_remaining is not None else expiry - upper}
    if lower >= expiry:
        return dict(base, state="missed_deadline", reason="expiry_reached", alert="Wake deadline missed; original intent retained without dispatch")
    if upper >= expiry:
        return dict(base, state="pending_time", reason="expiry_boundary_uncertain", alert="Expiry eligibility uncertain; no dispatch authorized")
    if upper - lower > intent["tolerance_seconds"]:
        return dict(base, state="pending_time", reason="precision_unavailable", alert="Clock bounds exceed this request tolerance; intent retained")
    if lower < due or (kind == "file" and not Path(schedule["path"]).exists()):
        return base
    return dict(base, state="due", reason="not_before_and_expiry_established")


def evaluate(root, identifier, clock, *, record_validator=None):
    from .records import find_record, replace_record
    with WakeLifecycleLock(root, identifier):
        found = find_record(root, identifier)
        record = dict(found.record)
        if not (record_validator or valid_record)(record) or record["status"] != "pending" or record["scheduling_intent"]["canonical_root"] != str(Path(root).resolve()):
            return "pending"
        from .wake_policy import apply_owner_state
        try:
            from .wake_session_modes import apply_session_mode
            held = apply_session_mode(record) or apply_owner_state(root, record)
        except WakeError as exc:
            held = str(exc)
        if held:
            record["policy_outcome"] = dict(state="held" if record["status"] != "cancelled" else "retired", reason=held)
            _save(root, record)
            return record["status"]
        _observe_event_match(record, clock)
        verdict = eligibility(record, clock)
        project_schedule(record)
        previous = record["time_recovery"]
        record["time_recovery"] = verdict
        if any(previous.get(key) != verdict.get(key) for key in ("state", "reason", "mode")):
            record["events"] = list(record["events"]) + [{"at": None, "type": "time_recovery", "message": verdict["reason"]}]
        if verdict["state"] == "due":
            record["status"] = "firing"
        elif verdict["state"] == "missed_deadline":
            record["status"] = "failed"
        path = _save(root, record)
        if found.path != path:
            found.path.unlink(missing_ok=True)
        return record["status"]


def dispatch(root, found, clock_provider=None, *, runtime_adapter=None):
    from .records import find_record
    from .native_delivery import dispatch_native, reconcile_native
    from .native_clock import snapshot
    from .injector import DispatchResult
    provider = clock_provider or snapshot
    with WakeLifecycleLock(root, found.record["id"]):
        active = find_record(root, found.record["id"])
        record = active.record
        if (not valid_record(record) or record["status"] != "firing" or record != found.record
                or record["scheduling_intent"]["canonical_root"] != str(Path(root).resolve())):
            return DispatchResult("skipped", "native intent changed or root does not match")
        if record.get("native_delivery", {}).get("state") == "uncertain":
            from .permission_wake import common_record
            if common_record(record):
                return dispatch_native(root,active,None,clock_provider=provider,runtime_adapter=runtime_adapter)
            return reconcile_native(root, active, None, runtime_adapter=runtime_adapter)
        return dispatch_native(root, active, None, clock_provider=provider, runtime_adapter=runtime_adapter)


def dispatch_gate(record, clock):
    verdict = eligibility(record, clock)
    # Reserve the bounded queue handoff and runtime-read budget before admitting
    # an effect. This is elapsed/UTC eligibility, never a fabricated timestamp.
    if verdict["state"] == "due" and verdict["dispatch_window_seconds"] <= 35:
        return dict(verdict, state="pending_time", reason="dispatch_window_uncertain", alert="Insufficient bounded dispatch window before expiry")
    return verdict
