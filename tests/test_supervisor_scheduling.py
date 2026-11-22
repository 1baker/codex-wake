from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from codex_wake.records import WakeError
from codex_wake.supervisor import build_supervisor_config, enroll_root


class SchedulingTests(unittest.TestCase):
    def test_enrollment_preserves_distinct_finite_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = enroll_root(wake_root=base / 'wake', registry_dir=base / 'registry',
                               poll_interval=60)
            self.assertEqual(json.loads(path.read_text())['poll_interval'], 60)
            for value in (0, -1, float('inf'), float('nan'), True):
                with self.assertRaises(WakeError):
                    enroll_root(wake_root=base / 'other', registry_dir=base / 'registry',
                                poll_interval=value)

    def test_process_scheduler_polls_real_roots_and_preserves_cadence(self):
        from codex_wake.supervisor_scheduler import SupervisorScheduler
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(registry_dir=base / 'registry',
                state_dir=base / 'state/supervisor', interval=0.1,
                max_workers=2, poll_timeout=10, validate_executable=False)
            root = base / 'wake'
            enroll_root(wake_root=root, registry_dir=config.registry_dir, root_id='slow',
                        poll_interval=60)
            with SupervisorScheduler(config, dispatch=False) as scheduler:
                completed = []
                end = time.monotonic() + 8
                while not completed and time.monotonic() < end:
                    completed.extend(scheduler.tick())
                    time.sleep(0.01)
                self.assertEqual(len(completed), 1)
                self.assertTrue(completed[0]['ok'], completed)
                self.assertEqual(scheduler.tick(), [])
                self.assertEqual(scheduler.running_count, 0)
                self.assertEqual(len(scheduler.worker_pids), 1)

    def test_abandoned_poll_is_held_and_requires_exact_reconciliation(self):
        from codex_wake.supervisor_scheduler import SupervisorScheduler, reconcile_root
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(registry_dir=base / 'registry',
                state_dir=base / 'state/supervisor', validate_executable=False)
            root = base / 'wake'; root.mkdir()
            enroll_root(wake_root=root, registry_dir=config.registry_dir, root_id='one')
            inflight = config.state_dir / 'inflight'; inflight.mkdir(parents=True)
            (inflight / 'old.json').write_text(json.dumps({
                'root_id': 'one', 'wake_root': str(root), 'token': 'old-token'}))
            with SupervisorScheduler(config, dispatch=False) as scheduler:
                self.assertEqual(scheduler.tick(), [])
                hold = json.loads((root / 'monitor-reconciliation.json').read_text())
                self.assertEqual(hold['token'], 'old-token')
                with self.assertRaises(WakeError):
                    reconcile_root(config, 'one', expected_token='wrong')
            reconcile_root(config, 'one', expected_token='old-token')
            self.assertFalse((root / 'monitor-reconciliation.json').exists())

    def test_startup_recovers_a_versioned_interrupted_poll(self):
        from codex_wake.supervisor_scheduler import SupervisorScheduler, _key
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(registry_dir=base / 'registry',
                state_dir=base / 'state/supervisor', validate_executable=False)
            root = base / 'wake'
            root.mkdir()
            enroll_root(wake_root=root, registry_dir=config.registry_dir, root_id='one')
            hold = root / 'monitor-reconciliation.json'
            inflight = config.state_dir / 'inflight' / (_key(str(root)) + '.json')
            inflight.parent.mkdir(parents=True)
            inflight.write_text(json.dumps({'root_id': 'one', 'wake_root': str(root),
                'token': 'interrupted-token', 'recovery_schema': 1}))
            receipt = config.state_dir / 'reconciled' / 'interrupted-token.json'
            for _ in range(2):
                with SupervisorScheduler(config, dispatch=False) as scheduler:
                    self.assertFalse(hold.exists())
                    self.assertFalse(inflight.exists())
                    self.assertEqual(json.loads(receipt.read_text())['recovery'], 'record_scoped')
                    scheduler.tick()
                    self.assertEqual(scheduler.running_count, 1)

    def test_startup_retries_recovery_when_the_previous_poll_releases_ownership(self):
        from codex_wake.monitor_ownership import MonitorOwnership
        from codex_wake.supervisor_scheduler import SupervisorScheduler, _key

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(registry_dir=base / 'registry',
                state_dir=base / 'state/supervisor', interval=0.02, validate_executable=False)
            root = base / 'wake'
            enroll_root(wake_root=root, registry_dir=config.registry_dir, root_id='one')
            inflight = config.state_dir / 'inflight' / (_key(str(root)) + '.json')
            inflight.parent.mkdir(parents=True)
            inflight.write_text(json.dumps({'root_id': 'one', 'wake_root': str(root),
                'token': 'contention', 'recovery_schema': 1}))
            hold = root / 'monitor-reconciliation.json'
            scheduler = SupervisorScheduler(config, dispatch=False)
            with MonitorOwnership(root) as previous:
                self.assertTrue(previous.acquired)
                scheduler.__enter__()
                self.addCleanup(scheduler.close)
                scheduler.tick()
                self.assertTrue(hold.exists())
                self.assertEqual(scheduler.running_count, 0)
            limit = time.monotonic() + 2
            while not scheduler.running_count and time.monotonic() < limit:
                scheduler.tick()
                time.sleep(0.01)
            self.assertFalse(hold.exists())
            self.assertEqual(scheduler.running_count, 1)
            scheduler.close()

    def test_hung_root_does_not_block_another_root_and_is_held(self):
        from codex_wake.supervisor_scheduler import SupervisorScheduler
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(registry_dir=base / 'registry',
                state_dir=base / 'state/supervisor', interval=0.05,
                max_workers=2, poll_timeout=1.5, validate_executable=False)
            blocked = base / 'blocked'; (blocked / 'pending').mkdir(parents=True)
            os.mkfifo(blocked / 'pending/wake_blocked.json')
            enroll_root(wake_root=blocked, registry_dir=config.registry_dir, root_id='blocked')
            enroll_root(wake_root=base / 'healthy', registry_dir=config.registry_dir, root_id='healthy')
            completed = []
            with SupervisorScheduler(config, dispatch=False) as scheduler:
                end = time.monotonic() + 6
                while time.monotonic() < end:
                    completed.extend(scheduler.tick())
                    if (blocked / 'monitor-reconciliation.json').exists():
                        break
                    time.sleep(0.01)
                self.assertTrue(any(r['root_id'] == 'healthy' and r['ok'] for r in completed))
                failures = [r for r in completed if r['root_id'] == 'blocked']
                self.assertEqual(failures[0]['error'], 'poll_timeout_outcome_unknown')
                self.assertTrue((blocked / 'monitor-reconciliation.json').is_file())
                self.assertLessEqual(len(scheduler.worker_pids), 2)

    def test_cli_enrollment_rejects_nonfinite_values_and_publishes_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = [sys.executable, '-m', 'codex_wake.entrypoint', 'supervisor', 'enroll',
                '--registry-dir', str(base / 'registry'), '--state-dir', str(base / 'state'),
                '--wake-root', str(base / 'wake'), '--root-id', 'public']
            result = subprocess.run(command + ['--poll-interval', '60'],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((base / 'registry/public.json').read_text())['poll_interval'], 60)
            rejected = subprocess.run(command + ['--poll-interval', 'nan'],
                                      text=True, capture_output=True, timeout=10)
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(json.loads((base / 'registry/public.json').read_text())['poll_interval'], 60)

    def test_invalid_root_path_reports_failure_without_blocking_healthy_root(self):
        from codex_wake.supervisor_scheduler import SupervisorScheduler
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = build_supervisor_config(registry_dir=base / 'registry',
                state_dir=base / 'state/supervisor', validate_executable=False)
            bad = base / 'bad'; bad.mkdir()
            enroll_root(wake_root=bad, registry_dir=config.registry_dir, root_id='bad')
            enroll_root(wake_root=base / 'healthy', registry_dir=config.registry_dir, root_id='healthy')
            bad.rmdir(); bad.symlink_to(bad)
            results = []
            with SupervisorScheduler(config, dispatch=False) as scheduler:
                end = time.monotonic() + 8
                while time.monotonic() < end:
                    results.extend(scheduler.tick())
                    if any(r['root_id'] == 'healthy' and r['ok'] for r in results):
                        break
                    time.sleep(0.01)
            self.assertTrue(any(r['root_id'] == 'bad' and not r['ok'] for r in results))
            self.assertTrue(any(r['root_id'] == 'healthy' and r['ok'] for r in results))
