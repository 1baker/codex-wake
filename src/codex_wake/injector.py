from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .records import (
    WakeError,
    WakePath,
    append_event,
    format_utc,
    replace_record,
    utc_now,
)


DEFAULT_BACKOFF_SECONDS = (60, 300)


@dataclass(frozen=True)
class DispatchResult:
    status: str
    message: str


class TmuxRunner(Protocol):
    def capture_pane(self, socket: str, pane: str) -> str:
        ...

    def paste_prompt(self, socket: str, pane: str, wake_id: str, prompt: str) -> None:
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
                ["tmux", "-S", socket, "paste-buffer", "-d", "-b", buffer_name, "-t", pane],
                check=True,
                text=True,
                capture_output=True,
            )
            # Codex's tmux-hosted multiline composer needs the paste to settle,
            # then a blank-line submit for the two-line canonical prompt.
            time.sleep(0.2)
            subprocess.run(
                ["tmux", "-S", socket, "send-keys", "-t", pane, "C-m"],
                check=True,
                text=True,
                capture_output=True,
            )
            time.sleep(0.2)
            subprocess.run(
                ["tmux", "-S", socket, "send-keys", "-t", pane, "C-m"],
                check=True,
                text=True,
                capture_output=True,
            )
        finally:
            Path(prompt_path).unlink(missing_ok=True)


def canonical_prompt(wake_id: str) -> str:
    return f"WAKE_TRIGGER_ID={wake_id}\nResume the scheduled wake task.\n"


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


def unsafe_pane_reason(text: str) -> str | None:
    # A confirmed bottom composer separates live controls from transcript text.
    # Keep the conservative legacy checks when this UI shape is not recognized.
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    prompts = [i for i, line in enumerate(lines) if re.match(r"^\s*›(?:\s|$)", line)]
    if prompts:
        index = prompts[-1]
        tail = lines[index + 1:]
        footer = re.compile(r"\b(?:context\s+\d+%\s+left|\d+%\s+context\s+left)\b", re.I)
        if len(tail) == 1 and footer.search(tail[0]):
            recent = "\n".join(lines[max(0, index - 3):index]).lower()
            if re.search(r"esc to interrupt|esc to cancel", recent):
                return "agent appears to be running"
            composer = lines[index].strip()[1:].strip()
            if composer not in ("", "Ask Codex to do anything"):
                return "composer contains a draft or unrecognized prompt"
            return None
    lowered = text.lower()
    patterns = (
        (r"\bapprove\b|\bapproval\b", "approval prompt visible"),
        (r"\ballow\b.*\bcommand\b", "command approval prompt visible"),
        (r"\bdeny\b.*\ballow\b", "confirmation prompt visible"),
        (r"\brunning\b.*\bcommand\b|\btool\b.*\brunning\b", "tool appears to be running"),
        (r"\bpress enter to continue\b|\bcontinue\?\b", "confirmation prompt visible"),
    )
    for pattern, reason in patterns:
        if re.search(pattern, lowered, re.MULTILINE):
            return reason
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if lines:
        last = lines[-1]
        if re.search(r"[$#%>]\s*$", last) and "codex" not in lowered:
            return "pane appears to be a shell prompt"
    return None


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
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    path = ack_path(root, wake_id)
    while True:
        if path.exists():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.1, deadline - time.monotonic()))


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


def dispatch_firing_record(
    root: Path,
    found: WakePath,
    *,
    runner: TmuxRunner | None = None,
    now: datetime | None = None,
    ack_timeout_override: float | None = None,
) -> DispatchResult:
    current = now or utc_now()
    record = dict(found.record)
    if record.get("status") != "firing":
        return DispatchResult("skipped", "record is not firing")
    wake_id = record.get("id")
    if not isinstance(wake_id, str) or not wake_id:
        raise WakeError("wake record missing id")
    target = record.get("target")
    if isinstance(target, dict) and target.get("transport") == "app-server":
        from .app_server import dispatch_app_server_record

        result = dispatch_app_server_record(root, found, now=current)
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

    try:
        with PaneLock(root, socket, pane):
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
            captured = tmux.capture_pane(socket, pane)
            unsafe = unsafe_pane_reason(captured)
            if unsafe:
                return requeue_or_fail(root, WakePath(root / "firing" / f"{wake_id}.json", record), record, f"unsafe pane: {unsafe}", current, "unsafe_pane")
            tmux.paste_prompt(socket, pane, wake_id, canonical_prompt(wake_id))
            timeout = ack_timeout_override
            if timeout is None:
                timeout = float(record.get("ack_timeout_seconds") or 30)
            if wait_for_ack(root, wake_id, timeout):
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
