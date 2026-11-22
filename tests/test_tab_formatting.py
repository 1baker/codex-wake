"""Formatting acceptance through the public controller on a disposable tmux."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from codex_wake.controller_tab_adapters import TmuxAttachmentTransport
from codex_wake.controller_tabs import ControllerTabs


@unittest.skipUnless(shutil.which('tmux'), 'tmux unavailable')
class FormattingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.socket=str(self.root/'tmux.sock')
        self.tmux('new-session','-d','-s','fixture','-n','original name','sleep 120')
        self.addCleanup(lambda:self.tmux('kill-server',check=False))
        self.transport=TmuxAttachmentTransport(self.socket,'$0')
        self.tabs=ControllerTabs(self.root,workspaces={'work':dict(kind='tmux',transport=self.transport)},host='test',environment='local')

    def tmux(self,*args,check=True):
        return subprocess.run(['tmux','-S',self.socket,*args],capture_output=True,text=True,check=check,timeout=5).stdout

    def call(self,verb,**arguments):
        return self.tabs.execute('tabs.format.'+verb,dict(workspace='work',**arguments))

    def test_background_tab_override_survives_automatic_formatting_and_can_be_cleared(self):
        from codex_wake.tab_format_monitor import refresh_formatting

        self.tmux('new-window', '-d', '-n', 'background', 'sleep 120')
        self.call('enable')
        original = self.tmux('show-options', '-w', '-v', '-t', '@1', 'window-status-style')
        style = {'foreground': 'yellow', 'background': 'blue', 'attributes': ['bold', 'underscore']}
        target = self.tabs.format_target(workspace='work')
        self.assertEqual(self.call('override-set', window='@1', style=style,
                                   expected_target=target)['override'], style)
        self.tmux('rename-window', '-t', '@1', 'chosen name')
        refresh_formatting(self.root, self.tabs.execute('tabs.list', {}), tabs=self.tabs)
        observed = self.call('override-inspect', window='@1')
        self.assertEqual(observed['override'], style)
        self.assertEqual(observed['options']['window-status-style']['effective'],
                         'fg=yellow,bg=blue,bold,underscore')
        self.assertEqual(self.tmux('display-message', '-p', '-t', '@1', '#{window_name}').strip(),
                         'chosen name')
        self.assertEqual(self.tmux('display-message', '-p', '-t', 'fixture', '#{window_id}').strip(), '@0')
        target = self.tabs.format_target(workspace='work')
        self.assertIsNone(self.call('override-clear', window='@1', expected_target=target)['override'])
        refresh_formatting(self.root, self.tabs.execute('tabs.list', {}), tabs=self.tabs)
        self.assertEqual(self.tmux('show-options', '-w', '-v', '-t', '@1', 'window-status-style'), original)
        self.assertIsNone(self.call('override-inspect', window='@1')['override'])

    def test_rollback_restores_explicit_and_inherited_originals_and_reenable_keeps_baseline(self):
        self.tmux('set-option','-w','-t','@0','window-status-format','original #W')
        self.tmux('set-option','-g','window-status-current-style','fg=yellow,bg=black')
        before=self.tmux('show-options','-w','-t','@0')
        self.assertEqual(self.call('enable')['status'],'applied')
        self.assertIn('SH',self.tmux('show-options','-w','-v','-t','@0','window-status-format'))
        self.assertEqual(self.call('rollback')['status'],'rolled_back')
        self.assertEqual(self.tmux('show-options','-w','-t','@0'),before)
        self.tmux('set-option','-w','-t','@0','window-status-format','intervening manual')
        self.call('reenable');self.call('rollback');self.call('rollback')
        self.assertEqual(self.tmux('show-options','-w','-t','@0'),before)
        self.assertEqual(self.tmux('display-message','-p','-t','@0','#{window_name}').strip(),'original name')

    def test_enable_after_server_restart_preserves_old_baseline_and_new_rollback(self):
        self.tmux('set-option','-w','-t','@0','window-status-format','before reboot #W')
        self.call('enable')
        old=self.call('status')['record']
        self.tmux('kill-server')
        self.socket=str(self.root/'restarted.sock')
        self.tmux('new-session','-d','-s','fixture','-n','after reboot','sleep 120')
        self.transport=TmuxAttachmentTransport(self.socket,'$0')
        self.tabs.workspaces['work']['transport']=self.transport
        self.tmux('set-option','-w','-t','@0','window-status-format','after reboot #W')
        before=self.tmux('show-options','-w','-t','@0')
        panes=self.tmux('list-panes','-F','#{pane_id}:#{pane_pid}')
        self.assertEqual(self.call('enable')['status'],'applied')
        self.assertIn('SH',self.tmux('show-options','-w','-v','-t','@0','window-status-format'))
        state=json.loads((self.root/'tab-formatting'/'state.json').read_text())
        self.assertEqual(state['retired_workspaces']['work'][old['identity']],old)
        self.assertEqual(self.call('rollback')['status'],'rolled_back')
        self.assertEqual(self.tmux('show-options','-w','-t','@0'),before)
        self.assertEqual(self.tmux('list-panes','-F','#{pane_id}:#{pane_pid}'),panes)

    def test_opted_in_refresh_recovers_replacement_and_rollback_stays_disabled(self):
        from codex_wake.tab_format_monitor import refresh_formatting
        self.call('configure',policy={'recover_namespace':True})
        self.call('enable')
        original=self.call('status')['record']
        self.tmux('new-session','-d','-s','replacement','sleep 120')
        self.tabs.workspaces['work']['transport']=TmuxAttachmentTransport(self.socket,'$1')
        before=self.tmux('show-options','-w','-t','@1')
        observed=self.tabs.execute('tabs.list',{})
        unavailable=dict(observed,resources=[dict(row,monitor_unavailable=True) for row in observed['resources']])
        held=refresh_formatting(self.root,unavailable,tabs=self.tabs)
        self.assertEqual(held['workspaces'][0]['code'],'stale_target')
        self.assertEqual(self.call('status')['record'],original)
        result=refresh_formatting(self.root,observed,tabs=self.tabs)
        self.assertEqual(result['workspaces'][0]['status'],'applied',result)
        state=json.loads((self.root/'tab-formatting'/'state.json').read_text())
        self.assertEqual(state['retired_workspaces']['work'][original['identity']],original)
        self.assertEqual(self.call('rollback')['status'],'rolled_back')
        self.assertEqual(self.tmux('show-options','-w','-t','@1'),before)
        self.tmux('new-session','-d','-s','next','sleep 120')
        self.tabs.workspaces['work']['transport']=TmuxAttachmentTransport(self.socket,'$2')
        result=refresh_formatting(self.root,self.tabs.execute('tabs.list',{}),tabs=self.tabs)
        self.assertEqual(result['workspaces'][0]['status'],'disabled')
        self.assertEqual(self.tmux('show-options','-w','-v','-t','@2','window-status-format'),'')

    def test_automatic_recovery_does_not_reenable_a_retired_rollback_hold(self):
        from codex_wake.tab_format_monitor import refresh_formatting
        self.call('configure',policy={'recover_namespace':True})
        self.call('enable');self.call('rollback')
        old_transport=self.transport
        before=self.tmux('show-options','-w','-t','@0')
        self.tmux('new-session','-d','-s','replacement','sleep 120')
        self.tabs.workspaces['work']['transport']=TmuxAttachmentTransport(self.socket,'$1')
        self.call('enable')
        self.tabs.workspaces['work']['transport']=old_transport
        outcome=refresh_formatting(self.root,self.tabs.execute('tabs.list',{}),tabs=self.tabs)
        self.assertEqual(outcome['workspaces'][0]['status'],'disabled')
        self.assertEqual(self.tmux('show-options','-w','-t','@0'),before)
        self.assertFalse(self.call('status')['record']['enabled'])

    def test_changed_namespace_is_inspectable_but_refresh_and_old_intent_are_fenced(self):
        from codex_wake.managed_inventory import InventoryError
        from codex_wake.tab_format_monitor import refresh_formatting
        self.call('enable')
        pin=self.tabs.format_target(workspace='work')
        path=self.root/'tab-formatting'/'state.json'
        original=path.read_bytes()
        self.tmux('new-session','-d','-s','replacement','sleep 120')
        self.tabs.workspaces['work']['transport']=TmuxAttachmentTransport(self.socket,'$1')
        for verb in ('status','inspect'):
            inspected=self.call(verb)
            self.assertEqual(inspected['status'],'stale_target')
            self.assertFalse(inspected['namespace_matches'])
        for verb in ('rollback','resume','reenable','reset','pause'):
            with self.assertRaises(InventoryError) as error:self.call(verb)
            self.assertEqual(error.exception.code,'stale_target')
        result=refresh_formatting(self.root,self.tabs.execute('tabs.list',{}),tabs=self.tabs)
        self.assertEqual(result['workspaces'][0]['code'],'stale_target')
        with self.assertRaises(InventoryError) as error:self.call('enable',expected_target=pin)
        self.assertEqual(error.exception.code,'stale_target')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(self.tmux('show-options','-w','-v','-t','@1','window-status-format'),'')

    def test_returning_namespace_reuses_originals_and_retired_alias_is_fenced(self):
        from codex_wake.managed_inventory import InventoryError
        self.tmux('set-option','-w','-t','@0','window-status-format','original namespace #W')
        before=self.tmux('show-options','-w','-t','@0')
        self.call('enable')
        old_transport=self.transport
        self.tmux('new-session','-d','-s','replacement','sleep 120')
        self.tabs.workspaces['work']['transport']=TmuxAttachmentTransport(self.socket,'$1')
        self.call('enable')
        self.tabs.workspaces['alias']=dict(kind='tmux',transport=old_transport)
        with self.assertRaises(InventoryError) as error:
            self.tabs.execute('tabs.format.enable',dict(workspace='alias'))
        self.assertEqual(error.exception.code,'formatting_custody_conflict')
        del self.tabs.workspaces['alias']
        self.tabs.workspaces['work']['transport']=old_transport
        self.assertEqual(self.call('enable')['status'],'applied')
        self.assertEqual(self.call('rollback')['status'],'rolled_back')
        self.assertEqual(self.tmux('show-options','-w','-t','@0'),before)

    def test_public_cli_and_mcp_contract_share_reversible_operations(self):
        from codex_wake.tab_contract import tool_specs
        from codex_wake.controller_http import TOOLS
        from codex_wake.mcp_server import SPECS
        config=self.root/'controller-tabs.json'
        config.write_text(json.dumps(dict(schema_version=1,workspaces={'work':dict(kind='tmux',socket_path=self.socket,session_id='$0')})))
        config.chmod(0o600)
        import sys
        from codex_wake.tab_monitor import TabMonitor
        self.addCleanup(lambda:TabMonitor(self.root).execute('tabs.monitor.stop',{}))
        for verb in ('enable','rollback','reenable'):
            tool='wake_tabs_format_'+verb
            self.assertIn(tool,tool_specs());self.assertIn(tool,TOOLS);self.assertIn(tool,SPECS)
            result=subprocess.run([sys.executable,'-m','codex_wake.entrypoint','--wake-root',str(self.root),'tabs','format',verb,'--workspace','work','--json'],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['result']['operation']['result']['status'],'rolled_back' if verb=='rollback' else 'applied')
        from codex_wake.mcp_server import CommandRunner
        command = [sys.executable, '-m', 'codex_wake.entrypoint', '--wake-root', str(self.root),
                   'tabs', 'format']
        style = {'foreground': 'yellow', 'background': 'blue', 'attributes': ['bold']}
        flags = ['--workspace', 'work', '--window', '@0', '--json']
        applied = subprocess.run([*command, 'override-set', *flags, '--style', json.dumps(style)],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        runner = CommandRunner(wake_root=self.root)
        observed, failed = runner.call('wake_tabs_format_override_inspect',
                                       {'workspace': 'work', 'window': '@0'})
        self.assertFalse(failed, observed)
        self.assertEqual(observed['result']['override'], style)
        cleared = subprocess.run([*command, 'override-clear', *flags], capture_output=True,
                                 text=True, timeout=15)
        self.assertEqual(cleared.returncode, 0, cleared.stdout + cleared.stderr)

    def test_changing_pane_titles_do_not_block_journaled_formatting_but_birth_changes_do(self):
        from codex_wake.tab_commands import operator_execute
        from codex_wake.managed_inventory import InventoryError
        class LiveTitles(TmuxAttachmentTransport):
            counter = 0
            def snapshot(self, deadline):
                self.counter += 1
                self.command(deadline, 'select-pane', '-t', '%0', '-T', 'turn '+str(self.counter))
                return super().snapshot(deadline)
        self.tabs.workspaces['work']['transport'] = LiveTitles(self.socket, '$0')
        for verb, wanted in [('enable','applied'), ('rollback','rolled_back'), ('reenable','applied')]:
            value = operator_execute('tabs.format.'+verb, dict(workspace='work'), self.root, owner=self.tabs)
            operation = value['result']['operation']
            self.assertEqual(operation['execution'], 'completed', operation)
            self.assertEqual(operation['result']['status'], wanted)
        pinned = self.tabs.format_target(workspace='work')
        self.tmux('respawn-pane', '-k', '-t', '%0', 'sleep 120')
        with self.assertRaises(InventoryError) as error:
            self.call('rollback', expected_target=pinned)
        self.assertEqual(error.exception.code, 'stale_target')
        self.assertTrue(self.call('status')['record']['enabled'])

    def test_missing_baseline_and_failed_restoration_are_not_success(self):
        from codex_wake.managed_inventory import InventoryError
        with self.assertRaises(InventoryError) as error:self.call('rollback')
        self.assertEqual(error.exception.code,'baseline_missing')
        self.call('enable')
        original=self.transport.formatting
        def unavailable(action,arguments,deadline):
            if action=='write':raise OSError('terminal unavailable')
            return original(action,arguments,deadline)
        self.transport.formatting=unavailable
        self.assertEqual(self.call('rollback')['status'],'partial')
        self.transport.formatting=original
        self.assertEqual(self.call('rollback')['status'],'rolled_back')
        self.assertFalse(self.call('status')['record']['enabled'])
