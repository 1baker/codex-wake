"""Explicit busy-input policies retain original native effects across retries."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

class SessionInputTests(unittest.TestCase):
    def test_queue_retains_native_acceptance_without_claiming_completion_or_replaying(self):
        from codex_wake.unified_session_input import SessionInputs
        with tempfile.TemporaryDirectory() as d:
            target=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread',process={'pid':os.getpid()})
            row=dict(thread_id='thread',target=target,endpoint='unix:///private.sock',codex_cmd=['codex'])
            calls=[]
            def request(row,method,args):
                calls.append(method)
                if method=='thread/read':return {'thread':{'id':'thread','status':{'type':'active'},'turns':[{'id':'active','status':'inProgress','items':[]}]}}
                if method=='thread/queue/add':return {'queuedSubmission':{'id':'queued','clientUserMessageId':args['clientUserMessageId'],'input':[dict(args['input'][0],text_elements=[])]}}
                raise AssertionError(method)
            with patch('codex_wake.unified_session_input.resolve',return_value=row):
                owner=SessionInputs(Path(d),request=request)
                first=owner.submit('thread:thread','Next task','queue','key')
                second=owner.submit('thread:thread','Next task','queue','key')
                self.assertEqual(first['result']['operation']['operation_id'],second['result']['operation']['operation_id'])
                self.assertEqual(first['result']['operation']['execution'],'queued')
                self.assertEqual(calls.count('thread/queue/add'),1)
                self.assertNotIn('turn/start',calls)
    def test_reject_busy_does_not_mutate_the_native_session(self):
        from codex_wake.unified_session_input import SessionInputs
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as d:
            row=dict(thread_id='t',target=dict(host='h',environment='e',uid=os.getuid(),home=d),endpoint='unix:///owned',codex_cmd=['codex'])
            calls=[]
            def request(row,method,args):calls.append(method);return {'thread':{'id':'t','status':{'type':'active'},'turns':[]}}
            with patch('codex_wake.unified_session_input.resolve',return_value=row):
                with self.assertRaisesRegex(InventoryError,'busy'):SessionInputs(Path(d),request=request).submit('thread:t','hello','reject','key')
                self.assertEqual(calls,['thread/read'])

    def test_steer_requires_the_original_active_turn_and_never_falls_back_when_idle(self):
        from codex_wake.unified_session_input import SessionInputs
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as d:
            target=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread')
            row=dict(thread_id='thread',target=target,endpoint='unix:///owned',codex_cmd=['codex'])
            state={'active':True,'reads':0}
            calls=[]
            def request(row,method,args):
                calls.append((method,args))
                if method=='thread/read':
                    return {'thread':{'id':'thread','status':{'type':'active' if state['active'] else 'idle'},'turns':[dict(id='original',status='inProgress' if state['active'] else 'completed',items=[])]}}
                if method=='turn/steer':return {'turnId':args['expectedTurnId']}
                raise AssertionError(method)
            with patch('codex_wake.unified_session_input.resolve',return_value=row):
                owner=SessionInputs(Path(d),request=request)
                result=owner.submit('thread:thread','New detail','steer','steer-one')['result']['operation']
                self.assertEqual(result['result']['turn_id'],'original')
                owner.submit('thread:thread','New detail','steer','steer-one')
                self.assertEqual(sum(m=='turn/steer' for m,a in calls),1)
                state['active']=False
                with self.assertRaises(InventoryError):owner.submit('thread:thread','Other detail','steer','steer-idle')
                self.assertNotIn('turn/start',[m for m,a in calls])

    def test_interrupt_then_submit_waits_for_confirmed_original_idle_and_starts_once(self):
        from codex_wake.unified_session_input import SessionInputs
        with tempfile.TemporaryDirectory() as d:
            target=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread')
            row=dict(thread_id='thread',target=target,endpoint='unix:///owned',codex_cmd=['codex'])
            state={'idle':False,'started':None}
            calls=[]
            def request(row,method,args):
                calls.append((method,args))
                if method=='thread/read':
                    turns=[dict(id='original',status='interrupted' if state['idle'] else 'inProgress',items=[])]
                    if state['started']:
                        turns.append(dict(id='new-turn',status='completed',items=[dict(type='userMessage',clientId=state['started'],content=[dict(type='text',text='Next',text_elements=[])]),dict(type='agentMessage',phase='final_answer',text='Finished')]))
                    return {'thread':dict(id='thread',status={'type':'idle' if state['idle'] else 'active'},turns=turns)}
                if method=='turn/interrupt':return {}
                if method=='turn/start':state['started']=args['clientUserMessageId'];raise OSError('native start reply lost after acceptance')
                raise AssertionError(method)
            with patch('codex_wake.unified_session_input.resolve',return_value=row):
                owner=SessionInputs(Path(d),request=request)
                first=owner.submit('thread:thread','Next','interrupt_then_submit','one')['result']['operation']
                identifier=first['operation_id']
                owner.result(identifier)
                self.assertNotIn('turn/start',[m for m,a in calls])
                state['idle']=True
                owner.result(identifier)
                self.assertEqual(sum(m=='turn/start' for m,a in calls),1)
                final=SessionInputs(Path(d),request=request).result(identifier)['result']['operation']
                self.assertEqual(final['execution'],'completed')
                self.assertEqual(final['answer']['text'],'Finished')
                owner.result(identifier)
                self.assertEqual(sum(m=='turn/interrupt' for m,a in calls),1)
                self.assertEqual(sum(m=='turn/start' for m,a in calls),1)
                self.assertEqual(state['started'],identifier+'.after-interrupt')

    def test_lost_idle_start_is_never_reinterpreted_as_an_interrupt_continuation(self):
        from codex_wake.unified_session_input import SessionInputs
        with tempfile.TemporaryDirectory() as d:
            target=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread')
            row=dict(thread_id='thread',target=target,endpoint='unix:///owned',codex_cmd=['codex'])
            calls=[]
            def request(row,method,args):
                calls.append(method)
                if method=='thread/read':return {'thread':dict(id='thread',status={'type':'idle'},turns=[])}
                if method=='turn/start':raise OSError('accepted but reply and history currently unavailable')
                raise AssertionError(method)
            with patch('codex_wake.unified_session_input.resolve',return_value=row):
                owner=SessionInputs(Path(d),request=request)
                value=owner.submit('thread:thread','Next','interrupt_then_submit','one')['result']['operation']
                self.assertEqual(value['phase'],'uncertain')
                owner.result(value['operation_id'])
                owner.result(value['operation_id'])
                self.assertEqual(calls.count('turn/start'),1)
                self.assertNotIn('turn/interrupt',calls)

    def test_lost_observation_preserves_original_input_without_retrying_effect(self):
        from codex_wake.unified_session_input import SessionInputs
        with tempfile.TemporaryDirectory() as d:
            target=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread')
            row=dict(thread_id='thread',target=target,endpoint='unix:///owned',codex_cmd=['codex'])
            fail=[False]
            calls=[]
            def request(row,method,args):
                calls.append(method)
                if method=='thread/read':
                    if fail[0]:raise OSError('observation connection lost')
                    return {'thread':dict(id='thread',status={'type':'active'},turns=[dict(id='active',status='inProgress',items=[])])}
                if method=='thread/queue/add':return {'queuedSubmission':dict(id='q',clientUserMessageId=args['clientUserMessageId'],input=args['input'])}
                raise AssertionError(method)
            with patch('codex_wake.unified_session_input.resolve',return_value=row):
                owner=SessionInputs(Path(d),request=request)
                identifier=owner.submit('thread:thread','Next','queue','one')['result']['operation']['operation_id']
                fail[0]=True
                result=owner.result(identifier)['result']['operation']
                self.assertEqual(result['operation_id'],identifier)
                self.assertEqual(result['execution'],'unknown')
                self.assertEqual(calls.count('thread/queue/add'),1)
