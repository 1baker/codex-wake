"""Public caller seams preserve exact scope, authority and frozen intent."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.mcp_server import CommandRunner, SPECS
from codex_wake.records import all_records

THREAD = '00000000-0000-7000-8000-000000000315'
META = dict(threadId=THREAD, sessionId=THREAD, callId='call-315',
            **{'x-codex-turn-metadata': dict(thread_id=THREAD, session_id=THREAD, turn_id='turn-315')})


class HarnessCallerTests(unittest.TestCase):
    def test_inventory_main_cli_and_mcp_share_suppression_and_identity(self):
        from codex_wake.managed_inventory import Observation
        import time
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample = Observation('codex', 'codex:fixture', THREAD, str(root), 'ready', time.time(),
                                 'native_metadata', dict(pid=123, start_ticks=42, boot_id='boot-a'),
                                 [dict(pane_id='%1', window_id='@1')], {'inspect': 'supported'})
            output = io.StringIO()
            with patch('codex_wake.managed_inventory_commands.RuntimeObserver.__call__', return_value=sample), contextlib.redirect_stdout(output):
                code = run(['--wake-root', str(root), 'agents', 'enroll', '--operator', '--conversation-id', THREAD, '--json'])
            self.assertEqual(code, 0, output.getvalue())
            enrolled = json.loads(output.getvalue())
            runner = CommandRunner(wake_root=root)
            with patch('codex_wake.managed_inventory_commands.RuntimeObserver.__call__', return_value=sample):
                same, failed = runner.call('wake_agents_enroll', dict(runtime='codex', conversation_id=THREAD), native_context=META)
            self.assertFalse(failed, same)
            self.assertEqual(same['agent']['managed_agent_id'], enrolled['agent']['managed_agent_id'])
            identity = same['agent']['managed_agent_id']
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(['--wake-root', str(root), 'agents', 'unenroll', '--operator', '--managed-agent-id', identity]), 0)
            with patch('codex_wake.managed_inventory_commands.RuntimeObserver.__call__', return_value=sample):
                suppressed, failed = CommandRunner(wake_root=root).call('wake_agents_enroll',
                    dict(runtime='codex', conversation_id=THREAD), native_context=META)
            self.assertFalse(failed, suppressed)
            self.assertEqual(suppressed['status'], 'suppressed')
            self.assertFalse(suppressed['agent']['binding_current'])

    def test_brief_main_cli_and_native_mcp_admit_same_approved_revision(self):
        from codex_wake.a2a_bus import BusStore
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bus, operator = BusStore.configure(root / 'bus')
            wake = root / 'wake'
            content = dict(objective='Implement approved packet', phase='implementation',
                           non_goals=['No release'], acceptance=['Public result'], context=[],
                           workspace=str(root), allocation_ref='allocation-existing', permission_ref='profile-existing')
            def cli(verb, *extra):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = run(['--wake-root', str(wake), 'task-briefs', verb, '--task-id', 'task-315',
                                  '--bus-root', str(bus.root), '--operator-capability', str(operator), *extra, '--json'])
                self.assertEqual(result, 0, output.getvalue())
                return json.loads(output.getvalue())
            cli('propose', '--brief-json', json.dumps(content))
            cli('approve', '--revision', '1')
            runner = CommandRunner(wake_root=wake)
            with patch('codex_wake.harness_mcp.native_workspace', return_value=root):
                value, failed = runner.call('wake_task_briefs_admit', dict(caller_thread_id=THREAD,
                    task_id='task-315', assignment_id='step-1'), native_context=META)
                self.assertFalse(failed, value)
                self.assertEqual(value['pin']['revision'], 1)
                denied, failed = runner.call('wake_task_briefs_approve', dict(caller_thread_id=THREAD,
                    task_id='task-315', revision=1), native_context=META)
                self.assertTrue(failed)
                self.assertEqual(denied['error']['code'], 'authority_denied')
                lost, failed = runner.call('wake_task_briefs_admit', dict(caller_thread_id=THREAD,
                    task_id='task-315', assignment_id='step-1'), native_context=None)
                self.assertTrue(failed)
            content['objective'] = 'Changed later scope'
            cli('propose', '--brief-json', json.dumps(content))
            cli('approve', '--revision', '2')
            with patch('codex_wake.harness_mcp.native_workspace', return_value=root):
                original, failed = runner.call('wake_task_briefs_admit', dict(caller_thread_id=THREAD,
                    task_id='task-315', assignment_id='step-1'), native_context=META)
            self.assertFalse(failed, original)
            self.assertEqual(original['pin']['revision'], 1)

    def test_worker_cannot_admit_later_revision_outside_its_workspace(self):
        from codex_wake.task_briefs import TaskBriefStore, BriefAuthority
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a, b = root / 'A', root / 'B'
            a.mkdir(); b.mkdir()
            store = TaskBriefStore(root / 'wake')
            operator = BriefAuthority('operator:test', 'operator')
            for workspace in (a, b):
                content = dict(objective='Work', phase='implementation', non_goals=['Release'],
                    acceptance=['Done'], context=[], workspace=str(workspace),
                    allocation_ref='existing', permission_ref='existing')
                proposal = store.propose('task', content, authority=operator)
                store.approve('task', proposal['revision'], authority=operator)
            runner = CommandRunner(wake_root=root / 'wake')
            with patch('codex_wake.harness_mcp.native_workspace', return_value=a):
                value, failed = runner.call('wake_task_briefs_admit', dict(caller_thread_id=THREAD,
                    task_id='task', assignment_id='step'), native_context=META)
            self.assertTrue(failed, value)
            self.assertEqual(value['error']['code'], 'authority_denied')
            with patch('codex_wake.harness_mcp.native_workspace', return_value=a):
                for tool, extra in [('wake_task_briefs_inspect', {}),
                                    ('wake_task_briefs_admit', dict(assignment_id='explicit', revision=2))]:
                    value, failed = runner.call(tool, dict(caller_thread_id=THREAD, task_id='task', **extra), native_context=META)
                    self.assertTrue(failed, value)
                value, failed = runner.call('wake_task_briefs_admit', dict(caller_thread_id=THREAD,
                    task_id='task', assignment_id='allowed', revision=1), native_context=META)
                self.assertFalse(failed, value)
                self.assertEqual(value['pin']['revision'], 1)
                value, failed = runner.call('wake_task_briefs_pin', dict(caller_thread_id=THREAD,
                    task_id='task', assignment_id='allowed'), native_context=META)
                self.assertFalse(failed, value)
            with patch('codex_wake.harness_mcp.native_workspace', return_value=b):
                value, failed = runner.call('wake_task_briefs_pin', dict(caller_thread_id=THREAD,
                    task_id='task', assignment_id='allowed'), native_context=META)
                self.assertTrue(failed, value)
                value, failed = runner.call('wake_task_briefs_admit', dict(caller_thread_id=THREAD,
                    task_id='task', assignment_id='allowed', revision=1), native_context=META)
                self.assertTrue(failed, value)

    def test_only_host_delegation_can_promote_native_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / 'host.json'
            policy.write_text(json.dumps(dict(version=1, controllers={THREAD: ['task-1']})))
            policy.chmod(0o600)
            runner = CommandRunner(wake_root=root / 'wake', harness_policy=policy)
            content = dict(objective='Check fixture', phase='review', non_goals=['No release'], acceptance=['Checked'],
                           context=[], workspace=str(root), allocation_ref='existing', permission_ref='existing')
            value, failed = runner.call('wake_task_briefs_propose', dict(caller_thread_id=THREAD,
                task_id='task-1', brief=content), native_context=META)
            self.assertFalse(failed, value)
            value, failed = runner.call('wake_task_briefs_approve', dict(caller_thread_id=THREAD,
                task_id='task-1', revision=1), native_context=META)
            self.assertFalse(failed, value)
            invalid, failed = runner.call('wake_task_briefs_approve', dict(caller_thread_id=THREAD,
                task_id='task-1', revision=1, role='operator'), native_context=META)
            self.assertTrue(failed)
            self.assertEqual(invalid['error']['code'], 'invalid_argument')

    def test_native_registration_requires_host_metadata_and_preserves_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = CommandRunner(wake_root=root)
            body = dict(caller_thread_id=THREAD, trigger='1m', prompt='Continue', idempotency_key='native-mcp', session_mode='background',
                        wake_lifetime='conversation', owner_end='hold', recipient_startup='background_saved')
            denied, failed = runner.call('wake_native_after', body)
            self.assertTrue(failed)
            self.assertFalse(all_records(root))
            with patch('codex_wake.sessions.observe', return_value={'complete':False,'sessions':[]}), patch('codex_wake.app_server.resolve_codex_cmd', return_value=sys.executable), patch(
                    'codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None}):
                value, failed = runner.call('wake_native_after', body, native_context=META)
            self.assertFalse(failed, value)
            self.assertEqual(value['requires_worker_schema'], 8)
            record = all_records(root)[0].record
            self.assertEqual(record['wake_policy']['owner'], dict(kind='conversation', id='codex:' + THREAD))
            self.assertEqual(record['wake_policy']['startup'], 'background_saved')
            self.assertEqual(record['target']['resume_policy'], 'same_thread')

    def test_native_registration_survives_detached_mcp_cwd_without_duplicate_wakes(self):
        import errno
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'native-workspace'
            workspace.mkdir()
            runner = CommandRunner(wake_root=root / 'wake', app_server='unix:///fixture.sock')
            body = dict(caller_thread_id=THREAD, trigger='1m', prompt='Read-only check',
                idempotency_key='detached-cwd', session_mode='background',
                wake_lifetime='persistent', recipient_startup='background_saved')
            with patch('os.getcwd', side_effect=OSError(errno.ENODEV, 'No such device')), patch(
                    'codex_wake.shared_app_server.SharedAppServerReader.read_thread',
                    return_value=dict(id=THREAD, cwd=str(workspace))), patch(
                    'codex_wake.shared_app_server.SharedAppServerReader.__enter__', lambda reader: reader), patch(
                    'codex_wake.shared_app_server.SharedAppServerReader.__exit__', return_value=None), patch(
                    'codex_wake.sessions.observe', return_value={'complete': False, 'sessions': []}), patch(
                    'codex_wake.app_server.resolve_codex_cmd', return_value=sys.executable), patch(
                    'codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None}):
                first, failed = runner.call('wake_native_after', body, native_context=META)
                self.assertFalse(failed, first)
                same, failed = runner.call('wake_native_after', body, native_context=META)
                self.assertFalse(failed, same)
                self.assertEqual(same['id'], first['id'])
                self.assertTrue(same['deduplicated'])
                denied, failed = runner.call('wake_native_after', body, native_context=None)
                self.assertTrue(failed, denied)

    def test_future_wakes_expose_original_due_and_delivery_window_without_claiming_monitoring(self):
        from datetime import datetime, UTC, timedelta
        origin = datetime(2030, 1, 1, tzinfo=UTC)
        clock = dict(utc=dict(status='network', sources=['fixture-a', 'fixture-b'],
            lower=origin.timestamp(), upper=origin.timestamp() + .2), counter=None)
        for delay, days in [('24h', 1), ('3650d', 3650)]:
            with self.subTest(delay=delay), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                runner = CommandRunner(wake_root=root)
                body = dict(caller_thread_id=THREAD, trigger=delay, ttl='24h', prompt='Read-only review',
                    idempotency_key='future-fixture', session_mode='reopen_live', wake_lifetime='persistent', recipient_startup='create_load_run')
                with patch('codex_wake.sessions.observe', return_value={'complete':False,'sessions':[]}), patch('codex_wake.app_server.resolve_codex_cmd', return_value=sys.executable), patch(
                        'codex_wake.native_clock.snapshot', return_value=clock):
                    value, failed = runner.call('wake_native_after', body, native_context=META)
                self.assertFalse(failed, value)
                due = origin + timedelta(days=days, microseconds=200000)
                self.assertEqual(value.get('due_at'), due.isoformat().replace('+00:00', 'Z'))
                self.assertEqual(value['expires_at'], (due + timedelta(days=1)).isoformat().replace('+00:00', 'Z'))
                self.assertFalse(value['armed'])
                self.assertEqual(value['scheduling_status'], 'retained_unmonitored')
                self.assertIn('monitor', value['next_action'].lower())
                record = all_records(root)[0].record
                self.assertEqual(record['predicate']['due_at'], value['due_at'])
                self.assertEqual(record['time_recovery']['reason'], 'not_due')

    def test_future_wake_requires_loop_worker_and_keeps_identity_when_monitor_arrives(self):
        from codex_wake.monitor import write_monitor_health
        clock = dict(utc=dict(status='network', sources=['fixture-a', 'fixture-b'],
            lower=1893456000, upper=1893456000.2), counter=None)
        with tempfile.TemporaryDirectory() as temporary, patch.dict('os.environ', {'XDG_STATE_HOME': temporary}):
            root = Path(temporary) / 'wake'
            runner = CommandRunner(wake_root=root)
            body = dict(caller_thread_id=THREAD, trigger='3650d', ttl='24h', prompt='Read-only review',
                idempotency_key='future-monitor-fixture', session_mode='background', wake_lifetime='persistent')
            write_monitor_health(wake_root=root, source='qualification-fixture', mode='once')
            with patch('codex_wake.sessions.observe', return_value={'complete':False,'sessions':[]}), patch('codex_wake.app_server.resolve_codex_cmd', return_value=sys.executable), patch(
                    'codex_wake.native_clock.snapshot', return_value=clock), patch(
                    'codex_wake.native_protocol.native_request', return_value={
                        'thread': {'id': THREAD, 'status': {'type': 'idle'}}}):
                first, failed = runner.call('wake_native_after', body, native_context=META)
                self.assertFalse(failed, first)
                self.assertFalse(first['armed'], 'a one-shot observation is not durable monitor ownership')
                write_monitor_health(wake_root=root, source='qualification-fixture', mode='loop')
                same, failed = runner.call('wake_native_after', body, native_context=META)
                self.assertFalse(failed, same)
            self.assertTrue(same['armed'])
            self.assertTrue(same['deduplicated'])
            self.assertEqual(same['id'], first['id'])
            self.assertEqual(same['due_at'], first['due_at'])
            self.assertEqual(len(all_records(root)), 1)

    def test_harness_tool_schemas_exclude_host_and_role_overrides(self):
        for name, spec in SPECS.items():
            if spec[0] not in ('agents', 'task-briefs', 'harness-native', 'harness-owner'):
                continue
            for forbidden in ('wake_root', 'harness_policy', 'operator', 'role', 'native_context', 'app_server'):
                self.assertNotIn(forbidden, spec[3], name)

    def test_caller_identity_cannot_assert_completion_but_can_reconcile_operator_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            body = dict(caller_thread_id=THREAD, owner_kind='conversation',
                        owner_id='codex:' + THREAD, event_id='finished-1')
            value, failed = CommandRunner(wake_root=root).call('wake_owner_complete', body, native_context=META)
            self.assertTrue(failed, value)
            self.assertIn('completion_evidence_required', value['error']['message'])
            self.assertFalse((root / 'wake-owners.json').exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(['--wake-root', str(root), 'wake-policy', 'owner-complete', '--operator',
                                      '--owner-kind', 'conversation', '--owner-id', 'codex:' + THREAD,
                                      '--event-id', 'finished-1']), 0)
            journal = (root / 'wake-owners.json').read_bytes()
            value, failed = CommandRunner(wake_root=root).call('wake_owner_complete', body, native_context=META)
            self.assertFalse(failed, value)
            self.assertTrue(value['deduplicated'])
            self.assertEqual((root / 'wake-owners.json').read_bytes(), journal)


if __name__ == '__main__':
    unittest.main()
