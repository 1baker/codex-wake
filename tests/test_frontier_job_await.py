"""Focused native job-result await integration; no provider submissions."""
import contextlib
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_wake.background_jobs import BackgroundJobs
from codex_wake.daemon import poll_once
from codex_wake.mcp_server import CommandRunner
from codex_wake.records import all_records
from codex_wake.session_permissions import PermissionStore, Principal
from codex_wake.task_briefs import BriefAuthority, TaskBriefStore
from tests.test_measurements import observation

THREAD = '00000000-0000-7000-8000-000000000336'
PEER = '00000000-0000-7000-8000-000000000337'
def fixture_clock():
    return observation(int(time.monotonic() * 1000), rate=0)


def metadata(thread):
    return dict(threadId=thread, sessionId=thread, callId='fixture-call', **{
        'x-codex-turn-metadata': dict(thread_id=thread, session_id=thread, turn_id='fixture-turn')})


class FrontierJobAwaitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / 'wake'
        self.workspace = base / 'workspace'
        self.workspace.mkdir()
        environment = patch.dict(os.environ, {
            'XDG_STATE_HOME': str(base / 'state'), 'XDG_CACHE_HOME': str(base / 'cache'),
            'XDG_CONFIG_HOME': str(base / 'config'), 'CODEX_WAKE_STABLE_TIME_CONFIG': ''})
        environment.start()
        self.addCleanup(environment.stop)
        clock = patch('codex_wake.measurements.snapshot', side_effect=fixture_clock)
        clock.start()
        self.addCleanup(clock.stop)
        original_popen = subprocess.Popen
        def launch(argv, *args, **kwargs):
            if argv[:4] == [sys.executable, '-m', 'codex_wake.background_jobs', '--supervise']:
                # Explicit fixture authority crosses only the existing owned
                # supervisor boundary; all subprocess options remain intact.
                bootstrap = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv.pop(1))
from tests.test_frontier_job_await import fixture_clock
from codex_wake import measurements
measurements.snapshot = fixture_clock
from codex_wake.background_jobs import _supervise
_supervise(Path(sys.argv[2]), sys.argv[3])
"""
                argv = [sys.executable, '-c', bootstrap, str(Path(__file__).resolve().parents[1]), *argv[3:]]
            return original_popen(argv, *args, **kwargs)
        supervisor = patch('codex_wake.background_jobs.subprocess.Popen', side_effect=launch)
        supervisor.start()
        self.addCleanup(supervisor.stop)
        self.operator = Principal('operator', 'operator')
        self.worker = Principal(THREAD, tasks=('task-job',))
        PermissionStore(self.root).configure({'version': 1, 'global': {'actions': {'job.launch': 'allow'}}},
            self.operator, expected_revision=0)
        briefs = TaskBriefStore(self.root)
        operator = BriefAuthority('operator', 'operator')
        briefs.propose('task-job', dict(objective='Await an owned bounded command', phase='fixture',
            non_goals=['No provider input'], acceptance=['Original result produces one owned wake'], context=[],
            workspace=str(self.workspace), allocation_ref='fixture', permission_ref='fixture'), authority=operator)
        briefs.approve('task-job', 1, authority=operator)
        briefs.admit('task-job', 'assignment-job', authority=BriefAuthority('native:' + THREAD,
            'worker', ('task-job',), workspace=str(self.workspace)))
        self.jobs = BackgroundJobs(self.root)
        self.jobs.approve_command('fixture', [sys.executable, '-c', "import time; time.sleep(.15); print('done')"],
            self.workspace, principal=self.operator, owner=THREAD,
            task_pin=briefs.assignment_pin('task-job', 'assignment-job'), max_seconds=2)
        self.job = self.jobs.launch('fixture', principal=self.worker, idempotency_key='one-job')
        self.runner = CommandRunner(wake_root=self.root, app_server='unix:///fixture-no-provider')

    def await_job(self, caller=THREAD, ttl='24h'):
        with patch('codex_wake.native_clock.snapshot', side_effect=fixture_clock), \
             patch('codex_wake.app_server.resolve_codex_cmd', return_value=sys.executable):
            return self.runner.call('wake_jobs_await', dict(caller_thread_id=caller,
                job_id=self.job['job_id'], ttl=ttl), native_context=metadata(caller))

    def test_native_await_retains_exact_owner_task_path_and_fires_after_job_completion_once(self):
        value, failed = self.await_job()
        self.assertFalse(failed, value)
        self.assertEqual(value['job']['job_id'], self.job['job_id'])
        records = all_records(self.root)
        self.assertEqual(len(records), 1)
        original = records[0].record
        self.assertEqual(original['predicate'], {'type': 'file_exists', 'path': self.job['result_path']})
        self.assertEqual(original['target']['thread_id'], THREAD)
        self.assertEqual(original['wake_policy']['lifetime'], 'task')
        self.assertEqual(original['wake_policy']['owner'], {'kind': 'task', 'id': 'task-job'})
        self.assertEqual(original['wake_policy']['owner_end'], 'retire')
        self.assertEqual(original['wake_policy']['permission_context']['subject'], THREAD)
        self.assertEqual(original['wake_policy']['permission_context']['task_id'], 'task-job')
        self.assertEqual(original['scheduling_intent']['ttl_seconds'], 86400)
        deadline = time.monotonic() + 5
        while self.jobs.inspect(self.job['job_id'])['status'] != 'completed' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.jobs.inspect(self.job['job_id'])['status'], 'completed')
        again, failed = self.await_job()
        self.assertFalse(failed, again)
        self.assertEqual(again['wake']['id'], original['id'])
        self.assertEqual(all_records(self.root)[0].record['scheduling_intent'], original['scheduling_intent'])
        with patch('codex_wake.native_clock.snapshot', side_effect=fixture_clock):
            first = poll_once(self.root, dispatch=False)
            second = poll_once(self.root, dispatch=False)
        self.assertEqual(first.fired, 1)
        self.assertEqual(second.fired, 0)
        self.assertEqual(all_records(self.root)[0].record['status'], 'firing')
        from codex_wake.cli import run
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(['--wake-root', str(self.root), 'wake-policy', 'owner-complete',
                '--operator', '--owner-kind', 'task', '--owner-id', 'task-job',
                '--event-id', 'fixture-owner-completed']), 0)
        with patch('codex_wake.native_clock.snapshot', side_effect=fixture_clock):
            poll_once(self.root, dispatch=False)
        retired = all_records(self.root)[0].record
        self.assertEqual(retired['status'], 'cancelled')
        self.assertEqual(retired['attempts'], 0)
        self.assertEqual(retired['scheduling_intent'], original['scheduling_intent'])
        self.assertEqual(self.jobs.inspect(self.job['job_id'])['result']['returncode'], 0)

    def test_foreign_caller_and_denied_wake_route_cannot_create_a_result_wake(self):
        value, failed = self.await_job(PEER)
        self.assertTrue(failed, value)
        self.assertEqual(all_records(self.root), [])
        PermissionStore(self.root).configure({'version': 1, 'mandatory': ['wake.background']},
            self.operator, expected_revision=1)
        value, failed = self.await_job()
        self.assertTrue(failed, value)
        self.assertEqual(all_records(self.root), [])


if __name__ == '__main__':
    unittest.main()
