"""Family public operations over disposable real tmux; no provider launches."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from codex_wake.controller_tabs import ControllerTabs
from codex_wake.bot_families import BotFamilies


class FamilyPlacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wake-family-')
        self.root = Path(self.temp.name)
        self.tabs = ControllerTabs(self.root, workspaces={}, host='test', environment='test')
        self.source = self.tabs.execute('tabs.session.create', dict(name='source', start=True))['session']
        self.sock = self.source['server']
        # Lifecycle tests own a fixed roster; asynchronous tmux name refresh is
        # a separate behavior and can invalidate exact pre-effect snapshots.
        subprocess.run(['tmux', '-S', self.sock, 'set-window-option', '-g', 'automatic-rename', 'off'], check=True, capture_output=True)
        for bot in ('a', 'b'):
            self.call('register', bot_id=bot)
        self.call('register', bot_id='child', parent_bot_id='a', temporary=True)
    def tearDown(self):
        subprocess.run(['tmux', '-S', self.sock, 'kill-server'], capture_output=True)
        self.temp.cleanup()
    def call(self, verb, **args):
        return self.tabs.execute('tabs.family.' + verb, args)
    def open(self, bot, **args):
        return self.call('open', bot_id=bot, client_id='test', server=self.sock, argv=['/bin/sh'], **args)
    def test_background_reuse_and_contiguous_root_groups(self):
        focused = subprocess.check_output(['tmux','-S',self.sock,'display-message','-p','-t','source','#{window_id}'],text=True).strip()
        a = self.open('a'); b = self.open('b'); child = self.open('child')
        self.assertTrue(self.open('a')['reused'])
        self.assertEqual(a['binding']['attachment'], self.open('a')['binding']['attachment'])
        session = self.tabs.execute('tabs.session.show', dict(session=a['session_id']))['session']
        self.assertEqual([w['window_id'] for w in session['snapshot']['windows']],
                         [a['binding']['attachment']['window_id'], child['binding']['attachment']['window_id'], b['binding']['attachment']['window_id']])
        self.assertEqual(subprocess.check_output(['tmux','-S',self.sock,'display-message','-p','-t','source','#{window_id}'],text=True).strip(),focused)
    def test_exact_native_binding_organized_once_and_manual_move_preserved(self):
        wid = subprocess.check_output(['tmux','-S',self.sock,'new-window','-d','-P','-F','#{window_id}','-t','source','/bin/sh'],text=True).strip()
        row = next(r for r in BotFamilies(self.root,tabs=self.tabs).observations() if r['window_id']==wid)
        self.call('bind',bot_id='child',client_id='test',**{k:row[k] for k in ('workspace','window_id','pane_id')})
        opened=self.open('child')
        self.assertEqual(opened['binding']['attachment']['window_id'],wid)
        self.assertNotEqual(opened['binding']['attachment']['workspace'],row['workspace'])
        subprocess.check_call(['tmux','-S',self.sock,'move-window','-d','-s',wid,'-t','source:'])
        self.assertEqual(self.open('child')['binding']['attachment']['workspace'],row['workspace'])
    def test_adopt_failed_and_wrong_parent_never_close(self):
        self.open('child')
        from codex_wake.managed_inventory import InventoryError
        with self.assertRaises(InventoryError):
            self.call('accept',bot_id='child',client_id='test',parent_bot_id='b',result_id='r',successful=True)
        self.assertEqual(self.call('accept',bot_id='child',client_id='test',parent_bot_id='a',result_id='r',successful=False)['status'],'retained')
        self.call('adopt',bot_id='child',client_id='test')
        self.assertEqual(self.call('accept',bot_id='child',client_id='test',parent_bot_id='a',result_id='r2',successful=True)['status'],'retained')
    def idle_observer(self, workspace, state='idle'):
        import time
        from codex_wake.process import process_identity
        cfg = self.tabs.workspaces[workspace]
        def observe(timeout):
            snapshot = cfg['transport'].snapshot(time.monotonic()+timeout)
            result = {}
            for window in snapshot['windows']:
                for pane in window['panes']:
                    birth = process_identity(pane['pid'])
                    result[pane['pane_id']] = dict(fresh=True,state=state,process=dict(pid=pane['pid'],start_ticks=birth['start_time_ticks'],boot_id=birth['boot_id']))
            return result
        cfg['observer'] = observe
    def test_successful_parent_acceptance_closes_only_idle_temporary_and_empty_owned_session(self):
        opened = self.open('child')
        workspace = opened['binding']['attachment']['workspace']
        self.idle_observer(workspace, 'busy')
        args = dict(bot_id='child',client_id='test',parent_bot_id='a',result_id='r',successful=True)
        self.assertEqual(self.call('accept',**args)['status'],'retained')
        self.idle_observer(workspace)
        self.assertEqual(self.call('accept',**args)['status'],'closed')
        self.assertEqual(self.call('accept',**args)['status'],'closed')
        sessions = self.tabs.execute('tabs.session.list',{})['sessions']
        self.assertNotIn(opened['session_id'],[r['id'] for r in sessions])
        self.assertEqual(self.call('show',bot_id='child')['bot']['bot_id'],'child')
    def test_adjacent_and_exact_parent_root_navigation(self):
        a = self.open('a')
        self.call('register',bot_id='grandchild',parent_bot_id='child')
        child = self.open('child',placement='adjacent')
        grandchild = self.open('grandchild',placement='adjacent')
        self.assertEqual(child['binding']['attachment']['workspace'],a['binding']['attachment']['workspace'])
        self.assertEqual(self.call('focus',bot_id='grandchild',client_id='test',relation='parent')['bot_id'],'child')
        self.assertEqual(self.call('focus',bot_id='grandchild',client_id='test',relation='root')['bot_id'],'a')
        subprocess.check_call(['tmux','-S',self.sock,'kill-window','-t',a['binding']['attachment']['window_id']])
        self.assertEqual(self.call('focus',bot_id='grandchild',client_id='test',relation='root')['status'],'root-tab-unavailable')
        self.assertIsNotNone(BotFamilies(self.root,tabs=self.tabs).resolve_binding(self.call('show',bot_id='grandchild')['bot'],'test'))
    def test_lost_launch_reply_is_held_without_duplicate(self):
        from codex_wake.managed_inventory import InventoryError
        original = self.tabs.create_tab
        dispatched = []
        def lose_reply(args):
            result = original(args)
            dispatched.append(result)
            raise KeyboardInterrupt('lost launch reply')
        self.tabs.create_tab = lose_reply
        with self.assertRaises(KeyboardInterrupt): self.open('child')
        with self.assertRaises(InventoryError) as caught: self.open('child')
        self.assertEqual(caught.exception.code,'uncertain_effect')
        self.assertEqual(len(dispatched),1)
    def test_lost_relocation_reply_reconciles_exact_attachment_without_replay(self):
        wid = subprocess.check_output(['tmux','-S',self.sock,'new-window','-d','-P','-F','#{window_id}','-t','source','/bin/sh'],text=True).strip()
        registry = BotFamilies(self.root,tabs=self.tabs)
        row = next(r for r in registry.observations() if r['window_id']==wid)
        self.call('bind',bot_id='child',client_id='test',**{k:row[k] for k in ('workspace','window_id','pane_id')})
        cfg = self.tabs.workspaces[row['workspace']]; original = cfg['transport'].command; sent=[]
        def lose_reply(deadline,*args):
            result = original(deadline,*args)
            if args[0]=='move-window':
                sent.append(args); raise KeyboardInterrupt('lost relocation reply')
            return result
        cfg['transport'].command=lose_reply
        with self.assertRaises(KeyboardInterrupt): self.open('child')
        self.assertTrue(self.open('child')['reused'])
        self.assertEqual(len(sent),1)
    def test_another_client_gets_distinct_attachment_and_unknown_work_is_retained(self):
        first = self.open('child')
        second = self.call('open',bot_id='child',client_id='another',server=self.sock,argv=['/bin/sh'])
        self.assertNotEqual(first['binding']['attachment']['pane_id'],second['binding']['attachment']['pane_id'])
        args=dict(bot_id='child',client_id='test',parent_bot_id='a',result_id='r',successful=True)
        self.assertEqual(self.call('accept',**args)['status'],'retained')
        self.assertEqual(self.call('show',bot_id='child')['bot']['bindings'][next(iter(self.call('show',bot_id='child')['bot']['bindings']))]['attachment']['pane_id'],first['binding']['attachment']['pane_id'])
    def test_lost_close_reply_reconciles_without_second_kill(self):
        opened=self.open('child'); workspace=opened['binding']['attachment']['workspace']
        self.idle_observer(workspace)
        transport=self.tabs.workspaces[workspace]['transport']; original=transport.command; sent=[]
        def lose_reply(deadline,*args):
            result=original(deadline,*args)
            if args[0]=='kill-window':
                sent.append(args); raise KeyboardInterrupt('lost close reply')
            return result
        transport.command=lose_reply
        args=dict(bot_id='child',client_id='test',parent_bot_id='a',result_id='r',successful=True)
        with self.assertRaises(KeyboardInterrupt):self.call('accept',**args)
        self.assertEqual(self.call('accept',**args)['status'],'closed')
        self.assertEqual(len(sent),1)
    def test_parent_without_presentation_retains_lineage_and_adjacency_is_held(self):
        result=self.open('child',placement='adjacent')
        self.assertEqual(result['status'],'root-tab-unavailable')
        self.assertEqual(self.call('show',bot_id='child')['bot']['root_bot_id'],'a')
        self.assertEqual(len(self.tabs.execute('tabs.session.list',{})['sessions']),1)

    def test_cli_open_replays_original_request_after_workers_session_creation(self):
        import json
        import sys
        config=self.root/'controller-tabs.json'
        config.write_text(json.dumps(dict(schema_version=1,workspaces=dict(source=dict(
            kind='tmux',socket_path=self.sock,session_id=self.source['native_session_id'])))))
        config.chmod(0o600)
        command=[sys.executable,'-m','codex_wake.entrypoint','--wake-root',str(self.root),
                 'tabs','family','open','--bot-id','a','--client-id','cli','--server',self.sock,
                 '--argv','/bin/sh','--request-id','family-open-a','--json']
        for _ in range(2):
            value=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(value.returncode,0,value.stdout+value.stderr)
            result=json.loads(value.stdout)['result']['operation']
            self.assertEqual(result['phase'],'terminal')
