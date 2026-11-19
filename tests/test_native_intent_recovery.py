import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.time_provider import TimeDecision
from codex_wake.daemon import poll_once
from codex_wake.records import all_records

THREAD = "01a1227e-a041-7b72-9c36-18349e7dd22c"


class NativeIntentRecoveryTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"CODEX_WAKE_STABLE_TIME_CONFIG": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def test_status_exposes_retained_time_alert_and_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            with patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None}), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'after', '--json', '--codex-path', sys.executable, THREAD, '3h', '--', 'Continue'])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                run(['--wake-root', str(root), 'status', '--json'])
            status = json.loads(output.getvalue())
            self.assertEqual(status['counts_by_time_recovery_state'], {'pending_time': 1})
            self.assertEqual(status['time_recovery_alerts'][0]['reason'], 'relative_origin_unanchored')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                run(['--wake-root', str(root), 'schema', '--json'])
            self.assertIn(6, json.loads(output.getvalue())['read_versions'])

    def test_cancelled_intent_archives_without_inventing_utc_and_keeps_retry_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            args = ['--wake-root', str(root), 'native', 'after', '--idempotency-key', 'cancelled-request', '--codex-path', sys.executable, THREAD, '3h', '--', 'Continue']
            with patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None}), contextlib.redirect_stdout(io.StringIO()):
                run(args)
                identifier = all_records(root)[0].record['id']
                run(['--wake-root', str(root), 'cancel', identifier])
                with patch('codex_wake.records.utc_now', side_effect=AssertionError('guest UTC forbidden')):
                    run(['--wake-root', str(root), 'archive', identifier])
                run(args)
            records = all_records(root, include_archive=True)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].record['status'], 'archived')
            self.assertIsNone(records[0].record['archived_at'])

    def test_rate_bound_preserves_not_before_precision_and_expiry(self):
        origin = {'utc': None, 'counter': {'epoch': 'host-a', 'counter': 1000000, 'frequency': 1000, 'rate_ppm': 5000}}
        # Independent worked samples: 10800 ticks-seconds is insufficient with
        # 0.5% fast-clock allowance; 10855 seconds proves the 10800s lower bound.
        cases = [(11800010, [], 'pending', 'not_due'),
                 (11855010, [], 'firing', 'not_before_and_expiry_established'),
                 (11855010, ['--time-tolerance', '1s'], 'pending', 'precision_unavailable'),
                 (12500000, [], 'failed', 'expiry_reached')]
        for counter, options, status, reason in cases:
            with self.subTest(counter=counter, options=options), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'wake'
                with patch('codex_wake.native_clock.snapshot', return_value=origin), contextlib.redirect_stdout(io.StringIO()):
                    run(['--wake-root', str(root), 'native', 'after', '--idempotency-key', 'rate-bound', '--ttl', '10m', *options, '--codex-path', sys.executable, THREAD, '3h', '--', 'Continue'])
                observed = {'utc': None, 'counter': dict(origin['counter'], counter=counter)}
                with patch('codex_wake.native_clock.snapshot', return_value=observed):
                    poll_once(root, dispatch=False)
                record = all_records(root)[0].record
                self.assertEqual(record['status'], status)
                self.assertEqual(record['time_recovery']['reason'], reason)

    def test_absolute_wake_requires_utc_and_rechecks_expiry_after_runtime_read(self):
        from subprocess import CompletedProcess
        from datetime import datetime, UTC
        due = datetime(2027, 1, 15, 12, tzinfo=UTC).timestamp()
        counter = {'epoch': 'host-a', 'counter': 1000000, 'frequency': 1000, 'rate_ppm': 0}
        bounded = lambda lower: {'utc': {'status': 'network', 'sources': ['a', 'b'], 'lower': lower, 'upper': lower + .1}, 'counter': counter}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            with patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': counter}), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'at', '--json', '--ttl', '1m', '--codex-path', sys.executable, THREAD, '2027-01-15T12:00:00Z', '--', 'Continue'])
            with patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': dict(counter, counter=999999999)}):
                self.assertEqual(poll_once(root, dispatch=False).fired, 0)
            with patch('codex_wake.native_clock.snapshot', side_effect=[bounded(due + 1), bounded(due + 1), bounded(due + 61)]), patch('codex_wake.native_delivery.read_native_thread', return_value={'id': THREAD, 'status': {'type': 'idle'}}), patch('codex_wake.native_delivery.subprocess.run') as submit:
                self.assertEqual(poll_once(root).submitted, 0)
            submit.assert_not_called()
            self.assertEqual(all_records(root)[0].record['time_recovery']['reason'], 'expiry_reached')

    def test_corrupted_intent_identity_or_history_is_held(self):
        from copy import deepcopy
        from codex_wake.records import classify_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            with patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None}), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'after', '--json', '--codex-path', sys.executable, THREAD, '3h', '--', 'Continue'])
            valid = all_records(root)[0].record
            for field, value in [('id', 'wake_intent_/../../escape'), ('events', None), ('scheduling_intent', [])]:
                with self.subTest(field=field):
                    self.assertEqual(classify_record(dict(deepcopy(valid), **{field: value})), 'hold')

    def test_authenticated_v2_wide_utc_retains_original_three_hour_deadline(self):
        from copy import deepcopy
        from test_native_clock import response
        from codex_wake.native_clock import from_response
        value = response()
        value.update(contract_version='2.0', bound='finite', best_effort=None,
                     counter_policy={'rate_ppm': 5000, 'maximum_age_ns': 300000000000})
        value['estimate'].update(earliest_utc='2027-01-15T12:00:00Z', utc='2027-01-15T12:00:03Z',
                                 latest_utc='2027-01-15T12:00:06Z', maximum_error_ns=3000000000, maximum_error_ms=3000.0)
        origin = from_response(value, counter=10000010, frequency=10000000)
        later = deepcopy(origin)
        later['utc'].update(lower=1800025207, upper=1800025213)
        later['counter']['counter'] += 108070000000
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            with patch('codex_wake.native_clock.snapshot', return_value=origin), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'after', '--json', '--idempotency-key', 'wide-v2', '--codex-path', sys.executable, THREAD, '3h', '--', 'Continue'])
            with patch('codex_wake.native_clock.snapshot', return_value=later):
                self.assertEqual(poll_once(root, dispatch=False).fired, 1)
            self.assertEqual(all_records(root)[0].record['scheduling_intent']['utc_anchor'], origin['utc'])

    def test_wrong_root_or_thread_cannot_dispatch_the_retained_request(self):
        import shutil
        origin = {'utc': None, 'counter': {'epoch': 'host-a', 'counter': 1000000, 'frequency': 1000, 'rate_ppm': 0}}
        due = {'utc': None, 'counter': dict(origin['counter'], counter=11800010)}
        with tempfile.TemporaryDirectory() as directory:
            root, other = Path(directory) / 'original', Path(directory) / 'other'
            with patch('codex_wake.native_clock.snapshot', return_value=origin), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'after', '--json', '--codex-path', sys.executable, THREAD, '3h', '--', 'Continue'])
            with patch('codex_wake.native_clock.snapshot', return_value=due):
                self.assertEqual(poll_once(root, dispatch=False).fired, 1)
            item = all_records(root)[0]
            (other / 'pending').mkdir(parents=True)
            shutil.copyfile(item.path, other / 'pending' / item.path.name)
            with patch('codex_wake.native_clock.snapshot', return_value=due), patch('codex_wake.native_delivery.read_native_thread', return_value={'id': 'c357309d-c209-4467-b757-e1488e6b1aaa', 'status': {'type': 'idle'}}), patch('codex_wake.native_delivery.subprocess.run') as submit:
                self.assertEqual(poll_once(other).submitted, 0)
                self.assertEqual(poll_once(root).submitted, 0)
            submit.assert_not_called()
            original = all_records(root)[0].record
            self.assertEqual(original['target']['thread_id'], THREAD)
            self.assertEqual(original['status'], 'pending')
            self.assertEqual(original['attempts'], 0)

    def test_required_monitor_must_support_the_retained_record_schema(self):
        from types import SimpleNamespace
        from codex_wake.records import WakeError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            with patch('codex_wake.monitor.monitor_readiness', return_value={'monitor_ready': True}), patch('codex_wake.signal_records.probe_managed_reader_capability', return_value=SimpleNamespace(schema_versions={1, 2, 3, 4, 5})), patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None}), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(WakeError, 'schema8'):
                    run(['--wake-root', str(root), 'native', 'after', '--require-monitor', '--json', '--codex-path', sys.executable, THREAD, '3h', '--', 'Continue'])
            self.assertEqual(len(all_records(root)), 1)

    def test_three_hour_request_is_retained_and_visible_when_time_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            output = io.StringIO()
            with patch("codex_wake.time_inspection.network_time_decision", return_value=TimeDecision("uncertain", reason="outage")), contextlib.redirect_stdout(output):
                code = run(["--wake-root", str(root), "native", "after", "--codex-path", sys.executable, THREAD, "3h", "--", "Inspect the agreed result"])
            self.assertEqual(code, 0)
            listing = io.StringIO()
            with contextlib.redirect_stdout(listing):
                self.assertEqual(run(["--wake-root", str(root), "list", "--json"]), 0)
            records = json.loads(listing.getvalue())
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["target"]["thread_id"], THREAD)
            self.assertEqual(records[0]["time_recovery"]["state"], "pending_time")
            self.assertIn("pending_time", output.getvalue())

    def test_retained_three_hour_delay_uses_same_epoch_counter_without_utc(self):
        first = {"utc": None, "counter": {"epoch": "host-a", "counter": 1000000, "frequency": 1000, "rate_ppm": 0}, "reason": "uncertainty_exceeded"}
        due = {"utc": None, "counter": {"epoch": "host-a", "counter": 11800010, "frequency": 1000, "rate_ppm": 0}, "reason": "uncertainty_exceeded"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            with patch("codex_wake.time_inspection.network_time_decision", return_value=TimeDecision("uncertain")), patch("codex_wake.native_clock.snapshot", return_value=first), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(["--wake-root", str(root), "native", "after", "--codex-path", sys.executable, THREAD, "3h", "--", "Continue"]), 0)
            with patch("codex_wake.native_clock.snapshot", return_value=due):
                result = poll_once(root, dispatch=False)
            self.assertEqual(result.fired, 1)
            self.assertEqual(len(all_records(root)), 1)
            self.assertEqual(all_records(root)[0].record["status"], "firing")

    def test_counter_only_recovery_holds_without_inventing_absolute_expiry(self):
        from subprocess import CompletedProcess
        first = {"utc": None, "counter": {"epoch": "host-a", "counter": 1000000, "frequency": 1000, "rate_ppm": 0}, "reason": "uncertainty_exceeded"}
        due = {"utc": None, "counter": {"epoch": "host-a", "counter": 11800010, "frequency": 1000, "rate_ppm": 0}, "reason": "uncertainty_exceeded"}
        queue = "01a1227e-a041-7b72-9c36-18349e7dd23c"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            with patch("codex_wake.time_inspection.network_time_decision", return_value=TimeDecision("uncertain")), patch("codex_wake.native_clock.snapshot", return_value=first), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(["--wake-root", str(root), "native", "after", "--codex-path", sys.executable, THREAD, "3h", "--", "Continue"]), 0)
            with patch("codex_wake.native_clock.snapshot", return_value=due), patch("codex_wake.native_delivery.read_native_thread", return_value={"id": THREAD, "status": {"type": "idle"}}), patch("codex_wake.native_delivery.subprocess.run", return_value=CompletedProcess([], 0, f"Queued message {queue} for thread {THREAD}.\n", "")) as submit:
                first_poll = poll_once(root)
                second_poll = poll_once(root)
            self.assertEqual(first_poll.submitted, 0)
            self.assertEqual(second_poll.submitted, 0)
            submit.assert_not_called()
            record = all_records(root)[0].record
            self.assertEqual(record['status'], 'pending')
            self.assertEqual(record['attempts'], 0)
            self.assertNotIn('native_delivery', record)
            self.assertIn('bounded_native_absolute_expiry_unavailable', str(record['policy_outcome']))

    def test_explicit_intent_key_survives_recovery_and_rejects_changed_request(self):
        from codex_wake.records import WakeError
        clock = {"utc": None, "counter": None, "reason": "outage"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            args = ["--wake-root", str(root), "native", "after", "--idempotency-key", "monitor-successor-001", "--codex-path", sys.executable, THREAD, "3h", "--", "Continue"]
            with patch("codex_wake.native_clock.snapshot", return_value=clock), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(args), 0)
                self.assertEqual(run(args), 0)
                with self.assertRaisesRegex(WakeError, "idempotency_conflict"):
                    run(args[:-1] + ["Different intent"])
            self.assertEqual(len(all_records(root)), 1)

    def test_absolute_stop_cannot_be_bypassed_by_a_relative_counter(self):
        first = {"utc": None, "counter": {"epoch": "host-a", "counter": 1000000, "frequency": 1000, "rate_ppm": 0}, "reason": "outage"}
        due = {"utc": None, "counter": {"epoch": "host-a", "counter": 11800010, "frequency": 1000, "rate_ppm": 0}, "reason": "outage"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            with patch("codex_wake.native_clock.snapshot", return_value=first), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(["--wake-root", str(root), "native", "after", "--idempotency-key", "stop-bound", "--stop-at", "2027-01-15T12:00:00Z", "--codex-path", sys.executable, THREAD, "3h", "--", "Continue"]), 0)
            with patch("codex_wake.native_clock.snapshot", return_value=due):
                result = poll_once(root, dispatch=False)
            self.assertEqual(result.fired, 0)
            self.assertEqual(all_records(root)[0].record["time_recovery"]["reason"], "absolute_stop_time_unavailable")

    def test_recovery_cannot_extend_an_unanchored_original_expiry(self):
        outage = {"utc": None, "counter": None, "reason": "outage"}
        recovered = {"utc": {"status": "network", "sources": ["a", "b"], "lower": 1800000000, "upper": 1800000000.2}, "counter": None}
        due = {"utc": {"status": "network", "sources": ["a", "b"], "lower": 1800000061, "upper": 1800000061.2}, "counter": None}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            output = io.StringIO()
            with patch("codex_wake.native_clock.snapshot", return_value=outage), contextlib.redirect_stdout(output):
                run(["--wake-root", str(root), "native", "after", "--json", "--idempotency-key", "recover-origin", "--ttl", "1m", "--codex-path", sys.executable, THREAD, "1m", "--", "Continue"])
            receipt = json.loads(output.getvalue())
            self.assertTrue(receipt['requires_original_clock_evidence'])
            self.assertEqual(receipt['automatic_recovery'], 'requires_original_clock_evidence')
            self.assertEqual(receipt['time_recovery']['reason'], 'relative_origin_unanchored')
            with patch("codex_wake.native_clock.snapshot", return_value=recovered):
                self.assertEqual(poll_once(root, dispatch=False).fired, 0)
            with patch("codex_wake.native_clock.snapshot", return_value=due):
                self.assertEqual(poll_once(root, dispatch=False).fired, 0)
            record = all_records(root)[0].record
            self.assertEqual(record['scheduling_intent']['origin_state'], 'awaiting_qualified_clock')
            self.assertIsNone(record['scheduling_intent']['counter_anchor'])
            self.assertIsNone(record['scheduling_intent']['utc_anchor'])
            self.assertEqual(record['time_recovery']['reason'], 'relative_origin_unanchored')
            self.assertIn('original', record['time_recovery']['alert'].lower())

    def test_uncertain_submission_is_reconciled_during_outage_without_retry(self):
        import subprocess
        first = {"utc": None, "counter": {"epoch": "host-a", "counter": 1000000, "frequency": 1000, "rate_ppm": 0}}
        due = {"utc": None, "counter": {"epoch": "host-a", "counter": 11800010, "frequency": 1000, "rate_ppm": 0}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            with patch("codex_wake.native_clock.snapshot", return_value=first), contextlib.redirect_stdout(io.StringIO()):
                run(["--wake-root", str(root), "native", "after", "--idempotency-key", "uncertain-001", "--codex-path", sys.executable, THREAD, "3h", "--", "Continue"])
            # This is an already-uncertain historical unbounded attempt. The
            # outage permits its original read contract, never new submission.
            from codex_wake.records import replace_record
            found = all_records(root)[0]
            record = dict(found.record, status='firing', attempts=1,
                native_delivery=dict(state='uncertain', route='existing_tab',
                    submission_id='11111111-1111-4111-8111-111111111111'))
            replace_record(root, found, record)
            with patch("codex_wake.native_clock.snapshot", return_value=due), patch("codex_wake.native_delivery.read_native_thread", return_value={"id": THREAD, "status": {"type": "idle"}}), patch("codex_wake.native_delivery.subprocess.run", side_effect=subprocess.TimeoutExpired("queue", 30)) as submit:
                poll_once(root)
                with patch("codex_wake.native_clock.snapshot", return_value={"utc": None, "counter": None, "reason": "outage"}), patch("codex_wake.native_delivery.native_request", side_effect=lambda endpoint, codex, method, params, timeout: {"data": [], "nextCursor": None} if method == "thread/queue/list" else {"thread": {"id": THREAD, "turns": []}}):
                    poll_once(root)
                    with patch('codex_wake.native_delivery.utc_now', side_effect=AssertionError('guest UTC forbidden')), contextlib.redirect_stdout(io.StringIO()):
                        run(['--wake-root', str(root), 'native', 'reconcile', all_records(root)[0].record['id']])
            self.assertTrue(all('queue' not in call.args[0] for call in submit.call_args_list))
            record = all_records(root)[0].record
            self.assertEqual(record["attempts"], 1)
            self.assertEqual(record["native_delivery"]["state"], "uncertain")

    def test_epoch_loss_holds_original_request_without_restarting_delay(self):
        first = {"utc": None, "counter": {"epoch": "host-a", "counter": 1000000, "frequency": 1000, "rate_ppm": 0}}
        changed = {"utc": None, "counter": {"epoch": "host-b", "counter": 999999999, "frequency": 1000, "rate_ppm": 0}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            with patch("codex_wake.native_clock.snapshot", return_value=first), contextlib.redirect_stdout(io.StringIO()):
                run(["--wake-root", str(root), "native", "after", "--idempotency-key", "epoch-001", "--codex-path", sys.executable, THREAD, "3h", "--", "Continue"])
            with patch("codex_wake.native_clock.snapshot", return_value=changed):
                self.assertEqual(poll_once(root, dispatch=False).fired, 0)
            record = all_records(root)[0].record
            self.assertEqual(record["scheduling_intent"]["counter_anchor"]["epoch"], "host-a")
            self.assertEqual(record["time_recovery"]["reason"], "counter_continuity_lost")

    def test_qualified_utc_recovers_original_deadline_after_counter_epoch_change(self):
        first = {"utc": {"status": "network", "sources": ["a", "b"], "lower": 1800000000, "upper": 1800000000.2}, "counter": {"epoch": "host-a", "counter": 1000000, "frequency": 1000, "rate_ppm": 0}}
        restored = {"utc": {"status": "network", "sources": ["a", "b"], "lower": 1800010801, "upper": 1800010801.2}, "counter": {"epoch": "host-b", "counter": 2000, "frequency": 1000, "rate_ppm": 0}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wake"
            with patch("codex_wake.native_clock.snapshot", return_value=first), contextlib.redirect_stdout(io.StringIO()):
                run(["--wake-root", str(root), "native", "after", "--idempotency-key", "restart-clock-001", "--codex-path", sys.executable, THREAD, "3h", "--", "Continue"])
            with patch("codex_wake.native_clock.snapshot", return_value=restored):
                self.assertEqual(poll_once(root, dispatch=False).fired, 1)
            self.assertEqual(all_records(root)[0].record["time_recovery"]["mode"], "bounded_utc")

    def test_utc_recovery_uses_saved_origin_when_counter_bounds_have_grown_too_wide(self):
        first = {'utc': {'status': 'network', 'sources': ['a', 'b'], 'lower': 1800000000, 'upper': 1800000000.2},
                 'counter': {'epoch': 'host-a', 'counter': 1000000, 'frequency': 1000, 'rate_ppm': 5000}}
        recovered = {'utc': {'status': 'network', 'sources': ['a', 'b'], 'lower': 1800086401, 'upper': 1800086401.2},
                     'counter': dict(first['counter'], counter=88000000)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            with patch('codex_wake.native_clock.snapshot', return_value=first), contextlib.redirect_stdout(io.StringIO()):
                run(['--wake-root', str(root), 'native', 'after', '--json', '--ttl', '10m', '--codex-path', sys.executable, THREAD, '24h', '--', 'Continue'])
            with patch('codex_wake.native_clock.snapshot', return_value=recovered):
                self.assertEqual(poll_once(root, dispatch=False).fired, 1)
            self.assertEqual(all_records(root)[0].record['time_recovery']['mode'], 'bounded_utc')

    def test_reconcile_recovers_original_future_timer_without_submitting_or_rebasing(self):
        origin = dict(utc=dict(status='network', sources=['a', 'b'], lower=1893456000, upper=1893456000.2), counter=None)
        later = dict(utc=dict(status='network', sources=['a', 'b'], lower=1893542401, upper=1893542401.2), counter=None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            output = io.StringIO()
            with patch('codex_wake.native_clock.snapshot', return_value=origin), contextlib.redirect_stdout(output):
                self.assertEqual(run(['--wake-root', str(root), 'native', 'after', '--json',
                    '--ttl', '24h', '--wake-lifetime', 'persistent', '--idempotency-key', 'recover-future',
                    '--codex-path', sys.executable, THREAD, '24h', '--', 'Read-only review']), 0)
            identifier = json.loads(output.getvalue())['id']
            output = io.StringIO()
            with patch('codex_wake.native_clock.snapshot', return_value=later), contextlib.redirect_stdout(output):
                self.assertEqual(run(['--wake-root', str(root), 'native', 'reconcile', identifier]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['status'], 'firing')
            self.assertEqual(result['result'], 'time_reconciled')
            self.assertEqual(result['due_at'], '2030-01-02T00:00:00.200000Z')
            self.assertEqual(result['expires_at'], '2030-01-03T00:00:00.200000Z')
            record = all_records(root)[0].record
            self.assertEqual(record['scheduling_intent']['utc_anchor'], origin['utc'])
            self.assertEqual(record['attempts'], 0)
            self.assertNotIn('native_delivery', record)
            self.assertEqual(len(all_records(root)), 1)
