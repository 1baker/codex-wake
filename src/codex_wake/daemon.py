from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .records import (
    WakeError,
    WakePath,
    default_wake_root,
    iter_records,
    move_record,
    parse_utc_timestamp,
    utc_now,
)
from .injector import TmuxRunner, dispatch_firing_record
from .monitor import write_monitor_health
from .process import boot_id_value, process_exists, process_identity


@dataclass(frozen=True)
class PollResult:
    checked: int = 0
    fired: int = 0
    failed: int = 0
    pending: int = 0
    dispatched: int = 0
    requeued: int = 0
    submitted: int = 0


def format_poll_result(result: PollResult) -> str:
    return (
        f"checked={result.checked} fired={result.fired} "
        f"failed={result.failed} pending={result.pending} "
        f"dispatched={result.dispatched} submitted={result.submitted} requeued={result.requeued}"
    )


def poll_result_has_activity(result: PollResult) -> bool:
    return any(
        (
            result.checked,
            result.fired,
            result.failed,
            result.dispatched,
            result.submitted,
            result.requeued,
        )
    )


def poll_result_dict(result: PollResult) -> dict[str, int]:
    return {
        "checked": result.checked,
        "fired": result.fired,
        "failed": result.failed,
        "pending": result.pending,
        "dispatched": result.dispatched,
        "submitted": result.submitted,
        "requeued": result.requeued,
    }


def pending_records(root: Path) -> list[WakePath]:
    return [item for item in iter_records(root) if item.record.get("status") == "pending"]


def firing_records(root: Path) -> list[WakePath]:
    return [item for item in iter_records(root) if item.record.get("status") == "firing"]


def next_attempt_is_due(record: dict, now: datetime) -> tuple[bool, str]:
    next_attempt = record.get("next_attempt_at")
    if not isinstance(next_attempt, str) or not next_attempt:
        return True, ""
    try:
        due_at = parse_utc_timestamp(next_attempt)
    except WakeError:
        return True, ""
    if due_at > now:
        return False, next_attempt
    return True, next_attempt


def predicate_is_ready(record: dict, now: datetime) -> tuple[bool, str]:
    predicate = record.get("predicate")
    if not isinstance(predicate, dict):
        raise WakeError("predicate must be an object")
    predicate_type = predicate.get("type")
    if predicate_type == "not_before":
        due_at = predicate.get("due_at")
        if not isinstance(due_at, str) or not due_at:
            raise WakeError("not_before predicate requires due_at")
        return parse_utc_timestamp(due_at) <= now, f"not_before due_at {due_at} matched"
    if predicate_type == "file_exists":
        raw_path = predicate.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise WakeError("file_exists predicate requires path")
        path = resolve_record_path(record, raw_path, "file_exists")
        return path.exists(), f"file_exists path {path} matched"
    if predicate_type == "file_changed":
        raw_path = predicate.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise WakeError("file_changed predicate requires path")
        path = resolve_record_path(record, raw_path, "file_changed")
        try:
            stat = path.stat()
        except FileNotFoundError:
            return False, f"file_changed path {path} matched"
        registered_exists = bool(predicate.get("registered_exists"))
        registered_mtime_ns = predicate.get("registered_mtime_ns")
        registered_size = predicate.get("registered_size")
        if not registered_exists:
            return True, f"file_changed path {path} was created"
        if not isinstance(registered_mtime_ns, int) or not isinstance(registered_size, int):
            raise WakeError("file_changed predicate requires registered_mtime_ns and registered_size")
        changed = stat.st_mtime_ns != registered_mtime_ns or stat.st_size != registered_size
        return changed, f"file_changed path {path} changed"
    if predicate_type == "process_done":
        pid = predicate.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise WakeError("process_done predicate requires positive integer pid")
        if not process_exists(pid):
            return True, f"process_done pid {pid} exited"
        registered_boot_id = predicate.get("registered_boot_id")
        if registered_boot_id is not None and not isinstance(registered_boot_id, str):
            raise WakeError("process_done registered_boot_id must be a string when present")
        if registered_boot_id:
            current_boot_id = boot_id_value()
            if current_boot_id and current_boot_id != registered_boot_id:
                return True, f"process_done pid {pid} was from previous boot"
        registered_start_time_ticks = predicate.get("registered_start_time_ticks")
        if registered_start_time_ticks is None:
            return False, f"process_done pid {pid} still exists"
        if not isinstance(registered_start_time_ticks, int):
            raise WakeError("process_done registered_start_time_ticks must be an integer when present")
        current_identity = process_identity(pid)
        if current_identity is None:
            return False, f"process_done pid {pid} still exists; process identity unavailable"
        if current_identity.get("start_time_ticks") != registered_start_time_ticks:
            return True, f"process_done pid {pid} no longer matches registered process"
        return False, f"process_done pid {pid} still matches registered process"
    raise WakeError(f"unsupported predicate type: {predicate_type}")


def resolve_record_path(record: dict, raw_path: str, predicate_type: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    cwd = record.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise WakeError(f"relative {predicate_type} predicate requires record cwd")
    return Path(cwd) / path


def poll_once(
    root: Path,
    now: datetime | None = None,
    *,
    dispatch: bool = True,
    runner: TmuxRunner | None = None,
    ack_timeout_override: float | None = None,
    allow_owner_dispatch: bool = True,
) -> PollResult:
    current = now or utc_now()
    from .owner_delivery import reconcile_owner_records
    reconcile_owner_records(root, now=current)
    from .app_server import reconcile_app_server_records
    reconcile_app_server_records(root, now=current)
    checked = fired = failed = pending = dispatched = requeued = submitted = 0
    for item in pending_records(root):
        checked += 1
        due_for_attempt, _next_attempt = next_attempt_is_due(item.record, current)
        if not due_for_attempt:
            pending += 1
            continue
        try:
            ready, message = predicate_is_ready(item.record, current)
        except WakeError as exc:
            move_record(
                root,
                item,
                "failed",
                event_type="failed",
                message=str(exc),
                now=current,
                last_error=str(exc),
            )
            failed += 1
            continue
        if ready:
            move_record(
                root,
                item,
                "firing",
                event_type="predicate_matched",
                message=message,
                now=current,
            )
            fired += 1
        else:
            pending += 1
    if dispatch:
        for item in firing_records(root):
            if item.record.get("target", {}).get("owner_thread_id") and not allow_owner_dispatch:
                continue  # Exact-owner receipt tracking requires a persistent loop monitor.
            dispatched += 1
            result = dispatch_firing_record(
                root,
                item,
                runner=runner,
                now=current,
                ack_timeout_override=ack_timeout_override,
            )
            if result.status == "submitted":
                submitted += 1
            elif result.status == "requeued":
                requeued += 1
            elif result.status == "failed":
                failed += 1
    return PollResult(
        checked=checked,
        fired=fired,
        failed=failed,
        pending=pending,
        dispatched=dispatched,
        requeued=requeued,
        submitted=submitted,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-waked")
    parser.add_argument(
        "--wake-root",
        type=Path,
        default=None,
        help="wake runtime root; defaults to .codex/wake under the current directory",
    )
    parser.add_argument("--once", action="store_true", help="run one polling pass and exit")
    parser.add_argument("--interval", type=float, default=5.0, help="poll interval in seconds")
    parser.add_argument("--no-dispatch", action="store_true", help="evaluate predicates but do not dispatch firing records")
    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=None,
        help="override ack wait timeout in seconds",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = (args.wake_root or default_wake_root()).resolve()
    if args.once:
        result = poll_once(root, dispatch=not args.no_dispatch, ack_timeout_override=args.ack_timeout, allow_owner_dispatch=False)
        write_monitor_health(
            wake_root=root,
            repo_root=Path.cwd(),
            source="codex-waked",
            mode="once",
            poll_result=poll_result_dict(result),
        )
        print(format_poll_result(result))
        return 0
    if args.interval <= 0:
        raise WakeError("--interval must be greater than zero")
    while True:
        result = poll_once(root, dispatch=not args.no_dispatch, ack_timeout_override=args.ack_timeout)
        write_monitor_health(
            wake_root=root,
            repo_root=Path.cwd(),
            source="codex-waked",
            mode="loop",
            poll_result=poll_result_dict(result),
        )
        if poll_result_has_activity(result):
            print(format_poll_result(result), flush=True)
        time.sleep(args.interval)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except WakeError as exc:
        print(f"codex-waked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
