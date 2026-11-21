"""Native event waiting is indefinite; delivery remains bounded after match."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.daemon import poll_once
from codex_wake.records import all_records

THREAD = '11111111-1111-4111-8111-111111111111'
NOW = 1900000000


def clock(at):
    return {'utc': {'status': 'network', 'sources': ['synthetic-a', 'synthetic-b'],
                    'lower': at, 'upper': at}, 'counter': None}


class NativeEventWaitTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict('os.environ', {'CODEX_WAKE_STABLE_TIME_CONFIG': ''})
        environment.start()
        self.addCleanup(environment.stop)

    def test_public_file_can_wait_past_old_expiry_then_starts_one_delivery_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root, event = Path(directory) / 'wake', Path(directory) / 'owner-response'
            args = ['--wake-root', str(root), 'native', 'file', '--json', '--codex-path',
                    sys.executable, '--ttl', '1m', '--observation-policy',
                    'until_event_or_cancel', '--idempotency-key', 'original-owner-event',
                    THREAD, str(event), '--', 'Inspect original response; no grant implied']
            output = io.StringIO()
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW)), contextlib.redirect_stdout(output):
                run(args)
            receipt = json.loads(output.getvalue())
            later = NOW + 36 * 3600
            with patch('codex_wake.native_clock.snapshot', return_value=clock(later)):
                poll_once(root, dispatch=False)
            record = all_records(root)[0].record
            self.assertEqual(record['status'], 'pending')
            self.assertEqual(receipt['observation_policy'], 'until_event_or_cancel')
            self.assertEqual(receipt['observation_state'], 'waiting')
            self.assertIsNone(receipt['expires_at'])
            self.assertEqual(record['time_recovery']['reason'], 'awaiting_event')
            event.write_text('synthetic response received; not a grant')
            with patch('codex_wake.native_clock.snapshot', return_value=clock(later)):
                poll_once(root, dispatch=False)
            matched = all_records(root)[0].record
            self.assertEqual(matched['status'], 'firing')
            original_match = matched['scheduling_intent']['event_match']
            event.unlink()  # An observed one-shot event survives later removal.
            output = io.StringIO()
            with patch('codex_wake.native_clock.snapshot', return_value=clock(later + 10)), contextlib.redirect_stdout(output):
                run(args)
            recovered = json.loads(output.getvalue())
            self.assertEqual(recovered['id'], receipt['id'])
            self.assertEqual(recovered['observation_state'], 'matched')
            self.assertEqual(all_records(root)[0].record['scheduling_intent']['event_match'], original_match)
            from codex_wake.native_intents import dispatch_gate
            self.assertEqual(dispatch_gate(all_records(root)[0].record, clock(later + 61))['reason'], 'expiry_reached')
            self.assertEqual(len(all_records(root)), 1)

    def test_finite_default_compatibility_and_cancelled_unresolved_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root, event = Path(directory) / 'wake', Path(directory) / 'owner-response'
            common = ['--wake-root', str(root), 'native', 'file', '--json', '--codex-path', sys.executable, '--ttl', '1m']
            tail = [THREAD, str(event), '--', 'Inspect original']
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW)), contextlib.redirect_stdout(io.StringIO()):
                run([*common, '--idempotency-key', 'finite', *tail])
                run([*common, '--idempotency-key', 'finite', '--observation-policy', 'registration_window', *tail])
                run([*common, '--idempotency-key', 'until', '--observation-policy', 'until_event_or_cancel', *tail])
            records = {r.record['scheduling_intent']['idempotency_key']: r.record for r in all_records(root)}
            self.assertEqual(len(records), 2)
            self.assertEqual(records['finite']['intent_schema_version'], 6)
            self.assertEqual(records['until']['intent_schema_version'], 9)
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW + 2 * 86400)):
                poll_once(root, dispatch=False)
            states = {r.record['scheduling_intent']['idempotency_key']: r.record['status'] for r in all_records(root)}
            self.assertEqual(states, {'finite': 'failed', 'until': 'pending'})
            from codex_wake.wake_control import delivery_guard
            output = io.StringIO()
            with delivery_guard(root), contextlib.redirect_stdout(output):
                run(['--wake-root', str(root), 'cancel', records['until']['id'], '--json'])
            self.assertEqual(json.loads(output.getvalue())['roots'][0]['results'][0]['state'], 'pending')
            event.write_text('synthetic owner event')
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW + 3 * 86400)):
                poll_once(root, dispatch=False)
            cancelled = next(r.record for r in all_records(root) if r.record['id'] == records['until']['id'])
            self.assertEqual(cancelled['status'], 'cancelled')
            self.assertNotIn('event_match', cancelled['scheduling_intent'])

    def test_public_mcp_capability_gate_and_exact_caller(self):
        from codex_wake.mcp_server import CommandRunner, SPECS
        from codex_wake.monitor import write_monitor_health
        from codex_wake.records import schema_summary
        from codex_wake.signal_records import ManagedReaderCapability
        self.assertIn('observation_policy', SPECS['wake_native_file'][3])
        self.assertNotIn('observation_policy', SPECS['wake_native_after'][3])
        self.assertIn('native_file_until_event_v1', schema_summary()['capabilities'])
        meta = dict(threadId=THREAD, sessionId=THREAD, callId='synthetic-call',
                    **{'x-codex-turn-metadata': dict(thread_id=THREAD, session_id=THREAD, turn_id='synthetic-turn')})
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'XDG_STATE_HOME': directory}):
            root = Path(directory) / 'wake'
            runner = CommandRunner(wake_root=root)
            body = dict(caller_thread_id=THREAD, trigger=str(Path(directory) / 'event'), ttl='1m',
                        prompt='Inspect original request', idempotency_key='mcp-until-event',
                        session_mode='reopen_live', wake_lifetime='persistent', observation_policy='until_event_or_cancel')
            value, failed = runner.call('wake_native_file', body, native_context=None)
            self.assertTrue(failed)
            self.assertEqual(all_records(root), [])
            with patch('codex_wake.sessions.observe', return_value={'complete': False, 'sessions': []}), patch(
                    'codex_wake.app_server.resolve_codex_cmd', return_value=sys.executable), patch(
                    'codex_wake.native_clock.snapshot', return_value=clock(NOW)), patch(
                    'codex_wake.wake_mode_runtime.registration_harness_readiness', return_value={'state': 'ready', 'reason': 'exact_native_read_verified'}), patch(
                    'codex_wake.measurements.utc_bounds', return_value=(NOW, NOW)):
                write_monitor_health(wake_root=root, source='synthetic-fixture', mode='loop')
                # A reader advertising old capabilities must not claim this new policy.
                fake_reader = ManagedReaderCapability(root, 'fixture', 1, frozenset({8, 9}), True)
                with patch('codex_wake.signal_records.probe_managed_reader_capability', return_value=fake_reader), patch(
                        'codex_wake.monitor.read_monitor_health', return_value={'mode': 'loop', 'reader_capabilities': ['wake_session_modes_v1']}):
                    held, failed = runner.call('wake_native_file', body, native_context=meta)
                self.assertFalse(failed, held)
                self.assertFalse(held['armed'])
                self.assertIn('native_file_until_event_v1', held['requires_worker_capabilities'])
                ready, failed = runner.call('wake_native_file', body, native_context=meta)
                self.assertFalse(failed, ready)
                self.assertTrue(ready['armed'])
                self.assertEqual(ready['harness']['state'], 'ready')
                self.assertEqual(ready['id'], held['id'])
                self.assertEqual(ready['observation_policy'], 'until_event_or_cancel')
                self.assertEqual(ready['observation_state'], 'waiting')
                self.assertIsNone(ready['expires_at'])
                Path(body['trigger']).write_text('synthetic owner response')
                with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW + 36 * 3600)):
                    poll_once(root, dispatch=False)
                with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW + 36 * 3600 + 61)):
                    elapsed, failed = runner.call('wake_native_file', body, native_context=meta)
                self.assertFalse(failed, elapsed)
                self.assertFalse(elapsed['armed'], 'an elapsed post-match window cannot be reported armed')
                self.assertEqual(elapsed['time_recovery']['reason'], 'expiry_reached')

    def test_explicit_stop_remains_effective_before_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root, event = Path(directory) / 'wake', Path(directory) / 'event'
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW)), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'file', '--json', '--codex-path', sys.executable,
                     '--observation-policy', 'until_event_or_cancel', '--stop-at', '2030-03-17T18:00:01Z',
                     THREAD, str(event), '--', 'Inspect original'])
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW + 86400)):
                poll_once(root, dispatch=False)
            record = all_records(root)[0].record
            self.assertEqual(record['status'], 'failed')
            self.assertEqual(record['time_recovery']['reason'], 'stop_reached')

    def test_late_event_preserves_unknown_submission_and_never_replays_input(self):
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.runtime_delivery import RuntimeRecipient, RuntimeObservation, RuntimeSubmission, RuntimeReconciliation
        class Adapter:
            submits = 0
            reconciles = 0
            def resolve(self, target):
                return RuntimeRecipient('codex', THREAD, target)
            def observe(self, recipient):
                return RuntimeObservation('ready', 'synthetic_idle', {})
            def submit_bounded(self, recipient, prompt, envelope):
                self.envelope = envelope
                self.submits += 1
                return RuntimeSubmission('uncertain', reason='synthetic_lost_ack')
            def reconcile_bounded(self, recipient, prompt, envelope):
                assert envelope == self.envelope
                self.reconciles += 1
                return RuntimeReconciliation(reason='not_yet_observed')
        with tempfile.TemporaryDirectory() as directory:
            root, event = Path(directory) / 'wake', Path(directory) / 'event'
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW)), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'file', '--json', '--codex-path', sys.executable,
                     '--observation-policy', 'until_event_or_cancel', '--ttl', '5m',
                     THREAD, str(event), '--', 'Inspect original; no credential authority'])
            event.write_text('synthetic response')
            adapter = Adapter()
            with patch('codex_wake.native_clock.snapshot', return_value=clock(NOW + 10 * 86400)):
                poll_once(root, dispatch=False)
                dispatch_firing_record(root, all_records(root)[0], runtime_adapter=adapter)
                dispatch_firing_record(root, all_records(root)[0], runtime_adapter=adapter)
            self.assertEqual(adapter.submits, 1)
            self.assertEqual(adapter.reconciles, 1)
            self.assertEqual(all_records(root)[0].record['attempts'], 1)
            self.assertEqual(all_records(root)[0].record['native_delivery']['state'], 'uncertain')
