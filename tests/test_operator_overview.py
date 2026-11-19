import unittest
from codex_wake.operator_overview import OperatorOverview

class OverviewTests(unittest.TestCase):
    def test_deadline_retains_unread_rows_as_unknown_and_redacts(self):
        ticks = iter([0, 0, 2, 2, 2, 2])
        rows = [dict(managed_agent_id='a', runtime='codex', root='/work', task_id=None,
                     enrollment='enrolled', state='ready', binding_current=True),
                dict(managed_agent_id='b', runtime='grok', root='/other', task_id='task',
                     enrollment='suppressed', state='stale', binding_current=False)]
        view = OperatorOverview(None, inventory=lambda: dict(agents=rows),
            observe=lambda *a, **k: dict(state='working', fresh=True, observed_at=1,
                reason='native', evidence_kind='native_metadata', capabilities={}),
            monotonic=lambda: next(ticks, 2)).snapshot(timeout=1)
        self.assertFalse(view['complete'])
        self.assertEqual(view['agents'][1]['semantic']['reason'], 'budget_exhausted')
        self.assertEqual(view['agents'][0]['repository']['status'], 'unknown')
        self.assertNotIn('process', str(view))

    def test_model_cannot_focus_and_no_policy_cannot_focus(self):
        from codex_wake.operator_overview import OverviewError
        from codex_wake.session_permissions import Principal
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            owner = OperatorOverview(Path(directory), inventory=lambda: {'agents': []})
            for principal in (None, Principal('model')):
                with self.assertRaises(OverviewError):
                    owner.focus('a', principal=principal)
            with self.assertRaises(OverviewError):
                owner.focus('a', principal=Principal('operator', 'operator'))

    def test_navigation_plan_rejects_expired_binding(self):
        from codex_wake.operator_overview import OverviewError
        row = dict(managed_agent_id='a',runtime='codex',root='/work',conversation_id='thread',
                   enrollment='enrolled',binding_current=False)
        owner = OperatorOverview(None,inventory=lambda: {'agents':[row]}, observe=lambda *a, **k: {},
                                session_source=lambda timeout: self.fail('stale binding must hold'))
        with self.assertRaises(OverviewError): owner.navigation_plan('a')

    def test_operator_command_focuses_private_existing_tmux_with_native_protocol(self):
        import argparse
        import contextlib
        import io
        import json
        import os
        from pathlib import Path
        import shlex
        import shutil
        import socket
        import subprocess
        import sys
        import tempfile
        import time
        from unittest.mock import patch
        from codex_wake.a2a_bus import BusStore
        from codex_wake.a2a_identity import RuntimeIdentity
        from codex_wake.managed_inventory import ManagedInventory, Observation
        from codex_wake.process import process_identity
        from codex_wake.session_permissions import PermissionStore, Principal
        from codex_wake.operator_overview_commands import register_parser, run
        from test_shared_app_server import FakeConnection, result
        if not shutil.which('tmux'):
            self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            os.chmod(root,0o700)
            socket_path=root/'tmux.sock'
            script=root/'fixture.py'
            script.write_text('import ctypes,os,time\nctypes.CDLL(None).prctl(15,b"codex",0,0,0)\nopen('+repr(str(root/'pid'))+',"w").write(str(os.getpid()))\ntime.sleep(60)\n')
            command=['tmux','-S',str(socket_path)]
            subprocess.run(command+['new-session','-d','-s','owned','-c',str(root),
                shlex.join([sys.executable,str(script)])],check=True,capture_output=True)
            self.addCleanup(lambda: subprocess.run(command+['kill-server'],capture_output=True))
            try:
                deadline=time.monotonic()+5
                while not (root/'pid').exists() and time.monotonic()<deadline: time.sleep(.01)
                pid=int((root/'pid').read_text())
                pane=subprocess.check_output(command+['display-message','-p','-t','owned','#{pane_id}'],text=True).strip()
                subprocess.run(command+['select-pane','-t',pane,'-T','fixture'],check=True)
                subprocess.run(command+['new-window','-d','-t','owned','-n','other','sleep 60'],check=True)
                subprocess.run(command+['new-session','-d','-s','other','sleep 60'],check=True)
                import pty
                master,slave=pty.openpty()
                client_tty=os.ttyname(slave)
                environment={k:v for k,v in os.environ.items() if k not in ('TMUX','TMUX_PANE')}
                environment['TERM']='xterm'
                client_process=subprocess.Popen(command+['attach-session','-t','other'],stdin=slave,stdout=slave,stderr=slave,env=environment)
                self.addCleanup(lambda: client_process.poll() is None and client_process.terminate())
                self.addCleanup(lambda: os.close(master))
                self.addCleanup(lambda: os.close(slave))
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    clients=subprocess.check_output(command+['list-clients','-F','#{client_tty}'],text=True).splitlines()
                    if client_tty in clients: break
                    time.sleep(.01)
                self.assertIn(client_tty,clients)
                subprocess.run(command+['select-window','-t','owned:1'],check=True)
                native_sock=socket.socket(socket.AF_UNIX)
                self.addCleanup(native_sock.close)
                native_path=root/'native.sock'
                native_sock.bind(str(native_path))
                server=dict(codexHome=str(root/'home'))
                thread=dict(id='thread',name='fixture',cwd=str(root),modelProvider='fixture',
                            status=dict(type='idle',activeFlags=[]))
                identity=RuntimeIdentity.from_metadata(thread,server)
                process=process_identity(pid)
                from codex_wake import measurements
                clock = measurements.snapshot()
                managed=ManagedInventory(root).enroll(Observation('codex',identity.namespace,'thread',str(root),
                    'ready',clock['utc']['upper'],'native_metadata',dict(pid=pid,start_ticks=process['start_time_ticks'],
                    boot_id=process['boot_id']),[],{'inspect':'supported'},clock_observation=clock),operator=True)['agent']
                bus,capability=BusStore.configure(root/'bus',bus_id='focusfixture')
                policy=PermissionStore(root)
                operator=Principal('operator:'+bus.bus_id,'operator')
                policy.configure(dict(version=1,**{'global':{'actions':{'workspace.navigate':'deny'}}}),
                    operator,expected_revision=0)
                parser=argparse.ArgumentParser()
                register_parser(parser.add_subparsers(dest='agents_command',required=True))
                args=parser.parse_args(['focus','--managed-agent-id',managed['managed_agent_id'],
                    '--bus-root',str(bus.root),'--operator-capability',str(capability),'--tmux-socket',str(socket_path),
                    '--app-server','unix://'+str(native_path),'--client',client_tty,'--json'])
                class Protocol(FakeConnection):
                    def __init__(self): super().__init__([])
                    def recv(self,timeout):
                        sent=self.sent[-1]
                        payload=server if sent['method']=='initialize' else {'data':['thread'],'nextCursor':None} if sent['method']=='thread/loaded/list' else {'thread':thread}
                        return json.dumps(result(sent['id'],payload))
                with patch('websockets.sync.client.unix_connect',side_effect=lambda *a,**k:Protocol()):
                    with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(run(args,root),2)
                    policy.configure(dict(version=1,**{'global':{'actions':{'workspace.navigate':'allow'}}}),
                                     operator,expected_revision=1)
                    before_sessions=subprocess.check_output(command+['list-sessions','-F','#{session_id}'],text=True)
                    output=io.StringIO()
                    with contextlib.redirect_stdout(output): code=run(args,root)
                    self.assertEqual(subprocess.check_output(command+['list-sessions','-F','#{session_id}'],text=True),before_sessions)
                    self.assertEqual(code,0,output.getvalue())
                    self.assertEqual(json.loads(output.getvalue())['status'],'focused')
                    active=subprocess.check_output(command+['display-message','-p','-t','owned','#{pane_id}'],text=True).strip()
                    self.assertEqual(active,pane)
                    selected_session=subprocess.check_output(command+['list-clients','-F','#{client_tty}\t#{session_name}'],text=True).strip()
                    self.assertEqual(selected_session,client_tty+'\towned')
                    subprocess.run(command+['select-window','-t','owned:1'],check=True)
                    server['codexHome']=str(root/'changed-namespace')
                    with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(run(args,root),2)
                    active=subprocess.check_output(command+['display-message','-p','-t','owned','#{pane_id}'],text=True).strip()
                    self.assertNotEqual(active,pane)
            finally:
                subprocess.run(command+['kill-server'],capture_output=True)
                if 'client_process' in locals(): client_process.wait(timeout=3)

    def test_projection_truncation_and_model_effect_denial(self):
        from codex_wake.operator_overview_commands import execute
        from codex_wake.operator_overview import OverviewError
        rows=[dict(managed_agent_id=str(n),runtime='codex',root='/work',task_id=None,
                   enrollment='enrolled',state='stale',binding_current=False) for n in range(2)]
        calls=[]
        def observe(identity,**kwargs):
            calls.append(identity)
            return dict(state='unknown',fresh=False,observed_at=None,reason='source_unavailable',
                        capabilities={'auth-required':'unsupported'})
        owner=OperatorOverview(None,inventory=lambda:{'agents':rows},observe=observe)
        view=execute('overview',{'limit':1},None,owner=owner)
        self.assertTrue(view['truncated'])
        self.assertFalse(view['complete'])
        self.assertEqual(calls,['0'])
        self.assertEqual(view['agents'][0]['semantic']['capabilities']['auth-required'],'unsupported')
        for action,arguments in [('focus',{'managed_agent_id':'0'}),
                                 ('overview',{'operator':True}),('overview',{'limit':True})]:
            with self.subTest(action=action,arguments=arguments),self.assertRaises(OverviewError):
                execute(action,arguments,None,owner=owner)

    def test_git_identity_is_verified_and_ignores_inherited_git_environment(self):
        import os
        from pathlib import Path
        import subprocess
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subprocess.run(['git','init','-q',str(root)],check=True)
            row=dict(managed_agent_id='a',runtime='codex',root=str(root),task_id=None,
                     enrollment='enrolled',state='stale',binding_current=False)
            owner=OperatorOverview(None,inventory=lambda:{'agents':[row]},
                observe=lambda *a,**k:dict(state='unknown',fresh=False,observed_at=None,
                                          reason='source_unavailable',capabilities={}))
            with patch.dict(os.environ,{'GIT_DIR':'/nonexistent','GIT_WORK_TREE':'/wrong'}):
                repository=owner.snapshot()['agents'][0]['repository']
            self.assertEqual(repository['status'],'verified')
            self.assertEqual(repository['worktree'],str(root.resolve()))
            self.assertEqual(repository['common_dir'],str((root/'.git').resolve()))
            self.assertEqual(repository['inode'],(root/'.git').stat().st_ino)
            self.assertEqual(repository['device'],(root/'.git').stat().st_dev)
