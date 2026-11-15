"""Explicit session modes; process loss is evidence, disconnection is not."""
import os
from .records import WakeError
from .process import boot_id_value, process_identity

SESSION_OBSERVATION_TIMEOUT = 15

MODES = ("session_only", "reopen_live", "background")
STARTUP = {"session_only": "active_tab", "reopen_live": "create_load_run", "background": "background_saved"}


def bind_mode(args, root, target):
    mode = getattr(args, "session_mode", None)
    if mode is None:
        return  # Legacy CLI policy contract; new agent registrations require mode.
    if mode not in MODES:
        raise WakeError("explicit_session_mode_required")
    expected = STARTUP[mode]
    selected = getattr(args, "recipient_startup", None)
    if selected is not None and selected != expected:
        raise WakeError("session_mode_startup_conflict")
    lifetime = getattr(args, "wake_lifetime", None)
    args.recipient_startup = expected
    args.wake_lifetime = lifetime or "persistent"
    target["session_mode"] = mode
    # Retry keeps the original binding; runtime restoration reads fresh settings.
    from .records import all_records
    key = getattr(args, "idempotency_key", None)
    for found in all_records(root, include_archive=True) if key else ():
        if found.record.get("scheduling_intent", {}).get("idempotency_key") == key:
            old = found.record.get("target", {})
            if old.get("session_mode") != mode:
                raise WakeError("idempotency_conflict: session mode differs")
            for field in ("session_owner", "session_origin", "tmux_socket"):
                if field in old:
                    target[field] = old[field]
            return
    from .sessions import observe
    try:
        snapshot = observe(endpoint=target["endpoint"], timeout=SESSION_OBSERVATION_TIMEOUT)
        rows = [row for row in snapshot.get("sessions", []) if row.get("thread_id") == target["thread_id"]]
        if not snapshot.get("complete") or len(rows) != 1 or rows[0].get("binding_status") != "metadata_matched" or len(rows[0].get("attachments", [])) != 1:
            raise WakeError("session_owner_unverified")
        attachment = rows[0]["attachments"][0]
        pid = attachment.get("client_pid")
        identity = process_identity(pid) if type(pid) is int and pid > 0 else None
        if not identity or identity["start_time_ticks"] != attachment.get("client_start_time_ticks"):
            raise WakeError("session_owner_unverified")
        origin = dict(pid=pid, identity=identity, pane_id=attachment.get("pane_id"), socket=attachment.get("socket"))
        target["session_origin"] = origin
        from pathlib import Path
        socket = attachment.get("socket")
        if isinstance(socket, str) and Path(socket).is_absolute():
            target["tmux_socket"] = socket
        if mode == "session_only":
            target["session_owner"] = origin
    except Exception as exc:
        if mode == "session_only":
            raise WakeError("session_owner_unverified") from exc


def session_state(target):
    if target.get("session_mode") != "session_only":
        return "continuing"
    owner = target.get("session_owner", {})
    identity = owner.get("identity", {})
    pid = owner.get("pid")
    if type(pid) is not int or pid <= 0 or not identity.get("boot_id"):
        return "unknown"
    boot = boot_id_value()
    if boot is None:
        return "unknown"
    if boot != identity["boot_id"]:
        return "closed"
    current = process_identity(pid)
    if current is not None:
        if current != identity:
            return "closed"
        socket = owner.get("socket")
        pane = owner.get("pane_id")
        if socket and pane:
            from pathlib import Path
            import subprocess
            try:
                Path(socket).stat()
                reply = subprocess.run(["tmux", "-S", socket, "list-panes", "-a", "-F", "#{pane_id}"],
                                       capture_output=True, text=True, timeout=5)
                if reply.returncode:
                    return "unknown"
                return "live" if pane in reply.stdout.splitlines() else "closed"
            except FileNotFoundError:
                # Only a missing pinned socket proves pane loss; a missing tmux
                # executable is an unavailable probe, not session completion.
                return "closed" if not Path(socket).exists() else "unknown"
            except (OSError, subprocess.SubprocessError):
                return "unknown"
        return "live"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "closed"
    except (PermissionError, OSError):
        pass
    return "unknown"


def apply_session_mode(record):
    if record.get("target", {}).get("session_mode") != "session_only":
        return None
    # An already admitted uncertain effect cannot be retracted or replayed.
    if record.get("native_delivery", {}).get("state") in ("uncertain", "accepted"):
        return None
    state = session_state(record["target"])
    if state == "closed":
        record["status"] = "cancelled"
        record["policy_outcome"] = dict(state="retired", reason="session_closed")
        return "session_closed"
    if state == "unknown":
        record["policy_outcome"] = dict(state="held", reason="session_owner_unverified")
        return "session_owner_unverified"
    return None
