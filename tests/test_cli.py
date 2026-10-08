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
        env = {
            **os.environ,
            "TMUX_PANE": "%11",
            "TMUX": "/tmp/tmux-1000/default,123,0",
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, env, clear=False):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(["--wake-root", str(root), *argv])
        return code, stdout.getvalue(), stderr.getvalue()

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
            self.assertIn("file_changed", data["predicate_types"])

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

    def test_cleanup_dry_run_and_delete_archived_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err = self.run_cli(["after", "1m", "--", "Cleanup later"], root)
            self.assertEqual(code, 0, err)
            wake_id = out.split()[0]
            code, _, err = self.run_cli(["cancel", wake_id], root)
            self.assertEqual(code, 0, err)
            code, _, err = self.run_cli(["archive", wake_id], root)
            self.assertEqual(code, 0, err)
            archived_path = root / "archive" / f"{wake_id}.json"
            data = json.loads(archived_path.read_text())
            data["archived_at"] = "2026-05-01T00:00:00Z"
            data["updated_at"] = "2026-05-01T00:00:00Z"
            archived_path.write_text(json.dumps(data), encoding="utf-8")

            with patch("codex_wake.records.utc_now", return_value=datetime(2026, 5, 19, tzinfo=UTC)):
                code, dry_run, err = self.run_cli(["cleanup", "--older-than", "7d"], root)
            self.assertEqual(code, 0, err)
            self.assertIn("would-delete", dry_run)
            self.assertTrue(archived_path.exists())

            with patch("codex_wake.records.utc_now", return_value=datetime(2026, 5, 19, tzinfo=UTC)):
                code, deleted, err = self.run_cli(["cleanup", "--older-than", "7d", "--delete"], root)
            self.assertEqual(code, 0, err)
            self.assertIn("deleted", deleted)
            self.assertFalse(archived_path.exists())

    def test_cleanup_json_reports_archive_and_delete_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
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
            record = json.loads(archived_path.read_text())
            record["archived_at"] = "2026-05-01T00:00:00Z"
            record["updated_at"] = "2026-05-01T00:00:00Z"
            archived_path.write_text(json.dumps(record), encoding="utf-8")

            with patch("codex_wake.records.utc_now", return_value=datetime(2026, 5, 19, tzinfo=UTC)):
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
                    code = cli.main(["--wake-root", str(root), "after", "1m", "--", "Wake"])
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
            self.assertEqual(data["target"], {"transport": "app-server", "endpoint": "stdio://", "thread_id": "thread_abc", "inline_payload": True})

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
            self.assertEqual(data["target"], {"transport": "app-server", "endpoint": "stdio://", "thread_id": "thread_abc", "inline_payload": True})

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
            with patch("codex_wake.cli.service_status", return_value=("inactive", "disabled")):
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
