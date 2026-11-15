"""Native reconciliation must tolerate long-thread responses with a finite cap."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from websockets.sync.server import unix_serve
from codex_wake.native_delivery import native_evidence


class NativeLargeResponseTests(unittest.TestCase):
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
                self.assertEqual(params['itemsView'],'full')
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
                with self.assertRaises(WakeError):
                    adapter.reconcile(adapter.resolve(dict(transport='native',thread_id='owned',
                        endpoint='unix:///owned',codex_cmd='/bin/true')),'retained prompt')

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
