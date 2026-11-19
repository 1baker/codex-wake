"""Cross-action public policy convergence, including fresh-process readback (#325)."""
from contextlib import redirect_stdout
from io import StringIO
import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.a2a_bus import BusStore
from codex_wake.cli import run


THREAD = '00000000-0000-7000-8000-000000000325'
UTC_BOUNDS = (1800000000, 1800000001)
# Contract matrix is deliberately independent of the implementation's catalog.
DEFAULTS = {
    'session.inspect': 'allow', 'refresh.self': 'allow',
    'refresh.connection': 'allow', 'refresh.shared': 'approval_required',
    'handoff.self': 'allow', 'resume.self': 'allow',
    'enforcement.enroll': 'allow', 'enforcement.increase': 'approval_required',
    'enforcement.disable': 'approval_required', 'enforcement.recover': 'approval_required',
    'a2a.send': 'allow', 'a2a.receive': 'allow', 'a2a.claim': 'allow', 'a2a.reply': 'allow',
    'wake.background': 'allow', 'wake.existing_tab': 'allow',
    'wake.new_tab': 'allow', 'wake.fresh_task': 'allow',
}


class PermissionConvergenceTests(unittest.TestCase):
    def setUp(self):
        clock = patch('codex_wake.measurements.utc_bounds', return_value=UTC_BOUNDS)
        clock.start()
        self.addCleanup(clock.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'common'
        self.bus, self.capability = BusStore.configure(self.base / 'bus')
        self.policy = self.base / 'policy.json'

    def cli(self, *args):
        output = StringIO()
        with redirect_stdout(output):
            code = run(['--wake-root', str(self.root), 'permissions', *args,
                        '--bus-root', str(self.bus.root), '--operator-capability',
                        str(self.capability), '--json'])
        self.assertEqual(code, 0, output.getvalue())
        return json.loads(output.getvalue())

    def configure(self, policy, revision):
        self.policy.write_text(json.dumps(policy))
        self.policy.chmod(0o600)
        return self.cli('configure', '--file', str(self.policy),
                        '--expected-revision', str(revision))

    def fresh_mcp(self, root):
        # Public CommandRunner in a new OS process, with verified native metadata;
        # this is source/subprocess evidence, never installed-runtime proof.
        script = '''
import json,sys
from pathlib import Path
from unittest.mock import patch
from codex_wake.mcp_server import CommandRunner
clock=patch('codex_wake.measurements.utc_bounds',return_value=json.loads(sys.argv[4]))
clock.start()
thread=sys.argv[2]
meta=dict(threadId=thread,sessionId=thread,callId='convergence',**{
    'x-codex-turn-metadata':dict(thread_id=thread,session_id=thread,turn_id='turn')})
runner=CommandRunner(wake_root=Path(sys.argv[1]))
print(json.dumps({action:runner.call('wake_permissions_show',
    dict(caller_thread_id=thread,action=action),native_context=meta)
    for action in json.loads(sys.argv[3])}))
'''
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        env.pop('CODEX_WAKE_STABLE_TIME_CONFIG', None)
        for key in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME'):
            env[key] = str(self.base / key)
        result = subprocess.run([sys.executable, '-c', script, str(root), THREAD,
                                 json.dumps(list(DEFAULTS)), json.dumps(UTC_BOUNDS)], env=env, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_matrix(self, values, expected, revision):
        self.assertEqual(set(values), set(DEFAULTS))
        for action, outcome in expected.items():
            with self.subTest(action=action):
                decision, failed = values[action]
                self.assertFalse(failed, decision)
                self.assertEqual(decision['permission'], outcome)
                self.assertEqual(decision['revision'], revision)
                self.assertEqual(decision['readiness'], 'not_observed')

    def test_cli_adoption_and_revocation_converge_across_bound_roots_and_restart(self):
        self.configure({'version': 1}, 0)
        domain = self.base / 'controller-domain'
        self.cli('bind-domain', '--domain-root', str(domain))
        self.assert_matrix(self.fresh_mcp(domain), DEFAULTS, 1)
        # One operator revision fences every action, including sessions whose
        # execution roots carry no independent policy copy.
        self.configure({'version': 1, 'mandatory': list(DEFAULTS)}, 1)
        expected = dict.fromkeys(DEFAULTS, 'deny')
        self.assert_matrix(self.fresh_mcp(domain), expected, 2)
        self.assert_matrix(self.fresh_mcp(self.root), expected, 2)
        self.assertFalse((domain / 'session-permissions').exists())
        for action in DEFAULTS:
            value = self.cli('show', '--subject', THREAD, '--action', action)
            self.assertEqual(value['permission'], 'deny')
            self.assertEqual(value['revision'], 2)

    def test_expired_approvals_cannot_reappear_after_public_restart(self):
        reference=datetime.fromtimestamp(UTC_BOUNDS[0], timezone.utc)
        future=(reference+timedelta(days=365)).isoformat()
        past=(reference-timedelta(days=365)).isoformat()
        policy = {'version': 1, 'global': {'default': 'approval_required'},
                  'approvals': [dict(id=action, action=action, subject=THREAD,
                    scope='standing', issuer='operator', expires_at=future)
                    for action in DEFAULTS]}
        self.configure(policy, 0)
        self.assert_matrix(self.fresh_mcp(self.root), dict.fromkeys(DEFAULTS, 'allow'), 1)
        for action in DEFAULTS:
            value = self.cli('show', '--subject', THREAD, '--action', action)
            self.assertEqual(value['permission'], 'allow')
            self.assertEqual(value['approval_id'], action)
        for approval in policy['approvals']:
            approval['expires_at'] = past
        self.configure(policy, 1)
        self.assert_matrix(self.fresh_mcp(self.root),
                           dict.fromkeys(DEFAULTS, 'approval_required'), 2)
        for action in DEFAULTS:
            value = self.cli('show', '--subject', THREAD, '--action', action)
            self.assertEqual(value['permission'], 'approval_required')
            self.assertIsNone(value.get('approval_id'))

    def test_bound_independent_handoff_controller_observes_revocation_without_effect(self):
        """A restarted controller cannot bypass the common root's newer deny."""
        import hashlib
        from unittest.mock import patch
        from codex_wake.agent_handoff import poll_handoffs
        from codex_wake.agent_lifecycle import save
        self.configure({'version': 1}, 0)
        domain = self.base / 'lifecycle-domain'
        self.cli('bind-domain', '--domain-root', str(domain))
        journal = domain / 'lifecycle'
        journal.mkdir(mode=0o700, parents=True)
        goal = dict(objective='Continue task', status='paused', tokenBudget=100,
                    tokensUsed=20, timeUsedSeconds=10, createdAt=1)
        intent = dict(operation='handoff', source_thread_id=THREAD,
            launch=dict(app_server='unix:///fixture', codex_path='/bin/true', timeout=1),
            continuation={'activation': {'approved': True, 'max_poll_seconds': 1,
                                         'deadline_margin_seconds': 10}})
        receipt = dict(thread_id=THREAD, successor_thread_id='successor', intent=intent,
            fingerprint='fingerprint', state='awaiting_activation', continuation_deadline=2000,
            source_goal=dict(goal, threadId=THREAD), successor_goal=dict(goal, threadId='successor'),
            permission_context=dict(action='handoff.self', subject=THREAD, target=THREAD,
                task_id=None, operation_id='handoff', predecessor=None, trigger='manual'))
        path = journal / 'receipt.json'
        save(path, receipt)
        save(journal / ('owner-' + hashlib.sha256(THREAD.encode()).hexdigest() + '.json'),
             dict(intent_fingerprint='fingerprint', source_thread_id=THREAD,
                  successor_thread_id='successor', state='successor_prepared'))
        self.configure({'version': 1, 'mandatory': ['handoff.self']}, 1)
        methods = []
        def native(_endpoint, _codex, method, params, _timeout):
            methods.append(method)
            self.assertEqual(method, 'thread/goal/get', 'No activation/native effect permitted')
            return {'goal': dict(goal, threadId=params['threadId'])}
        with patch('codex_wake.agent_handoff.native_request', side_effect=native), \
             patch('codex_wake.native_clock.snapshot', return_value={'utc': {'upper': 1000, 'lower': 999}}):
            poll_handoffs(domain, supervision={'interval': 1})
        saved = json.loads(path.read_text())
        self.assertEqual(saved['state'], 'blocked')
        self.assertEqual(saved['reason'], 'permission_deny')
        self.assertEqual(methods, ['thread/goal/get', 'thread/goal/get'])
        self.assertEqual(saved['source_goal']['tokensUsed'], 20)
        self.assertEqual(saved['source_goal']['timeUsedSeconds'], 10)
        self.assertEqual(saved['continuation_deadline'], 2000)
