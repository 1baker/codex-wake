from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from codex_wake import cli
from codex_wake.openclaw_plugin import package_version
from codex_wake.records import WakeError, build_record, write_record
from codex_wake.service import ServiceAppServerReadiness


class CliTests(unittest.TestCase):
    def readiness(self) -> ServiceAppServerReadiness:
        return ServiceAppServerReadiness(
            codex_cmd_ready=True,
            codex_cmd_source="unit_environment",
            codex_cmd="/usr/bin/codex",
            unit_codex_cmd="/usr/bin/codex",
            user_manager_codex_cmd="",
            interactive_codex_cmd="/usr/bin/codex",
            message="service unit sets CODEX_WAKE_CODEX_CMD",
        )

    def run_cli(self, argv: list[str], root: Path) -> tuple[int, str, str]:
        # These fixtures exercise the retained tmux compatibility interface.
        if argv and argv[0] in {'after', 'at', 'file'} and '--app-server-thread-id' not in argv:
            argv = [argv[0], '--legacy-tmux', *argv[1:]]
        env = {
            **os.environ,
            "TMUX_PANE": "%11",
            "TMUX": "/tmp/tmux-1000/default,123,0",
            "CODEX_THREAD_ID": "thread_cli",
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, env, clear=False), patch(
            "codex_wake.records.resolve_tmux_thread_pane", return_value=("%11", 1234, 5678)
        ):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(["--wake-root", str(root), *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_service_and_supervisor_help_describe_stable_executable_paths(self) -> None:
        parser = cli.build_parser()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["service", "install", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("stable Codex executable path", stdout.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["supervisor", "enroll", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("stable OpenClaw executable path", stdout.getvalue())

    def test_service_install_exposes_a_persistent_no_dispatch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            args = cli.build_parser().parse_args(
                ["service", "install", "--no-start", "--no-dispatch"]
            )

            config = cli.service_config_for_args(args, root)

            self.assertFalse(config.dispatch_enabled)

    def test_github_ci_source_configure_persists_an_explicit_enabled_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"

            code, out, err = self.run_cli(
                [
                    "github-ci", "source", "configure",
                    "--source", "github-ci",
                    "--repository", "example/project",
                    "--repository-id", "123",
                    "--workflow-id", "456",
                    "--ref", "refs/heads/main",
                    "--conclusion", "success",
                    "--credential-ref", "CODEX_WAKE_GITHUB_TOKEN",
                    "--enabled",
                ],
                root,
            )

            self.assertEqual(code, 0, err)
            self.assertIn("source=github-ci", out)
            payload = json.loads((root / "github" / "sources.json").read_text())
            self.assertEqual(payload["sources"][0]["refs"], ["refs/heads/main"])
            self.assertEqual(payload["sources"][0]["conclusions"], ["success"])
            self.assertTrue(payload["sources"][0]["enabled"])

            code, listed, err = self.run_cli(
                ["github-ci", "source", "list", "--json"], root
            )
            self.assertEqual(code, 0, err)
            summary = json.loads(listed)
            self.assertEqual(summary["sources"][0]["source_instance"], "github-ci")
            self.assertNotIn("credential_ref", listed)

            code, shown, err = self.run_cli(
                ["github-ci", "source", "show", "github-ci", "--json"], root
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(shown)["repository"], "example/project")
            self.assertNotIn("credential_ref", shown)

    def test_github_ci_completed_registers_one_idempotent_journal_authoritative_wake(self) -> None:
        from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            configured = [
                "github-ci", "source", "configure",
                "--source", "github-ci",
                "--repository", "example/project",
                "--repository-id", "123",
                "--workflow-id", "456",
                "--ref", "refs/heads/main",
                "--conclusion", "failure",
                "--credential-ref", "CODEX_WAKE_GITHUB_TOKEN",
                "--enabled",
            ]
            self.assertEqual(self.run_cli(configured, root)[0], 0)
            command = [
                "github-ci", "completed",
                "--source", "github-ci",
                "--ref", "refs/heads/main",
                "--conclusion", "failure",
                "--idempotency-key", "ci-main-failed",
                "--max-attempts", "1",
                "--", "Inspect the failed workflow",
            ]

            publisher = WakeRecordPublisher(
                root,
                ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
            )
            with patch(
                "codex_wake.signal_records.WakeRecordPublisher.for_managed_reader",
                return_value=publisher,
            ):
                first = self.run_cli(command, root)
                second = self.run_cli(command, root)

            self.assertEqual((first[0], second[0]), (0, 0), first[2] + second[2])
            wake_id = first[1].split()[0]
            self.assertEqual(second[1].split()[0], wake_id)
            record = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(record["schema_version"], 2)
            self.assertEqual(record["max_attempts"], 1)
            self.assertEqual(record["predicate"]["source"], "github")
            self.assertEqual(record["predicate"]["source_instance"], "github-ci")
            self.assertEqual(record["predicate"]["kind"], "workflow_run.completed")
            self.assertTrue((root / "signals" / "journal.sqlite3").is_file())

    def test_github_ci_help_and_registration_gates_are_explicit_and_fail_closed(self) -> None:
        parser = cli.build_parser()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["github-ci", "completed", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--source", stdout.getvalue())
        self.assertIn("exactly 1", stdout.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "github-ci", "completed", "--source", "github-ci",
                    "--ref", "refs/heads/main", "--conclusion", "success",
                    "--max-attempts", "2", "continue",
                ]
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            code, _out, error = self.run_cli(
                [
                    "github-ci", "source", "configure",
                    "--source", "github-ci", "--repository", "example/project",
                    "--repository-id", "123", "--workflow-id", "456",
                    "--ref", "refs/heads/main", "--conclusion", "success",
                    "--credential-ref", "ghp_raw_value", "--enabled",
                ],
                root,
            )
            self.assertEqual(code, 2)
            self.assertIn("environment variable name", error)
            self.assertFalse((root / "github" / "sources.json").exists())

            disabled = [
                "github-ci", "source", "configure",
                "--source", "github-ci", "--repository", "example/project",
                "--repository-id", "123", "--workflow-id", "456",
                "--ref", "refs/heads/main", "--conclusion", "success",
                "--credential-ref", "CODEX_WAKE_GITHUB_TOKEN", "--disabled",
            ]
            self.assertEqual(self.run_cli(disabled, root)[0], 0)
            code, _out, error = self.run_cli(
                [
                    "github-ci", "completed", "--source", "github-ci",
                    "--ref", "refs/heads/main", "--conclusion", "success",
                    "continue",
                ],
                root,
            )
            self.assertEqual(code, 2)
            self.assertIn("not enabled", error)
            self.assertFalse((root / "signals" / "journal.sqlite3").exists())

    def test_lifecycle_argument_configs_ignore_missing_launch_executables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            parser = cli.build_parser()
            service_args = parser.parse_args(
                [
                    "--wake-root",
                    str(base / "wake"),
                    "service",
                    "status",
                    "--daemon-path",
                    str(base / "missing-daemon"),
                    "--codex-path",
                    str(base / "missing-codex"),
                ]
            )
            service_config = cli.service_config_for_args(service_args, base / "wake")
            self.assertIsNone(service_config.daemon_path)
            self.assertIsNone(service_config.codex_path)
            with self.assertRaises(WakeError):
                cli.service_config_for_args(
                    service_args,
                    base / "wake",
                    validate_executables=True,
                )

            supervisor_args = parser.parse_args(
                [
                    "supervisor",
                    "status",
                    "--codex-wake-path",
                    str(base / "missing-codex-wake"),
                    "--registry-dir",
                    str(base / "registry"),
                ]
            )
            supervisor_config = cli.supervisor_config_for_args(supervisor_args)
            self.assertIsNone(supervisor_config.codex_wake_path)
            with self.assertRaises(WakeError):
                cli.supervisor_config_for_args(supervisor_args, validate_executable=True)

    def test_service_config_renders_only_a_github_credential_file_reference(self) -> None:
        from dataclasses import replace

        from codex_wake.service import build_service_config, render_unit

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            credential_file = base / "github.env"
            credential_file.write_text("CODEX_WAKE_GITHUB_TOKEN=never-render-this\n")
            parser = cli.build_parser()
            args = parser.parse_args(
                [
                    "--wake-root", str(base / "wake"),
                    "service", "status",
                    "--github-credential-file", str(credential_file),
                ]
            )

            config = cli.service_config_for_args(args, base / "wake")
            unit = render_unit(replace(config, daemon_path=Path("/usr/bin/codex-waked")))

            self.assertEqual(config.github_credential_file, credential_file.resolve())
            self.assertIn(f"EnvironmentFile={credential_file.resolve()}", unit)
            self.assertNotIn("never-render-this", unit)

            credential_file.chmod(0o600)
            symlink = base / "github-link.env"
            symlink.symlink_to(credential_file)
            with self.assertRaisesRegex(WakeError, "owner-only regular file"):
                build_service_config(
                    repo_root=base,
                    wake_root=base / "wake",
                    daemon_path="/bin/true",
                    github_credential_file=symlink,
                    unit_dir=base,
                    log_path=base / "wake.log",
                    validate_executables=True,
                )

    def test_service_config_rejects_relative_github_credential_file_path(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "service",
                "status",
                "--github-credential-file",
                "github.env",
            ]
        )

        with self.assertRaisesRegex(WakeError, "absolute parser-safe path"):
            cli.service_config_for_args(args, Path("/tmp/wake"))

    def test_legacy_after_uses_qualified_upper_without_rounding_due_early(self):
        from test_measurements import observation
        clock=observation(1000)
        clock['utc'].update(lower=1893456000.25,upper=1893456000.75)
        for argv in [['after','1s','--','fixture'],['app','after','fixture-thread','1s','--','fixture']]:
            with self.subTest(command=argv[0]),tempfile.TemporaryDirectory() as tmp, \
                    patch('codex_wake.measurements.snapshot',return_value=clock), \
                    patch('codex_wake.cli.utc_now',side_effect=AssertionError('guest clock forbidden')):
                root=Path(tmp)
                code,out,err=self.run_cli(argv,root)
                self.assertEqual(code,0,err)
                record=json.loads(next((root/'pending').glob('*.json')).read_text())
                self.assertEqual(record['predicate']['due_at'],'2030-01-01T00:00:02Z')
                self.assertEqual(record['created_at'],'2030-01-01T00:00:00Z')

    def test_legacy_creators_hold_without_qualified_utc_before_record_write(self):
        from codex_wake.measurements import TimeUnavailable
        requests=[['app','after','fixture-thread','1s','--','fixture'],['after','1s','--','fixture'],['at','2030-01-01T00:00:00Z','--','fixture'],
                  ['file','created.txt','--','fixture'],['changed','changed.txt','--','fixture'],
                  ['pid',str(os.getpid()),'--','fixture']]
        for argv in requests:
            with self.subTest(command=argv[0]),tempfile.TemporaryDirectory() as tmp, \
                    patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('clock absent')), \
                    patch('codex_wake.cli.utc_now',side_effect=AssertionError('guest clock forbidden')):
                root=Path(tmp)
                code,out,err=self.run_cli(argv,root)
                self.assertEqual(code,2)
                self.assertIn('stable_time_creation_unqualified',err)
                self.assertFalse(list((root/'pending').glob('*.json')))

    def test_after_creates_pending_wake(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(["after", "45m", "--", "Continue later"], root)
            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            record_path = root / "pending" / f"{wake_id}.json"
            data = json.loads(record_path.read_text())
            self.assertEqual(data["predicate"]["type"], "not_before")
            self.assertEqual(data["target"]["pane"], "%11")
            self.assertEqual(data["target"]["thread_id"], "thread_cli")
            self.assertEqual(data["target"]["client_pid"], 1234)
            self.assertEqual(data["target"]["client_start_time_ticks"], 5678)
            self.assertEqual(data["prompt"], "Continue later")
            self.assertEqual(data["status"], "pending")

    def test_schema_command_reports_version_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(["schema"], root)
            self.assertEqual(code, 0, err)
            self.assertIn("schema_version=1", out)
            self.assertIn("compatibility=additive_optional_fields", out)
            self.assertIn("schema_doc=docs/dev/wake-record-schema.md", out)

            code, json_out, err = self.run_cli(["schema", "--json"], root)
            self.assertEqual(code, 0, err)
            data = json.loads(json_out)
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["read_versions"], [1, 2, 3, 4, 5, 6, 7, 8])
            self.assertEqual(data["default_write_version"], 1)
            self.assertEqual(data["signal_record_contract_version"], 2)
            self.assertEqual(data["signal_journal_schema_version"], 2)
            self.assertIn("file_changed", data["predicate_types"])

    def test_support_export_writes_bounded_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            output = base / "support" / "signals.json"

            code, stdout, stderr = self.run_cli(
                [
                    "support",
                    "export",
                    "--output",
                    str(output),
                    "--max-wakes",
                    "5",
                    "--max-bytes",
                    "8192",
                    "--json",
                ],
                base / "wake",
            )

            self.assertEqual(code, 0, stderr)
            receipt = json.loads(stdout)
            self.assertEqual(receipt["path"], str(output))
            self.assertLessEqual(receipt["size_bytes"], 8192)
            self.assertEqual(len(receipt["sha256"]), 64)
            self.assertEqual(json.loads(output.read_text())["schema_version"], 1)

    def test_support_export_cli_cannot_replace_signal_journal(self) -> None:
        from codex_wake.signal_records import signal_journal_path
        from codex_wake.signal_store import SQLiteSignalModule
        from codex_wake.signal_support import signal_readiness

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            journal = signal_journal_path(root)
            SQLiteSignalModule(journal)
            original = journal.read_bytes()
            before = signal_readiness(root)

            code, _stdout, stderr = self.run_cli(
                ["support", "export", "--output", str(journal), "--json"], root
            )

            self.assertEqual(code, 2)
            self.assertIn("outside the wake root", stderr)
            self.assertEqual(journal.read_bytes(), original)
            self.assertEqual(signal_readiness(root), before)

    def test_show_signal_state_reads_existing_authority_without_creating_it(self) -> None:
        from codex_wake.event_wake import EventWake
        from codex_wake.signal_records import (
            ManagedReaderCapability,
            WakeRecordPublisher,
            signal_journal_path,
        )
        from codex_wake.signal_store import SQLiteSignalModule
        from tests.test_signals import make_adapter, make_intent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            journal = signal_journal_path(root)
            placeholder = build_record(
                predicate={"type": "not_before", "due_at": "2026-09-15T14:00:00Z"},
                prompt="continue",
                cwd=Path(tmp),
                target={"transport": "tmux", "tmux_socket": "/tmp/tmux", "pane": "%1"},
                now=datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
            )
            placeholder["id"] = "missing"
            write_record(root, placeholder)
            code, _out, _err = self.run_cli(
                ["show", "missing", "--signal-state"], root
            )
            self.assertNotEqual(code, 0)
            self.assertFalse(journal.exists())
            journal.parent.mkdir(parents=True)
            journal.write_bytes(b"not-a-sqlite-journal")
            code, _out, error = self.run_cli(
                ["show", "missing", "--signal-state"], root
            )
            self.assertNotEqual(code, 0)
            self.assertNotIn("not-a-sqlite", error)
            journal.unlink()

            runtime = SQLiteSignalModule(
                journal,
                record_publisher=WakeRecordPublisher(
                    root,
                    ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            EventWake(
                runtime,
                adapters=[make_adapter()],
                clock=lambda: datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
                id_factory=lambda: "wake_signal",
            ).register(make_intent(), idempotency_key="job-42")

            code, output, error = self.run_cli(
                ["show", "wake_signal", "--signal-state"], root
            )
            self.assertEqual(code, 0, error)
            inspected = json.loads(output)
            self.assertEqual(inspected["arm"]["state"], "published")
            self.assertEqual(inspected["lifecycle"]["applied_status"], "pending")
            self.assertEqual(inspected["record"]["schema_version"], 2)
            self.assertIsNone(inspected["degradation"])

    def test_filesystem_created_registers_v2_and_inspection_explains_baseline(self) -> None:
        from codex_wake.daemon import poll_once
        from codex_wake.filesystem_signals import FilesystemSignalAdapter, FilesystemSignalRunner
        from codex_wake.signal_records import (
            ManagedReaderCapability,
            WakeRecordPublisher,
            signal_journal_path,
        )
        from codex_wake.signal_store import SQLiteSignalModule

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "wake"
            publisher = WakeRecordPublisher(
                root,
                ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
            )
            with patch("codex_wake.signal_records.WakeRecordPublisher.for_managed_reader", return_value=publisher):
                with patch("codex_wake.cli.Path.cwd", return_value=base):
                    code, output, error = self.run_cli(
                        [
                            "filesystem",
                            "created",
                            "--idempotency-key",
                            "build-result",
                            "--max-attempts",
                            "1",
                            "out/result.txt",
                            "--",
                            "Continue build",
                        ],
                        root,
                    )
            self.assertEqual(code, 0, error)
            wake_id = output.split()[0]
            pending = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(pending["schema_version"], 2)
            self.assertEqual(pending["predicate"]["kind"], "file.created")
            self.assertEqual(pending["predicate"]["subject"], "path:out/result.txt")
            self.assertEqual(pending["max_attempts"], 1)

            code, inspected_output, error = self.run_cli(
                ["show", wake_id, "--signal-state"], root
            )
            self.assertEqual(code, 0, error)
            inspected = json.loads(inspected_output)
            self.assertEqual(inspected["source_evidence"]["baseline"]["exists"], False)
            self.assertIsNone(inspected["source_evidence"]["observed"])

            watched = base / "out" / "result.txt"
            watched.parent.mkdir()
            watched.write_text("never expose this", encoding="utf-8")
            adapter = FilesystemSignalAdapter(base, "out/result.txt")
            runtime = SQLiteSignalModule.open_existing(
                signal_journal_path(root), record_publisher=publisher
            )
            armed = runtime.load_armed_signal(wake_id)
            runner = FilesystemSignalRunner((adapter,), armed_signals=(armed,))
            poll_once(
                root,
                now=datetime(2026, 9, 14, 17, 0, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
                signal_runners=(runner,),
            )
            code, inspected_output, error = self.run_cli(
                ["show", wake_id, "--signal-state"], root
            )
            self.assertEqual(code, 0, error)
            inspected = json.loads(inspected_output)
            observed = inspected["source_evidence"]["observed"]
            self.assertEqual(observed["exists"], True)
            self.assertEqual(observed["observation_reason"], "periodic")
            self.assertEqual(len(observed["fingerprint"]), 64)
            self.assertNotIn("never expose this", inspected_output)

    def test_filesystem_rejects_non_positive_attempt_bound(self) -> None:
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(
                ["filesystem", "created", "--max-attempts", "0", "out/result.txt", "continue"]
            )
        self.assertEqual(raised.exception.code, 2)

    def test_process_exit_registers_exact_schema_v2_identity_without_process_metadata(self) -> None:
        from codex_wake.process_signals import ProcessExitAdapter, ProcessExitSample
        from codex_wake.runtime_signals import RuntimeSourceDescriptor, RuntimeSourceRegistry
        from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            identity = {
                "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
                "pid": 321,
                "start_time_ticks": 654,
                "owner_uid": os.geteuid(),
            }
            descriptor = RuntimeSourceDescriptor.parse({
                "version": 1,
                "kind": "process.exit",
                "resource": identity,
                "target_state": "terminated",
            })
            adapter = ProcessExitAdapter(
                descriptor,
                RuntimeSourceRegistry({"process.exit": lambda candidate: candidate == descriptor}),
                lambda: ProcessExitSample.alive(**identity),
            )
            publisher = WakeRecordPublisher(
                root,
                ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
            )
            with (
                patch(
                    "codex_wake.process_signals.production_process_exit_adapter",
                    return_value=adapter,
                ),
                patch(
                    "codex_wake.signal_records.WakeRecordPublisher.for_managed_reader",
                    return_value=publisher,
                ),
            ):
                code, output, error = self.run_cli(
                    [
                        "process-exit", "--idempotency-key", "exact-process",
                        "--max-attempts", "2", "321", "--", "Continue work",
                    ],
                    root,
                )
            self.assertEqual(code, 0, error)
            wake_id = output.split()[0]
            record = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(record["schema_version"], 2)
            self.assertEqual(record["max_attempts"], 2)
            self.assertEqual(record["predicate"]["source"], "runtime")
            self.assertEqual(record["predicate"]["kind"], "process.exit")
            encoded = json.dumps(record, sort_keys=True)
            self.assertNotIn("cmdline", encoded)
            self.assertNotIn("environ", encoded)
            self.assertNotIn("exit_code", encoded)

    def test_process_exit_rejects_invalid_attempt_bound(self) -> None:
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["process-exit", "--max-attempts", "0", "123", "continue"])
        self.assertEqual(raised.exception.code, 2)

    def test_systemd_unit_configuration_and_transition_registration_are_bounded(self) -> None:
        from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher
        from codex_wake.systemd_signals import SystemdUnitState

        class FixtureManager:
            def resolve_unit(self, unit: str, *, timeout_seconds: int) -> str:
                return unit

            def read_unit(self, unit: str, *, timeout_seconds: int) -> SystemdUnitState:
                return SystemdUnitState(unit, "inactive", "manager-a")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            configured = self.run_cli([
                "systemd-unit", "source", "configure",
                "--source", "build-state", "--unit", "build.service",
                "--target-state", "active", "--target-state", "failed",
                "--poll-timeout", "4", "--enabled",
            ], root)
            self.assertEqual(configured[0], 0, configured[2])
            mode = (root / "systemd" / "sources.json").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)

            code, output, error = self.run_cli(
                ["systemd-unit", "source", "list", "--json"], root
            )
            self.assertEqual(code, 0, error)
            source = json.loads(output)["sources"][0]
            self.assertEqual(source["unit"], "build.service")
            self.assertEqual(source["target_states"], ["active", "failed"])
            self.assertNotIn("method", output)
            self.assertNotIn("bus_address", output)

            publisher = WakeRecordPublisher(
                root,
                ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
            )
            with (
                patch("codex_wake.systemd_signals.SystemdUserBusBackend", return_value=FixtureManager()),
                patch(
                    "codex_wake.signal_records.WakeRecordPublisher.for_managed_reader",
                    return_value=publisher,
                ),
            ):
                code, output, error = self.run_cli([
                    "systemd-unit", "becomes", "--source", "build-state",
                    "--state", "active", "--idempotency-key", "build-active",
                    "--max-attempts", "2", "--", "Continue build",
                ], root)
            self.assertEqual(code, 0, error)
            wake_id = output.split()[0]
            record = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(record["schema_version"], 2)
            self.assertEqual(record["max_attempts"], 2)
            self.assertEqual(record["predicate"]["source"], "systemd")
            self.assertEqual(record["predicate"]["kind"], "unit.active_state")
            self.assertEqual(record["predicate"]["subject"], "unit:build.service")

    def test_systemd_unit_configuration_rejects_wildcards_and_unbounded_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            for unit, timeout in (("*.service", "5"), ("build.service", "61")):
                with self.subTest(unit=unit, timeout=timeout):
                    code, _output, error = self.run_cli([
                        "systemd-unit", "source", "configure",
                        "--source", "build-state", "--unit", unit,
                        "--target-state", "active", "--poll-timeout", timeout,
                        "--enabled",
                    ], root)
                    self.assertEqual(code, 2)
                    self.assertIn("configuration is invalid", error)

    def test_version_reports_package_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(["--wake-root", str(root), "--version"])

            self.assertEqual(raised.exception.code, 0)
            self.assertIn(f"codex-wake {package_version()}", stdout.getvalue())

    def test_app_status_reports_thread_status_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "codex_wake.cli.read_app_server_thread_status",
                return_value={
                    "thread_id": "thread_abc",
                    "status": {"type": "active", "activeFlags": ["waitingOnApproval"]},
                    "status_type": "active",
                    "active_flags": ["waitingOnApproval"],
                    "cwd": "/tmp/repo",
                    "sessionId": "session_123",
                },
            ):
                code, out, err = self.run_cli(["app", "status", "--json", "thread_abc"], root)

            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["thread_id"], "thread_abc")
            self.assertEqual(data["status_type"], "active")
            self.assertEqual(data["active_flags"], ["waitingOnApproval"])

    def test_app_status_can_request_resume_backed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "codex_wake.cli.read_app_server_thread_status",
                return_value={
                    "thread_id": "thread_abc",
                    "status": {"type": "idle"},
                    "status_type": "idle",
                },
            ) as read_status:
                code, out, err = self.run_cli(["app", "status", "--resume", "thread_abc"], root)

            self.assertEqual(code, 0, err)
            read_status.assert_called_once_with("thread_abc", resume=True)
            self.assertIn("thread_id=thread_abc", out)
            self.assertIn("status_type=idle", out)
            self.assertIn("source=thread/resume", out)

    def test_app_candidates_reports_local_rollout_backed_threads_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            codex_home = Path(tmp) / "codex"
            session_dir = codex_home / "sessions" / "2026" / "05" / "21"
            session_dir.mkdir(parents=True)
            (session_dir / "rollout-2026-05-21T01-00-00-thread_abc.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-21T01:00:00.000Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "thread_abc",
                            "timestamp": "2026-05-21T01:00:00.000Z",
                            "cwd": "/tmp/repo",
                            "originator": "codex-tui",
                        },
                    }
                ),
                encoding="utf-8",
            )

            code, out, err = self.run_cli(["app", "candidates", "--codex-home", str(codex_home), "--json"], root)

            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data[0]["thread_id"], "thread_abc")
            self.assertEqual(data[0]["cwd"], "/tmp/repo")
            self.assertEqual(data[0]["resumable_source"], "local_session_rollout")

    def test_app_candidates_text_points_to_resume_status_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            codex_home = Path(tmp) / "codex"
            session_dir = codex_home / "sessions" / "2026" / "05" / "21"
            session_dir.mkdir(parents=True)
            (session_dir / "rollout-2026-05-21T01-00-00-thread_abc.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": "thread_abc", "cwd": "/tmp/repo"}}),
                encoding="utf-8",
            )

            code, out, err = self.run_cli(["app", "candidates", "--codex-home", str(codex_home)], root)

            self.assertEqual(code, 0, err)
            self.assertIn("THREAD_ID", out)
            self.assertIn("thread_abc", out)
            self.assertIn("codex-wake app status --resume <THREAD_ID>", out)

    def test_app_candidates_can_validate_with_resume_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            codex_home = Path(tmp) / "codex"
            session_dir = codex_home / "sessions" / "2026" / "05" / "21"
            session_dir.mkdir(parents=True)
            (session_dir / "rollout-2026-05-21T01-00-00-thread_abc.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": "thread_abc", "cwd": "/tmp/repo"}}),
                encoding="utf-8",
            )
            with patch(
                "codex_wake.cli.read_app_server_thread_status",
                return_value={
                    "thread_id": "thread_abc",
                    "status": {"type": "idle"},
                    "status_type": "idle",
                },
            ) as read_status:
                code, out, err = self.run_cli(
                    ["app", "candidates", "--codex-home", str(codex_home), "--validate", "--json"],
                    root,
                )

            self.assertEqual(code, 0, err)
            read_status.assert_called_once_with("thread_abc", resume=True, cwd="/tmp/repo")
            data = json.loads(out)
            self.assertEqual(data[0]["validation"], "resume_ok")
            self.assertEqual(data[0]["status_type"], "idle")
            self.assertEqual(data[0]["status"], {"type": "idle"})

    def test_app_candidates_only_idle_filters_validated_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            codex_home = Path(tmp) / "codex"
            session_dir = codex_home / "sessions" / "2026" / "05" / "21"
            session_dir.mkdir(parents=True)
            for thread_id in ("thread_idle", "thread_active"):
                (session_dir / f"rollout-{thread_id}.jsonl").write_text(
                    json.dumps({"type": "session_meta", "payload": {"id": thread_id, "cwd": "/tmp/repo"}}),
                    encoding="utf-8",
                )

            def fake_status(thread_id: str, *, resume: bool, cwd: str | None = None) -> dict:
                status_type = "idle" if thread_id == "thread_idle" else "active"
                return {"thread_id": thread_id, "status": {"type": status_type}, "status_type": status_type}

            with patch("codex_wake.cli.read_app_server_thread_status", side_effect=fake_status):
                code, out, err = self.run_cli(
                    ["app", "candidates", "--codex-home", str(codex_home), "--validate", "--only-idle", "--json"],
                    root,
                )

            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual([row["thread_id"] for row in data], ["thread_idle"])

    def test_app_candidates_only_idle_requires_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            code, _, err = self.run_cli(["app", "candidates", "--only-idle"], root)

            self.assertEqual(code, 2)
            self.assertIn("--only-idle requires --validate", err)

    def test_file_show_list_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(["file", ".codex/events/pytest.done", "--", "Read log"], root)
            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]

            code, show_out, err = self.run_cli(["show", wake_id], root)
            self.assertEqual(code, 0, err)
            shown = json.loads(show_out)
            self.assertEqual(shown["predicate"], {"type": "file_exists", "path": ".codex/events/pytest.done"})

            code, list_out, err = self.run_cli(["list"], root)
            self.assertEqual(code, 0, err)
            self.assertIn(wake_id, list_out)
            self.assertIn("file_exists", list_out)

            code, cancel_out, err = self.run_cli(["cancel", wake_id], root)
            self.assertEqual(code, 0, err)
            self.assertIn("cancelled", cancel_out)
            self.assertTrue((root / "cancelled" / f"{wake_id}.json").exists())
            self.assertFalse((root / "pending" / f"{wake_id}.json").exists())

            code, archive_out, err = self.run_cli(["archive", wake_id], root)
            self.assertEqual(code, 0, err)
            self.assertIn("archived", archive_out)
            self.assertTrue((root / "archive" / f"{wake_id}.json").exists())

            code, archived_list, err = self.run_cli(["list", "--archived"], root)
            self.assertEqual(code, 0, err)
            self.assertIn(wake_id, archived_list)

    def test_status_command_reports_counts_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(["after", "45m", "--", "Continue later"], root)
            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            code, _, err = self.run_cli(["cancel", wake_id], root)
            self.assertEqual(code, 0, err)
            code, _, err = self.run_cli(["archive", wake_id], root)
            self.assertEqual(code, 0, err)
            code, _, err = self.run_cli(["file", ".codex/events/done", "--", "Check event"], root)
            self.assertEqual(code, 0, err)

            code, text_out, err = self.run_cli(["status"], root)
            self.assertEqual(code, 0, err)
            self.assertIn("total=2", text_out)
            self.assertIn("active_total=1", text_out)
            self.assertIn("archived_total=1", text_out)
            self.assertIn("counts_by_status=", text_out)
            self.assertIn("counts_by_visibility_classification=", text_out)

            code, json_out, err = self.run_cli(["status", "--json"], root)
            self.assertEqual(code, 0, err)
            data = json.loads(json_out)
            self.assertEqual(data["total"], 2)
            self.assertEqual(data["active_total"], 1)
            self.assertEqual(data["archived_total"], 1)
            self.assertEqual(data["counts_by_status"]["pending"], 1)
            self.assertEqual(data["counts_by_status"]["archived"], 1)
            self.assertEqual(data["counts_by_predicate"]["file_exists"], 1)
            self.assertEqual(data["counts_by_target_transport"]["tmux"], 2)
            self.assertEqual(data["counts_by_visibility_classification"], {})
            self.assertTrue(data["earliest_next_attempt_at"])
            self.assertEqual(data["signal_readiness"]["status"], "ready")

    def test_status_command_reports_source_readiness_without_resource_identity(self) -> None:
        readiness = {
            "status": "blocked",
            "sources": [
                {
                    "source": "systemd",
                    "source_instance": "private-unit-source",
                    "status": "unavailable",
                },
                {
                    "source": "runtime",
                    "source_instance": "private-process-source",
                    "status": "ready",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "codex_wake.signal_support.signal_readiness", return_value=readiness
        ):
            root = Path(tmp)
            code, text_out, err = self.run_cli(["status"], root)
            self.assertEqual(code, 0, err)
            self.assertIn("signal_readiness=blocked", text_out)
            self.assertIn("signal_sources=runtime:ready,systemd:unavailable", text_out)
            self.assertNotIn("private-unit-source", text_out)
            self.assertNotIn("private-process-source", text_out)

            code, json_out, err = self.run_cli(["status", "--json"], root)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(json_out)["signal_readiness"], readiness)

    def test_cleanup_dry_run_and_delete_archived_records(self) -> None:
        observed = [datetime(2026, 5, 1, tzinfo=UTC).timestamp()]
        with tempfile.TemporaryDirectory() as tmp, patch(
                "codex_wake.measurements.utc_bounds",
                side_effect=lambda: (observed[0], observed[0])):
            root = Path(tmp)
            code, out, err = self.run_cli(["after", "1m", "--", "Cleanup later"], root)
            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            code, _, err = self.run_cli(["cancel", wake_id], root)
            self.assertEqual(code, 0, err)
            code, _, err = self.run_cli(["archive", wake_id], root)
            self.assertEqual(code, 0, err)
            archived_path = root / "archive" / f"{wake_id}.json"
            observed[0] = datetime(2026, 5, 19, tzinfo=UTC).timestamp()
            code, dry_run, err = self.run_cli(["cleanup", "--older-than", "7d"], root)
            self.assertEqual(code, 0, err)
            self.assertIn("would-delete", dry_run)
            self.assertTrue(archived_path.exists())

            code, deleted, err = self.run_cli(["cleanup", "--older-than", "7d", "--delete"], root)
            self.assertEqual(code, 0, err)
            self.assertIn("deleted", deleted)
            self.assertFalse(archived_path.exists())

    def test_cleanup_json_reports_archive_and_delete_candidates(self) -> None:
        observed = [datetime(2026, 5, 1, tzinfo=UTC).timestamp()]
        with tempfile.TemporaryDirectory() as tmp, patch(
                "codex_wake.measurements.utc_bounds",
                side_effect=lambda: (observed[0], observed[0])):
            root = Path(tmp)
            code, out, err = self.run_cli(["after", "1m", "--", "Cleanup json"], root)
            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            code, _, err = self.run_cli(["cancel", wake_id], root)
            self.assertEqual(code, 0, err)

            code, archive_json, err = self.run_cli(["cleanup", "--archive-terminal", "--older-than", "30d", "--json"], root)
            self.assertEqual(code, 0, err)
            archive_data = json.loads(archive_json)
            self.assertEqual(archive_data["mode"], "dry-run")
            self.assertTrue(archive_data["archive_terminal"])
            self.assertEqual(archive_data["archived_terminal_count"], 1)
            self.assertEqual(archive_data["archived_terminal"][0]["wake_id"], wake_id)
            archived_path = root / "archive" / f"{wake_id}.json"
            observed[0] = datetime(2026, 5, 19, tzinfo=UTC).timestamp()
            code, delete_json, err = self.run_cli(["cleanup", "--older-than", "7d", "--delete", "--json"], root)
            self.assertEqual(code, 0, err)
            delete_data = json.loads(delete_json)
            self.assertEqual(delete_data["mode"], "delete")
            self.assertEqual(delete_data["matched_count"], 1)
            self.assertEqual(delete_data["matched"][0]["wake_id"], wake_id)
            self.assertTrue(delete_data["matched"][0]["deleted"])
            self.assertFalse(archived_path.exists())

    def test_cleanup_can_archive_terminal_records_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(["after", "1m", "--", "Cleanup later"], root)
            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            code, _, err = self.run_cli(["cancel", wake_id], root)
            self.assertEqual(code, 0, err)

            code, cleanup_out, err = self.run_cli(["cleanup", "--archive-terminal", "--older-than", "1d"], root)

            self.assertEqual(code, 0, err)
            self.assertIn(f"archived {wake_id}", cleanup_out)
            self.assertTrue((root / "archive" / f"{wake_id}.json").exists())
            self.assertFalse((root / "cancelled" / f"{wake_id}.json").exists())

    def test_changed_creates_file_changed_predicate_with_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            watched = repo / "watched.log"
            watched.write_text("before", encoding="utf-8")
            root = repo / ".codex" / "wake"
            cwd = Path.cwd()
            try:
                os.chdir(repo)
                code, out, err = self.run_cli(["changed", "watched.log", "--", "Read changed log"], root)
            finally:
                os.chdir(cwd)

            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["predicate"]["type"], "file_changed")
            self.assertEqual(data["predicate"]["path"], "watched.log")
            self.assertTrue(data["predicate"]["registered_exists"])
            self.assertIsInstance(data["predicate"]["registered_mtime_ns"], int)
            self.assertEqual(data["predicate"]["registered_size"], len("before"))

    def test_changed_allows_missing_file_creation_watch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / ".codex" / "wake"
            cwd = Path.cwd()
            try:
                os.chdir(repo)
                code, out, err = self.run_cli(["changed", "missing.log", "--", "Read created log"], root)
            finally:
                os.chdir(cwd)

            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["predicate"]["type"], "file_changed")
            self.assertFalse(data["predicate"]["registered_exists"])
            self.assertIsNone(data["predicate"]["registered_mtime_ns"])
            self.assertIsNone(data["predicate"]["registered_size"])

    def test_pid_creates_process_done_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("codex_wake.cli.process_identity", return_value={"start_time_ticks": 12345, "boot_id": "boot-abc"}):
                code, out, err = self.run_cli(["pid", str(os.getpid()), "--", "Process done"], root)

            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(
                data["predicate"],
                {
                    "type": "process_done",
                    "pid": os.getpid(),
                    "registered_start_time_ticks": 12345,
                    "registered_boot_id": "boot-abc",
                },
            )

    def test_pid_keeps_liveness_fallback_when_identity_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("codex_wake.cli.process_identity", return_value=None):
                code, out, err = self.run_cli(["pid", str(os.getpid()), "--", "Process done"], root)

            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["predicate"], {"type": "process_done", "pid": os.getpid()})

    def test_create_requires_tmux_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"TMUX_PANE": "", "TMUX": ""}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(["--wake-root", str(root), "after", "--legacy-tmux", "1m", "--", "Wake"])
            self.assertEqual(code, 2)
            self.assertIn("TMUX_PANE is required", stderr.getvalue())

    def test_app_server_thread_target_does_not_require_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"TMUX_PANE": "", "TMUX": ""}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "--wake-root",
                            str(root),
                            "after",
                            "--app-server-thread-id",
                            "thread_abc",
                            "1m",
                            "--",
                            "Wake app server",
                        ]
                    )
            self.assertEqual(code, 0, stderr.getvalue())
            wake_id = stdout.getvalue().split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["target"], {"transport": "app-server", "endpoint": "stdio://", "thread_id": "thread_abc"})

    def test_app_after_creates_app_server_target_without_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"TMUX_PANE": "", "TMUX": ""}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "--wake-root",
                            str(root),
                            "app",
                            "after",
                            "thread_abc",
                            "1m",
                            "--",
                            "Wake app server",
                        ]
                    )

            self.assertEqual(code, 0, stderr.getvalue())
            wake_id = stdout.getvalue().split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["predicate"]["type"], "not_before")
            self.assertEqual(data["target"], {"transport": "app-server", "endpoint": "stdio://", "thread_id": "thread_abc"})

    def test_app_after_can_opt_into_active_writer_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(
                ["app", "after", "--retry-active-writer", "thread_abc", "1m", "--", "Wake app server"],
                root,
            )

            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertIs(data["target"]["retry_active_writer"], True)

    def test_compatibility_app_target_can_opt_into_active_writer_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(
                [
                    "after",
                    "--app-server-thread-id",
                    "thread_abc",
                    "--retry-active-writer",
                    "1m",
                    "--",
                    "Wake app server",
                ],
                root,
            )

            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertIs(data["target"]["retry_active_writer"], True)

    def test_app_after_can_persist_codex_cmd_for_daemon_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            codex = Path(tmp) / "bin" / "codex"
            codex.parent.mkdir()
            codex.write_text("#!/bin/sh\n", encoding="utf-8")
            codex.chmod(0o755)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"TMUX_PANE": "", "TMUX": ""}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "--wake-root",
                            str(root),
                            "app",
                            "after",
                            "--codex-path",
                            str(codex),
                            "thread_abc",
                            "1m",
                            "--",
                            "Wake app server",
                        ]
                    )

            self.assertEqual(code, 0, stderr.getvalue())
            wake_id = stdout.getvalue().split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["target"]["codex_cmd"], str(codex.resolve()))

    def test_openclaw_after_creates_gateway_target_without_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"TMUX_PANE": "", "TMUX": ""}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "--wake-root",
                            str(root),
                            "openclaw",
                            "after",
                            "--agent",
                            "main",
                            "--session-key",
                            "agent:main:slack:channel:c0ahqqcg7j4",
                            "--workspace",
                            "default",
                            "--channel",
                            "C0AHQQCG7J4",
                            "--thread-ts",
                            "1779729958.218239",
                            "1m",
                            "--",
                            "Wake OpenClaw",
                        ]
                    )

            self.assertEqual(code, 0, stderr.getvalue())
            wake_id = stdout.getvalue().split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["predicate"]["type"], "not_before")
            target = data["target"]
            self.assertEqual(target["transport"], "openclaw_gateway")
            self.assertEqual(target["openclaw"]["agent_id"], "main")
            self.assertEqual(target["openclaw"]["session_key"], "agent:main:slack:channel:c0ahqqcg7j4")
            self.assertEqual(target["openclaw"]["channel"]["workspace"], "default")
            self.assertEqual(target["openclaw"]["channel"]["channel_id"], "C0AHQQCG7J4")
            self.assertEqual(target["openclaw"]["channel"]["thread_ts"], "1779729958.218239")
            self.assertFalse(target["dispatch"]["deliver"])
            self.assertEqual(data["prompt"], "Wake OpenClaw")

    def test_openclaw_after_can_persist_openclaw_cmd_for_daemon_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            openclaw = Path(tmp) / "bin" / "openclaw"
            openclaw.parent.mkdir()
            openclaw.write_text("#!/bin/sh\n", encoding="utf-8")
            openclaw.chmod(0o755)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"TMUX_PANE": "", "TMUX": ""}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "--wake-root",
                            str(root),
                            "openclaw",
                            "after",
                            "--agent",
                            "main",
                            "--session-key",
                            "agent:main:slack:channel:c0ahqqcg7j4",
                            "--openclaw-path",
                            str(openclaw),
                            "1m",
                            "--",
                            "Wake OpenClaw",
                        ]
                    )

            self.assertEqual(code, 0, stderr.getvalue())
            wake_id = stdout.getvalue().split()[0]
            data = json.loads((root / "pending" / f"{wake_id}.json").read_text())
            self.assertEqual(data["target"]["openclaw_cmd"], str(openclaw.resolve()))

    def test_openclaw_after_rejects_placeholder_session_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(
                    [
                        "--wake-root",
                        str(root),
                        "openclaw",
                        "after",
                        "--agent",
                        "main",
                        "--session-key",
                        "agent:main:noop-smoke-test",
                        "1m",
                        "--",
                        "Wake OpenClaw",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertIn("unsupported placeholder value", stderr.getvalue())

    def test_openclaw_plugin_install_json_reports_non_link_install_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            source = Path(tmp) / "plugin"
            source.mkdir()
            with patch(
                "codex_wake.cli.install_openclaw_plugin",
                return_value={
                    "plugin_id": "codex-wake",
                    "plugin_version": "0.1.1",
                    "package_name": "@cochranresearchgroup/openclaw-codex-wake",
                    "package_version": "0.1.1",
                    "source_kind": "local-path",
                    "source_path": str(source),
                    "command": ["/usr/bin/openclaw", "plugins", "install", "--force", str(source)],
                    "dry_run": False,
                    "returncode": 0,
                    "stdout": "Installed codex-wake\n",
                    "stderr": "",
                },
            ) as install_plugin:
                code, out, err = self.run_cli(
                    [
                        "openclaw-plugin",
                        "install",
                        "--source-dir",
                        str(source),
                        "--openclaw-path",
                        "/usr/bin/openclaw",
                        "--force",
                        "--json",
                    ],
                    root,
                )

            self.assertEqual(code, 0, err)
            install_plugin.assert_called_once()
            kwargs = install_plugin.call_args.kwargs
            self.assertEqual(kwargs["source_dir"], source)
            self.assertTrue(kwargs["force"])
            self.assertFalse(kwargs["refresh"])
            self.assertFalse(kwargs["prune_linked_path"])
            data = json.loads(out)
            self.assertEqual(data["plugin_id"], "codex-wake")
            self.assertEqual(data["source_kind"], "local-path")
            self.assertNotIn("--link", data["command"])

    def test_openclaw_plugin_install_can_request_linked_path_prune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            source = Path(tmp) / "plugin"
            linked = Path(tmp) / "repo" / "plugins" / "openclaw-codex-wake"
            config = Path(tmp) / "openclaw.json"
            with patch(
                "codex_wake.cli.install_openclaw_plugin",
                return_value={
                    "plugin_id": "codex-wake",
                    "plugin_version": "0.1.1",
                    "package_name": "@cochranresearchgroup/openclaw-codex-wake",
                    "package_version": "0.1.1",
                    "source_kind": "local-path",
                    "source_path": str(source),
                    "command": ["/usr/bin/openclaw", "plugins", "install", "--force", str(source)],
                    "dry_run": False,
                    "returncode": 0,
                    "stdout": "Installed codex-wake\n",
                    "stderr": "",
                    "prune_linked_path": {
                        "config_path": str(config),
                        "backup_path": str(config) + ".codex-wake-backup-20260526T120000Z",
                        "linked_source_dir": str(linked),
                        "removed_paths": [str(linked)],
                        "changed": True,
                        "dry_run": False,
                    },
                },
            ) as install_plugin:
                code, out, err = self.run_cli(
                    [
                        "openclaw-plugin",
                        "install",
                        "--source-dir",
                        str(source),
                        "--force",
                        "--prune-linked-path",
                        "--linked-source-dir",
                        str(linked),
                        "--openclaw-config",
                        str(config),
                        "--json",
                    ],
                    root,
                )

            self.assertEqual(code, 0, err)
            kwargs = install_plugin.call_args.kwargs
            self.assertTrue(kwargs["prune_linked_path"])
            self.assertEqual(kwargs["linked_source_dir"], linked)
            self.assertEqual(kwargs["openclaw_config"], config)
            data = json.loads(out)
            self.assertEqual(data["prune_linked_path"]["removed_paths"], [str(linked)])

    def test_openclaw_plugin_update_forces_and_refreshes_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            with patch(
                "codex_wake.cli.install_openclaw_plugin",
                return_value={
                    "plugin_id": "codex-wake",
                    "plugin_version": "0.1.1",
                    "package_name": "@cochranresearchgroup/openclaw-codex-wake",
                    "package_version": "0.1.1",
                    "source_kind": "git-materialized",
                    "source_path": str(Path(tmp) / "materialized"),
                    "command": ["/usr/bin/openclaw", "plugins", "install", "--force", str(Path(tmp) / "materialized")],
                    "dry_run": True,
                    "returncode": None,
                    "stdout": "",
                    "stderr": "",
                    "prune_linked_path": None,
                },
            ) as install_plugin:
                code, out, err = self.run_cli(
                    [
                        "openclaw-plugin",
                        "update",
                        "--tag",
                        "v0.4.15",
                        "--openclaw-path",
                        "/usr/bin/openclaw",
                        "--dry-run",
                    ],
                    root,
                )

            self.assertEqual(code, 0, err)
            kwargs = install_plugin.call_args.kwargs
            self.assertEqual(kwargs["ref"], "v0.4.15")
            self.assertTrue(kwargs["force"])
            self.assertTrue(kwargs["refresh"])
            self.assertFalse(kwargs["prune_linked_path"])
            self.assertIn("plugin_id=codex-wake", out)
            self.assertIn("dry_run=true", out)

    def test_openclaw_plugin_pack_prints_install_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            output = Path(tmp) / "dist"
            with patch(
                "codex_wake.cli.pack_openclaw_plugin",
                return_value={
                    "plugin_id": "codex-wake",
                    "plugin_version": "0.1.1",
                    "package_name": "@cochranresearchgroup/openclaw-codex-wake",
                    "package_version": "0.1.1",
                    "source_path": str(Path(tmp) / "plugin"),
                    "output_dir": str(output),
                    "tarball": str(output / "plugin.tgz"),
                    "command": ["npm", "pack"],
                    "stdout": "plugin.tgz\n",
                    "stderr": "",
                },
            ) as pack_plugin:
                code, out, err = self.run_cli(
                    ["openclaw-plugin", "pack", "--output-dir", str(output)],
                    root,
                )

            self.assertEqual(code, 0, err)
            self.assertEqual(pack_plugin.call_args.kwargs["output_dir"], output)
            self.assertIn("install_hint=openclaw plugins install npm-pack:", out)

    def test_openclaw_after_requires_session_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exc:
                    cli.main(
                        [
                            "--wake-root",
                            str(root),
                            "openclaw",
                            "after",
                            "--agent",
                            "main",
                            "1m",
                            "--",
                            "Wake OpenClaw",
                        ]
                    )

            self.assertEqual(exc.exception.code, 2)
            self.assertIn("the following arguments are required: --session-key", stderr.getvalue())

    def test_app_rejects_non_stdio_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(
                    [
                        "--wake-root",
                            str(root),
                            "app",
                            "after",
                            "--endpoint",
                            "ws://127.0.0.1:4500",
                            "thread_abc",
                            "1m",
                            "--",
                            "Wake app server",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertIn("only app-server endpoint stdio://", stderr.getvalue())

    def test_app_server_rejects_non_stdio_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(
                    [
                        "--wake-root",
                        str(root),
                        "after",
                        "--app-server-thread-id",
                        "thread_abc",
                        "--app-server-endpoint",
                        "ws://127.0.0.1:4500",
                        "1m",
                        "--",
                        "Wake app server",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("only app-server endpoint stdio://", stderr.getvalue())

    def test_service_status_command_prints_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            unit_path = Path(tmp) / "unit.service"
            log_path = Path(tmp) / "service.log"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("codex_wake.cli.service_status", return_value=("inactive", "disabled")), \
                    patch("codex_wake.cli.service_dispatch_mode", return_value="disabled"):
                with patch("codex_wake.cli.build_service_config") as build_config:
                    build_config.return_value = type(
                        "Config",
                        (),
                        {
                            "name": "wake-test.service",
                            "unit_path": unit_path,
                            "log_path": log_path,
                        },
                    )()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = cli.main(["--wake-root", str(root), "service", "status"])

            self.assertEqual(code, 0, stderr.getvalue())
            self.assertIn("name=wake-test.service", stdout.getvalue())
            self.assertIn(f"unit={unit_path}", stdout.getvalue())
            self.assertIn("dispatch=disabled", stdout.getvalue())

    def test_monitor_check_json_reports_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            readiness = {
                "wake_root": str(root),
                "repo_root": str(Path(tmp)),
                "monitor_ready": True,
                "monitor_source": "repo_service",
                "service": {
                    "name": "wake-test.service",
                    "active": "active",
                    "enabled": "enabled",
                    "unit": str(Path(tmp) / "wake-test.service"),
                    "log": str(Path(tmp) / "wake.log"),
                    "wake_root": str(root),
                    "matches_wake_root": True,
                    "config_error": "",
                },
                "health": {
                    "path": str(Path(tmp) / "health.json"),
                    "exists": False,
                    "recent": False,
                    "persistent": False,
                    "source": "",
                    "mode": "",
                    "checked_at": "",
                    "pid": "",
                },
                "transports": {},
            }
            with patch("codex_wake.cli.monitor_readiness", return_value=readiness):
                code, out, err = self.run_cli(["monitor", "check", "--json"], root)

            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertTrue(data["monitor_ready"])
            self.assertEqual(data["monitor_source"], "repo_service")

    def test_require_monitor_blocks_unmonitored_wake_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            readiness = {
                "wake_root": str(root),
                "monitor_ready": False,
                "service": {"name": "wake-test.service", "active": "inactive", "wake_root": ""},
                "health": {"recent": False},
            }
            with patch("codex_wake.cli.monitor_readiness", return_value=readiness):
                code, _out, err = self.run_cli(["after", "--require-monitor", "1m", "--", "Wake later"], root)

            self.assertEqual(code, 2)
            self.assertIn("no active monitor owns this wake root", err)
            self.assertFalse((root / "pending").exists())

    def test_require_monitor_allows_ready_wake(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            readiness = {
                "wake_root": str(root),
                "monitor_ready": True,
                "service": {"name": "wake-test.service", "active": "active", "wake_root": str(root)},
                "health": {"recent": True},
            }
            with patch("codex_wake.cli.monitor_readiness", return_value=readiness):
                code, out, err = self.run_cli(["after", "--require-monitor", "1m", "--", "Wake later"], root)

            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            self.assertTrue((root / "pending" / f"{wake_id}.json").exists())

    def test_hook_install_and_check_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / ".codex" / "wake"
            codex_home = repo / "codex-home"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(["--wake-root", str(root), "hook", "install", "--repo-root", str(repo)])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertIn("installed hook config", stdout.getvalue())

            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(["--wake-root", str(root), "hook", "check", "--repo-root", str(repo)])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertIn("installed=true", stdout.getvalue())
            self.assertIn("/hooks review", stdout.getvalue())
            self.assertIn("does not list", stdout.getvalue())
            self.assertIn("hook_project_config_installed=true", stdout.getvalue())
            self.assertIn("hook_user_config_installed=false", stdout.getvalue())
            self.assertIn("hook_duplicate_install=false", stdout.getvalue())
            self.assertIn("hook_ack_count=0", stdout.getvalue())
            self.assertIn("hook_active_session_loaded=unknown_without_ack", stdout.getvalue())

    def test_doctor_reports_readiness_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / ".codex" / "wake"
            codex_home = repo / "codex-home"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("codex_wake.cli.service_status", return_value=("inactive", "disabled")):
                with patch("codex_wake.cli.service_app_server_readiness", return_value=self.readiness()):
                    with patch("codex_wake.cli.shutil.which", side_effect=lambda name, **_: f"/usr/bin/{name}"):
                        with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                                code = cli.main(["--wake-root", str(root), "doctor", "--repo-root", str(repo)])
            self.assertEqual(code, 0, stderr.getvalue())
            output = stdout.getvalue()
            self.assertIn(f"repo_root={repo}", output)
            self.assertIn(f"wake_root={root}", output)
            self.assertIn("codex_waked=/usr/bin/codex-waked", output)
            self.assertIn("codex=/usr/bin/codex", output)
            self.assertIn("hook_config_installed=false", output)
            self.assertIn("hook_user_config_installed=false", output)
            self.assertIn("hook_duplicate_install=false", output)
            self.assertIn("hook_active_session_loaded=unknown_without_ack", output)
            self.assertIn("service_active=inactive", output)
            self.assertIn("service_app_server_codex_ready=true", output)
            self.assertIn("service_app_server_codex_source=unit_environment", output)
            self.assertIn("service_app_server_codex_cmd=/usr/bin/codex", output)
            self.assertIn("restart or resume", output)

    def test_doctor_json_reports_readiness_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / ".codex" / "wake"
            codex_home = repo / "codex-home"
            ack_dir = root / "acks"
            ack_dir.mkdir(parents=True)
            (ack_dir / "wake_seen.submitted").write_text(
                json.dumps(
                    {
                        "wake_id": "wake_seen",
                        "submitted_at": "2026-05-20T03:30:00Z",
                        "session_id": "session_seen",
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("codex_wake.cli.service_status", return_value=("active", "enabled")):
                with patch("codex_wake.cli.service_app_server_readiness", return_value=self.readiness()):
                    with patch("codex_wake.cli.shutil.which", side_effect=lambda name, **_: f"/usr/bin/{name}"):
                        with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                                code = cli.main(["--wake-root", str(root), "doctor", "--repo-root", str(repo), "--json"])

            self.assertEqual(code, 0, stderr.getvalue())
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["repo_root"], str(repo))
            self.assertEqual(data["wake_root"], str(root))
            self.assertEqual(data["commands"]["codex_waked"], "/usr/bin/codex-waked")
            self.assertEqual(data["commands"]["codex"], "/usr/bin/codex")
            self.assertEqual(data["commands"]["tmux"], "/usr/bin/tmux")
            self.assertFalse(data["hook_config"]["installed"])
            self.assertFalse(data["hook_sources"]["project"]["installed"])
            self.assertFalse(data["hook_sources"]["user"]["installed"])
            self.assertFalse(data["hook_sources"]["duplicate_installed"])
            self.assertEqual(data["hook_runtime"]["ack_count"], 1)
            self.assertEqual(data["hook_runtime"]["active_session_loaded"], "observed_ack")
            self.assertEqual(data["hook_runtime"]["latest_ack_wake_id"], "wake_seen")
            self.assertEqual(data["service"]["active"], "active")
            self.assertTrue(data["service_app_server"]["codex_cmd_ready"])
            self.assertEqual(data["service_app_server"]["codex_cmd_source"], "unit_environment")
            self.assertEqual(data["service_app_server"]["codex_cmd"], "/usr/bin/codex")
            self.assertIn("restart or resume", data["trust"])

    def test_doctor_uses_supervisor_owned_app_server_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / ".codex" / "wake"
            supervisor_app_server = {
                "codex_cmd_ready": False,
                "codex_cmd_source": "supervisor_registry_missing",
                "codex_cmd": "",
                "unit_codex_cmd": "",
                "user_manager_codex_cmd": "",
                "interactive_codex_cmd": "",
                "message": "supervisor root registration does not set dispatch.codex_cmd",
            }
            monitor = {
                "monitor_ready": True,
                "monitor_source": "supervisor",
                "transports": {"app_server": supervisor_app_server},
                "signals": {"capability": {"status": "ready"}, "sources": []},
            }
            with patch("codex_wake.cli.service_status", return_value=("inactive", "disabled")):
                with patch("codex_wake.cli.service_app_server_readiness", return_value=self.readiness()):
                    with patch("codex_wake.cli.monitor_readiness", return_value=monitor):
                        code, out, err = self.run_cli(
                            ["doctor", "--repo-root", str(repo), "--json"],
                            root,
                        )

            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertFalse(data["service_app_server"]["codex_cmd_ready"])
            self.assertEqual(
                data["service_app_server"]["codex_cmd_source"],
                "supervisor_registry_missing",
            )

    def test_doctor_json_reports_duplicate_hook_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            codex_home = Path(tmp) / "codex-home"
            root = repo / ".codex" / "wake"
            repo.mkdir()
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--wake-root", str(root), "hook", "install", "--repo-root", str(repo)])
            user_hook = codex_home / "hooks.json"
            user_hook.parent.mkdir()
            user_hook.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "UserPromptSubmit": [
                                {"hooks": [{"type": "command", "command": "codex-wake-hook"}]}
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("codex_wake.cli.service_status", return_value=("inactive", "disabled")):
                with patch("codex_wake.cli.service_app_server_readiness", return_value=self.readiness()):
                    with patch("codex_wake.cli.shutil.which", side_effect=lambda name, **_: f"/usr/bin/{name}"):
                        with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                                code = cli.main(["--wake-root", str(root), "doctor", "--repo-root", str(repo), "--json"])

            self.assertEqual(code, 0, stderr.getvalue())
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["hook_sources"]["installed_scopes"], ["project", "user"])
            self.assertTrue(data["hook_sources"]["duplicate_installed"])
            self.assertIn("duplicate wake context", data["hook_sources"]["overlap_warning"])

    def test_product_readiness_json_reports_normalized_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            with patch(
                "codex_wake.cli.product_readiness_summary",
                return_value={
                    "schema_version": 1,
                    "generated_at": "2026-05-26T12:00:00Z",
                    "repo_root": str(Path(tmp) / "repo"),
                    "wake_root": str(root),
                    "overall_status": "blocked",
                    "status_vocabulary": ["ready", "warning", "manual_only", "blocked"],
                    "checks": {
                        "cli": {"status": "ready", "message": "installed"},
                        "openclaw_gateway": {"status": "blocked", "message": "auth missing"},
                        "tmux": {"status": "manual_only", "message": "no pane"},
                    },
                },
            ) as readiness:
                code, out, err = self.run_cli(["product-readiness", "--json"], root)

            self.assertEqual(code, 0, err)
            readiness.assert_called_once()
            data = json.loads(out)
            self.assertEqual(data["overall_status"], "blocked")
            self.assertEqual(data["checks"]["tmux"]["status"], "manual_only")

    def test_product_readiness_text_prints_check_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            with patch(
                "codex_wake.cli.product_readiness_summary",
                return_value={
                    "schema_version": 1,
                    "generated_at": "2026-05-26T12:00:00Z",
                    "repo_root": str(Path(tmp) / "repo"),
                    "wake_root": str(root),
                    "overall_status": "warning",
                    "status_vocabulary": ["ready", "warning", "manual_only", "blocked"],
                    "checks": {
                        "cli": {"status": "ready", "message": "installed"},
                        "hooks": {"status": "warning", "message": "hook missing"},
                        "skills": {"status": "ready", "message": "skill installed"},
                        "repo_service": {"status": "warning", "message": "inactive"},
                        "supervisor": {"status": "ready", "message": "active"},
                        "monitor": {"status": "ready", "message": "owned"},
                        "app_server": {"status": "ready", "message": "codex ready"},
                        "openclaw_gateway": {"status": "ready", "message": "rpc ready"},
                        "openclaw_plugin": {"status": "ready", "message": "plugin ready"},
                        "tmux": {"status": "manual_only", "message": "no pane"},
                    },
                },
            ):
                code, out, err = self.run_cli(["product-readiness"], root)

            self.assertEqual(code, 0, err)
            self.assertIn("overall_status=warning", out)
            self.assertIn("hooks_status=warning", out)
            self.assertIn("tmux_status=manual_only", out)

    def test_hook_check_reports_latest_ack_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / ".codex" / "wake"
            ack_dir = root / "acks"
            ack_dir.mkdir(parents=True)
            (ack_dir / "wake_seen.submitted").write_text(
                json.dumps(
                    {
                        "wake_id": "wake_seen",
                        "submitted_at": "2026-05-18T21:30:00Z",
                        "session_id": "session_seen",
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(["--wake-root", str(root), "hook", "install", "--repo-root", str(repo)])
            self.assertEqual(code, 0, stderr.getvalue())

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(["--wake-root", str(root), "hook", "check", "--repo-root", str(repo)])

            self.assertEqual(code, 0, stderr.getvalue())
            output = stdout.getvalue()
            self.assertIn("hook_ack_count=1", output)
            self.assertIn("hook_active_session_loaded=observed_ack", output)
            self.assertIn("hook_latest_ack_wake_id=wake_seen", output)
            self.assertIn("hook_latest_ack_session_id=session_seen", output)

    def test_hook_user_install_and_check_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "codex-home"
            root = Path(tmp) / "wake"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(
                    [
                        "--wake-root",
                        str(root),
                        "hook",
                        "user",
                        "install",
                        "--codex-home",
                        str(codex_home),
                    ]
                )

            self.assertEqual(code, 0, stderr.getvalue())
            self.assertIn("installed user hook config", stdout.getvalue())
            self.assertTrue((codex_home / "hooks.json").exists())

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(
                    [
                        "--wake-root",
                        str(root),
                        "hook",
                        "user",
                        "check",
                        "--codex-home",
                        str(codex_home),
                    ]
                )

            self.assertEqual(code, 0, stderr.getvalue())
            output = stdout.getvalue()
            self.assertIn(f"path={codex_home / 'hooks.json'}", output)
            self.assertIn("scope=user", output)
            self.assertIn("installed=true", output)
            self.assertIn("hook_active_session_loaded=unknown_without_ack", output)


if __name__ == "__main__":
    unittest.main()
