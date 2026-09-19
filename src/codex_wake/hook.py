from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


WAKE_ID_RE = re.compile(r"\bWAKE_TRIGGER_ID=([A-Za-z0-9_.:-]+)\b")


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_wake_id(prompt: str) -> str | None:
    match = WAKE_ID_RE.search(prompt)
    return match.group(1) if match else None


def wake_root_for_payload(payload: dict[str, Any]) -> Path:
    cwd = Path(payload.get("cwd") or ".").resolve()
    return cwd / ".codex" / "wake"


def monitored_wake_roots() -> list[Path]:
    """Return durable wake roots registered by local monitor health records."""
    state_dir = Path.home() / ".local" / "state" / "codex-wake" / "monitors"
    roots: list[Path] = []
    for health_path in sorted(state_dir.glob("*.json")):
        try:
            health = json.loads(health_path.read_text(encoding="utf-8"))
            root_value = health.get("wake_root") if isinstance(health, dict) else None
            root = Path(root_value).expanduser().resolve() if isinstance(root_value, str) and root_value else None
        except (OSError, json.JSONDecodeError):
            continue
        if root is not None and root not in roots:
            roots.append(root)
    return roots


def find_trigger_path(wake_root: Path, wake_id: str) -> Path | None:
    for status in ("firing", "pending", "submitted", "failed", "cancelled", "expired"):
        path = wake_root / status / f"{wake_id}.json"
        if path.exists():
            return path
    return None


def resolve_wake_root(payload: dict[str, Any], wake_id: str) -> Path:
    """Find the authoritative wake root even when a resumed TUI has another cwd."""
    payload_root = wake_root_for_payload(payload)
    if find_trigger_path(payload_root, wake_id) is not None:
        return payload_root
    for candidate in monitored_wake_roots():
        if find_trigger_path(candidate, wake_id) is not None:
            return candidate
    return payload_root


def write_ack(wake_root: Path, wake_id: str, payload: dict[str, Any]) -> Path:
    ack_path = wake_root / "acks" / f"{wake_id}.submitted"
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    ack = {
        "wake_id": wake_id,
        "submitted_at": utc_timestamp(),
        "turn_id": payload.get("turn_id"),
        "session_id": payload.get("session_id"),
    }
    ack_path.write_text(json.dumps(ack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ack_path


def additional_context_for_trigger(wake_id: str, trigger: dict[str, Any]) -> str:
    predicate = json.dumps(trigger.get("predicate"), indent=2, sort_keys=True)
    context_paths = trigger.get("context_paths") or []
    evidence_paths = trigger.get("evidence_paths") or []
    return (
        "A scheduled wake trigger fired.\n\n"
        f"Wake id: {wake_id}\n"
        f"Predicate:\n{predicate}\n\n"
        f"Original wake prompt:\n{trigger.get('prompt', '')}\n\n"
        f"Context paths: {json.dumps(context_paths, sort_keys=True)}\n"
        f"Evidence paths: {json.dumps(evidence_paths, sort_keys=True)}\n\n"
        "Before editing files, verify the predicate is still true and inspect any referenced logs, "
        "event files, context paths, or evidence paths. If the task is already complete, report that "
        "and stop."
    )


def missing_trigger_context(wake_id: str) -> str:
    return (
        f"Wake trigger {wake_id} was submitted, but its trigger file was not found. "
        "Inspect .codex/wake before continuing, and ask the user if the wake state is ambiguous."
    )


def hook_output(additional_context: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }


def handle_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    prompt = payload.get("prompt") or ""
    if not isinstance(prompt, str):
        return None
    wake_id = extract_wake_id(prompt)
    if not wake_id:
        return None
    wake_root = resolve_wake_root(payload, wake_id)
    write_ack(wake_root, wake_id, payload)
    trigger_path = find_trigger_path(wake_root, wake_id)
    if trigger_path is None:
        return hook_output(missing_trigger_context(wake_id))
    try:
        trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return hook_output(
            f"Wake trigger {wake_id} was submitted, but its trigger file is not valid JSON. "
            "Inspect .codex/wake before continuing."
        )
    return hook_output(additional_context_for_trigger(wake_id, trigger))


def main(argv: list[str] | None = None) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"codex-wake hook: invalid JSON input: {exc}", file=sys.stderr)
        return 2
    output = handle_payload(payload)
    if output is not None:
        print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
