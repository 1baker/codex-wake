from __future__ import annotations

import fcntl
import json
import os
import re
import select
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Protocol

from .injector import canonical_prompt
from .records import WakeError, WakePath, append_event, format_utc, replace_record, utc_now


APP_SERVER_BACKOFF_SECONDS = (60, 300)
APP_SERVER_CODEX_ENV = "CODEX_WAKE_CODEX_CMD"


class AppServerDeadline(WakeError):
    pass


def require_unowned_stdio(thread_id: str, *, codex_home: Path | None = None) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", thread_id):
        raise WakeError("invalid stdio thread identifier")
    home = codex_home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    lock = home / "thread-writer-locks" / f"{thread_id}.lock"
    try:
        descriptor = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        descriptor = None
    except OSError as exc:
        raise WakeError("writer ownership cannot be safely checked") from exc
    if descriptor is not None:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise WakeError("stdio refuses a thread with a live writer lock; use its existing TUI") from exc
        finally:
            os.close(descriptor)
    # Legacy native clients may not have the current lock file. Inspect only IDs.
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            if (proc / "comm").read_text().strip() != "codex":
                continue
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if b"resume" in args and args[args.index(b"resume") + 1] == thread_id.encode():
                raise WakeError("stdio refuses a thread owned by an existing Codex client")
        except (OSError, IndexError):
            continue


class AppServerClient(Protocol):
    def initialize(self) -> dict[str, Any]:
        ...

    def resume_thread(self, thread_id: str, cwd: str | None = None) -> dict[str, Any]:
        ...

    def read_thread(self, thread_id: str, include_turns: bool = False) -> dict[str, Any]:
        ...

    def start_turn(self, thread_id: str, prompt: str, cwd: str | None = None) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class AppServerDispatchResult:
    status: str
    message: str


@dataclass(frozen=True)
class AppServerThreadCandidate:
    thread_id: str
    cwd: str
    created_at: str
    updated_at: str
    path: str
    originator: str
    cli_version: str
    model_provider: str
    agent_nickname: str
    agent_role: str


def resolve_codex_cmd(
    raw: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    path: str | None = None,
    required: bool = False,
) -> str:
    source_env = env if env is not None else os.environ
    candidate = raw or source_env.get(APP_SERVER_CODEX_ENV) or ""
    if candidate:
        if "/" in candidate:
            resolved = Path(candidate).expanduser()
            if resolved.exists():
                return str(resolved.resolve())
            if required:
                raise WakeError(f"configured Codex CLI path does not exist: {candidate}")
            return ""
        found = shutil.which(candidate, path=path)
        if found:
            return str(Path(found).resolve())
        if required:
            raise WakeError(f"Codex CLI command not found: {candidate}")
        return ""
    found = shutil.which("codex", path=path)
    if found:
        return str(Path(found).resolve())
    if required:
        raise WakeError(
            "Codex CLI command not found: codex; configure "
            f"{APP_SERVER_CODEX_ENV} or reinstall the service with --codex-path"
        )
    return ""


def app_server_command(
    command: list[str] | None = None,
    *,
    codex_cmd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    if command:
        return list(command)
    source_env = env if env is not None else os.environ
    configured = codex_cmd or source_env.get(APP_SERVER_CODEX_ENV) or ""
    resolved = resolve_codex_cmd(codex_cmd, env=source_env, required=bool(configured))
    return [resolved or "codex", "app-server", "--listen", "stdio://"]


class StdioAppServerClient:
    def __init__(
        self,
        command: list[str] | None = None,
        *,
        codex_cmd: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.command = app_server_command(command, codex_cmd=codex_cmd)
        self.timeout_seconds = timeout_seconds
        self._lifetime_deadline = time.monotonic() + min(30.0, max(0.0, timeout_seconds))
        self._next_id = 1
        self._buffer = b""
        self._terminal_notifications: list[dict] = []
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise WakeError(
                f"app-server command not found: {self.command[0]}; configure "
                f"{APP_SERVER_CODEX_ENV} or reinstall the service with --codex-path"
            ) from exc
        # Drain stderr without retaining potentially private transcript/diagnostics.
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        if self.process.stderr is not None:
            try:
                while self.process.stderr.read(65536):
                    pass
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self._stderr_thread.join(timeout=1)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe is not None:
                pipe.close()

    def _receive(self, deadline: float) -> dict:
        deadline = min(deadline, self._lifetime_deadline)
        if self.process.stdout is None:
            raise WakeError("app-server stdout unavailable")
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppServerDeadline("app-server response deadline elapsed")
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                raise AppServerDeadline("app-server response deadline elapsed")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise WakeError("app-server closed stdout before confirmed response")
            self._buffer += chunk
            if len(self._buffer) > 16 * 1024 * 1024:
                raise WakeError("app-server response exceeds bounded reader size")
        line, self._buffer = self._buffer.split(b"\n", 1)
        try:
            message = json.loads(line)
        except ValueError as exc:
            raise WakeError("invalid app-server response JSON") from exc
        if not isinstance(message, dict):
            raise WakeError("invalid app-server response shape")
        return message

    def wait_for_turn(self, thread_id: str, turn_id: str, *, timeout_seconds: float = 30.0) -> dict:
        deadline = time.monotonic() + min(30.0, max(0.0, timeout_seconds))
        while True:
            message = self._terminal_notifications.pop(0) if self._terminal_notifications else self._receive(deadline)
            if message.get("method") != "turn/completed":
                continue
            params = message.get("params", {})
            turn = params.get("turn", {})
            if params.get("threadId") == thread_id and turn.get("id") == turn_id:
                if turn.get("status") not in {"completed", "interrupted", "failed"}:
                    raise WakeError("matching turn completed event has invalid terminal status")
                return turn

    def interrupt_for_deadline(self, thread_id: str, turn_id: str) -> dict:
        # Only the private stdio child is eligible, never a managed owner.
        self._lifetime_deadline = time.monotonic() + 2.0
        self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        return self.wait_for_turn(thread_id, turn_id, timeout_seconds=2.0)

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.process.stdin is None or self.process.stdout is None:
            raise WakeError("app-server stdio pipes are unavailable")
        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self.process.stdin.write((json.dumps(payload) + "\n").encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + min(30.0, max(0.0, self.timeout_seconds))
        while True:
            message = self._receive(deadline)
            if message.get("id") != request_id:
                if message.get("method") == "turn/completed":
                    if len(self._terminal_notifications) >= 64:
                        raise WakeError("too many unmatched terminal notifications")
                    self._terminal_notifications.append(message)
                continue
            if "error" in message:
                raise WakeError(f"app-server {method} failed: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise WakeError(f"app-server {method} returned non-object result")
            return result

    def initialize(self) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-wake",
                    "title": "Codex Wake",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )

    def resume_thread(self, thread_id: str, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id, "persistExtendedHistory": False}
        if cwd:
            params["cwd"] = cwd
        return self.request("thread/resume", params)

    def read_thread(self, thread_id: str, include_turns: bool = False) -> dict[str, Any]:
        return self.request("thread/read", {"threadId": thread_id, "includeTurns": include_turns})

    def start_turn(self, thread_id: str, prompt: str, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
        }
        if cwd:
            params["cwd"] = cwd
        return self.request("turn/start", params)


def app_server_target(record: dict[str, Any]) -> dict[str, Any]:
    target = record.get("target")
    if not isinstance(target, dict):
        raise WakeError("record target must be an object")
    if target.get("transport") != "app-server":
        raise WakeError(f"unsupported target transport: {target.get('transport')}")
    endpoint = target.get("endpoint", "stdio://")
    if endpoint != "stdio://":
        raise WakeError("only app-server stdio:// transport is implemented")
    thread_id = target.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise WakeError("app-server target requires thread_id")
    return target


def thread_status_from_response(response: dict[str, Any]) -> dict[str, Any]:
    thread = response.get("thread")
    if not isinstance(thread, dict):
        raise WakeError("app-server response missing thread")
    status = thread.get("status")
    if not isinstance(status, dict):
        raise WakeError("app-server thread response missing status")
    status_type = status.get("type")
    if not isinstance(status_type, str) or not status_type:
        raise WakeError("app-server thread status missing type")
    return status


def thread_summary_from_response(response: dict[str, Any]) -> dict[str, Any]:
    thread = response.get("thread")
    if not isinstance(thread, dict):
        raise WakeError("app-server response missing thread")
    status = thread_status_from_response(response)
    summary: dict[str, Any] = {
        "thread_id": thread.get("id", ""),
        "status": status,
        "status_type": status["type"],
    }
    active_flags = status.get("activeFlags")
    if isinstance(active_flags, list):
        summary["active_flags"] = active_flags
    for key in ("cwd", "sessionId", "updatedAt"):
        if key in thread:
            summary[key] = thread[key]
    return summary


def read_app_server_thread_status(
    thread_id: str,
    *,
    client: AppServerClient | None = None,
    resume: bool = False,
    cwd: str | None = None,
    codex_cmd: str | None = None,
) -> dict[str, Any]:
    app_client = client or StdioAppServerClient(codex_cmd=codex_cmd)
    try:
        app_client.initialize()
        if resume:
            response = app_client.resume_thread(thread_id, cwd=cwd)
        else:
            response = app_client.read_thread(thread_id)
        return thread_summary_from_response(response)
    finally:
        if client is None:
            app_client.close()


def discover_local_thread_candidates(
    *,
    codex_home: Path | None = None,
    limit: int = 20,
    cwd: Path | None = None,
) -> list[AppServerThreadCandidate]:
    if limit <= 0:
        raise WakeError("limit must be a positive integer")
    root = (codex_home or Path.home() / ".codex").expanduser()
    sessions_root = root / "sessions"
    if not sessions_root.exists():
        return []
    cwd_filter = str(cwd.resolve()) if cwd else None
    paths: list[Path] = []
    for dirpath, _, filenames in os.walk(sessions_root, followlinks=True):
        for filename in filenames:
            if filename.startswith("rollout-") and filename.endswith(".jsonl"):
                paths.append(Path(dirpath) / filename)
    paths.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    candidates: list[AppServerThreadCandidate] = []
    for path in paths:
        candidate = thread_candidate_from_rollout(path)
        if candidate is None:
            continue
        if cwd_filter and candidate.cwd != cwd_filter:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def thread_candidate_from_rollout(path: Path) -> AppServerThreadCandidate | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
        event = json.loads(first_line)
        stat = path.stat()
    except (OSError, IndexError, json.JSONDecodeError):
        return None
    if event.get("type") != "session_meta":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    thread_id = payload.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        cwd = ""
    return AppServerThreadCandidate(
        thread_id=thread_id,
        cwd=cwd,
        created_at=str(payload.get("timestamp") or event.get("timestamp") or ""),
        updated_at=format_utc(datetime.fromtimestamp(stat.st_mtime, tz=UTC)),
        path=str(path),
        originator=str(payload.get("originator") or ""),
        cli_version=str(payload.get("cli_version") or ""),
        model_provider=str(payload.get("model_provider") or ""),
        agent_nickname=str(payload.get("agent_nickname") or ""),
        agent_role=str(payload.get("agent_role") or ""),
    )


def app_server_backoff_for_attempt(attempt: int) -> int:
    if attempt <= 1:
        return APP_SERVER_BACKOFF_SECONDS[0]
    return APP_SERVER_BACKOFF_SECONDS[min(attempt - 1, len(APP_SERVER_BACKOFF_SECONDS) - 1)]


def requeue_app_server_record(
    root: Path,
    found: WakePath,
    record: dict[str, Any],
    message: str,
    now: datetime,
) -> AppServerDispatchResult:
    wake_id = record.get("id")
    if not isinstance(wake_id, str) or not wake_id:
        raise WakeError("wake record missing id")
    attempts = int(record.get("attempts") or 0)
    max_attempts = int(record.get("max_attempts") or 3)
    if attempts >= max_attempts:
        record["status"] = "failed"
        record["updated_at"] = format_utc(now)
        record["last_error"] = message
        record = append_event(record, "failed", message, now)
        replace_record(root, found, record)
        return AppServerDispatchResult("failed", message)
    next_attempt = now + timedelta(seconds=app_server_backoff_for_attempt(attempts))
    record["status"] = "pending"
    record["updated_at"] = format_utc(now)
    record["next_attempt_at"] = format_utc(next_attempt)
    record["last_error"] = message
    record = append_event(record, "requeued", message, now, next_attempt_at=record["next_attempt_at"])
    replace_record(root, found, record)
    return AppServerDispatchResult("requeued", message)


def dispatch_app_server_record(
    root: Path,
    found: WakePath,
    *,
    client: AppServerClient | None = None,
    now: datetime | None = None,
) -> AppServerDispatchResult:
    current = now or utc_now()
    record = dict(found.record)
    if record.get("status") != "firing":
        return AppServerDispatchResult("skipped", "record is not firing")
    wake_id = record.get("id")
    if not isinstance(wake_id, str) or not wake_id:
        raise WakeError("wake record missing id")
    if record.get("delivery", {}).get("state") in {"sending", "accepted", "uncertain"}:
        record["delivery"] = {**record["delivery"], "state": "uncertain"}
        record["status"] = "failed"
        record["last_error"] = "Recovered possibly submitted app-server delivery; no replay permitted"
        replace_record(root, found, record)
        return AppServerDispatchResult("failed", record["last_error"])
    try:
        target = app_server_target(record)
        thread_id = target["thread_id"]
        cwd = record.get("cwd") if isinstance(record.get("cwd"), str) else None
        attempt = int(record.get("attempts") or 0) + 1
        record["attempts"] = attempt
        record["updated_at"] = format_utc(current)
        record = append_event(
            record,
            "dispatch_attempt",
            "Starting app-server wake turn",
            current,
            thread_id=thread_id,
            endpoint=target.get("endpoint", "stdio://"),
        )
        replace_record(root, found, record)
        command = target.get("command")
        if command is not None and not isinstance(command, list):
            raise WakeError("app-server target command must be a list when provided")
        codex_cmd = target.get("codex_cmd")
        if codex_cmd is not None and not isinstance(codex_cmd, str):
            raise WakeError("app-server target codex_cmd must be a string when provided")
        require_unowned_stdio(thread_id)
        timeout = float(target.get("completion_timeout_seconds", 30.0))
        if not 0 < timeout <= 30:
            raise WakeError("stdio completion timeout must be greater than zero and at most 30 seconds")
        app_client = client or StdioAppServerClient(command=command, codex_cmd=codex_cmd, timeout_seconds=timeout)
        try:
            app_client.initialize()
            resume_result = app_client.resume_thread(thread_id, cwd=cwd)
            if resume_result.get("thread", {}).get("id") != thread_id:
                raise WakeError("app-server resumed a different thread")
            thread_status = thread_status_from_response(resume_result)
            record = dict(record)
            record["app_server_preflight"] = {
                "thread_id": thread_id,
                "status": thread_status,
            }
            record = append_event(
                record,
                "app_server_preflight",
                f"App-server thread status is {thread_status['type']}",
                current,
                thread_id=thread_id,
                status=thread_status,
            )
            replace_record(root, WakePath(root / "firing" / f"{wake_id}.json", record), record)
            if thread_status["type"] != "idle":
                message = f"app-server thread not idle: {thread_status['type']}"
                if thread_status["type"] == "active":
                    return requeue_app_server_record(
                        root,
                        WakePath(root / "firing" / f"{wake_id}.json", record),
                        record,
                        message,
                        current,
                    )
                raise WakeError(message)
            from .owner_delivery import process_snapshot
            monitor = {"monitor_pid": os.getpid(), "monitor_start_ticks": process_snapshot(os.getpid())["start_ticks"]}
            record["delivery"] = {"state": "sending", **monitor}
            replace_record(root, WakePath(root / "firing" / f"{wake_id}.json", record), record)
            if target.get("inline_payload"):
                from .owner_delivery import inline_prompt
                prompt = inline_prompt(record)
            else:
                prompt = canonical_prompt(wake_id)
            turn_result = app_client.start_turn(thread_id, prompt, cwd=cwd)
            metadata = app_server_dispatch_metadata(resume_result, turn_result)
            if not metadata.get("turn_id"):
                raise WakeError("app-server accepted response has no turn ID; delivery is uncertain")
            record["status"] = "submitted"
            record["dispatch_result"] = metadata
            record["delivery"] = {"state": "accepted", **monitor}
            record = append_event(record, "ack_observed", "App-server turn/start accepted wake prompt", current, **metadata)
            replace_record(root, WakePath(root / "firing" / f"{wake_id}.json", record), record)
            found = WakePath(root / "submitted" / f"{wake_id}.json", record)
            waiter = getattr(app_client, "wait_for_turn", None)
            if callable(waiter):
                try:
                    terminal = waiter(thread_id, metadata["turn_id"], timeout_seconds=timeout)
                except AppServerDeadline:
                    interrupter = getattr(app_client, "interrupt_for_deadline", None)
                    record["delivery"]["interrupt_requested_reason"] = "deadline"
                    if client is not None or not callable(interrupter):
                        raise
                    terminal = interrupter(thread_id, metadata["turn_id"])
                state = terminal.get("status")
                if state not in {"completed", "interrupted", "failed"}:
                    raise WakeError("invalid app-server terminal turn status")
                record["delivery"] = {**record["delivery"], "state": state, "finished_at": format_utc(utc_now())}
                if state != "completed":
                    record["status"] = "failed"
                record = append_event(record, "turn_" + state, "Matching app-server terminal turn event observed", utc_now())
                replace_record(root, found, record)
                return AppServerDispatchResult(record["status"], "matching turn " + state)
            return AppServerDispatchResult("submitted", "turn/start accepted; external client owns completion")
        finally:
            if client is None:
                app_client.close()
    except (WakeError, OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        if record.get("delivery", {}).get("state") in {"sending", "accepted"}:
            record["delivery"] = {**record["delivery"], "state": "uncertain"}
        record["status"] = "failed"
        record["updated_at"] = format_utc(current)
        record["last_error"] = str(exc)
        record = append_event(record, "failed", str(exc), current)
        replace_record(root, found, record)
        return AppServerDispatchResult("failed", str(exc))


def reconcile_app_server_records(root: Path, *, now: datetime | None = None) -> None:
    from .records import iter_records
    from .owner_delivery import process_snapshot
    current = now or utc_now()
    for found in iter_records(root):
        r = dict(found.record)
        d = dict(r.get("delivery", {}))
        if r.get("target", {}).get("transport") != "app-server" or d.get("state") != "accepted":
            continue
        try:
            live = process_snapshot(int(d["monitor_pid"]))["start_ticks"] == d["monitor_start_ticks"]
        except (WakeError, KeyError, ValueError):
            live = False
        if not live:
            r["delivery"] = {**d, "state": "uncertain"}
            r["status"] = "failed"
            r["last_error"] = "Stdio monitor died after acceptance; no replay permitted"
            r = append_event(r, "delivery_uncertain", r["last_error"], current)
            replace_record(root, found, r)


def app_server_dispatch_metadata(resume_result: dict[str, Any], turn_result: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    thread = resume_result.get("thread")
    if isinstance(thread, dict) and isinstance(thread.get("id"), str):
        metadata["thread_id"] = thread["id"]
    turn = turn_result.get("turn")
    if isinstance(turn, dict) and isinstance(turn.get("id"), str):
        metadata["turn_id"] = turn["id"]
    return metadata
