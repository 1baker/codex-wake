from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import UTC
from pathlib import Path

from .app_server import discover_local_thread_candidates, read_app_server_thread_status, resolve_codex_cmd
from .hook_config import (
    DEFAULT_HOOK_COMMAND,
    HookSourceCheck,
    check_hook_config,
    check_hook_sources,
    check_user_hook_config,
    hook_review_note,
    hook_runtime_evidence,
    install_hook_config,
    install_user_hook_config,
)
from .openclaw_gateway import DEFAULT_GATEWAY_TIMEOUT_MS, DEFAULT_OPENCLAW_TIMEOUT_SECONDS, build_openclaw_gateway_target
from .openclaw_plugin import (
    DEFAULT_PLUGIN_REPO_URL,
    default_plugin_ref,
    install_openclaw_plugin,
    pack_openclaw_plugin,
    package_version,
)
from .product_readiness import product_readiness_summary
from .process import process_exists, process_identity
from .monitor import monitor_readiness, require_monitor_ready
from .records import (
    WakeError,
    all_records,
    archive_record,
    archive_terminal_records,
    build_record,
    cancel_record,
    cleanup_archived_records,
    capture_tmux_target,
    default_wake_root,
    find_record,
    format_utc,
    iter_records,
    normalize_prompt,
    parse_duration,
    parse_timestamp,
    schema_summary,
    status_summary,
    utc_now,
    write_record,
)
from .service import build_service_config, install_service, read_log_tail, service_status, stop_service, uninstall_service
from .service import service_app_server_readiness
from .supervisor import (
    build_supervisor_config,
    enroll_root,
    install_supervisor,
    stop_supervisor,
    supervisor_run_loop,
    supervisor_status,
    uninstall_supervisor,
    unenroll_root,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-wake")
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    parser.add_argument(
        "--wake-root",
        type=Path,
        default=None,
        help="wake runtime root; defaults to .codex/wake under the current directory",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    after = subparsers.add_parser("after", help="create a wake after a duration such as 45m or 1h30m")
    after.add_argument("duration")
    after.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(after)
    add_monitor_gate_options(after)
    add_retry_options(after)

    at = subparsers.add_parser("at", help="create a wake at an ISO-8601 timestamp with timezone")
    at.add_argument("timestamp")
    at.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(at)
    add_monitor_gate_options(at)

    app = subparsers.add_parser("app", help="create an app-server-targeted wake")
    app_subparsers = app.add_subparsers(dest="app_command", required=True)

    app_after = app_subparsers.add_parser("after", help="create an app-server wake after a duration")
    app_after.add_argument("--endpoint", default="stdio://", help="app-server endpoint; only stdio:// is currently implemented")
    app_after.add_argument("--codex-path", help="Codex CLI path or command for daemon-side app-server dispatch")
    add_monitor_gate_options(app_after)
    app_after.add_argument("thread_id")
    app_after.add_argument("duration")
    app_after.add_argument("prompt", nargs=argparse.REMAINDER)

    app_at = app_subparsers.add_parser("at", help="create an app-server wake at an ISO-8601 timestamp")
    app_at.add_argument("--endpoint", default="stdio://", help="app-server endpoint; only stdio:// is currently implemented")
    app_at.add_argument("--codex-path", help="Codex CLI path or command for daemon-side app-server dispatch")
    add_monitor_gate_options(app_at)
    app_at.add_argument("thread_id")
    app_at.add_argument("timestamp")
    app_at.add_argument("prompt", nargs=argparse.REMAINDER)

    app_status = app_subparsers.add_parser("status", help="read an app-server thread status without starting a turn")
    app_status.add_argument("--endpoint", default="stdio://", help="app-server endpoint; only stdio:// is currently implemented")
    app_status.add_argument("--codex-path", help="Codex CLI path or command to launch local stdio app-server")
    app_status.add_argument("--json", action="store_true", dest="as_json")
    app_status.add_argument("--resume", action="store_true", help="resume the thread before reading status; does not start a turn")
    app_status.add_argument("thread_id")

    app_candidates = app_subparsers.add_parser(
        "candidates",
        help="list local rollout-backed thread ids that can be checked with app status --resume",
    )
    app_candidates.add_argument("--codex-home", type=Path, default=None, help="Codex home to scan; defaults to ~/.codex")
    app_candidates.add_argument("--cwd", type=Path, default=None, help="only show candidates created for this working directory")
    app_candidates.add_argument("--limit", type=int, default=20, help="maximum candidates to print")
    app_candidates.add_argument("--validate", action="store_true", help="check each candidate with thread/resume without starting a turn")
    app_candidates.add_argument("--only-idle", action="store_true", help="with --validate, only print candidates whose resumed status is idle")
    app_candidates.add_argument("--codex-path", help="Codex CLI path or command for validation checks")
    app_candidates.add_argument("--json", action="store_true", dest="as_json")

    openclaw = subparsers.add_parser("openclaw", help="create an OpenClaw Gateway-targeted wake")
    openclaw_subparsers = openclaw.add_subparsers(dest="openclaw_command", required=True)

    openclaw_after = openclaw_subparsers.add_parser("after", help="create an OpenClaw Gateway wake after a duration")
    add_openclaw_gateway_options(openclaw_after)
    add_monitor_gate_options(openclaw_after)
    openclaw_after.add_argument("duration")
    openclaw_after.add_argument("prompt", nargs=argparse.REMAINDER)

    openclaw_at = openclaw_subparsers.add_parser("at", help="create an OpenClaw Gateway wake at an ISO-8601 timestamp")
    add_openclaw_gateway_options(openclaw_at)
    add_monitor_gate_options(openclaw_at)
    openclaw_at.add_argument("timestamp")
    openclaw_at.add_argument("prompt", nargs=argparse.REMAINDER)

    openclaw_plugin = subparsers.add_parser("openclaw-plugin", help="install or package the OpenClaw codex-wake plugin")
    openclaw_plugin_subparsers = openclaw_plugin.add_subparsers(dest="openclaw_plugin_command", required=True)

    openclaw_plugin_install = openclaw_plugin_subparsers.add_parser(
        "install",
        help="install the OpenClaw plugin from a public codex-wake tag or local source copy",
    )
    add_openclaw_plugin_install_options(openclaw_plugin_install, force_default=False)

    openclaw_plugin_update = openclaw_plugin_subparsers.add_parser(
        "update",
        help="refresh and force-install the OpenClaw plugin from a public codex-wake tag or local source copy",
    )
    add_openclaw_plugin_install_options(openclaw_plugin_update, force_default=True)

    openclaw_plugin_pack = openclaw_plugin_subparsers.add_parser(
        "pack",
        help="create an npm-pack artifact for the OpenClaw plugin",
    )
    openclaw_plugin_pack.add_argument("--source-dir", type=Path, default=None, help="plugin source dir; defaults to ./plugins/openclaw-codex-wake")
    openclaw_plugin_pack.add_argument("--output-dir", type=Path, default=Path("dist/openclaw-plugin"), help="directory for the .tgz artifact")
    openclaw_plugin_pack.add_argument("--npm-path", default="npm", help="npm executable to run")
    openclaw_plugin_pack.add_argument("--json", action="store_true", dest="as_json")

    file_cmd = subparsers.add_parser("file", help="create a wake when a file exists")
    file_cmd.add_argument("path")
    file_cmd.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(file_cmd)
    add_monitor_gate_options(file_cmd)
    add_retry_options(file_cmd)

    changed = subparsers.add_parser("changed", help="create a wake when a file is created or changes mtime/size")
    changed.add_argument("path")
    changed.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(changed)
    add_monitor_gate_options(changed)
    add_retry_options(changed)

    pid = subparsers.add_parser("pid", help="create a wake when a process id exits")
    pid.add_argument("pid", type=int)
    pid.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(pid)
    add_monitor_gate_options(pid)

    list_cmd = subparsers.add_parser("list", help="list wake records")
    list_cmd.add_argument("--json", action="store_true", dest="as_json")
    list_cmd.add_argument("--archived", action="store_true", help="include archived wake records")

    status = subparsers.add_parser("status", help="summarize wake records by state")
    status.add_argument("--json", action="store_true", dest="as_json")

    show = subparsers.add_parser("show", help="show one wake record")
    show.add_argument("wake_id")

    cancel = subparsers.add_parser("cancel", help="cancel a pending or firing wake")
    cancel.add_argument("wake_id")

    archive = subparsers.add_parser("archive", help="archive terminal wake records")
    archive.add_argument("wake_id", nargs="?", help="specific wake id to archive")
    archive.add_argument("--all-terminal", action="store_true", help="archive all submitted, failed, cancelled, and expired wakes")

    cleanup = subparsers.add_parser("cleanup", help="preview or delete old archived wake records")
    cleanup.add_argument("--older-than", default="30d", help="archive retention window; defaults to 30d")
    cleanup.add_argument("--delete", action="store_true", help="delete matching archived records; default is dry-run")
    cleanup.add_argument("--archive-terminal", action="store_true", help="archive terminal records before evaluating cleanup")
    cleanup.add_argument("--json", action="store_true", dest="as_json")

    schema = subparsers.add_parser("schema", help="show wake record schema version and compatibility policy")
    schema.add_argument("--json", action="store_true", dest="as_json")

    service = subparsers.add_parser("service", help="manage a user-scoped codex-waked service")
    service_subparsers = service.add_subparsers(dest="service_command", required=True)

    service_install = service_subparsers.add_parser("install", help="install and start a user systemd service")
    add_service_options(service_install)
    service_install.add_argument("--no-start", action="store_true", help="write the unit but do not enable or start it")

    service_status_cmd = service_subparsers.add_parser("status", help="show user service state")
    add_service_options(service_status_cmd)

    service_logs = service_subparsers.add_parser("logs", help="print recent service log lines")
    add_service_options(service_logs)
    service_logs.add_argument("--lines", type=int, default=50)

    service_stop = service_subparsers.add_parser("stop", help="stop and disable the user service")
    add_service_options(service_stop)

    service_uninstall = service_subparsers.add_parser("uninstall", help="stop, disable, and remove the user service")
    add_service_options(service_uninstall)

    monitor = subparsers.add_parser("monitor", help="inspect monitor readiness for the selected wake root")
    monitor_subparsers = monitor.add_subparsers(dest="monitor_command", required=True)
    monitor_check = monitor_subparsers.add_parser("check", help="check whether an active monitor owns this wake root")
    add_service_options(monitor_check)
    monitor_check.add_argument("--stale-after", type=int, default=120, help="seconds before monitor health is considered stale")
    monitor_check.add_argument("--json", action="store_true", dest="as_json")

    supervisor = subparsers.add_parser("supervisor", help="manage the user-scoped multi-root wake supervisor")
    supervisor_subparsers = supervisor.add_subparsers(dest="supervisor_command", required=True)

    supervisor_install = supervisor_subparsers.add_parser("install", help="install and start the user supervisor service")
    add_supervisor_options(supervisor_install)
    supervisor_install.add_argument("--no-start", action="store_true", help="write the unit but do not enable or start it")

    supervisor_status_cmd = supervisor_subparsers.add_parser("status", help="show supervisor service and registered roots")
    add_supervisor_options(supervisor_status_cmd)
    supervisor_status_cmd.add_argument("--all", action="store_true", help="show all registered roots")
    supervisor_status_cmd.add_argument("--json", action="store_true", dest="as_json")

    supervisor_logs = supervisor_subparsers.add_parser("logs", help="print recent supervisor log lines")
    add_supervisor_options(supervisor_logs)
    supervisor_logs.add_argument("--lines", type=int, default=50)

    supervisor_start = supervisor_subparsers.add_parser("start", help="start the user supervisor service")
    add_supervisor_options(supervisor_start)

    supervisor_stop = supervisor_subparsers.add_parser("stop", help="stop and disable the user supervisor service")
    add_supervisor_options(supervisor_stop)

    supervisor_uninstall = supervisor_subparsers.add_parser("uninstall", help="stop, disable, and remove the supervisor service")
    add_supervisor_options(supervisor_uninstall)

    supervisor_enroll = supervisor_subparsers.add_parser("enroll", help="register a wake root for supervisor monitoring")
    add_supervisor_options(supervisor_enroll)
    supervisor_enroll.add_argument("--wake-root", dest="enroll_wake_root", type=Path, default=None)
    supervisor_enroll.add_argument("--repo-root", type=Path, default=None)
    supervisor_enroll.add_argument("--root-id")
    supervisor_enroll.add_argument("--owner-kind", default="repo")
    supervisor_enroll.add_argument("--owner-name")
    supervisor_enroll.add_argument("--codex-path", help="Codex CLI command to record for this root")
    supervisor_enroll.add_argument("--openclaw-path", help="OpenClaw CLI command to record for this root")
    supervisor_enroll.add_argument("--disabled", action="store_true", help="register the root disabled")

    supervisor_unenroll = supervisor_subparsers.add_parser("unenroll", help="remove a wake root from supervisor monitoring")
    add_supervisor_options(supervisor_unenroll)
    supervisor_unenroll.add_argument("--wake-root", dest="unenroll_wake_root", type=Path, default=None)
    supervisor_unenroll.add_argument("--root-id")

    supervisor_run = supervisor_subparsers.add_parser("run", help="run supervisor polling")
    add_supervisor_options(supervisor_run)
    supervisor_run.add_argument("--once", action="store_true", help="run one multi-root poll and exit")
    supervisor_run.add_argument("--no-dispatch", action="store_true", help="evaluate predicates but do not dispatch firing records")
    supervisor_run.add_argument("--json", action="store_true", dest="as_json", help="with --once, print JSON results")

    hook = subparsers.add_parser("hook", help="install or check Codex hook config")
    hook_subparsers = hook.add_subparsers(dest="hook_command", required=True)

    hook_install = hook_subparsers.add_parser("install", help="write .codex/hooks.json for codex-wake-hook")
    add_hook_options(hook_install)

    hook_check = hook_subparsers.add_parser("check", help="check .codex/hooks.json for codex-wake-hook")
    add_hook_options(hook_check)

    hook_user = hook_subparsers.add_parser("user", help="install or check user-scope Codex hook config")
    hook_user_subparsers = hook_user.add_subparsers(dest="user_hook_command", required=True)

    hook_user_install = hook_user_subparsers.add_parser("install", help="write user-scope hooks.json for codex-wake-hook")
    add_user_hook_options(hook_user_install)

    hook_user_check = hook_user_subparsers.add_parser("check", help="check user-scope hooks.json for codex-wake-hook")
    add_user_hook_options(hook_user_check)

    doctor = subparsers.add_parser("doctor", help="report Codex Wake readiness for this repo")
    doctor.add_argument("--hook-command", default=DEFAULT_HOOK_COMMAND, help="expected UserPromptSubmit hook command")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--monitor", action="store_true", help="include monitor readiness; included by default")
    add_service_options(doctor)

    readiness = subparsers.add_parser("product-readiness", help="report installed product readiness across Codex and OpenClaw")
    readiness.add_argument("--hook-command", default=DEFAULT_HOOK_COMMAND, help="expected UserPromptSubmit hook command")
    readiness.add_argument("--repo-root", type=Path, default=None, help="repo root; defaults to current directory")
    readiness.add_argument("--service-name", help="repo-scoped systemd service name")
    readiness.add_argument("--supervisor-name", help="user supervisor systemd service name")
    readiness.add_argument("--interval", type=float, default=1.0, help="service/supervisor poll interval for config inspection")
    readiness.add_argument("--daemon-path", help="codex-waked path for repo service config inspection")
    readiness.add_argument("--codex-path", help="Codex CLI command for repo service app-server readiness")
    readiness.add_argument("--codex-wake-path", help="codex-wake path for supervisor config inspection")
    readiness.add_argument("--log-path", type=Path, default=None, help="repo service log path")
    readiness.add_argument("--supervisor-log-path", type=Path, default=None, help="supervisor log path")
    readiness.add_argument("--registry-dir", type=Path, default=None, help="supervisor registry dir")
    readiness.add_argument("--state-dir", type=Path, default=None, help="supervisor state dir")
    readiness.add_argument("--openclaw-path", help="OpenClaw CLI command")
    readiness.add_argument("--openclaw-config", type=Path, default=None, help="OpenClaw config path")
    readiness.add_argument("--stale-after", type=int, default=120, help="seconds before monitor health is considered stale")
    readiness.add_argument("--openclaw-timeout", type=float, default=30.0, help="seconds for OpenClaw readiness probes")
    readiness.add_argument("--json", action="store_true", dest="as_json")

    return parser


def add_target_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--app-server-thread-id",
        help="create an app-server-targeted wake for the given Codex thread id instead of capturing tmux",
    )
    parser.add_argument(
        "--app-server-endpoint",
        default="stdio://",
        help="app-server endpoint for --app-server-thread-id; only stdio:// is currently implemented",
    )
    parser.add_argument(
        "--app-server-codex-path",
        help="Codex CLI path or command for daemon-side app-server dispatch",
    )


def add_openclaw_gateway_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", required=True, help="OpenClaw agent id")
    parser.add_argument("--session-key", required=True, help="durable OpenClaw session key, such as agent:main:slack:channel:c0...")
    parser.add_argument("--gateway-url", help="OpenClaw Gateway WebSocket URL; defaults to OpenClaw config")
    parser.add_argument("--token-env", help="environment variable containing the Gateway token")
    parser.add_argument("--password-env", help="environment variable containing the Gateway password")
    parser.add_argument("--openclaw-path", help="OpenClaw CLI path or command for daemon-side Gateway dispatch")
    parser.add_argument("--workspace", help="channel workspace/account evidence")
    parser.add_argument("--channel", dest="channel_id", help="channel id evidence, for example a Slack channel id")
    parser.add_argument("--thread-ts", help="thread timestamp evidence")
    parser.add_argument("--channel-provider", default="slack", help="channel provider evidence; defaults to slack")
    parser.add_argument("--deliver", action="store_true", help="ask OpenClaw to deliver the final reply through the session/channel")
    parser.add_argument("--timeout", type=int, default=DEFAULT_OPENCLAW_TIMEOUT_SECONDS, help="OpenClaw agent turn timeout in seconds")
    parser.add_argument("--gateway-timeout-ms", type=int, default=DEFAULT_GATEWAY_TIMEOUT_MS, help="Gateway CLI timeout in milliseconds")
    parser.add_argument("--reply-channel", help="delivery channel override passed to OpenClaw")
    parser.add_argument("--reply-to", help="delivery target override passed to OpenClaw")
    parser.add_argument("--reply-account", dest="reply_account_id", help="delivery account id override passed to OpenClaw")
    parser.add_argument("--model", help="OpenClaw model override")
    parser.add_argument("--thinking", help="OpenClaw thinking level override")


def add_openclaw_plugin_install_options(parser: argparse.ArgumentParser, *, force_default: bool) -> None:
    parser.add_argument("--source-dir", type=Path, default=None, help="install from this local plugin source directory instead of git")
    parser.add_argument("--repo-url", default=DEFAULT_PLUGIN_REPO_URL, help="codex-wake git repo URL for public-tag materialization")
    parser.add_argument("--tag", dest="ref", default=None, help="codex-wake git tag/ref to materialize; defaults to the installed package version")
    parser.add_argument("--materialize-dir", type=Path, default=None, help="directory for materialized public-tag plugin source")
    parser.add_argument("--openclaw-path", help="OpenClaw CLI path or command")
    parser.add_argument("--openclaw-config", type=Path, default=None, help="OpenClaw config to edit when pruning a linked plugin path")
    parser.add_argument(
        "--prune-linked-path",
        action="store_true",
        help="remove the repo-linked plugins.load.paths entry after a successful install, writing a config backup",
    )
    parser.add_argument(
        "--linked-source-dir",
        type=Path,
        default=None,
        help="linked plugin source path to prune; defaults to any linked codex-wake plugin path in OpenClaw config",
    )
    parser.add_argument("--refresh", action="store_true", help="re-clone and replace the materialized public-tag source")
    parser.add_argument("--dry-run", action="store_true", help="print the install command without running OpenClaw")
    parser.add_argument("--json", action="store_true", dest="as_json")
    if force_default:
        parser.add_argument("--no-force", action="store_true", help="do not pass --force to OpenClaw install")
    else:
        parser.add_argument("--force", action="store_true", help="pass --force to OpenClaw install")


def add_monitor_gate_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--require-monitor",
        action="store_true",
        help="fail before writing a wake record unless an active monitor owns this wake root",
    )


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def duration_seconds(value: str) -> int:
    try:
        return int(parse_duration(value).total_seconds())
    except WakeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def add_retry_options(parser: argparse.ArgumentParser) -> None:
    # Options must come before the positional arguments: prompt uses REMAINDER.
    parser.add_argument(
        "--max-attempts",
        type=positive_int,
        default=None,
        help="dispatch attempts before failing (unsafe pane, ack timeout, tmux error); defaults to 3",
    )
    parser.add_argument(
        "--busy-deadline",
        type=duration_seconds,
        default=None,
        help="how long a busy pane is retried without consuming attempts, from the first dispatch attempt, such as 2h; defaults to 2h",
    )


def add_service_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="systemd user unit name; defaults to codex-wake-<repo>.service")
    parser.add_argument("--repo-root", type=Path, default=None, help="repo root for the service; defaults to current directory")
    parser.add_argument("--interval", type=float, default=1.0, help="daemon poll interval in seconds")
    parser.add_argument("--daemon-path", help="path to codex-waked; defaults to PATH resolution")
    parser.add_argument("--codex-path", help="Codex CLI path or command to persist for app-server dispatch")
    parser.add_argument("--log-path", type=Path, default=None, help="service log path")


def add_supervisor_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="systemd user unit name; defaults to codex-wake-supervisor.service")
    parser.add_argument("--interval", type=float, default=1.0, help="supervisor poll interval in seconds")
    parser.add_argument("--codex-wake-path", help="path to codex-wake; defaults to PATH resolution")
    parser.add_argument("--registry-dir", type=Path, default=None, help="root registry directory; defaults to ~/.config/codex-wake/roots.d")
    parser.add_argument("--state-dir", type=Path, default=None, help="supervisor state directory; defaults to ~/.local/state/codex-wake/supervisor")
    parser.add_argument("--log-path", type=Path, default=None, help="supervisor service log path")


def add_hook_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=None, help="repo root to update; defaults to current directory")
    parser.add_argument("--command", dest="hook_command_text", default=DEFAULT_HOOK_COMMAND, help="hook command to install or check")


def add_user_hook_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", type=Path, default=None, help="Codex home; defaults to CODEX_HOME or ~/.codex")
    parser.add_argument("--command", dest="hook_command_text", default=DEFAULT_HOOK_COMMAND, help="hook command to install or check")


def resolve_root(args: argparse.Namespace) -> Path:
    return (args.wake_root or default_wake_root()).resolve()


def create_after(args: argparse.Namespace, root: Path) -> int:
    now = utc_now()
    due = now + parse_duration(args.duration)
    predicate = {"type": "not_before", "due_at": format_utc(due)}
    return create_record(args.prompt, predicate, root, now, args)


def create_at(args: argparse.Namespace, root: Path) -> int:
    due = parse_timestamp(args.timestamp)
    predicate = {"type": "not_before", "due_at": format_utc(due)}
    return create_record(args.prompt, predicate, root, utc_now(), args)


def create_app(args: argparse.Namespace, root: Path) -> int:
    if args.app_command == "status":
        return app_status(args)
    if args.app_command == "candidates":
        return app_candidates(args)
    now = utc_now()
    if args.app_command == "after":
        due = now + parse_duration(args.duration)
    elif args.app_command == "at":
        due = parse_timestamp(args.timestamp)
    else:
        raise WakeError(f"unknown app command: {args.app_command}")
    if args.endpoint != "stdio://":
        raise WakeError("only app-server endpoint stdio:// is currently implemented")
    predicate = {"type": "not_before", "due_at": format_utc(due)}
    target = {
        "transport": "app-server",
        "endpoint": args.endpoint,
        "thread_id": args.thread_id,
    }
    if args.codex_path:
        target["codex_cmd"] = resolve_codex_cmd(args.codex_path, required=True)
    return create_record(args.prompt, predicate, root, now, args, target=target)


def create_openclaw(args: argparse.Namespace, root: Path) -> int:
    now = utc_now()
    if args.openclaw_command == "after":
        due = now + parse_duration(args.duration)
    elif args.openclaw_command == "at":
        due = parse_timestamp(args.timestamp)
    else:
        raise WakeError(f"unknown openclaw command: {args.openclaw_command}")
    predicate = {"type": "not_before", "due_at": format_utc(due)}
    target = build_openclaw_gateway_target(
        agent_id=args.agent,
        session_key=args.session_key,
        gateway_url=args.gateway_url,
        token_env=args.token_env,
        password_env=args.password_env,
        openclaw_cmd=args.openclaw_path,
        workspace=args.workspace,
        channel_id=args.channel_id,
        thread_ts=args.thread_ts,
        channel_provider=args.channel_provider,
        deliver=args.deliver,
        timeout_seconds=args.timeout,
        gateway_timeout_ms=args.gateway_timeout_ms,
        reply_channel=args.reply_channel,
        reply_to=args.reply_to,
        reply_account_id=args.reply_account_id,
        model=args.model,
        thinking=args.thinking,
    )
    return create_record(args.prompt, predicate, root, now, args, target=target)


def openclaw_plugin_command(args: argparse.Namespace) -> int:
    command = args.openclaw_plugin_command
    if command in {"install", "update"}:
        force = bool(args.force) if command == "install" else not bool(args.no_force)
        result = install_openclaw_plugin(
            source_dir=args.source_dir,
            repo_url=args.repo_url,
            ref=args.ref or (None if args.source_dir else default_plugin_ref()),
            materialize_dir=args.materialize_dir,
            openclaw_path=args.openclaw_path,
            force=force,
            refresh=bool(args.refresh or command == "update"),
            dry_run=bool(args.dry_run),
            prune_linked_path=bool(args.prune_linked_path),
            linked_source_dir=args.linked_source_dir,
            openclaw_config=args.openclaw_config,
        )
        if args.as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        print(f"plugin_id={result['plugin_id']}")
        print(f"plugin_version={result['plugin_version']}")
        print(f"package_name={result['package_name']}")
        print(f"package_version={result['package_version']}")
        print(f"source_kind={result['source_kind']}")
        print(f"source_path={result['source_path']}")
        print("command=" + " ".join(result["command"]))
        if result["dry_run"]:
            print("dry_run=true")
        else:
            print("installed=true")
            if result["stdout"]:
                print(str(result["stdout"]).rstrip())
            if result["stderr"]:
                print(str(result["stderr"]).rstrip(), file=sys.stderr)
        prune = result.get("prune_linked_path")
        if isinstance(prune, dict):
            print(f"prune_linked_path_changed={str(bool(prune.get('changed'))).lower()}")
            print(f"prune_linked_path_removed={len(prune.get('removed_paths') or [])}")
            if prune.get("backup_path"):
                print(f"prune_linked_path_backup={prune['backup_path']}")
        registry_refresh = result.get("registry_refresh")
        if isinstance(registry_refresh, dict):
            print("registry_refresh_command=" + " ".join(registry_refresh["command"]))
            print(f"registry_refresh_dry_run={str(bool(registry_refresh.get('dry_run'))).lower()}")
        return 0
    if command == "pack":
        result = pack_openclaw_plugin(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            npm_path=args.npm_path,
        )
        if args.as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        print(f"plugin_id={result['plugin_id']}")
        print(f"plugin_version={result['plugin_version']}")
        print(f"package_name={result['package_name']}")
        print(f"package_version={result['package_version']}")
        print(f"source_path={result['source_path']}")
        print(f"tarball={result['tarball']}")
        print("install_hint=openclaw plugins install npm-pack:" + str(result["tarball"]))
        return 0
    raise WakeError(f"unknown openclaw-plugin command: {command}")


def app_status(args: argparse.Namespace) -> int:
    if args.endpoint != "stdio://":
        raise WakeError("only app-server endpoint stdio:// is currently implemented")
    status_kwargs = {"resume": args.resume}
    if args.codex_path:
        status_kwargs["codex_cmd"] = args.codex_path
    summary = read_app_server_thread_status(args.thread_id, **status_kwargs)
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"thread_id={summary['thread_id']}")
    print(f"status_type={summary['status_type']}")
    print(f"source={'thread/resume' if args.resume else 'thread/read'}")
    active_flags = summary.get("active_flags")
    if isinstance(active_flags, list):
        print("active_flags=" + ",".join(str(flag) for flag in active_flags))
    if summary.get("cwd"):
        print(f"cwd={summary['cwd']}")
    if summary.get("sessionId"):
        print(f"session_id={summary['sessionId']}")
    return 0


def app_candidates(args: argparse.Namespace) -> int:
    if args.only_idle and not args.validate:
        raise WakeError("--only-idle requires --validate")
    candidates = discover_local_thread_candidates(codex_home=args.codex_home, limit=args.limit, cwd=args.cwd)
    rows = []
    for candidate in candidates:
        row = {
            "thread_id": candidate.thread_id,
            "cwd": candidate.cwd,
            "created_at": candidate.created_at,
            "updated_at": candidate.updated_at,
            "path": candidate.path,
            "originator": candidate.originator,
            "cli_version": candidate.cli_version,
            "model_provider": candidate.model_provider,
            "agent_nickname": candidate.agent_nickname,
            "agent_role": candidate.agent_role,
            "resumable_source": "local_session_rollout",
            "validation": "unchecked",
        }
        if args.validate:
            try:
                status_kwargs = {"resume": True, "cwd": candidate.cwd or None}
                if args.codex_path:
                    status_kwargs["codex_cmd"] = args.codex_path
                summary = read_app_server_thread_status(
                    candidate.thread_id,
                    **status_kwargs,
                )
            except WakeError as exc:
                row["validation"] = "resume_failed"
                row["validation_error"] = str(exc)
            else:
                row["validation"] = "resume_ok"
                row["status_type"] = summary.get("status_type", "")
                row["status"] = summary.get("status", {})
        if args.only_idle and row.get("status_type") != "idle":
            continue
        rows.append(row)
    if args.as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        print("No local app-server thread candidates found.")
        return 0
    if args.validate:
        print("THREAD_ID\tVALIDATION\tSTATUS\tUPDATED_AT\tCWD")
        for row in rows:
            print(
                f"{row['thread_id']}\t{row['validation']}\t{row.get('status_type', '')}\t{row['updated_at']}\t{row['cwd']}"
            )
    else:
        print("THREAD_ID\tUPDATED_AT\tCWD")
        for row in rows:
            print(f"{row['thread_id']}\t{row['updated_at']}\t{row['cwd']}")
    print("Use: codex-wake app status --resume <THREAD_ID>")
    return 0


def create_file(args: argparse.Namespace, root: Path) -> int:
    path = args.path.strip()
    if not path:
        raise WakeError("file path is required")
    predicate = {"type": "file_exists", "path": path}
    return create_record(args.prompt, predicate, root, utc_now(), args)


def create_changed(args: argparse.Namespace, root: Path) -> int:
    path_text = args.path.strip()
    if not path_text:
        raise WakeError("file path is required")
    path = Path(path_text)
    resolved = path if path.is_absolute() else Path.cwd() / path
    try:
        stat = resolved.stat()
    except FileNotFoundError:
        predicate = {
            "type": "file_changed",
            "path": path_text,
            "registered_exists": False,
            "registered_mtime_ns": None,
            "registered_size": None,
        }
    else:
        predicate = {
            "type": "file_changed",
            "path": path_text,
            "registered_exists": True,
            "registered_mtime_ns": stat.st_mtime_ns,
            "registered_size": stat.st_size,
        }
    return create_record(args.prompt, predicate, root, utc_now(), args)


def create_pid(args: argparse.Namespace, root: Path) -> int:
    pid = args.pid
    if pid <= 0:
        raise WakeError("pid must be a positive integer")
    if not process_exists(pid):
        raise WakeError(f"process does not exist: {pid}")
    predicate = {"type": "process_done", "pid": pid}
    identity = process_identity(pid)
    if identity:
        predicate["registered_start_time_ticks"] = identity["start_time_ticks"]
        if "boot_id" in identity:
            predicate["registered_boot_id"] = identity["boot_id"]
    return create_record(args.prompt, predicate, root, utc_now(), args)


def create_record(
    prompt_parts: list[str],
    predicate: dict,
    root: Path,
    now,
    args: argparse.Namespace,
    *,
    target: dict | None = None,
) -> int:
    prompt = normalize_prompt(prompt_parts)
    if getattr(args, "require_monitor", False):
        readiness = monitor_readiness(wake_root=root, repo_root=Path.cwd())
        require_monitor_ready(readiness)
    record = build_record(
        predicate=predicate,
        prompt=prompt,
        cwd=Path.cwd(),
        target=target or target_for_args(args),
        now=now,
    )
    if getattr(args, "max_attempts", None) is not None:
        record["max_attempts"] = args.max_attempts
    if getattr(args, "busy_deadline", None) is not None:
        record["busy_deadline_seconds"] = args.busy_deadline
    path = write_record(root, record)
    print(f"{record['id']} {path}")
    return 0


def target_for_args(args: argparse.Namespace) -> dict[str, str]:
    if getattr(args, "app_server_thread_id", None):
        endpoint = getattr(args, "app_server_endpoint", "stdio://")
        if endpoint != "stdio://":
            raise WakeError("only app-server endpoint stdio:// is currently implemented")
        target = {
            "transport": "app-server",
            "endpoint": endpoint,
            "thread_id": args.app_server_thread_id,
        }
        codex_path = getattr(args, "app_server_codex_path", None)
        if codex_path:
            target["codex_cmd"] = resolve_codex_cmd(codex_path, required=True)
        return target
    return capture_tmux_target()


def list_records(args: argparse.Namespace, root: Path) -> int:
    records = all_records(root, include_archive=args.archived)
    if args.as_json:
        print(json.dumps([item.record for item in records], indent=2, sort_keys=True))
        return 0
    if not records:
        print("No wakes.")
        return 0
    print("ID\tSTATUS\tPREDICATE\tNEXT")
    for item in records:
        record = item.record
        predicate = record.get("predicate") or {}
        predicate_type = predicate.get("type", "unknown")
        next_attempt = record.get("next_attempt_at", "")
        print(f"{record.get('id')}\t{record.get('status')}\t{predicate_type}\t{next_attempt}")
    return 0


def status_command(args: argparse.Namespace, root: Path) -> int:
    summary = status_summary(root)
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"wake_root={summary['wake_root']}")
    print(f"total={summary['total']}")
    print(f"active_total={summary['active_total']}")
    print(f"terminal_total={summary['terminal_total']}")
    print(f"archived_total={summary['archived_total']}")
    counts_by_status = summary["counts_by_status"]
    counts_by_predicate = summary["counts_by_predicate"]
    counts_by_target = summary["counts_by_target_transport"]
    counts_by_visibility = summary["counts_by_visibility_classification"]
    assert isinstance(counts_by_status, dict)
    assert isinstance(counts_by_predicate, dict)
    assert isinstance(counts_by_target, dict)
    assert isinstance(counts_by_visibility, dict)
    print("counts_by_status=" + ",".join(f"{key}:{counts_by_status[key]}" for key in sorted(counts_by_status)))
    print("counts_by_predicate=" + ",".join(f"{key}:{counts_by_predicate[key]}" for key in sorted(counts_by_predicate)))
    print("counts_by_target_transport=" + ",".join(f"{key}:{counts_by_target[key]}" for key in sorted(counts_by_target)))
    print(
        "counts_by_visibility_classification="
        + ",".join(f"{key}:{counts_by_visibility[key]}" for key in sorted(counts_by_visibility))
    )
    print(f"earliest_next_attempt_at={summary['earliest_next_attempt_at']}")
    return 0


def show_record(args: argparse.Namespace, root: Path) -> int:
    found = find_record(root, args.wake_id)
    print(json.dumps(found.record, indent=2, sort_keys=True))
    return 0


def cancel(args: argparse.Namespace, root: Path) -> int:
    path = cancel_record(root, args.wake_id)
    print(f"cancelled {args.wake_id} {path}")
    return 0


def archive(args: argparse.Namespace, root: Path) -> int:
    if bool(args.wake_id) == bool(args.all_terminal):
        raise WakeError("provide either a wake id or --all-terminal")
    if args.all_terminal:
        paths = archive_terminal_records(root)
        for path in paths:
            print(f"archived {path.stem} {path}")
        if not paths:
            print("No terminal wakes to archive.")
        return 0
    path = archive_record(root, args.wake_id)
    print(f"archived {args.wake_id} {path}")
    return 0


def cleanup(args: argparse.Namespace, root: Path) -> int:
    older_than = parse_duration(args.older_than)
    archived = []
    if args.archive_terminal:
        archived = archive_terminal_records(root)
    results = cleanup_archived_records(root, older_than=older_than, delete=args.delete)
    if args.as_json:
        print(
            json.dumps(
                {
                    "wake_root": str(root),
                    "mode": "delete" if args.delete else "dry-run",
                    "older_than": args.older_than,
                    "archive_terminal": bool(args.archive_terminal),
                    "archived_terminal_count": len(archived),
                    "archived_terminal": [{"wake_id": path.stem, "path": str(path)} for path in archived],
                    "matched_count": len(results),
                    "matched": [
                        {
                            "wake_id": result.wake_id,
                            "path": str(result.path),
                            "retention_at": result.retention_at,
                            "deleted": result.deleted,
                        }
                        for result in results
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    for path in archived:
        print(f"archived {path.stem} {path}")
    action = "deleted" if args.delete else "would-delete"
    for result in results:
        print(f"{action} {result.wake_id} {result.path} retention_at={result.retention_at}")
    mode = "delete" if args.delete else "dry-run"
    print(f"cleanup mode={mode} older_than={args.older_than} archived={len(archived)} matched={len(results)}")
    return 0


def schema_command(args: argparse.Namespace) -> int:
    summary = schema_summary()
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"schema_version={summary['schema_version']}")
    print(f"compatibility={summary['compatibility']}")
    print(f"schema_doc={summary['schema_doc']}")
    print(f"statuses={','.join(summary['active_statuses'] + summary['terminal_statuses'] + [summary['archived_status']])}")
    print(f"predicate_types={','.join(summary['predicate_types'])}")
    print(f"target_transports={','.join(summary['target_transports'])}")
    print(f"required_fields={','.join(summary['required_fields'])}")
    print(f"optional_fields={','.join(summary['optional_fields'])}")
    print(f"schema_bump_required_for={','.join(summary['schema_bump_required_for'])}")
    return 0


def service_config_for_args(args: argparse.Namespace, root: Path):
    return build_service_config(
        repo_root=args.repo_root,
        wake_root=root,
        name=args.name,
        interval=args.interval,
        daemon_path=args.daemon_path,
        codex_path=args.codex_path,
        resolve_default_codex=True,
        log_path=args.log_path,
    )


def service_command(args: argparse.Namespace, root: Path) -> int:
    config = service_config_for_args(args, root)
    if args.service_command == "install":
        install_service(config, start=not args.no_start)
        action = "installed" if args.no_start else "installed and started"
        print(f"{action} {config.name}")
        print(f"unit={config.unit_path}")
        print(f"log={config.log_path}")
        print(f"app_server_codex_cmd={config.codex_path or 'missing'}")
        return 0
    if args.service_command == "status":
        active, enabled = service_status(config)
        print(f"name={config.name}")
        print(f"active={active}")
        print(f"enabled={enabled}")
        print(f"unit={config.unit_path}")
        print(f"log={config.log_path}")
        print(f"app_server_codex_cmd={getattr(config, 'codex_path', None) or 'missing'}")
        return 0
    if args.service_command == "logs":
        print(f"log={config.log_path}")
        text = read_log_tail(config.log_path, args.lines)
        if text:
            print(text)
        return 0
    if args.service_command == "stop":
        stop_service(config)
        print(f"stopped {config.name}")
        return 0
    if args.service_command == "uninstall":
        uninstall_service(config)
        print(f"uninstalled {config.name}")
        print(f"removed={config.unit_path}")
        return 0
    raise WakeError(f"unknown service command: {args.service_command}")


def monitor_command(args: argparse.Namespace, root: Path) -> int:
    if args.monitor_command != "check":
        raise WakeError(f"unknown monitor command: {args.monitor_command}")
    readiness = monitor_readiness(
        wake_root=root,
        repo_root=args.repo_root,
        service_name=args.name,
        interval=args.interval,
        daemon_path=args.daemon_path,
        codex_path=args.codex_path,
        log_path=args.log_path,
        stale_after_seconds=args.stale_after,
    )
    if args.as_json:
        print(json.dumps(readiness, indent=2, sort_keys=True))
        return 0 if readiness["monitor_ready"] else 1
    service = readiness["service"]
    health = readiness["health"]
    assert isinstance(service, dict)
    assert isinstance(health, dict)
    print(f"wake_root={readiness['wake_root']}")
    print(f"repo_root={readiness['repo_root']}")
    print(f"monitor_ready={str(readiness['monitor_ready']).lower()}")
    print(f"monitor_source={readiness['monitor_source'] or 'missing'}")
    print(f"service_name={service['name']}")
    print(f"service_active={service['active']}")
    print(f"service_enabled={service['enabled']}")
    print(f"service_unit={service['unit']}")
    print(f"service_wake_root={service['wake_root'] or 'missing'}")
    print(f"service_matches_wake_root={str(service['matches_wake_root']).lower()}")
    print(f"health_path={health['path']}")
    print(f"health_exists={str(health['exists']).lower()}")
    print(f"health_recent={str(health['recent']).lower()}")
    print(f"health_persistent={str(health['persistent']).lower()}")
    print(f"health_source={health['source'] or 'missing'}")
    print(f"health_mode={health['mode'] or 'missing'}")
    print(f"health_checked_at={health['checked_at']}")
    return 0 if readiness["monitor_ready"] else 1


def supervisor_config_for_args(args: argparse.Namespace):
    return build_supervisor_config(
        name=args.name,
        interval=args.interval,
        codex_wake_path=args.codex_wake_path,
        registry_dir=args.registry_dir,
        state_dir=args.state_dir,
        log_path=args.log_path,
    )


def supervisor_command(args: argparse.Namespace, root: Path) -> int:
    config = supervisor_config_for_args(args)
    command = args.supervisor_command
    if command == "install":
        install_supervisor(config, start=not args.no_start)
        action = "installed" if args.no_start else "installed and started"
        print(f"{action} {config.name}")
        print(f"unit={config.unit_path}")
        print(f"log={config.log_path}")
        print(f"registry_dir={config.registry_dir}")
        print(f"state_dir={config.state_dir}")
        return 0
    if command == "start":
        install_supervisor(config, start=True)
        print(f"started {config.name}")
        return 0
    if command == "stop":
        stop_supervisor(config)
        print(f"stopped {config.name}")
        return 0
    if command == "uninstall":
        uninstall_supervisor(config)
        print(f"uninstalled {config.name}")
        print(f"removed={config.unit_path}")
        return 0
    if command == "logs":
        print(f"log={config.log_path}")
        text = read_log_tail(config.log_path, args.lines)
        if text:
            print(text)
        return 0
    if command == "status":
        summary = supervisor_status(config)
        if args.as_json:
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
        service = summary["service"]
        assert isinstance(service, dict)
        print(f"name={service['name']}")
        print(f"active={service['active']}")
        print(f"enabled={service['enabled']}")
        print(f"unit={service['unit']}")
        print(f"log={service['log']}")
        print(f"registry_dir={summary['registry_dir']}")
        print(f"state_dir={summary['state_dir']}")
        print(f"root_count={summary['root_count']}")
        roots = summary["roots"]
        assert isinstance(roots, list)
        if roots:
            print("ROOT_ID\tENABLED\tHEALTH_STATUS\tHEALTH_RECENT\tWAKE_ROOT\tREMEDIATION")
            for item in roots:
                print(
                    f"{item.get('root_id')}\t{str(item.get('enabled')).lower()}\t"
                    f"{item.get('health_status')}\t{str(item.get('health_recent')).lower()}\t"
                    f"{item.get('wake_root')}\t{item.get('remediation') or ''}"
                )
        return 0
    if command == "enroll":
        enroll_wake_root = (args.enroll_wake_root or root).resolve()
        path = enroll_root(
            wake_root=enroll_wake_root,
            repo_root=args.repo_root,
            registry_dir=config.registry_dir,
            root_id=args.root_id,
            enabled=not args.disabled,
            owner_kind=args.owner_kind,
            owner_name=args.owner_name,
            codex_cmd=args.codex_path,
            openclaw_cmd=args.openclaw_path,
        )
        print(f"enrolled {path.stem}")
        print(f"path={path}")
        print(f"wake_root={enroll_wake_root}")
        return 0
    if command == "unenroll":
        path = unenroll_root(
            wake_root=args.unenroll_wake_root,
            root_id=args.root_id,
            registry_dir=config.registry_dir,
        )
        print(f"unenrolled {path.stem}")
        print(f"removed={path}")
        return 0
    if command == "run":
        if args.once and args.as_json:
            from .supervisor import supervisor_poll_once

            print(
                json.dumps(
                    supervisor_poll_once(config, mode="once", dispatch=not args.no_dispatch),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        return supervisor_run_loop(config, once=args.once, dispatch=not args.no_dispatch)
    raise WakeError(f"unknown supervisor command: {command}")


def print_hook_runtime_evidence(root: Path) -> None:
    evidence = hook_runtime_evidence(root)
    print(f"hook_ack_count={evidence.ack_count}")
    print(f"hook_active_session_loaded={evidence.active_session_loaded}")
    print(f"hook_latest_ack_path={evidence.latest_ack_path or ''}")
    print(f"hook_latest_ack_submitted_at={evidence.latest_ack_submitted_at}")
    print(f"hook_latest_ack_wake_id={evidence.latest_ack_wake_id}")
    print(f"hook_latest_ack_session_id={evidence.latest_ack_session_id}")
    print("hook_loaded_note=ack evidence proves a hook ran only after a wake prompt was submitted")


def hook_source_to_dict(check: HookSourceCheck) -> dict[str, object]:
    return {
        "scope": check.scope,
        "path": str(check.path),
        "exists": check.exists,
        "valid_json": check.valid_json,
        "installed": check.installed,
        "command": check.command,
        "message": check.message,
    }


def print_hook_sources(repo_root: Path, command: str) -> None:
    sources = check_hook_sources(repo_root, command)
    print(f"hook_project_config={sources.project.path}")
    print(f"hook_project_config_exists={str(sources.project.exists).lower()}")
    print(f"hook_project_config_installed={str(sources.project.installed).lower()}")
    print(f"hook_user_config={sources.user.path}")
    print(f"hook_user_config_exists={str(sources.user.exists).lower()}")
    print(f"hook_user_config_installed={str(sources.user.installed).lower()}")
    print(f"hook_installed_scopes={','.join(sources.installed_scopes)}")
    print(f"hook_duplicate_install={str(sources.duplicate_installed).lower()}")
    print(f"hook_overlap_warning={sources.overlap_warning}")


def print_hook_source_check(check: HookSourceCheck) -> None:
    print(f"path={check.path}")
    print(f"scope={check.scope}")
    print(f"exists={str(check.exists).lower()}")
    print(f"valid_json={str(check.valid_json).lower()}")
    print(f"installed={str(check.installed).lower()}")
    print(f"command={check.command}")
    print(f"message={check.message}")


def hook_command(args: argparse.Namespace, root: Path) -> int:
    repo_root = (getattr(args, "repo_root", None) or Path.cwd()).resolve()
    if args.hook_command == "install":
        path = install_hook_config(repo_root, args.hook_command_text)
        print(f"installed hook config: {path}")
        print(f"command={args.hook_command_text}")
        print(f"note={hook_review_note()}")
        return 0
    if args.hook_command == "check":
        check = check_hook_config(repo_root, args.hook_command_text)
        print(f"path={check.path}")
        print(f"exists={str(check.exists).lower()}")
        print(f"valid_json={str(check.valid_json).lower()}")
        print(f"installed={str(check.installed).lower()}")
        print(f"command={check.command}")
        print(f"message={check.message}")
        print(f"trust={hook_review_note()}")
        print_hook_sources(repo_root, args.hook_command_text)
        print_hook_runtime_evidence(root)
        return 0 if check.installed else 1
    if args.hook_command == "user":
        if args.user_hook_command == "install":
            path = install_user_hook_config(args.codex_home, args.hook_command_text)
            print(f"installed user hook config: {path}")
            print(f"command={args.hook_command_text}")
            print(f"note={hook_review_note()}")
            return 0
        if args.user_hook_command == "check":
            check = check_user_hook_config(args.codex_home, args.hook_command_text)
            print_hook_source_check(check)
            print(f"trust={hook_review_note()}")
            print_hook_runtime_evidence(root)
            return 0 if check.installed else 1
        raise WakeError(f"unknown user hook command: {args.user_hook_command}")
    raise WakeError(f"unknown hook command: {args.hook_command}")


def doctor_summary(args: argparse.Namespace, root: Path) -> dict[str, object]:
    repo_root = (args.repo_root or Path.cwd()).resolve()
    hook_check = check_hook_config(repo_root, args.hook_command)
    hook_sources = check_hook_sources(repo_root, args.hook_command)
    config = service_config_for_args(args, root)
    codex_wake = shutil.which("codex-wake") or ""
    codex_waked = shutil.which("codex-waked") or ""
    codex_wake_hook = shutil.which("codex-wake-hook") or ""
    codex = shutil.which("codex") or ""
    tmux = shutil.which("tmux") or ""
    try:
        active, enabled = service_status(config)
    except Exception as exc:
        active, enabled = "unknown", f"unknown ({exc})"
    hook_evidence = hook_runtime_evidence(root)
    app_server_readiness = service_app_server_readiness(config)
    monitor = monitor_readiness(
        wake_root=root,
        repo_root=repo_root,
        service_name=config.name,
        interval=config.interval,
        daemon_path=str(config.daemon_path),
        log_path=config.log_path,
    )
    return {
        "repo_root": str(repo_root),
        "wake_root": str(root),
        "commands": {
            "codex_wake": codex_wake or "",
            "codex_waked": codex_waked or "",
            "codex_wake_hook": codex_wake_hook or "",
            "codex": codex or "",
            "tmux": tmux or "",
        },
        "hook_config": {
            "path": str(hook_check.path),
            "exists": hook_check.exists,
            "valid_json": hook_check.valid_json,
            "installed": hook_check.installed,
            "command": hook_check.command,
            "message": hook_check.message,
        },
        "hook_sources": {
            "project": hook_source_to_dict(hook_sources.project),
            "user": hook_source_to_dict(hook_sources.user),
            "installed_scopes": list(hook_sources.installed_scopes),
            "duplicate_installed": hook_sources.duplicate_installed,
            "overlap_warning": hook_sources.overlap_warning,
        },
        "hook_runtime": {
            "ack_count": hook_evidence.ack_count,
            "active_session_loaded": hook_evidence.active_session_loaded,
            "latest_ack_path": str(hook_evidence.latest_ack_path) if hook_evidence.latest_ack_path else "",
            "latest_ack_submitted_at": hook_evidence.latest_ack_submitted_at,
            "latest_ack_wake_id": hook_evidence.latest_ack_wake_id,
            "latest_ack_session_id": hook_evidence.latest_ack_session_id,
            "loaded_note": "ack evidence proves a hook ran only after a wake prompt was submitted",
        },
        "service": {
            "name": config.name,
            "active": active,
            "enabled": enabled,
            "unit": str(config.unit_path),
            "log": str(config.log_path),
        },
        "service_app_server": asdict(app_server_readiness),
        "monitor": monitor,
        "trust": hook_review_note(),
    }


def doctor_command(args: argparse.Namespace, root: Path) -> int:
    summary = doctor_summary(args, root)
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    commands = summary["commands"]
    hook_config = summary["hook_config"]
    hook_runtime = summary["hook_runtime"]
    hook_sources = summary["hook_sources"]
    service = summary["service"]
    service_app_server = summary["service_app_server"]
    monitor = summary["monitor"]
    assert isinstance(commands, dict)
    assert isinstance(hook_config, dict)
    assert isinstance(hook_runtime, dict)
    assert isinstance(hook_sources, dict)
    assert isinstance(service, dict)
    assert isinstance(service_app_server, dict)
    assert isinstance(monitor, dict)
    print(f"repo_root={summary['repo_root']}")
    print(f"wake_root={summary['wake_root']}")
    print(f"codex_wake={commands['codex_wake'] or 'missing'}")
    print(f"codex_waked={commands['codex_waked'] or 'missing'}")
    print(f"codex_wake_hook={commands['codex_wake_hook'] or 'missing'}")
    print(f"codex={commands['codex'] or 'missing'}")
    print(f"tmux={commands['tmux'] or 'missing'}")
    print(f"hook_config={hook_config['path']}")
    print(f"hook_config_exists={str(hook_config['exists']).lower()}")
    print(f"hook_config_valid_json={str(hook_config['valid_json']).lower()}")
    print(f"hook_config_installed={str(hook_config['installed']).lower()}")
    print(f"hook_command={hook_config['command']}")
    print(f"hook_user_config={hook_sources['user']['path']}")
    print(f"hook_user_config_exists={str(hook_sources['user']['exists']).lower()}")
    print(f"hook_user_config_installed={str(hook_sources['user']['installed']).lower()}")
    print(f"hook_installed_scopes={','.join(hook_sources['installed_scopes'])}")
    print(f"hook_duplicate_install={str(hook_sources['duplicate_installed']).lower()}")
    print(f"hook_overlap_warning={hook_sources['overlap_warning']}")
    print(f"hook_ack_count={hook_runtime['ack_count']}")
    print(f"hook_active_session_loaded={hook_runtime['active_session_loaded']}")
    print(f"hook_latest_ack_path={hook_runtime['latest_ack_path']}")
    print(f"hook_latest_ack_submitted_at={hook_runtime['latest_ack_submitted_at']}")
    print(f"hook_latest_ack_wake_id={hook_runtime['latest_ack_wake_id']}")
    print(f"hook_latest_ack_session_id={hook_runtime['latest_ack_session_id']}")
    print(f"hook_loaded_note={hook_runtime['loaded_note']}")
    print(f"service_name={service['name']}")
    print(f"service_active={service['active']}")
    print(f"service_enabled={service['enabled']}")
    print(f"service_unit={service['unit']}")
    print(f"service_log={service['log']}")
    print(f"service_app_server_codex_ready={str(service_app_server['codex_cmd_ready']).lower()}")
    print(f"service_app_server_codex_source={service_app_server['codex_cmd_source']}")
    print(f"service_app_server_codex_cmd={service_app_server['codex_cmd'] or 'missing'}")
    print(f"service_app_server_unit_codex_cmd={service_app_server['unit_codex_cmd'] or 'missing'}")
    print(f"service_app_server_user_manager_codex_cmd={service_app_server['user_manager_codex_cmd'] or 'missing'}")
    print(f"service_app_server_interactive_codex_cmd={service_app_server['interactive_codex_cmd'] or 'missing'}")
    print(f"service_app_server_note={service_app_server['message']}")
    print(f"monitor_ready={str(monitor['monitor_ready']).lower()}")
    print(f"monitor_source={monitor['monitor_source'] or 'missing'}")
    print(f"trust={summary['trust']}")
    return 0


def product_readiness_command(args: argparse.Namespace, root: Path) -> int:
    summary = product_readiness_summary(
        wake_root=root,
        repo_root=args.repo_root,
        hook_command=args.hook_command,
        service_name=args.service_name,
        supervisor_name=args.supervisor_name,
        interval=args.interval,
        daemon_path=args.daemon_path,
        codex_path=args.codex_path,
        codex_wake_path=args.codex_wake_path,
        log_path=args.log_path,
        supervisor_log_path=args.supervisor_log_path,
        registry_dir=args.registry_dir,
        state_dir=args.state_dir,
        openclaw_path=args.openclaw_path,
        openclaw_config=args.openclaw_config,
        stale_after_seconds=args.stale_after,
        openclaw_timeout=args.openclaw_timeout,
    )
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"overall_status={summary['overall_status']}")
    print(f"repo_root={summary['repo_root']}")
    print(f"wake_root={summary['wake_root']}")
    checks = summary["checks"]
    assert isinstance(checks, dict)
    for name in (
        "cli",
        "hooks",
        "skills",
        "repo_service",
        "supervisor",
        "monitor",
        "app_server",
        "openclaw_gateway",
        "openclaw_plugin",
        "tmux",
    ):
        check = checks.get(name)
        if isinstance(check, dict):
            print(f"{name}_status={check.get('status')}")
            print(f"{name}_message={check.get('message')}")
    return 0


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = resolve_root(args)
    if args.command == "after":
        return create_after(args, root)
    if args.command == "at":
        return create_at(args, root)
    if args.command == "app":
        return create_app(args, root)
    if args.command == "openclaw":
        return create_openclaw(args, root)
    if args.command == "openclaw-plugin":
        return openclaw_plugin_command(args)
    if args.command == "file":
        return create_file(args, root)
    if args.command == "changed":
        return create_changed(args, root)
    if args.command == "pid":
        return create_pid(args, root)
    if args.command == "list":
        return list_records(args, root)
    if args.command == "status":
        return status_command(args, root)
    if args.command == "show":
        return show_record(args, root)
    if args.command == "cancel":
        return cancel(args, root)
    if args.command == "archive":
        return archive(args, root)
    if args.command == "cleanup":
        return cleanup(args, root)
    if args.command == "schema":
        return schema_command(args)
    if args.command == "service":
        return service_command(args, root)
    if args.command == "monitor":
        return monitor_command(args, root)
    if args.command == "supervisor":
        return supervisor_command(args, root)
    if args.command == "hook":
        return hook_command(args, root)
    if args.command == "doctor":
        return doctor_command(args, root)
    if args.command == "product-readiness":
        return product_readiness_command(args, root)
    raise WakeError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except WakeError as exc:
        print(f"codex-wake: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
