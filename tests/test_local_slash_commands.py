"""Native slash action semantics through the public owner and real journal."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest
from websockets.sync.server import unix_serve


class LocalSlashCommandTests(unittest.TestCase):
    def test_rename_preserves_arguments_and_duplicate_intent_never_prompts(self):
        from codex_wake.local_slash_commands import execute
        with self.native() as (root, endpoint, state):
            name='Δ  release "candidate"'
            first=execute(root,'run',dict(selector='thread:one',command='/rename',arguments=name,idempotency_key='rename-1',endpoint=endpoint))
            record=first['result']['operation']
            self.assertEqual(record['execution'],'completed')
            self.assertTrue(record['result']['executed'])
            self.assertTrue(record['result']['completed'])
            self.assertEqual(state['name'],name)
            repeated=execute(root,'run',dict(selector='thread:one',command='/rename',arguments=name,idempotency_key='rename-1',endpoint=endpoint))
            self.assertEqual(repeated['result']['operation']['operation_id'],record['operation_id'])
            self.assertEqual(state['calls'].count('thread/name/set'),1)
            self.assertNotIn('turn/start',state['calls'])

    def test_rename_interaction_requires_explicit_input_then_observes_native_name(self):
        from codex_wake.local_slash_commands import execute
        with self.native() as (root,endpoint,state):
            setup=dict(selector='thread:one',command='/rename',idempotency_key='interactive-1',endpoint=endpoint)
            first=execute(root,'run',setup)['result']['operation']
            self.assertEqual(first['execution'],'not_started')
            self.assertEqual(first['result']['presentation'],'controller_interaction')
            handle=first['result']['interaction_id']
            self.assertNotIn('thread/name/set',state['calls'])
            result=execute(root,'respond',dict(interaction_id=handle,value='Chosen Δ name',idempotency_key='response-1'))
            self.assertEqual(result['result']['operation']['execution'],'completed')
            self.assertEqual(state['name'],'Chosen Δ name')
            original=execute(root,'result',dict(operation_id=first['operation_id']))['result']['operation']
            self.assertTrue(original['result']['completed'])
            repeated=execute(root,'respond',dict(interaction_id=handle,value='Chosen Δ name',idempotency_key='response-1'))
            self.assertEqual(repeated['result']['operation']['operation_id'],result['result']['operation']['operation_id'])
            self.assertEqual(state['calls'].count('thread/name/set'),1)
            self.assertNotIn('turn/start',state['calls'])

    def test_uncertain_response_is_reconciled_without_renaming_twice(self):
        from codex_wake.local_slash_commands import execute
        from codex_wake.managed_inventory import InventoryError
        with self.native() as (root,endpoint,state):
            handle=execute(root,'run',dict(selector='thread:one',command='/rename',idempotency_key='lost-input',endpoint=endpoint))['result']['operation']['operation_id']
            state['lose_rename']=True
            response=execute(root,'respond',dict(interaction_id=handle,value='Acknowledgement lost',idempotency_key='lost-response'))['result']['operation']
            self.assertEqual(response['execution'],'unknown')
            with self.assertRaises(InventoryError):
                execute(root,'cancel',dict(interaction_id=handle))
            result=execute(root,'result',dict(operation_id=handle))['result']['operation']
            self.assertEqual(result['execution'],'completed')
            self.assertEqual(result['result']['observation']['name'],'Acknowledgement lost')
            execute(root,'respond',dict(interaction_id=handle,value='Acknowledgement lost',idempotency_key='lost-response'))
            self.assertEqual(state['calls'].count('thread/name/set'),1)

    def test_cancellation_and_stale_target_never_rename_or_submit_unknown_command(self):
        from codex_wake.local_slash_commands import execute
        from codex_wake.managed_inventory import InventoryError
        with self.native() as (root,endpoint,state):
            with self.assertRaisesRegex(InventoryError,'Supported native adapter'):
                execute(root,'run',dict(selector='thread:one',command='/model',idempotency_key='unsupported',endpoint=endpoint))
            handle=execute(root,'run',dict(selector='thread:one',command='/rename',idempotency_key='cancel-input',endpoint=endpoint))['result']['operation']['operation_id']
            cancelled=execute(root,'cancel',dict(interaction_id=handle))['result']['operation']
            self.assertEqual(cancelled['execution'],'cancelled')
            self.assertFalse(cancelled['result']['executed'])
            with self.assertRaises(InventoryError):
                execute(root,'respond',dict(interaction_id=handle,value='No rename',idempotency_key='cancelled-response'))
            stale=execute(root,'run',dict(selector='thread:one',command='/rename',idempotency_key='stale-input',endpoint=endpoint))['result']['operation']['operation_id']
            (root/'home').rename(root/'old-home');(root/'home').mkdir(mode=0o700)
            with self.assertRaisesRegex(InventoryError,'generation changed'):
                execute(root,'respond',dict(interaction_id=stale,value='No stale rename',idempotency_key='stale-response'))
            self.assertEqual(state['name'],'original')
            self.assertNotIn('thread/name/set',state['calls'])
            self.assertNotIn('turn/start',state['calls'])

    def test_delegated_interaction_keeps_caller_identity_and_rechecks_content_grant(self):
        import time
        from dataclasses import replace
        from codex_wake.controller_auth import Actor,AuthError
        from codex_wake.local_slash_commands import LocalSlashCommands
        from codex_wake.local_sessions import resolve
        with self.native() as (root,endpoint,state):
            target=resolve(root,'thread:one',endpoint=endpoint)['target']
            actor=[Actor('operator','owner','connector','grant','https://issuer','wake:controller',frozenset({'control','observe','content.observe'}),[target],time.time()+120)]
            revoked=[False]
            def authorize(target,action):
                if revoked[0] or action not in actor[0].scopes:raise AuthError('insufficient_scope')
                return actor[0]
            owner=LocalSlashCommands(root,authorize=authorize)
            first=owner.run('thread:one','/rename','','delegated-one',endpoint=endpoint)['result']['operation']
            owner.respond(first['operation_id'],'Delegated name','reply-one')
            actor[0]=replace(actor[0],scopes=frozenset({'content.observe'}))
            result=owner.result(first['operation_id'])['result']['operation']
            self.assertEqual(result['execution'],'completed')
            self.assertEqual(state['calls'].count('thread/name/set'),1)
            revoked[0]=True
            before=len(state['calls'])
            with self.assertRaises(AuthError):owner.result(first['operation_id'])
            self.assertEqual(len(state['calls']),before)

    @contextmanager
    def native(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);home=root/'home';home.mkdir(mode=0o700)
            state=dict(name='original',calls=[])
            endpoint='unix://'+str(root/'native.sock')
            def handler(ws):
                for raw in ws:
                    request=json.loads(raw)
                    if 'id' not in request:continue
                    method=request['method'];params=request.get('params',{});state['calls'].append(method)
                    if method=='initialize':value=dict(codexHome=str(home))
                    elif method=='thread/loaded/list':value=dict(data=['one'],nextCursor=None)
                    elif method=='thread/read':value=dict(thread=dict(id='one',name=state['name'],cwd=str(root),status=dict(type='idle'),modelProvider='offline',turns=[]))
                    elif method=='thread/name/set':
                        state['name']=params['name'];value={}
                        if state.pop('lose_rename',False):
                            ws.close();return
                    else:raise AssertionError('unexpected native method '+method)
                    ws.send(json.dumps(dict(id=request['id'],result=value)))
            with unix_serve(handler,str(root/'native.sock')) as server:
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                try:yield root,endpoint,state
                finally:server.shutdown();worker.join(timeout=5)
