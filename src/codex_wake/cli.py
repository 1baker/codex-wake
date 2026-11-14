from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from contextlib import nullcontext
from dataclasses import asdict, replace
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
    protected_signal_cleanup_records,
    schema_summary,
    status_summary,
    utc_now,
    write_record,
)
from .service import build_service_config, install_service, read_log_tail, service_dispatch_mode, service_status, stop_service, uninstall_service
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


def bounded_attempt_count(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 100") from None
    if not 1 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return parsed


def one_attempt_count(value: str) -> int:
    if value != "1":
        raise argparse.ArgumentTypeError("GitHub CI wakes require exactly one dispatch attempt")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-wake")
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    parser.add_argument(
        "--wake-root",
        type=Path,
        default=None,
        help="explicit runtime root; account commands use the saved user controller, project wakes use .codex/wake",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    from .recurring_commands import register_parser as register_schedules
    register_schedules(subparsers)
    from .completion import register_parser as register_completion
    register_completion(subparsers)
    from .local_control_commands import register_parser as register_local_control
    register_local_control(subparsers)
    import argparse as _argparse
    _control_verbs = next(a for a in subparsers.choices['control']._actions if isinstance(a, _argparse._SubParsersAction))
    from .local_health import register_parser as register_local_health
    register_local_health(_control_verbs)
    from .local_slash_commands import register as register_local_slash
    register_local_slash(_control_verbs)
    from .local_control_lifecycle import register as register_local_lifecycle
    register_local_lifecycle(_control_verbs)
    from .local_self_limits import register_parser as register_local_self_limits
    register_local_self_limits(subparsers)
    from .governor_commands import register_parser as register_governor
    register_governor(subparsers)
    from .wake_control import add_control_parsers
    add_control_parsers(subparsers)
    from .time_inspection import add_time_parser
    add_time_parser(subparsers)
    from .sessions_cli import add_sessions_parser
    add_sessions_parser(subparsers)
    from .controller_commands import register_parser as register_controller
    register_controller(subparsers)
    from .account_commands import register_parser as register_accounts
    register_accounts(subparsers)
    from .build_commands import register_parser as register_builds
    register_builds(subparsers)
    from .daemon_commands import register_parser as register_daemons
    register_daemons(subparsers)
    from .history_commands import register_parser as register_history
    register_history(subparsers)
    from .migration_commands import register_parser as register_migration
    register_migration(subparsers)
    from .host_commands import register_parser as register_hosts
    register_hosts(subparsers)
    from .health_commands import register_parser as register_health
    register_health(subparsers)
    from .notice_commands import register_parser as register_notices
    register_notices(subparsers)
    from .recovery_commands import register_parser as register_recovery
    register_recovery(subparsers)
    from .flow_session_commands import register_parser as register_flow_sessions
    register_flow_sessions(subparsers)
    from .flow_commands import register_parser as register_flows
    register_flows(subparsers)
    from .operation_commands import register_parser as register_operations
    register_operations(subparsers)
    profiles = subparsers.add_parser("profiles", help="Profiles compatibility commands owned by Wake")
    profiles.add_argument("--config", type=Path, dest="profile_config")
    profiles.add_argument("profile_arguments", nargs=argparse.REMAINDER)
    from .native_delivery import add_native_parser
    add_native_parser(subparsers)
    from .runtime_wakes import add_grok_parser
    add_grok_parser(subparsers)
    from .wake_policy import register_parser as register_wake_policy
    register_wake_policy(subparsers)
    from .task_brief_commands import register_parser as register_task_briefs
    register_task_briefs(subparsers)
    from .managed_inventory_commands import register_parser as register_managed_agents
    register_managed_agents(subparsers)
    from .resource_claim_commands import register_parser as register_resources
    register_resources(subparsers)
    from .attention_commands import register_parser as register_attention
    register_attention(subparsers)
    from .work_acceptance_commands import register_parser as register_acceptance
    register_acceptance(subparsers)
    from .background_job_commands import register_parser as register_jobs
    register_jobs(subparsers)
    from .tab_organization_commands import register_parser as register_tabs
    register_tabs(subparsers)
    from .guarded_interaction_commands import register_parser as register_interactions
    register_interactions(subparsers)
    from .a2a_cli import add_a2a_parser
    add_a2a_parser(subparsers)
    from .messages_cli import add_messages_parser
    add_messages_parser(subparsers)
    from .goal_limits_cli import add_goal_limits_parser
    add_goal_limits_parser(subparsers)
    from .permission_commands import register_parser as register_permissions
    register_permissions(subparsers)

    after = subparsers.add_parser("after", help="create a wake after a duration such as 45m or 1h30m")
    after.add_argument("duration")
    after.add_argument("prompt", nargs=argparse.REMAINDER)
    after.add_argument("--network-time", action="store_true", help="use bounded network-first time (plain NTP, explicitly unauthenticated)")
    add_target_options(after)
    add_monitor_gate_options(after)

    at = subparsers.add_parser("at", help="create a wake at an ISO-8601 timestamp with timezone")
    at.add_argument("timestamp")
    at.add_argument("prompt", nargs=argparse.REMAINDER)
    at.add_argument("--network-time", action="store_true", help="use bounded network-first time (plain NTP, explicitly unauthenticated)")
    add_target_options(at)
    add_monitor_gate_options(at)

    app = subparsers.add_parser("app", help="create an app-server-targeted wake")
    app_subparsers = app.add_subparsers(dest="app_command", required=True)

    app_after = app_subparsers.add_parser("after", help="create an app-server wake after a duration")
    app_after.add_argument("--endpoint", default="stdio://", help="app-server endpoint; only stdio:// is currently implemented")
    app_after.add_argument("--codex-path", help="Codex CLI path or command for daemon-side app-server dispatch")
    add_active_writer_retry_option(app_after)
    add_monitor_gate_options(app_after)
    app_after.add_argument("thread_id")
    app_after.add_argument("duration")
    app_after.add_argument("prompt", nargs=argparse.REMAINDER)

    app_at = app_subparsers.add_parser("at", help="create an app-server wake at an ISO-8601 timestamp")
    app_at.add_argument("--endpoint", default="stdio://", help="app-server endpoint; only stdio:// is currently implemented")
    app_at.add_argument("--codex-path", help="Codex CLI path or command for daemon-side app-server dispatch")
    add_active_writer_retry_option(app_at)
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

    changed = subparsers.add_parser("changed", help="create a wake when a file is created or changes mtime/size")
    changed.add_argument("path")
    changed.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(changed)
    add_monitor_gate_options(changed)

    filesystem = subparsers.add_parser(
        "filesystem",
        help="arm a durable schema-v2 filesystem-state wake",
    )
    filesystem_subparsers = filesystem.add_subparsers(
        dest="filesystem_command", required=True
    )
    for recipe, help_text in (
        ("created", "wake after the path is observed being created"),
        ("exists", "wake while the path exists"),
        ("changed", "wake after the observed path fingerprint changes"),
    ):
        recipe_parser = filesystem_subparsers.add_parser(recipe, help=help_text)
        recipe_parser.add_argument("--idempotency-key")
        recipe_parser.add_argument(
            "--max-attempts",
            type=bounded_attempt_count,
            default=3,
            help="maximum dispatch attempts (1-100; default: 3)",
        )
        recipe_parser.add_argument("path")
        recipe_parser.add_argument("prompt", nargs=argparse.REMAINDER)
        add_target_options(recipe_parser)
        add_monitor_gate_options(recipe_parser)

    process_exit = subparsers.add_parser(
        "process-exit",
        help="arm a durable schema-v2 wake for one exact same-user process identity",
    )
    process_exit.add_argument("--idempotency-key")
    process_exit.add_argument(
        "--max-attempts",
        type=bounded_attempt_count,
        default=3,
        help="maximum dispatch attempts (1-100; default: 3)",
    )
    process_exit.add_argument("pid", type=int)
    process_exit.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(process_exit)
    add_monitor_gate_options(process_exit)

    systemd_unit = subparsers.add_parser(
        "systemd-unit",
        help="configure and arm exact read-only user-systemd transition wakes",
    )
    systemd_unit_subparsers = systemd_unit.add_subparsers(
        dest="systemd_unit_command", required=True
    )
    systemd_source = systemd_unit_subparsers.add_parser(
        "source", help="manage nonsecret exact user-systemd source configuration"
    )
    systemd_source_subparsers = systemd_source.add_subparsers(
        dest="systemd_source_command", required=True
    )
    systemd_configure = systemd_source_subparsers.add_parser(
        "configure", help="persist one exact current-user unit allowlist"
    )
    systemd_configure.add_argument("--source", required=True, dest="source_instance")
    systemd_configure.add_argument("--unit", required=True)
    systemd_configure.add_argument(
        "--target-state", required=True, action="append", dest="target_states",
        choices=("active", "inactive", "failed"),
    )
    systemd_configure.add_argument(
        "--poll-timeout", type=int, default=5, dest="poll_timeout_seconds"
    )
    systemd_enabled = systemd_configure.add_mutually_exclusive_group(required=True)
    systemd_enabled.add_argument("--enabled", "--enable", action="store_true", dest="enabled")
    systemd_enabled.add_argument("--disabled", "--disable", action="store_false", dest="enabled")
    systemd_list = systemd_source_subparsers.add_parser(
        "list", help="list sanitized configured user-systemd sources"
    )
    systemd_list.add_argument("--json", action="store_true", dest="as_json")
    systemd_show = systemd_source_subparsers.add_parser(
        "show", help="show one sanitized configured user-systemd source"
    )
    systemd_show.add_argument("source_instance")
    systemd_show.add_argument("--json", action="store_true", dest="as_json")
    systemd_becomes = systemd_unit_subparsers.add_parser(
        "becomes", help="wake after the exact configured unit transitions to a target state"
    )
    systemd_becomes.add_argument("--source", required=True, dest="source_instance")
    systemd_becomes.add_argument(
        "--state", required=True, choices=("active", "inactive", "failed"),
        dest="target_state",
    )
    systemd_becomes.add_argument("--idempotency-key")
    systemd_becomes.add_argument(
        "--max-attempts", type=bounded_attempt_count, default=3,
        help="maximum dispatch attempts (1-100; default: 3)",
    )
    systemd_becomes.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(systemd_becomes)
    add_monitor_gate_options(systemd_becomes)

    github_ci = subparsers.add_parser(
        "github-ci", help="configure and arm durable GitHub Actions completion wakes"
    )
    github_ci_subparsers = github_ci.add_subparsers(dest="github_ci_command", required=True)
    github_source = github_ci_subparsers.add_parser(
        "source", help="manage nonsecret GitHub source configuration"
    )
    github_source_subparsers = github_source.add_subparsers(
        dest="github_source_command", required=True
    )
    github_source_configure = github_source_subparsers.add_parser(
        "configure", help="persist one bounded GitHub.com source allowlist"
    )
    github_source_configure.add_argument("--source", required=True, dest="source_instance")
    github_source_configure.add_argument("--repository", required=True)
    github_source_configure.add_argument("--repository-id", required=True, type=int)
    github_source_configure.add_argument("--workflow-id", required=True, type=int)
    github_source_configure.add_argument("--ref", required=True, action="append", dest="refs")
    github_source_configure.add_argument(
        "--conclusion", required=True, action="append", dest="conclusions",
        choices=("success", "failure", "cancelled", "timed_out", "neutral", "skipped", "action_required", "startup_failure"),
    )
    github_source_configure.add_argument(
        "--credential-ref", default="GH_CLI",
        help="credential reference (default: GH_CLI; never a credential value)",
    )
    enabled = github_source_configure.add_mutually_exclusive_group(required=True)
    enabled.add_argument("--enabled", "--enable", action="store_true", dest="enabled")
    enabled.add_argument("--disabled", "--disable", action="store_false", dest="enabled")
    github_source_list = github_source_subparsers.add_parser(
        "list", help="list sanitized configured GitHub sources"
    )
    github_source_list.add_argument("--json", action="store_true", dest="as_json")
    github_source_show = github_source_subparsers.add_parser(
        "show", help="show one sanitized configured GitHub source"
    )
    github_source_show.add_argument("source_instance")
    github_source_show.add_argument("--json", action="store_true", dest="as_json")
    github_completed = github_ci_subparsers.add_parser(
        "completed", help="wake on one verified configured workflow completion"
    )
    github_completed.add_argument("--source", required=True, dest="source_instance")
    github_completed.add_argument("--ref", required=True)
    github_completed.add_argument(
        "--conclusion", required=True, action="append", dest="conclusions"
    )
    github_completed.add_argument("--idempotency-key")
    github_completed.add_argument(
        "--max-attempts", type=one_attempt_count, default=1,
        help="maximum dispatch attempts; GitHub CI wakes require exactly 1",
    )
    github_completed.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(github_completed)
    add_monitor_gate_options(github_completed)

    http_json = subparsers.add_parser(
        "http-json", help="configure and arm generic HTTP/JSON completion wakes"
    )
    http_json_subparsers = http_json.add_subparsers(dest="http_json_command", required=True)
    http_json_source = http_json_subparsers.add_parser(
        "source", help="manage bounded HTTP/JSON status sources"
    )
    http_json_source_subparsers = http_json_source.add_subparsers(
        dest="http_json_source_command", required=True
    )
    http_json_configure = http_json_source_subparsers.add_parser("configure")
    http_json_configure.add_argument("--source", required=True, dest="source_instance")
    http_json_configure.add_argument("--url", required=True)
    http_json_configure.add_argument("--state-pointer", required=True)
    http_json_configure.add_argument("--event-id-pointer", default=None)
    http_json_configure.add_argument("--completed-at-pointer", default=None)
    http_json_configure.add_argument("--terminal-value", required=True, action="append", dest="terminal_values")
    http_json_configure.add_argument(
        "--selector", action="append", default=[],
        help="bounded JSON Pointer equality selector in POINTER=VALUE form",
    )
    http_json_configure.add_argument("--credential-ref", default=None)
    http_json_configure.add_argument("--allow-non-loopback", action="store_true")
    http_json_configure.add_argument("--request-timeout", type=int, default=10, dest="request_timeout_seconds")
    http_json_configure.add_argument("--max-response-bytes", type=int, default=1_048_576)
    http_json_enabled = http_json_configure.add_mutually_exclusive_group(required=True)
    http_json_enabled.add_argument("--enabled", "--enable", action="store_true", dest="enabled")
    http_json_enabled.add_argument("--disabled", "--disable", action="store_false", dest="enabled")
    http_json_list = http_json_source_subparsers.add_parser("list")
    http_json_list.add_argument("--json", action="store_true", dest="as_json")
    http_json_show = http_json_source_subparsers.add_parser("show")
    http_json_show.add_argument("source_instance")
    http_json_show.add_argument("--json", action="store_true", dest="as_json")
    http_json_check = http_json_source_subparsers.add_parser("check")
    http_json_check.add_argument("source_instance")
    http_json_check.add_argument("--json", action="store_true", dest="as_json")
    http_json_remove = http_json_source_subparsers.add_parser("remove")
    http_json_remove.add_argument("source_instance")
    http_json_completed = http_json_subparsers.add_parser(
        "completed", help="wake when one configured HTTP/JSON job reaches a terminal value"
    )
    http_json_completed.add_argument("--source", required=True, dest="source_instance")
    http_json_completed.add_argument("--idempotency-key")
    http_json_completed.add_argument("--max-attempts", type=bounded_attempt_count, default=3)
    http_json_completed.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(http_json_completed)
    add_monitor_gate_options(http_json_completed)

    github_webhook = subparsers.add_parser(
        "github-webhook", help="configure and operate one bounded local GitHub webhook listener"
    )
    github_webhook_subparsers = github_webhook.add_subparsers(
        dest="github_webhook_command", required=True
    )
    webhook_source = github_webhook_subparsers.add_parser(
        "source", help="manage owner-only nonsecret webhook listener configuration"
    )
    webhook_source_subparsers = webhook_source.add_subparsers(
        dest="github_webhook_source_command", required=True
    )
    webhook_configure = webhook_source_subparsers.add_parser("configure")
    webhook_configure.add_argument("--source", required=True, dest="source_instance")
    webhook_configure.add_argument("--bind-address", default="127.0.0.1")
    webhook_configure.add_argument("--port", type=int, default=8820)
    webhook_configure.add_argument(
        "--allow-non-loopback", action="store_true",
        help="explicitly allow one non-loopback numeric bind address",
    )
    webhook_configure.add_argument("--secret-ref", required=True)
    webhook_configure.add_argument("--previous-secret-ref")
    webhook_configure.add_argument("--max-body-bytes", type=int, default=262_144)
    webhook_configure.add_argument("--max-connections", type=int, default=8)
    webhook_configure.add_argument("--request-timeout", type=float, default=15.0, dest="request_timeout_seconds")
    webhook_configure.add_argument("--operation-timeout", type=float, default=8.0, dest="operation_timeout_seconds")
    webhook_configure.add_argument("--shutdown-timeout", type=float, default=10.0, dest="shutdown_timeout_seconds")
    webhook_enabled = webhook_configure.add_mutually_exclusive_group(required=True)
    webhook_enabled.add_argument("--enabled", action="store_true", dest="enabled")
    webhook_enabled.add_argument("--disabled", action="store_false", dest="enabled")
    webhook_list = webhook_source_subparsers.add_parser("list")
    webhook_list.add_argument("--json", action="store_true", dest="as_json")
    webhook_show = webhook_source_subparsers.add_parser("show")
    webhook_show.add_argument("source_instance")
    webhook_show.add_argument("--json", action="store_true", dest="as_json")
    webhook_service = github_webhook_subparsers.add_parser("service")
    webhook_service_subparsers = webhook_service.add_subparsers(dest="github_webhook_service_command", required=True)
    for action in ("install", "start", "stop", "status", "uninstall"):
        service_action = webhook_service_subparsers.add_parser(action)
        service_action.add_argument("--source", required=True, dest="source_instance")
        service_action.add_argument("--executable-path")
        service_action.add_argument("--unit-dir", type=Path)
        service_action.add_argument("--log-path", type=Path)
        service_action.add_argument("--json", action="store_true", dest="as_json")
        if action == "install":
            service_action.add_argument("--no-start", action="store_true")
    for action in ("readiness", "support"):
        probe = github_webhook_subparsers.add_parser(action)
        probe.add_argument("--source", required=True, dest="source_instance")
        probe.add_argument("--json", action="store_true", dest="as_json")
    webhook_health = github_webhook_subparsers.add_parser(
        "health", help="project independent managed webhook health planes"
    )
    webhook_health.add_argument("--source", required=True, dest="source_instance")
    webhook_health.add_argument("--json", action="store_true", dest="as_json")
    webhook_rotation = github_webhook_subparsers.add_parser(
        "rotation", help="preview sanitized managed-secret rotation state"
    )
    webhook_rotation_subparsers = webhook_rotation.add_subparsers(
        dest="github_webhook_rotation_command", required=True
    )
    rotation_status = webhook_rotation_subparsers.add_parser("status")
    rotation_status.add_argument("--source", required=True, dest="source_instance")
    rotation_status.add_argument("--json", action="store_true", dest="as_json")
    rotation_preview = webhook_rotation_subparsers.add_parser("preview")
    rotation_preview.add_argument("--source", required=True, dest="source_instance")
    rotation_preview.add_argument("--target-generation", required=True, type=int)
    rotation_preview.add_argument("--overlap-seconds", required=True, type=int)
    rotation_preview.add_argument("--json", action="store_true", dest="as_json")
    webhook_cleanup = github_webhook_subparsers.add_parser(
        "cleanup", help="preview or explicitly apply exact managed cleanup"
    )
    webhook_cleanup_subparsers = webhook_cleanup.add_subparsers(
        dest="github_webhook_cleanup_command", required=True
    )
    for action in ("preview", "apply"):
        cleanup = webhook_cleanup_subparsers.add_parser(action)
        cleanup.add_argument("--source", required=True, dest="source_instance")
        cleanup.add_argument("--action", required=True, choices=("disable", "delete"))
        cleanup.add_argument("--json", action="store_true", dest="as_json")
        if action == "apply":
            cleanup.add_argument("--expected-intent", required=True)
    webhook_binding = github_webhook_subparsers.add_parser(
        "binding", help="manage one exact provider webhook binding"
    )
    webhook_binding_subparsers = webhook_binding.add_subparsers(
        dest="github_webhook_binding_command", required=True
    )
    binding_configure = webhook_binding_subparsers.add_parser(
        "configure", help="persist a secret-free desired webhook binding"
    )
    binding_configure.add_argument("--source", required=True, dest="source_instance")
    binding_configure.add_argument("--installation-id", required=True)
    binding_configure.add_argument("--repository", required=True)
    binding_configure.add_argument("--repository-id", required=True, type=int)
    binding_configure.add_argument("--callback-url", required=True)
    binding_configure.add_argument(
        "--credential-ref", default="GH_CLI", dest="provider_credential_ref",
        help="provider credential reference (default: GH_CLI; never a credential value)",
    )
    binding_configure.add_argument("--json", action="store_true", dest="as_json")
    for action in ("show", "status", "reconcile"):
        binding_action = webhook_binding_subparsers.add_parser(action)
        binding_action.add_argument("source_instance")
        binding_action.add_argument("--json", action="store_true", dest="as_json")
        if action == "reconcile":
            arm = binding_action.add_mutually_exclusive_group()
            arm.add_argument("--dry-run", action="store_false", dest="apply")
            arm.add_argument("--apply", action="store_true", dest="apply")
            binding_action.set_defaults(apply=False)

    pid = subparsers.add_parser("pid", help="create a wake when a process id exits")
    pid.add_argument("pid", type=int)
    pid.add_argument("prompt", nargs=argparse.REMAINDER)
    add_target_options(pid)
    add_monitor_gate_options(pid)

    list_cmd = subparsers.add_parser("list", help="list wake records")
    from .wake_control import add_scope_options
    add_scope_options(list_cmd)
    list_cmd.add_argument("--json", action="store_true", dest="as_json")
    list_cmd.add_argument("--archived", action="store_true", help="include archived wake records")

    status = subparsers.add_parser("status", help="summarize wake records by state")
    status.add_argument("--json", action="store_true", dest="as_json")

    show = subparsers.add_parser("show", help="show one wake record")
    show.add_argument("wake_id")
    show.add_argument(
        "--signal-state",
        action="store_true",
        help="inspect bounded signal authority without evaluating it",
    )

    cancel = subparsers.add_parser("cancel", help="cancel a pending or firing wake")
    cancel.add_argument("wake_id", nargs="?")
    cancel.add_argument("--all", action="store_true", help="cancel all eligible wakes in the selected scope")
    cancel.add_argument("--json", action="store_true", dest="as_json")
    add_scope_options(cancel)

    archive = subparsers.add_parser("archive", help="archive terminal wake records")
    archive.add_argument("wake_id", nargs="?", help="specific wake id to archive")
    archive.add_argument("--all-terminal", action="store_true", help="archive all submitted, failed, cancelled, and expired wakes")

    cleanup = subparsers.add_parser("cleanup", help="preview or delete old archived wake records")
    cleanup.add_argument("--older-than", default="30d", help="archive retention window; defaults to 30d")
    cleanup.add_argument("--delete", action="store_true", help="delete matching archived records; default is dry-run")
    cleanup.add_argument("--archive-terminal", action="store_true", help="archive terminal records before evaluating cleanup")
    cleanup.add_argument("--json", action="store_true", dest="as_json")

    support = subparsers.add_parser(
        "support", help="inspect or export sanitized signal support evidence"
    )
    support_subparsers = support.add_subparsers(dest="support_command", required=True)
    support_export = support_subparsers.add_parser(
        "export", help="write a deterministic bounded signal support artifact"
    )
    support_export.add_argument("--output", type=Path, required=True)
    support_export.add_argument("--max-wakes", type=int, default=50)
    support_export.add_argument("--max-bytes", type=int, default=262_144)
    support_export.add_argument("--json", action="store_true", dest="as_json")

    schema = subparsers.add_parser("schema", help="show wake record schema version and compatibility policy")
    schema.add_argument("--json", action="store_true", dest="as_json")

    service = subparsers.add_parser("service", help="manage a user-scoped codex-waked service")
    service_subparsers = service.add_subparsers(dest="service_command", required=True)

    service_install = service_subparsers.add_parser("install", help="install and start a user systemd service")
    add_service_options(service_install)
    service_install.add_argument("--no-start", action="store_true", help="write the unit but do not enable or start it")
    service_install.add_argument(
        "--no-dispatch", action="store_false", dest="dispatch_enabled",
        help="persist a daemon unit that evaluates wakes without dispatching them",
    )

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
    supervisor_enroll.add_argument("--codex-path", help="stable Codex executable path to record for this root")
    supervisor_enroll.add_argument("--openclaw-path", help="stable OpenClaw executable path to record for this root")
    supervisor_enroll.add_argument("--poll-interval", type=float, default=None, help="per-root polling seconds; defaults to supervisor interval")
    supervisor_enroll.add_argument("--disabled", action="store_true", help="register the root disabled")

    supervisor_unenroll = supervisor_subparsers.add_parser("unenroll", help="remove a wake root from supervisor monitoring")
    add_supervisor_options(supervisor_unenroll)
    supervisor_unenroll.add_argument("--wake-root", dest="unenroll_wake_root", type=Path, default=None)
    supervisor_unenroll.add_argument("--root-id")

    supervisor_reconcile = supervisor_subparsers.add_parser(
        "reconcile", help="release an exact held poll after inspecting uncertain effects")
    add_supervisor_options(supervisor_reconcile)
    supervisor_reconcile.add_argument("--root-id", required=True)
    supervisor_reconcile.add_argument("--expected-token", required=True)
    supervisor_reconcile.add_argument("--acknowledge-uncertain-effects", action="store_true", required=True)

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

    from .account_shortcuts import register as register_shortcuts
    register_shortcuts(parser)
    from .command_contract import apply_help
    from .unified_contract import apply_cli
    return apply_cli(apply_help(parser))


def add_target_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--legacy-tmux', action='store_true',
                        help='explicitly select compatibility tmux delivery; prefer native for time/file wakes')
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
    add_active_writer_retry_option(parser)


def add_active_writer_retry_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--retry-active-writer",
        action="store_true",
        help="retry with bounded backoff if the app-server thread has an active writer; default is terminal failure",
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


def add_service_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="systemd user unit name; defaults to codex-wake-<repo>.service")
    parser.add_argument("--repo-root", type=Path, default=None, help="repo root for the service; defaults to current directory")
    parser.add_argument("--interval", type=float, default=1.0, help="daemon poll interval in seconds")
    parser.add_argument("--daemon-path", help="stable codex-waked executable path; defaults to PATH resolution")
    parser.add_argument("--codex-path", help="stable Codex executable path to persist for app-server dispatch")
    parser.add_argument(
        "--github-credential-file", type=Path, default=None,
        help="owner-only systemd EnvironmentFile containing referenced GitHub credentials",
    )
    parser.add_argument("--log-path", type=Path, default=None, help="service log path")


def add_supervisor_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="systemd user unit name; defaults to codex-wake-supervisor.service")
    parser.add_argument("--interval", type=float, default=1.0, help="supervisor poll interval in seconds")
    parser.add_argument("--max-workers", type=int, default=4, help="maximum isolated poll workers (2-32)")
    parser.add_argument("--poll-timeout", type=float, default=300.0, help="hold roots whose polling exceeds this many seconds")
    parser.add_argument("--codex-wake-path", help="stable codex-wake executable path; defaults to PATH resolution")
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
    observation = None
    if args.network_time:
        from .network_wakes import read_time, creation_time
        observation = read_time()
        now = creation_time(observation)
    else:
        now = utc_now()
    due = now + parse_duration(args.duration)
    predicate = {"type": "not_before", "due_at": format_utc(due)}
    return create_record(args.prompt, predicate, root, now, args, time_observation=observation)


def create_at(args: argparse.Namespace, root: Path) -> int:
    due = parse_timestamp(args.timestamp)
    observation = None
    if args.network_time:
        from .network_wakes import read_time, creation_time, precise_deadline
        observation = read_time()
        now = creation_time(observation)
        due = precise_deadline(args.timestamp)
        stamp = due.isoformat().replace('+00:00','Z')
    else:
        now, stamp = utc_now(), format_utc(due)
    predicate = {"type": "not_before", "due_at": stamp}
    return create_record(args.prompt, predicate, root, now, args, time_observation=observation)


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
    target: dict[str, object] = {
        "transport": "app-server",
        "endpoint": args.endpoint,
        "thread_id": args.thread_id,
    }
    if args.retry_active_writer:
        target["retry_active_writer"] = True
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


def create_filesystem_signal(args: argparse.Namespace, root: Path) -> int:
    from .event_wake import EventWake
    from .filesystem_signals import FilesystemSignalAdapter
    from .signal_records import WakeRecordPublisher, signal_journal_path
    from .signal_store import SQLiteSignalModule
    from .signals import Degraded, Invalid, Resume, WakeIntent

    try:
        adapter = FilesystemSignalAdapter(Path.cwd(), args.path)
    except ValueError as exc:
        raise WakeError(str(exc)) from None
    prompt = normalize_prompt(args.prompt)
    if getattr(args, "require_monitor", False):
        readiness = monitor_readiness(wake_root=root, repo_root=Path.cwd())
        require_monitor_ready(readiness)
    now = utc_now()
    runtime = SQLiteSignalModule(
        signal_journal_path(root),
        record_publisher=WakeRecordPublisher.for_managed_reader(root),
    )
    result = EventWake(
        runtime,
        adapters=(adapter,),
        clock=lambda: now,
        id_factory=lambda: f"wake_{uuid.uuid4().hex}",
    ).register(
        WakeIntent(
            adapter.request(args.filesystem_command),
            Resume(prompt, Path.cwd(), target_for_args(args)),
            max_attempts=args.max_attempts,
        ),
        idempotency_key=args.idempotency_key or f"filesystem:{uuid.uuid4().hex}",
    )
    if isinstance(result, Degraded):
        raise WakeError(f"filesystem signal registration unavailable: {result.code}")
    if isinstance(result, Invalid):
        raise WakeError("filesystem signal registration is invalid")
    path = root / "pending" / f"{result.wake_id}.json"
    print(f"{result.wake_id} {path}")
    return 0


def create_process_exit_signal(args: argparse.Namespace, root: Path) -> int:
    from .event_wake import EventWake
    from .process_signals import production_process_exit_adapter
    from .signal_records import WakeRecordPublisher, signal_journal_path
    from .signal_store import SQLiteSignalModule
    from .signals import Degraded, Invalid, Resume, WakeIntent

    prompt = normalize_prompt(args.prompt)
    if getattr(args, "require_monitor", False):
        readiness = monitor_readiness(wake_root=root, repo_root=Path.cwd())
        require_monitor_ready(readiness)
    try:
        adapter = production_process_exit_adapter(args.pid)
    except (OSError, TypeError, ValueError) as exc:
        raise WakeError(f"process exit source is unavailable: {exc}") from None
    now = utc_now()
    runtime = SQLiteSignalModule(
        signal_journal_path(root),
        record_publisher=WakeRecordPublisher.for_managed_reader(root),
    )
    result = EventWake(
        runtime,
        adapters=(adapter,),
        clock=lambda: now,
        id_factory=lambda: f"wake_{uuid.uuid4().hex}",
    ).register(
        WakeIntent(
            adapter.request(),
            Resume(prompt, Path.cwd(), target_for_args(args)),
            max_attempts=args.max_attempts,
        ),
        idempotency_key=args.idempotency_key or f"process-exit:{uuid.uuid4().hex}",
    )
    if isinstance(result, Degraded):
        raise WakeError(f"process exit signal registration unavailable: {result.code}")
    if isinstance(result, Invalid):
        raise WakeError("process exit signal registration is invalid")
    path = root / "pending" / f"{result.wake_id}.json"
    print(f"{result.wake_id} {path}")
    return 0


def systemd_unit_command(args: argparse.Namespace, root: Path) -> int:
    from .systemd_source_config import SystemdSourceConfig, SystemdSourceStore

    store = SystemdSourceStore(root)
    if args.systemd_unit_command == "source":
        if args.systemd_source_command == "configure":
            try:
                source = store.configure(SystemdSourceConfig(
                    source_instance=args.source_instance,
                    unit=args.unit,
                    owner_uid=os.geteuid(),
                    target_states=frozenset(args.target_states),
                    enabled=args.enabled,
                    poll_timeout_seconds=args.poll_timeout_seconds,
                ))
            except (OSError, TypeError, ValueError) as exc:
                raise WakeError(f"systemd source configuration is invalid: {exc}") from None
            print(f"source={source.source_instance}")
            print(f"enabled={str(source.enabled).lower()}")
            print(f"config={store.path}")
            return 0
        try:
            sources = store.sources()
            if args.systemd_source_command == "show":
                selected = [item for item in sources if item.source_instance == args.source_instance]
                if not selected:
                    raise WakeError(f"systemd source is not configured: {args.source_instance}")
                summaries = [_systemd_source_summary(selected[0])]
            else:
                summaries = [_systemd_source_summary(item) for item in sources]
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        payload = summaries[0] if args.systemd_source_command == "show" else {"sources": summaries}
        if args.as_json:
            print(json.dumps(payload, sort_keys=True))
        elif args.systemd_source_command == "show":
            for key, value in payload.items():
                print(f"{key}={value}")
        else:
            for source in summaries:
                print(f"{source['source_instance']} {source['unit']} enabled={str(source['enabled']).lower()}")
        return 0

    from .event_wake import EventWake
    from .runtime_signals import RuntimeSourceRegistry
    from .signal_records import WakeRecordPublisher, signal_journal_path
    from .signal_store import SQLiteSignalModule
    from .signals import Degraded, Invalid, Resume, WakeIntent
    from .systemd_signals import SystemdReadCapability, SystemdSignalAdapter, SystemdUserBusBackend

    try:
        source = store.registry().select(args.source_instance)
        adapter = SystemdSignalAdapter(
            source,
            SystemdUserBusBackend(),
            RuntimeSourceRegistry({
                "systemd.unit": lambda descriptor: _configured_systemd_descriptor(
                    store, args.source_instance, descriptor
                )
            }),
            SystemdReadCapability("user", os.geteuid()),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise WakeError(f"systemd source is unavailable: {exc}") from None
    prompt = normalize_prompt(args.prompt)
    if getattr(args, "require_monitor", False):
        readiness = monitor_readiness(wake_root=root, repo_root=Path.cwd())
        require_monitor_ready(readiness)
    now = utc_now()
    runtime = SQLiteSignalModule(
        signal_journal_path(root),
        record_publisher=WakeRecordPublisher.for_managed_reader(root),
    )
    result = EventWake(
        runtime,
        adapters=(adapter,),
        clock=lambda: now,
        id_factory=lambda: f"wake_{uuid.uuid4().hex}",
    ).register(
        WakeIntent(
            adapter.request(args.target_state),
            Resume(prompt, Path.cwd(), target_for_args(args)),
            max_attempts=args.max_attempts,
        ),
        idempotency_key=args.idempotency_key or f"systemd-unit:{uuid.uuid4().hex}",
    )
    if isinstance(result, Degraded):
        raise WakeError(f"systemd signal registration unavailable: {result.code}")
    if isinstance(result, Invalid):
        raise WakeError("systemd signal registration is invalid")
    path = root / "pending" / f"{result.wake_id}.json"
    print(f"{result.wake_id} {path}")
    return 0


def _systemd_source_summary(source) -> dict[str, object]:
    return {
        "source_instance": source.source_instance,
        "unit": source.unit,
        "owner_uid": source.owner_uid,
        "target_states": sorted(source.target_states),
        "enabled": source.enabled,
        "poll_timeout_seconds": source.poll_timeout_seconds,
    }


def _configured_systemd_descriptor(store, source_instance: str, descriptor) -> bool:
    try:
        current = store.registry().select(source_instance)
        return any(
            descriptor == current.descriptor(state)
            for state in current.target_states
        )
    except (OSError, TypeError, ValueError):
        return False


def github_ci_command(args: argparse.Namespace, root: Path) -> int:
    from .event_wake import EventWake
    from .github_polling import GitHubPollingAdapter, GitHubPollingConfig
    from .github_source_config import GitHubSourceStore
    from .signal_records import WakeRecordPublisher, signal_journal_path
    from .signal_store import SQLiteSignalModule
    from .signals import Degraded, Invalid, Resume, WakeIntent

    store = GitHubSourceStore(root)
    if args.github_ci_command == "completed":
        try:
            source = store.registry().select(args.source_instance)
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        adapter = GitHubPollingAdapter(source, object())
        request = adapter.request(ref=args.ref, conclusions=tuple(args.conclusions))
        if isinstance(request, Invalid):
            raise WakeError("GitHub CI completion is outside the configured allowlist")
        prompt = normalize_prompt(args.prompt)
        if getattr(args, "require_monitor", False):
            readiness = monitor_readiness(wake_root=root, repo_root=Path.cwd())
            require_monitor_ready(readiness)
        now = utc_now()
        runtime = SQLiteSignalModule(
            signal_journal_path(root),
            record_publisher=WakeRecordPublisher.for_managed_reader(root),
        )
        result = EventWake(
            runtime,
            adapters=(adapter,),
            clock=lambda: now,
            id_factory=lambda: f"wake_{uuid.uuid4().hex}",
        ).register(
            WakeIntent(
                request,
                Resume(prompt, Path.cwd(), target_for_args(args)),
                max_attempts=args.max_attempts,
            ),
            idempotency_key=args.idempotency_key or f"github-ci:{uuid.uuid4().hex}",
        )
        if isinstance(result, Degraded):
            raise WakeError(f"GitHub CI signal registration unavailable: {result.code}")
        if isinstance(result, Invalid):
            raise WakeError("GitHub CI signal registration is invalid")
        path = root / "pending" / f"{result.wake_id}.json"
        print(f"{result.wake_id} {path}")
        return 0
    if args.github_ci_command != "source":
        raise WakeError("unsupported github-ci command")
    if args.github_source_command in {"list", "show"}:
        try:
            sources = store.sources()
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        if args.github_source_command == "show":
            sources = tuple(
                source for source in sources if source.source_instance == args.source_instance
            )
            if not sources:
                raise WakeError("GitHub source is not configured")
        summaries = [_github_source_summary(source) for source in sources]
        if getattr(args, "as_json", False):
            print(json.dumps(summaries[0] if args.github_source_command == "show" else {"sources": summaries}, sort_keys=True))
        else:
            for summary in summaries:
                print(
                    f"source={summary['source_instance']} enabled={str(summary['enabled']).lower()} "
                    f"repository={summary['repository']} workflow_id={summary['workflow_id']}"
                )
        return 0
    if args.github_source_command != "configure":
        raise WakeError("unsupported github-ci source command")
    if (
        not isinstance(args.credential_ref, str)
        or not args.credential_ref
        or not args.credential_ref.isascii()
        or not args.credential_ref.replace("_", "A").isalnum()
        or not args.credential_ref[0].isalpha()
        or args.credential_ref.upper() != args.credential_ref
    ):
        raise WakeError("credential reference must be an uppercase environment variable name")
    source = GitHubPollingConfig(
        source_instance=args.source_instance,
        repository=args.repository,
        repository_id=args.repository_id,
        workflow_id=args.workflow_id,
        refs=frozenset(args.refs),
        conclusions=frozenset(args.conclusions),
        credential_ref=args.credential_ref,
        enabled=args.enabled,
        evidence_mode="positive_only",
    )
    try:
        store.configure(source)
    except ValueError as exc:
        raise WakeError(str(exc)) from None
    print(f"source={source.source_instance}")
    print(f"enabled={str(source.enabled).lower()}")
    print(f"config={store.path}")
    return 0


def _github_source_summary(source) -> dict[str, object]:
    return {
        "source_instance": source.source_instance,
        "repository": source.repository,
        "repository_id": source.repository_id,
        "workflow_id": source.workflow_id,
        "refs": sorted(source.refs),
        "conclusions": sorted(source.conclusions),
        "enabled": source.enabled,
        "hostname": source.hostname,
        "evidence_mode": source.evidence_mode,
    }


def http_json_command(args: argparse.Namespace, root: Path) -> int:
    from .event_wake import EventWake
    from .http_json_signals import HTTPJSONClient, HTTPJSONSignalAdapter
    from .http_json_source_config import HTTPJSONSourceConfig, HTTPJSONSourceStore
    from .signal_records import WakeRecordPublisher, signal_journal_path
    from .signal_store import SQLiteSignalModule
    from .signals import Degraded, Invalid, Resume, WakeIntent

    store = HTTPJSONSourceStore(root)
    if args.http_json_command == "completed":
        try:
            source = store.select(args.source_instance)
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        adapter = HTTPJSONSignalAdapter(source, HTTPJSONClient(source))
        prompt = (
            normalize_prompt(args.prompt)
            if args.prompt
            else (
                f"HTTP JSON source {source.source_instance} reached a configured terminal state. "
                f"Verify the authoritative status at {source.url} before acting."
            )
        )
        if getattr(args, "require_monitor", False):
            require_monitor_ready(monitor_readiness(wake_root=root, repo_root=Path.cwd()))
        now = utc_now()
        runtime = SQLiteSignalModule(
            signal_journal_path(root),
            record_publisher=WakeRecordPublisher.for_managed_reader(root),
        )
        result = EventWake(
            runtime,
            adapters=(adapter,),
            clock=lambda: now,
            id_factory=lambda: f"wake_{uuid.uuid4().hex}",
        ).register(
            WakeIntent(
                adapter.request(),
                Resume(prompt, Path.cwd(), target_for_args(args)),
                max_attempts=args.max_attempts,
            ),
            idempotency_key=args.idempotency_key or f"http-json:{uuid.uuid4().hex}",
        )
        if isinstance(result, Degraded):
            raise WakeError(f"HTTP JSON signal registration unavailable: {result.code}")
        if isinstance(result, Invalid):
            raise WakeError("HTTP JSON signal registration is invalid")
        path = root / "pending" / f"{result.wake_id}.json"
        print(f"{result.wake_id} {path}")
        return 0

    if args.http_json_command != "source":
        raise WakeError("unsupported http-json command")
    command = args.http_json_source_command
    if command in {"list", "show"}:
        try:
            sources = store.sources()
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        if command == "show":
            sources = tuple(item for item in sources if item.source_instance == args.source_instance)
            if not sources:
                raise WakeError("HTTP JSON source is not configured")
        summaries = [_http_json_source_summary(item) for item in sources]
        if args.as_json:
            print(json.dumps(summaries[0] if command == "show" else {"sources": summaries}, sort_keys=True))
        else:
            for item in summaries:
                print(f"source={item['source_instance']} enabled={str(item['enabled']).lower()} url={item['url']}")
        return 0
    if command == "remove":
        active = [
            item for item in iter_records(root)
            if item.record.get("status") in {"pending", "firing"}
            and isinstance(item.record.get("predicate"), dict)
            and item.record["predicate"].get("source") == "http-json"
            and item.record["predicate"].get("source_instance") == args.source_instance
        ]
        if active:
            raise WakeError("HTTP JSON source has active wakes; cancel them before removal")
        try:
            removed = store.remove(args.source_instance)
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        if not removed:
            raise WakeError("HTTP JSON source is not configured")
        print(f"removed={args.source_instance}")
        return 0
    if command == "check":
        try:
            source = store.select(args.source_instance)
            event = HTTPJSONSignalAdapter(source, HTTPJSONClient(source)).observe(utc_now())
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        payload = {
            "source_instance": source.source_instance,
            "reachable": True,
            "terminal": event is not None,
            "state": event.state if event else None,
            "event_id": event.event_id if event else None,
        }
        if args.as_json:
            print(json.dumps(payload, sort_keys=True))
        else:
            for key, value in payload.items():
                print(f"{key}={value if value is not None else 'none'}")
        return 0
    if command != "configure":
        raise WakeError("unsupported http-json source command")
    selectors = []
    for raw in args.selector:
        if "=" not in raw:
            raise WakeError("selector must use POINTER=VALUE")
        pointer, value = raw.split("=", 1)
        selectors.append((pointer, value))
    try:
        source = HTTPJSONSourceConfig(
            source_instance=args.source_instance,
            url=args.url,
            state_pointer=args.state_pointer,
            event_id_pointer=args.event_id_pointer,
            terminal_values=frozenset(args.terminal_values),
            selectors=tuple(selectors),
            completed_at_pointer=args.completed_at_pointer,
            credential_ref=args.credential_ref,
            allow_non_loopback=args.allow_non_loopback,
            enabled=args.enabled,
            request_timeout_seconds=args.request_timeout_seconds,
            max_response_bytes=args.max_response_bytes,
        )
        store.configure(source)
    except ValueError as exc:
        raise WakeError(str(exc)) from None
    print(f"source={source.source_instance}")
    print(f"enabled={str(source.enabled).lower()}")
    print(f"config={store.path}")
    return 0


def _http_json_source_summary(source) -> dict[str, object]:
    return {
        "source_instance": source.source_instance,
        "url": source.url,
        "state_pointer": source.state_pointer,
        "event_id_pointer": source.event_id_pointer,
        "terminal_values": sorted(source.terminal_values),
        "selectors": [[pointer, value] for pointer, value in source.selectors],
        "completed_at_pointer": source.completed_at_pointer,
        "credential_configured": source.credential_ref is not None,
        "allow_non_loopback": source.allow_non_loopback,
        "enabled": source.enabled,
        "request_timeout_seconds": source.request_timeout_seconds,
        "max_response_bytes": source.max_response_bytes,
    }


def github_webhook_command(
    args: argparse.Namespace, root: Path, *, provider_factory=None,
    cleanup_local_factory=None,
) -> int:
    from .webhook_lifecycle import (
        WebhookListenerConfig, WebhookListenerStore, build_webhook_service_config,
        disable_webhook_listener, install_webhook_service, listener_summary, start_webhook_service, stop_webhook_service,
        uninstall_webhook_service, webhook_readiness, webhook_service_name, webhook_service_status, webhook_support,
    )

    store = WebhookListenerStore(root)
    if args.github_webhook_command == "rotation":
        from .managed_webhook_rotation_preview import ManagedWebhookRotationPreviewer

        try:
            previewer = ManagedWebhookRotationPreviewer(root)
            action = args.github_webhook_rotation_command
            result = previewer.preview(
                args.source_instance, now=int(utc_now().timestamp()),
                target_generation=(args.target_generation if action == "preview" else None),
                overlap_seconds=(args.overlap_seconds if action == "preview" else None),
            ).to_dict()
        except ValueError as exc:
            raise WakeError(str(exc)) from None
        if args.as_json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(
                f"source={result['source_instance']} phase={result['phase']} "
                f"action={result['next_action']} deadline={result['deadline_state']}"
            )
        return 0 if result["next_action"] not in {"BLOCKED", "ROLLBACK_REQUIRED"} else 1
    if args.github_webhook_command == "health":
        from .managed_webhook_cleanup import (
            LocalCleanupState, SystemdCleanupAdapter,
            classify_provider_object,
        )
        from .managed_webhook_health import (
            ListenerHealth,
            ProviderObjectHealth, project_health,
        )
        from .managed_webhook_health_evidence import ManagedWebhookHealthEvidenceStore
        from .managed_webhooks import ManagedWebhookStore

        try:
            binding = ManagedWebhookStore(root).load(args.source_instance)
            listener = store.select(binding.source_instance)
            local = (
                cleanup_local_factory(root)
                if cleanup_local_factory is not None
                else SystemdCleanupAdapter(root)
            )
            try:
                provider = _managed_webhook_provider(
                    binding, listener, provider_factory=provider_factory,
                )
                hooks = provider.list_hooks(repository_id=binding.repository_id)
                provider_object, _ = classify_provider_object(binding, hooks)
            except Exception:
                provider_object = ProviderObjectHealth.UNAVAILABLE
            try:
                local_state = local.observe(
                    listener=listener,
                    service_id=binding.service_id,
                )
            except Exception:
                local_state = LocalCleanupState.UNKNOWN
            local_health = {
                LocalCleanupState.OWNED_ACTIVE: ListenerHealth.READY,
                LocalCleanupState.PROVEN_ABSENT: ListenerHealth.DISABLED,
                LocalCleanupState.UNKNOWN: ListenerHealth.UNKNOWN,
            }[local_state]
            delivery, polling = ManagedWebhookHealthEvidenceStore(root).project(
                binding, now=int(utc_now().timestamp()),
            )
            result = project_health(
                generation=binding.generation,
                desired_fingerprint=binding.desired_fingerprint,
                local_listener=local_health,
                provider_object=provider_object,
                provider_delivery=delivery,
                polling_fallback=polling,
            ).to_dict()
            if args.as_json:
                print(json.dumps(result, sort_keys=True))
            else:
                print(
                    f"source={binding.source_instance} aggregate={result['aggregate']} "
                    f"provider={result['provider_object']} polling={result['polling_fallback']}"
                )
            return 0 if result["aggregate"] == "HEALTHY" else 1
        except ValueError as exc:
            raise WakeError(str(exc)) from None
    if args.github_webhook_command == "cleanup":
        from .managed_webhook_cleanup import (
            ManagedWebhookCleanupController, SystemdCleanupAdapter,
        )
        from .managed_webhook_health import CleanupAction
        from .managed_webhooks import ManagedWebhookStore

        try:
            binding = ManagedWebhookStore(root).load(args.source_instance)
            listener = store.select(binding.source_instance)
            provider = _managed_webhook_provider(
                binding, listener, provider_factory=provider_factory,
            )
            local = (
                cleanup_local_factory(root)
                if cleanup_local_factory is not None
                else SystemdCleanupAdapter(root)
            )
            controller = ManagedWebhookCleanupController(
                root, provider=provider, local=local,
            )
            plan = controller.preview(
                args.source_instance, CleanupAction(args.action.upper()),
            )
            result: dict[str, object] = {
                "mode": args.github_webhook_cleanup_command,
                **plan.to_dict(),
            }
            if args.github_webhook_cleanup_command == "apply":
                if args.expected_intent != plan.intent.intent_id:
                    raise ValueError("managed webhook cleanup plan is stale")
                result["tombstone"] = controller.execute(plan).to_dict()
            if args.as_json:
                print(json.dumps(result, sort_keys=True))
            else:
                print(
                    f"source={args.source_instance} action={args.action} "
                    f"eligibility={plan.eligibility.value} mode={result['mode']}"
                )
            return 0 if plan.eligibility.value == "ELIGIBLE_FOR_EXPLICIT_PLAN" else 1
        except ValueError as exc:
            raise WakeError(str(exc)) from None
    if args.github_webhook_command == "source":
        action = args.github_webhook_source_command
        try:
            if action == "configure":
                listener = WebhookListenerConfig(
                    source_instance=args.source_instance, address=args.bind_address, port=args.port,
                    secret_ref=args.secret_ref, previous_secret_ref=args.previous_secret_ref,
                    enabled=args.enabled, allow_non_loopback=args.allow_non_loopback,
                    max_body_bytes=args.max_body_bytes, max_connections=args.max_connections,
                    request_timeout_seconds=args.request_timeout_seconds,
                    operation_timeout_seconds=args.operation_timeout_seconds,
                    shutdown_timeout_seconds=args.shutdown_timeout_seconds,
                )
                current = next((item for item in store.listeners() if item.source_instance == listener.source_instance), None)
                listener = (disable_webhook_listener(store, listener) if current is not None and current.enabled and not listener.enabled
                            else store.configure(listener))
                print(f"source={listener.source_instance}\nenabled={str(listener.enabled).lower()}\nconfig={store.path}")
                return 0
            listeners = store.listeners()
            if action == "show":
                listeners = tuple(item for item in listeners if item.source_instance == args.source_instance)
                if not listeners:
                    raise WakeError("webhook listener is not configured")
            summaries = [listener_summary(item) for item in listeners]
            if args.as_json:
                print(json.dumps(summaries[0] if action == "show" else {"listeners": summaries}, sort_keys=True))
            else:
                for item in summaries:
                    print(f"source={item['source_instance']} enabled={str(item['enabled']).lower()} address={item['address']} port={item['port']} path={item['path']}")
            return 0
        except ValueError as exc:
            raise WakeError(str(exc)) from None
    if args.github_webhook_command == "binding":
        from .managed_webhooks import (
            LifecycleState, ManagedWebhookBinding, ManagedWebhookReconciler,
            ManagedWebhookStore, PlanAction,
        )

        managed_store = ManagedWebhookStore(root)
        action = args.github_webhook_binding_command
        try:
            if action == "configure":
                listener = store.select(args.source_instance)
                proposed = ManagedWebhookBinding(
                    owner_id=args.source_instance,
                    installation_id=args.installation_id,
                    canonical_root=str(Path(root).resolve()),
                    owner_uid=os.getuid(),
                    provider_host="api.github.com",
                    source_instance=args.source_instance,
                    repository=args.repository,
                    repository_id=args.repository_id,
                    callback_url=args.callback_url,
                    events=("workflow_run",),
                    service_id=webhook_service_name(args.source_instance),
                    executable_id="codex-wake-github-webhook",
                    provider_credential_ref=args.provider_credential_ref,
                    secret_generation=1,
                )
                current = next(
                    (item for item in managed_store.bindings() if item.owner_id == proposed.owner_id),
                    None,
                )
                if current is None:
                    saved = managed_store.save(proposed)
                else:
                    if current.installation_id != proposed.installation_id:
                        raise ValueError("managed webhook ownership is immutable")
                    proposed = replace(
                        current,
                        repository=proposed.repository,
                        repository_id=proposed.repository_id,
                        callback_url=proposed.callback_url,
                        events=proposed.events,
                        service_id=proposed.service_id,
                        executable_id=proposed.executable_id,
                        provider_credential_ref=proposed.provider_credential_ref,
                        desired_fingerprint="",
                    )
                    if proposed.desired_fingerprint == current.desired_fingerprint:
                        saved = current
                    else:
                        if current.lifecycle not in {LifecycleState.UNMANAGED, LifecycleState.ACTIVE}:
                            raise ValueError("managed webhook desired state cannot change while ownership is unresolved")
                        saved = managed_store.save(proposed, expected_generation=current.generation)
                result = _managed_webhook_binding_summary(saved, listener_configured=True)
                _print_managed_webhook_result(result, as_json=args.as_json)
                return 0

            binding = managed_store.load(args.source_instance)
            listener = next(
                (item for item in store.listeners() if item.source_instance == binding.source_instance),
                None,
            )
            if action == "show":
                _print_managed_webhook_result(
                    _managed_webhook_binding_summary(binding, listener_configured=listener is not None),
                    as_json=args.as_json,
                )
                return 0
            applying = action == "reconcile" and args.apply
            if applying:
                from .managed_webhook_rotation import ManagedWebhookRotationStore
                rotation_store = ManagedWebhookRotationStore(root)
            else:
                rotation_store = None
            with rotation_store.locked() if rotation_store is not None else nullcontext():
                if rotation_store is not None and any(
                    item.source_instance == binding.source_instance
                    for item in rotation_store._records_unlocked()
                ):
                    raise ValueError("generic webhook reconciliation is blocked while rotation authority exists")
                provider = _managed_webhook_provider(
                    binding, listener, provider_factory=provider_factory,
                )
                reconciler = ManagedWebhookReconciler(managed_store, provider)
                plan = reconciler.preview(binding.owner_id)
                result = {
                    "binding": _managed_webhook_binding_summary(binding, listener_configured=listener is not None),
                    "plan": plan.to_dict(),
                    "mode": "status" if action == "status" else ("apply" if args.apply else "dry-run"),
                }
                if action == "status":
                    _print_managed_webhook_result(result, as_json=args.as_json)
                    return 0 if plan.inventory.value == "EXACT" else 1
                if action != "reconcile":
                    raise WakeError("unsupported github-webhook binding command")
                if args.apply:
                    if listener is None:
                        raise ValueError("webhook listener is not configured")
                    receipt = reconciler.execute(plan)
                    result["receipt"] = receipt.to_dict()
                    result["binding"] = _managed_webhook_binding_summary(
                        managed_store.load(binding.owner_id), listener_configured=True
                    )
                    _print_managed_webhook_result(result, as_json=args.as_json)
                    return 1 if receipt.state.value == "UNKNOWN" else 0
                _print_managed_webhook_result(result, as_json=args.as_json)
                return 1 if plan.action is PlanAction.READ_ONLY else 0
        except ValueError as exc:
            raise WakeError(str(exc)) from None
    if args.github_webhook_command in {"readiness", "support"}:
        result = (webhook_readiness if args.github_webhook_command == "readiness" else webhook_support)(
            wake_root=root, source_instance=args.source_instance
        )
        if args.as_json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"status={result.get('status', result.get('webhook_listener', {}).get('status', 'unknown'))}")
        return 0 if result.get("status", result.get("webhook_listener", {}).get("status")) != "blocked" else 1
    try:
        config = build_webhook_service_config(
            wake_root=root, source_instance=args.source_instance,
            executable_path=args.executable_path, unit_dir=args.unit_dir, log_path=args.log_path,
            validate_executable=args.github_webhook_service_command == "install",
        )
        action = args.github_webhook_service_command
        if action == "install":
            install_webhook_service(config, start=not args.no_start)
            result: dict[str, object] = {"service": config.name, "unit": str(config.unit_path), "installed": True}
        elif action == "start":
            start_webhook_service(config)
            result = {"service": config.name, "started": True}
        elif action == "stop":
            stop_webhook_service(config)
            result = {"service": config.name, "stopped": True}
        elif action == "uninstall":
            uninstall_webhook_service(config)
            result = {"service": config.name, "uninstalled": True}
        else:
            active, enabled = webhook_service_status(config)
            result = {"service": config.name, "active": active, "enabled": enabled, "unit": str(config.unit_path)}
    except (ValueError, WakeError) as exc:
        raise WakeError(str(exc)) from None
    if args.as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(" ".join(f"{key}={value}" for key, value in result.items()))
    return 0


def _managed_webhook_provider(binding, listener, *, provider_factory=None):
    if provider_factory is None:
        from .github_webhook_admin import GitHubWebhookAdmin

        provider_factory = GitHubWebhookAdmin

    def credential_resolver(reference: str) -> str:
        from .github_credentials import resolve_github_credential

        return resolve_github_credential(reference, hostname=binding.provider_host)

    def secret_generation_resolver(generation: int) -> str:
        if listener is None:
            raise ValueError("managed webhook secret generation is unavailable")
        references = {listener.current_generation: listener.secret_ref}
        if listener.previous_generation is not None and listener.previous_secret_ref is not None:
            references[listener.previous_generation] = listener.previous_secret_ref
        reference = references.get(generation)
        if reference is None:
            raise ValueError("managed webhook secret generation is unavailable")
        return os.environ[reference]

    return provider_factory(
        binding,
        credential_resolver=credential_resolver,
        secret_generation_resolver=secret_generation_resolver,
    )


def _managed_webhook_binding_summary(binding, *, listener_configured: bool) -> dict[str, object]:
    return {
        "owner_id": binding.owner_id,
        "installation_id": binding.installation_id,
        "source_instance": binding.source_instance,
        "repository": binding.repository,
        "repository_id": binding.repository_id,
        "provider_host": binding.provider_host,
        "callback_url": binding.callback_url,
        "events": list(binding.events),
        "service_id": binding.service_id,
        "executable_id": binding.executable_id,
        "provider_hook_id": binding.provider_hook_id,
        "lifecycle": binding.lifecycle.value,
        "generation": binding.generation,
        "desired_fingerprint": binding.desired_fingerprint,
        "provider_credential_reference_configured": True,
        "listener_secret_reference_configured": listener_configured,
    }


def _print_managed_webhook_result(result: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, sort_keys=True))
        return
    binding = result.get("binding") if isinstance(result.get("binding"), dict) else result
    assert isinstance(binding, dict)
    print(
        f"source={binding['source_instance']} lifecycle={binding['lifecycle']} "
        f"repository={binding['repository']} hook_id={binding['provider_hook_id']}"
    )
    plan = result.get("plan")
    if isinstance(plan, dict):
        print(
            f"mode={result['mode']} inventory={plan['inventory']} "
            f"action={plan['action']} operation={plan['operation']}"
        )
    receipt = result.get("receipt")
    if isinstance(receipt, dict):
        print(f"receipt={receipt['state']} code={receipt['code']}")


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
    time_observation=None,
) -> int:
    prompt = normalize_prompt(prompt_parts)
    if getattr(args, "require_monitor", False):
        readiness = monitor_readiness(wake_root=root, repo_root=Path.cwd())
        require_monitor_ready(readiness)
    if (target is None and predicate.get('type') in {'not_before', 'file_exists'}
            and not getattr(args, 'app_server_thread_id', None)
            and not getattr(args, 'legacy_tmux', False)):
        raise WakeError('use native after|at|file THREAD TRIGGER, or explicitly select --legacy-tmux')
    record = build_record(
        predicate=predicate,
        prompt=prompt,
        cwd=Path.cwd(),
        target=target or target_for_args(args),
        now=now,
    )
    if time_observation is not None:
        from .network_wakes import mark_network_record
        mark_network_record(record,time_observation)
    path = write_record(root, record)
    print(f"{record['id']} {path}")
    return 0


def target_for_args(args: argparse.Namespace) -> dict[str, object]:
    if getattr(args, 'legacy_tmux', False) and getattr(args, 'app_server_thread_id', None):
        raise WakeError('--legacy-tmux and --app-server-thread-id are mutually exclusive')
    if getattr(args, "app_server_thread_id", None):
        endpoint = getattr(args, "app_server_endpoint", "stdio://")
        if endpoint != "stdio://":
            raise WakeError("only app-server endpoint stdio:// is currently implemented")
        target: dict[str, object] = {
            "transport": "app-server",
            "endpoint": endpoint,
            "thread_id": args.app_server_thread_id,
        }
        if getattr(args, "retry_active_writer", False):
            target["retry_active_writer"] = True
        codex_path = getattr(args, "app_server_codex_path", None)
        if codex_path:
            target["codex_cmd"] = resolve_codex_cmd(codex_path, required=True)
        return target
    if getattr(args, "retry_active_writer", False):
        raise WakeError("--retry-active-writer requires an app-server target")
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
    from .signal_support import signal_readiness

    summary = status_summary(root)
    signals = signal_readiness(root)
    summary["signal_readiness"] = signals
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
    for alert in summary['time_recovery_alerts']:
        print(f"time_alert={alert['id']} state={alert['state']} reason={alert['reason']} {alert['alert']}")
    print(f"signal_readiness={signals['status']}")
    signal_sources = signals.get("sources", [])
    if isinstance(signal_sources, list):
        source_states = sorted(
            f"{item.get('source', 'unknown')}:{item.get('status', 'unknown')}"
            for item in signal_sources
            if isinstance(item, dict)
        )
        print("signal_sources=" + ",".join(source_states))
    return 0


def show_record(args: argparse.Namespace, root: Path) -> int:
    found = find_record(root, args.wake_id)
    if getattr(args, "signal_state", False):
        from .signal_records import signal_journal_path
        from .signal_store import SQLiteSignalModule, SignalStoreError
        from .signals import Degraded

        try:
            runtime = SQLiteSignalModule.open_existing(signal_journal_path(root))
        except SignalStoreError:
            raise WakeError("signal authority is unavailable") from None
        if runtime is None:
            raise WakeError("signal authority is unavailable")
        inspected = runtime.inspect_signal_state(args.wake_id, record=found.record)
        if isinstance(inspected, Degraded):
            raise WakeError(f"signal authority is unavailable: {inspected.code}")
        print(json.dumps(inspected, indent=2, sort_keys=True))
        return 0
    print(json.dumps(found.record, indent=2, sort_keys=True))
    return 0


def cancel(args: argparse.Namespace, root: Path) -> int:
    from .wake_control import _cancel
    results = _cancel(root,args)
    result = results[0]
    if result['state'] != 'cancelled':
        raise WakeError(result.get('reason','wake cancellation held'))
    print(f"cancelled {args.wake_id} {root / 'cancelled' / (args.wake_id + '.json')}")
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
    protected = protected_signal_cleanup_records(root, older_than=older_than)
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
                    "protected_count": len(protected),
                    "protected": protected,
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
    for item in protected:
        print(
            f"protected {item['wake_id']} reasons={','.join(item['reasons'])} "
            f"repair={item['repair']}"
        )
    mode = "delete" if args.delete else "dry-run"
    print(
        f"cleanup mode={mode} older_than={args.older_than} archived={len(archived)} "
        f"matched={len(results)} protected={len(protected)}"
    )
    return 0


def support_command(args: argparse.Namespace, root: Path) -> int:
    if args.support_command != "export":
        raise WakeError(f"unknown support command: {args.support_command}")
    from .signal_support import export_signal_support

    try:
        result = export_signal_support(
            root,
            args.output,
            max_wakes=args.max_wakes,
            max_bytes=args.max_bytes,
        )
    except (OSError, ValueError) as exc:
        raise WakeError(str(exc)) from None
    payload = {
        "path": str(result.path),
        "size_bytes": result.size_bytes,
        "sha256": result.sha256,
        "included_wakes": result.included_wakes,
        "omitted_wakes": result.omitted_wakes,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key, value in payload.items():
            print(f"{key}={value}")
    return 0


def schema_command(args: argparse.Namespace) -> int:
    summary = schema_summary()
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"schema_version={summary['schema_version']}")
    print(f"read_versions={','.join(str(value) for value in summary['read_versions'])}")
    print(f"default_write_version={summary['default_write_version']}")
    print(f"signal_record_contract_version={summary['signal_record_contract_version']}")
    print(f"signal_journal_schema_version={summary['signal_journal_schema_version']}")
    print(f"compatibility={summary['compatibility']}")
    print(f"schema_doc={summary['schema_doc']}")
    print(f"statuses={','.join(summary['active_statuses'] + summary['terminal_statuses'] + [summary['archived_status']])}")
    print(f"predicate_types={','.join(summary['predicate_types'])}")
    print(f"target_transports={','.join(summary['target_transports'])}")
    print(f"required_fields={','.join(summary['required_fields'])}")
    print(f"optional_fields={','.join(summary['optional_fields'])}")
    print(f"schema_bump_required_for={','.join(summary['schema_bump_required_for'])}")
    return 0


def service_config_for_args(args: argparse.Namespace, root: Path, *, validate_executables: bool = False):
    return build_service_config(
        repo_root=args.repo_root,
        wake_root=root,
        name=args.name,
        interval=args.interval,
        daemon_path=args.daemon_path,
        codex_path=args.codex_path,
        github_credential_file=args.github_credential_file,
        dispatch_enabled=getattr(args, "dispatch_enabled", True),
        resolve_default_codex=validate_executables,
        log_path=args.log_path,
        validate_executables=validate_executables,
    )


def service_command(args: argparse.Namespace, root: Path) -> int:
    config = service_config_for_args(
        args,
        root,
        validate_executables=args.service_command == "install",
    )
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
        print(f"dispatch={service_dispatch_mode(config)}")
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
    signals = readiness["signals"]
    print(f"signal_capability_status={signals['capability']['status']}")
    print(f"signal_source_count={len(signals['sources'])}")
    for item in signals["sources"]:
        print(
            f"signal_source={item['source']}:{item['source_instance']} "
            f"status={item['status']} message={item['message']}"
        )
    return 0 if readiness["monitor_ready"] else 1


def supervisor_config_for_args(args: argparse.Namespace, *, validate_executable: bool = False):
    return build_supervisor_config(
        name=args.name,
        interval=args.interval,
        max_workers=args.max_workers,
        poll_timeout=args.poll_timeout,
        codex_wake_path=args.codex_wake_path,
        registry_dir=args.registry_dir,
        state_dir=args.state_dir,
        log_path=args.log_path,
        validate_executable=validate_executable,
    )


def supervisor_command(args: argparse.Namespace, root: Path) -> int:
    command = args.supervisor_command
    config = supervisor_config_for_args(
        args,
        validate_executable=command in {"install", "start", "run"},
    )
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
            poll_interval=args.poll_interval,
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
    if command == "reconcile":
        from .supervisor_scheduler import reconcile_root
        reconcile_root(config, args.root_id, expected_token=args.expected_token)
        print(f"reconciled {args.root_id}; future polling may resume under existing authority")
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
    config = service_config_for_args(args, root, validate_executables=False)
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
        daemon_path=str(config.daemon_path) if config.daemon_path else None,
        log_path=config.log_path,
    )
    app_server_summary = asdict(app_server_readiness)
    if monitor.get("monitor_source") not in {"", "repo_service"}:
        monitor_transports = monitor.get("transports")
        monitor_app_server = (
            monitor_transports.get("app_server")
            if isinstance(monitor_transports, dict)
            else None
        )
        if isinstance(monitor_app_server, dict):
            app_server_summary = dict(monitor_app_server)
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
        "service_app_server": app_server_summary,
        "monitor": monitor,
        "signals": monitor["signals"],
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
    signals = summary["signals"]
    assert isinstance(commands, dict)
    assert isinstance(hook_config, dict)
    assert isinstance(hook_runtime, dict)
    assert isinstance(hook_sources, dict)
    assert isinstance(service, dict)
    assert isinstance(service_app_server, dict)
    assert isinstance(monitor, dict)
    assert isinstance(signals, dict)
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
    print(f"signal_capability_status={signals['capability']['status']}")
    print(f"signal_source_count={len(signals['sources'])}")
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
        "signals",
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


def run(argv: list[str] | None = None, *, permission_principal=None) -> int:
    from .unified_contract import expand_cli, metadata
    parser = build_parser()
    argv, discover = expand_cli(argv, parser)
    if discover:
        print(json.dumps(metadata(), sort_keys=True))
        return 0
    args = parser.parse_args(argv)
    if getattr(args, '_external_connector', False):
        if args.wake_root is not None:
            raise WakeError('The external connector uses the Wake root in its private config; remove --wake-root.')
        try:
            from .external_connector import serve
        except ImportError:
            raise WakeError('Install the codex-wake MCP extra to serve the connector.') from None
        try:
            return serve(args.config)
        except (ValueError, OSError, KeyError) as error:
            raise WakeError('External connector configuration is invalid: '+str(error)) from None
    if (args.command in ('accounts', 'stores', 'configuration', 'history', 'builds', 'daemons', 'migration', 'tabs', 'environment')
            and not (args.command == 'configuration' and args.account_verb == 'default-root')):
        from .shortcut_store import default_root
        try:
            args.wake_root = default_root(args.wake_root)
        except (ValueError, OSError) as error:
            raise WakeError(str(error)) from None
    from .account_shortcuts import handles as shortcut_handles, command as shortcut_command
    if shortcut_handles(args):
        return shortcut_command(args)
    if permission_principal is not None:
        from .session_permissions import Principal
        if not isinstance(permission_principal,Principal):raise WakeError('permission_identity_unverified')
        args._permission_principal=permission_principal
    if args.command == "completion":
        from .completion import command as completion_command
        return completion_command(args, args.wake_root)
    if args.command == "time":
        from .time_inspection import time_command
        return time_command(args)
    root = resolve_root(args)
    if getattr(args, "_unified_operation", None):
        from .local_control_service import LocalOperations
        payload = dict(getattr(args, 'arguments', {}))
        for key in getattr(args, '_unified_fields', ['resource_id']):
            if hasattr(args, key):
                if key in payload:raise WakeError('duplicate_unified_argument')
                payload[key] = getattr(args, key)
        if getattr(args, '_unified_route', None) == 'protected':
            from .controller_client import execute_cli
            from types import SimpleNamespace
            return execute_cli(SimpleNamespace(endpoint=args.controller_endpoint, token_file=args.controller_token_file, transport=args.controller_transport, operation=args._unified_operation, arguments=payload))
        print(json.dumps(LocalOperations(root).execute(args._unified_operation, payload), sort_keys=True))
        return 0
    if args.command == "schedules":
        from .recurring_commands import command as schedule_command
        return schedule_command(args, root)
    if args.command == 'goal-limits':
        from .goal_limits_cli import goal_limits_command
        return goal_limits_command(args, root)
    if (args.command in ('pause','resume','pause-status','interrupt')
            or args.command == 'cancel' and (args.all or args.all_roots or args.as_json or args.authorized_root)
            or args.command == 'list' and (args.all_roots or args.authorized_root)):
        from .wake_control import control_command
        return control_command(args, root)

    if args.command == "messages":
        from .messages_cli import messages_command
        return messages_command(args)
    if args.command == "a2a":
        from .a2a_cli import a2a_command
        return a2a_command(args)
    if args.command == 'governor':
        from .governor_commands import command
        from .local_control_lifecycle import root_for
        return command(args, root_for(args))
    if args.command == 'self-limits':
        from .local_self_limits import command
        from .local_control_lifecycle import root_for
        return command(args, root_for(args))
    if args.command == 'control':
        from .local_control_lifecycle import root_for
        local_root = root_for(args)
        if args.control_verb in ('server','remote','connection','powershell','mcp'):
            from .local_control_lifecycle import command
            return command(args, local_root)
        if args.control_verb == 'slash':
            from .local_slash_cli import command
            return command(args, local_root)
        if args.control_verb == 'health':
            from .local_health import command
            return command(args, local_root)
        from .local_control_commands import command
        return command(args, local_root)
    if args.command == "sessions":
        if args.sessions_command == 'target':
            from .tab_targets import target_command
            return target_command(args, root)
        if args.sessions_command == 'execution':
            from .strict_runtime import execution_command
            return execution_command(args,root)
        if args.sessions_command == 'configuration':
            from .lifecycle_configuration import configuration_command
            return configuration_command(args, root)
        if args.sessions_command == 'handoff':
            from .agent_handoff import handoff_command
            return handoff_command(args, root)
        if args.sessions_command == 'refresh-watch':
            from .shared_refresh import watch
            watch(root, args.interval)
            return 0
        if args.sessions_command == 'refresh':
            from .agent_refresh import refresh_command
            return refresh_command(args, root)
        if args.sessions_command == 'spawn':
            from .agent_lifecycle import spawn_command
            return spawn_command(args, root)
        if args.sessions_command in ('open', 'close'):
            from .session_lifecycle import lifecycle_command
            return lifecycle_command(args, root)
        from .sessions_cli import sessions_command
        return sessions_command(args)
    if args.command == 'acceptance':
        from .work_acceptance_commands import run as acceptance_command
        return acceptance_command(args, root)
    if args.command == 'attention':
        from .attention_commands import run as attention_command
        return attention_command(args, root)
    if args.command == 'tabs':
        from .tab_organization_commands import run as tabs_command
        return tabs_command(args, root)
    if args.command == 'interactions':
        from .guarded_interaction_commands import run as interactions_command
        return interactions_command(args, root)
    if args.command == 'jobs':
        from .background_job_commands import jobs_command
        register = None
        principal = None
        if args.job_command == 'await':
            from .permission_commands import verified_cli_principal
            from .background_jobs import BackgroundJobs
            from .session_permissions import Principal
            from .permission_enforcement import verified_tasks
            principal = verified_cli_principal(args)
            pin = BackgroundJobs(root).inspect(args.job_id)['intent']['profile']['command']['task_pin']
            if principal.role != 'operator':
                principal = Principal(principal.subject, tasks=verified_tasks(root, principal.subject,
                    pin['task_id'], pin['assignment_id'], actor_id=getattr(args, 'permission_actor_id', None)))
            from .frontier_mcp import job_awaiter
            register = job_awaiter(root, args.app_server, principal)
        return jobs_command(args, root, principal=principal, register_wake=register)
    if args.command == 'resources':
        from .resource_claim_commands import run as resources_command
        return resources_command(args, root)
    if args.command == 'permissions':
        from .permission_commands import command as permissions_command
        return permissions_command(args, root)
    if args.command == 'agents':
        from .managed_inventory_commands import run as agents_command
        return agents_command(args, root)
    if args.command == 'task-briefs':
        from .task_brief_commands import task_briefs_command
        return task_briefs_command(args, root)
    if args.command == 'wake-policy':
        from .wake_policy import command
        return command(args, root)
    if args.command == 'grok':
        from .runtime_wakes import command
        return command(args, root)
    if args.command == "native":
        if args.native_command == 'migrate':
            from .native_delivery import migrate_command
            return migrate_command(args, root)
        if args.native_command == 'reconcile':
            from .native_delivery import reconcile_command
            return reconcile_command(args, root)
        from .native_delivery import create_native
        return create_native(args, root)
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
    if args.command == "filesystem":
        return create_filesystem_signal(args, root)
    if args.command == "process-exit":
        return create_process_exit_signal(args, root)
    if args.command == "systemd-unit":
        return systemd_unit_command(args, root)
    if args.command == "github-ci":
        return github_ci_command(args, root)
    if args.command == "http-json":
        return http_json_command(args, root)
    if args.command == "github-webhook":
        return github_webhook_command(args, root)
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
    if args.command == "support":
        return support_command(args, root)
    if args.command == "profiles":
        from .profile_compat import main
        arguments = args.profile_arguments
        if arguments and arguments[0] == "--":
            arguments = arguments[1:]
        if args.profile_config is not None:
            arguments = ["--config", str(args.profile_config), *arguments]
        elif args.wake_root is not None:
            arguments = ["--config", str(args.wake_root / "controller-accounts.toml"), *arguments]
        return main(arguments)
    if args.command in ("accounts", "configuration", "stores"):
        from .account_commands import command
        return command(args, root)
    if args.command == "health":
        from .health_commands import command
        return command(args, args.wake_root)
    if args.command == "notices":
        from .notice_commands import command
        return command(args, args.wake_root)
    if args.command == "recovery":
        from .recovery_commands import command
        return command(args, args.wake_root)
    if args.command == "flow-sessions":
        from .flow_session_commands import command
        return command(args, args.wake_root)
    if args.command == "flows":
        from .flow_commands import command
        return command(args, args.wake_root)
    if args.command == "operations":
        from .operation_commands import command
        return command(args, args.wake_root)
    if args.command == "hosts":
        from .host_commands import command
        return command(args, args.wake_root)
    if args.command == "migration":
        from .migration_commands import command
        return command(args, root)
    if args.command == "history":
        from .history_commands import command
        return command(args, args.wake_root)
    if args.command == "daemons":
        from .daemon_commands import command
        return command(args, args.wake_root)
    if args.command == "builds":
        from .build_commands import command, owner_from_root
        return command(args, owner_from_root(args.wake_root))
    if args.command == "controller":
        from .controller_commands import command
        return command(args)
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
