"""Configured observer authority over real temporary mailbox and wake journals."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest

from codex_wake.a2a_identity import BusError
from codex_wake.a2a_receipt_authority import ConfiguredReceiptAuthority
from codex_wake.daemon import poll_once
from codex_wake.signal_records import signal_journal_path, WakeRecordPublisher, current_reader_capability
from codex_wake.signal_store import SQLiteSignalModule
from codex_wake.signals import EvaluationLimits, Degraded
from tests import test_a2a_receipt_signals as fixture


class ConfiguredReceiptTests(unittest.TestCase):
    arm = fixture.ReceiptBridgeTests.arm

    def setUp(self):
        fixture.ReceiptBridgeTests.setUp(self)
        self.wake_root = self.root / 'wake'
        self.module = SQLiteSignalModule(signal_journal_path(self.wake_root),
            record_publisher=WakeRecordPublisher(self.wake_root, current_reader_capability(self.wake_root)))
        self.config = self.root / 'receipt-authority.json'
        self.grant = dict(source_instance=self.adapter.source_instance,
            bus_root=str(self.bus.root), bus_id=self.bus.bus_id,
            operator_capability=str(self.operator), actor=asdict(self.actors[0]),
            message_id=self.identifier)
        self.write_config()

    def write_config(self, grants=None):
        value = dict(schema_version=1, wake_root=str(self.wake_root),
                     grants=[self.grant] if grants is None else grants)
        self.config.write_text(json.dumps(value))
        self.config.chmod(0o600)

    def reply(self):
        self.mailbox.reply(self.actors[1], self.identifier, body='private fixture reply',
                           idempotency_key='reply', delivery='inbox')

    def test_executable_restore_requires_opt_in_and_does_not_dispatch_or_duplicate(self):
        armed = self.arm()
        self.reply()
        executable = os.environ.get('CODEX_WAKE_RECEIPT_DAEMON')
        # Explicit fixture time crosses the process seam, as in shared-refresh
        # acceptance; production receives no test clock flag or fallback.
        bootstrap = """import runpy, sys
from codex_wake import measurements
measurements.utc_bounds = lambda: (1000., 1000.)
executable = sys.argv.pop(1)
if executable:
    sys.argv[0] = executable
    runpy.run_path(executable, run_name='__main__')
else:
    from codex_wake.daemon import main
    raise SystemExit(main())
"""
        command = [sys.executable, '-c', bootstrap, executable or '']
        command += ['--once', '--no-dispatch', '--wake-root', str(self.wake_root)]
        before = self.mailbox_counts()
        def run(extra=()):
            result = subprocess.run(command + list(extra), text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('private fixture', result.stdout + result.stderr)
            return result
        run()
        self.assertTrue((self.wake_root / 'pending' / (armed.wake_id + '.json')).exists())
        extra = ['--a2a-receipt-authority', str(self.config)]
        run(extra)
        fired = self.wake_root / 'firing' / (armed.wake_id + '.json')
        self.assertTrue(fired.exists())
        original = fired.read_bytes()
        run(extra)
        self.assertEqual(fired.read_bytes(), original)
        self.assertEqual(len(list(fired.parent.glob('*.json'))), 1)
        self.assertNotIn(b'private fixture', original)
        self.assertEqual(self.mailbox_counts(), before)

    def mailbox_counts(self):
        with self.bus.connection() as database:
            return tuple(database.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                         for table in ('events', 'mail_receipts', 'mail_envelopes'))

    def test_config_revocation_fences_an_already_constructed_cached_runner(self):
        armed = self.arm()
        self.reply()
        authority = ConfiguredReceiptAuthority(self.config, self.wake_root)
        mailbox, actor = authority.resolve(armed)
        from codex_wake.a2a_receipt_signals import ReceiptSignalAdapter, ReceiptSignalRunner
        adapter = ReceiptSignalAdapter.restore(armed, mailbox, actor)
        runner = ReceiptSignalRunner(adapter, [armed])
        runner.reconcile(self.module, datetime.now(timezone.utc), EvaluationLimits(100))
        self.write_config([])
        result = runner.evaluate(self.module, armed, datetime.now(timezone.utc), EvaluationLimits(100))
        self.assertIsInstance(result, Degraded)
        self.assertFalse(list((self.wake_root / 'firing').glob('*.json')))

    def test_observer_transaction_cannot_write_or_act_as_recipient(self):
        armed = self.arm()
        mailbox, actor = ConfiguredReceiptAuthority(self.config, self.wake_root).resolve(armed)
        before = self.mailbox_counts()
        with mailbox.transaction(actor) as database:
            # Read-only authority must survive a callback toggling this pragma.
            database.execute('PRAGMA query_only=OFF')
            with self.assertRaises(sqlite3.OperationalError):
                database.execute("UPDATE meta SET value='true' WHERE key='paused'")
            database.execute('ROLLBACK')
        with self.assertRaises(BusError):
            with mailbox.transaction(actor, permission='receive'):
                self.fail('observer obtained recipient authority')
        self.assertEqual(self.mailbox_counts(), before)

    def test_rotation_fences_cached_observer_and_wrong_message_is_refused(self):
        armed = self.arm()
        self.reply()
        authority = ConfiguredReceiptAuthority(self.config, self.wake_root)
        wrong = replace(armed, spec=replace(armed.spec, subject='message:other'))
        with self.assertRaises(BusError):
            authority.resolve(wrong)
        mailbox, actor = authority.resolve(armed)
        from codex_wake.a2a_receipt_signals import ReceiptSignalAdapter, ReceiptSignalRunner
        runner = ReceiptSignalRunner(ReceiptSignalAdapter.restore(armed, mailbox, actor), [armed])
        runner.reconcile(self.module, datetime.now(timezone.utc), EvaluationLimits(100))
        self.bus.rotate_actor(actor.actor_id, self.operator)
        self.assertIsInstance(runner.evaluate(self.module, armed, datetime.now(timezone.utc),
                                            EvaluationLimits(100)), Degraded)

    def test_invalid_configuration_holds_cached_receipts_without_arm_path_discovery(self):
        armed = self.arm()
        self.reply()
        self.adapter.mirror(self.module)
        now = datetime.now(timezone.utc)
        invalid = [dict(self.grant, actor=dict(self.grant['actor'], generation=2)),
                   dict(self.grant, operator_capability=str(self.root / 'absent-capability')),
                   dict(self.grant, bus_root=str(self.root / 'absent-bus'))]
        for grant in invalid:
            with self.subTest(grant_keys=list(grant)):
                self.write_config([grant])
                result = poll_once(self.wake_root, now, dispatch=False, signal_runtime=self.module,
                                   receipt_authority_path=self.config)
                self.assertEqual(result.fired, 0)
                self.assertEqual(result.pending, 1)
        self.assertFalse((self.root / 'absent-bus').exists())
        self.assertFalse((self.root / 'absent-capability').exists())

    def test_private_config_bounds_root_pin_and_duplicate_members_are_enforced(self):
        armed = self.arm()
        authority = ConfiguredReceiptAuthority(self.config, self.wake_root)
        for raw in ('{}', 'x' * 65537,
                    '{"schema_version":1,"schema_version":1,"wake_root":"x","grants":[]}'):
            self.config.write_text(raw)
            with self.subTest(raw_size=len(raw)), self.assertRaises(BusError):
                authority.resolve(armed)
        self.write_config()
        self.config.chmod(0o644)
        with self.assertRaises(BusError):
            authority.resolve(armed)
        self.config.chmod(0o600)
        with self.assertRaises(BusError):
            ConfiguredReceiptAuthority(self.config, self.root / 'other-wake').resolve(armed)
        link = self.root / 'linked.json'
        link.symlink_to(self.config)
        with self.assertRaises(BusError):
            ConfiguredReceiptAuthority(link, self.wake_root).resolve(armed)
