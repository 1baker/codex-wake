"""Host-managed formatting starts the existing monitor without a second command."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from codex_wake.tab_monitor import TabMonitor


@unittest.skipUnless(shutil.which('tmux'), 'tmux unavailable')
class FormattingAutostartTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.socket=str(self.root/'tmux.sock')
        self.tmux('new-session','-d','-s','fixture','exec sleep 90')
        self.addCleanup(lambda:self.tmux('kill-server',check=False))
        self.monitor=TabMonitor(self.root)
        self.addCleanup(lambda:self.monitor.execute('tabs.monitor.stop',{}))
        config=self.root/'controller-tabs.json'
        config.write_text(json.dumps(dict(schema_version=1,workspaces={'work':dict(kind='tmux',socket_path=self.socket,
            session_id='$0',evidence_scope='disposable_fixture',privacy='safe')})));config.chmod(0o600)

    def tmux(self,*args,check=True):
        return subprocess.run(['tmux','-S',self.socket,*args],text=True,capture_output=True,check=check,timeout=5).stdout

    def cli(self,*args):
        result=subprocess.run([sys.executable,'-m','codex_wake.entrypoint','--wake-root',str(self.root),
                               'tabs','format',*args,'--json'],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        value=json.loads(result.stdout)
        return value['result']['operation']['result'] if 'operation' in value.get('result',{}) else value

    def test_one_enable_and_reenable_command_reuses_monitor_and_updates_new_tabs(self):
        enabled=self.cli('enable','--workspace','work')
        self.assertEqual(enabled['monitor']['status'],'running')
        self.assertLessEqual(enabled['monitor']['interval'],5)
        self.assertNotIn('snapshot',enabled['monitor'])
        before=self.monitor.execute('tabs.monitor.status',{})['monitor']['process']
        self.assertIsNotNone(before)
        self.tmux('new-window','-d','-t','$0','-n','later error',"printf 'ERROR: test turn failed\\n'; exec sleep 60")
        until=time.monotonic()+12
        while True:
            label=self.tmux('show-options','-w','-v','-t','@1','window-status-format')
            if 'ERR' in label:break
            self.assertLess(time.monotonic(),until,'monitor never projected later tab error')
            time.sleep(.05)
        self.cli('rollback','--workspace','work')
        self.assertEqual(self.monitor.execute('tabs.monitor.status',{})['monitor']['process'],before)
        reenabling=self.cli('reenable','--workspace','work')
        self.assertEqual(reenabling['monitor']['status'],'running')
        self.assertTrue(reenabling['monitor']['already_running'])
        self.assertEqual(self.monitor.execute('tabs.monitor.status',{})['monitor']['process'],before)

    def test_monitor_started_before_configured_socket_discovers_it_when_created(self):
        # Config is fixed before startup; only native socket availability changes.
        self.tmux('kill-server')
        self.socket=str(self.root/'late.sock')
        config=self.root/'controller-tabs.json'
        config.write_text(json.dumps(dict(schema_version=1,workspaces=dict(work=dict(
            kind='tmux',socket_path=self.socket,session_id='$0')))))
        config.chmod(0o600)
        self.monitor.execute('tabs.monitor.start',dict(interval=.2))
        self.tmux('new-session','-d','-s','late','-n','later terminal','sleep 60')
        from codex_wake.tab_restore_marker import mark_restored
        mark_restored(lambda _, *args: self.tmux(*args).strip(), None,
                      dict(session='late', session_id='$0', window_id='@0', pane_id='%0',
                           index=0, title='later terminal', placeholder=None))
        # Discovery plus projection may span two configured whole cycles.
        # This is a readiness assertion, not a latency benchmark.
        budget=self.monitor.execute('tabs.monitor.status',{})['monitor']['settings']['cycle_timeout']
        deadline=time.monotonic()+2*budget
        while True:
            shown=self.tmux('show-options','-w','-v','-t','@0','window-status-format')
            if 'SH' in shown:break
            self.assertLess(time.monotonic(),deadline,'startup monitor never discovered the late terminal socket')
            time.sleep(.05)
        self.assertEqual(self.tmux('display-message','-p','-t','@0','#{window_name}').strip(),'later terminal')
        self.assertIn('later terminal ↻', self.tmux('display-message', '-p', '-t', '%0', shown.strip()))

    def test_socket_appearing_during_observer_construction_is_discovered(self):
        from unittest.mock import patch
        from codex_wake.controller_tabs import controller_tabs_from_root
        from codex_wake.tab_observer import TabObserver
        self.tmux('kill-server')
        self.socket=str(self.root/'construction.sock')
        config=self.root/'controller-tabs.json'
        config.write_text(json.dumps(dict(schema_version=1,workspaces=dict(work=dict(
            kind='tmux',socket_path=self.socket,session_id='$0')))))
        config.chmod(0o600)
        def terminal_starts_after_qualification(*args,**kwargs):
            # Delegate every qualification decision to the real owner. Only the
            # external terminal-start event is scheduled at this startup boundary.
            owner=controller_tabs_from_root(*args,**kwargs)
            if not Path(self.socket).exists():
                self.tmux('new-session','-d','-s','late','-n','later terminal','sleep 60')
            return owner
        with patch('codex_wake.controller_tabs.controller_tabs_from_root',
                   side_effect=terminal_starts_after_qualification):
            observer=TabObserver(self.root)
        self.addCleanup(observer.close)
        snapshot=observer.tick(deadline=time.monotonic()+2)
        from codex_wake.tab_format_monitor import refresh_formatting
        refresh_formatting(self.root,snapshot,tabs=observer.owner,deadline=time.monotonic()+2)
        self.assertIn('SH',self.tmux('show-options','-w','-v','-t','@0','window-status-format'))
        self.assertEqual(snapshot['resource_count'],1,snapshot['unavailable'])
        self.assertEqual(snapshot['resources'][0]['target']['workspace'],'work')
        self.assertEqual(self.tmux('display-message','-p','-t','@0','#{window_name}').strip(),'later terminal')

    def test_injected_owner_and_global_optout_do_not_start_background_discovery(self):
        from codex_wake.controller_tabs import controller_tabs_from_root, ControllerTabs
        factory=controller_tabs_from_root(self.root)
        injected=ControllerTabs(self.root,workspaces=factory.workspaces,host=factory.host,environment=factory.environment)
        result=injected.execute('tabs.format.enable',dict(workspace='work'))
        self.assertEqual(result['status'],'applied')
        self.assertNotIn('monitor',result)
        self.assertEqual(self.monitor.execute('tabs.monitor.status',{})['monitor']['status'],'inactive')
        factory.execute('tabs.format.configure',dict(scope='global',policy={'enabled':False}))
        result=factory.execute('tabs.format.enable',dict(workspace='work'))
        self.assertEqual(result['status'],'disabled')
        self.assertEqual(self.monitor.execute('tabs.monitor.status',{})['monitor']['status'],'inactive')

    def test_monitor_start_failure_is_partial_instead_of_one_shot_success(self):
        from codex_wake.controller_tabs import controller_tabs_from_root
        owner=controller_tabs_from_root(self.root)
        self.root.chmod(0o755)
        try:
            result=owner.execute('tabs.format.enable',dict(workspace='work'))
        finally:
            self.root.chmod(0o700)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['monitor']['status'],'unavailable')
        self.assertIn('monitor_state_unavailable',[failure['code'] for failure in result['failures']])
        self.assertEqual(self.monitor.execute('tabs.monitor.status',{})['monitor']['status'],'inactive')
