"""Fresh command receipt arming, durable replay and honest no-dispatch state."""
import json
import os
import subprocess
import sys
import unittest
from tests import test_a2a_receipt_authority as fixture
from datetime import datetime, timezone


class ReceiptArmingTests(unittest.TestCase):
    def setUp(self):
        fixture.ConfiguredReceiptTests.setUp(self)
        self.now = datetime(2026, 9, 14, tzinfo=timezone.utc).timestamp()
        self.environment = dict(os.environ, XDG_STATE_HOME=str(self.root / 'state'))
        from codex_wake.monitor import write_monitor_health
        self.health = write_monitor_health(wake_root=self.wake_root, source='fixture-reader', mode='no-dispatch',
            state_dir=self.root / 'state' / 'codex-wake' / 'monitors')
    write_config = fixture.ConfiguredReceiptTests.write_config
    reply = fixture.ConfiguredReceiptTests.reply
    mailbox_counts = fixture.ConfiguredReceiptTests.mailbox_counts

    def child_command(self, executable, module):
        # Child UTC matches monitor-health metadata and the fixture's expiry
        # scenarios; no production clock flag or fallback is introduced.
        bootstrap = """import runpy, sys
from codex_wake import measurements
value = float(sys.argv.pop(1))
measurements.utc_bounds = lambda: (value, value)
executable, module = sys.argv.pop(1), sys.argv.pop(1)
if executable:
    sys.argv[0] = executable
    runpy.run_path(executable, run_name='__main__')
else:
    runpy.run_module(module, run_name='__main__', alter_sys=True)
"""
        return [sys.executable, '-c', bootstrap, str(self.now), executable or '', module]

    def command(self, *, key='arm-fixture', condition='reply', expires='2099-01-01T00:00:00+00:00'):
        executable = os.environ.get('CODEX_WAKE_RECEIPT_CLI')
        cmd = self.child_command(executable, 'codex_wake.cli')
        return subprocess.run(cmd + ['a2a', 'arm-receipt', '--wake-root', str(self.wake_root),
            '--receipt-authority', str(self.config), '--source-instance', self.adapter.source_instance,
            '--condition', condition, '--idempotency-key', key, '--expires-at', expires,
            '--prompt', 'Inspect receipt evidence.', '--tmux-pane', '%1',
            '--tmux-socket', '/tmp/fixture-tmux'], capture_output=True, text=True, timeout=10, env=self.environment)

    def daemon(self):
        executable = os.environ.get('CODEX_WAKE_RECEIPT_DAEMON')
        cmd = self.child_command(executable, 'codex_wake.daemon')
        result = subprocess.run(cmd + ['--once', '--no-dispatch', '--wake-root', str(self.wake_root),
            '--a2a-receipt-authority', str(self.config)], capture_output=True, text=True, timeout=10, env=self.environment)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_arm_is_idempotent_pending_then_one_durable_firing(self):
        before = self.mailbox_counts()
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertFalse(value['dispatch_qualified'])
        identifier = value['wake_id']
        self.assertEqual(json.loads(self.command().stdout)['wake_id'], identifier)
        conflict = self.command(condition='received')
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn('IDEMPOTENCY_CONFLICT', conflict.stdout)
        self.daemon()
        self.assertTrue((self.wake_root / 'pending' / (identifier + '.json')).exists())
        self.assertEqual(self.mailbox_counts(), before)
        self.reply()
        replied = self.mailbox_counts()
        self.daemon()
        fired = self.wake_root / 'firing' / (identifier + '.json')
        original = fired.read_bytes()
        self.daemon()
        self.assertEqual(fired.read_bytes(), original)
        self.assertEqual(self.mailbox_counts(), replied)
        self.assertNotIn(b'private fixture', original)
        self.assertNotIn('private fixture', result.stdout)

    def test_absent_grant_refuses_before_creating_wake_state(self):
        self.write_config([])
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list((self.wake_root / 'pending').glob('*.json')))
        self.assertNotIn(str(self.operator), result.stdout)

    def test_reader_advertisement_missing_or_wrong_root_refuses(self):
        before = self.mailbox_counts()
        self.health.unlink()
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('READER_CAPABILITY_UNAVAILABLE', result.stdout)
        from codex_wake.monitor import write_monitor_health
        write_monitor_health(wake_root=self.wake_root, source='fixture-reader', mode='no-dispatch',
            state_dir=self.health.parent, extra={'wake_root': str(self.root / 'other')})
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('READER_CAPABILITY_UNAVAILABLE', result.stdout)
        self.assertFalse(list((self.wake_root / 'pending').glob('*.json')))
        self.assertEqual(self.mailbox_counts(), before)

    def test_expired_arm_and_revoked_grant_do_not_fire(self):
        result = self.command(expires='2000-01-01T00:00:00+00:00')
        self.assertEqual(result.returncode, 0, result.stdout)
        identifier = json.loads(result.stdout)['wake_id']
        self.daemon()
        self.assertTrue((self.wake_root / 'expired' / (identifier + '.json')).exists())
        from codex_wake.monitor import write_monitor_health
        write_monitor_health(wake_root=self.wake_root, source='fixture-reader', mode='no-dispatch',
            state_dir=self.health.parent)
        result = self.command(key='other')
        self.assertEqual(result.returncode, 0, result.stdout)
        identifier = json.loads(result.stdout)['wake_id']
        self.reply()
        self.write_config([])
        self.daemon()
        self.assertTrue((self.wake_root / 'pending' / (identifier + '.json')).exists())
        self.assertFalse((self.wake_root / 'firing' / (identifier + '.json')).exists())
