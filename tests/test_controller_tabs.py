import tempfile
import unittest
from pathlib import Path
from codex_wake.controller_tabs import ControllerTabs
from codex_wake.managed_inventory import InventoryError


class Transport:
    def snapshot(self, deadline):
        return dict(server='fixture', session_id='$1', socket_identity=[1,2], windows=[
            dict(window_id='@1', index=0, name='friendly', focused=True, linked=False,
                 panes=[dict(pane_id='%1', pid=123)])])


class ControllerTabsTests(unittest.TestCase):
    def test_friendly_selector_and_exact_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = ControllerTabs(directory, workspaces={'fixture': dict(transport=Transport(), kind='psmux')}, host='h', environment='fixture')
            resource = owner.execute('tabs.show', {'workspace':'fixture','selector':'friendly'})['resources'][0]
            self.assertEqual(resource['window']['window_id'], '@1')
            self.assertFalse(resource['input_custody']['available'])
            with self.assertRaises(InventoryError) as caught:
                owner.execute('tabs.capture', {'workspace':'fixture','expected_target':{},'pane':'%1'})
            self.assertEqual(caught.exception.code, 'stale_target')

    def test_owned_stdio_never_falls_back_or_steals_pipe(self):
        from codex_wake.controller_tab_adapters import OwnedStdioBroker
        class Client:
            def start_turn(self, thread, text):
                return dict(thread=thread, text=text)
        with tempfile.TemporaryDirectory() as directory:
            broker = OwnedStdioBroker(Client(), bindings={'%1':'thread'}, owner_id='host-owner')
            owner = ControllerTabs(directory, workspaces={'fixture': dict(transport=Transport(), kind='stdio', broker=broker, privacy=lambda pane:'safe')}, host='h', environment='fixture')
            row = owner.execute('tabs.show', {'workspace':'fixture'})['resources'][0]
            args = dict(workspace='fixture', expected_target=row['target'], pane='%1', input='fixture', custody=row['input_custody'], transport='structured')
            self.assertEqual(owner.execute('tabs.input', args)['result']['thread'], 'thread')
            broker.relinquish()
            with self.assertRaises(InventoryError): owner.execute('tabs.input', args)

    def test_real_isolated_tmux_capture_preview_apply(self):
        import shutil
        import subprocess
        from codex_wake.controller_tab_adapters import TmuxAttachmentTransport
        if not shutil.which('tmux'): self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory) / 'tmux.sock')
            subprocess.run(['tmux','-S',socket,'new-session','-d','-s','fixture','sleep 60'], check=True)
            try:
                transport = TmuxAttachmentTransport(socket, '$0')
                for name in ('ready','working'):
                    subprocess.run(['tmux','-S',socket,'new-window','-d','-n',name,'sleep 60'], check=True)
                from codex_wake.process import process_identity
                import time
                subprocess.run(['git','init','-q',directory], check=True)
                initial = transport.snapshot(time.monotonic()+5)
                evidence = {}
                for window in initial['windows']:
                    for pane in window['panes']:
                        identity = process_identity(pane['pid'])
                        evidence[pane['pane_id']] = dict(fresh=True, conversation_id=pane['pane_id'],
                            namespace='fixture', root=directory, state='working' if window['name']=='working' else 'ready',
                            process=dict(pid=pane['pid'],start_ticks=identity['start_time_ticks'],boot_id=identity['boot_id']))
                owner = ControllerTabs(directory, workspaces={'fixture':dict(transport=transport,kind='byobu',privacy=lambda pane:'safe',observer=lambda timeout:evidence)}, host='h', environment='fixture')
                row = owner.execute('tabs.list', {})['resources'][0]
                base = dict(workspace='fixture', expected_target=row['target'])
                capture = owner.execute('tabs.capture', dict(base,pane=row['window']['panes'][0]['pane_id'], lines=5))
                self.assertTrue(capture['fallback'])
                subprocess.run(['tmux','-S',socket,'select-pane','-t','%0','-T','changed status'],check=True)
                with self.assertRaises(InventoryError) as strict:
                    owner.execute('tabs.capture',dict(base,pane=row['window']['panes'][0]['pane_id'],lines=5))
                self.assertEqual(strict.exception.code,'stale_target')
                from codex_wake.tab_commands import operator_execute
                preview=operator_execute('tabs.preview',dict(workspace='fixture'),directory,owner=owner)['result']['operation']
                self.assertEqual(preview['phase'],'terminal',preview)
                plan=preview['result']['plan']
                base=dict(workspace='fixture',expected_target=row['lifecycle_target'])
                from codex_wake.controller_auth import OAuthAuthority
                from codex_wake.controller_runtime import ControllerRuntime
                from codex_wake.controller_tabs import AuthorizedTabs
                import hashlib,base64
                authority = OAuthAuthority(Path(directory)/'oauth.sqlite',issuer='https://issuer',resource='https://resource')
                client = authority.register(dict(redirect_uris=['http://127.0.0.1/callback']))
                verifier = 'v'*43
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                stable = {k:v for k,v in row['target'].items() if k != 'generation'}
                code = authority.authorize(subject='operator',principal_kind='owner',client_id=client['client_id'],
                    redirect_uri='http://127.0.0.1/callback',resource=authority.resource,scopes=['control'],targets=[stable],code_challenge=challenge)
                token = authority.token(dict(grant_type='authorization_code',code=code,code_verifier=verifier,client_id=client['client_id'],
                    redirect_uri='http://127.0.0.1/callback',resource=authority.resource))['access_token']
                facade = AuthorizedTabs(authority,owner,ControllerRuntime(directory))
                def mutate(operation,payload,key):
                    request = dict(operation_id=key,idempotency_key=key,correlation_id=key,binding='fixture-cli',target=payload['expected_target'])
                    return facade.execute(token,operation,dict(payload,_request=request))['result']['operation']
                subprocess.run(['tmux','-S',socket,'select-pane','-t','%0','-T','status before apply'],check=True)
                applied = mutate('tabs.apply',dict(base,plan_id=plan['plan_id']),'apply')
                self.assertEqual(applied['phase'],'terminal')
                result = applied['result']
                self.assertEqual(result['receipt']['status'], 'applied')
                self.assertTrue(result['receipt']['swaps'])
                current = owner.execute('tabs.list', {})['resources'][0]['lifecycle_target']
                self.assertNotEqual(current,row['lifecycle_target'])
                stale = mutate('tabs.undo',dict(base,receipt_id=result['receipt']['receipt_id']),'stale')
                self.assertEqual(stale['reason'],'stale_target')
                self.assertEqual(owner.execute('tabs.list',{})['resources'][0]['lifecycle_target'],current)
                subprocess.run(['tmux','-S',socket,'select-pane','-t','%0','-T','status before undo'],check=True)
                undone_operation = mutate('tabs.undo',dict(workspace='fixture',expected_target=current,receipt_id=result['receipt']['receipt_id']),'undo')
                self.assertEqual(undone_operation['phase'],'terminal')
                undone = undone_operation['result']
                self.assertEqual(undone['receipt']['status'], 'undone')
            finally:
                subprocess.run(['tmux','-S',socket,'kill-server'], check=False)

    def test_psmux_finite_protocol_and_replaced_generation(self):
        from codex_wake.controller_tab_adapters import PsmuxAttachmentTransport
        import time
        generation = ['fixture-1']
        calls = []
        def bridge(action, args, deadline):
            calls.append((action,args))
            return dict(generation=generation[0],result=Transport().snapshot(deadline) if action=='snapshot' else 'fixture output')
        transport = PsmuxAttachmentTransport(bridge,generation='fixture-1')
        with tempfile.TemporaryDirectory() as directory:
            owner = ControllerTabs(directory, workspaces={'fixture':dict(transport=transport,kind='psmux',privacy=lambda pane:'safe')},host='h',environment='fixture')
            row = owner.execute('tabs.list', {})['resources'][0]
            result = owner.execute('tabs.capture', dict(workspace='fixture',expected_target=row['target'],pane='%1',lines=2))
            self.assertEqual(result['text'],'fixture output')
            self.assertEqual(calls[-1],('capture',{'pane':'%1','lines':2}))
            generation[0] = 'replacement'
            with self.assertRaises(InventoryError): owner.execute('tabs.list',{})

    def test_authorized_uncertain_stdio_input_is_not_replayed(self):
        import time
        from types import SimpleNamespace
        from codex_wake.controller_auth import Actor, AuthError
        from codex_wake.controller_runtime import ControllerRuntime
        from codex_wake.controller_tabs import AuthorizedTabs
        from codex_wake.controller_tab_adapters import OwnedStdioBroker
        calls = []
        class Client:
            def start_turn(self, thread, text):
                calls.append((thread,text))
                raise BrokenPipeError('fixture disconnected after submission')
        with tempfile.TemporaryDirectory() as directory:
            broker = OwnedStdioBroker(Client(),bindings={'%1':'thread'},owner_id='fixture')
            owner = ControllerTabs(directory,workspaces={'fixture':dict(transport=Transport(),kind='stdio',broker=broker,privacy=lambda pane:'safe')},host='h',environment='fixture')
            row = owner.execute('tabs.show',{'workspace':'fixture'})['resources'][0]
            target = row['target']
            actor = Actor('owner','human','client','grant','https://issuer','https://resource',frozenset({'control','observe'}),[target],time.time()+600)
            authority = SimpleNamespace(authenticate=lambda token:actor)
            facade = AuthorizedTabs(authority,owner,ControllerRuntime(directory))
            args = dict(workspace='fixture',expected_target=target,pane='%1',input='fixture',custody=row['input_custody'],transport='structured',
                _request=dict(operation_id='one',idempotency_key='one',correlation_id='one',binding='first',target=target))
            result = facade.execute('token','tabs.input',args)
            self.assertEqual(result['result']['operation']['phase'],'uncertain')
            runtime = ControllerRuntime(directory)
            readback = runtime.operation(actor, 'operations.result', {'operation_id': 'one'}, authorize=lambda: actor)
            self.assertEqual(readback['result']['operation']['phase'], 'uncertain')
            self.assertEqual(readback['result']['operation']['operation_id'], 'one')
            AuthorizedTabs(authority, owner, runtime).execute('token', 'tabs.input', args)
            self.assertEqual(len(calls), 1)
            denied = Actor('owner','human','client','grant','https://issuer','https://resource',frozenset({'observe'}),[target],time.time()+600)
            with self.assertRaises(AuthError):
                AuthorizedTabs(SimpleNamespace(authenticate=lambda token:denied),owner,ControllerRuntime(directory)).execute('token','tabs.input',args)
            self.assertEqual(len(calls),1)

    def test_private_and_unknown_privacy_prevents_read_and_input_effects(self):
        class PrivateTransport(Transport):
            def capture(self, *args):
                raise AssertionError('private terminal was read')
        for state in (None, 'private_input', 'draft', 'working'):
            with tempfile.TemporaryDirectory() as directory:
                config = dict(transport=PrivateTransport(),kind='psmux')
                if state is not None: config['privacy'] = lambda pane:state
                owner = ControllerTabs(directory,workspaces={'fixture':config},host='h',environment='fixture')
                target = owner.execute('tabs.list',{})['resources'][0]['target']
                with self.assertRaises(InventoryError) as caught:
                    owner.execute('tabs.capture',dict(workspace='fixture',expected_target=target,pane='%1'))
                self.assertEqual(caught.exception.code,'presentation_privacy_unknown')
                with self.assertRaises(InventoryError) as input_error:
                    owner.execute('tabs.input',dict(workspace='fixture',expected_target=target,pane='%1',input='fixture',transport='terminal',custody={}))
                self.assertEqual(input_error.exception.code,'presentation_privacy_unknown')

    def test_real_explicit_terminal_fallback(self):
        import shutil
        import subprocess
        import time
        from codex_wake.controller_tab_adapters import TmuxAttachmentTransport, OwnedTerminalBroker
        if not shutil.which('tmux'): self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory)/'fallback.sock')
            subprocess.run(['tmux','-S',socket,'new-session','-d','-s','fixture','cat'],check=True)
            try:
                transport = TmuxAttachmentTransport(socket,'$0')
                broker = OwnedTerminalBroker(transport,panes=['%0'],owner_id='fixture')
                owner = ControllerTabs(directory,workspaces={'fixture':dict(transport=transport,kind='byobu',broker=broker,privacy=lambda pane:'safe')},host='h',environment='fixture')
                row = owner.execute('tabs.list',{})['resources'][0]
                args = dict(workspace='fixture', expected_target=row['target'], window=row['window']['window_id'],
                            custody=row['input_custody'], transport='terminal')
                result = owner.execute('tabs.input', dict(args, input='fixture line'))
                self.assertEqual(result['pane'], '%0')
                self.assertEqual(result['result']['acceptance'], 'terminal_adapter')
                captured = owner.execute('tabs.capture', {k: args[k] for k in ('workspace', 'expected_target', 'window')})
                self.assertEqual(captured['pane'], '%0')
                self.assertEqual(captured['text'].count('fixture line'), 1)
                owner.execute('tabs.input', dict(args, mode='keys', keys=['Enter']))
                deadline = time.monotonic() + 2
                while transport.capture('%0', 5, deadline).count('fixture line') < 2:
                    self.assertLess(time.monotonic(), deadline, 'Enter did not submit the literal text')
                    time.sleep(.01)
                with self.assertRaises(InventoryError):
                    owner.execute('tabs.input', dict(args, input='unsafe\nsecond'))
                subprocess.run(['tmux', '-S', socket, 'split-window', '-d', '-t', '%0', 'cat'], check=True)
                with self.assertRaises(InventoryError) as stale:
                    owner.execute('tabs.input', dict(args, input='stale'))
                self.assertEqual(stale.exception.code, 'stale_target')
                fresh = owner.execute('tabs.list', {})['resources'][0]['target']
                with self.assertRaises(InventoryError) as ambiguous:
                    owner.execute('tabs.capture', dict(workspace='fixture', expected_target=fresh, window=row['window']['window_id']))
                self.assertEqual(ambiguous.exception.code, 'ambiguous_target')
            finally:
                subprocess.run(['tmux','-S',socket,'kill-server'],check=False)

    def test_actual_disposable_stdio_process_uses_existing_client(self):
        import sys
        from codex_wake.app_server import StdioAppServerClient
        from codex_wake.controller_tab_adapters import OwnedStdioBroker
        program = '''import json,sys
for line in sys.stdin:
    row=json.loads(line)
    result={'fixture':True,'method':row['method'],'params':row['params']}
    print(json.dumps({'id':row['id'],'result':result}),flush=True)
'''
        client = StdioAppServerClient(command=[sys.executable,'-u','-c',program],timeout_seconds=2)
        try:
            client.initialize()
            broker = OwnedStdioBroker(client,bindings={'%1':'fixture-thread'},owner_id='fixture-process')
            with tempfile.TemporaryDirectory() as directory:
                owner = ControllerTabs(directory,workspaces={'fixture':dict(transport=Transport(),kind='stdio',broker=broker,privacy=lambda pane:'safe')},host='h',environment='fixture')
                row = owner.execute('tabs.list',{})['resources'][0]
                result = owner.execute('tabs.input',dict(workspace='fixture',expected_target=row['target'],pane='%1',input='fixture only',transport='structured',custody=row['input_custody']))
                self.assertEqual(result['result']['method'],'turn/start')
                self.assertEqual(result['result']['params']['threadId'],'fixture-thread')
                self.assertIs(broker.client,client)
        finally:
            client.close()

    def test_host_factory_installed_cli_uses_fixed_private_configuration(self):
        import argparse
        import contextlib
        import io
        import json
        import shutil
        import subprocess
        from codex_wake.controller_tabs import controller_tabs_from_root
        from codex_wake.tab_commands import register_parser, command
        if not shutil.which('tmux'): self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory)/'factory.sock')
            subprocess.run(['tmux','-S',socket,'new-session','-d','-s','fixture','sleep 60'],check=True)
            try:
                config = Path(directory)/'controller-tabs.json'
                config.write_text(json.dumps(dict(schema_version=1,workspaces={'fixture':dict(kind='byobu',socket_path=socket,session_id='$0')})))
                config.chmod(0o600)
                owner = controller_tabs_from_root(directory)
                target = owner.execute('tabs.list',{})['resources'][0]['target']
                self.assertEqual(target['workspace'],'fixture')
                with self.assertRaises(InventoryError) as caught:
                    owner.execute('tabs.capture',dict(workspace='fixture',expected_target=target,pane='%0'))
                self.assertEqual(caught.exception.code,'presentation_privacy_unknown')
                parser = argparse.ArgumentParser()
                parser.add_argument('--wake-root',default=directory)
                register_parser(parser.add_subparsers())
                args = parser.parse_args(['tabs','list','--json'])
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(command(args),0)
                self.assertEqual(json.loads(output.getvalue())['resources'][0]['target']['workspace'],'fixture')
                config.chmod(0o644)
                with self.assertRaises(InventoryError): controller_tabs_from_root(directory)
            finally:
                subprocess.run(['tmux','-S',socket,'kill-server'],check=False)
