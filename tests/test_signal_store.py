from __future__ import annotations

import tempfile
import threading
import unittest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from codex_wake.event_wake import EventWake
from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher
from codex_wake.signal_store import SQLiteSignalModule, SignalStoreError
from codex_wake.signals import (
    Degraded,
    Eq,
    EvaluationLimits,
    Ingested,
    Invalid,
    Matched,
    NormalizedObservation,
    Registration,
    Resume,
    ScriptedSourceAdapter,
    SignalRequest,
    SourceAnchor,
    SourceCommit,
    SourceContract,
    Verification,
    WakeIntent,
)
from tests.test_signals import make_adapter, make_intent


NOW = datetime(2026, 9, 14, 14, 0, tzinfo=UTC)


def make_module(database: Path, **kwargs) -> SQLiteSignalModule:
    wake_root = database.parent / "wake"
    publisher = WakeRecordPublisher(
        wake_root,
        ManagedReaderCapability(
            wake_root=wake_root,
            reader_id="test-managed-reader",
            generation=1,
            schema_versions=frozenset({1, 2}),
            active=True,
        ),
    )
    return SQLiteSignalModule(database, record_publisher=publisher, **kwargs)


def make_observation(value: str = "delivery-1") -> NormalizedObservation:
    return NormalizedObservation(
        source="memory",
        source_instance="contract-test",
        kind="job.completed",
        subject="job:42",
        occurrence_namespace="job-run",
        occurrence_value=value,
        occurred_at=NOW,
        observed_at=NOW,
        attributes={"result": "ready", "attempt": 1},
        verification=Verification("verified", "scripted"),
        evidence_ref=f"memory:evidence:{value}",
    )


class BlockingAdapter(ScriptedSourceAdapter):
    def __init__(self) -> None:
        super().__init__(
            make_adapter().contract(),
            anchor=SourceAnchor(0, "memory:0", {}, "local_journal"),
        )
        self.entered = threading.Event()
        self.release = threading.Event()

    def establish_anchor(self, spec, now):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("test did not release anchor")
        return super().establish_anchor(spec, now)


class RaisingOnceAdapter(ScriptedSourceAdapter):
    def __init__(self) -> None:
        super().__init__(
            make_adapter().contract(),
            anchor=SourceAnchor(0, "memory:0", {}, "local_journal"),
        )
        self._raise_once = True

    def establish_anchor(self, spec, now):
        if self._raise_once:
            self._raise_once = False
            self.anchor_calls += 1
            raise RuntimeError("provider-secret-must-not-escape")
        return super().establish_anchor(spec, now)


class SQLiteSignalModuleTests(unittest.TestCase):
    def setUp(self):
        clock = patch("codex_wake.measurements.utc_bounds",
                      return_value=(NOW.timestamp(), NOW.timestamp()))
        clock.start()
        self.addCleanup(clock.stop)

    def test_filesystem_baseline_filter_does_not_change_other_state_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            module = make_module(database)
            contract = SourceContract(
                "other",
                "state-test",
                frozenset({"thing.changed"}),
                frozenset({"thing:1"}),
                {"matched": bool, "baseline_fingerprint": str},
            )
            adapter = ScriptedSourceAdapter(
                contract,
                anchor=SourceAnchor(0, "other:a", {"fingerprint": "a"}, "state_recheck"),
            )
            intent = WakeIntent(
                SignalRequest(
                    1,
                    "other",
                    "state-test",
                    "state",
                    "thing.changed",
                    "thing:1",
                    "becomes",
                    (Eq("matched", True),),
                    "required",
                ),
                Resume("continue", Path(tmp), {"transport": "tmux"}),
            )
            registration = EventWake(
                module,
                adapters=(adapter,),
                clock=lambda: NOW,
                id_factory=lambda: "wake_other",
            ).register(intent, idempotency_key="other-state")
            armed = module.load_armed_signal(registration.wake_id)
            module.ingest(
                (
                    NormalizedObservation(
                        "other",
                        "state-test",
                        "thing.changed",
                        "thing:1",
                        "fixture",
                        "change-1",
                        NOW,
                        NOW,
                        {"matched": True, "baseline_fingerprint": "different"},
                        Verification("verified", "fixture"),
                    ),
                ),
                SourceCommit("other", "state-test", "checkpoint-1", 1, NOW),
            )

            result = module.evaluate(
                registration.wake_id, armed, NOW, EvaluationLimits(10)
            )

            self.assertEqual(result.outcome, "matched")

    def test_reserved_match_survives_expiry_for_delivery_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            module = make_module(database)
            intent = replace(make_intent(), expires_at=NOW + timedelta(seconds=1))
            registration = EventWake(
                module,
                adapters=[make_adapter()],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            ).register(intent, idempotency_key="job-42")
            module.ingest(
                [make_observation()],
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )
            armed = module.load_armed_signal(registration.wake_id)
            reserved = module.evaluate(
                registration.wake_id, armed, NOW, EvaluationLimits(10)
            )

            reopened = make_module(database)
            replay = reopened.evaluate(
                registration.wake_id,
                armed,
                NOW + timedelta(seconds=2),
                EvaluationLimits(10),
            )

            self.assertIsInstance(reserved, Matched)
            self.assertEqual(replay, reserved)
            self.assertFalse(reopened.expire_unreserved(registration.wake_id, now=NOW + timedelta(seconds=2)))

    def test_missing_qualified_utc_holds_new_journal_but_existing_inspection_is_untimed(self):
        from codex_wake.measurements import TimeUnavailable
        with tempfile.TemporaryDirectory() as tmp:
            database=Path(tmp)/'signals.sqlite3'
            with patch('codex_wake.measurements.utc_bounds',side_effect=TimeUnavailable('unqualified')):
                with self.assertRaises(SignalStoreError):SQLiteSignalModule(database)
            initialized=SQLiteSignalModule(database,lease_clock=lambda:NOW)
            original=initialized.journal_status()
            with patch('codex_wake.measurements.utc_bounds',side_effect=TimeUnavailable('unqualified')):
                reopened=SQLiteSignalModule.open_existing(database)
                self.assertEqual(reopened.journal_status().journal_uuid,original.journal_uuid)
                self.assertEqual(reopened.journal_status().schema_version,2)

    def test_existing_only_open_never_creates_a_missing_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"

            self.assertIsNone(SQLiteSignalModule.open_existing(database))
            self.assertFalse(database.exists())
            SQLiteSignalModule(database)

            reopened = SQLiteSignalModule.open_existing(database)
            self.assertIsNotNone(reopened)
            self.assertEqual(reopened.journal_status().schema_version, 2)

    def test_journal_reports_versioned_full_wal_posture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = SQLiteSignalModule(Path(tmp) / "signals.sqlite3").journal_status()

            self.assertEqual(status.schema_version, 2)
            self.assertTrue(status.journal_uuid)
            self.assertEqual(status.journal_mode, "wal")
            self.assertEqual(status.synchronous, 2)
            self.assertTrue(status.foreign_keys)

    def test_newer_journal_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            SQLiteSignalModule(database)
            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA user_version = 3")

            with self.assertRaisesRegex(SignalStoreError, "newer"):
                SQLiteSignalModule(database)

    def test_nonempty_unowned_and_foreign_application_databases_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unowned = Path(tmp) / "unowned.sqlite3"
            with sqlite3.connect(unowned) as connection:
                connection.execute("CREATE TABLE unrelated(value TEXT)")
            with self.assertRaisesRegex(SignalStoreError, "nonempty"):
                SQLiteSignalModule(unowned)

            foreign = Path(tmp) / "foreign.sqlite3"
            with sqlite3.connect(foreign) as connection:
                connection.execute("PRAGMA application_id = 12345")
            with self.assertRaisesRegex(SignalStoreError, "application id"):
                SQLiteSignalModule(foreign)

    def test_anchor_exception_is_sanitized_and_same_identity_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            adapter = RaisingOnceAdapter()
            facade = EventWake(
                make_module(database),
                adapters=[adapter],
                clock=lambda: NOW,
                id_factory=iter(("wake_1", "wake_2")).__next__,
            )

            first = facade.register(make_intent(), idempotency_key="job-42")
            retry = facade.register(make_intent(), idempotency_key="job-42")

            self.assertIsInstance(first, Degraded)
            self.assertEqual(first.code, "SOURCE_UNAVAILABLE")
            self.assertNotIn("provider-secret", repr(first))
            self.assertIsInstance(retry, Registration)
            self.assertEqual(retry.wake_id, "wake_1")

    def test_preparation_release_failure_does_not_escape_public_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            module = make_module(Path(tmp) / "signals.sqlite3")
            facade = EventWake(
                module,
                adapters=[RaisingOnceAdapter()],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )

            with patch.object(
                module,
                "_release_preparation",
                side_effect=sqlite3.OperationalError("storage-secret-must-not-escape"),
            ):
                result = facade.register(make_intent(), idempotency_key="job-42")

            self.assertIsInstance(result, Degraded)
            self.assertNotIn("storage-secret", repr(result))

    def test_unqualified_default_clock_holds_ingest_and_republication_without_guest_fallback(self):
        from codex_wake.measurements import TimeUnavailable
        with tempfile.TemporaryDirectory() as tmp,patch('codex_wake.measurements.utc_bounds',return_value=(NOW.timestamp(),NOW.timestamp())):
            database=Path(tmp)/'signals.sqlite3'
            crashed=[False]
            def checkpoint(name):
                if name=='after_prepared_commit' and not crashed[0]:
                    crashed[0]=True
                    raise RuntimeError('interrupted before publication')
            module=make_module(database,checkpoint=checkpoint)
            facade=EventWake(module,adapters=[make_adapter()],clock=lambda:NOW,id_factory=lambda:'wake_clock_held')
            prepared=facade.register(make_intent(),idempotency_key='clock-held-publication')
            self.assertIsInstance(prepared,Degraded)
            record=database.parent/'wake'/'pending'/'wake_clock_held.json'
            self.assertFalse(record.exists())
            with patch('codex_wake.measurements.utc_bounds',side_effect=TimeUnavailable('unqualified')):
                self.assertEqual(module.reconcile_publications(),0)
                self.assertFalse(record.exists())
                outcome=module.ingest([make_observation()],SourceCommit('memory','contract-test','c1',1,NOW))
                self.assertIsInstance(outcome,Degraded)
                self.assertIsNone(module.source_checkpoint('memory','contract-test'))
            self.assertEqual(module.reconcile_publications(),1)
            self.assertTrue(record.exists())

    def test_expired_preparation_never_calls_the_source_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[0]
            def clock():
                calls[0]+=1
                return NOW if calls[0]<=2 else NOW+timedelta(seconds=31)
            adapter=make_adapter()
            module=make_module(Path(tmp)/'signals.sqlite3',lease_clock=clock)
            result=EventWake(module,adapters=[adapter],clock=lambda:NOW,
                id_factory=lambda:'wake_expired_before_source').register(make_intent(),idempotency_key='expired-before-source')
            self.assertIsInstance(result,Degraded)
            self.assertEqual(result.code,'SOURCE_LEASE_LOST')
            self.assertEqual(adapter.anchor_calls,0)

    def test_qualified_bounds_never_steal_or_continue_an_ambiguous_preparation_lease(self):
        bounds=[NOW.timestamp(),(NOW+timedelta(seconds=20)).timestamp()]
        with tempfile.TemporaryDirectory() as tmp,patch('codex_wake.measurements.utc_bounds',side_effect=lambda:tuple(bounds)):
            database=Path(tmp)/'signals.sqlite3'
            blocked=BlockingAdapter()
            facade=EventWake(make_module(database),adapters=[blocked],clock=lambda:NOW,id_factory=lambda:'wake_original')
            with ThreadPoolExecutor(max_workers=2) as pool:
                preparing=pool.submit(facade.register,make_intent(),idempotency_key='qualified-lease')
                try:
                    self.assertTrue(blocked.entered.wait(timeout=5))
                    bounds[:]=[(NOW+timedelta(seconds=10)).timestamp(),(NOW+timedelta(seconds=40)).timestamp()]
                    denied_adapter=make_adapter()
                    uncertain=EventWake(make_module(database),adapters=[denied_adapter],clock=lambda:NOW,
                        id_factory=lambda:'wake_not_rebased').register(make_intent(),idempotency_key='qualified-lease')
                    self.assertIsInstance(uncertain,Degraded)
                    self.assertEqual(uncertain.code,'REGISTRATION_IN_PROGRESS')
                    self.assertEqual(denied_adapter.anchor_calls,0)
                finally:blocked.release.set()
                late=preparing.result(timeout=5)
            self.assertIsInstance(late,Degraded)
            self.assertEqual(late.code,'SOURCE_LEASE_LOST')
            bounds[:]=[(NOW+timedelta(seconds=31)).timestamp(),(NOW+timedelta(seconds=32)).timestamp()]
            recovered=EventWake(make_module(database),adapters=[make_adapter()],clock=lambda:NOW,
                id_factory=lambda:'wake_new_candidate').register(make_intent(),idempotency_key='qualified-lease')
            self.assertIsInstance(recovered,Registration)
            self.assertEqual(recovered.wake_id,'wake_original')

    def test_stale_preparation_is_taken_over_with_same_reserved_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            lease_now = [NOW]
            blocked_adapter = BlockingAdapter()
            interrupted = EventWake(
                make_module(database, lease_clock=lambda: lease_now[0]),
                adapters=[blocked_adapter],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                abandoned = pool.submit(
                    interrupted.register,
                    make_intent(),
                    idempotency_key="job-42",
                )
                self.assertTrue(blocked_adapter.entered.wait(timeout=5))
                lease_now[0] = NOW + timedelta(seconds=31)
                retry_adapter = make_adapter()
                recovered = EventWake(
                    make_module(database, lease_clock=lambda: lease_now[0]),
                    adapters=[retry_adapter],
                    clock=lambda: lease_now[0],
                    id_factory=lambda: "wake_2",
                ).register(make_intent(), idempotency_key="job-42")
                blocked_adapter.release.set()
                fenced = abandoned.result(timeout=5)

            replay_adapter = make_adapter()
            replay = EventWake(
                make_module(database, lease_clock=lambda: lease_now[0]),
                adapters=[replay_adapter],
                clock=lambda: lease_now[0],
                id_factory=lambda: "wake_3",
            ).register(make_intent(), idempotency_key="job-42")

            self.assertIsInstance(recovered, Registration)
            self.assertEqual(recovered.wake_id, "wake_1")
            self.assertEqual(replay, recovered)
            self.assertIsInstance(fenced, Degraded)
            self.assertEqual(fenced.code, "SOURCE_LEASE_LOST")
            self.assertEqual(retry_adapter.anchor_calls, 1)
            self.assertEqual(replay_adapter.anchor_calls, 0)

    def test_store_failures_are_closed_and_sanitized_at_public_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            module = make_module(database)
            facade = EventWake(
                module,
                adapters=[make_adapter()],
                clock=lambda: NOW,
                id_factory=iter(("wake_1", "wake_2")).__next__,
            )
            registration = facade.register(make_intent(), idempotency_key="first")
            armed = module.load_armed_signal(registration.wake_id)

            with patch.object(
                module,
                "_connect",
                side_effect=sqlite3.OperationalError("database-secret-must-not-escape"),
            ):
                outcomes = (
                    facade.register(make_intent(), idempotency_key="second"),
                    module.ingest(
                        [make_observation()],
                        SourceCommit("memory", "contract-test", "c1", 1, NOW),
                    ),
                    module.evaluate(
                        registration.wake_id,
                        armed,
                        NOW,
                        EvaluationLimits(10),
                    ),
                    module.journal_status(),
                    module.retention_pins(),
                    module.release_retention_pins(
                        registration.wake_id,
                        reasons=frozenset({"active_anchor"}),
                        released_at=NOW,
                    ),
                    module.compact_receipts(
                        through_sequence=1,
                        limit=1,
                        now=NOW,
                    ),
                )
                missing = module.load_armed_signal(registration.wake_id)

            for outcome in outcomes:
                self.assertIsInstance(outcome, Degraded)
                self.assertEqual(outcome.code, "STORE_UNAVAILABLE")
                self.assertNotIn("database-secret", repr(outcome))
            self.assertIsNone(missing)

    def test_initialization_storage_failure_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "codex_wake.signal_store.sqlite3.connect",
                side_effect=sqlite3.OperationalError("database-secret-must-not-escape"),
            ):
                with self.assertRaises(SignalStoreError) as captured:
                    SQLiteSignalModule(Path(tmp) / "signals.sqlite3")

            self.assertEqual(str(captured.exception), "signal journal initialization failed")

            with patch.object(
                Path,
                "mkdir",
                side_effect=OSError("path-secret-must-not-escape"),
            ):
                with self.assertRaises(SignalStoreError) as path_failure:
                    SQLiteSignalModule(Path(tmp) / "blocked" / "signals.sqlite3")

            self.assertEqual(str(path_failure.exception), "signal journal initialization failed")

    def test_registration_ingest_and_match_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            adapter = make_adapter()
            first_module = make_module(database)
            first_facade = EventWake(
                first_module,
                adapters=[adapter],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )
            registration = first_facade.register(make_intent(), idempotency_key="job-42")
            self.assertIsInstance(registration, Registration)
            ingested = first_module.ingest(
                [make_observation()],
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )
            armed = first_module.load_armed_signal(registration.wake_id)
            self.assertIsNotNone(armed)
            first_match = first_module.evaluate(
                registration.wake_id,
                armed,
                NOW,
                EvaluationLimits(10),
            )
            self.assertIsInstance(first_match, Matched)

            replay_adapter = make_adapter()
            reopened = make_module(database)
            replay_facade = EventWake(
                reopened,
                adapters=[replay_adapter],
                clock=lambda: NOW,
                id_factory=lambda: "wake_unused",
            )
            replay_registration = replay_facade.register(
                make_intent(), idempotency_key="job-42"
            )
            reopened_arm = reopened.load_armed_signal(registration.wake_id)
            self.assertEqual(replay_registration, registration)
            self.assertEqual(replay_adapter.anchor_calls, 0)
            self.assertEqual(
                reopened.evaluate(
                    registration.wake_id,
                    reopened_arm,
                    NOW,
                    EvaluationLimits(10),
                ),
                first_match,
            )
            self.assertEqual(len(ingested.receipts), 1)

    def test_conflicting_batch_rolls_back_receipts_sequence_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            module = make_module(database)
            facade = EventWake(
                module,
                adapters=[make_adapter()],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )
            self.assertIsInstance(
                facade.register(make_intent(), idempotency_key="job-42"),
                Registration,
            )
            original = make_observation("original")
            first = module.ingest(
                [original],
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )
            conflicting = replace(
                make_observation("original"),
                attributes={"result": "failed", "attempt": 1},
            )
            rejected = module.ingest(
                [make_observation("new"), conflicting],
                SourceCommit("memory", "contract-test", "checkpoint-3", 3, NOW),
            )

            reopened = make_module(database)
            accepted = reopened.ingest(
                [make_observation("new")],
                SourceCommit("memory", "contract-test", "checkpoint-2", 2, NOW),
            )
            duplicate = reopened.ingest(
                [make_observation("new")],
                SourceCommit("memory", "contract-test", "checkpoint-2", 2, NOW),
            )
            regression = reopened.ingest(
                [original],
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )

            self.assertIsInstance(first, Ingested)
            self.assertIsInstance(rejected, Invalid)
            self.assertEqual(rejected.code, "OCCURRENCE_IDENTITY_CONFLICT")
            self.assertIsInstance(accepted, Ingested)
            self.assertEqual(accepted.receipts[0].local_sequence, 2)
            self.assertFalse(accepted.receipts[0].duplicate)
            self.assertTrue(duplicate.receipts[0].duplicate)
            self.assertEqual(duplicate.receipts[0].receipt_id, accepted.receipts[0].receipt_id)
            self.assertIsInstance(regression, Invalid)
            self.assertEqual(regression.code, "CHECKPOINT_REGRESSION")

    def test_concurrent_same_key_registration_has_one_anchor_and_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            adapter = BlockingAdapter()
            first = EventWake(
                make_module(database),
                adapters=[adapter],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )
            second = EventWake(
                make_module(database),
                adapters=[adapter],
                clock=lambda: NOW,
                id_factory=lambda: "wake_2",
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = pool.submit(first.register, make_intent(), idempotency_key="job-42")
                self.assertTrue(adapter.entered.wait(timeout=5))
                concurrent = second.register(make_intent(), idempotency_key="job-42")
                adapter.release.set()
                accepted = pending.result(timeout=5)

            self.assertIsInstance(accepted, Registration)
            self.assertIsInstance(concurrent, Degraded)
            self.assertEqual(concurrent.code, "REGISTRATION_IN_PROGRESS")
            self.assertEqual(concurrent.wake_id, accepted.wake_id)
            self.assertEqual(adapter.anchor_calls, 1)
            replay = second.register(make_intent(), idempotency_key="job-42")
            self.assertEqual(replay, accepted)

    def test_anchor_fences_ingest_independently_of_provider_observed_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            adapter = BlockingAdapter()
            registering_module = make_module(
                database, lease_clock=lambda: NOW
            )
            registering = EventWake(
                registering_module,
                adapters=[adapter],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )
            ingesting = make_module(database, lease_clock=lambda: NOW)
            commit = SourceCommit(
                "memory",
                "contract-test",
                "checkpoint-1",
                1,
                NOW + timedelta(days=365),
            )

            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = pool.submit(
                    registering.register,
                    make_intent(),
                    idempotency_key="job-42",
                )
                self.assertTrue(adapter.entered.wait(timeout=5))
                fenced = ingesting.ingest([make_observation()], commit)
                adapter.release.set()
                registration = pending.result(timeout=5)

            accepted = ingesting.ingest([make_observation()], commit)
            self.assertIsInstance(fenced, Degraded)
            self.assertEqual(fenced.code, "SOURCE_BUSY")
            self.assertIsInstance(registration, Registration)
            self.assertIsInstance(accepted, Ingested)

    def test_concurrent_evaluators_return_one_durable_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            first = make_module(database)
            facade = EventWake(
                first,
                adapters=[make_adapter()],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )
            registration = facade.register(make_intent(), idempotency_key="job-42")
            self.assertIsInstance(registration, Registration)
            first.ingest(
                [make_observation()],
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )
            armed = first.load_armed_signal(registration.wake_id)
            self.assertIsNotNone(armed)
            second = make_module(database)

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        module.evaluate,
                        registration.wake_id,
                        armed,
                        NOW,
                        EvaluationLimits(10),
                    )
                    for module in (first, second)
                ]
                results = [future.result(timeout=5) for future in futures]

            self.assertIsInstance(results[0], Matched)
            self.assertEqual(results[0], results[1])

    def test_reservation_replay_still_requires_a_durable_published_arm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            module = make_module(database)
            registration = EventWake(
                module,
                adapters=[make_adapter()],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            ).register(make_intent(), idempotency_key="job-42")
            module.ingest(
                [make_observation()],
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )
            armed = module.load_armed_signal(registration.wake_id)
            first = module.evaluate(
                registration.wake_id,
                armed,
                NOW,
                EvaluationLimits(10),
            )
            self.assertIsInstance(first, Matched)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE arms SET state = 'prepared' WHERE wake_id = ?",
                    (registration.wake_id,),
                )

            replay = module.evaluate(
                registration.wake_id,
                armed,
                NOW,
                EvaluationLimits(10),
            )

            self.assertIsInstance(replay, Degraded)
            self.assertEqual(replay.code, "ARM_NOT_PUBLISHED")

    def test_bounded_evaluation_progress_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            module = make_module(database)
            facade = EventWake(
                module,
                adapters=[make_adapter()],
                clock=lambda: NOW,
                id_factory=lambda: "wake_1",
            )
            registration = facade.register(make_intent(), idempotency_key="job-42")
            self.assertIsInstance(registration, Registration)
            observations = [
                replace(make_observation("first"), attributes={"result": "waiting", "attempt": 1}),
                replace(make_observation("second"), attributes={"result": "waiting", "attempt": 2}),
                replace(make_observation("third"), attributes={"result": "ready", "attempt": 3}),
            ]
            module.ingest(
                observations,
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )
            armed = module.load_armed_signal(registration.wake_id)

            first = module.evaluate(registration.wake_id, armed, NOW, EvaluationLimits(1))
            second_module = make_module(database)
            second = second_module.evaluate(registration.wake_id, armed, NOW, EvaluationLimits(1))
            third_module = make_module(database)
            third = third_module.evaluate(registration.wake_id, armed, NOW, EvaluationLimits(1))

            self.assertIsInstance(first, Degraded)
            self.assertEqual(first.code, "EVALUATION_BUDGET_EXHAUSTED")
            self.assertIsInstance(second, Degraded)
            self.assertEqual(second.code, "EVALUATION_BUDGET_EXHAUSTED")
            self.assertIsInstance(third, Matched)
            self.assertEqual(third.receipt.local_sequence, 3)

    def test_retention_pins_survive_reopen_and_bound_compaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "signals.sqlite3"
            module = make_module(database)
            ids = iter(("wake_pending", "wake_match"))
            facade = EventWake(
                module,
                adapters=[make_adapter()],
                clock=lambda: NOW,
                id_factory=lambda: next(ids),
            )
            pending_registration = facade.register(
                make_intent(result="waiting"),
                idempotency_key="pending",
            )
            match_registration = facade.register(
                make_intent(result="ready"),
                idempotency_key="match",
            )
            pending_observation = replace(
                make_observation("pending"),
                attributes={"result": "waiting", "attempt": 1},
                verification=Verification("pending", "scripted"),
            )
            module.ingest(
                [pending_observation, make_observation("matched")],
                SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
            )
            pending_arm = module.load_armed_signal(pending_registration.wake_id)
            match_arm = module.load_armed_signal(match_registration.wake_id)
            pending = module.evaluate(
                pending_registration.wake_id,
                pending_arm,
                NOW,
                EvaluationLimits(10),
            )
            matched = module.evaluate(
                match_registration.wake_id,
                match_arm,
                NOW,
                EvaluationLimits(10),
            )
            self.assertIsInstance(pending, Degraded)
            self.assertEqual(pending.code, "VERIFICATION_PENDING")
            self.assertIsInstance(matched, Matched)

            reopened = make_module(database)
            pins = reopened.retention_pins()
            self.assertEqual(
                {pin.reason for pin in pins},
                {"active_anchor", "verification_pending", "match_evidence"},
            )
            blocked = reopened.compact_receipts(
                through_sequence=2,
                limit=10,
                now=NOW,
            )
            self.assertEqual((blocked.deleted, blocked.retained), (0, 2))

            reopened.release_retention_pins(
                pending_registration.wake_id,
                reasons=frozenset({"active_anchor", "verification_pending"}),
                released_at=NOW,
            )
            reopened.release_retention_pins(
                match_registration.wake_id,
                reasons=frozenset({"active_anchor"}),
                released_at=NOW,
            )
            partial = reopened.compact_receipts(
                through_sequence=2,
                limit=10,
                now=NOW,
            )
            self.assertEqual((partial.deleted, partial.retained), (1, 1))

            reopened.release_retention_pins(
                match_registration.wake_id,
                reasons=frozenset({"match_evidence"}),
                released_at=NOW,
            )
            final = reopened.compact_receipts(
                through_sequence=2,
                limit=10,
                now=NOW,
            )
            self.assertEqual((final.deleted, final.retained), (1, 0))


if __name__ == "__main__":
    unittest.main()
