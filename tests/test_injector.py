from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from codex_wake.injector import (
    PaneLock,
    canonical_prompt,
    dispatch_firing_record,
    lock_name_for_pane,
    unsafe_pane_reason,
)
from codex_wake.records import WakePath, build_record, write_record


class FakeTmuxRunner:
    def __init__(self, capture: str = "Codex ready", captures: list[str | BaseException] | None = None) -> None:
        self.captures: list[str | BaseException] = list(captures) if captures is not None else [capture]
        self.capture_calls = 0
        self.pastes: list[tuple[str, str, str, str]] = []

    def capture_pane(self, socket: str, pane: str) -> str:
        self.capture_calls += 1
        if len(self.captures) > 1:
            value = self.captures.pop(0)
        else:
            value = self.captures[0]
        if isinstance(value, BaseException):
            raise value
        return value

    def paste_prompt(self, socket: str, pane: str, wake_id: str, prompt: str) -> None:
        self.pastes.append((socket, pane, wake_id, prompt))


class InjectorTests(unittest.TestCase):
    def make_firing_record(self, root: Path, cwd: Path, prompt: str = "full continuation prompt") -> WakePath:
        now = datetime(2026, 5, 18, 20, 30, tzinfo=UTC)
        record = build_record(
            predicate={"type": "not_before", "due_at": "2026-05-18T21:15:00Z"},
            prompt=prompt,
            cwd=cwd,
            target={"transport": "tmux", "tmux_socket": "/tmp/tmux/default", "pane": "%1"},
            now=now,
        )
        record["id"] = "wake_test"
        record["status"] = "firing"
        path = write_record(root, record)
        return WakePath(path=path, record=record)

    def test_canonical_prompt_uses_wake_id_only(self) -> None:
        self.assertEqual(canonical_prompt("wake_123"), "WAKE_TRIGGER_ID=wake_123\nResume the scheduled wake task.\n")

    def test_unsafe_pane_reason_rejects_shell_prompt_and_approval(self) -> None:
        self.assertEqual(unsafe_pane_reason("Approve command?"), "approval prompt visible")
        self.assertEqual(unsafe_pane_reason("user@host:~/repo$ "), "pane appears to be a shell prompt")
        self.assertIsNone(unsafe_pane_reason("Codex\nready for input"))

    def test_pane_lock_rejects_concurrent_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with PaneLock(root, "/tmp/tmux/default", "%1"):
                with self.assertRaises(ValueError):
                    with PaneLock(root, "/tmp/tmux/default", "%1"):
                        pass
            self.assertFalse((root / "locks" / f"{lock_name_for_pane('/tmp/tmux/default', '%1')}.lock").exists())

    def test_idle_composer_ignores_historical_approval_words(self) -> None:
        for history in ("approval prompt visible", "Approve command?",
                        "User approved the update", "running command",
                        '"last_error": "unsafe pane: approval prompt visible"'):
            for footer in ("gpt-6 · Context 86% left", "gpt-5 · 86% context left"):
                with self.subTest(history=history, footer=footer):
                    self.assertIsNone(unsafe_pane_reason(
                        f"{history}\n› Ask Codex to do anything\n{footer}"))

    def test_busy_composer_stays_blocked(self) -> None:
        self.assertEqual(unsafe_pane_reason(
            "• Working (13s • esc to interrupt)\n\n› Ask Codex to do anything\n"
            "gpt-6 · Context 86% left"), "agent appears to be running")

    def test_draft_composer_stays_blocked(self) -> None:
        self.assertEqual(unsafe_pane_reason(
            "› my unsent draft\ngpt-6 · Context 86% left"),
            "composer contains a draft or unrecognized prompt")

    def test_actual_approval_dialogs_stay_blocked(self) -> None:
        for dialog in ("Approve command?", "Approval required\n› 1. Yes\n2. No",
                       "Allow this command?\nDeny / Allow",
                       "› Ask Codex to do anything\nApproval required\n"
                       "gpt-6 · Context 86% left"):
            with self.subTest(dialog=dialog):
                self.assertIsNotNone(unsafe_pane_reason(dialog))

    def test_historical_approval_does_not_prevent_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp))
            runner = FakeTmuxRunner(capture="approval prompt visible\n"
                "› Ask Codex to do anything\ngpt-6 · Context 86% left")
            (root / "acks").mkdir(exist_ok=True)
            (root / "acks" / "wake_test.submitted").touch()
            result = dispatch_firing_record(root, found, runner=runner,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), ack_timeout_override=0)
            self.assertEqual(result.status, "submitted")
            self.assertEqual(len(runner.pastes), 1)

    def test_pane_lock_removes_stale_dead_pid_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / "locks" / f"{lock_name_for_pane('/tmp/tmux/default', '%1')}.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("999999999", encoding="ascii")

            with PaneLock(root, "/tmp/tmux/default", "%1"):
                self.assertEqual(lock_path.read_text(encoding="ascii"), str(os.getpid()))

            self.assertFalse(lock_path.exists())

    def test_pane_lock_removes_malformed_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / "locks" / f"{lock_name_for_pane('/tmp/tmux/default', '%1')}.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("not-a-pid", encoding="ascii")

            with PaneLock(root, "/tmp/tmux/default", "%1"):
                self.assertEqual(lock_path.read_text(encoding="ascii"), str(os.getpid()))

            self.assertFalse(lock_path.exists())

    def test_dispatch_pastes_only_canonical_prompt_and_requeues_without_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), prompt="SECRET FULL PROMPT")
            runner = FakeTmuxRunner()

            result = dispatch_firing_record(
                root,
                found,
                runner=runner,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                ack_timeout_override=0,
            )

            self.assertEqual(result.status, "requeued")
            self.assertEqual(len(runner.pastes), 1)
            self.assertEqual(runner.pastes[0][3], canonical_prompt("wake_test"))
            self.assertNotIn("SECRET FULL PROMPT", runner.pastes[0][3])
            pending = root / "pending" / "wake_test.json"
            self.assertTrue(pending.exists())
            data = json.loads(pending.read_text())
            self.assertEqual(data["attempts"], 1)
            self.assertEqual(data["events"][-2]["type"], "ack_timeout")
            self.assertEqual(data["events"][-1]["type"], "requeued")

    def test_dispatch_marks_submitted_when_ack_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp))
            ack_dir = root / "acks"
            ack_dir.mkdir(parents=True, exist_ok=True)
            (ack_dir / "wake_test.submitted").write_text("{}", encoding="utf-8")

            result = dispatch_firing_record(
                root,
                found,
                runner=FakeTmuxRunner(),
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                ack_timeout_override=0,
            )

            self.assertEqual(result.status, "submitted")
            submitted_path = root / "submitted" / "wake_test.json"
            self.assertTrue(submitted_path.exists())
            data = json.loads(submitted_path.read_text())
            self.assertEqual(data["visibility_result"]["classification"], "ack_observed_visibility_unproven")
            self.assertEqual(data["events"][-2]["type"], "ack_observed")
            self.assertEqual(data["events"][-1]["type"], "tmux_visibility_checked")

    def test_dispatch_records_visible_prompt_when_marker_appears_after_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp))
            ack_dir = root / "acks"
            ack_dir.mkdir(parents=True, exist_ok=True)
            (ack_dir / "wake_test.submitted").write_text("{}", encoding="utf-8")
            runner = FakeTmuxRunner(
                captures=[
                    "Codex ready",
                    "Codex\n> WAKE_TRIGGER_ID=wake_test\n  Resume the scheduled wake task.",
                ]
            )

            result = dispatch_firing_record(
                root,
                found,
                runner=runner,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                ack_timeout_override=0,
            )

            self.assertEqual(result.status, "submitted")
            data = json.loads((root / "submitted" / "wake_test.json").read_text())
            visibility = data["visibility_result"]
            self.assertEqual(visibility["classification"], "visible_prompt_observed")
            self.assertFalse(visibility["pre_capture"]["wake_marker_present"])
            self.assertTrue(visibility["post_capture"]["wake_marker_present"])
            self.assertTrue(visibility["post_marker_new"])
            self.assertEqual(visibility["privacy"], "raw_pane_text_not_stored")
            self.assertEqual(data["events"][-1]["visibility_result"]["classification"], "visible_prompt_observed")
            self.assertNotIn("WAKE_TRIGGER_ID", json.dumps(visibility))

    def test_dispatch_records_visibility_check_failure_without_failing_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp))
            ack_dir = root / "acks"
            ack_dir.mkdir(parents=True, exist_ok=True)
            (ack_dir / "wake_test.submitted").write_text("{}", encoding="utf-8")
            runner = FakeTmuxRunner(captures=["Codex ready", OSError("capture failed")])

            result = dispatch_firing_record(
                root,
                found,
                runner=runner,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                ack_timeout_override=0,
            )

            self.assertEqual(result.status, "submitted")
            data = json.loads((root / "submitted" / "wake_test.json").read_text())
            visibility = data["visibility_result"]
            self.assertEqual(visibility["classification"], "visibility_check_failed")
            self.assertIn("post-ack tmux capture failed", visibility["error"])
            self.assertEqual(data["events"][-2]["type"], "ack_observed")
            self.assertEqual(data["events"][-1]["type"], "tmux_visibility_checked")
            self.assertEqual(data["status"], "submitted")

    def test_unsafe_pane_requeues_and_does_not_paste(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp))
            runner = FakeTmuxRunner(capture="Approve command?")

            result = dispatch_firing_record(
                root,
                found,
                runner=runner,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                ack_timeout_override=0,
            )

            self.assertEqual(result.status, "requeued")
            self.assertEqual(runner.pastes, [])
            data = json.loads((root / "pending" / "wake_test.json").read_text())
            self.assertEqual(data["attempts"], 1)
            self.assertEqual(data["events"][-2]["type"], "unsafe_pane")


if __name__ == "__main__":
    unittest.main()
