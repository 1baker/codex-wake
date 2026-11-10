from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
SCHEMA_COMPATIBILITY = "additive_optional_fields"
SCHEMA_DOC = "docs/dev/wake-record-schema.md"
ACTIVE_STATUS_DIRS = ("pending", "firing", "submitted", "failed", "cancelled", "expired")
TERMINAL_STATUSES = {"submitted", "failed", "cancelled", "expired"}
VALID_STATUSES = set(ACTIVE_STATUS_DIRS) | {"archived"}
PREDICATE_TYPES = ("not_before", "file_exists", "file_changed", "process_done")
TARGET_TRANSPORTS = ("tmux", "app-server", "openclaw_gateway")


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


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


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
    current = now or utc_now()
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


def capture_tmux_target(env: dict[str, str] | None = None) -> dict[str, str]:
    source = env if env is not None else os.environ
    pane = source.get("TMUX_PANE")
    tmux_env = source.get("TMUX")
    if not pane:
        raise WakeError("TMUX_PANE is required to create a tmux-targeted wake")
    if not tmux_env:
        raise WakeError("TMUX is required to resolve the tmux socket")
    socket = tmux_env.split(",", 1)[0]
    if not socket:
        raise WakeError("TMUX did not contain a socket path")
    return {
        "transport": "tmux",
        "tmux_socket": socket,
        "pane": pane,
    }


def make_event(event_type: str, message: str, now: datetime | None = None) -> dict[str, Any]:
    return {
        "at": format_utc(now or utc_now()),
        "type": event_type,
        "message": message,
    }


def append_event(
    record: dict[str, Any],
    event_type: str,
    message: str,
    now: datetime | None = None,
    **extra: Any,
) -> dict[str, Any]:
    updated = dict(record)
    event = make_event(event_type, message, now)
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
    current = now or utc_now()
    wake_id = make_wake_id(current)
    timestamp = format_utc(current)
    return {
        "schema_version": SCHEMA_VERSION,
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
            "visibility_result",
            "busy_deadline_seconds",
            "first_dispatch_attempt_at",
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
    target_dir = root / status
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{wake_id}.json"
    temp_path = final_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(final_path)
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
            except json.JSONDecodeError:
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
        except json.JSONDecodeError:
            continue
        results.append(WakePath(path=path, record=record))
    return sorted(results, key=lambda item: (item.record.get("archived_at", ""), item.record.get("id", "")))


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
    pending_next_attempts: list[str] = []

    for item in [*active_records, *archived_records]:
        record = item.record
        status = record.get("status")
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
        "earliest_next_attempt_at": min(pending_next_attempts) if pending_next_attempts else "",
    }


def cancel_record(root: Path, wake_id: str, now: datetime | None = None) -> Path:
    found = find_record(root, wake_id)
    record = dict(found.record)
    status = record.get("status")
    if status in {"submitted", "failed", "cancelled", "expired", "archived"}:
        raise WakeError(f"cannot cancel wake in status {status}")
    current = now or utc_now()
    record["status"] = "cancelled"
    record["updated_at"] = format_utc(current)
    events = list(record.get("events") or [])
    events.append(make_event("cancelled", "Wake cancelled by operator", current))
    record["events"] = events
    destination = write_record(root, record)
    if found.path != destination and found.path.exists():
        found.path.unlink()
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
    current = now or utc_now()
    record = dict(found.record)
    record["status"] = status
    record["updated_at"] = format_utc(current)
    if last_error:
        record["last_error"] = last_error
    record = append_event(record, event_type, message, current)
    destination = write_record(root, record)
    if found.path != destination and found.path.exists():
        found.path.unlink()
    return destination


def replace_record(root: Path, found: WakePath, record: dict[str, Any]) -> Path:
    destination = write_record(root, record)
    if found.path != destination and found.path.exists():
        found.path.unlink()
    return destination


def archive_record(root: Path, wake_id: str, now: datetime | None = None) -> Path:
    found = find_record(root, wake_id)
    record = dict(found.record)
    status = record.get("status")
    if status not in TERMINAL_STATUSES:
        raise WakeError(f"cannot archive wake in status {status}")
    current = now or utc_now()
    record["previous_status"] = status
    record["status"] = "archived"
    record["archived_at"] = format_utc(current)
    record["updated_at"] = format_utc(current)
    record = append_event(record, "archived", "Wake archived by operator", current)
    archive_dir = root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    final_path = archive_dir / f"{wake_id}.json"
    temp_path = final_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(final_path)
    if found.path.exists():
        found.path.unlink()
    return final_path


def archive_terminal_records(root: Path, now: datetime | None = None) -> list[Path]:
    archived: list[Path] = []
    for item in list(iter_records(root)):
        wake_id = item.record.get("id")
        if item.record.get("status") in TERMINAL_STATUSES and isinstance(wake_id, str):
            archived.append(archive_record(root, wake_id, now=now))
    return archived


def cleanup_archived_records(
    root: Path,
    *,
    older_than: timedelta,
    now: datetime | None = None,
    delete: bool = False,
) -> list[CleanupResult]:
    if older_than <= timedelta():
        raise WakeError("older_than must be greater than zero")
    current = now or utc_now()
    cutoff = current - older_than
    results: list[CleanupResult] = []
    for item in iter_archived_records(root):
        wake_id = item.record.get("id")
        retention_text = retention_timestamp(item.record)
        if not isinstance(wake_id, str) or not wake_id or retention_text is None:
            continue
        try:
            retention_at = parse_utc_timestamp(retention_text)
        except WakeError:
            continue
        if retention_at > cutoff:
            continue
        if delete and item.path.exists():
            item.path.unlink()
        results.append(CleanupResult(path=item.path, wake_id=wake_id, retention_at=format_utc(retention_at), deleted=delete))
    return results


def retention_timestamp(record: dict[str, Any]) -> str | None:
    for key in ("archived_at", "updated_at", "created_at"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None
