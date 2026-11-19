from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from codex_wake.app_server import StdioAppServerClient
from codex_wake.monitor import write_monitor_health
from codex_wake.event_wake import EventWake
from codex_wake.filesystem_signals import FilesystemSignalAdapter
from codex_wake.records import WakeError, build_record, write_record
from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher, signal_journal_path
from codex_wake.signal_store import SQLiteSignalModule
from codex_wake.signals import Resume, WakeIntent
from codex_wake.supervisor import (
    build_supervisor_config,
    enroll_root,
    install_supervisor,
    iter_registry_entries,
    render_supervisor_unit,
    resolve_codex_wake_path,
    stop_supervisor,
    supervisor_poll_once,
    supervisor_status,
    uninstall_supervisor,
    unenroll_root,
)


class FakeRunner:
    def __init__(self, active: str = "active", enabled: str = "enabled") -> None:
        self.active = active
        self.enabled = enabled
        self.calls: list[list[str]] = []

    def run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        stdout = ""
        if "is-active" in args:
            stdout = f"{self.active}\n"
        if "is-enabled" in args:
            stdout = f"{self.enabled}\n"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


class SupervisorTests(unittest.TestCase):
    def test_supervisor_preserves_mixed_legacy_and_signal_readers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(
                unit_dir=base / "systemd",
                registry_dir=base / "registry",
                state_dir=base / "state" / "supervisor",
                validate_executable=False,
            )
            legacy_root = base / "legacy" / "wake"
            legacy = build_record(
                predicate={"type": "not_before", "due_at": "2026-09-14T00:00:00Z"},
                prompt="legacy",
                cwd=base,
                target={"transport": "tmux", "tmux_socket": "/tmp/tmux", "pane": "%1"},
            )
            legacy["id"] = "wake_legacy"
            write_record(legacy_root, legacy)
            signal_repo = base / "signal"
            signal_root = signal_repo / "wake"
            adapter = FilesystemSignalAdapter(signal_repo, "ready.flag")
            runtime = SQLiteSignalModule(
                signal_journal_path(signal_root),
                record_publisher=WakeRecordPublisher(
                    signal_root,
                    ManagedReaderCapability(signal_root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            EventWake(
                runtime,
                adapters=(adapter,),
                clock=lambda: datetime(2026, 9, 14, 18, 0, tzinfo=UTC),
                id_factory=lambda: "wake_signal",
            ).register(
                WakeIntent(adapter.request("created"), Resume("signal", signal_repo, {"transport": "tmux"})),
                idempotency_key="signal",
            )
            signal_repo.mkdir(exist_ok=True)
            (signal_repo / "ready.flag").write_text("ready", encoding="utf-8")
            enroll_root(wake_root=legacy_root, repo_root=base / "legacy", registry_dir=config.registry_dir, root_id="legacy")
            enroll_root(wake_root=signal_root, repo_root=signal_repo, registry_dir=config.registry_dir, root_id="signal")

            results = supervisor_poll_once(config, mode="once", dispatch=False)

            self.assertEqual([item["root_id"] for item in results], ["legacy", "signal"])
            self.assertTrue(all(item["ok"] for item in results))
            self.assertTrue((legacy_root / "firing" / "wake_legacy.json").is_file())
            signal_record = json.loads(
                (signal_root / "firing" / "wake_signal.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                signal_record["trigger_match"]["attributes"]["observation_reason"],
                "startup",
            )

    def make_executable(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_enroll_and_unenroll_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            registry = base / "config" / "roots.d"
            wake_root = base / "repo" / ".codex" / "wake"
            path = enroll_root(wake_root=wake_root, repo_root=base / "repo", registry_dir=registry, root_id="repo-test")

            data = json.loads(path.read_text())
            self.assertEqual(data["root_id"], "repo-test")
            self.assertEqual(data["wake_root"], str(wake_root.resolve()))
            self.assertTrue(data["enabled"])
            self.assertEqual(len(iter_registry_entries(registry)), 1)

            removed = unenroll_root(root_id="repo-test", registry_dir=registry)
            self.assertEqual(removed, path)
            self.assertFalse(path.exists())

    def test_enroll_preserves_stable_codex_and_openclaw_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex = self.make_executable(base / "bin" / "codex")
            openclaw = self.make_executable(base / "bin" / "openclaw")
            path = enroll_root(
                wake_root=base / "repo" / ".codex" / "wake",
                repo_root=base / "repo",
                registry_dir=base / "registry",
                codex_cmd=str(codex),
                openclaw_cmd=str(openclaw),
            )

            dispatch = json.loads(path.read_text())["dispatch"]
            self.assertEqual(dispatch["codex_cmd"], str(codex))
            self.assertEqual(dispatch["openclaw_cmd"], str(openclaw))

    def test_supervisor_dispatch_uses_enrolled_codex_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wake_root = base / "repo" / ".codex" / "wake"
            codex = base / "bin" / "codex"
            codex.parent.mkdir(parents=True)
            codex.write_text(
                f"""#!{sys.executable}
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "initialize":
        result = {{"userAgent": "fake"}}
    elif method == "thread/resume":
        result = {{"thread": {{"id": request["params"]["threadId"], "status": {{"type": "idle"}}}}}}
    elif method == "turn/start":
        result = {{"turn": {{"id": "turn_supervisor"}}}}
    else:
        result = {{}}
    print(json.dumps({{"jsonrpc": "2.0", "id": request["id"], "result": result}}), flush=True)
""",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            config = build_supervisor_config(
                unit_dir=base / "systemd",
                registry_dir=base / "registry",
                state_dir=base / "state" / "supervisor",
                validate_executable=False,
            )
            enroll_root(
                wake_root=wake_root,
                repo_root=base / "repo",
                registry_dir=config.registry_dir,
                codex_cmd=str(codex),
            )
            record = build_record(
                predicate={"type": "not_before", "due_at": "2000-01-01T00:00:00Z"},
                prompt="supervisor default command",
                cwd=base / "repo",
                target={
                    "transport": "app-server",
                    "endpoint": "stdio://",
                    "thread_id": "thread_supervisor",
                },
                now=datetime(2000, 1, 1, tzinfo=UTC),
            )
            record["id"] = "wake_supervisor"
            write_record(wake_root, record)

            # This fixture qualifies enrolled executable routing only. The Unix
            # daemon/connection lifetime is exercised by test_app_server_lifecycle.
            with patch.dict("os.environ", {"PATH": "/definitely/missing"}, clear=True), patch(
                "codex_wake.app_server.UnixWebSocketAppServerClient",
                side_effect=lambda codex_cmd: StdioAppServerClient(codex_cmd=codex_cmd),
            ):
                results = supervisor_poll_once(config, mode="once")

            self.assertTrue(results[0]["ok"])
            health = json.loads(Path(results[0]["health_path"]).read_text(encoding="utf-8"))
            self.assertTrue(health["transports"]["app_server"]["codex_cmd_ready"])
            self.assertEqual(
                health["transports"]["app_server"]["codex_cmd_source"],
                "supervisor_registry",
            )
            submitted = json.loads(
                (wake_root / "submitted" / "wake_supervisor.json").read_text(encoding="utf-8")
            )
            self.assertEqual(submitted["dispatch_result"]["turn_id"], "turn_supervisor")
            self.assertNotIn("codex_cmd", submitted["target"])

    def test_supervisor_health_rejects_stale_enrolled_codex_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex = self.make_executable(base / "bin" / "codex")
            config = build_supervisor_config(
                unit_dir=base / "systemd",
                registry_dir=base / "registry",
                state_dir=base / "state" / "supervisor",
                validate_executable=False,
            )
            enroll_root(
                wake_root=base / "repo" / ".codex" / "wake",
                repo_root=base / "repo",
                registry_dir=config.registry_dir,
                codex_cmd=str(codex),
            )
            codex.unlink()

            results = supervisor_poll_once(config, mode="loop", dispatch=False)

            health = json.loads(Path(results[0]["health_path"]).read_text(encoding="utf-8"))
            app_server = health["transports"]["app_server"]
            self.assertFalse(app_server["codex_cmd_ready"])
            self.assertEqual(app_server["codex_cmd_source"], "supervisor_registry")
            self.assertIn("does not exist", app_server["message"])

    def test_enroll_rejects_version_managed_node_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            openclaw = self.make_executable(
                base / ".nvm" / "versions" / "node" / "v24.1.0" / "bin" / "openclaw"
            )

            with self.assertRaisesRegex(WakeError, "stable wrapper or symlink"):
                enroll_root(
                    wake_root=base / "repo" / ".codex" / "wake",
                    registry_dir=base / "registry",
                    openclaw_cmd=str(openclaw),
                )

            self.assertFalse((base / "registry").exists())

    def test_lifecycle_and_registry_commands_do_not_require_supervisor_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(
                codex_wake_path=str(base / "missing-codex-wake"),
                unit_dir=base / "systemd",
                registry_dir=base / "registry",
                state_dir=base / "state",
                validate_executable=False,
            )
            self.assertIsNone(config.codex_wake_path)
            path = enroll_root(
                wake_root=base / "repo" / ".codex" / "wake",
                registry_dir=config.registry_dir,
                root_id="lifecycle",
            )
            self.assertEqual(supervisor_status(config, FakeRunner())["root_count"], 1)
            self.assertEqual(unenroll_root(root_id="lifecycle", registry_dir=config.registry_dir), path)
            runner = FakeRunner()
            stop_supervisor(config, runner)
            uninstall_supervisor(config, runner)
            self.assertIn(["systemctl", "--user", "disable", "--now", config.name], runner.calls)
            with self.assertRaisesRegex(WakeError, "resolved before rendering"):
                render_supervisor_unit(config)

    def test_resolve_codex_wake_uses_valid_named_invocation_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invoked = self.make_executable(Path(tmp) / "bin" / "codex-wake")
            with patch("codex_wake.executables.shutil.which", return_value=None):
                with patch("sys.argv", [str(invoked)]):
                    self.assertEqual(resolve_codex_wake_path(), invoked)

    def test_concurrent_enrollment_writes_complete_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            registry = base / "registry"
            wake_root = base / "repo" / ".codex" / "wake"
            writers = 12
            barrier = threading.Barrier(writers + 1)
            stop_reading = threading.Event()
            read_errors: list[Exception] = []
            target = registry / "shared-root.json"

            def read_while_writing() -> None:
                barrier.wait()
                while not stop_reading.is_set():
                    try:
                        json.loads(target.read_text(encoding="utf-8"))
                    except FileNotFoundError:
                        pass
                    except Exception as exc:
                        read_errors.append(exc)

            def write(index: int) -> Path:
                barrier.wait()
                return enroll_root(
                    wake_root=wake_root,
                    repo_root=base / "repo",
                    registry_dir=registry,
                    root_id="shared-root",
                    owner_name=f"writer-{index}",
                )

            reader = threading.Thread(target=read_while_writing)
            reader.start()
            try:
                with ThreadPoolExecutor(max_workers=writers) as pool:
                    paths = list(pool.map(write, range(writers)))
            finally:
                stop_reading.set()
                reader.join()

            self.assertEqual(len(set(paths)), 1)
            self.assertEqual(read_errors, [])
            payload = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["root_id"], "shared-root")
            self.assertRegex(payload["owner"]["name"], r"^writer-\d+$")
            self.assertEqual(sorted(item.name for item in registry.iterdir()), ["shared-root.json"])

    def test_render_and_install_supervisor_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_wake = self.make_executable(base / "bin" / "codex-wake")
            config = build_supervisor_config(
                codex_wake_path=str(codex_wake),
                unit_dir=base / "systemd",
                log_path=base / "state" / "supervisor.log",
                registry_dir=base / "config" / "roots.d",
                state_dir=base / "state" / "supervisor",
            )
            unit = render_supervisor_unit(config)

            self.assertIn("codex-wake-supervisor.service", config.name)
            self.assertIn("supervisor run --interval 1", unit)
            self.assertIn("--registry-dir", unit)
            self.assertIn("--state-dir", unit)
            self.assertIn(f'ExecStart="{codex_wake}" supervisor run', unit)

            runner = FakeRunner()
            install_supervisor(config, runner)
            self.assertTrue(config.unit_path.exists())
            self.assertEqual(
                runner.calls,
                [
                    ["systemctl", "--user", "daemon-reload"],
                    ["systemctl", "--user", "enable", "--now", config.name],
                    ["systemctl", "--user", "is-active", config.name],
                ],
            )
            uninstall_supervisor(config, runner)
            self.assertFalse(config.unit_path.exists())

    def test_supervisor_status_lists_registered_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_wake = self.make_executable(base / "bin" / "codex-wake")
            config = build_supervisor_config(
                codex_wake_path=str(codex_wake),
                unit_dir=base / "systemd",
                log_path=base / "state" / "supervisor.log",
                registry_dir=base / "config" / "roots.d",
                state_dir=base / "state" / "supervisor",
            )
            wake_root = base / "repo" / ".codex" / "wake"
            enroll_root(wake_root=wake_root, repo_root=base / "repo", registry_dir=config.registry_dir, root_id="repo-test")

            status = supervisor_status(config, FakeRunner(active="inactive", enabled="disabled"))

            self.assertEqual(status["service"]["active"], "inactive")
            self.assertEqual(status["root_count"], 1)
            self.assertEqual(status["roots"][0]["root_id"], "repo-test")
            self.assertEqual(status["roots"][0]["wake_root"], str(wake_root.resolve()))
            self.assertEqual(status["roots"][0]["health_status"], "missing")
            self.assertIn("supervisor run --once", status["roots"][0]["remediation"])

    def test_supervisor_status_marks_stale_health_with_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_wake = self.make_executable(base / "bin" / "codex-wake")
            config = build_supervisor_config(
                codex_wake_path=str(codex_wake),
                unit_dir=base / "systemd",
                log_path=base / "state" / "supervisor.log",
                registry_dir=base / "config" / "roots.d",
                state_dir=base / "state" / "supervisor",
            )
            wake_root = base / "repo" / ".codex" / "wake"
            enroll_root(wake_root=wake_root, repo_root=base / "repo", registry_dir=config.registry_dir, root_id="repo-test")
            write_monitor_health(
                wake_root=wake_root,
                repo_root=base / "repo",
                source="supervisor",
                mode="loop",
                state_dir=config.state_dir.parent / "monitors",
                now=datetime.now(UTC) - timedelta(hours=1),
            )

            status = supervisor_status(config, FakeRunner(active="active", enabled="enabled"))

            root_status = status["roots"][0]
            self.assertFalse(root_status["health_recent"])
            self.assertEqual(root_status["health_status"], "stale")
            self.assertIn("codex-wake-supervisor.service", root_status["remediation"])
            self.assertIn("supervisor unenroll --root-id repo-test", root_status["remediation"])

    def test_supervisor_run_once_polls_registered_roots_and_writes_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_wake = self.make_executable(base / "bin" / "codex-wake")
            config = build_supervisor_config(
                codex_wake_path=str(codex_wake),
                unit_dir=base / "systemd",
                log_path=base / "state" / "supervisor.log",
                registry_dir=base / "config" / "roots.d",
                state_dir=base / "state" / "supervisor",
            )
            repo = base / "repo"
            wake_root = repo / ".codex" / "wake"
            enroll_root(wake_root=wake_root, repo_root=repo, registry_dir=config.registry_dir, root_id="repo-test")
            record = build_record(
                predicate={"type": "not_before", "due_at": "2026-05-25T20:39:34Z"},
                prompt="Resume",
                now=datetime(2026, 5, 25, tzinfo=UTC),
                cwd=repo,
                target={"transport": "tmux", "tmux_socket": "/tmp/tmux/default", "pane": "%1"},
            )
            record["id"] = "wake_supervisor"
            write_record(wake_root, record)

            with patch("codex_wake.supervisor.poll_once") as poll_once:
                poll_once.return_value = type(
                    "Result",
                    (),
                    {
                        "checked": 1,
                        "fired": 1,
                        "failed": 0,
                        "pending": 0,
                        "dispatched": 0,
                        "submitted": 0,
                        "requeued": 0,
                        "time_held": 0,
                    },
                )()
                results = supervisor_poll_once(config, mode="loop", dispatch=False)

            self.assertEqual(results[0]["root_id"], "repo-test")
            self.assertTrue(results[0]["ok"])
            self.assertTrue(results[0]["activity"])
            self.assertTrue((base / "state" / "monitors").exists())
            poll_once.assert_called_once()
            self.assertFalse(poll_once.call_args.kwargs["dispatch"])


if __name__ == "__main__":
    unittest.main()
