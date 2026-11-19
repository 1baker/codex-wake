from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from codex_wake.injector import (
    PaneLock,
    TmuxPane,
    canonical_prompt,
    dispatch_firing_record,
    lock_name_for_pane,
    unsafe_pane_reason,
    wait_for_ack,
)
from codex_wake.daemon import poll_once
from codex_wake.event_wake import EventWake
from codex_wake.records import WakeError, WakePath, build_record, cancel_record, find_record, replace_record, write_record
from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher, signal_journal_path
from codex_wake.signal_store import SQLiteSignalModule
from codex_wake.signals import SourceCommit
from tests.test_signal_store import make_observation
from tests.test_signals import make_adapter, make_intent


class FakeTmuxRunner:
    def __init__(
        self,
        capture: str = "Codex ready",
        captures: list[str | BaseException] | None = None,
        panes: list[TmuxPane] | None = None,
    ) -> None:
        self.captures: list[str | BaseException] = list(captures) if captures is not None else [capture]
        self.capture_calls = 0
        self.pastes: list[tuple[str, str, str, str]] = []
        self.panes = (
            panes
            if panes is not None
            else [TmuxPane("%1", "Owning session | repo", "/repo", 101, 202)]
        )

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

    def list_session_panes(self, socket: str, pane: str) -> list[TmuxPane]:
        return self.panes


class FakeAppServerClient:
    def __init__(self, *, status: str = "idle", fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.calls: list[tuple[str, object]] = []

    def initialize(self) -> dict:
        if self.fail:
            raise WakeError("app-server unavailable")
        return {}

    def resume_thread(self, thread_id: str, cwd: str | None = None) -> dict:
        self.calls.append(("resume", thread_id))
        return {"thread": {"id": thread_id, "status": {"type": self.status}}}

    def read_thread(self, thread_id: str, include_turns: bool = False) -> dict:
        self.calls.append(("read", thread_id))
        return {"thread": {"id": thread_id, "status": {"type": self.status}}}

    def start_turn(self, thread_id: str, prompt: str, cwd: str | None = None) -> dict:
        self.calls.append(("turn", thread_id))
        return {"turn": {"id": "turn_123"}}

    def close(self) -> None:
        return None


class InjectorTests(unittest.TestCase):
    def test_default_native_dispatch_holds_ambiguous_expiry_without_changing_original_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'wake'
            found = self.make_firing_record(root, Path(tmp))
            record = dict(found.record)
            record['schema_version'] = 4
            record['target'] = {'transport': 'native', 'thread_id': 'd6724570-2d77-415d-99b8-cd5ceeb3454a',
                'endpoint': 'unix:///tmp/unused-native.sock', 'codex_cmd': '/bin/false',
                'expires_at': '2026-05-18T21:15:00Z'}
            found = WakePath(write_record(root, record), record)
            expiry = datetime(2026, 5, 18, 21, 15, tzinfo=UTC).timestamp()
            with patch('codex_wake.measurements.utc_bounds', return_value=(expiry - 1, expiry + 1)):
                result = dispatch_firing_record(root, found)
            self.assertEqual(result.status, 'skipped')
            self.assertIn('expiry is uncertain', result.message)
            self.assertEqual(find_record(root, 'wake_test').record, record)
            with patch('codex_wake.measurements.utc_bounds', return_value=(expiry, expiry + 1)):
                result = dispatch_firing_record(root, found)
            self.assertEqual(result.status, 'failed')
            expired = find_record(root, 'wake_test').record
            self.assertEqual(expired['target']['expires_at'], '2026-05-18T21:15:00Z')
            self.assertEqual(expired['attempts'], 0)

    def test_default_dispatch_holds_without_qualified_utc_before_any_transport(self) -> None:
        from codex_wake import measurements
        with tempfile.TemporaryDirectory() as tmp:
            for transport in ('tmux', 'app-server'):
                with self.subTest(transport=transport):
                    root = Path(tmp) / transport
                    found = self.make_firing_record(root, Path(tmp))
                    runner = FakeTmuxRunner()
                    client = FakeAppServerClient()
                    record = dict(found.record)
                    if transport == 'app-server':
                        record['target'] = {'transport': 'app-server', 'thread_id': 'thread_abc', 'endpoint': 'stdio://'}
                    path = write_record(root, record)
                    with patch('codex_wake.measurements.datetime_now', side_effect=measurements.TimeUnavailable('clock unavailable')):
                        result = dispatch_firing_record(root, WakePath(path, record), runner=runner,
                            app_server_client=client, thread_identity_resolver=self.identity, ack_timeout_override=0)
                    self.assertEqual(result.status, 'skipped')
                    self.assertEqual(find_record(root, 'wake_test').record, record)
                    self.assertEqual(runner.capture_calls, 0)
                    self.assertEqual(runner.pastes, [])
                    self.assertEqual(client.calls, [])

    def test_default_dispatch_uses_qualified_metadata_and_reconciles_held_ack_without_utc(self) -> None:
        from codex_wake import measurements
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'wake'
            found = self.make_firing_record(root, Path(tmp))
            runner = FakeTmuxRunner()
            receipt = root / 'acks' / 'wake_test.submitted'
            receipt.parent.mkdir(exist_ok=True)
            receipt.write_text('{}')
            with patch('codex_wake.measurements.datetime_now', return_value=datetime(2026, 5, 18, 21, 15, tzinfo=UTC)):
                result = dispatch_firing_record(root, found, runner=runner,
                    thread_identity_resolver=self.identity, ack_timeout_override=0)
            self.assertEqual(result.status, 'submitted')
            submitted = find_record(root, 'wake_test')
            self.assertEqual(submitted.record['updated_at'], '2026-05-18T21:15:00Z')
            self.assertEqual(submitted.record['events'][-1]['at'], '2026-05-18T21:15:00Z')
            held_root = Path(tmp) / 'held'
            held = self.make_firing_record(held_root, Path(tmp))
            held.record['ack_wait_time_held'] = True
            held = WakePath(write_record(held_root, held.record), held.record)
            receipt = held_root / 'acks' / 'wake_test.submitted'
            receipt.parent.mkdir(exist_ok=True)
            receipt.write_text('{}')
            held_runner = FakeTmuxRunner()
            with patch('codex_wake.measurements.datetime_now', side_effect=measurements.TimeUnavailable('clock unavailable')):
                result = dispatch_firing_record(held_root, held, runner=held_runner)
            self.assertEqual(result.status, 'submitted')
            self.assertEqual(held_runner.pastes, [])
            event = find_record(held_root, 'wake_test').record['events'][-1]
            self.assertIsNone(event['at'])
            self.assertEqual(event['time_status'], 'not_observed')

    def test_ordinary_ack_wait_does_not_require_a_time_service_observation(self) -> None:
        from codex_wake import measurements
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / 'acks' / 'wake_test.submitted'
            receipt.parent.mkdir()
            receipt.write_text('{}')
            with patch('codex_wake.measurements.snapshot', side_effect=measurements.TimeUnavailable('client helper failed')):
                self.assertTrue(wait_for_ack(root, 'wake_test', 0))
                self.assertTrue(wait_for_ack(root, 'wake_test', 1))

    def test_ack_polling_adds_no_clock_gate_and_old_held_outcomes_do_not_replay(self) -> None:
        from codex_wake import measurements
        with tempfile.TemporaryDirectory() as tmp:
            for held in (False, True):
                with self.subTest(held=held):
                    root = Path(tmp) / str(held)
                    found = self.make_firing_record(root, Path(tmp))
                    if held:
                        found.record['ack_wait_time_held'] = True
                        found = WakePath(write_record(root, found.record), found.record)
                    else:
                        receipt = root / 'acks' / 'wake_test.submitted'
                        receipt.parent.mkdir(exist_ok=True)
                        receipt.write_text('{}')
                    runner = FakeTmuxRunner()
                    with patch('codex_wake.measurements.snapshot', side_effect=measurements.TimeUnavailable('client helper failed')):
                        result = dispatch_firing_record(root, found, runner=runner,
                            now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                            thread_identity_resolver=self.identity, ack_timeout_override=1)
                    self.assertEqual(result.status, 'skipped' if held else 'submitted')
                    self.assertEqual(len(runner.pastes), 0 if held else 1)

    def setUp(self) -> None:
        patcher = patch(
            "codex_wake.app_server.read_app_server_thread_identity",
            side_effect=self.identity,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_signal_cancellation_holds_lifecycle_lock_until_dispatch_reloads_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                lease_clock=lambda: datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
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
            runtime.ingest(
                [make_observation()],
                SourceCommit(
                    "memory", "contract-test", "checkpoint-1", 1,
                    datetime(2026, 9, 14, 14, 1, tzinfo=UTC),
                ),
            )
            poll_once(
                root,
                now=datetime(2026, 9, 14, 14, 2, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
            )
            firing = find_record(root, "wake_signal")
            lock_held = threading.Event()
            release = threading.Event()

            def cancellation_checkpoint(name: str) -> None:
                if name == "after_cancel_lock":
                    lock_held.set()
                    self.assertTrue(release.wait(timeout=5))

            runner = FakeTmuxRunner()
            with ThreadPoolExecutor(max_workers=2) as pool:
                cancellation = pool.submit(
                    cancel_record,
                    root,
                    "wake_signal",
                    datetime(2026, 9, 14, 14, 3, tzinfo=UTC),
                    checkpoint=cancellation_checkpoint,
                )
                self.assertTrue(lock_held.wait(timeout=5))
                dispatch = pool.submit(
                    dispatch_firing_record,
                    root,
                    firing,
                    runner=runner,
                    signal_authorizer=runtime.authorize_firing_record,
                )
                release.set()
                cancellation.result(timeout=5)
                result = dispatch.result(timeout=5)

            self.assertEqual(result.status, "skipped")
            self.assertEqual(runner.capture_calls, 0)
            self.assertEqual(runner.pastes, [])
            cancelled = json.loads((root / "cancelled" / "wake_signal.json").read_text())
            self.assertEqual(cancelled["attempts"], 0)

    def test_signal_firing_without_live_authority_makes_no_transport_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp))
            found.record["schema_version"] = 2
            found.record["record_revision"] = 2
            runner = FakeTmuxRunner()

            result = dispatch_firing_record(
                root,
                found,
                runner=runner,
                signal_authorizer=lambda _record: False,
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(found.record["attempts"], 0)
            self.assertEqual(runner.capture_calls, 0)
            self.assertEqual(runner.pastes, [])

    def test_signal_firing_with_tampered_payload_makes_no_transport_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                lease_clock=lambda: datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
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
            runtime.ingest(
                [make_observation()],
                SourceCommit(
                    "memory", "contract-test", "checkpoint-1", 1,
                    datetime(2026, 9, 14, 14, 1, tzinfo=UTC),
                ),
            )
            poll_once(
                root,
                now=datetime(2026, 9, 14, 14, 2, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
            )
            found = find_record(root, "wake_signal")
            tampered = dict(found.record)
            tampered["prompt"] = "tampered prompt"
            found.path.write_text(json.dumps(tampered), encoding="utf-8")
            runner = FakeTmuxRunner()

            result = dispatch_firing_record(
                root,
                WakePath(found.path, tampered),
                runner=runner,
                now=datetime(2026, 9, 14, 14, 2, tzinfo=UTC),
                signal_authorizer=runtime.authorize_firing_record,
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(runner.capture_calls, 0)
            self.assertEqual(runner.pastes, [])

    def make_firing_record(
        self,
        root: Path,
        cwd: Path,
        prompt: str = "full continuation prompt",
        *,
        max_attempts: int = 3,
        thread_id: str | None = "thread_abc",
    ) -> WakePath:
        now = datetime(2026, 5, 18, 20, 30, tzinfo=UTC)
        record = build_record(
            predicate={"type": "not_before", "due_at": "2026-05-18T21:15:00Z"},
            prompt=prompt,
            cwd=cwd,
            target={
                "transport": "tmux",
                "tmux_socket": "/tmp/tmux/default",
                "pane": "%1",
                **({"thread_id": thread_id} if thread_id else {}),
                **({"client_pid": 101, "client_start_time_ticks": 202} if thread_id else {}),
            },
            now=now,
        )
        record["id"] = "wake_test"
        record["status"] = "firing"
        record["max_attempts"] = max_attempts
        path = write_record(root, record)
        return WakePath(path=path, record=record)

    @staticmethod
    def identity(thread_id: str, **_kwargs: object) -> dict[str, str]:
        return {"thread_id": thread_id, "name": "Owning session", "cwd": "/repo"}

    def test_session_aware_dispatch_uses_unchanged_original_pane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), thread_id="thread_abc")
            (root / "acks").mkdir(parents=True, exist_ok=True)
            (root / "acks" / "wake_test.submitted").write_text("{}", encoding="utf-8")
            runner = FakeTmuxRunner(panes=[TmuxPane("%1", "Owning session | repo", "/repo", 101, 202)])

            result = dispatch_firing_record(
                root, found, runner=runner, thread_identity_resolver=self.identity,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), ack_timeout_override=0,
            )

            self.assertEqual(result.status, "submitted")
            self.assertEqual(runner.pastes[0][1], "%1")
            data = json.loads((root / "submitted" / "wake_test.json").read_text())
            self.assertEqual(data["route_selection"]["outcome"], "original_pane")

    def test_session_aware_dispatch_routes_to_unique_relocated_pane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), thread_id="thread_abc")
            (root / "acks").mkdir(parents=True, exist_ok=True)
            (root / "acks" / "wake_test.submitted").write_text("{}", encoding="utf-8")
            runner = FakeTmuxRunner(panes=[
                TmuxPane("%1", "Foreign session | repo", "/repo", 303, 404),
                TmuxPane("%9", "⠋ Owning session | repo", "/repo", 101, 202),
            ])

            result = dispatch_firing_record(
                root, found, runner=runner, thread_identity_resolver=self.identity,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), ack_timeout_override=0,
            )

            self.assertEqual(result.status, "submitted")
            self.assertEqual([paste[1] for paste in runner.pastes], ["%9"])
            data = json.loads((root / "submitted" / "wake_test.json").read_text())
            self.assertEqual(data["route_selection"]["outcome"], "relocated_pane")

    def test_session_aware_dispatch_fails_closed_on_ambiguous_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), thread_id="thread_abc")
            runner = FakeTmuxRunner(panes=[
                TmuxPane("%1", "Owning session", "/repo", 101, 202),
                TmuxPane("%9", "Owning session", "/repo", 101, 202),
            ])

            result = dispatch_firing_record(
                root, found, runner=runner, thread_identity_resolver=self.identity,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), ack_timeout_override=0,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(runner.pastes, [])
            data = json.loads((root / "failed" / "wake_test.json").read_text())
            self.assertEqual(data["route_selection"]["outcome"], "ambiguous_match")

    def test_foreign_reused_pane_falls_back_to_exact_app_server_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), thread_id="thread_abc")
            runner = FakeTmuxRunner(panes=[TmuxPane("%1", "Owning session", "/repo", 303, 404)])
            client = FakeAppServerClient()

            result = dispatch_firing_record(
                root, found, runner=runner, thread_identity_resolver=self.identity,
                app_server_client=client, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
            )

            self.assertEqual(result.status, "submitted")
            self.assertEqual(runner.pastes, [])
            self.assertIn(("turn", "thread_abc"), client.calls)
            data = json.loads((root / "submitted" / "wake_test.json").read_text())
            self.assertEqual(data["route_selection"]["outcome"], "app_server_fallback")
            self.assertNotIn("visibility_result", data)

    def test_app_server_fallback_requeues_active_writer_contention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), thread_id="thread_abc")
            client = FakeAppServerClient(status="active")

            result = dispatch_firing_record(
                root, found, runner=FakeTmuxRunner(panes=[]), thread_identity_resolver=self.identity,
                app_server_client=client, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
            )

            self.assertEqual(result.status, "requeued")
            data = json.loads((root / "pending" / "wake_test.json").read_text())
            self.assertEqual(data["route_selection"]["outcome"], "app_server_fallback")
            self.assertIn("active writer", data["last_error"])

    def test_no_matching_pane_or_valid_fallback_records_no_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), thread_id="thread_abc")
            client = FakeAppServerClient(fail=True)

            result = dispatch_firing_record(
                root, found, runner=FakeTmuxRunner(panes=[]), thread_identity_resolver=self.identity,
                app_server_client=client, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
            )

            self.assertEqual(result.status, "failed")
            data = json.loads((root / "failed" / "wake_test.json").read_text())
            self.assertEqual(data["route_selection"]["outcome"], "no_target")
            self.assertEqual(data["route_selection"]["attempted_route"], "app_server_fallback")

    def test_legacy_tmux_record_without_thread_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), thread_id=None)
            runner = FakeTmuxRunner()

            result = dispatch_firing_record(
                root,
                found,
                runner=runner,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                ack_timeout_override=0,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(runner.pastes, [])
            data = json.loads((root / "failed" / "wake_test.json").read_text())
            self.assertEqual(data["route_selection"]["outcome"], "no_target")
            self.assertIn("missing durable Codex thread identity", data["last_error"])

    def test_canonical_prompt_routes_to_owning_wake_root(self) -> None:
        root = Path("/tmp/a wake root")
        self.assertEqual(
            canonical_prompt("wake_123", root),
            "WAKE_TRIGGER_ID=wake_123\n"
            "WAKE_TRIGGER_ROOT=/tmp/a wake root\n"
            "Resume the scheduled wake task.\n",
        )

    def test_unsafe_pane_reason_rejects_shell_prompt_and_approval(self) -> None:
        self.assertEqual(unsafe_pane_reason("Approve command?"), "approval prompt visible")
        self.assertEqual(unsafe_pane_reason("user@host:~/repo$ "), "pane appears to be a shell prompt")
        self.assertIsNone(unsafe_pane_reason("Codex\nready for input"))

    def test_unsafe_pane_reason_ignores_approval_words_in_inert_history(self) -> None:
        self.assertIsNone(
            unsafe_pane_reason(
                "Completed configuration:\n"
                "--browser-chatgpt-tool-approval allow-once\n"
                "No approval prompt was shown.\n"
                "Codex\n"
                "ready for input"
            )
        )

    def test_unsafe_pane_reason_ignores_prompt_structure_outside_active_region(self) -> None:
        historical_prompt = "Approve command?\n"
        recent_idle_region = "\n".join(f"completed output {index}" for index in range(13))
        self.assertIsNone(unsafe_pane_reason(historical_prompt + recent_idle_region))

    def test_pane_lock_rejects_concurrent_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with PaneLock(root, "/tmp/tmux/default", "%1"):
                with self.assertRaises(ValueError):
                    with PaneLock(root, "/tmp/tmux/default", "%1"):
                        pass
            self.assertFalse((root / "locks" / f"{lock_name_for_pane('/tmp/tmux/default', '%1')}.lock").exists())

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
            self.assertEqual(runner.pastes[0][3], canonical_prompt("wake_test", root))
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
            self.assertEqual(data["attempts"], 0)
            self.assertEqual(data["safety_deferrals"], 1)
            self.assertEqual(data["events"][-2]["type"], "unsafe_pane")
            self.assertEqual(
                data["events"][-2]["pane_safety"],
                {
                    "active_region_line_limit": 12,
                    "active_region_start_offset": 0,
                    "inspected_line_count": 1,
                    "matched_line_offset": 0,
                    "region": "last_nonempty_lines",
                    "rule_id": "approval_question",
                    "total_nonempty_line_count": 1,
                },
            )
            self.assertNotIn("Approve command?", json.dumps(data["events"][-2]))

    def test_unsafe_preflight_does_not_consume_sole_delivery_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), max_attempts=1)
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
            self.assertEqual(data["attempts"], 0)
            self.assertEqual(data["max_attempts"], 1)
            self.assertEqual(data["safety_deferrals"], 1)
            self.assertEqual(data["max_safety_deferrals"], 3)
            self.assertNotIn("dispatch_attempt", [event["type"] for event in data["events"]])

    def test_persistent_unsafe_preflight_exhausts_separate_safety_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            found = self.make_firing_record(root, Path(tmp), max_attempts=1)
            runner = FakeTmuxRunner(capture="Approve command?")

            for index in range(3):
                result = dispatch_firing_record(
                    root,
                    found,
                    runner=runner,
                    now=datetime(2026, 5, 18, 21, 15 + index, tzinfo=UTC),
                    ack_timeout_override=0,
                )
                if index < 2:
                    self.assertEqual(result.status, "requeued")
                    found = find_record(root, "wake_test")
                    record = dict(found.record)
                    record["status"] = "firing"
                    replace_record(root, found, record)
                    found = find_record(root, "wake_test")

            self.assertEqual(result.status, "failed")
            self.assertEqual(runner.pastes, [])
            data = json.loads((root / "failed" / "wake_test.json").read_text())
            self.assertEqual(data["attempts"], 0)
            self.assertEqual(data["safety_deferrals"], 3)
            self.assertEqual(data["max_safety_deferrals"], 3)
            self.assertEqual(data["events"][-1]["message"], "Maximum pane safety deferrals reached")


if __name__ == "__main__":
    unittest.main()
