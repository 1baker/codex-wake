"""Native reconciliation must tolerate long-thread responses with a finite cap."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from websockets.sync.server import unix_serve
from websockets.exceptions import ConnectionClosed
from codex_wake.native_delivery import native_evidence


class NativeLargeResponseTests(unittest.TestCase):
    def setUp(self):
        clock = dict(reason='authenticated_utc', valid_for_ns=1000000000,
            utc=dict(status='network', lower=1700000000, upper=1700000001),
            counter=dict(epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                counter=1000, frequency=1000, rate_ppm=5000))
        for target, value in (('configuration', '/explicit-test-clock'), ('snapshot', clock)):
            context = patch('codex_wake.native_clock.' + target, return_value=value)
            context.start()
            self.addCleanup(context.stop)

    def test_invalid_rpc_timeout_refuses_before_endpoint_discovery_or_connection(self):
        from codex_wake.native_protocol import native_request
        from codex_wake.records import WakeError
        for timeout in (float('nan'), float('inf'), -float('inf'), True, False, -1, '2', None):
            with self.subTest(timeout=timeout), \
                    patch('codex_wake.shared_app_server.locate_shared_endpoint') as locate, \
                    patch('websockets.sync.client.unix_connect') as connect:
                with self.assertRaisesRegex(WakeError, 'invalid native request timeout'):
                    native_request('unix://', 'unused', 'thread/read', {}, timeout)
                locate.assert_not_called()
                connect.assert_not_called()

    def test_rpc_waits_work_without_stable_time(self):
        from codex_wake.native_protocol import native_request
        calls = []
        def handler(ws):
            for raw in ws:
                request = json.loads(raw)
                calls.append(request['method'])
                if 'id' in request:
                    ws.send(json.dumps({'id': request['id'], 'result': {'ok': True}}))
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Path(directory) / 'server.sock'
            with unix_serve(handler, str(endpoint)) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    with patch('codex_wake.native_clock.configuration', return_value=None), \
                            patch('codex_wake.measurements.deadline', side_effect=AssertionError('protective wait queried reliable time')):
                        self.assertEqual(native_request('unix://' + str(endpoint), 'unused',
                            'thread/read', {'threadId': 'owned'}, 2), {'ok': True})
                    self.assertEqual(calls, ['initialize', 'initialized', 'thread/read'])
                finally:
                    server.shutdown()
                    worker.join(timeout=2)

    def test_rpc_initialize_and_request_share_one_protective_budget(self):
        from codex_wake.native_protocol import native_request
        from codex_wake.records import WakeError
        advisory = [0.0]
        def handler(ws):
            try:
                for raw in ws:
                    request = json.loads(raw)
                    if request.get('method') == 'initialize':
                        ws.send(json.dumps({'id': request['id'], 'result': {}}))
            except ConnectionClosed:
                pass  # Client closes immediately on its protective timeout.
        def initialized(ws, metadata):
            advisory[0] = 3.0
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Path(directory) / 'server.sock'
            with unix_serve(handler, str(endpoint)) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    with patch('codex_wake.native_protocol.time', SimpleNamespace(monotonic=lambda: advisory[0])):
                        with self.assertRaisesRegex(WakeError, 'inspect state before retry'):
                            native_request('unix://' + str(endpoint), 'unused',
                                'thread/read', {}, 2, verify_connection=initialized)
                finally:
                    server.shutdown()
                    worker.join(timeout=2)

    def test_rpc_timeout_after_write_does_not_replay(self):
        from codex_wake.native_protocol import native_request
        from codex_wake.records import WakeError
        calls = []
        release = threading.Event()
        def handler(ws):
            for raw in ws:
                request = json.loads(raw)
                calls.append(request['method'])
                if request['method'] == 'initialize':
                    ws.send(json.dumps({'id': request['id'], 'result': {}}))
                elif request['method'] == 'turn/start':
                    release.wait(2)
                    return
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Path(directory) / 'server.sock'
            with unix_serve(handler, str(endpoint)) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    with patch('codex_wake.native_clock.configuration', return_value=None):
                        with self.assertRaises((TimeoutError, WakeError)):
                            native_request('unix://' + str(endpoint), 'unused',
                                'turn/start', {'threadId': 'owned'}, .1)
                    self.assertEqual(calls.count('turn/start'), 1)
                finally:
                    release.set()
                    server.shutdown()
                    worker.join(timeout=2)

    def test_native_reconciliation_does_not_require_time_authority(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        from unittest.mock import patch
        from codex_wake.measurements import TimeUnavailable
        calls = []
        def request(endpoint, executable, method, params, timeout):
            calls.append(method)
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 10)
            if method == 'thread/queue/list':
                return dict(data=[dict(id='queue-original', clientUserMessageId='original',
                    input=[dict(type='text', text='wake')])], nextCursor=None)
            if method == 'thread/read': return dict(thread=dict(id='thread'))
            if method == 'thread/turns/list': return dict(data=[], nextCursor=None)
            self.fail(method)
        adapter = CodexRuntimeAdapter(read_thread=lambda target: None, request=request,
            run=lambda *args: self.fail('reconciliation must not send'), project_failure=lambda *args: None)
        recipient = adapter.resolve(dict(transport='native', thread_id='thread', endpoint='unix://', codex_cmd='/codex'))
        with patch('codex_wake.measurements.snapshot', side_effect=TimeUnavailable('unavailable')):
            result = adapter.reconcile(recipient, 'wake')
        self.assertEqual(result.evidence['queue_id'], 'queue-original')
        self.assertEqual(calls, ['thread/queue/list', 'thread/read', 'thread/turns/list'])

    def test_reconciliation_reads_user_message_beyond_default_websocket_cap(self):
        prompt = 'wake regression marker'
        thread_id = '01a10922-e791-7dd0-8bb2-ae9f110a688b'
        def handler(ws):
            for raw in ws:
                request = json.loads(raw)
                if 'id' not in request:
                    continue
                method = request['method']
                if method == 'initialize':
                    result = {}
                elif method == 'thread/queue/list':
                    result = {'data': [], 'nextCursor': None}
                elif method == 'thread/turns/list':
                    ws.send(json.dumps({'id':request['id'],'error':{'code':-32601,'message':'older server'}}))
                    continue
                else:
                    result = {'thread': {'id': thread_id, 'turns': [
                        {'id': 'turn', 'status': 'completed', 'items': [
                            {'id': 'large-context', 'type': 'assistantMessage', 'text': 'x' * (2 * 1024 * 1024)},
                            {'id': 'message', 'clientId': 'submission', 'type': 'userMessage',
                             'content': [{'type': 'text', 'text': prompt}]},
                        ]},
                    ]}}
                ws.send(json.dumps({'id': request['id'], 'result': result}))
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Path(directory) / 'server.sock'
            with unix_serve(handler, str(endpoint)) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    evidence, reason = native_evidence({'endpoint': 'unix://' + str(endpoint),
                        'codex_cmd': 'unused', 'thread_id': thread_id}, prompt)
                    self.assertEqual(evidence['client_message_id'], 'submission')
                    self.assertEqual(evidence['source'], 'native_turn')
                finally:
                    server.shutdown()
                    worker.join(timeout=2)

    def test_paged_reconciliation_recovers_terminal_identity_when_whole_history_disconnects(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        prompt='exact retained wake prompt'
        calls=[]
        def request(endpoint,codex,method,params,timeout):
            calls.append(method)
            if method=='thread/queue/list':return {'data':[],'nextCursor':None}
            if method=='thread/read':
                if params.get('includeTurns'):raise ConnectionError('whole-history connection closed')
                return {'thread':{'id':'owned'}}
            if method=='thread/turns/list':
                if 'cursor' not in params:
                    return {'data':[{'id':'newer-turn','status':'completed','itemsView':'full','items':[]}],
                            'nextCursor':'older'}
                self.assertEqual(params['cursor'],'older')
                self.assertEqual(params['itemsView'],'summary')
                return {'data':[{'id':'original-turn','status':'completed','itemsView':'full','items':[
                    {'type':'userMessage','id':'original-message','clientId':'original-client',
                     'content':[{'type':'text','text':prompt}]},
                    {'type':'agentMessage','id':'answer','text':'done'},
                ]}],'nextCursor':None}
            raise AssertionError('unexpected native effect: '+method)
        def forbidden(*args,**kwargs):raise AssertionError('reconciliation cannot write')
        adapter=CodexRuntimeAdapter(read_thread=forbidden,request=request,run=forbidden,project_failure=forbidden)
        result=adapter.reconcile(adapter.resolve(dict(transport='native',thread_id='owned',
            endpoint='unix:///owned',codex_cmd='/bin/true')),prompt)
        self.assertEqual(result.evidence['client_message_id'],'original-client')
        self.assertEqual(result.evidence['turn_id'],'original-turn')
        self.assertEqual(result.evidence['user_message_id'],'original-message')
        self.assertEqual(result.evidence['execution'],'turn_completed')
        self.assertEqual(result.evidence['output_summary']['text_bytes'],4)
        self.assertNotIn('turn/start',calls)

    def test_incomplete_or_ambiguous_pages_never_become_native_evidence(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        from codex_wake.records import WakeError
        turn={'id':'same','status':'completed','itemsView':'full','items':[]}
        for problem in ('missing-cursor','cursor-cycle','duplicate-turn','summary-only','missing-items','page-bound'):
            with self.subTest(problem=problem):
                def request(endpoint,codex,method,params,timeout):
                    if method=='thread/queue/list':return {'data':[],'nextCursor':None}
                    if method=='thread/read':
                        self.assertFalse(params['includeTurns'],'bad pages cannot authorize legacy fallback')
                        return {'thread':{'id':'owned'}}
                    self.assertEqual(method,'thread/turns/list','no native write is allowed')
                    if problem=='missing-cursor':return {'data':[]}
                    if problem=='cursor-cycle':return {'data':[],'nextCursor':'cycle'}
                    if problem=='page-bound':return {'data':[],'nextCursor':str(int(params.get('cursor','0'))+1)}
                    if problem=='duplicate-turn':return {'data':[turn],'nextCursor':'older' if 'cursor' not in params else None}
                    item=dict(turn,itemsView='summary') if problem=='summary-only' else dict(turn,items=None)
                    return {'data':[item],'nextCursor':None}
                def forbidden(*args,**kwargs):raise AssertionError('reconciliation cannot write')
                adapter=CodexRuntimeAdapter(read_thread=forbidden,request=request,run=forbidden,project_failure=forbidden)
                recipient = adapter.resolve(dict(transport='native', thread_id='owned',
                                                 endpoint='unix:///owned', codex_cmd='/bin/true'))
                if problem == 'summary-only':
                    # Unrelated summaries can be searched, but cannot establish
                    # execution evidence without a matching complete item read.
                    self.assertIsNone(adapter.reconcile(recipient, 'retained prompt').evidence)
                else:
                    with self.assertRaises(WakeError):
                        adapter.reconcile(recipient, 'retained prompt')

    def test_a_late_native_response_does_not_extend_the_shared_deadline(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        from codex_wake.records import WakeError
        clock=[0.0]
        def request(endpoint,codex,method,params,timeout):
            if method=='thread/queue/list':return {'data':[],'nextCursor':None}
            if method=='thread/read':return {'thread':{'id':'owned'}}
            self.assertEqual(method,'thread/turns/list')
            clock[0]=11.0
            return {'data':[],'nextCursor':None}
        def forbidden(*args,**kwargs):raise AssertionError('reconciliation cannot write')
        adapter=CodexRuntimeAdapter(read_thread=forbidden,request=request,run=forbidden,
            project_failure=forbidden,monotonic=lambda:clock[0])
        with self.assertRaises(WakeError):
            adapter.reconcile(adapter.resolve(dict(transport='native',thread_id='owned',
                endpoint='unix:///owned',codex_cmd='/bin/true')),'retained prompt')

    def test_legacy_fallback_cannot_supply_an_unknown_terminal_state(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        from codex_wake.native_protocol import NativeCapabilityUnavailable
        from codex_wake.records import WakeError
        def request(endpoint,codex,method,params,timeout):
            if method=='thread/queue/list':return {'data':[],'nextCursor':None}
            if method=='thread/turns/list':raise NativeCapabilityUnavailable('older server')
            self.assertEqual(method,'thread/read')
            return {'thread':{'id':'owned','turns':[{'id':'unknown-turn','status':'invented',
                'items':[{'type':'userMessage','id':'message','clientId':'client',
                          'content':[{'type':'text','text':'retained prompt'}]}]}]}}
        def forbidden(*args,**kwargs):raise AssertionError('reconciliation cannot write')
        adapter=CodexRuntimeAdapter(read_thread=forbidden,request=request,run=forbidden,project_failure=forbidden)
        with self.assertRaises(WakeError):
            adapter.reconcile(adapter.resolve(dict(transport='native',thread_id='owned',
                endpoint='unix:///owned',codex_cmd='/bin/true')),'retained prompt')

    def test_exact_prompt_with_malformed_native_identity_is_not_evidence(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        from codex_wake.records import WakeError
        for message_id, client_id in ((None,None),('',None),(42,None),('message',''),('message',42)):
            with self.subTest(message_id=message_id,client_id=client_id):
                def request(endpoint,codex,method,params,timeout):
                    if method=='thread/queue/list':return {'data':[],'nextCursor':None}
                    if method=='thread/read':return {'thread':{'id':'owned'}}
                    self.assertEqual(method,'thread/turns/list','no input calls')
                    return {'data':[{'id':'turn','status':'completed','itemsView':'full','items':[
                        {'type':'userMessage','id':message_id,'clientId':client_id,
                         'content':[{'type':'text','text':'retained prompt'}]}]}],'nextCursor':None}
                def forbidden(*args,**kwargs):raise AssertionError('reconciliation cannot write')
                adapter=CodexRuntimeAdapter(read_thread=forbidden,request=request,run=forbidden,project_failure=forbidden)
                with self.assertRaises(WakeError):
                    adapter.reconcile(adapter.resolve(dict(transport='native',thread_id='owned',
                        endpoint='unix:///owned',codex_cmd='/bin/true')),'retained prompt')

    def test_absent_native_client_id_retains_exact_message_id_fallback(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        def request(endpoint,codex,method,params,timeout):
            if method=='thread/queue/list':return {'data':[],'nextCursor':None}
            if method=='thread/read':return {'thread':{'id':'owned'}}
            self.assertEqual(method,'thread/turns/list','no input calls')
            return {'data':[{'id':'turn','status':'completed','itemsView':'full','items':[
                {'type':'userMessage','id':'original-message','content':[{'type':'text','text':'retained prompt'}]}]}],
                'nextCursor':None}
        def forbidden(*args,**kwargs):raise AssertionError('reconciliation cannot write')
        adapter=CodexRuntimeAdapter(read_thread=forbidden,request=request,run=forbidden,project_failure=forbidden)
        value=adapter.reconcile(adapter.resolve(dict(transport='native',thread_id='owned',
            endpoint='unix:///owned',codex_cmd='/bin/true')),'retained prompt')
        self.assertEqual(value.evidence['client_message_id'],'original-message')
        self.assertEqual(value.evidence['user_message_id'],'original-message')

    def test_method_not_found_is_distinct_from_other_native_rejections(self):
        from codex_wake.native_protocol import native_request, NativeCapabilityUnavailable
        from codex_wake.records import WakeError
        for code in (-32601,-32603):
            with self.subTest(code=code),tempfile.TemporaryDirectory() as directory:
                def handler(ws):
                    for raw in ws:
                        request=json.loads(raw)
                        if 'id' not in request:continue
                        response=dict(id=request['id'])
                        if request['method']=='initialize':response['result']={}
                        else:response['error']=dict(code=code,message='native refusal')
                        ws.send(json.dumps(response))
                endpoint=Path(directory)/'server.sock'
                with unix_serve(handler,str(endpoint)) as server:
                    worker=threading.Thread(target=server.serve_forever,daemon=True)
                    worker.start()
                    try:
                        with self.assertRaises(WakeError) as rejected:
                            native_request('unix://'+str(endpoint),'unused','thread/notice/read',{},2)
                        self.assertEqual(isinstance(rejected.exception,NativeCapabilityUnavailable),code==-32601)
                    finally:
                        server.shutdown();worker.join(timeout=2)
