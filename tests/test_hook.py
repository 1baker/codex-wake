from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_wake.hook import extract_wake_id, handle_payload, main
from codex_wake.records import build_record, write_record


class HookTests(unittest.TestCase):
    def make_payload(self, cwd: Path, prompt: str) -> dict:
        return {
            "prompt": prompt,
            "cwd": str(cwd),
            "turn_id": "turn_123",
            "session_id": "session_456",
            "hook_event_name": "UserPromptSubmit",
        }

    def test_extract_wake_id(self) -> None:
        self.assertEqual(extract_wake_id("WAKE_TRIGGER_ID=wake_123\nResume"), "wake_123")
        self.assertIsNone(extract_wake_id("ordinary prompt"))

    def test_no_match_returns_none_and_writes_no_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = handle_payload(self.make_payload(Path(tmp), "ordinary prompt"))
            self.assertIsNone(output)
            self.assertFalse((Path(tmp) / ".codex" / "wake" / "acks").exists())

    def test_found_record_writes_ack_and_adds_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            wake_root = cwd / ".codex" / "wake"
            record = build_record(
                predicate={"type": "file_exists", "path": ".codex/events/pytest.done"},
                prompt="Read pytest log and continue",
                cwd=cwd,
                target={"transport": "tmux", "tmux_socket": "/tmp/tmux/default", "pane": "%1"},
            )
            record["id"] = "wake_test"
            record["status"] = "firing"
            record["context_paths"] = ["docs/dev/context.md"]
            record["evidence_paths"] = [".codex/events/pytest.log"]
            write_record(wake_root, record)

            output = handle_payload(self.make_payload(cwd, "WAKE_TRIGGER_ID=wake_test\nResume"))

            ack_path = wake_root / "acks" / "wake_test.submitted"
            self.assertTrue(ack_path.exists())
            ack = json.loads(ack_path.read_text())
            self.assertEqual(ack["wake_id"], "wake_test")
            self.assertEqual(ack["turn_id"], "turn_123")
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("A scheduled wake trigger fired.", context)
            self.assertIn("Read pytest log and continue", context)
            self.assertIn(".codex/events/pytest.log", context)

    def test_missing_record_writes_ack_and_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output = handle_payload(self.make_payload(cwd, "WAKE_TRIGGER_ID=wake_missing\nResume"))

            self.assertTrue((cwd / ".codex" / "wake" / "acks" / "wake_missing.submitted").exists())
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("trigger file was not found", context)

    def test_resolves_monitored_root_when_resumed_tui_cwd_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            wake_root = repo / ".codex" / "wake"
            record = build_record(
                predicate={"type": "not_before"},
                prompt="Verify managed resume",
                cwd=repo,
                target={"transport": "tmux", "tmux_socket": "/tmp/tmux/default", "pane": "%1"},
            )
            record["id"] = "wake_monitored"
            record["status"] = "firing"
            write_record(wake_root, record)
            monitor_dir = base / ".local" / "state" / "codex-wake" / "monitors"
            monitor_dir.mkdir(parents=True)
            (monitor_dir / "root.json").write_text(json.dumps({"wake_root": str(wake_root)}), encoding="utf-8")

            with patch("codex_wake.hook.Path.home", return_value=base):
                output = handle_payload(self.make_payload(base, "WAKE_TRIGGER_ID=wake_monitored\nResume"))

            self.assertTrue((wake_root / "acks" / "wake_monitored.submitted").exists())
            self.assertIn("Verify managed resume", output["hookSpecificOutput"]["additionalContext"])

    def test_main_prints_hook_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.make_payload(Path(tmp), "WAKE_TRIGGER_ID=wake_missing\nResume")
            stdin = io.StringIO(json.dumps(payload))
            stdout = io.StringIO()
            with patch("sys.stdin", stdin), contextlib.redirect_stdout(stdout):
                code = main([])
            self.assertEqual(code, 0)
            parsed = json.loads(stdout.getvalue())
            self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")


if __name__ == "__main__":
    unittest.main()
