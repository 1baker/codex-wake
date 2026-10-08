from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from codex_wake.owner_delivery import (
    inline_prompt, payload_digest, reconcile_owner_record, rollout_cursor,
    dispatch_owner_record, validate_process_snapshot, completion_token, process_snapshot, owner_pane_idle,
)
from codex_wake.records import WakeError, WakePath, build_record, find_record, write_record


class OwnerDeliveryTests(unittest.TestCase):
    def record(self, root: Path, rollout: Path):
        r = build_record(predicate={"type": "not_before", "due_at": "2026-10-05T04:00:00Z"},
            prompt="Reply TEST_OK. Do not use tools.", cwd=root,
            target={"transport": "tmux", "pane": "%1", "tmux_socket": "/tmp/sock",
                    "owner_thread_id": "owner", "owner_pid": 123, "owner_start_ticks": 45,
                    "owner_remote": "ws://127.0.0.1:50000", "rollout_path": str(rollout)})
        r["id"] = "wake_owner"
        r["status"] = "firing"
        return r

    def rollout(self, root: Path):
        path = root / "rollout.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": "owner"}}) + "\n" +
                        json.dumps({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "baseline"}}) + "\n")
        return path

    def append(self, path, event):
        with path.open("a") as f:
            f.write(json.dumps(event) + "\n")

    def user(self, r, turn="turn_new"):
        return {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": inline_prompt(r)}],
            "internal_chat_message_metadata_passthrough": {"turn_id": turn}}}

    def arm(self, r, path, now):
        r["delivery"] = {"state": "pasted", "monitor_pid": 999,
            "payload_sha256": payload_digest(r["prompt"]), "cursor": rollout_cursor(path, "owner"),
            "accept_deadline": (now + timedelta(seconds=30)).isoformat(),
            "completion_deadline": (now + timedelta(hours=3)).isoformat()}
        return r

    def test_payload_bounded_and_digest_bound(self):
        r = {"id": "wake_owner", "prompt": "exact task"}
        p = inline_prompt(r)
        self.assertTrue(p.startswith("WAKE_TRIGGER_ID=wake_owner\nWAKE_PAYLOAD_SHA256="))
        self.assertIn(hashlib.sha256(b"exact task").hexdigest(), p)
        self.assertNotIn(completion_token(r), p)
        with self.assertRaises(WakeError):
            inline_prompt({"id": "wake_owner", "prompt": "x" * 8193})

    def test_current_tui_shortcuts_footer_is_positive_idle_not_arbitrary_output(self):
        composer = "› Ask Codex to do anything\nGPT-6-Luna low · Context 94% left"
        self.assertTrue(owner_pane_idle(composer + "\n? for shortcuts"))
        self.assertTrue(owner_pane_idle(composer + "\n? for shortcuts     ⚠ 1 warning · f2 to view"))
        for unknown in ("Approve this command?", "? for shortcuts\nRunning tool", "unexpected footer"):
            self.assertFalse(owner_pane_idle(composer + "\n" + unknown))

    def test_exact_process_lifetime_foreground_ancestry_and_remote(self):
        target = {"owner_thread_id": "owner", "owner_start_ticks": 45,
                  "owner_remote": "ws://127.0.0.1:50000"}
        snap = {"start_ticks": 45, "pgid": 12, "tpgid": 12, "tty": 99,
                "args": ["codex", "--remote", "ws://127.0.0.1:50000", "resume", "owner"]}
        validate_process_snapshot(target, snap, pane_tty=99, ancestor_match=True)
        for changes in ({"start_ticks": 46}, {"tpgid": 15}, {"tty": 100},
                        {"args": ["codex", "resume", "other"]}):
            with self.assertRaises(WakeError):
                validate_process_snapshot(target, {**snap, **changes}, pane_tty=99, ancestor_match=True)
        with self.assertRaises(WakeError):
            validate_process_snapshot(target, snap, pane_tty=99, ancestor_match=False)

    def test_reconcile_accepts_only_matching_user_digest_and_exact_terminal_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self.rollout(root); now = datetime.now(UTC)
            r = self.arm(self.record(root, path), path, now); write_record(root, r)
            wrong = self.user(r); wrong["payload"]["content"][0]["text"] = "WAKE_TRIGGER_ID=wake_owner\nwrong"
            self.append(path, wrong)
            self.append(path, self.user(r))
            self.append(path, {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "other"}})
            reconcile_owner_record(root, find_record(root, r["id"]), now=now, monitor_pid=999)
            found = find_record(root, r["id"])
            self.assertEqual(found.record["delivery"]["state"], "accepted")
            self.assertEqual(found.record["dispatch_result"]["turn_id"], "turn_new")
            self.append(path, {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn_new",
                "last_agent_message": "TEST_OK WAKE_DONE=wake_owner"}})
            reconcile_owner_record(root, found, now=now, monitor_pid=999)
            self.assertEqual(find_record(root, r["id"]).record["delivery"]["state"], "completed")

    def test_crash_after_sending_or_paste_never_requeues(self):
        for state in ("sending", "pasted"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); path = self.rollout(root); now = datetime.now(UTC)
                r = self.arm(self.record(root, path), path, now); r["delivery"]["state"] = state
                write_record(root, r)
                reconcile_owner_record(root, find_record(root, r["id"]), now=now, monitor_pid=1000)
                data = find_record(root, r["id"]).record
                self.assertEqual(data["status"], "failed")
                self.assertEqual(data["delivery"]["state"], "uncertain")

    def test_truncation_and_inode_change_and_accept_timeout_fail_closed(self):
        for case in ("truncate", "replace", "timeout"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); path = self.rollout(root); now = datetime.now(UTC)
                r = self.arm(self.record(root, path), path, now); write_record(root, r)
                if case == "truncate": path.write_text("")
                if case == "replace":
                    path.rename(root / "old.jsonl"); self.rollout(root)
                reconcile_owner_record(root, find_record(root, r["id"]), now=now+timedelta(seconds=31), monitor_pid=999)
                self.assertEqual(find_record(root, r["id"]).record["delivery"]["state"], "uncertain")

    def test_abort_not_completion_and_partial_line_retried_without_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self.rollout(root); now = datetime.now(UTC)
            r = self.arm(self.record(root, path), path, now); write_record(root, r)
            text = json.dumps(self.user(r))
            with path.open("a") as f: f.write(text[:30])
            old = r["delivery"]["cursor"]["offset"]
            reconcile_owner_record(root, find_record(root, r["id"]), now=now, monitor_pid=999)
            self.assertEqual(find_record(root, r["id"]).record["delivery"]["cursor"]["offset"], old)
            with path.open("a") as f: f.write(text[30:] + "\n")
            self.append(path, {"type": "event_msg", "payload": {"type": "turn_aborted", "turn_id": "turn_new", "reason": "interrupted"}})
            reconcile_owner_record(root, find_record(root, r["id"]), now=now, monitor_pid=999)
            self.assertEqual(find_record(root, r["id"]).record["delivery"]["state"], "interrupted")

    def test_second_capture_blocks_paste_and_recovered_sending_cannot_paste(self):
        class Runner:
            def __init__(self): self.calls = 0; self.pastes = 0
            def capture_pane(self, *args):
                self.calls += 1
                return "Codex\n› Ask Codex to do anything\ngpt-6 · Context 80% left" if self.calls == 1 else "Approve command?"
            def paste_prompt(self, *args): self.pastes += 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self.rollout(root); r = self.record(root, path); write_record(root, r)
            runner = Runner()
            with patch("codex_wake.owner_delivery.verify_owner_target"):
                result = dispatch_owner_record(root, find_record(root, r["id"]), runner=runner)
            self.assertEqual(runner.pastes, 0)
            self.assertEqual(result.status, "failed")
            data = find_record(root, r["id"]).record
            self.assertEqual(data["delivery"]["state"], "not_sent")
            data["status"] = "firing"; data["delivery"]["state"] = "sending"; write_record(root, data)
            dispatch_owner_record(root, find_record(root, r["id"]), runner=runner)
            self.assertEqual(runner.pastes, 0)

    def test_active_runtime_even_with_idle_looking_composer_never_pastes(self):
        class Runner:
            def capture_pane(self,*args): return "› Ask Codex to do anything\ngpt-6 · Context 80% left"
            def paste_prompt(self,*args): raise AssertionError("busy runtime must not receive a paste")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=self.rollout(root); r=self.record(root,path); write_record(root,r)
            self.append(path,{"type":"event_msg","payload":{"type":"task_started","turn_id":"active"}})
            with patch("codex_wake.owner_delivery.verify_owner_target"):
                result=dispatch_owner_record(root,find_record(root,r["id"]),runner=Runner())
            self.assertEqual(result.status,"waiting")
            data=find_record(root,r["id"]).record
            self.assertEqual(data["attempts"],0)
            self.assertNotIn("delivery",data)

    def test_live_foreign_monitor_is_not_failed_by_concurrent_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=self.rollout(root); now=datetime.now(UTC)
            r=self.arm(self.record(root,path),path,now)
            r["delivery"]["monitor_pid"]=os.getpid()
            r["delivery"]["monitor_start_ticks"]=process_snapshot(os.getpid())["start_ticks"]
            write_record(root,r)
            reconcile_owner_record(root,find_record(root,r["id"]),now=now,monitor_pid=999999999)
            self.assertEqual(find_record(root,r["id"]).record["delivery"]["state"],"pasted")

    def test_two_due_owner_records_in_one_poll_paste_only_once(self):
        from codex_wake.daemon import poll_once

        class Runner:
            def __init__(self): self.pastes = []
            def capture_pane(self, *args): return "› Ask Codex to do anything\nGPT-6 · Context 80% left"
            def paste_owner_prompt(self, socket, pane, wake_id, prompt): self.pastes.append(wake_id)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self.rollout(root)
            first = self.record(root, path); second = self.record(root, path)
            second["id"] = "wake_other"
            write_record(root, first); write_record(root, second)
            runner = Runner()
            with patch("codex_wake.owner_delivery.verify_owner_target"):
                poll_once(root, runner=runner)
            self.assertEqual(len(runner.pastes), 1)
            sent = find_record(root, runner.pastes[0]).record
            self.assertEqual(sent["delivery"]["state"], "pasted")
            untouched_id = next(r["id"] for r in (first, second) if r["id"] not in runner.pastes)
            untouched = find_record(root, untouched_id).record
            self.assertNotIn("delivery", untouched)
            self.assertEqual(untouched["attempts"], 0)
            self.assertEqual(untouched["events"], second["events"])

    def test_owner_inflight_guard_covers_firing_and_submitted_live_states(self):
        for status in ("firing", "submitted"):
            for state in ("sending", "pasted", "accepted"):
                with self.subTest(status=status, state=state), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp); path = self.rollout(root)
                    blocked = self.record(root, path); blocker = self.record(root, path)
                    blocker["id"] = "wake_existing"; blocker["status"] = status
                    blocker["delivery"] = {"state": state}
                    write_record(root, blocked); write_record(root, blocker)
                    with patch("codex_wake.owner_delivery.verify_owner_target") as verify:
                        result = dispatch_owner_record(root, find_record(root, blocked["id"]))
                    self.assertEqual(result.status, "waiting")
                    verify.assert_not_called()
                    self.assertNotIn("delivery", find_record(root, blocked["id"]).record)

    def test_echoed_prompt_alone_cannot_be_visible_response(self):
        class Runner:
            def capture_pane(self,*args): return inline_prompt(r)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=self.rollout(root); now=datetime.now(UTC)
            r=self.arm(self.record(root,path),path,now); write_record(root,r)
            self.append(path,self.user(r))
            self.append(path,{"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn_new",
                "last_agent_message":"OK " + completion_token(r)}})
            with patch("codex_wake.owner_delivery.verify_owner_target"):
                reconcile_owner_record(root,find_record(root,r["id"]),now=now,monitor_pid=999,runner=Runner())
            self.assertEqual(find_record(root,r["id"]).record["visibility_result"]["classification"],"completion_visibility_unproven")

    def test_owner_bracketed_paste_uses_one_submit_and_once_cannot_dispatch(self):
        from codex_wake.injector import SubprocessTmuxRunner
        from codex_wake.daemon import poll_once
        with patch("codex_wake.injector.subprocess.run") as run, patch("codex_wake.injector.time.sleep"):
            SubprocessTmuxRunner().paste_owner_prompt("/tmp/socket","%1","wake_owner","line1\n\nline2")
            commands=[c.args[0] for c in run.call_args_list]
            self.assertIn("-p",commands[1])
            self.assertEqual(sum("send-keys" in cmd for cmd in commands),1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=self.rollout(root); r=self.record(root,path); write_record(root,r)
            with patch("codex_wake.injector.dispatch_firing_record") as dispatch:
                poll_once(root,allow_owner_dispatch=False)
                dispatch.assert_not_called()


if __name__ == "__main__": unittest.main()
