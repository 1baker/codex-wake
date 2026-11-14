"""Existing-turn observations through the local controller, without model input."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.local_control_service import LocalOperations


class ExistingTurnObservationTests(unittest.TestCase):
    def test_any_existing_turn_is_observed_without_resume_or_submission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = dict(uid=os.getuid(), home=str(root), process=dict(pid=os.getpid()),
                          conversation_id='conversation', generation='original')
            row = dict(thread_id='conversation', target=target, endpoint='unix:///owned.sock', codex_cmd=['codex'])
            turn = dict(id='human-turn', status='inProgress', items=[dict(id='answer', type='agentMessage', phase='final_answer', text='Partial')])
            calls = []
            def request(endpoint, command, method, params, timeout, **kwargs):
                calls.append((method, params))
                return {'thread': {'id': 'conversation', 'turns': [turn]}}
            with patch('codex_wake.local_session_observation.resolve', return_value=row), patch('codex_wake.local_session_observation.native_request', side_effect=request):
                owner = LocalOperations(root)
                attached = owner.execute('local.observe', dict(selector='thread:conversation', turn_id='human-turn', idempotency_key='watch-one'))
                identifier = attached['result']['observation_id']
                first = owner.execute('local.observation.output', dict(observation_id=identifier))['result']
                self.assertFalse(first['terminal'])
                self.assertFalse(first['capabilities']['live_notification_stream'])
                self.assertTrue(first['retention']['history_gap'])
                self.assertEqual(first['snapshot']['status'], 'inProgress')
                self.assertEqual(first['events'][0]['provenance'], 'native_thread_snapshot')
                cursor = first['next_cursor']
                turn.update(status='completed', items=[dict(id='answer', type='agentMessage', phase='final_answer', text='Done.')])
                finished = LocalOperations(root).execute('local.observation.output', dict(observation_id=identifier, cursor=cursor))['result']
                self.assertTrue(finished['terminal'])
                self.assertEqual(finished['answer']['text'], 'Done.')
                self.assertTrue(any(e['kind'] == 'turn/completed' for e in finished['events']))
                replay = owner.execute('local.observe', dict(selector='thread:conversation', turn_id='human-turn', idempotency_key='watch-one'))
                self.assertEqual(replay['result']['observation_id'], identifier)
                self.assertEqual({method for method, _ in calls}, {'thread/read'})
                self.assertTrue(all(params['threadId'] == 'conversation' for _, params in calls))

    def test_retention_gaps_and_cancellation_never_interrupt_the_turn(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = dict(uid=os.getuid(), home=str(root), process=dict(pid=os.getpid()), conversation_id='conversation')
            row = dict(thread_id='conversation', target=target, endpoint='unix:///owned.sock', codex_cmd=['codex'])
            turn = dict(id='peer-turn', status='inProgress', items=[dict(id='tool', type='mcpToolCall', name='lookup', status='running'), dict(id='private', type='reasoning', text='hidden')])
            calls = []
            def request(endpoint, command, method, params, timeout, **kwargs):
                calls.append(method)
                return {'thread': {'id': 'conversation', 'turns': [turn]}}
            with patch('codex_wake.local_session_observation.resolve', return_value=row), patch('codex_wake.local_session_observation.native_request', side_effect=request):
                owner = LocalOperations(root)
                identifier = owner.execute('local.observe', dict(selector='thread:conversation', turn_id='peer-turn', max_events=1))['result']['observation_id']
                turn['items'][0]['status'] = 'completed'
                value = owner.execute('local.observation.output', dict(observation_id=identifier))['result']
                self.assertTrue(value['retention']['cursor_gap'])
                self.assertTrue(value['retention']['truncated'])
                self.assertEqual(value['snapshot']['items'], [dict(id='tool', type='mcpToolCall', name='lookup', status='completed')])
                cancelled = owner.execute('local.observation.cancel', dict(observation_id=identifier))['result']
                self.assertFalse(cancelled['turn_cancelled'])
                count = len(calls)
                again = owner.execute('local.observation.output', dict(observation_id=identifier))['result']
                self.assertEqual(again['status'], 'cancelled')
                self.assertEqual(len(calls), count)
                self.assertEqual(set(calls), {'thread/read'})

    def test_stale_target_and_revoked_content_right_are_rechecked_on_each_page(self):
        from codex_wake.local_session_observation import SessionObservations
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = dict(uid=os.getuid(), home=str(root), process=dict(pid=os.getpid()), conversation_id='conversation')
            row = dict(thread_id='conversation', target=target, endpoint='unix:///owned.sock', codex_cmd=['codex'])
            allowed = [True]
            def authorize(target, capability):
                self.assertEqual(capability, 'content')
                if not allowed[0]:
                    raise InventoryError('permission_denied', 'content access revoked')
            with patch('codex_wake.local_session_observation.resolve', return_value=row) as resolver, patch('codex_wake.local_session_observation.native_request', return_value={'thread': {'id':'conversation', 'turns':[dict(id='peer-turn', status='inProgress', items=[])]}}) as reader:
                owner = SessionObservations(root, authorize=authorize)
                identifier = owner.observe('thread:conversation', 'peer-turn')['result']['observation_id']
                allowed[0] = False
                calls = reader.call_count
                with self.assertRaisesRegex(InventoryError, 'revoked'):
                    owner.output(identifier)
                self.assertEqual(reader.call_count, calls)
                allowed[0] = True
                resolver.side_effect = InventoryError('stale_target', 'original native peer replaced')
                with self.assertRaisesRegex(InventoryError, 'replaced'):
                    owner.output(identifier)
                self.assertEqual(reader.call_count, calls)

    def test_snapshot_content_is_bounded_without_claiming_complete_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = dict(uid=os.getuid(), home=str(root), process=dict(pid=os.getpid()), conversation_id='conversation')
            row = dict(thread_id='conversation', target=target, endpoint='unix:///owned.sock', codex_cmd=['codex'])
            items = [dict(id=str(i), type='agentMessage', phase='final_answer', text='x' * 32768) for i in range(4)]
            with patch('codex_wake.local_session_observation.resolve', return_value=row), patch('codex_wake.local_session_observation.native_request', return_value={'thread': {'id':'conversation', 'turns':[dict(id='peer-turn', status='completed', items=items)]}}):
                owner = LocalOperations(root)
                identifier = owner.execute('local.observe', dict(selector='thread:conversation', turn_id='peer-turn'))['result']['observation_id']
                value = owner.execute('local.observation.output', dict(observation_id=identifier))['result']
                self.assertLessEqual(sum(len(i.get('text','').encode()) for i in value['snapshot']['items']), 32768)
                self.assertTrue(value['snapshot']['truncated'])
                self.assertFalse(value['retention']['history_complete'])

    def test_unavailable_native_observation_is_not_reported_as_work_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = dict(uid=os.getuid(), home=str(root), process=dict(pid=os.getpid()), conversation_id='conversation')
            row = dict(thread_id='conversation', target=target, endpoint='unix:///owned.sock', codex_cmd=['codex'])
            with patch('codex_wake.local_session_observation.resolve', return_value=row), patch('codex_wake.local_session_observation.native_request', side_effect=OSError('connection lost')):
                attached = LocalOperations(root).execute('local.observe', dict(selector='thread:conversation', turn_id='peer-turn'))['result']
                self.assertEqual(attached['status'], 'unavailable')
                self.assertFalse(attached['terminal'])
                self.assertEqual(attached['execution'], 'unknown')

    def test_cancelling_observation_does_not_wait_for_a_blocked_native_read(self):
        import threading
        from codex_wake.local_session_observation import SessionObservations
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = dict(uid=os.getuid(), home=str(root), process=dict(pid=os.getpid()), conversation_id='conversation')
            row = dict(thread_id='conversation', target=target, endpoint='unix:///owned.sock', codex_cmd=['codex'])
            entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
            blocked = [False]
            def request(*args, **kwargs):
                if blocked[0]:
                    entered.set()
                    release.wait(3)
                return {'thread': {'id':'conversation', 'turns':[dict(id='peer-turn', status='inProgress', items=[])]}}
            with patch('codex_wake.local_session_observation.resolve', return_value=row), patch('codex_wake.local_session_observation.native_request', side_effect=request):
                owner = SessionObservations(root)
                identifier = owner.observe('thread:conversation', 'peer-turn')['result']['observation_id']
                blocked[0] = True
                reader = threading.Thread(target=lambda: owner.output(identifier))
                reader.start()
                self.assertTrue(entered.wait(1))
                def cancel():
                    owner.cancel(identifier)
                    cancelled.set()
                closer = threading.Thread(target=cancel)
                closer.start()
                try:
                    self.assertTrue(cancelled.wait(.5), 'read-only observation cancellation waited on native I/O')
                finally:
                    release.set()
                    reader.join(3)
                    closer.join(3)
                self.assertEqual(owner.output(identifier)['result']['status'], 'cancelled')
