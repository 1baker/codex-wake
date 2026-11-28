from __future__ import annotations

import os
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol

from . import measurements

from .records import (
    WakeError,
    WakePath,
    WakeLifecycleLock,
    append_event,
    format_utc,
    find_record,
    replace_record,
    codex_client_identity_for_tty,
)


DEFAULT_BACKOFF_SECONDS = (60, 300)


@dataclass(frozen=True)
class DispatchResult:
    status: str
    message: str


@dataclass(frozen=True)
class TmuxPane:
    pane: str
    title: str
    cwd: str
    client_pid: int
    client_start_time_ticks: int


class TmuxRunner(Protocol):
    def capture_pane(self, socket: str, pane: str) -> str:
        ...

    def paste_prompt(self, socket: str, pane: str, wake_id: str, prompt: str) -> None:
        ...

    def list_session_panes(self, socket: str, pane: str) -> list[TmuxPane]:
        ...


class SubprocessTmuxRunner:
    def capture_pane(self, socket: str, pane: str) -> str:
        result = subprocess.run(
            ["tmux", "-S", socket, "capture-pane", "-p", "-t", pane],
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout

    def paste_prompt(self, socket: str, pane: str, wake_id: str, prompt: str) -> None:
        buffer_name = f"codex-wake-{wake_id}"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(prompt)
            prompt_path = handle.name
        try:
            subprocess.run(
                ["tmux", "-S", socket, "load-buffer", "-b", buffer_name, prompt_path],
                check=True,
                text=True,
                capture_output=True,
            )
            subprocess.run(
                ["tmux", "-S", socket, "paste-buffer", "-p", "-d", "-b", buffer_name, "-t", pane],
                check=True,
                text=True,
                capture_output=True,
            )
            # Bracketed paste is one input event, rather than a stream that the
            # paste-burst detector can absorb together with the submit key.
            time.sleep(1.0)
            subprocess.run(
                ["tmux", "-S", socket, "send-keys", "-t", pane, "C-m"],
                check=True,
                text=True,
                capture_output=True,
            )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

    def list_session_panes(self, socket: str, pane: str) -> list[TmuxPane]:
        session = subprocess.run(
            ["tmux", "-S", socket, "display-message", "-p", "-t", pane, "#{session_id}"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        if not session:
            raise WakeError("tmux did not return a session id for the captured pane")
        result = subprocess.run(
            [
                "tmux", "-S", socket, "list-panes", "-s", "-t", session,
                "-F", "#{pane_id}\t#{pane_title}\t#{pane_current_path}\t#{pane_tty}",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        panes: list[TmuxPane] = []
        for line in result.stdout.splitlines():
            fields = line.split("\t", 3)
            if len(fields) != 4 or not all(fields):
                continue
            try:
                client_pid, start_ticks = codex_client_identity_for_tty(fields[3])
            except WakeError:
                continue
            panes.append(TmuxPane(fields[0], fields[1], fields[2], client_pid, start_ticks))
        return panes


def canonical_pane_title(title: str) -> str:
    normalized = title.strip()
    if normalized and 0x2800 <= ord(normalized[0]) <= 0x28FF:
        normalized = normalized[1:].lstrip()
    return normalized.split(" | ", 1)[0].strip()


def matching_thread_panes(
    panes: list[TmuxPane],
    identity: dict[str, str],
    *,
    client_pid: int,
    client_start_time_ticks: int,
) -> list[TmuxPane]:
    return [
        pane
        for pane in panes
        if pane.client_pid == client_pid
        and pane.client_start_time_ticks == client_start_time_ticks
        and pane.cwd == identity["cwd"]
        and canonical_pane_title(pane.title) == identity["name"]
    ]


def canonical_prompt(wake_id: str, wake_root: Path) -> str:
    return (
        f"WAKE_TRIGGER_ID={wake_id}\n"
        f"WAKE_TRIGGER_ROOT={wake_root.resolve()}\n"
        "Resume the scheduled wake task.\n"
    )


def wake_marker_present(text: str, wake_id: str) -> bool:
    return f"WAKE_TRIGGER_ID={wake_id}" in text


def pane_capture_summary(text: str, wake_id: str) -> dict[str, Any]:
    return {
        "line_count": len(text.splitlines()),
        "wake_marker_present": wake_marker_present(text, wake_id),
    }


def tmux_visibility_result(
    *,
    wake_id: str,
    pane: str,
    before_text: str,
    after_text: str | None,
    now: datetime,
    error: str | None = None,
) -> dict[str, Any]:
    before = pane_capture_summary(before_text, wake_id)
    result: dict[str, Any] = {
        "transport": "tmux",
        "pane": pane,
        "checked_at": format_utc(now),
        "privacy": "raw_pane_text_not_stored",
        "pre_capture": before,
    }
    if error:
        result["classification"] = "visibility_check_failed"
        result["error"] = error
        return result
    after = pane_capture_summary(after_text or "", wake_id)
    post_marker_new = bool(after["wake_marker_present"] and not before["wake_marker_present"])
    result["post_capture"] = after
    result["post_marker_new"] = post_marker_new
    if post_marker_new:
        result["classification"] = "visible_prompt_observed"
    else:
        result["classification"] = "ack_observed_visibility_unproven"
    return result


ACTIVE_PANE_LINE_LIMIT = 12


def active_pane_region(text: str) -> tuple[list[str], int, int]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    start = max(0, len(lines) - ACTIVE_PANE_LINE_LIMIT)
    return lines[start:], start, len(lines)


def classify_pane_safety(text: str) -> tuple[str, dict[str, Any]] | None:
    lines, _start, total_lines = active_pane_region(re.sub(r"(?:\x1b\[|\x9b)[0-9;:]*m", "", text))
    patterns = (
        (r"^\s*resume paused goal\?\s*$", "paused_goal_question", "paused goal prompt visible"),
        (r"^\s*approve(?: this)? command\?\s*$", "approval_question", "approval prompt visible"),
        (r"^\s*allow\b.*\bcommand\b.*\?\s*$", "command_permission_question", "command approval prompt visible"),
        (r"^\s*deny\b.*\ballow\b.*\?\s*$", "deny_allow_question", "confirmation prompt visible"),
        (r"\brunning\b.*\bcommand\b|\btool\b.*\brunning\b", "running_tool_status", "tool appears to be running"),
        (r"^\s*press enter to continue\s*$|^\s*continue\?\s*$", "continue_question", "confirmation prompt visible"),
    )
    for offset, line in enumerate(lines):
        lowered = line.lower()
        for pattern, rule_id, reason in patterns:
            if re.search(pattern, lowered):
                return reason, {
                    "rule_id": rule_id,
                    "region": "last_nonempty_lines",
                    "active_region_line_limit": ACTIVE_PANE_LINE_LIMIT,
                    "active_region_start_offset": _start,
                    "total_nonempty_line_count": total_lines,
                    "inspected_line_count": len(lines),
                    "matched_line_offset": offset,
                }
    if lines:
        last = lines[-1]
        if re.search(r"[$#%>]\s*$", last) and not any("codex" in line.lower() for line in lines):
            return "pane appears to be a shell prompt", {
                "rule_id": "foreign_shell_prompt",
                "region": "last_nonempty_lines",
                "active_region_line_limit": ACTIVE_PANE_LINE_LIMIT,
                "active_region_start_offset": _start,
                "total_nonempty_line_count": total_lines,
                "inspected_line_count": len(lines),
                "matched_line_offset": len(lines) - 1,
            }
    return None


def unsafe_pane_reason(text: str) -> str | None:
    classification = classify_pane_safety(text)
    return classification[0] if classification is not None else None


def lock_name_for_pane(socket: str, pane: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{socket}_{pane}").strip("_")
    return safe or "unknown-pane"


class PaneLock:
    def __init__(self, root: Path, socket: str, pane: str) -> None:
        self.path = root / "locks" / f"{lock_name_for_pane(socket, pane)}.lock"
        self.fd: int | None = None

    def __enter__(self) -> "PaneLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_stale_lock()
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise WakeError(f"pane lock already held: {self.path}") from exc
        os.write(self.fd, str(os.getpid()).encode("ascii"))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)

    def _remove_stale_lock(self) -> None:
        if not self.path.exists():
            return
        try:
            pid = int(self.path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            self.path.unlink(missing_ok=True)
            return
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self.path.unlink(missing_ok=True)
        except PermissionError:
            return


def ack_path(root: Path, wake_id: str) -> Path:
    return root / "acks" / f"{wake_id}.submitted"


def wait_for_ack(root: Path, wake_id: str, timeout_seconds: float) -> bool:
    """Advisory receipt polling; this is not trusted expiry evidence."""
    path = ack_path(root, wake_id)
    until = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if path.exists():
            return True
        remaining = until - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.1, remaining))


def target_from_record(record: dict) -> tuple[str, str]:
    target = record.get("target")
    if not isinstance(target, dict):
        raise WakeError("record target must be an object")
    if target.get("transport") != "tmux":
        raise WakeError(f"unsupported target transport: {target.get('transport')}")
    socket = target.get("tmux_socket")
    pane = target.get("pane")
    if not isinstance(socket, str) or not socket:
        raise WakeError("tmux target requires tmux_socket")
    if not isinstance(pane, str) or not pane:
        raise WakeError("tmux target requires pane")
    return socket, pane


def backoff_for_attempt(attempt: int) -> int:
    if attempt <= 1:
        return DEFAULT_BACKOFF_SECONDS[0]
    return DEFAULT_BACKOFF_SECONDS[min(attempt - 1, len(DEFAULT_BACKOFF_SECONDS) - 1)]


from .wake_control import guard_dispatch


@guard_dispatch
def dispatch_firing_record(
    root: Path,
    found: WakePath,
    *,
    runner: TmuxRunner | None = None,
    now: datetime | None = None,
    ack_timeout_override: float | None = None,
    app_server_codex_cmd: str | None = None,
    signal_authorizer: Callable[[dict[str, Any]], bool] | None = None,
    thread_identity_resolver: Callable[[str], dict[str, str]] | None = None,
    app_server_client: Any | None = None,
    time_provider=None,
    runtime_adapter=None,
) -> DispatchResult:
    record = found.record
    from .records import classify_record
    classification = classify_record(record)
    if classification == 'hold':
        return DispatchResult('skipped','unrecognized record; no dispatch authorized')
    if classification == 'runtime_intent_v7':
        from .runtime_wakes import dispatch
        return dispatch(root, found, time_provider=time_provider)
    if classification == 'native_intent_v6':
        from .native_intents import dispatch
        provider = None
        if time_provider is not None:
            from dataclasses import asdict
            provider = lambda: {'utc': asdict(time_provider()), 'counter': None}
        return dispatch(root, found, provider, runtime_adapter=runtime_adapter)
    network_current = None
    if classification == 'native_network_v5':
        from .network_wakes import read_time, evaluation_time, precise_deadline
        try:
            decision = read_time(time_provider)
            lower = evaluation_time(decision)
            predicate = record['predicate']
            due = predicate.get('due_at') if predicate['type'] == 'not_before' else None
            retry = record.get('next_attempt_at')
            uncertain = record.get('native_delivery', {}).get('state') == 'uncertain'
            if not uncertain and ((due and lower < precise_deadline(due))
                                  or (retry and lower < precise_deadline(retry))):
                return DispatchResult('skipped', 'native network deadline not established')
            expiry = precise_deadline(record['target']['expires_at']).timestamp()
            if not uncertain and decision.lower < expiry <= decision.upper:
                return DispatchResult('skipped', 'native expiry is uncertain')
            network_current = lower
        except WakeError:
            if record.get('native_delivery', {}).get('state') == 'uncertain':
                from .native_delivery import reconcile_native
                with WakeLifecycleLock(root, record['id']):
                    try:
                        active = find_record(root, record['id'])
                    except WakeError:
                        return DispatchResult('skipped', 'native record no longer active')
                    if active.record != record or active.record['status'] != 'firing':
                        return DispatchResult('skipped', 'native record changed during acquisition')
                    return reconcile_native(root, active, None, runtime_adapter=runtime_adapter)
            return DispatchResult('skipped', 'network time uncertain; no native submission authorized')
    if classification == 'network_v3':
        from .network_wakes import read_time, evaluation_time, creation_time, precise_deadline
        try:
            decision = read_time(time_provider)
            lower = evaluation_time(decision)
            if lower < precise_deadline(record['predicate']['due_at']) or lower < precise_deadline(record.get('next_attempt_at',record['predicate']['due_at'])):
                return DispatchResult('skipped','network deadline not established')
            network_current = creation_time(decision)
        except WakeError:
            return DispatchResult('skipped','network time uncertain; no dispatch authorized')
    wake_id = record.get("id")
    native = isinstance(record.get('target'), dict) and record['target'].get('transport') == 'native'
    if (record.get("schema_version") not in (2,3) and not native) or not isinstance(wake_id, str) or not wake_id:
        return _dispatch_firing_record_unlocked(
            root,
            found,
            runner=runner,
            now=now,
            ack_timeout_override=ack_timeout_override,
            app_server_codex_cmd=app_server_codex_cmd,
            signal_authorizer=signal_authorizer,
            thread_identity_resolver=thread_identity_resolver,
            app_server_client=app_server_client,
            runtime_adapter=runtime_adapter,
        )
    with WakeLifecycleLock(root, wake_id):
        try:
            reloaded = json.loads(found.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return DispatchResult("skipped", "signal firing record is no longer active")
        active = WakePath(found.path, reloaded)
        if reloaded.get("schema_version") != record.get("schema_version") or reloaded.get("status") != "firing" or classify_record(reloaded) == "hold":
            return DispatchResult("skipped", "signal firing record is no longer active")
        if classification == 'network_v3' and (reloaded.get('predicate') != record.get('predicate') or reloaded.get('next_attempt_at') != record.get('next_attempt_at')):
            return DispatchResult('skipped','network wake changed during acquisition')
        if classification == 'native_network_v5' and any(
                reloaded.get(key) != record.get(key) for key in
                ('predicate', 'target', 'next_attempt_at', 'time_policy', 'time_observation', 'native_delivery')):
            return DispatchResult('skipped', 'native wake changed during acquisition')
        return _dispatch_firing_record_unlocked(
            root,
            active,
            runner=runner,
            now=network_current or now,
            ack_timeout_override=ack_timeout_override,
            app_server_codex_cmd=app_server_codex_cmd,
            signal_authorizer=signal_authorizer,
            thread_identity_resolver=thread_identity_resolver,
            app_server_client=app_server_client,
            runtime_adapter=runtime_adapter,
            time_provider=time_provider,
        )


def _dispatch_firing_record_unlocked(
    root: Path,
    found: WakePath,
    *,
    runner: TmuxRunner | None = None,
    now: datetime | None = None,
    ack_timeout_override: float | None = None,
    app_server_codex_cmd: str | None = None,
    signal_authorizer: Callable[[dict[str, Any]], bool] | None = None,
    thread_identity_resolver: Callable[[str], dict[str, str]] | None = None,
    app_server_client: Any | None = None,
    runtime_adapter=None,
    time_provider=None,
) -> DispatchResult:
    record = dict(found.record)
    if record.get("status") != "firing":
        return DispatchResult("skipped", "record is not firing")
    wake_id = record.get("id")
    if not isinstance(wake_id, str) or not wake_id:
        raise WakeError("wake record missing id")
    if record.get('ack_wait_time_held') is True:
        # A paste may already have succeeded. Never start another wait/attempt
        # with a renewed deadline; only reconcile the durable receipt.
        if not ack_path(root, wake_id).exists():
            return DispatchResult('skipped', 'ack outcome unknown; prior wait held; no replay')
        record['status'] = 'submitted'
        record = append_event(record, 'ack_observed', 'Held wake submission ack observed', now)
        replace_record(root, found, record)
        return DispatchResult('submitted', 'ack observed after held wait')
    if now is not None:
        current = now
    else:
        try:
            target = record.get('target')
            if isinstance(target, dict) and target.get('transport') == 'native':
                from .records import parse_timestamp
                lower, upper = measurements.utc_bounds()
                current = datetime.fromtimestamp(upper, UTC)
                expiry = parse_timestamp(target['expires_at']).timestamp()
                # Metadata's rounded upper bound cannot prove expiration.
                if lower < expiry <= max(upper, current.timestamp()):
                    return DispatchResult('skipped', 'native expiry is uncertain')
            else:
                current = measurements.datetime_now()
        except measurements.TimeUnavailable:
            return DispatchResult('skipped', 'reliable UTC unavailable to this client; no dispatch authorized')
    if record.get("schema_version") == 2:
        authorized = False
        if signal_authorizer is not None:
            try:
                authorized = bool(signal_authorizer(record))
            except Exception:
                authorized = False
        else:
            try:
                from .signal_records import signal_journal_path
                from .signal_store import SQLiteSignalModule

                runtime = SQLiteSignalModule.open_existing(signal_journal_path(root))
                authorized = runtime is not None and runtime.authorize_firing_record(record)
            except Exception:
                authorized = False
        if not authorized:
            return DispatchResult("skipped", "signal firing authority unavailable")
        predicate = record.get("predicate")
        if isinstance(predicate, dict) and predicate.get("source") == "a2a.receipt":
            return DispatchResult("skipped", "A2A receipt delivery is unqualified")
    target = record.get("target")
    if isinstance(target, dict) and target.get('transport') == 'native':
        from .native_delivery import dispatch_native
        return dispatch_native(root, found, current, clock_provider=time_provider, runtime_adapter=runtime_adapter)
    if isinstance(target, dict) and target.get("transport") == "app-server":
        from .app_server import dispatch_app_server_record

        result = dispatch_app_server_record(
            root,
            found,
            client=app_server_client,
            default_codex_cmd=app_server_codex_cmd,
            now=current,
        )
        return DispatchResult(result.status, result.message)
    if isinstance(target, dict) and target.get("transport") == "openclaw_gateway":
        from .openclaw_gateway import dispatch_openclaw_gateway_record

        result = dispatch_openclaw_gateway_record(root, found, now=current)
        return DispatchResult(result.status, result.message)
    try:
        socket, pane = target_from_record(record)
    except WakeError as exc:
        record["last_error"] = str(exc)
        record["status"] = "failed"
        record = append_event(record, "failed", str(exc), current)
        replace_record(root, found, record)
        return DispatchResult("failed", str(exc))
    tmux = runner or SubprocessTmuxRunner()

    thread_id = target.get("thread_id") if isinstance(target, dict) else None
    if not isinstance(thread_id, str) or not thread_id:
        message = "tmux target missing durable Codex thread identity"
        record["status"] = "failed"
        record["updated_at"] = format_utc(current)
        record["last_error"] = message
        record["route_selection"] = {"outcome": "no_target", "captured_pane": pane}
        record = append_event(record, "route_unavailable", message, current, **record["route_selection"])
        replace_record(root, found, record)
        return DispatchResult("failed", message)
    if isinstance(thread_id, str) and thread_id:
        client_pid = target.get("client_pid")
        client_start_time_ticks = target.get("client_start_time_ticks")
        try:
            if not isinstance(client_pid, int) or not isinstance(client_start_time_ticks, int):
                raise WakeError("session-aware tmux target missing Codex client process identity")
            if thread_identity_resolver is None:
                from .app_server import read_app_server_thread_identity

                identity = read_app_server_thread_identity(thread_id, codex_cmd=app_server_codex_cmd)
            else:
                identity = thread_identity_resolver(thread_id)
            if identity.get("thread_id") != thread_id:
                raise WakeError("thread identity resolver returned a different thread")
            matches = matching_thread_panes(
                tmux.list_session_panes(socket, pane),
                identity,
                client_pid=client_pid,
                client_start_time_ticks=client_start_time_ticks,
            )
        except (WakeError, OSError, subprocess.SubprocessError) as exc:
            matches = []
            resolution_error = str(exc)
        else:
            resolution_error = ""
        if len(matches) > 1:
            message = f"ambiguous tmux thread match: {len(matches)} panes"
            record["status"] = "failed"
            record["updated_at"] = format_utc(current)
            record["last_error"] = message
            record["route_selection"] = {
                "outcome": "ambiguous_match",
                "thread_id": thread_id,
                "candidate_panes": [item.pane for item in matches],
            }
            record = append_event(record, "route_ambiguous", message, current, **record["route_selection"])
            replace_record(root, found, record)
            return DispatchResult("failed", message)
        if len(matches) == 1:
            selected = matches[0].pane
            outcome = "original_pane" if selected == pane else "relocated_pane"
            record["route_selection"] = {
                "outcome": outcome,
                "thread_id": thread_id,
                "captured_pane": pane,
                "selected_pane": selected,
            }
            record = append_event(
                record,
                "route_selected",
                f"Selected {outcome.replace('_', ' ')} {selected}",
                current,
                **record["route_selection"],
            )
            replace_record(root, found, record)
            pane = selected
        else:
            fallback_target: dict[str, Any] = {
                "transport": "app-server",
                "endpoint": "stdio://",
                "thread_id": thread_id,
                "retry_active_writer": True,
            }
            record["target"] = fallback_target
            record["route_selection"] = {
                "outcome": "app_server_fallback",
                "thread_id": thread_id,
                "captured_pane": pane,
            }
            if resolution_error:
                record["route_selection"]["tmux_resolution_error"] = resolution_error
            record = append_event(
                record,
                "route_selected",
                "No exact tmux pane match; selected app-server fallback",
                current,
                **record["route_selection"],
            )
            fallback_found = WakePath(root / "firing" / f"{wake_id}.json", record)
            replace_record(root, found, record)
            from .app_server import dispatch_app_server_record

            result = dispatch_app_server_record(
                root,
                fallback_found,
                client=app_server_client,
                default_codex_cmd=app_server_codex_cmd,
                now=current,
            )
            if result.status == "failed":
                failed = find_record(root, wake_id)
                failed_record = dict(failed.record)
                failed_record["route_selection"] = {
                    **failed_record.get("route_selection", {}),
                    "outcome": "no_target",
                    "attempted_route": "app_server_fallback",
                }
                failed_record = append_event(
                    failed_record,
                    "route_unavailable",
                    "No exact tmux pane or eligible app-server target was available",
                    current,
                    **failed_record["route_selection"],
                )
                replace_record(root, failed, failed_record)
            return DispatchResult(result.status, result.message)

    try:
        with PaneLock(root, socket, pane):
            try:
                captured = tmux.capture_pane(socket, pane)
            except (WakeError, OSError, subprocess.SubprocessError):
                record["attempts"] = int(record.get("attempts") or 0) + 1
                raise
            unsafe = classify_pane_safety(captured)
            if unsafe:
                reason, evidence = unsafe
                return requeue_unsafe_pane(
                    root,
                    WakePath(root / "firing" / f"{wake_id}.json", record),
                    record,
                    f"unsafe pane: {reason}",
                    current,
                    evidence,
                )
            timeout = ack_timeout_override
            if timeout is None:
                timeout = float(record.get("ack_timeout_seconds") or 30)
            attempt = int(record.get("attempts") or 0) + 1
            record["attempts"] = attempt
            record["updated_at"] = format_utc(current)
            record = append_event(
                record,
                "dispatch_attempt",
                f"Pasting canonical wake prompt into tmux pane {pane}",
                current,
                attempt=attempt,
            )
            replace_record(root, found, record)
            tmux.paste_prompt(socket, pane, wake_id, canonical_prompt(wake_id, root))
            acknowledged = wait_for_ack(root, wake_id, timeout)
            if acknowledged:
                record["status"] = "submitted"
                record["updated_at"] = format_utc(current)
                record = append_event(record, "ack_observed", "Wake prompt submission ack observed", current)
                try:
                    post_ack_capture = tmux.capture_pane(socket, pane)
                except (WakeError, OSError, subprocess.SubprocessError) as exc:
                    visibility = tmux_visibility_result(
                        wake_id=wake_id,
                        pane=pane,
                        before_text=captured,
                        after_text=None,
                        now=current,
                        error=f"post-ack tmux capture failed: {exc}",
                    )
                    message = "Tmux pane visibility check failed after ack"
                else:
                    visibility = tmux_visibility_result(
                        wake_id=wake_id,
                        pane=pane,
                        before_text=captured,
                        after_text=post_ack_capture,
                        now=current,
                    )
                    message = f"Tmux pane visibility classified as {visibility['classification']}"
                record["visibility_result"] = visibility
                record = append_event(
                    record,
                    "tmux_visibility_checked",
                    message,
                    current,
                    visibility_result=visibility,
                )
                replace_record(root, WakePath(root / "firing" / f"{wake_id}.json", record), record)
                return DispatchResult("submitted", "ack observed")
            return requeue_or_fail(root, WakePath(root / "firing" / f"{wake_id}.json", record), record, "ack timeout", current, "ack_timeout")
    except WakeError as exc:
        return requeue_or_fail(root, found, record, str(exc), current, "failed")
    except (OSError, subprocess.SubprocessError) as exc:
        return requeue_or_fail(root, found, record, f"tmux dispatch failed: {exc}", current, "failed")


def requeue_unsafe_pane(
    root: Path,
    found: WakePath,
    record: dict,
    message: str,
    now: datetime,
    evidence: dict[str, Any],
) -> DispatchResult:
    deferrals = int(record.get("safety_deferrals") or 0) + 1
    max_deferrals = int(record.get("max_safety_deferrals") or 3)
    record["safety_deferrals"] = deferrals
    record["max_safety_deferrals"] = max_deferrals
    record["updated_at"] = format_utc(now)
    record["last_error"] = message
    record = append_event(
        record,
        "unsafe_pane",
        message,
        now,
        attempt=int(record.get("attempts") or 0),
        safety_deferral=deferrals,
        pane_safety=evidence,
    )
    if deferrals >= max_deferrals:
        record["status"] = "failed"
        record = append_event(
            record,
            "failed",
            "Maximum pane safety deferrals reached",
            now,
            attempt=int(record.get("attempts") or 0),
            safety_deferral=deferrals,
        )
        replace_record(root, found, record)
        return DispatchResult("failed", message)
    delay = backoff_for_attempt(deferrals)
    record["status"] = "pending"
    record["next_attempt_at"] = format_utc(now + timedelta(seconds=delay))
    record = append_event(
        record,
        "requeued",
        f"Wake requeued after {delay} seconds",
        now,
        attempt=int(record.get("attempts") or 0),
        safety_deferral=deferrals,
    )
    replace_record(root, found, record)
    return DispatchResult("requeued", message)


def requeue_or_fail(
    root: Path,
    found: WakePath,
    record: dict,
    message: str,
    now: datetime,
    event_type: str,
) -> DispatchResult:
    attempts = int(record.get("attempts") or 0)
    max_attempts = int(record.get("max_attempts") or 3)
    record["updated_at"] = format_utc(now)
    record["last_error"] = message
    record = append_event(record, event_type, message, now, attempt=attempts)
    if attempts >= max_attempts:
        record["status"] = "failed"
        record = append_event(record, "failed", "Maximum dispatch attempts reached", now, attempt=attempts)
        replace_record(root, found, record)
        return DispatchResult("failed", message)
    delay = backoff_for_attempt(attempts + 1)
    record["status"] = "pending"
    record["next_attempt_at"] = format_utc(now + timedelta(seconds=delay))
    record = append_event(record, "requeued", f"Wake requeued after {delay} seconds", now, attempt=attempts)
    replace_record(root, found, record)
    return DispatchResult("requeued", message)
