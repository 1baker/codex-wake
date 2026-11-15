"""Later authoritative completion corrects an earlier interrupted observation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from codex_wake.unified_session_input import SessionInputs

class NativeInputReconciliationTests(unittest.TestCase):
 def test_completed_native_turn_reconciles_retained_interruption_without_resubmit(self):
  with tempfile.TemporaryDirectory() as temporary:
   target=dict(host='h',environment='e',uid=os.getuid(),home=temporary,conversation_id='thread')
   row=dict(thread_id='thread',target=target,endpoint='unix:///owned',codex_cmd=['codex'])
   state=dict(status=None,client=None,unavailable=False,turn_id='turn',observed_client=None)
   calls=[]
   def request(row,method,args):
    calls.append(method)
    if method=='thread/queue/add':
     state['client']=args['clientUserMessageId']
     return dict(queuedSubmission=dict(id='queue',clientUserMessageId=state['client'],input=args['input']))
    if method=='thread/read':
     if state['unavailable']:raise OSError('observation unavailable')
     items=[dict(type='userMessage',clientId=state['observed_client'] or state['client'],content=[dict(type='text',text='reply')]),dict(type='agentMessage',phase='final_answer',text='answer')]
     turns=[dict(id=state['turn_id'],status=state['status'],items=items)] if state['status'] else []
     return dict(thread=dict(id='thread',status=dict(type='active'),turns=turns))
    raise AssertionError(method)
   with patch('codex_wake.unified_session_input.resolve',return_value=row):
    owner=SessionInputs(Path(temporary),request=request)
    identifier=owner.submit('thread:thread','reply','queue','one')['result']['operation']['operation_id']
    state['status']='interrupted'
    self.assertEqual(owner.result(identifier)['result']['operation']['execution'],'cancelled')
    self.assertEqual(owner.result(identifier)['result']['operation']['execution'],'cancelled')
    state['unavailable']=True
    self.assertEqual(owner.result(identifier)['result']['operation']['execution'],'cancelled')
    state['unavailable']=False
    state['status']='completed'
    state['turn_id']='other'
    self.assertEqual(owner.result(identifier)['result']['operation']['execution'],'cancelled')
    state['turn_id']='turn'
    state['observed_client']='other-client'
    self.assertEqual(owner.result(identifier)['result']['operation']['execution'],'cancelled')
    state['observed_client']=None
    result=owner.result(identifier)['result']['operation']
    self.assertEqual(result['execution'],'completed')
    self.assertEqual(result['answer']['text'],'answer')
    with owner.runtime.connect() as db:
     self.assertEqual(db.execute("SELECT count(*) FROM events WHERE operation_id=? AND event_key='native_completion_reconciled'",(identifier,)).fetchone()[0],1)
    reads=calls.count('thread/read')
    state['status']='interrupted'
    self.assertEqual(owner.result(identifier)['result']['operation']['execution'],'completed')
    self.assertEqual(calls.count('thread/read'),reads)
    self.assertEqual(calls.count('thread/queue/add'),1)
    self.assertNotIn('turn/start',calls)
