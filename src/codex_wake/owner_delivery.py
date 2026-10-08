"""Exact existing-TUI delivery; no new host, writer, or inference connection."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .records import WakeError, WakePath, append_event, format_utc, iter_records, parse_utc_timestamp, replace_record, utc_now

MAX_PAYLOAD_BYTES = 8192
MAX_SCAN_BYTES = 8 * 1024 * 1024
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
LIVE_STATES = {"sending", "pasted", "accepted"}


def completion_token(record: dict) -> str:
    return f"WAKE_DONE={record['id']}"


def payload_digest(prompt: str) -> str:
    if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise WakeError("inline wake payload must be at most 8192 UTF-8 bytes")
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def inline_prompt(record: dict) -> str:
    digest = payload_digest(record["prompt"])
    if completion_token(record) in record["prompt"]:
        raise WakeError("the completion token must not be echoed in the input payload")
    return (f"WAKE_TRIGGER_ID={record['id']}\nWAKE_PAYLOAD_SHA256={digest}\n"
            "WAKE_PAYLOAD_INCLUDED=1\n\n" + record["prompt"] +
            "\n\nWhen reporting the outcome, append the prefix WAKE_DONE= immediately followed by the value of WAKE_TRIGGER_ID to the final answer.\n")


def process_snapshot(pid: int) -> dict:
    try:
        base = Path(f"/proc/{pid}")
        if base.stat().st_uid != os.getuid():
            raise WakeError("owner process belongs to another user")
        fields = (base / "stat").read_text().rsplit(")", 1)[1].split()
        args = [s.decode() for s in (base / "cmdline").read_bytes().split(b"\0") if s]
        return {"ppid": int(fields[1]), "pgid": int(fields[2]), "tty": int(fields[4]),
                "tpgid": int(fields[5]), "start_ticks": int(fields[19]), "args": args}
    except (OSError, ValueError, UnicodeError, IndexError) as exc:
        raise WakeError("owner process metadata unavailable") from exc


def argument_value(args: list[str], flag: str) -> str | None:
    try:
        return args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def validate_process_snapshot(target: dict, snapshot: dict, *, pane_tty: int, ancestor_match: bool) -> None:
    args = snapshot["args"]
    if not args or Path(args[0]).name != "codex":
        raise WakeError("target is not the native Codex client")
    if argument_value(args, "resume") != target["owner_thread_id"]:
        raise WakeError("native client resume thread differs from wake owner")
    if argument_value(args, "--remote") != target["owner_remote"]:
        raise WakeError("native client's remote endpoint changed")
    if snapshot["start_ticks"] != target["owner_start_ticks"]:
        raise WakeError("owner PID lifetime changed")
    if not ancestor_match or snapshot["tty"] != pane_tty or pane_tty == 0:
        raise WakeError("owner process is not in the target pane terminal")
    if snapshot["tpgid"] != snapshot["pgid"]:
        raise WakeError("Codex is not the foreground process group")


def pane_metadata(target: dict) -> tuple[int, int]:
    try:
        result = subprocess.run(["tmux", "-S", target["tmux_socket"], "display-message", "-p", "-t", target["pane"],
            "#{pane_pid}\t#{pane_tty}"], check=True, text=True, capture_output=True, timeout=3)
        pid, tty = result.stdout.strip().split("\t")
        return int(pid), os.stat(tty).st_rdev
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise WakeError("target pane metadata unavailable") from exc


def verify_owner_target(target: dict) -> None:
    pane_pid, tty = pane_metadata(target)
    pid = target["owner_pid"]
    snap = process_snapshot(pid)
    parent = pid
    ancestors = set()
    for _ in range(64):
        if parent <= 1 or parent in ancestors:
            break
        ancestors.add(parent)
        if parent == pane_pid:
            break
        parent = process_snapshot(parent)["ppid"]
    validate_process_snapshot(target, snap, pane_tty=tty, ancestor_match=pane_pid in ancestors)
    try:
        if os.stat(f"/proc/{pid}/fd/0").st_rdev != tty:
            raise WakeError("owner stdin is not the pane terminal")
    except OSError as exc:
        raise WakeError("owner stdin terminal unavailable") from exc


def rollout_cursor(path: Path, thread_id: str) -> dict:
    try:
        with path.open("rb") as f:
            meta = json.loads(f.readline(MAX_SCAN_BYTES))
            st = os.fstat(f.fileno())
        if meta.get("type") != "session_meta" or meta.get("payload", {}).get("id") != thread_id:
            raise WakeError("rollout metadata does not match exact owner")
        return {"dev": st.st_dev, "ino": st.st_ino, "offset": st.st_size}
    except (OSError, ValueError) as exc:
        raise WakeError("exact-owner rollout metadata unavailable") from exc


def rollout_idle(path: Path) -> bool:
    """Require the latest bounded runtime lifecycle evidence to be terminal."""
    with path.open("rb") as f:
        size = os.fstat(f.fileno()).st_size
        offset = max(0, size - MAX_SCAN_BYTES)
        f.seek(offset)
        if offset:
            f.readline()  # discard a potentially partial first line
        latest = None
        for line in f.read(MAX_SCAN_BYTES).splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            p = e.get("payload", {})
            if e.get("type") == "event_msg" and p.get("type") in {"task_started", "task_complete", "turn_aborted"}:
                latest = p["type"]
        return latest in {"task_complete", "turn_aborted"}


def owner_pane_idle(text: str) -> bool:
    from .injector import unsafe_pane_reason
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    prompts = [i for i, line in enumerate(lines) if re.match(r"^\s*›(?:\s|$)", line)]
    if not prompts or unsafe_pane_reason(text):
        return False
    index = prompts[-1]
    tail = lines[index + 1:]
    known_shortcuts = (len(tail) == 2 and bool(re.fullmatch(
        r"\s*\? for shortcuts(?:\s+⚠\s+\d+ warnings? · f2 to view)?", tail[1])))
    return (lines[index].strip()[1:].strip() in {"", "Ask Codex to do anything"}
            and (len(tail) == 1 or known_shortcuts)
            and bool(re.search(r"context\s+\d+%\s+left|\d+%\s+context\s+left", tail[0], re.I)))


def capture_owner_target(target: dict, thread_id: str, pid: int) -> dict:
    if not UUID_PATTERN.fullmatch(thread_id):
        raise WakeError("owner mode requires an exact thread UUID")
    snap = process_snapshot(pid)
    remote = argument_value(snap["args"], "--remote")
    if not remote or not re.fullmatch(r"ws://127\.0\.0\.1:\d+", remote):
        raise WakeError("owner mode requires an existing loopback managed client")
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    matches = list((home / "sessions").glob(f"**/rollout-*-{thread_id}.jsonl"))
    if len(matches) != 1:
        raise WakeError("expected exactly one owner rollout")
    result = {**target, "owner_thread_id": thread_id, "owner_pid": pid,
              "owner_start_ticks": snap["start_ticks"], "owner_remote": remote,
              "rollout_path": str(matches[0].resolve())}
    verify_owner_target(result)
    rollout_cursor(matches[0], thread_id)
    return result


def store(root: Path, found: WakePath, record: dict, event: str, message: str, now: datetime) -> dict:
    record["updated_at"] = format_utc(now)
    record = append_event(record, event, message, now)
    replace_record(root, found, record)
    return record


def uncertain(root: Path, found: WakePath, record: dict, message: str, now: datetime) -> None:
    record["delivery"] = {**record.get("delivery", {}), "state": "uncertain"}
    record["status"] = "failed"
    record["last_error"] = message
    store(root, found, record, "delivery_uncertain", message, now)


def dispatch_owner_record(root: Path, found: WakePath, *, runner=None, now: datetime | None = None):
    from .injector import DispatchResult, PaneLock, SubprocessTmuxRunner, unsafe_pane_reason
    current = now or utc_now()
    r = dict(found.record)
    if r.get("delivery"):
        return DispatchResult("skipped", "owner delivery already attempted; reconcile only")
    idle_wait = r.get("idle_wait", {})
    if idle_wait and current > parse_utc_timestamp(idle_wait["deadline"]):
        r["status"] = "expired"; r["delivery"] = {"state": "not_sent"}
        store(root, found, r, "owner_idle_expired", "Idle wait expired; no prompt sent", current)
        return DispatchResult("failed", "idle wait expired")
    if idle_wait and current < parse_utc_timestamp(idle_wait["next_check_at"]):
        return DispatchResult("waiting", "waiting for idle check")
    t = r["target"]
    tmux = runner or SubprocessTmuxRunner()
    try:
        with PaneLock(root, t["tmux_socket"], t["pane"]):
            for other in iter_records(root):
                candidate = other.record
                if (candidate.get("id") != r["id"]
                        and candidate.get("status") in {"firing", "submitted"}
                        and candidate.get("target", {}).get("owner_thread_id") == t["owner_thread_id"]
                        and candidate.get("delivery", {}).get("state") in LIVE_STATES):
                    return DispatchResult("waiting", "another delivery to this owner is unresolved")
            verify_owner_target(t)
            capture = tmux.capture_pane(t["tmux_socket"], t["pane"])
            if not owner_pane_idle(capture) or not rollout_idle(Path(t["rollout_path"])):
                # No side effect yet: waiting for idle does not spend a delivery attempt.
                first = not idle_wait
                r["idle_wait"] = {"deadline": idle_wait.get("deadline", format_utc(current + timedelta(hours=3))),
                                  "next_check_at": format_utc(current + timedelta(seconds=5))}
                if first:
                    store(root, found, r, "owner_waiting_idle", "Exact owner is busy; no prompt sent", current)
                else:
                    replace_record(root, found, r)
                return DispatchResult("waiting", "waiting for exact owner to be idle")
            prompt = inline_prompt(r)
            cursor = rollout_cursor(Path(t["rollout_path"]), t["owner_thread_id"])
            r["attempts"] = int(r.get("attempts") or 0) + 1
            r["delivery"] = {"state": "sending", "monitor_pid": os.getpid(), "monitor_start_ticks": process_snapshot(os.getpid())["start_ticks"], "payload_sha256": payload_digest(r["prompt"]),
                "cursor": cursor, "accept_deadline": format_utc(current + timedelta(seconds=30)),
                "completion_deadline": format_utc(current + timedelta(hours=3))}
            r = store(root, found, r, "owner_sending", "Durable no-replay boundary before pane submission", current)
            found = WakePath(root / "firing" / f"{r['id']}.json", r)
            verify_owner_target(t)
            second = tmux.capture_pane(t["tmux_socket"], t["pane"])
            if not owner_pane_idle(second) or not rollout_idle(Path(t["rollout_path"])):
                r["delivery"]["state"] = "not_sent"
                r["status"] = "failed"
                store(root, found, r, "owner_not_sent", "Pane changed before paste; no prompt sent", current)
                return DispatchResult("failed", "pane changed before paste")
            tmux.paste_owner_prompt(t["tmux_socket"], t["pane"], r["id"], prompt)
            r["delivery"]["state"] = "pasted"
            store(root, found, r, "owner_pasted", "Paste attempted; exact rollout receipt still required", current)
            return DispatchResult("waiting", "paste attempted; reconcile without replay")
    except (WakeError, OSError, subprocess.SubprocessError) as exc:
        if r.get("delivery"):
            uncertain(root, found, r, str(exc), current)
        else:
            r["status"] = "failed"; r["last_error"] = str(exc)
            store(root, found, r, "owner_not_sent", str(exc), current)
        return DispatchResult("failed", str(exc))


def user_turn(event: dict, record: dict) -> str | None:
    payload = event.get("payload", {})
    if event.get("type") != "response_item" or payload.get("type") != "message" or payload.get("role") != "user":
        return None
    content = payload.get("content", [])
    text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") in {"input_text", "text"})
    if text.rstrip("\n") != inline_prompt(record).rstrip("\n"):
        return None
    turn = payload.get("internal_chat_message_metadata_passthrough", {}).get("turn_id")
    return turn if isinstance(turn, str) and turn else None


def reconcile_owner_record(root: Path, found: WakePath, *, now: datetime | None = None, monitor_pid: int | None = None,
                           runner=None) -> None:
    current = now or utc_now()
    r = dict(found.record)
    d = dict(r.get("delivery", {})); r["delivery"] = d
    visibility_retry = (d.get("state") == "completed" and d.get("completion_marker_in_answer")
                        and r.get("visibility_result", {}).get("classification") != "visible_response_observed"
                        and (not d.get("visibility_deadline") or current <= parse_utc_timestamp(d["visibility_deadline"])))
    if d.get("state") not in LIVE_STATES and not visibility_retry:
        return
    changed_monitor = d.get("monitor_pid") != (monitor_pid or os.getpid())
    if changed_monitor:
        try:
            original = process_snapshot(int(d["monitor_pid"]))
            live_original = d.get("monitor_start_ticks") in {None, original["start_ticks"]}
        except (WakeError, ValueError, KeyError):
            live_original = False
        if live_original:
            return  # A concurrent one-shot must not steal or fail a live monitor's record.
        if d["state"] in {"sending", "pasted"}:
            uncertain(root, found, r, "Monitor died after submission boundary; never resend", current)
            return
    try:
        cursor = dict(d["cursor"])
        path = Path(r["target"]["rollout_path"])
        with path.open("rb") as f:
            st = os.fstat(f.fileno())
            if (st.st_dev, st.st_ino) != (cursor["dev"], cursor["ino"]) or st.st_size < cursor["offset"]:
                raise WakeError("rollout inode changed or file was truncated")
            f.seek(cursor["offset"])
            scanned = 0
            while scanned < MAX_SCAN_BYTES:
                line = f.readline(MAX_SCAN_BYTES + 1)
                if not line or not line.endswith(b"\n"):
                    if len(line) > MAX_SCAN_BYTES:
                        raise WakeError("rollout event exceeds bounded reader size")
                    break
                event = json.loads(line)
                cursor["offset"] = f.tell(); scanned += len(line)
                if d["state"] in {"sending", "pasted"}:
                    turn = user_turn(event, r)
                    if turn:
                        d["state"] = "accepted"
                        r["status"] = "submitted"
                        r["dispatch_result"] = {"thread_id": r["target"]["owner_thread_id"], "turn_id": turn}
                        r = append_event(r, "turn_accepted", "Exact rollout user message matches wake and payload", current)
                        r["delivery"] = d
                p = event.get("payload", {})
                if d["state"] == "accepted" and event.get("type") == "event_msg" and p.get("turn_id") == r["dispatch_result"]["turn_id"]:
                    if p.get("type") in {"task_complete", "turn_aborted"}:
                        d["state"] = "completed" if p["type"] == "task_complete" else "interrupted"
                        d["finished_at"] = event.get("timestamp")
                        d["completion_marker_in_answer"] = completion_token(r) in str(p.get("last_agent_message", ""))
                        if d["state"] == "interrupted":
                            r["status"] = "failed"
                            d["abort_reason"] = p.get("reason")
                        r = append_event(r, "turn_" + d["state"], "Exact owner rollout terminal event observed", current)
                        r["delivery"] = d
                        break
        d["cursor"] = cursor
        deadline_key = "completion_deadline" if d["state"] == "accepted" else "accept_deadline"
        if d["state"] in LIVE_STATES and current > parse_utc_timestamp(d[deadline_key]):
            raise WakeError("owner delivery deadline elapsed; no replay permitted")
        if d["state"] == "completed" and d.get("completion_marker_in_answer"):
            d.setdefault("visibility_deadline", format_utc(current + timedelta(seconds=30)))
            from .injector import SubprocessTmuxRunner
            try:
                verify_owner_target(r["target"])
                pane = (runner or SubprocessTmuxRunner()).capture_pane(r["target"]["tmux_socket"], r["target"]["pane"])
                visible = completion_token(r) in pane
                r["visibility_result"] = {"classification": "visible_response_observed" if visible else "completion_visibility_unproven",
                    "pane": r["target"]["pane"], "checked_at": format_utc(current), "privacy": "raw_pane_text_not_stored"}
            except (WakeError, OSError, subprocess.SubprocessError):
                r["visibility_result"] = {"classification": "completion_visibility_unproven"}
        r["delivery"] = d
        r["updated_at"] = format_utc(current)
        replace_record(root, found, r)
    except (WakeError, OSError, ValueError, KeyError, TypeError) as exc:
        uncertain(root, found, r, str(exc), current)


def reconcile_owner_records(root: Path, *, now: datetime | None = None) -> None:
    for found in iter_records(root):
        if found.record.get("target", {}).get("owner_thread_id") and found.record.get("status") in {"firing", "submitted"}:
            reconcile_owner_record(root, found, now=now)
