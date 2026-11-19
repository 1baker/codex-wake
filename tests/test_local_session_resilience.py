"""Faults at public operation seams over a real owned Unix protocol peer.

Provider-free wire injection is not installed native restart/interrupt acceptance.
#471 already protects text/cursor order, caller exit, timeout, and late completion.
"""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import unix_serve
from codex_wake.local_session_operations import LocalSessionControl
from codex_wake.local_session_events import TurnEvents


@contextlib.contextmanager
def peer(*,lost_ack=False,echo_id=True,busy=False,hold_ack=False,hold_observation=False,interrupt_reply='ack'):
    with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ):
        # Wire fixtures own no operator panes; inherit isolation in collectors.
        os.environ.pop('TMUX',None);os.environ['TMUX_TMPDIR']=directory
        root=Path(directory);home=root/'home';home.mkdir();endpoint='unix://'+str(root/'native.sock')
        accepted=threading.Event();finish=threading.Event();drop=threading.Event()
        state=dict(starts=[],interrupts=[],finish=finish,drop=drop,accepted=accepted,status='inProgress')
        ack=threading.Event();observation=threading.Event();release_observation=threading.Event()
        if not hold_ack:ack.set()
        if not hold_observation:release_observation.set()
        state.update(ack=ack,observation=observation,release_observation=release_observation)
        operations=[]
        def handler(ws):
            try:
                for raw in ws:
                    message=json.loads(raw)
                    if 'id' not in message:continue
                    method=message['method'];params=message.get('params',{})
                    if method=='initialize':result={'codexHome':str(home)}
                    elif method=='thread/loaded/list':result={'data':['one','unrelated'],'nextCursor':None}
                    elif method=='thread/read':
                        thread=params['threadId'];items=[]
                        if accepted.is_set() and thread=='one':
                            request=state['starts'][0]
                            user=dict(type='userMessage',id='question',content=request['input'])
                            if echo_id:user['clientId']=request.get('clientUserMessageId')
                            items=[user]
                            if finish.is_set():items += [dict(type='agentMessage',id='comment',phase='commentary',text='Working'),dict(type='agentMessage',id='answer',phase='final_answer',text='Retained answer')]
                        turn=dict(id='owned-turn',status=state['status'] if finish.is_set() else 'inProgress',items=items)
                        active=thread=='one' and (busy or (accepted.is_set() and not finish.is_set()))
                        result={'thread':dict(id=thread,cwd=str(root),status={'type':'active' if active else 'idle'},turns=[turn] if items else [])}
                        if echo_id=='duplicate' and items:result['thread']['turns'].append(dict(turn,id='another-turn'))
                        if params.get('includeTurns') and accepted.is_set() and hold_observation and not state.get('observation_once'):
                            state['observation_once']=True;observation.set();release_observation.wait(10)
                    elif method=='thread/resume':result={'thread':{'id':params['threadId']}}
                    elif method=='turn/start':
                        state['starts'].append(params);accepted.set()
                        if not ack.wait(10):return
                        if lost_ack:return
                        result={'turn':{'id':'owned-turn'}}
                    elif method=='turn/interrupt':
                        state['interrupts'].append(params)
                        if interrupt_reply=='stall':drop.wait(5);return
                        if interrupt_reply=='reject':
                            ws.send(json.dumps(dict(id=message['id'],error=dict(code=-32000,message='refused'))));continue
                        state['status']='interrupted';finish.set();result={}
                    else:raise AssertionError(method)
                    ws.send(json.dumps(dict(id=message['id'],result=result)))
                    if method=='turn/start':
                        def event(kind,**body):ws.send(json.dumps(dict(method=kind,params=dict(threadId='one',turnId='owned-turn',**body))))
                        event('turn/started',turn={'id':'owned-turn','status':'inProgress'})
                        event('item/agentMessage/delta',itemId='answer',delta='Retained ')
                        deadline=time.monotonic()+15
                        while not finish.wait(.01) and not drop.is_set() and time.monotonic()<deadline:pass
                        if drop.is_set():return
                        if not finish.is_set():return
                        if state['status']!='interrupted':event('item/completed',item={'id':'answer','type':'agentMessage','phase':'final_answer','text':'Retained answer'})
                        event('turn/completed',turn={'id':'owned-turn','status':state['status']});return
            except ConnectionClosed:pass
        with unix_serve(handler,str(root/'native.sock')) as server:
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            state.update(root=root,home=home,endpoint=endpoint,owner=LocalSessionControl(root),operations=operations,handler=handler)
            try:yield state
            finally:
                ack.set();release_observation.set();finish.set();drop.set();server.shutdown();worker.join(2)
                for identifier in operations:
                    metadata=TurnEvents(root).state(identifier);pid=metadata.get('pid');deadline=time.monotonic()+3
                    while pid and Path('/proc',str(pid)).exists() and time.monotonic()<deadline:time.sleep(.01)


def submit(state,key='intent'):
    value=state['owner'].prompt('thread:one','Bounded fixture prompt',key,endpoint=state['endpoint'])
    record=value['result']['operation'];state['operations'].append(record['operation_id']);return record


class SessionResilienceTests(unittest.TestCase):
    def test_result_and_output_recheck_authority_before_advisory_timeout_publication(self):
        from codex_wake import measurements
        from codex_wake.controller_auth import AuthError
        from codex_wake.daemon_commands import local_operator
        for method in ('result','output'):
            for loss in ('expiry','revocation'):
                with self.subTest(method=method,loss=loss),tempfile.TemporaryDirectory() as directory:
                    root=Path(directory);home=root/'home';home.mkdir()
                    owner=LocalSessionControl(root);authority=[100]
                    owner.runtime.now=lambda:authority[0]
                    target=dict(host='fixture',environment='linux',uid=os.getuid(),home=str(home))
                    with patch('codex_wake.measurements.utc_bounds',return_value=(100,100)):
                        actor=local_operator(target)
                        request=dict(operation_id='final-authority',idempotency_key='final-authority',
                            correlation_id='final-authority',binding='fixture',target=target)
                        owner.runtime.execute(actor,'sessions.prompt',dict(_request=request),authorize=lambda:actor,
                            dispatch=lambda *_:dict(answer='private retained result'))
                        calls=0
                        def clock():
                            nonlocal calls
                            calls+=1
                            if calls>=3:
                                if loss=='expiry':authority[0]=221
                                else:owner.runtime.revoke_grant(actor.grant_id,issuer=actor.issuer,resource=actor.resource)
                                return 2.0
                            return 0.0
                        with patch('codex_wake.local_session_operations.time.monotonic',side_effect=clock):
                            with self.assertRaises(AuthError):
                                getattr(owner,method)('final-authority',timeout=1)

    def test_positive_result_and_output_waits_do_not_require_counter(self):
        from codex_wake import measurements
        from codex_wake.daemon_commands import local_operator
        for method in ('result','output'):
            with self.subTest(method=method),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);home=root/'home';home.mkdir()
                owner=LocalSessionControl(root);owner.runtime.now=lambda:100
                target=dict(host='fixture',environment='linux',uid=os.getuid(),home=str(home))
                with patch('codex_wake.measurements.utc_bounds',return_value=(100,100)):
                    actor=local_operator(target)
                    request=dict(operation_id='retained',idempotency_key='retained',
                        correlation_id='retained',binding='fixture',target=target)
                    owner.runtime.execute(actor,'sessions.prompt',dict(_request=request),authorize=lambda:actor,
                        dispatch=lambda *_:dict(answer='retained'))
                    with patch('codex_wake.measurements.snapshot',side_effect=measurements.TimeUnavailable('auxiliary counter unavailable')):
                        positive=getattr(owner,method)('retained',timeout=1)
                        cached=getattr(owner,method)('retained',timeout=0)
                if method=='result':
                    self.assertEqual(positive['result']['operation']['phase'],'terminal')
                    self.assertEqual(cached['result']['operation']['phase'],'terminal')
                else:
                    self.assertTrue(positive['terminal'])
                    self.assertTrue(cached['terminal'])

    def test_collector_loses_clock_on_ack_keeps_unknown_without_prompt_replay(self):
        from codex_wake import local_session_events as events
        from codex_wake.measurements import TimeUnavailable
        for loss_at in ('ack','scope'):
            with peer() as state, contextlib.ExitStack() as clock:
                original=events.unix_connect
                @contextlib.contextmanager
                def connection(*args,**kwargs):
                    with original(*args,**kwargs) as ws:
                        class Wrapped:
                            def __getattr__(self,name):return getattr(ws,name)
                            def recv(self,**options):
                                raw=ws.recv(**options)
                                if loss_at=='ack' and json.loads(raw).get('id')==5:
                                    clock.enter_context(patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('lost at acknowledgement')))
                                return raw
                        yield Wrapped()
                publish=events.TurnEvents.publish_scope
                def publish_then_lose(store,*args):
                    publish(store,*args)
                    if loss_at=='scope':clock.enter_context(patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('lost after scope publication')))
                def run(root,identifier):
                    with patch.object(events,'unix_connect',connection), patch.object(events.TurnEvents,'publish_scope',publish_then_lose):events.collect(root,identifier)
                    retained=events.TurnEvents(root).runtime._load(identifier)
                    clock.close()
                    if retained['phase']=='uncertain':
                        from codex_wake.managed_inventory import InventoryError
                        raise InventoryError('uncertain_effect','retrieve original operation')
                    return retained.get('result')
                with patch.object(events,'launch',side_effect=run):
                    value=submit(state,'collector-lost-ack-clock')
                self.assertEqual(len(state['starts']),1)
                self.assertEqual(value['phase'],'uncertain')
                self.assertEqual(value['reason'],'uncertain_effect')
                self.assertEqual(TurnEvents(state['root']).state(value['operation_id'])['reason'],'stable_time_unavailable')
                self.assertEqual('protective_scope' in TurnEvents(state['root']).state(value['operation_id']),loss_at=='scope')
                self.assertIsNone(value.get('result'))
                clock.close()
                again=submit(state,'collector-lost-ack-clock')
                self.assertEqual(again['operation_id'],value['operation_id'])
                self.assertEqual(len(state['starts']),1)

    def test_launch_without_qualified_counter_refuses_before_detached_collector(self):
        from codex_wake.local_session_events import launch
        from codex_wake.measurements import TimeUnavailable
        with tempfile.TemporaryDirectory() as root, patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('unavailable')):
            with patch('codex_wake.local_session_events.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(TimeUnavailable,'unavailable'):
                    launch(root,'not-yet-started')
                spawn.assert_not_called()

    def test_private_revocation_interrupts_qualified_owned_turn_during_total_clock_loss_once(self):
        from codex_wake.measurements import TimeUnavailable
        with peer() as state:
            admitted=submit(state,'protective-clock-loss')
            identifier=admitted['operation_id']
            record=state['owner'].runtime._load(identifier)
            principal=record['principal']
            original_metadata=TurnEvents(state['root']).state(identifier)
            self.assertEqual(original_metadata['protective_scope_status'],'qualified')
            original_scope=original_metadata['protective_scope']
            with patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('all counter evidence lost')):
                outcome=state['owner'].runtime.revoke_grant(principal['grant_id'],issuer=principal['issuer'],resource=principal['resource'])
                self.assertEqual(state['interrupts'],[dict(threadId='one',turnId='owned-turn')])
                self.assertEqual(outcome['operations'][0]['cancellation'],'requested')
                state['owner'].runtime.revoke_grant(principal['grant_id'],issuer=principal['issuer'],resource=principal['resource'])
                self.assertEqual(len(state['interrupts']),1)
                from codex_wake.native_protocol import native_request
                native_request(state['endpoint'],'/unused','thread/read',dict(threadId='one',includeTurns=False),1)
                self.assertEqual(len(state['starts']),1)
                self.assertEqual(TurnEvents(state['root']).state(identifier)['protective_scope'],original_scope)
            self.assertEqual(len(state['starts']),1)

    def test_total_clock_loss_does_not_reconcile_unacknowledged_turn_or_create_scope(self):
        from codex_wake.measurements import TimeUnavailable
        with peer(lost_ack=True) as state:
            admitted=submit(state,'protective-unacked');identifier=admitted['operation_id']
            record=state['owner'].runtime._load(identifier);principal=record['principal']
            self.assertNotIn('protective_scope',TurnEvents(state['root']).state(identifier))
            with patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('lost')):
                outcome=state['owner'].runtime.revoke_grant(principal['grant_id'],issuer=principal['issuer'],resource=principal['resource'])
            self.assertEqual(outcome['operations'][0]['cancellation'],'uncertain')
            self.assertEqual(state['interrupts'],[])
            self.assertNotIn('protective_scope',TurnEvents(state['root']).state(identifier))
            self.assertEqual(len(state['starts']),1)

    def test_clock_loss_rejects_missing_empty_mismatched_or_retargeted_scope(self):
        from codex_wake.measurements import TimeUnavailable
        for defect in ('legacy','empty_turn','admission','target','endpoint','replaced_socket'):
            with self.subTest(defect=defect),peer() as state:
                with contextlib.ExitStack() as cleanups:
                    admitted=submit(state,'protective-'+defect);identifier=admitted['operation_id']
                    store=TurnEvents(state['root']);metadata=store.state(identifier)
                    self.assertIn('protective_scope',metadata)
                    if defect=='legacy':metadata.pop('protective_scope')
                    elif defect=='empty_turn':metadata['protective_scope']['turn_id']=''
                    elif defect=='admission':metadata['protective_scope']['admission_fingerprint']='changed'
                    elif defect=='target':metadata['protective_scope']['target_sha256']='changed'
                    elif defect=='endpoint':metadata['protective_scope']['endpoint']='unix:///changed.sock'
                    else:
                        Path(state['endpoint'][7:]).unlink()
                        replacement=cleanups.enter_context(unix_serve(state['handler'],state['endpoint'][7:]))
                        worker=threading.Thread(target=replacement.serve_forever,daemon=True);worker.start()
                        cleanups.callback(worker.join,2);cleanups.callback(replacement.shutdown)
                    with store.runtime.connect() as db:
                        db.execute('UPDATE native_turn_collectors SET state=? WHERE operation_id=?',(json.dumps(metadata),identifier))
                    record=state['owner'].runtime._load(identifier);principal=record['principal']
                    with patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('lost')):
                        outcome=state['owner'].runtime.revoke_grant(principal['grant_id'],issuer=principal['issuer'],resource=principal['resource'])
                    self.assertEqual(state['interrupts'],[])
                    self.assertEqual(outcome['operations'][0]['cancellation'],'uncertain')
                    if defect=='legacy':self.assertNotIn('protective_scope',store.state(identifier))
                    self.assertEqual(len(state['starts']),1)

    def test_protective_fuse_and_rejection_remain_uncertain_without_replay(self):
        from codex_wake.measurements import TimeUnavailable
        for response in ('stall','reject','unsupported_fuse'):
            with self.subTest(response=response),peer(interrupt_reply=response) as state:
                admitted=submit(state,'protective-'+response);identifier=admitted['operation_id']
                record=state['owner'].runtime._load(identifier);principal=record['principal']
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch('codex_wake.measurements.snapshot',side_effect=TimeUnavailable('lost')))
                    if response=='unsupported_fuse':stack.enter_context(patch('codex_wake.host_counter._TransportFuse',side_effect=ValueError('unsupported')))
                    outcome=state['owner'].runtime.revoke_grant(principal['grant_id'],issuer=principal['issuer'],resource=principal['resource'])
                    self.assertEqual(outcome['operations'][0]['cancellation'],'uncertain')
                    self.assertEqual(len(state['interrupts']),0 if response=='unsupported_fuse' else 1)
                    state['owner'].runtime.revoke_grant(principal['grant_id'],issuer=principal['issuer'],resource=principal['resource'])
                    self.assertEqual(len(state['interrupts']),0 if response=='unsupported_fuse' else 1)
                current=state['owner'].runtime._load(identifier)
                self.assertNotEqual(current['phase'],'terminal')
                self.assertEqual(TurnEvents(state['root']).state(identifier)['protective_attempt']['status'],'uncertain')

    def test_missing_native_ack_never_cancels_an_unbound_turn_or_replays_prompt(self):
        for echo in (False,'duplicate'):
            with peer(lost_ack=True,echo_id=echo) as state:
                record=submit(state);identifier=record['operation_id']
                result=state['owner'].result(identifier)['result']['operation']
                self.assertEqual(result['phase'],'uncertain')
                cancelled=state['owner'].cancel(identifier)['result']['operation']
                self.assertEqual(cancelled['cancellation'],'uncertain')
                self.assertEqual(state['interrupts'],[])
                caller=subprocess.run([sys.executable,'-m','codex_wake','--wake-root',str(state['root']),'control','prompt','thread:one','--json',
                    'Bounded fixture prompt','--idempotency-key','intent','--endpoint',state['endpoint']],capture_output=True,text=True,timeout=10)
                self.assertEqual(caller.returncode,3,caller.stderr)
                self.assertEqual(json.loads(caller.stdout)['result']['operation']['operation_id'],identifier)
                self.assertEqual(len(state['starts']),1)

    def test_lost_ack_reconciles_only_unique_native_echo_then_cancels_exact_turn(self):
        with peer(lost_ack=True) as state:
            record=submit(state);identifier=record['operation_id']
            result=state['owner'].result(identifier)['result']['operation']
            self.assertEqual(result['phase'],'waiting')
            self.assertEqual(result['result']['turn_id'],'owned-turn')
            self.assertEqual(state['starts'][0]['clientUserMessageId'],identifier)
            cancelled=state['owner'].cancel(identifier)['result']['operation']
            self.assertEqual(cancelled['execution'],'cancelled')
            self.assertEqual(state['interrupts'],[{'threadId':'one','turnId':'owned-turn'}])
            self.assertEqual(len(state['starts']),1)

    def test_late_ack_survives_an_older_unqualified_observation(self):
        with peer(echo_id=False,hold_ack=True,hold_observation=True) as state, ThreadPoolExecutor(2) as pool:
            prompting=pool.submit(submit,state)
            self.assertTrue(state['accepted'].wait(5))
            identifier=state['starts'][0]['clientUserMessageId']
            observing=pool.submit(state['owner'].result,identifier)
            self.assertTrue(state['observation'].wait(5))
            state['ack'].set();accepted=prompting.result(10)
            self.assertEqual(accepted['result']['turn_id'],'owned-turn')
            state['release_observation'].set()
            result=observing.result(10)['result']['operation']
            self.assertEqual(result['result']['turn_id'],'owned-turn')
            self.assertEqual(result['phase'],'waiting')
            state['status']='completed';state['finish'].set()
            terminal=state['owner'].output(identifier,timeout=3)
            self.assertTrue(terminal['terminal']);self.assertEqual(terminal['execution'],'completed')

    def test_disconnected_stream_retains_cursor_and_late_final_without_cancelling(self):
        with peer() as state:
            record=submit(state);identifier=record['operation_id']
            page=state['owner'].output(identifier,mode='stream',timeout=3);deadline=time.monotonic()+3
            while not page['text'] and time.monotonic()<deadline:page=state['owner'].output(identifier,mode='stream',cursor=page['next_cursor'],timeout=1)
            self.assertEqual(page['text'],'Retained ')
            cursor=page['next_cursor'];state['drop'].set();deadline=time.monotonic()+3
            while TurnEvents(state['root']).state(identifier)['status']!='uncertain' and time.monotonic()<deadline:time.sleep(.01)
            pending=state['owner'].output(identifier,mode='final',timeout=0)
            self.assertFalse(pending['terminal']);self.assertFalse(pending['wait']['ends_work'])
            self.assertEqual(state['interrupts'],[])
            state['status']='completed';state['finish'].set()
            late=LocalSessionControl(state['root']).output(identifier,mode='final',timeout=1)
            self.assertEqual(late['text'],'Retained answer')
            self.assertEqual(late['execution'],'completed')
            tail=state['owner'].output(identifier,mode='transcript',cursor=cursor)
            self.assertEqual(tail['events'],[]);self.assertFalse(tail['retention']['history_complete'])
            Path(state['endpoint'][7:]).unlink()
            cached=state['owner'].result(identifier)['result']['operation']
            self.assertEqual(cached['answer']['text'],'Retained answer')
            self.assertEqual(len(state['starts']),1)

    def test_busy_refusal_is_known_not_submitted_and_preserves_unrelated_turns(self):
        with peer(busy=True) as state:
            record=submit(state)
            self.assertEqual((record['phase'],record['execution'],record['delivery']),('terminal','failed','not_submitted'))
            self.assertEqual(record['reason'],'session_busy')
            self.assertEqual(state['starts'],[]);self.assertEqual(state['interrupts'],[])

    def test_replaced_socket_keeps_pending_original_unknown_and_retry_bound(self):
        with peer(lost_ack=True,echo_id=False) as state:
            original=submit(state);identifier=original['operation_id'];target=original['target']
            Path(state['endpoint'][7:]).unlink()
            with unix_serve(state['handler'],state['endpoint'][7:]) as replacement:
                worker=threading.Thread(target=replacement.serve_forever,daemon=True);worker.start()
                try:
                    observed=state['owner'].result(identifier)['result']['operation']
                    self.assertEqual(observed['phase'],'uncertain');self.assertEqual(observed['reason'],'stale_target')
                    cancelled=state['owner'].cancel(identifier)['result']['operation']
                    self.assertEqual(cancelled['cancellation'],'uncertain')
                    retry=submit(state)
                    self.assertEqual(retry['operation_id'],identifier);self.assertEqual(retry['target'],target)
                    self.assertEqual(len(state['starts']),1);self.assertEqual(state['interrupts'],[])
                finally:replacement.shutdown();worker.join(2)

    def test_cancel_before_ack_is_uncertain_then_late_ack_and_terminal_are_preserved(self):
        with peer(echo_id=False,hold_ack=True) as state, ThreadPoolExecutor(1) as pool:
            prompting=pool.submit(submit,state)
            self.assertTrue(state['accepted'].wait(5));identifier=state['starts'][0]['clientUserMessageId']
            cancel=state['owner'].cancel(identifier)['result']['operation']
            self.assertEqual(cancel['cancellation'],'uncertain');self.assertEqual(state['interrupts'],[])
            state['ack'].set();accepted=prompting.result(10)
            self.assertEqual(accepted['result']['turn_id'],'owned-turn')
            self.assertEqual(accepted['cancellation'],'uncertain')
            state['status']='completed';state['finish'].set()
            completed=state['owner'].output(identifier,timeout=3)
            self.assertEqual(completed['execution'],'completed');self.assertTrue(completed['terminal'])
            again=state['owner'].cancel(identifier)['result']['operation']
            self.assertEqual(again['execution'],'completed');self.assertEqual(state['interrupts'],[])
            self.assertEqual(len(state['starts']),1)

    def test_older_uncertain_cancel_cannot_erase_a_confirmed_exact_cancel(self):
        with peer(echo_id=False,hold_ack=True,hold_observation=True) as state, ThreadPoolExecutor(2) as pool:
            prompting=pool.submit(submit,state)
            self.assertTrue(state['accepted'].wait(5));identifier=state['starts'][0]['clientUserMessageId']
            older_cancel=pool.submit(state['owner'].cancel,identifier)
            self.assertTrue(state['observation'].wait(5))
            state['ack'].set();prompting.result(10)
            confirmed=state['owner'].cancel(identifier)['result']['operation']
            self.assertEqual(confirmed['cancellation'],'confirmed')
            state['release_observation'].set()
            final=older_cancel.result(10)['result']['operation']
            self.assertEqual(final['cancellation'],'confirmed')
            self.assertEqual(final['execution'],'cancelled')
            self.assertEqual(state['interrupts'],[{'threadId':'one','turnId':'owned-turn'}])
