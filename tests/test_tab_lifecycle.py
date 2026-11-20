"""Public manual lifecycle acceptance on an owned, real tmux server."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from codex_wake.controller_tab_adapters import TmuxAttachmentTransport
from codex_wake.managed_inventory import InventoryError


@unittest.skipUnless(shutil.which('tmux'), 'tmux unavailable')
class TabLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.socket = str(self.root / 'tmux.sock')
        self.tmux('new-session', '-d', '-s', 'source', 'sleep 120')
        # Bare-shell CRUD must not race the operator's interactive startup hooks.
        # This private server uses a plain POSIX shell without login/profile code.
        self.tmux('set-option','-g','default-shell','/bin/sh')
        self.tmux('set-option','-g','default-command','exec /bin/sh')
        self.tmux('set-environment','-g','-u','ENV')
        self.addCleanup(lambda: subprocess.run(['tmux', '-S', self.socket, 'kill-server'],
                                               capture_output=True))
        self.tmux('new-session', '-d', '-s', 'holding', 'sleep 120')
        self.workspaces = {
            'source': dict(kind='byobu', transport=TmuxAttachmentTransport(self.socket, '$0')),
            'holding': dict(kind='tmux', transport=TmuxAttachmentTransport(self.socket, '$1')),
        }

    def tmux(self, *args):
        return subprocess.check_output(['tmux', '-S', self.socket, *args], text=True).strip()

    def owner(self):
        from codex_wake.tab_lifecycle import TabLifecycle
        return TabLifecycle(self.root, workspaces=self.workspaces, host='test', environment='posix')

    def test_same_session_insertion_reports_and_preserves_protected_siblings(self):
        pinned = self.tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-t', '$0:', '-n', 'pinned', 'sleep 120')
        companion = self.tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-t', '$0:', '-n', 'companion', 'sleep 120')
        owner = self.owner()
        before = owner.inspect('source')
        evidence = {}
        for window in before['snapshot']['windows']:
            for pane in window['panes']:
                birth = pane['process_generation']
                evidence[pane['pane_id']] = dict(fresh=True, state='idle', process=dict(
                    pid=pane['pid'], start_ticks=birth['start_time_ticks'], boot_id=birth['boot_id']))
        # This host observation boundary supplies verified idle fixture processes.
        owner.workspaces['source'].update(pins=[pinned], observer=lambda timeout: evidence)
        args = dict(workspace='source', window=companion, destination='source', index=1,
                    expected_target=before['target'], expected_destination=before['target'])
        preview = owner.execute('tabs.move', dict(args, preview=True))
        self.assertTrue(preview['requires_force'], preview)
        self.assertIn('pinned', preview['protection'])
        self.assertEqual(preview['displaced_tabs'][0]['window_id'], pinned)
        with self.assertRaises(InventoryError) as caught:
            owner.execute('tabs.move', args)
        self.assertEqual(caught.exception.code, 'tab_protected')
        self.assertEqual(owner.inspect('source')['target'], before['target'])
        moved = owner.execute('tabs.move', dict(args, force=True))
        self.assertEqual(moved['window']['index'], 1)

    def test_shell_create_rename_focus_close_has_exact_identity_and_preserves_history(self):
        owner = self.owner()
        history = self.root / 'history.jsonl'
        history.write_text('existing synthetic conversation')
        inode = history.stat().st_ino
        before = owner.inspect('source')
        created = owner.execute('tabs.create', dict(workspace='source', expected_target=before['target'],
                                                  name='new tab', cwd=str(self.root)))
        wid = created['window']['window_id']
        self.assertEqual(created['status'], 'applied')
        renamed = owner.execute('tabs.rename', dict(workspace='source', expected_target=owner.inspect('source')['target'],
                                                    window=wid, name='renamed'))
        self.assertEqual(renamed['window']['name'], 'renamed')
        focused = owner.execute('tabs.focus', dict(workspace='source', expected_target=owner.inspect('source')['target'], window=wid))
        self.assertTrue(focused['window']['focused'])
        with self.assertRaises(InventoryError) as held:
            owner.execute('tabs.close', dict(workspace='source', expected_target=owner.inspect('source')['target'], window=wid))
        self.assertEqual(held.exception.code, 'tab_protected')
        closed = owner.execute('tabs.close', dict(workspace='source', expected_target=owner.inspect('source')['target'], window=wid, force=True))
        self.assertEqual(closed['conversation'], 'preserved')
        self.assertEqual(history.read_text(), 'existing synthetic conversation')
        self.assertEqual(history.stat().st_ino, inode)

    def test_lifecycle_pins_ignore_titles_but_input_pins_and_birth_guards_stay_exact(self):
        from codex_wake.controller_tabs import ControllerTabs
        tabs=ControllerTabs(self.root,workspaces=self.workspaces,host='test',environment='posix')
        first=next(r for r in tabs.execute('tabs.list',{})['resources'] if r['target']['workspace']=='source')
        self.tmux('select-pane','-t','@0','-T','live turn updated')
        second=next(r for r in tabs.execute('tabs.list',{})['resources'] if r['target']['workspace']=='source')
        self.assertNotEqual(first['target'],second['target'])
        self.assertEqual(first['lifecycle_target'],second['lifecycle_target'])
        owner=self.owner()
        result=owner.execute('tabs.rename',dict(workspace='source',window='@0',name='same process',expected_target=first['lifecycle_target']))
        self.assertEqual(result['status'],'applied')
        pinned=owner.inspect('source')['target']
        self.tmux('respawn-pane','-k','-t','@0','sleep 120')
        with self.assertRaises(InventoryError) as held:
            owner.execute('tabs.close',dict(workspace='source',window='@0',expected_target=pinned,force=True))
        self.assertEqual(held.exception.code,'stale_target')

    def test_stale_create_and_collision_refuse_before_new_windows(self):
        owner = self.owner()
        stale = owner.inspect('source')['target']
        first = owner.execute('tabs.create', dict(workspace='source', expected_target=stale, name='unique'))
        with self.assertRaises(InventoryError) as held:
            owner.execute('tabs.create', dict(workspace='source', expected_target=stale, name='other'))
        self.assertEqual(held.exception.code, 'stale_target')
        with self.assertRaises(InventoryError) as held:
            owner.execute('tabs.create', dict(workspace='source', expected_target=owner.inspect('source')['target'], name='unique'))
        self.assertEqual(held.exception.code, 'name_conflict')
        self.assertEqual(len(owner.inspect('source')['snapshot']['windows']), 2)
        self.assertEqual(first['window']['name'], 'unique')

    def test_park_restore_preserves_panes_processes_and_receipt_placement(self):
        owner = self.owner()
        wid = self.tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-t', '$0:', '-n', 'park me', 'sleep 120')
        original = next(w for w in owner.inspect('source')['snapshot']['windows'] if w['window_id'] == wid)
        args = dict(workspace='source', expected_target=owner.inspect('source')['target'], window=wid,
                    destination='holding', expected_destination=owner.inspect('holding')['target'])
        with self.assertRaises(InventoryError) as held:
            owner.execute('tabs.park', args)
        self.assertEqual(held.exception.code, 'tab_protected')
        preview = owner.execute('tabs.park', dict(args, preview=True))
        self.assertEqual(preview['status'], 'preview')
        self.assertTrue(preview['requires_force'])
        parked = owner.execute('tabs.park', dict(args, force=True))
        self.assertEqual(parked['window']['panes'], original['panes'])
        restored = owner.execute('tabs.restore', dict(workspace='holding',
            expected_target=owner.inspect('holding')['target'], window=wid,
            destination='source', expected_destination=owner.inspect('source')['target'],
            receipt_id=parked['receipt_id'], force=True))
        self.assertEqual(restored['window']['window_id'], wid)
        self.assertEqual(restored['window']['index'], original['index'])
        self.assertEqual(restored['window']['panes'], original['panes'])

    def test_restore_collision_preserves_parked_window_and_last_source_is_held(self):
        owner = self.owner()
        wid = self.tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-t', '$0:', '-n', 'parked', 'sleep 120')
        parked = owner.execute('tabs.park', dict(workspace='source', expected_target=owner.inspect('source')['target'],
            window=wid, destination='holding', expected_destination=owner.inspect('holding')['target'], force=True))
        self.tmux('new-window', '-d', '-t', '$0:1', '-n', 'collision', 'sleep 120')
        with self.assertRaises(InventoryError) as caught:
            owner.execute('tabs.restore', dict(workspace='holding', expected_target=owner.inspect('holding')['target'],
                window=wid, destination='source', expected_destination=owner.inspect('source')['target'],
                receipt_id=parked['receipt_id'], force=True))
        self.assertEqual(caught.exception.code, 'placement_conflict')
        self.assertIn(wid, [w['window_id'] for w in owner.inspect('holding')['snapshot']['windows']])
        self.tmux('kill-window', '-t', '$0:1')
        source_wid = owner.inspect('source')['snapshot']['windows'][0]['window_id']
        with self.assertRaises(InventoryError) as caught:
            owner.execute('tabs.move', dict(workspace='source', expected_target=owner.inspect('source')['target'],
                window=source_wid, destination='holding', expected_destination=owner.inspect('holding')['target'], force=True))
        self.assertEqual(caught.exception.code, 'tab_protected')

    def test_same_session_insertion_preserves_focus_and_pane_births(self):
        owner = self.owner()
        for name in ('second', 'third', 'fourth'):
            self.tmux('new-window', '-d', '-t', '$0:', '-n', name, 'sleep 120')
        before = owner.inspect('source')
        windows = before['snapshot']['windows']
        ids = [w['window_id'] for w in windows]
        args = dict(workspace='source', expected_target=before['target'],
                    destination='source', expected_destination=before['target'],
                    window=ids[3], index=1, force=True)
        self.assertEqual(owner.execute('tabs.move', dict(args, preview=True))['status'], 'preview')
        result = owner.execute('tabs.move', args)
        after = owner.inspect('source')['snapshot']['windows']
        self.assertEqual([w['window_id'] for w in after], [ids[0], ids[3], ids[1], ids[2]])
        self.assertEqual([w['window_id'] for w in after if w['focused']], [ids[0]])
        self.assertEqual({w['window_id']: w['panes'] for w in after},
                         {w['window_id']: w['panes'] for w in windows})
        self.assertEqual(result['window']['index'], 1)
        target = owner.inspect('source')['target']
        self.assertEqual(owner.execute('tabs.move', dict(args, expected_target=target,
                         expected_destination=target, force=False))['status'], 'noop')

    def test_other_backend_is_explicitly_unsupported(self):
        self.workspaces['source']['kind'] = 'psmux'
        owner = self.owner()
        with self.assertRaises(InventoryError) as caught:
            owner.execute('tabs.create', dict(workspace='source', expected_target=owner.inspect('source')['target'], name='unsupported'))
        self.assertEqual(caught.exception.code, 'unsupported_target')

    def test_shared_operation_journal_replays_create_and_retains_uncertain_effect(self):
        import time
        from codex_wake.controller_auth import Actor
        from codex_wake.controller_runtime import ControllerRuntime
        owner = self.owner()
        actor = Actor('owner', 'owner', 'client', 'grant', 'issuer', 'resource',
                      frozenset({'control'}), [dict(host='test', environment='posix')], time.time() + 60)
        runtime = ControllerRuntime(self.root)
        target = owner.inspect('source')['target']
        request = dict(operation_id='create-once', idempotency_key='create-once',
                       correlation_id='create-once', binding='test-owner', target=target)
        args = dict(workspace='source', expected_target=target, name='once', _request=request)
        created = runtime.execute(actor, 'tabs.create', args, authorize=lambda: actor, dispatch=owner.execute)
        replay = runtime.execute(actor, 'tabs.create', args, authorize=lambda: actor, dispatch=owner.execute)
        self.assertEqual(created['result']['operation'], replay['result']['operation'])
        self.assertEqual(len([w for w in owner.inspect('source')['snapshot']['windows'] if w['name'] == 'once']), 1)
        with self.assertRaises(InventoryError) as caught:
            runtime.execute(actor, 'tabs.create', dict(args, name='changed'), authorize=lambda: actor, dispatch=owner.execute)
        self.assertEqual(caught.exception.code, 'idempotency_conflict')

        class InterruptedTransport(TmuxAttachmentTransport):
            def command(self, deadline, *command):
                value = super().command(deadline, *command)
                if command[0] == 'new-window':
                    raise OSError('synthetic lost response after real window creation')
                return value
        self.workspaces['source']['transport'] = InterruptedTransport(self.socket, '$0')
        owner = self.owner()
        target = owner.inspect('source')['target']
        request = dict(operation_id='unknown-create', idempotency_key='unknown-create',
                       correlation_id='unknown-create', binding='test-owner', target=target)
        args = dict(workspace='source', expected_target=target, name='uncertain', _request=request)
        unknown = runtime.execute(actor, 'tabs.create', args, authorize=lambda: actor, dispatch=owner.execute)
        again = runtime.execute(actor, 'tabs.create', args, authorize=lambda: actor, dispatch=owner.execute)
        self.assertEqual(unknown['result']['operation']['execution'], 'unknown')
        self.assertEqual(unknown['result']['operation'], again['result']['operation'])
        self.assertEqual(len([w for w in owner.inspect('source')['snapshot']['windows'] if w['name'] == 'uncertain']), 1)

    def test_idle_observer_may_bind_native_descendant_of_the_pane_shell(self):
        from codex_wake.process import process_identity
        wid = self.tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-t', '$0:', '-n', 'descendant',
                        'sh -c "sleep 120 & wait"')
        pane_pid = int(self.tmux('display-message', '-p', '-t', wid, '#{pane_pid}'))
        # The child exists before tmux reports its pane, and pgrep is bounded.
        child = int(subprocess.check_output(['pgrep', '-P', str(pane_pid)], text=True).splitlines()[0])
        pane = self.tmux('display-message', '-p', '-t', wid, '#{pane_id}')
        identity = process_identity(child)
        self.workspaces['source']['observer'] = lambda timeout: {pane: dict(fresh=True, state='ready',
            process=dict(pid=child, start_ticks=identity['start_time_ticks'], boot_id=identity['boot_id']))}
        owner = self.owner()
        moved = owner.execute('tabs.move', dict(workspace='source', expected_target=owner.inspect('source')['target'],
            window=wid, destination='holding', expected_destination=owner.inspect('holding')['target']))
        self.assertEqual(moved['status'], 'applied')
        self.assertEqual(moved['window']['panes'][0]['pid'], pane_pid)

    def test_forced_close_of_last_tab_reports_removed_workspace(self):
        owner = self.owner()
        row = owner.inspect('source')
        wid = row['snapshot']['windows'][0]['window_id']
        closed = owner.execute('tabs.close', dict(workspace='source', expected_target=row['target'], window=wid, force=True))
        self.assertEqual(closed['status'], 'applied')
        self.assertEqual(closed['workspace_state'], 'removed')
        self.assertEqual(closed['conversation'], 'preserved')
        self.assertEqual(len(owner.inspect('holding')['snapshot']['windows']), 1)
