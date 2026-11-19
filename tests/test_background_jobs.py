"""Real-process job acceptance (#336); timed cases require enrolled Stable Time."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from codex_wake.background_jobs import BackgroundJobs
from codex_wake import measurements
from codex_wake.session_permissions import PermissionStore, Principal
from codex_wake.task_briefs import BriefAuthority, TaskBriefStore


class BackgroundJobsTests(unittest.TestCase):
    def test_exact_cancel_remains_available_without_qualified_timestamp(self):
        from unittest.mock import patch
        from codex_wake import measurements
        clock = dict(reason='authenticated_counter_only', counter=dict(
            epoch='c357309d-c209-4467-b757-e1488e6b1aaa', counter=1000,
            frequency=1000, rate_ppm=0))
        store = self.approve('pass', max_seconds=3)
        with patch.object(measurements, 'utc_time', return_value=100), patch.object(measurements, 'snapshot', return_value=clock), patch('codex_wake.background_jobs.subprocess.Popen') as spawn:
            spawn.return_value.poll.return_value = 0
            job = store.launch('fixture', principal=self.worker, idempotency_key='cancel-clock')
        with patch.object(measurements, 'utc_time', side_effect=measurements.TimeUnavailable('unqualified')):
            store.cancel(job['job_id'], principal=self.worker, expected_generation=job['generation'])
        request = json.loads((self.root/'background-jobs'/job['job_id']/'cancel.json').read_text())
        self.assertIsNone(request['requested_at'])
        self.assertEqual(request['clock_status'], 'unavailable')
        self.assertEqual(request['generation'], job['generation'])

    def test_unqualified_stable_time_refuses_before_supervisor_launch(self):
        from unittest.mock import patch
        from codex_wake import measurements
        store = self.approve("raise SystemExit('must not execute')", max_seconds=3)
        with patch.object(measurements, 'utc_time', side_effect=measurements.TimeUnavailable('unqualified')), patch('codex_wake.background_jobs.subprocess.Popen') as spawn:
            with self.assertRaises(measurements.TimeUnavailable):
                store.launch('fixture', principal=self.worker, idempotency_key='clock-held')
        spawn.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'wake'
        self.workspace = Path(self.tmp.name) / 'work'
        self.workspace.mkdir()
        self.operator = Principal('operator', 'operator')
        self.worker = Principal('worker', tasks=('task-1',))
        PermissionStore(self.root).configure({'version': 1, 'global': {'actions': {'job.launch': 'allow', 'job.cancel': 'allow'}}},
            self.operator, expected_revision=0)
        brief = TaskBriefStore(self.root)
        authority = BriefAuthority('operator', 'operator')
        brief.propose('task-1', dict(objective='Run a bounded local fixture', phase='test',
            non_goals=['No providers'], acceptance=['Retained exact exit and logs'], context=[],
            workspace=str(self.workspace), allocation_ref='fixture', permission_ref='fixture'), authority=authority)
        brief.approve('task-1', 1, authority=authority)
        brief.admit('task-1', 'assignment-1', authority=authority)
        self.pin = brief.assignment_pin('task-1', 'assignment-1')

    def terminal(self, store, job_id, seconds=8):
        deadline = measurements.deadline(seconds)
        while not deadline.expired():
            value = store.inspect(job_id)
            if value['status'] in ('completed', 'cancelled', 'timed_out', 'failed', 'unknown'):
                return value
            time.sleep(.02)
        self.fail('job did not reach a terminal or unknown outcome')

    def test_command_outlives_submitting_process_and_retains_exit_logs_on_restart(self):
        script = "import time,sys; time.sleep(.2); print('retained stdout'); print('retained stderr',file=sys.stderr); sys.exit(7)"
        submit = """
import json,sys
from codex_wake.background_jobs import BackgroundJobs
from codex_wake.session_permissions import Principal
store=BackgroundJobs(sys.argv[1])
profile=store.approve_command('fixture', [sys.executable,'-c',sys.argv[3]], sys.argv[2],
    principal=Principal('operator','operator'), task_pin=json.loads(sys.argv[4]), owner='worker', max_seconds=3, max_log_bytes=1024)
job=store.launch('fixture',principal=Principal('worker',tasks=('task-1',)),idempotency_key='one')
print(json.dumps(job))
"""
        result = subprocess.run([sys.executable, '-c', submit, str(self.root), str(self.workspace), script,
            json.dumps(self.pin)], capture_output=True, text=True, check=True, timeout=5)
        launched = json.loads(result.stdout)
        value = self.terminal(BackgroundJobs(self.root), launched['job_id'])
        self.assertEqual(value['status'], 'completed')
        self.assertEqual(value['result']['returncode'], 7)
        self.assertEqual(value['result']['process'], value['process'])
        self.assertEqual(Path(value['stdout_path']).read_text(), 'retained stdout\n')
        self.assertEqual(Path(value['stderr_path']).read_text(), 'retained stderr\n')
        self.assertEqual(value['result']['generation'], launched['generation'])
        self.assertEqual(value['result']['intent_sha256'], value['intent_sha256'])


    def approve(self, script, **bounds):
        store = BackgroundJobs(self.root)
        store.approve_command('fixture', [sys.executable, '-c', script], self.workspace,
            principal=self.operator, task_pin=self.pin, owner='worker', **bounds)
        return store

    def test_cancel_is_attributable_and_kills_owned_term_resistant_descendants(self):
        marker = self.workspace / 'child-ready'
        child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"
        script = ("import subprocess,sys,signal,time,pathlib; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
            f"pathlib.Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(30)")
        store = self.approve(script, max_seconds=5, max_log_bytes=64)
        launched = store.launch('fixture', principal=self.worker, idempotency_key='cancel')
        deadline = measurements.deadline(2)
        while not marker.exists() and not deadline.expired():
            time.sleep(.01)
        self.assertTrue(marker.exists())
        store.cancel(launched['job_id'], principal=self.worker, expected_generation=launched['generation'])
        value = self.terminal(store, launched['job_id'])
        self.assertEqual(value['status'], 'cancelled')
        self.assertEqual(value['result']['cancellation']['actor'], 'worker')
        self.assertEqual(value['result']['returncode'], -9)
        from codex_wake.process_signals import observe_process_exit
        child_sample = observe_process_exit(int(marker.read_text()))
        self.assertIn(child_sample.state, ('disappeared', 'zombie'))


    def test_public_command_inspects_owned_job_and_denies_foreign_owner(self):
        from argparse import Namespace
        from codex_wake.background_job_commands import execute
        from codex_wake.background_jobs import BackgroundJobError
        store = self.approve("print('ok')", max_seconds=2)
        launched = store.launch('fixture', principal=self.worker, idempotency_key='inspect')
        self.terminal(store, launched['job_id'])
        args = Namespace(job_command='show', job_id=launched['job_id'])
        value = execute(args, self.root, principal=self.worker)
        self.assertEqual(value['result']['returncode'], 0)
        with self.assertRaises(BackgroundJobError):
            execute(args, self.root, principal=Principal('peer', tasks=('task-1',)))


    def test_cancel_revocation_before_effect_does_not_interrupt_original_job(self):
        import signal
        store = self.approve("import time; time.sleep(.8)", max_seconds=2)
        job = store.launch('fixture', principal=self.worker, idempotency_key='revoked-cancel')
        os.kill(job['supervisor']['pid'], signal.SIGSTOP)
        try:
            store.cancel(job['job_id'], principal=self.worker, expected_generation=1)
            PermissionStore(self.root).configure({'version': 1, 'mandatory': ['job.cancel'],
                'global': {'actions': {'job.launch': 'allow'}}}, self.operator, expected_revision=1)
        finally:
            os.kill(job['supervisor']['pid'], signal.SIGCONT)
        result = self.terminal(store, job['job_id'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['result']['returncode'], 0)


    def test_wall_and_combined_log_bounds_are_enforced(self):
        store = self.approve("import os,time; os.write(1,b'x'*100000); os.write(2,b'y'*100000); time.sleep(30)",
            max_seconds=.15, max_log_bytes=128)
        job = store.launch('fixture', principal=self.worker, idempotency_key='bounded')
        value = self.terminal(store, job['job_id'])
        self.assertEqual(value['status'], 'timed_out')
        self.assertTrue(value['result']['log_truncated'])
        self.assertEqual(value['result']['stored_log_bytes'], 128)
        self.assertEqual(sum(Path(value[key]).stat().st_size for key in ('stdout_path', 'stderr_path')), 128)

    def test_supervisor_loss_preserves_unknown_and_key_never_relaunches(self):
        import signal
        marker = self.workspace / 'execution-count'
        script = f"import pathlib,time; p=pathlib.Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x'); time.sleep(.5)"
        store = self.approve(script, max_seconds=2)
        job = store.launch('fixture', principal=self.worker, idempotency_key='uncertain')
        deadline = measurements.deadline(2)
        while not marker.exists() and not deadline.expired():
            time.sleep(.01)
        self.assertTrue(marker.exists())
        os.kill(job['supervisor']['pid'], signal.SIGKILL)
        deadline = measurements.deadline(2)
        while store.inspect(job['job_id'])['status'] != 'unknown' and not deadline.expired():
            time.sleep(.01)
        again = BackgroundJobs(self.root).launch('fixture', principal=self.worker, idempotency_key='uncertain')
        self.assertEqual(again['job_id'], job['job_id'])
        self.assertEqual(again['status'], 'unknown')
        self.assertEqual(marker.read_text(), 'x')
        # Only fixture ownership is cleaned up; product never guesses a lost group.
        try:
            os.killpg(job['process']['pid'], signal.SIGKILL)
        except ProcessLookupError:
            pass

    def test_launch_denial_and_changed_profile_cannot_reuse_old_intent(self):
        from codex_wake.background_jobs import BackgroundJobError
        from codex_wake.session_permissions import PermissionDenied
        store = self.approve("print('once')", max_seconds=2)
        job = store.launch('fixture', principal=self.worker, idempotency_key='stable')
        self.terminal(store, job['job_id'])
        self.assertEqual(store.launch('fixture', principal=self.worker, idempotency_key='stable')['job_id'], job['job_id'])
        self.approve("print('different')", max_seconds=2)
        with self.assertRaises(BackgroundJobError) as conflict:
            store.launch('fixture', principal=self.worker, idempotency_key='stable')
        self.assertEqual(conflict.exception.code, 'job_idempotency_conflict')
        PermissionStore(self.root).configure({'version': 1, 'mandatory': ['job.launch']},
            self.operator, expected_revision=1)
        with self.assertRaises(PermissionDenied):
            store.launch('fixture', principal=self.worker, idempotency_key='denied')

    def test_await_registers_real_existing_exists_signal_and_reconstructs_after_completion(self):
        from datetime import datetime, UTC
        from codex_wake.event_wake import EventWake
        from codex_wake.filesystem_signals import FilesystemSignalAdapter
        from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher, signal_journal_path
        from codex_wake.signal_store import SQLiteSignalModule
        from codex_wake.signals import Resume, WakeIntent, Registration
        from codex_wake.daemon import poll_once
        store = self.approve("print('finished')", max_seconds=2)
        job = store.launch('fixture', principal=self.worker, idempotency_key='await')
        self.terminal(store, job['job_id'])
        now = datetime.now(UTC)
        publisher = WakeRecordPublisher(self.root,
            ManagedReaderCapability(self.root, 'fixture', 1, frozenset({1, 2}), True))
        runtime = SQLiteSignalModule(signal_journal_path(self.root), record_publisher=publisher)
        def register(path, key, snapshot):
            self.assertEqual(snapshot['intent']['owner'], 'worker')
            adapter = FilesystemSignalAdapter(self.root, path)
            value = EventWake(runtime, adapters=(adapter,), clock=lambda: now,
                id_factory=lambda: 'wake_job_fixture').register(WakeIntent(adapter.request('exists'),
                    Resume('Inspect original job result', self.root,
                        {'transport': 'tmux', 'tmux_socket': '/tmp/fixture', 'pane': '%1'})), idempotency_key=key)
            self.assertIsInstance(value, Registration)
            return {'wake_id': value.wake_id}
        awaiting = store.await_result(job['job_id'], principal=self.worker, register_wake=register)
        self.assertEqual(awaiting['wake']['wake_id'], 'wake_job_fixture')
        first = poll_once(self.root, now=now, dispatch=False, signal_runtime=runtime)
        second = poll_once(self.root, now=now, dispatch=False, signal_runtime=runtime)
        self.assertEqual(first.fired, 1)
        self.assertEqual(second.fired, 0)


    def test_unknown_store_version_is_retained_without_command_replay(self):
        from codex_wake.background_jobs import BackgroundJobError
        store = self.approve("print('version')", max_seconds=2)
        job = store.launch('fixture', principal=self.worker, idempotency_key='version')
        value = self.terminal(store, job['job_id'])
        path = Path(value['result_path']).with_name('state.json')
        state = json.loads(path.read_text())
        state['version'] = 99
        path.write_text(json.dumps(state))
        original = path.read_bytes()
        with self.assertRaises(BackgroundJobError):
            BackgroundJobs(self.root).launch('fixture', principal=self.worker, idempotency_key='version')
        self.assertEqual(path.read_bytes(), original)

    def test_declared_mutation_requires_and_rechecks_real_claim(self):
        from codex_wake.background_jobs import BackgroundJobError
        from codex_wake.resource_claims import Claimant, ResourceClaims
        from codex_wake.process_signals import observe_process_exit
        store = BackgroundJobs(self.root)
        marker = self.workspace / 'mutation-marker'
        argv = [sys.executable, '-c', f"import pathlib; pathlib.Path({str(marker)!r}).write_text('effect')"]
        with self.assertRaises(BackgroundJobError):
            store.approve_command('mutation', argv, self.workspace, principal=self.operator,
                task_pin=self.pin, owner='worker', mutation=True)
        identity = observe_process_exit(os.getpid()).identity()
        claimant_clock = measurements.snapshot()
        claimant = Claimant('agent_' + 'a' * 32, str(self.workspace),
            dict(pid=identity['pid'], start_ticks=identity['start_time_ticks'], boot_id=identity['boot_id']),
            claimant_clock['utc']['upper'], clock_observation=claimant_clock)
        claims = ResourceClaims(self.root)
        claim = claims.claim('worktree', self.workspace, claimant)
        store.approve_command('mutation', argv, self.workspace, principal=self.operator,
            task_pin=self.pin, owner='worker', mutation=True,
            claim=(claim['claim_id'], claim['generation'], claimant), max_seconds=2)
        claims.release(claim['claim_id'], claim['generation'], claimant)
        from codex_wake.resource_claims import ResourceClaimError
        with self.assertRaises(ResourceClaimError):
            store.launch('mutation', principal=self.worker, idempotency_key='fenced', claimant=claimant)
        self.assertFalse(marker.exists())


    def test_public_mutation_profile_uses_fresh_host_claimant_at_each_launch(self):
        import argparse
        from codex_wake.background_job_commands import execute, register_parser
        from codex_wake.managed_inventory import ManagedInventory, Observation
        from codex_wake.resource_claims import Claimant, ResourceClaims
        from codex_wake.process_signals import observe_process_exit
        from codex_wake.background_jobs import BackgroundJobError
        identity = observe_process_exit(os.getpid()).identity()
        process = dict(pid=identity['pid'], start_ticks=identity['start_time_ticks'], boot_id=identity['boot_id'])
        def observer(_):
            clock = measurements.snapshot()
            return Observation('codex', 'fixture', 'worker', str(self.workspace), 'ready', clock['utc']['upper'],
                'native_metadata', process, [], {'inspect': 'supported'}, clock_observation=clock)
        inventory = ManagedInventory(self.root)
        agent = inventory.enroll(observer({}), operator=True)['agent']
        initial_clock = measurements.snapshot()
        claimant = Claimant(agent['managed_agent_id'], str(self.workspace), process, initial_clock['utc']['upper'], clock_observation=initial_clock)
        claims = ResourceClaims(self.root)
        claim = claims.claim('worktree', self.workspace, claimant)
        parser = argparse.ArgumentParser()
        register_parser(parser.add_subparsers(dest='command', required=True))
        marker = self.workspace / 'configured-mutation'
        argv = [sys.executable, '-c', f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ok')"]
        configure = parser.parse_args(['jobs', 'configure', '--profile', 'mutation', '--owner', 'worker',
            '--task-id', 'task-1', '--assignment-id', 'assignment-1', '--cwd', str(self.workspace),
            '--argv-json', json.dumps(argv), '--mutation', '--claim-id', claim['claim_id'],
            '--claim-generation', str(claim['generation']), '--managed-agent-id', agent['managed_agent_id']])
        profile = execute(configure, self.root, principal=self.operator, observer=observer)
        self.assertNotIn('observed_at', json.dumps(profile['command']['claim']))
        launch = parser.parse_args(['jobs', 'launch', '--profile', 'mutation', '--idempotency-key', 'fresh'])
        job = execute(launch, self.root, principal=self.worker, observer=observer)
        self.assertEqual(self.terminal(BackgroundJobs(self.root), job['job_id'])['status'], 'completed')
        self.assertEqual(marker.read_text(), 'ok')
        # A retained pre-correction profile fixture has an expired observation.
        # Its identity remains data; only a newly observed Claimant may execute.
        import hashlib
        catalog_path = self.root / 'background-jobs' / 'commands.json'
        catalog = json.loads(catalog_path.read_text())
        legacy = catalog['profiles']['mutation']
        stored_claim = legacy['command']['claim']
        stored_claim['claimant'] = dict(stored_claim.pop('owner'), observed_at=measurements.utc_time() - 60)
        legacy['sha256'] = hashlib.sha256(json.dumps(legacy['command'], sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        catalog_path.write_text(json.dumps(catalog))
        launch.idempotency_key = 'old-profile-fresh-observation'
        old_profile_job = execute(launch, self.root, principal=self.worker, observer=observer)
        self.assertEqual(self.terminal(BackgroundJobs(self.root), old_profile_job['job_id'])['status'], 'completed')
        self.assertLess(legacy['command']['claim']['claimant']['observed_at'], measurements.utc_time() - 30)
        stale_clock = measurements.snapshot()
        stale_clock['counter']['counter'] -= 40 * stale_clock['counter']['frequency']
        stale = Claimant(agent['managed_agent_id'], str(self.workspace), process, measurements.utc_time() - 40, clock_observation=stale_clock)
        with self.assertRaises(Exception):
            BackgroundJobs(self.root).launch('mutation', principal=self.worker,
                idempotency_key='stale', claimant=stale)
        with self.assertRaises(BackgroundJobError):
            BackgroundJobs(self.root).launch('mutation', principal=self.worker,
                idempotency_key='model-dict', claimant=dict(claimant.__dict__))
        from dataclasses import replace
        def changed_observer(arguments):
            return replace(observer(arguments), process=dict(process, start_ticks=process['start_ticks'] + 1))
        launch.idempotency_key = 'changed-generation'
        with self.assertRaises(BackgroundJobError):
            execute(launch, self.root, principal=self.worker, observer=changed_observer)
        inventory.set_enrollment(agent['managed_agent_id'], enabled=False)
        launch.idempotency_key = 'suppressed'
        with self.assertRaises(Exception):
            execute(launch, self.root, principal=self.worker, observer=observer)


if __name__ == '__main__':
    unittest.main()
