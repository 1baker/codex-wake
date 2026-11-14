"""Terminal content/input contracts at the existing host-tab seam."""
import tempfile
import unittest
from pathlib import Path

from codex_wake.controller_tabs import ControllerTabs
from codex_wake.daemon_commands import local_operator


class TerminalTransport:
    def __init__(self):
        self.text = 'first screen'
        self.commands = []
    def snapshot(self, deadline):
        return dict(server='server1', session_id='$1', socket_identity=[1,2], windows=[
            dict(window_id='@1', index=0, name='shell', focused=True, linked=False,
                 panes=[dict(pane_id='%1', pid=123, process_generation='birth1')])])
    def capture(self, pane, lines, deadline):
        self.commands.append(('capture', pane))
        return self.text


class UnifiedTerminalTests(unittest.TestCase):
    def make(self, root, transport, broker=None, privacy=lambda pane:'safe'):
        from codex_wake.unified_terminal import TerminalControl
        tabs = ControllerTabs(root, workspaces={'work':dict(transport=transport, kind='psmux', privacy=privacy, broker=broker)}, host='host', environment='env')
        def authorize(target, action):
            return local_operator(target, ('content.observe','terminal.input'))
        owner = TerminalControl(root,tabs=tabs,authorize=authorize)
        row = tabs.execute('tabs.show', dict(workspace='work'))['resources'][0]
        pane = row['window']['panes'][0]
        args = dict(workspace='work',pane='%1',expected_target=row['target'],expected_pane={k:pane[k] for k in ('pane_id','pid','process_generation')})
        return owner, args, tabs

    def test_rendered_observation_reconnects_with_explicit_snapshot_gaps(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = TerminalTransport()
            owner,args,tabs = self.make(Path(temp),transport)
            handle = owner.execute('environment.panes.observe', dict(args,idempotency_key='screen',max_events=1))
            identifier = handle['observation_id']
            transport.text = 'first screen\nnext line'
            page = owner.execute('environment.panes.output', dict(observation_id=identifier,cursor=1))
            self.assertEqual(page['events'][0]['kind'],'append')
            self.assertEqual(page['events'][0]['text'],'\nnext line')
            self.assertFalse(page['capabilities']['raw_terminal_byte_stream'])
            transport.text = 'replacement screen'
            again = owner.execute('environment.panes.output', dict(observation_id=identifier,cursor=0))
            self.assertTrue(again['retention']['cursor_gap'])
            self.assertTrue(again['retention']['history_gap'])
            self.assertEqual(again['snapshot']['text'],'replacement screen')
            self.assertEqual(again['events'][0]['kind'],'replace')
            self.assertEqual(owner.execute('environment.panes.observe', dict(args,idempotency_key='screen',max_events=1))['observation_id'], identifier)

    def test_explicit_paste_and_keys_have_durable_delivery_without_semantic_success(self):
        from codex_wake.controller_tab_adapters import OwnedTerminalBroker
        with tempfile.TemporaryDirectory() as temp:
            transport = TerminalTransport()
            transport.paste_literal = lambda pane,text,deadline:transport.commands.append(('paste',pane,text))
            transport.send_key_tokens = lambda pane,keys,deadline:transport.commands.append(('keys',pane,keys))
            broker = OwnedTerminalBroker(transport,panes=['%1'],owner_id='host-owner')
            owner,args,tabs = self.make(Path(temp),transport,broker)
            request = dict(args,custody=broker.inspect(),text='line one\nline two',idempotency_key='paste-one')
            first = owner.execute('environment.panes.paste',request)['result']['operation']
            owner.execute('environment.panes.paste',request)
            self.assertEqual([c for c in transport.commands if c[0]=='paste'],[('paste','%1','line one\nline two')])
            self.assertEqual(first['result']['semantic_execution'],'unknown')
            self.assertEqual(first['result']['input_mode'],'paste')
            self.assertFalse(first['result']['implicit_enter'])
            result = owner.execute('environment.panes.keys',dict(args,custody=broker.inspect(),keys=['C-c','Enter'],idempotency_key='keys-one'))['result']['operation']
            self.assertEqual(result['result']['input_mode'],'keys')
            self.assertEqual(transport.commands[-1],('keys','%1',['C-c','Enter']))

    def test_privacy_permissions_and_exact_birth_fence_input_before_effects(self):
        from codex_wake.controller_tab_adapters import OwnedTerminalBroker
        from codex_wake.managed_inventory import InventoryError
        from codex_wake.controller_auth import AuthError
        with tempfile.TemporaryDirectory() as temp:
            transport = TerminalTransport()
            transport.paste_literal = lambda *args:transport.commands.append(('unexpected-paste',))
            broker = OwnedTerminalBroker(transport,panes=['%1'],owner_id='host-owner')
            owner,args,tabs = self.make(Path(temp),transport,broker)
            request = dict(args,custody=broker.inspect(),text='hello',idempotency_key='fenced')
            original = owner.authorize
            owner.authorize=lambda target,action:local_operator(target,('content.observe',))
            with self.assertRaises(AuthError):owner.execute('environment.panes.paste',request)
            owner.authorize=original
            tabs.workspaces['work']['privacy']=lambda pane:'draft'
            with self.assertRaisesRegex(InventoryError,'draft'):owner.execute('environment.panes.paste',request)
            with self.assertRaises(InventoryError):owner.execute('environment.panes.capture',args)
            tabs.workspaces['work']['privacy']=lambda pane:'safe'
            changed=dict(request,expected_pane=dict(args['expected_pane'],process_generation='reused-pid'))
            with self.assertRaisesRegex(InventoryError,'generation'):owner.execute('environment.panes.paste',changed)
            self.assertFalse(transport.commands)

    def test_private_tmux_broker_pastes_without_implicit_enter_and_sends_explicit_keys(self):
        import json
        import shutil
        import shlex
        import subprocess
        import time
        from codex_wake.controller_tab_adapters import OwnedTerminalBroker,TmuxAttachmentTransport
        executable=shutil.which('tmux')
        if executable is None:self.skipTest('tmux is not installed')
        with tempfile.TemporaryDirectory(prefix='t635-') as temp:
            socket=str(Path(temp)/'s')
            program="import os,tty;tty.setraw(0);print('READY',flush=True);exec(\"while True:\\n d=os.read(0,65536)\\n print(repr(d),flush=True)\")"
            subprocess.run([executable,'-S',socket,'new-session','-d','-s','isolated',shlex.join(['/usr/bin/python3','-u','-c',program])],check=True)
            try:
                transport=TmuxAttachmentTransport(socket,'$0')
                deadline=time.monotonic()+3
                while 'READY' not in transport.capture('%0',10,time.monotonic()+1):
                    self.assertLess(time.monotonic(),deadline,'private terminal readiness deadline')
                    time.sleep(.02)
                broker=OwnedTerminalBroker(transport,panes=['%0'],owner_id='private-test')
                custody=broker.inspect()
                broker.paste('%0','hello\nworld',expected_custody=custody)
                deadline=time.monotonic()+3
                while True:
                    text=transport.capture('%0',20,time.monotonic()+1)
                    if 'hello\\nworld' in text:break
                    self.assertLess(time.monotonic(),deadline,'literal paste observation deadline')
                    time.sleep(.02)
                self.assertNotIn('\\r',text)
                broker.keys('%0',['C-a','Enter'],expected_custody=custody)
                deadline=time.monotonic()+3
                while True:
                    text=transport.capture('%0',20,time.monotonic()+1)
                    if '\\x01\\r' in text:break
                    self.assertLess(time.monotonic(),deadline,'explicit key observation deadline')
                    time.sleep(.02)
            finally:
                subprocess.run([executable,'-S',socket,'kill-server'],check=False,capture_output=True)
