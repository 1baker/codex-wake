from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .daemon import format_poll_result, poll_once, poll_result_has_activity
from .monitor import (
    health_is_recent,
    monitor_health_path,
    read_monitor_health,
    root_key,
    write_monitor_health,
)
from .records import WakeError, format_utc, utc_now
from .service import CommandRunner, read_log_tail, slugify, systemctl, systemd_quote, user_state_dir, user_systemd_dir


DEFAULT_SUPERVISOR_SERVICE = "codex-wake-supervisor.service"
DEFAULT_SUPERVISOR_INTERVAL = 1.0


@dataclass(frozen=True)
class SupervisorConfig:
    name: str
    interval: float
    codex_wake_path: Path
    unit_path: Path
    log_path: Path
    registry_dir: Path
    state_dir: Path


def user_config_dir(env: dict[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    base = source.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / "codex-wake"
    return Path.home() / ".config" / "codex-wake"


def default_registry_dir(env: dict[str, str] | None = None) -> Path:
    return user_config_dir(env) / "roots.d"


def default_supervisor_state_dir(env: dict[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    return user_state_dir(source) / "supervisor"


def resolve_codex_wake_path(raw: str | None = None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    found = shutil.which("codex-wake")
    if not found:
        invoked = Path(sys.argv[0]).expanduser()
        if invoked.exists():
            return invoked.resolve()
        raise WakeError("codex-wake was not found on PATH; install codex-wake first")
    return Path(found).resolve()


def build_supervisor_config(
    *,
    name: str | None = None,
    interval: float = DEFAULT_SUPERVISOR_INTERVAL,
    codex_wake_path: str | None = None,
    unit_dir: Path | None = None,
    log_path: Path | None = None,
    registry_dir: Path | None = None,
    state_dir: Path | None = None,
) -> SupervisorConfig:
    resolved_name = name or DEFAULT_SUPERVISOR_SERVICE
    if not resolved_name.endswith(".service"):
        resolved_name = f"{resolved_name}.service"
    if "/" in resolved_name:
        raise WakeError("supervisor service name must not contain '/'")
    if interval <= 0:
        raise WakeError("--interval must be greater than zero")
    resolved_state = (state_dir or default_supervisor_state_dir()).expanduser()
    resolved_registry = (registry_dir or default_registry_dir()).expanduser()
    resolved_log = (log_path or (user_state_dir() / "codex-wake-supervisor.log")).expanduser()
    return SupervisorConfig(
        name=resolved_name,
        interval=interval,
        codex_wake_path=resolve_codex_wake_path(codex_wake_path),
        unit_path=(unit_dir or user_systemd_dir()).expanduser() / resolved_name,
        log_path=resolved_log,
        registry_dir=resolved_registry,
        state_dir=resolved_state,
    )


def render_supervisor_unit(config: SupervisorConfig) -> str:
    return (
        "[Unit]\n"
        "Description=Codex Wake supervisor for registered wake roots\n"
        "Documentation=https://github.com/CochranResearchGroup/codex-wake\n"
        "After=default.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={systemd_quote(config.codex_wake_path)} supervisor run "
        f"--interval {config.interval:g} "
        f"--registry-dir {systemd_quote(config.registry_dir)} "
        f"--state-dir {systemd_quote(config.state_dir)}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        f"StandardOutput=append:{config.log_path}\n"
        f"StandardError=append:{config.log_path}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install_supervisor(config: SupervisorConfig, runner: CommandRunner | None = None, *, start: bool = True) -> None:
    config.unit_path.parent.mkdir(parents=True, exist_ok=True)
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    config.registry_dir.mkdir(parents=True, exist_ok=True)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.unit_path.write_text(render_supervisor_unit(config), encoding="utf-8")
    systemctl(["daemon-reload"], runner)
    if start:
        systemctl(["enable", "--now", config.name], runner)
        active = systemctl(["is-active", config.name], runner, check=False).stdout.strip()
        if active != "active":
            raise WakeError(f"supervisor service did not become active: {config.name} ({active or 'unknown'})")


def stop_supervisor(config: SupervisorConfig, runner: CommandRunner | None = None) -> None:
    systemctl(["disable", "--now", config.name], runner, check=False)


def uninstall_supervisor(config: SupervisorConfig, runner: CommandRunner | None = None) -> None:
    stop_supervisor(config, runner)
    config.unit_path.unlink(missing_ok=True)
    systemctl(["daemon-reload"], runner)


def supervisor_service_status(config: SupervisorConfig, runner: CommandRunner | None = None) -> tuple[str, str]:
    active = systemctl(["is-active", config.name], runner, check=False).stdout.strip() or "unknown"
    enabled = systemctl(["is-enabled", config.name], runner, check=False).stdout.strip() or "unknown"
    return active, enabled


def make_root_id(wake_root: Path, repo_root: Path | None = None) -> str:
    base = slugify((repo_root or wake_root).name)
    digest = hashlib.sha1(str(wake_root.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def registry_path(registry_dir: Path, root_id: str) -> Path:
    return registry_dir.expanduser() / f"{root_id}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def enroll_root(
    *,
    wake_root: Path,
    repo_root: Path | None = None,
    registry_dir: Path | None = None,
    root_id: str | None = None,
    enabled: bool = True,
    owner_kind: str = "repo",
    owner_name: str | None = None,
    codex_cmd: str | None = None,
    openclaw_cmd: str | None = None,
    now=None,
) -> Path:
    resolved_root = wake_root.expanduser().resolve()
    resolved_repo = (repo_root or resolved_root.parent.parent).expanduser().resolve()
    resolved_registry = (registry_dir or default_registry_dir()).expanduser()
    resolved_id = root_id or make_root_id(resolved_root, resolved_repo)
    if "/" in resolved_id:
        raise WakeError("root id must not contain '/'")
    timestamp = format_utc(now or utc_now())
    entry: dict[str, Any] = {
        "schema_version": 1,
        "root_id": resolved_id,
        "wake_root": str(resolved_root),
        "repo_root": str(resolved_repo),
        "enabled": bool(enabled),
        "created_at": timestamp,
        "updated_at": timestamp,
        "owner": {
            "kind": owner_kind,
            "name": owner_name or resolved_repo.name,
        },
        "dispatch": {},
    }
    if codex_cmd:
        entry["dispatch"]["codex_cmd"] = codex_cmd
    if openclaw_cmd:
        entry["dispatch"]["openclaw_cmd"] = openclaw_cmd
    path = registry_path(resolved_registry, resolved_id)
    _atomic_write_json(path, entry)
    return path


def load_registry_entry(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["_path"] = str(path)
    return payload


def iter_registry_entries(registry_dir: Path | None = None) -> list[dict[str, Any]]:
    directory = (registry_dir or default_registry_dir()).expanduser()
    if not directory.exists():
        return []
    entries = []
    for path in sorted(directory.glob("*.json")):
        entry = load_registry_entry(path)
        if entry:
            entries.append(entry)
    return entries


def find_registry_entry_for_root(wake_root: Path, registry_dir: Path | None = None) -> dict[str, Any] | None:
    resolved_root = str(wake_root.expanduser().resolve())
    for entry in iter_registry_entries(registry_dir):
        if entry.get("wake_root") == resolved_root:
            return entry
    return None


def unenroll_root(*, wake_root: Path | None = None, root_id: str | None = None, registry_dir: Path | None = None) -> Path:
    resolved_registry = (registry_dir or default_registry_dir()).expanduser()
    if bool(wake_root) == bool(root_id):
        raise WakeError("provide either --wake-root or --root-id")
    if root_id:
        path = registry_path(resolved_registry, root_id)
    else:
        entry = find_registry_entry_for_root(wake_root or Path(), resolved_registry)
        if not entry:
            raise WakeError(f"wake root is not enrolled: {(wake_root or Path()).expanduser().resolve()}")
        path = Path(str(entry["_path"]))
    path.unlink(missing_ok=False)
    return path


def entry_status(entry: dict[str, Any], *, state_dir: Path | None = None) -> dict[str, Any]:
    wake_root = Path(str(entry.get("wake_root") or "")).expanduser()
    monitor_dir = state_dir.parent / "monitors" if state_dir else None
    health = read_monitor_health(wake_root, monitor_dir)
    recent = health_is_recent(health)
    enabled = bool(entry.get("enabled", False))
    if recent:
        health_status = "ready"
        remediation = ""
    elif health:
        health_status = "stale"
        remediation = (
            "check codex-wake-supervisor.service, run `codex-wake supervisor run --once`, "
            f"or unenroll stale root with `codex-wake supervisor unenroll --root-id {entry.get('root_id', '')}`"
        )
    else:
        health_status = "missing"
        remediation = (
            "start the supervisor and run `codex-wake supervisor run --once`, "
            f"or unenroll obsolete root with `codex-wake supervisor unenroll --root-id {entry.get('root_id', '')}`"
        )
    if not enabled:
        remediation = f"enable this root registration or remove it with `codex-wake supervisor unenroll --root-id {entry.get('root_id', '')}`"
    return {
        "root_id": entry.get("root_id", ""),
        "wake_root": str(wake_root.resolve()) if str(wake_root) else "",
        "repo_root": entry.get("repo_root", ""),
        "enabled": enabled,
        "registry_path": entry.get("_path", ""),
        "health_path": str(monitor_health_path(wake_root, monitor_dir)),
        "health_recent": recent,
        "health_status": health_status,
        "health_source": str(health.get("source") or "") if health else "",
        "health_mode": str(health.get("mode") or "") if health else "",
        "health_checked_at": str(health.get("checked_at") or "") if health else "",
        "remediation": remediation,
    }


def supervisor_status(config: SupervisorConfig, runner: CommandRunner | None = None) -> dict[str, Any]:
    try:
        active, enabled = supervisor_service_status(config, runner)
    except Exception as exc:
        active, enabled = "unknown", f"unknown ({exc})"
    entries = iter_registry_entries(config.registry_dir)
    return {
        "service": {
            "name": config.name,
            "active": active,
            "enabled": enabled,
            "unit": str(config.unit_path),
            "log": str(config.log_path),
        },
        "registry_dir": str(config.registry_dir),
        "state_dir": str(config.state_dir),
        "root_count": len(entries),
        "roots": [entry_status(entry, state_dir=config.state_dir) for entry in entries],
    }


def supervisor_poll_once(config: SupervisorConfig, *, mode: str = "once", dispatch: bool = True) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    monitor_dir = config.state_dir.parent / "monitors"
    for entry in iter_registry_entries(config.registry_dir):
        if not entry.get("enabled", False):
            continue
        wake_root_text = entry.get("wake_root")
        if not isinstance(wake_root_text, str) or not wake_root_text:
            continue
        wake_root = Path(wake_root_text).expanduser().resolve()
        repo_root_text = entry.get("repo_root")
        repo_root = Path(repo_root_text).expanduser().resolve() if isinstance(repo_root_text, str) and repo_root_text else None
        try:
            result = poll_once(wake_root, dispatch=dispatch, allow_owner_dispatch=mode != "once")
            poll_summary = {
                "checked": result.checked,
                "fired": result.fired,
                "failed": result.failed,
                "pending": result.pending,
                "dispatched": result.dispatched,
                "submitted": result.submitted,
                "requeued": result.requeued,
            }
            health_path = write_monitor_health(
                wake_root=wake_root,
                repo_root=repo_root,
                source="supervisor",
                mode=mode,
                poll_result=poll_summary,
                state_dir=monitor_dir,
                extra={"root_id": entry.get("root_id", "")},
            )
            results.append(
                {
                    "root_id": entry.get("root_id", ""),
                    "wake_root": str(wake_root),
                    "ok": True,
                    "activity": poll_result_has_activity(result),
                    "result": poll_summary,
                    "summary": format_poll_result(result),
                    "health_path": str(health_path),
                }
            )
        except Exception as exc:
            write_monitor_health(
                wake_root=wake_root,
                repo_root=repo_root,
                source="supervisor",
                mode=mode,
                poll_result={},
                state_dir=monitor_dir,
                extra={"root_id": entry.get("root_id", ""), "last_error": str(exc)},
            )
            results.append(
                {
                    "root_id": entry.get("root_id", ""),
                    "wake_root": str(wake_root),
                    "ok": False,
                    "activity": True,
                    "error": str(exc),
                }
            )
    return results


def supervisor_run_loop(config: SupervisorConfig, *, once: bool = False, dispatch: bool = True) -> int:
    if once:
        results = supervisor_poll_once(config, mode="once", dispatch=dispatch)
        for item in results:
            if item.get("ok"):
                print(f"{item['root_id']} {item['summary']}")
            else:
                print(f"{item['root_id']} failed error={item.get('error', '')}")
        return 0
    while True:
        results = supervisor_poll_once(config, mode="loop", dispatch=dispatch)
        for item in results:
            if item.get("activity"):
                if item.get("ok"):
                    print(f"{item['root_id']} {item['summary']}", flush=True)
                else:
                    print(f"{item['root_id']} failed error={item.get('error', '')}", flush=True)
        time.sleep(config.interval)
