from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

from codex_wake.a2a_bus import BusStore
from codex_wake.a2a_identity import BusError, RuntimeIdentity
from codex_wake.a2a_mailbox import Mailbox
from codex_wake.a2a_receipt_signals import ReceiptSignalAdapter, ReceiptSignalRunner
from codex_wake.daemon import poll_once, default_signal_runners
from codex_wake.injector import dispatch_firing_record
from codex_wake.records import WakePath
from codex_wake.a2a_receipt_family import receipt_source_registration
from codex_wake.source_registry import BuiltinSourceRegistry
from codex_wake.event_wake import EventWake
from codex_wake.signals import Degraded, EvaluationLimits, Ingested, Matched, NotReady, Registration
from tests.test_signal_store import make_module
from tests.test_signals import make_intent


class ReceiptBridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.
        clock = patch("codex_wake.measurements.utc_bounds",
                      side_effect=lambda: (self.now, self.now))
        clock.start()
        self.addCleanup(clock.stop)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.bus, self.operator = BusStore.configure(self.root / 'bus')
        self.bus.enroll(self.repo, self.operator)
        self.identities = [RuntimeIdentity('fixture', name, str(self.repo)) for name in ('sender','recipient','foreign')]
        self.actors = []
        for identity in self.identities:
            cap, _ = self.bus.issue_actor(identity, self.repo, self.operator)
            self.actors.append(self.bus.authenticate(cap, identity, invoking_cwd=self.repo))
        Mailbox.migrate(self.bus, self.operator)
        self.mailbox = Mailbox(self.bus, clock=lambda: self.now, monotonic=lambda: self.now)
        self.identifier = self.mailbox.send(self.actors[0], self.identities[1], body='private fixture request',
                    idempotency_key='request', delivery='inbox')['message']['message_id']
        self.module = make_module(self.root / 'signals.sqlite')
        self.adapter = ReceiptSignalAdapter(self.mailbox, self.actors[0], self.identifier)

    def arm(self, condition='reply'):
        now = datetime.fromtimestamp(self.now, timezone.utc)
        wake = EventWake(self.module, adapters=[self.adapter], clock=lambda: now, id_factory=lambda: 'wake_receipt_fixture')
        result = wake.register(replace(make_intent(), when=self.adapter.request(condition)), idempotency_key='fixture-arm')
        self.assertIsInstance(result, Registration)
        # The engine exposes its durable arms for restored runner operation.
        return self.module.load_armed_signal(result.wake_id)

    def test_exact_reply_can_replay_and_match_without_body_or_notification(self):
        armed = self.arm()
        mirrored = self.adapter.mirror(self.module)
        self.assertIsInstance(mirrored, Ingested)
        now = datetime.fromtimestamp(self.now, timezone.utc)
        self.assertIsInstance(self.module.evaluate(armed.wake_id, armed, now, EvaluationLimits(max_candidates=100)), NotReady)
        self.mailbox.reply(self.actors[1], self.identifier, body='private fixture reply', idempotency_key='reply', delivery='inbox')
        self.assertIsInstance(self.adapter.mirror(self.module), Ingested)
        self.assertIsInstance(self.module.evaluate(armed.wake_id, armed, now, EvaluationLimits(max_candidates=100)), Matched)
        self.assertEqual(self.adapter.mirror(self.module)['status'], 'caught_up')
        with self.bus.connection() as database:
            self.assertEqual(database.execute('SELECT count(*) FROM mail_receipts').fetchone()[0], 2)
        self.assertNotIn(b'private fixture', (self.root / 'signals.sqlite').read_bytes())

    def test_receipt_before_arm_is_replayed_and_foreign_actor_refused(self):
        self.mailbox.read(self.actors[1], self.identifier)
        armed = self.arm('received')
        self.adapter.mirror(self.module)
        now = datetime.fromtimestamp(self.now, timezone.utc)
        self.assertIsInstance(self.module.evaluate(armed.wake_id, armed, now, EvaluationLimits(max_candidates=100)), Matched)
        with self.assertRaises(BusError): ReceiptSignalAdapter(self.mailbox, self.actors[2], self.identifier)

    def test_revocation_does_not_create_signal_evidence(self):
        self.arm()
        self.bus.revoke_actor(self.actors[0].actor_id, self.operator)
        self.assertIsInstance(self.adapter.mirror(self.module), Degraded)
        self.assertIsInstance(self.module.source_checkpoint('a2a.receipt', self.adapter.source_instance), type(None))

    def test_corrupt_signal_intent_is_refused_without_receipt_effect(self):
        self.arm()
        with self.bus.connection() as database:
            database.execute("UPDATE mail_outbox SET payload='{}' WHERE kind='receipt_signal'")
        self.assertIsInstance(self.adapter.mirror(self.module), Degraded)
        self.assertIsNone(self.module.source_checkpoint('a2a.receipt', self.adapter.source_instance))
        with self.bus.connection() as database:
            self.assertEqual(database.execute('SELECT count(*) FROM mail_receipts').fetchone()[0], 1)

    def test_interrupted_signal_commit_is_reconciled_by_original_checkpoint(self):
        self.arm()
        def crash(stage):
            if stage == 'after_ingest_commit':
                raise RuntimeError('fixture interrupted acknowledgement')
        interrupted = make_module(self.root / 'signals.sqlite', checkpoint=crash)
        self.assertIsInstance(self.adapter.mirror(interrupted), Degraded)
        self.assertEqual(self.adapter.mirror(self.module)['status'], 'caught_up')

    def test_restored_runner_publishes_once_without_notification_or_body(self):
        armed = self.arm()
        self.mailbox.reply(self.actors[1], self.identifier, body='private fixture reply',
                           idempotency_key='reply', delivery='inbox')
        restored_module = make_module(self.root / 'signals.sqlite')
        restored_arm = restored_module.load_armed_signal(armed.wake_id)
        restored = ReceiptSignalAdapter.restore(restored_arm, self.mailbox, self.actors[0])
        registry = BuiltinSourceRegistry((receipt_source_registration(
            lambda arm: (self.mailbox, self.actors[0])),))
        runners = default_signal_runners(self.root / 'wake', restored_module, source_registry=registry)
        self.assertEqual(len(runners), 1)
        now = datetime.fromtimestamp(self.now, timezone.utc)
        wake_root = self.root / 'wake'
        first = poll_once(wake_root, now, dispatch=False, signal_runtime=restored_module,
                          signal_runners=runners)
        self.assertEqual(first.fired, 1)
        self.assertEqual(first.dispatched, 0)
        second = poll_once(wake_root, now, dispatch=False, signal_runtime=restored_module,
                           signal_runners=runners)
        self.assertEqual(second.fired, 0)
        self.assertEqual(len(list((wake_root / 'firing').glob('*.json'))), 1)
        self.assertNotIn('private fixture', (wake_root / 'firing' / (armed.wake_id + '.json')).read_text())
        path = wake_root / 'firing' / (armed.wake_id + '.json')
        found = WakePath(path, json.loads(path.read_text()))
        held = dispatch_firing_record(wake_root, found,
                                      signal_authorizer=restored_module.authorize_firing_record)
        self.assertEqual(held.status, 'skipped')
        self.assertEqual(held.message, 'A2A receipt delivery is unqualified')
        self.assertTrue(path.exists())

    def test_revoked_cached_receipt_cannot_publish_with_or_without_runner(self):
        armed = self.arm()
        self.mailbox.reply(self.actors[1], self.identifier, body='private fixture reply',
                           idempotency_key='reply', delivery='inbox')
        self.adapter.mirror(self.module)
        runner = ReceiptSignalRunner(self.adapter, [armed])
        self.bus.revoke_actor(self.actors[0].actor_id, self.operator)
        now = datetime.fromtimestamp(self.now, timezone.utc)
        for runners in ((), (runner,)):
            result = poll_once(self.root / 'wake', now, dispatch=False,
                              signal_runtime=self.module, signal_runners=runners)
            self.assertEqual(result.fired, 0)
            self.assertEqual(result.pending, 1)
        self.assertFalse(list((self.root / 'wake' / 'firing').glob('*.json')))

    def test_restore_refuses_wrong_generation_and_mutated_descriptor(self):
        armed = self.arm()
        bad = replace(armed, anchor=replace(armed.anchor, baseline=dict(sequence=0, descriptor='{}')))
        with self.assertRaises(BusError):
            ReceiptSignalAdapter.restore(bad, self.mailbox, self.actors[0])
        cap, _ = self.bus.rotate_actor(self.actors[0].actor_id, self.operator)
        new_actor = self.bus.authenticate(cap, self.identities[0], invoking_cwd=self.repo)
        with self.assertRaises(BusError):
            ReceiptSignalAdapter.restore(armed, self.mailbox, new_actor)

    def test_reconstruction_failure_holds_cached_evidence_and_never_opens_arm_paths(self):
        armed = self.arm()
        self.mailbox.reply(self.actors[1], self.identifier, body='private fixture reply',
                           idempotency_key='reply', delivery='inbox')
        self.adapter.mirror(self.module)
        def denied(arm):
            raise BusError('authorization_denied', 'fixture configured authority unavailable')
        registry = BuiltinSourceRegistry((receipt_source_registration(denied),))
        runners = default_signal_runners(self.root / 'wake', self.module, source_registry=registry)
        result = poll_once(self.root / 'wake', datetime.fromtimestamp(self.now, timezone.utc),
                          dispatch=False, signal_runtime=self.module, signal_runners=runners)
        self.assertEqual(result.fired, 0)
        self.assertEqual(result.pending, 1)
