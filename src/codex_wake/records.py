from __future__ import annotations

import json
import math
import fcntl
import hashlib
import os
import subprocess
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from .signal_records import decode_signal_record, signal_journal_path
from .time_provider import NETWORK_TIME_POLICY


SCHEMA_VERSION = 1
NATIVE_SCHEMA_VERSION = 4
NATIVE_NETWORK_SCHEMA_VERSION = 5
SCHEMA_COMPATIBILITY = "additive_optional_fields"
SCHEMA_DOC = "docs/dev/wake-record-schema.md"
ACTIVE_STATUS_DIRS = ("pending", "firing", "submitted", "failed", "cancelled", "expired")
TERMINAL_STATUSES = {"submitted", "failed", "cancelled", "expired"}
VALID_STATUSES = set(ACTIVE_STATUS_DIRS) | {"archived"}
PREDICATE_TYPES = ("not_before", "file_exists", "file_changed", "process_done")
TARGET_TRANSPORTS = ("tmux", "native", "app-server", "openclaw_gateway")


class WakeError(ValueError):
    """Raised for invalid wake input."""


@dataclass(frozen=True)
class WakePath:
    path: Path
    record: dict[str, Any]


@dataclass(frozen=True)
class CleanupResult:
    path: Path
    wake_id: str
    retention_at: str
    deleted: bool


class WakeLifecycleLock:
    """Root/wake-scoped serialization for v2 terminal and dispatch decisions."""

    def __init__(self, root: Path, wake_id: str) -> None:
        digest = hashlib.sha256(wake_id.encode("utf-8")).hexdigest()[:24]
        self.path = Path(root) / "locks" / f"signal-lifecycle-{digest}.lock"
        self._handle = None

    def __enter__(self) -> WakeLifecycleLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="ascii")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


def classify_record(record: object) -> str:
    """Pure multi-version classification; unrecognized records are held."""

    if isinstance(record, dict) and record.get('schema_version') == 8:
        from .wake_policy import core_record
        try:
            version = record.get('intent_schema_version')
            if type(version) is not int or version not in (6, 7):
                return 'hold'
            return classify_record(core_record(record, version))
        except (WakeError, TypeError, KeyError):
            return 'hold'
    if isinstance(record, dict) and ('wake_policy' in record or 'intent_schema_version' in record):
        return 'hold'

    if (isinstance(record, dict) and isinstance(record.get('target'), dict)
            and record['target'].get('transport') == 'runtime' and record.get('schema_version') != 7):
        return 'hold'
    if isinstance(record, dict) and record.get('schema_version') == 7:
        from .runtime_wakes import valid_record
        return 'runtime_intent_v7' if valid_record(record) else 'hold'
    if isinstance(record, dict) and record.get('schema_version') == 6:
        from .native_intents import valid_record
        return 'native_intent_v6' if valid_record(record) else 'hold'
    if isinstance(record, dict) and record.get('schema_version') == NATIVE_NETWORK_SCHEMA_VERSION:
        if classify_record(dict(record, schema_version=NATIVE_SCHEMA_VERSION)) != 'v1':
            return 'hold'
        if record.get('time_policy') != NETWORK_TIME_POLICY:
            return 'hold'
        from .time_provider import TimeDecision, require_time_decision
        try:
            observed = record['time_observation']
            if not isinstance(observed['sources'], (list, tuple)):
                return 'hold'
            require_time_decision(TimeDecision(observed['status'], tuple(observed['sources']),
                                              observed['lower'], observed['upper']))
        except (KeyError, TypeError, ValueError):
            return 'hold'
        return 'native_network_v5'
    if decode_signal_record(record) is not None:
        return "signal_v2"
    if not isinstance(record, dict) or record.get("schema_version") not in (SCHEMA_VERSION,3,NATIVE_SCHEMA_VERSION):
        return "hold"
    predicate = record.get("predicate")
    if isinstance(predicate, dict) and predicate.get("type") == "signal":
        return "hold"
    if not isinstance(record.get("id"), str) or not record.get("id"):
        return "hold"
    if not isinstance(record.get("status"), str) or record["status"] not in VALID_STATUSES:
        return "hold"
    target = record.get("target")
    if isinstance(target, dict) and target.get('transport') == 'native':
        if type(record.get('attempts')) is not int or record['attempts'] < 0:
            return "hold"
    if record.get("schema_version") == NATIVE_SCHEMA_VERSION:
        target = record.get("target")
        if (not isinstance(target, dict) or target.get("transport") != "native"
                or not isinstance(predicate, dict)
                or not isinstance(predicate.get("type"), str)
                or predicate["type"] not in {"not_before", "file_exists"}
                or not all(isinstance(target.get(key), str) and target[key]
                           for key in ("thread_id", "endpoint", "codex_cmd", "expires_at"))):
            return "hold"
        from uuid import UUID
        try:
            if str(UUID(target['thread_id'])) != target['thread_id']:
                return "hold"
            parse_timestamp(target['expires_at'])
            if not target['endpoint'].startswith('unix://') or not Path(target['codex_cmd']).is_absolute():
                return "hold"
            if predicate['type'] == 'not_before':
                if not isinstance(predicate.get('due_at'), str):
                    return "hold"
                parse_timestamp(predicate['due_at'])
            elif not isinstance(predicate.get('path'), str) or not Path(predicate['path']).is_absolute():
                return "hold"
        except (ValueError, KeyError, TypeError):
            return "hold"
        # Same basic predicate evaluation family; transport owns native effects.
        return "v1"
    if record.get("schema_version") == 3:
        if record.get("time_policy") != NETWORK_TIME_POLICY or not isinstance(predicate,dict) or predicate.get("type") != "not_before":
            return "hold"
        return "network_v3"
    return "v1"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def creation_utc_upper() -> float:
    """Qualified creation observation; unavailable time cannot authorize a new record."""
    from .measurements import TimeUnavailable, utc_time
    try:
        return utc_time()
    except TimeUnavailable:
        raise WakeError('stable_time_creation_unqualified') from None


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_duration(value: str) -> timedelta:
    text = value.strip().lower()
    if not text:
        raise WakeError("duration is required")
    pattern = re.compile(r"(\d+)([smhd])")
    pos = 0
    total = timedelta()
    for match in pattern.finditer(text):
        if match.start() != pos:
            raise WakeError(f"invalid duration: {value}")
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "s":
            total += timedelta(seconds=amount)
        elif unit == "m":
            total += timedelta(minutes=amount)
        elif unit == "h":
            total += timedelta(hours=amount)
        elif unit == "d":
            total += timedelta(days=amount)
        pos = match.end()
    if pos != len(text) or total <= timedelta():
        raise WakeError(f"invalid duration: {value}")
    return total


def parse_timestamp(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WakeError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise WakeError("timestamp must include a timezone offset or Z")
    return parsed.astimezone(UTC).replace(microsecond=0)


def parse_utc_timestamp(value: str) -> datetime:
    parsed = parse_timestamp(value)
    return parsed.astimezone(UTC).replace(microsecond=0)


def make_wake_id(now: datetime | None = None) -> str:
    current = now if now is not None else datetime.fromtimestamp(creation_utc_upper(), UTC)
    stamp = current.astimezone(UTC).strftime("%Y%m%d_%H%M%S")
    return f"wake_{stamp}_{secrets.token_hex(2)}"


def default_wake_root(cwd: Path | None = None) -> Path:
    base = cwd or Path.cwd()
    return base / ".codex" / "wake"


def normalize_prompt(parts: list[str]) -> str:
    cleaned = list(parts)
    if cleaned and cleaned[0] == "--":
        cleaned = cleaned[1:]
    prompt = " ".join(cleaned).strip()
    if not prompt:
        raise WakeError("prompt is required after --")
    return prompt


def _codex_client_candidates_for_ttys(ttys):
    matches = {tty: [] for tty in ttys}
    if not matches:
        return matches
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            tty = os.readlink(entry / "fd" / "0")
            if tty not in matches:
                continue
            command = (entry / "comm").read_text(encoding="utf-8").strip()
            if command != "codex":
                continue
            stat = (entry / "stat").read_text(encoding="utf-8").split()
            matches[tty].append((int(entry.name), int(stat[21])))
        except (FileNotFoundError, OSError, IndexError, ValueError):
            continue
    return matches


def codex_client_identities_for_ttys(ttys):
    """Observe unique native clients with one process census, without caching."""
    return {tty: rows[0] for tty, rows in _codex_client_candidates_for_ttys(ttys).items()
            if len(rows) == 1}


def codex_client_identity_for_tty(tty: str) -> tuple[int, int]:
    matches = _codex_client_candidates_for_ttys([tty])[tty]
    if len(matches) != 1:
        raise WakeError(f"expected one Codex client on {tty}, found {len(matches)}")
    return matches[0]


def _canonical_tmux_title(title: str) -> str:
    normalized = title.strip()
    if normalized and 0x2800 <= ord(normalized[0]) <= 0x28FF:
        normalized = normalized[1:].lstrip()
    return normalized.split(" | ", 1)[0].strip()


def resolve_tmux_thread_pane(socket: str, pane: str, thread_id: str) -> tuple[str, int, int]:
    from .app_server import read_app_server_thread_identity

    identity = read_app_server_thread_identity(thread_id)
    try:
        session_result = subprocess.run(
            ["tmux", "-S", socket, "display-message", "-p", "-t", pane, "#{session_id}"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WakeError(f"cannot inspect captured tmux session: {exc}") from exc
    session = session_result.stdout.strip()
    try:
        panes_result = subprocess.run(
            [
                "tmux", "-S", socket, "list-panes", "-s", "-t", session,
                "-F", "#{pane_id}\t#{pane_title}\t#{pane_current_path}\t#{pane_tty}",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WakeError(f"cannot enumerate captured tmux session: {exc}") from exc
    matches: list[tuple[str, str]] = []
    for line in panes_result.stdout.splitlines():
        fields = line.split("\t", 3)
        if (
            len(fields) == 4
            and fields[2] == identity["cwd"]
            and _canonical_tmux_title(fields[1]) == identity["name"]
        ):
            matches.append((fields[0], fields[3]))
    if len(matches) != 1:
        raise WakeError(f"expected one tmux pane for Codex thread {thread_id}, found {len(matches)}")
    selected_pane, tty = matches[0]
    client_pid, start_ticks = codex_client_identity_for_tty(tty)
    return selected_pane, client_pid, start_ticks


def capture_tmux_target(
    env: dict[str, str] | None = None,
    *,
    pane_resolver: Callable[[str, str, str], tuple[str, int, int]] | None = None,
) -> dict[str, Any]:
    source = env if env is not None else os.environ
    pane = source.get("TMUX_PANE")
    tmux_env = source.get("TMUX")
    if not pane:
        raise WakeError("TMUX_PANE is required to create a tmux-targeted wake")
    if not tmux_env:
        raise WakeError("TMUX is required to resolve the tmux socket")
    thread_id = source.get("CODEX_THREAD_ID") or source.get("CODEX_SESSION_ID")
    if not thread_id:
        raise WakeError(
            "CODEX_THREAD_ID or CODEX_SESSION_ID is required to create a session-aware tmux wake"
        )
    socket = tmux_env.split(",", 1)[0]
    if not socket:
        raise WakeError("TMUX did not contain a socket path")
    pane, client_pid, client_start_time_ticks = (pane_resolver or resolve_tmux_thread_pane)(
        socket, pane, thread_id
    )
    return {
        "transport": "tmux",
        "tmux_socket": socket,
        "pane": pane,
        "thread_id": thread_id,
        "client_pid": client_pid,
        "client_start_time_ticks": client_start_time_ticks,
    }


def _metadata_now(now: datetime | None) -> datetime | None:
    if now is not None:
        return now
    from . import measurements
    try:
        return measurements.datetime_now()
    except measurements.TimeUnavailable:
        return None


def _event_at(event_type: str, message: str, now: datetime | None) -> dict[str, Any]:
    event = {
        "at": None if now is None else format_utc(now),
        "type": event_type,
        "message": message,
    }
    if now is None:
        event['time_status'] = 'not_observed'
    return event


def make_event(event_type: str, message: str, now: datetime | None = None) -> dict[str, Any]:
    return _event_at(event_type, message, _metadata_now(now))


def append_event(
    record: dict[str, Any],
    event_type: str,
    message: str,
    now: datetime | None = None,
    **extra: Any,
) -> dict[str, Any]:
    updated = dict(record)
    event = dict(at=None, type=event_type, message=message) if record.get("schema_version") in (6, 7, 8) and now is None else make_event(event_type, message, now)
    event.update(extra)
    events = list(updated.get("events") or [])
    events.append(event)
    updated["events"] = events
    return updated


def build_record(
    *,
    predicate: dict[str, Any],
    prompt: str,
    cwd: Path,
    target: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now if now is not None else datetime.fromtimestamp(creation_utc_upper(), UTC)
    wake_id = make_wake_id(current)
    timestamp = format_utc(current)
    return {
        "schema_version": NATIVE_SCHEMA_VERSION if target.get("transport") == "native" else SCHEMA_VERSION,
        "id": wake_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "cwd": str(cwd.resolve()),
        "target": target,
        "predicate": predicate,
        "prompt": prompt,
        "status": "pending",
        "attempts": 0,
        "max_attempts": 3,
        "ack_timeout_seconds": 30,
        "next_attempt_at": predicate.get("due_at", timestamp),
        "events": [make_event("created", "Wake record created", current)],
    }


def schema_summary() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "read_versions": [1, 2, 3, 4, 5, 6, 7, 8],
        "policy_intent_write_version": 8,
        "runtime_intent_write_version": 8,
        "runtime_intent_base_version": 7,
        "native_intent_write_version": 8,
        "native_intent_base_version": 6,
        "native_network_write_version": NATIVE_NETWORK_SCHEMA_VERSION,
        "native_write_version": NATIVE_NETWORK_SCHEMA_VERSION,
        "legacy_native_write_version": NATIVE_SCHEMA_VERSION,
        "default_write_version": SCHEMA_VERSION,
        "signal_record_contract_version": 2,
        "signal_journal_schema_version": 2,
        "compatibility": SCHEMA_COMPATIBILITY,
        "schema_doc": SCHEMA_DOC,
        "active_statuses": list(ACTIVE_STATUS_DIRS[:2]),
        "terminal_statuses": sorted(TERMINAL_STATUSES),
        "archived_status": "archived",
        "predicate_types": list(PREDICATE_TYPES),
        "target_transports": list(TARGET_TRANSPORTS),
        "required_fields": [
            "schema_version",
            "id",
            "created_at",
            "updated_at",
            "cwd",
            "target",
            "predicate",
            "prompt",
            "status",
            "attempts",
            "max_attempts",
            "ack_timeout_seconds",
            "next_attempt_at",
            "events",
        ],
        "optional_fields": [
            "context_paths",
            "evidence_paths",
            "last_error",
            "previous_status",
            "archived_at",
            "dispatch_result",
            "route_selection",
            "visibility_result",
        ],
        "schema_bump_required_for": [
            "rename_or_remove_required_fields",
            "incompatible_field_meaning_change",
            "make_optional_field_required_for_existing_records",
            "incompatible_status_or_directory_change",
            "incompatible_target_transport_change",
            "incompatible_predicate_semantics_change",
        ],
    }


def ensure_runtime_dirs(root: Path) -> None:
    for name in ACTIVE_STATUS_DIRS + ("acks", "logs", "locks", "archive"):
        (root / name).mkdir(parents=True, exist_ok=True)


def write_record(root: Path, record: dict[str, Any]) -> Path:
    ensure_runtime_dirs(root)
    status = record.get("status")
    wake_id = record.get("id")
    if status not in VALID_STATUSES:
        raise WakeError(f"invalid wake status: {status}")
    if not isinstance(wake_id, str) or not wake_id:
        raise WakeError("wake record missing id")
    # Schema6/7 keep one atomic authority file across all active/terminal states.
    # Status is in the record, not inferred from its directory. This prevents a
    # crash between status-directory writes from reviving a pre-submission copy.
    target_dir = root / ("pending" if record.get('schema_version') in (6, 7, 8) else status)
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{wake_id}.json"
    temp_path = final_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(final_path)
    if record.get('schema_version') in (6, 7, 8):
        with final_path.open('rb') as stream:
            os.fsync(stream.fileno())
        for directory in (target_dir, root, root.parent):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    return final_path


def iter_records(root: Path) -> list[WakePath]:
    results: list[WakePath] = []
    for status in ACTIVE_STATUS_DIRS:
        directory = root / status
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            results.append(WakePath(path=path, record=record))
    return sorted(results, key=lambda item: (item.record.get("created_at", ""), item.record.get("id", "")))


def iter_archived_records(root: Path) -> list[WakePath]:
    archive_dir = root / "archive"
    results: list[WakePath] = []
    if not archive_dir.exists():
        return results
    for path in sorted(archive_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        results.append(WakePath(path=path, record=record))
    return sorted(results, key=lambda item: (item.record.get("archived_at") or "", item.record.get("id", "")))


def find_record(root: Path, wake_id: str) -> WakePath:
    for item in iter_records(root):
        if item.record.get("id") == wake_id:
            return item
    raise WakeError(f"wake not found: {wake_id}")


def all_records(root: Path, include_archive: bool = False) -> list[WakePath]:
    records = iter_records(root)
    if include_archive:
        records.extend(iter_archived_records(root))
    return sorted(records, key=lambda item: (item.record.get("created_at", ""), item.record.get("id", "")))


def status_summary(root: Path) -> dict[str, Any]:
    active_records = iter_records(root)
    archived_records = iter_archived_records(root)
    status_counts = {status: 0 for status in ACTIVE_STATUS_DIRS}
    status_counts["archived"] = 0
    predicate_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}
    visibility_counts: dict[str, int] = {}
    time_recovery_counts: dict[str, int] = {}
    time_recovery_alerts: list[dict[str, Any]] = []
    pending_next_attempts: list[str] = []

    for item in [*active_records, *archived_records]:
        record = item.record
        status = record.get("status")
        recovery = record.get('time_recovery')
        if record.get('schema_version') in (6, 7, 8) and isinstance(recovery, dict):
            state = recovery.get('state')
            if isinstance(state, str):
                time_recovery_counts[state] = time_recovery_counts.get(state, 0) + 1
            if recovery.get('alert') and status in {'pending', 'firing', 'failed'}:
                time_recovery_alerts.append({'id': record.get('id'), 'state': state,
                                             'reason': recovery.get('reason'), 'alert': recovery['alert']})
        if status == "archived":
            status_counts["archived"] += 1
        elif isinstance(status, str):
            status_counts[status] = status_counts.get(status, 0) + 1
        predicate = record.get("predicate")
        if isinstance(predicate, dict):
            predicate_type = predicate.get("type")
            if isinstance(predicate_type, str) and predicate_type:
                predicate_counts[predicate_type] = predicate_counts.get(predicate_type, 0) + 1
        target = record.get("target")
        if isinstance(target, dict):
            transport = target.get("transport")
            if isinstance(transport, str) and transport:
                target_counts[transport] = target_counts.get(transport, 0) + 1
        visibility = record.get("visibility_result")
        if isinstance(visibility, dict):
            classification = visibility.get("classification")
            if isinstance(classification, str) and classification:
                visibility_counts[classification] = visibility_counts.get(classification, 0) + 1
        if status in {"pending", "firing"}:
            next_attempt = record.get("next_attempt_at")
            if isinstance(next_attempt, str) and next_attempt:
                pending_next_attempts.append(next_attempt)

    active_total = status_counts.get("pending", 0) + status_counts.get("firing", 0)
    terminal_total = sum(status_counts.get(status, 0) for status in sorted(TERMINAL_STATUSES))
    archived_total = status_counts.get("archived", 0)
    return {
        "wake_root": str(root),
        "total": len(active_records) + len(archived_records),
        "active_total": active_total,
        "terminal_total": terminal_total,
        "archived_total": archived_total,
        "counts_by_status": status_counts,
        "counts_by_predicate": dict(sorted(predicate_counts.items())),
        "counts_by_target_transport": dict(sorted(target_counts.items())),
        "counts_by_visibility_classification": dict(sorted(visibility_counts.items())),
        "counts_by_time_recovery_state": dict(sorted(time_recovery_counts.items())),
        "time_recovery_alerts": time_recovery_alerts[:100],
        "time_recovery_alert_total": len(time_recovery_alerts),
        "earliest_next_attempt_at": min(pending_next_attempts) if pending_next_attempts else "",
    }


def cancel_record(
    root: Path,
    wake_id: str,
    now: datetime | None = None,
    *,
    checkpoint: Callable[[str], None] | None = None,
) -> Path:
    found = find_record(root, wake_id)
    if decode_signal_record(found.record) is not None or classify_record(found.record) in {"network_v3", "native_network_v5", "native_intent_v6", "runtime_intent_v7"}:
        with WakeLifecycleLock(root, wake_id):
            if checkpoint is not None:
                checkpoint("after_cancel_lock")
            return _cancel_found(root, find_record(root, wake_id), now, checkpoint)
    return _cancel_found(root, found, now, checkpoint)


def _cancel_found(
    root: Path,
    found: WakePath,
    now: datetime | None,
    checkpoint: Callable[[str], None] | None,
) -> Path:
    record = dict(found.record)
    status = record.get("status")
    if status in {"submitted", "failed", "cancelled", "expired", "archived"}:
        raise WakeError(f"cannot cancel wake in status {status}")
    network = classify_record(record) in {'network_v3', 'native_network_v5', 'native_intent_v6', 'runtime_intent_v7'}
    if network:
        current = None
    elif now is not None:
        current = now
    elif record.get('schema_version') in (1, 2, 4):
        from . import measurements
        try:
            current = measurements.datetime_now()
        except measurements.TimeUnavailable:
            # Stopping an authorized wake does not require a timestamp.
            current = None
    else:
        current = utc_now()
    record["status"] = "cancelled"
    if current is None and record.get('schema_version') == 2:
        # Schema2 requires a timestamp string. Retain the last observation,
        # explicitly excluding it as evidence of the cancellation's time.
        record['updated_at_time_status'] = 'not_observed'
    else:
        record["updated_at"] = None if current is None else format_utc(current)
        record.pop('updated_at_time_status', None)
    events = list(record.get("events") or [])
    events.append(dict(type='cancelled',message='Wake cancelled by operator',at=None,time_status='not_observed') if current is None else make_event("cancelled", "Wake cancelled by operator", current))
    record["events"] = events
    destination = write_record(root, record)
    if checkpoint is not None:
        checkpoint("after_cancel_replace")
    if found.path != destination and found.path.exists():
        found.path.unlink()
    if checkpoint is not None:
        checkpoint("after_cancel_source_unlink")
    _retire_signal_terminal(root, record, current)
    return destination


def move_record(
    root: Path,
    found: WakePath,
    status: str,
    *,
    event_type: str,
    message: str,
    now: datetime | None = None,
    last_error: str | None = None,
) -> Path:
    if status not in VALID_STATUSES:
        raise WakeError(f"invalid wake status: {status}")
    record = dict(found.record)
    untimed = record.get('schema_version') in (6, 7, 8) and now is None
    current = None if untimed else _metadata_now(now)
    if current is None and found.record.get('schema_version') == 2:
        # Schema2 still requires a timestamp. Do not publish an unreadable
        # record or change the separate signal terminal-fence contract.
        raise WakeError('signal_move_time_unqualified')
    record["status"] = status
    record["updated_at"] = None if current is None else format_utc(current)
    if last_error:
        record["last_error"] = last_error
    event = (dict(at=None, type=event_type, message=message)
             if untimed
             else _event_at(event_type, message, current))
    record['events'] = [*(record.get('events') or []), event]
    destination = write_record(root, record)
    if found.path != destination and found.path.exists():
        found.path.unlink()
    return destination


def replace_record(root: Path, found: WakePath, record: dict[str, Any]) -> Path:
    destination = write_record(root, record)
    if found.path != destination and found.path.exists():
        found.path.unlink()
    return destination


def _archive_time(schema,now):
    if schema in (6,7,8):
        return None,None  # Existing untimed native archival contract.
    if schema==3:
        from .network_wakes import creation_time,read_time
        decision=read_time()
        current=creation_time(decision)
        lower,upper=decision.lower,decision.upper
    elif now is not None:
        current=now  # Explicit trusted host clock seam.
        lower=upper=now.timestamp()
    else:
        from . import measurements
        try:
            lower,upper=measurements.utc_bounds()
        except measurements.TimeUnavailable:
            if schema in (1,4):
                return None,dict(basis='not_observed',lower=None,upper=None)
            raise WakeError('qualified_time_unavailable: archival requires qualified UTC') from None
        current=datetime.fromtimestamp(upper,UTC)
    return current,dict(basis='qualified_utc',lower=lower,upper=upper)


def archive_record(
    root: Path,
    wake_id: str,
    now: datetime | None = None,
    *,
    checkpoint: Callable[[str], None] | None = None,
) -> Path:
    found = find_record(root, wake_id)
    record = dict(found.record)
    status = record.get("status")
    if status not in TERMINAL_STATUSES:
        raise WakeError(f"cannot archive wake in status {status}")
    schema=record.get('schema_version')
    current,bounds=_archive_time(schema,now)
    record["previous_status"] = status
    record["status"] = "archived"
    record["archived_at"] = None if current is None else format_utc(current)
    record["updated_at"] = ("" if schema in (6,7,8) else None) if current is None else format_utc(current)
    if bounds is not None:record['archive_time_bounds']=bounds
    if current is None and schema not in (6,7,8):
        record['events']=[*(record.get('events') or []),dict(type='archived',message='Wake archived by operator',at=None,time_status='not_observed')]
    else:
        record = append_event(record, "archived", "Wake archived by operator", current)
    archive_dir = root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    final_path = archive_dir / f"{wake_id}.json"
    temp_path = final_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(final_path)
    if checkpoint is not None:
        checkpoint("after_archive_replace")
    if found.path.exists():
        found.path.unlink()
    _retire_signal_terminal(root, record, current)
    return final_path


def archive_terminal_records(root: Path, now: datetime | None = None) -> list[Path]:
    archived: list[Path] = []
    for item in list(iter_records(root)):
        wake_id = item.record.get("id")
        if item.record.get("status") in TERMINAL_STATUSES and isinstance(wake_id, str):
            archived.append(archive_record(root, wake_id, now=now))
    return archived


def _archive_retention_upper(record):
    bounds=record.get('archive_time_bounds')
    if bounds is None and record.get('schema_version')==3 and isinstance(record.get('archived_at'),str) and record['archived_at']:
        # The legacy network writer stored an accepted upper bound, truncated
        # to whole seconds. Its next whole second remains conservative.
        return parse_utc_timestamp(record['archived_at']).timestamp()+1
    if (not isinstance(bounds,dict) or bounds.get('basis')!='qualified_utc'
            or any(type(bounds.get(key)) not in (int,float) or not math.isfinite(bounds[key])
                   for key in ('lower','upper')) or bounds['lower']>bounds['upper']):
        raise WakeError('archive_retention_time_unqualified: retain legacy or unknown-time archive for explicit reconciliation')
    return bounds['upper']


def _retention_candidates(items,older_than,now):
    seconds=Fraction(older_than.days*86400+older_than.seconds)+Fraction(older_than.microseconds,1000000)
    current=None if now is None else now.timestamp()
    candidates=[]
    for item in items:
        wake_id=item.record.get('id')
        text=retention_timestamp(item.record)
        if not isinstance(wake_id,str) or not wake_id or text is None:continue
        try:reference=parse_utc_timestamp(text)
        except WakeError:continue
        upper=_archive_retention_upper(item.record)
        if current is None:
            from . import measurements
            try:current=measurements.utc_bounds()[0]
            except measurements.TimeUnavailable:
                raise WakeError('qualified_time_unavailable: retention requires qualified UTC') from None
        cutoff=Fraction(current)-seconds
        if item.record.get('schema_version')==3:
            from .network_wakes import evaluation_time,read_time
            try:
                decision=read_time()
                evaluation_time(decision)
                cutoff=Fraction(decision.lower)-seconds
            except WakeError:
                raise WakeError('qualified_time_unavailable: network retention time unqualified') from None
        if Fraction(upper)<=cutoff:candidates.append((item,reference))
    return candidates


def cleanup_archived_records(
    root: Path,
    *,
    older_than: timedelta,
    now: datetime | None = None,
    delete: bool = False,
    checkpoint: Callable[[str], None] | None = None,
) -> list[CleanupResult]:
    if older_than <= timedelta():
        raise WakeError("older_than must be greater than zero")
    results: list[CleanupResult] = []
    # Complete time qualification before any deletion; unknown legacy data
    # cannot cause a partially applied batch before its gate is reported.
    for item,retention_at in _retention_candidates(iter_archived_records(root),older_than,now):
        wake_id = item.record.get("id")
        if decode_signal_record(item.record) is not None and not _signal_cleanup_allowed(root, item.record):
            continue
        if delete and item.path.exists():
            if checkpoint is not None:
                checkpoint("before_cleanup_unlink")
            item.path.unlink()
            if checkpoint is not None:
                checkpoint("after_cleanup_unlink")
        results.append(CleanupResult(path=item.path, wake_id=wake_id, retention_at=format_utc(retention_at), deleted=delete))
    return results


def protected_signal_cleanup_records(
    root: Path,
    *,
    older_than: timedelta,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """List old signal records held by lifecycle or retention protection."""

    if older_than <= timedelta():
        raise WakeError("older_than must be greater than zero")
    protected: list[dict[str, Any]] = []
    items=(item for item in iter_archived_records(root) if decode_signal_record(item.record) is not None)
    for item,retention_at in _retention_candidates(items,older_than,now):
        wake_id = item.record.get("id")
        detail = signal_cleanup_protection(root, item.record)
        if detail is None or detail.get("allowed"):
            continue
        protected.append(
            {
                "wake_id": wake_id,
                "path": str(item.path),
                "retention_at": format_utc(retention_at),
                "reasons": list(detail.get("reasons") or []),
                "repair": str(detail.get("repair") or ""),
            }
        )
    return protected


def _retire_signal_terminal(root: Path, record: dict[str, Any], now: datetime | None) -> None:
    if decode_signal_record(record) is None:
        return
    try:
        from .signal_store import SQLiteSignalModule

        runtime = SQLiteSignalModule.open_existing(signal_journal_path(root))
        if runtime is not None:
            runtime.retire_terminal_record(record, now=now)
    except Exception:
        return


def _signal_cleanup_allowed(root: Path, record: dict[str, Any]) -> bool:
    try:
        from .signal_store import SQLiteSignalModule

        runtime = SQLiteSignalModule.open_existing(signal_journal_path(root))
        return runtime is not None and runtime.cleanup_allowed(record)
    except Exception:
        return False


def signal_cleanup_protection(root: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    """Return actionable protection detail for an archived signal record."""

    if decode_signal_record(record) is None:
        return None
    try:
        from .signal_store import SQLiteSignalModule

        runtime = SQLiteSignalModule.open_existing(signal_journal_path(root))
        if runtime is None:
            return {
                "allowed": False,
                "reasons": ["journal_missing"],
                "repair": "preserve the record and restore its signal journal before cleanup",
            }
        return runtime.cleanup_diagnostic(record)
    except Exception:
        return {
            "allowed": False,
            "reasons": ["journal_unavailable"],
            "repair": "preserve the record and repair or restore the signal journal before cleanup",
        }


def retention_timestamp(record: dict[str, Any]) -> str | None:
    for key in ("archived_at", "updated_at", "created_at"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None
