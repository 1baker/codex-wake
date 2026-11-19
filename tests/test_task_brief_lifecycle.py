"""Approved brief pins reach the existing spawn and checkpoint caller seams."""
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from websockets.sync.server import unix_serve

from codex_wake.agent_lifecycle import spawn_command
from codex_wake.agent_handoff import handoff_command
from codex_wake.records import WakeError
from codex_wake.task_briefs import BriefAuthority, TaskBriefStore


class TaskBriefLifecycleTests(unittest.TestCase):
    def setUp(self):
        clock = patch('codex_wake.measurements.utc_bounds', return_value=(100, 101))
        clock.start()
        self.addCleanup(clock.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / 'wake'
        self.operator = BriefAuthority('operator:fixture', 'operator')
        self.content = dict(objective='Finish fixture', phase='implementation',
            non_goals=['Never deploy'], acceptance=['Expected public behavior'], context=[],
            workspace=str(self.workspace), allocation_ref='existing-allocation', permission_ref='worker')
        self.store = TaskBriefStore(self.root)
        self.store.propose('task-1', self.content, authority=self.operator)
        self.store.approve('task-1', 1, authority=self.operator)
        self.source = '00000000-0000-7000-8000-000000000159'
        self.profiles = self.workspace / 'profiles.json'
        self.endpoint = self.workspace / 'native.sock'
        self.profile = dict(cwd=str(self.workspace), app_server='unix://' + str(self.endpoint),
            codex_path='/bin/true', tmux_session='fixture', timeout=1)
        self.profiles.write_text(json.dumps(dict(version=1, profiles={'worker': self.profile},
            callers={self.source: ['worker']})))

    def spawn_args(self):
        return SimpleNamespace(profiles=self.profiles, profile='worker', caller_thread_id=self.source,
            intent='spawn-brief', name='worker', task='Run the approved checks',
            expires_at='2030-01-01T00:00:00Z', as_json=True,
            task_id='task-1', assignment_id='instruction-1', revision=None)

    def test_spawn_freezes_and_exposes_approved_scope_on_repeated_admission(self):
        endpoint = socket.socket(socket.AF_UNIX)
        endpoint.bind(str(self.endpoint))
        self.addCleanup(endpoint.close)
        args = self.spawn_args()
        def invoke():
            output = StringIO()
            with redirect_stdout(output), patch('codex_wake.native_clock.snapshot',
                    return_value={'utc': {'lower': 1893456001, 'upper': 1893456002}}):
                self.assertEqual(spawn_command(args, self.root), 5)
            return json.loads(output.getvalue())
        first = invoke()
        self.assertEqual(first['intent']['task_brief']['revision'], 1)
        self.assertIn('Never deploy', first['intent']['task'])
        self.assertIn('Expected public behavior', first['intent']['task'])
        self.store.propose('task-1', dict(self.content, objective='New approved objective'), authority=self.operator)
        self.store.approve('task-1', 2, authority=self.operator)
        repeated = invoke()
        self.assertEqual(repeated['fingerprint'], first['fingerprint'])
        self.assertEqual(repeated['intent']['task_brief']['revision'], 1)
        self.assertNotIn('New approved objective', repeated['intent']['task'])

    def test_preexisting_spawn_intent_keeps_original_assignment_on_upgrade(self):
        endpoint = socket.socket(socket.AF_UNIX)
        endpoint.bind(str(self.endpoint))
        self.addCleanup(endpoint.close)
        args = self.spawn_args()
        def invoke():
            output = StringIO()
            with redirect_stdout(output), patch('codex_wake.native_clock.snapshot',
                    return_value={'utc': {'lower': 1893456001, 'upper': 1893456002}}):
                self.assertEqual(spawn_command(args, self.root), 5)
            return json.loads(output.getvalue())
        saved = invoke()
        # Persisted version-1 fixture from the previous public spawn format.
        original = ('Assignment instructions, subject to the approved task brief:\n' + args.task
            + '\n\nAPPROVED_TASK_BRIEF=' + json.dumps(dict(pin=saved['intent']['task_brief'],
                content=self.content), sort_keys=True))
        saved['intent']['task'] = original
        saved.pop('dispatch')
        saved['fingerprint'] = hashlib.sha256(json.dumps(saved['intent'], sort_keys=True).encode()).hexdigest()
        path = self.root / 'lifecycle' / (hashlib.sha256(args.intent.encode()).hexdigest() + '.json')
        path.write_text(json.dumps(saved))
        self.assertEqual(invoke()['intent']['task'], original)
        args.task = 'A different assignment'
        with self.assertRaisesRegex(WakeError, 'different lifecycle assignment'):
            invoke()

    def test_unapproved_brief_cannot_reach_spawn_journal(self):
        self.store.propose('task-2', self.content, authority=self.operator)
        args = self.spawn_args()
        args.task_id = 'task-2'
        with self.assertRaises(WakeError) as denied:
            spawn_command(args, self.root)
        self.assertEqual(getattr(denied.exception, 'code', None), 'brief_unapproved')
        self.assertFalse((self.root / 'lifecycle').exists())

    def test_configured_spawn_keeps_the_existing_objective_allocation(self):
        instructions = self.workspace / 'instructions.md'
        instructions.write_text('Review the approved fixture only.')
        selection = dict(name='fixture', path=str(instructions))
        policy = dict(objective='Finish fixture', objective_id='existing-allocation',
            approval='operator fixture', started_at='2030-01-01T00:00:00Z')
        config = dict(version=1, profiles={'worker': self.profile}, callers={self.source: ['worker']},
            continuations={self.source: policy}, lifecycle_defaults=dict(handoff_writer=selection,
                preflight_reviewer=selection, session_token_limit=100, session_time_limit_seconds=100,
                objective_token_limit=1000, objective_time_limit_seconds=1000, max_correction_cycles=2))
        self.profiles.write_text(json.dumps(config))
        endpoint = socket.socket(socket.AF_UNIX)
        endpoint.bind(str(self.endpoint))
        self.addCleanup(endpoint.close)
        args = self.spawn_args()
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(spawn_command(args, self.root), 5)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt['reason'], 'resident_objective_supervisor_required')
        self.assertEqual(receipt['intent']['task_brief']['revision'], 1)
        self.assertEqual(receipt['intent']['continuation']['objective_id'], 'existing-allocation')

    def test_checkpoint_pin_is_validated_and_carried_without_re_admission(self):
        worker = BriefAuthority('native:' + self.source, 'worker', ('task-1',))
        self.store.admit('task-1', 'instruction-1', authority=worker)
        pin = self.store.assignment_pin('task-1', 'instruction-1')
        policy = dict(objective='Finish fixture', token_cap=1000, time_cap_seconds=100,
            tokens_before_source=0, seconds_before_source=0, approval='operator fixture',
            started_at='2030-01-01T00:00:00Z')
        self.profiles.write_text(json.dumps(dict(version=1, profiles={'worker': self.profile},
            callers={self.source: ['worker']}, continuations={self.source: policy})))
        checkpoint = dict(source_thread_id=self.source, objective='Finish fixture', authority='operator fixture',
            next_packet='Read the checkpoint', pending_obligations=[], repo=str(self.workspace),
            worktree=str(self.workspace), commit='a' * 40, dirty_work='No fixture changes',
            acceptance_remaining=['Expected public behavior'], evidence=['Native writer fixture'],
            pending_wakes=[], pending_messages=[], claim_holders=[], reply_route='original thread',
            hard_stops=['Original resource limits'], expires_at='2030-01-01T00:01:00Z',
            resources={k: policy[k] for k in ('token_cap', 'time_cap_seconds', 'tokens_before_source',
                                            'seconds_before_source', 'started_at')}, task_brief=pin)
        path = self.workspace / 'checkpoint.json'
        path.write_text(json.dumps(checkpoint))
        methods = []
        def handler(ws):
            for raw in ws:
                request = json.loads(raw)
                if 'id' not in request:
                    continue
                methods.append(request['method'])
                if request['method'] == 'initialize':
                    value = {'userAgent': 'fixture'}
                elif request['method'] == 'thread/goal/get':
                    value = {'goal': dict(threadId=self.source, objective='Finish fixture', status='paused',
                        tokenBudget=1000, timeUsedSeconds=12, createdAt=100, updatedAt=100)}
                else:
                    raise AssertionError('Unexpected effect ' + request['method'])
                ws.send(json.dumps(dict(id=request['id'], result=value)))
        server = unix_serve(handler, str(self.endpoint))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            args = SimpleNamespace(profiles=self.profiles, profile='worker', thread_id=self.source,
                checkpoint='checkpoint.json', checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                caller_thread_id=self.source, expires_at='2030-01-01T00:01:00Z', mode='new-tab',
                intent='handoff-brief', as_json=True)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(handoff_command(args, self.root), 5)
            receipt = json.loads(output.getvalue())
            self.assertEqual(receipt['intent']['task_brief'], pin)
            self.assertEqual(len(self.store.inspect('task-1')['admissions']), 1)
            checkpoint['task_brief'] = dict(pin, digest='f' * 64)
            path.write_text(json.dumps(checkpoint))
            args.checkpoint_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            before = list(methods)
            with self.assertRaises(WakeError):
                handoff_command(args, self.root)
            self.assertEqual(methods, before)
        finally:
            server.shutdown()
            thread.join(timeout=2)
