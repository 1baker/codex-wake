import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(shutil.which('tmux'),'tmux unavailable')
class MonitorPolicyTests(unittest.TestCase):
    def test_monitor_ticks_only_explicitly_enabled_policy_through_retained_operation(self):
        from codex_wake.controller_tabs import controller_tabs_from_root
        from codex_wake.tab_monitor import TabMonitor
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);mux=root/'mux.sock'
            subprocess.run(['tmux','-S',str(mux),'new-session','-d','-s','fixture','sleep 60'],check=True)
            self.addCleanup(subprocess.run,['tmux','-S',str(mux),'kill-server'],capture_output=True)
            p=root/'controller-tabs.json';p.write_text(json.dumps(dict(schema_version=1,workspaces={'fixture':dict(kind='tmux',socket_path=str(mux),session_id='$0')})));p.chmod(0o600)
            owner=controller_tabs_from_root(root)
            self.assertEqual(owner.execute('tabs.policy.status',{})['policy']['state'],'disabled')
            owner.execute('tabs.policy.configure',dict(workspace='fixture',debounce_seconds=0))
            owner.execute('tabs.policy.enable',{})
            enabled_generation=owner.policy_target()['generation']
            monitor=TabMonitor(root)
            try:
                monitor.execute('tabs.monitor.start',dict(interval=.3,probe_timeout=.3,stale_after=2,cycle_timeout=1))
                deadline=time.monotonic()+6
                while True:
                    status=monitor.execute('tabs.monitor.status',{})
                    operation=status['monitor'].get('last_policy_operation')
                    if operation:break
                    self.assertLess(time.monotonic(),deadline,status)
                    time.sleep(.02)
                self.assertEqual(operation['execution'],'completed',operation)
                policy=owner.execute('tabs.policy.status',{})['policy']
                if policy['last_reason']=='clock_regressed':
                    # Guest UTC may step during this real-process test. The
                    # safety pause must invalidate the old operator pin once.
                    self.assertEqual(policy['state'],'paused')
                    self.assertEqual(policy['control_revision'],int(enabled_generation)+1)
                else:
                    self.assertEqual(policy['state'],'enabled')
                    self.assertEqual(str(policy['control_revision']),enabled_generation,
                                     'Background ticks must not invalidate an operator pause pin.')
                    self.assertEqual(policy['last_reason'],'unqualified_observations')
                owner.execute('tabs.policy.disable',{})
                self.assertEqual(owner.execute('tabs.policy.status',{})['policy']['state'],'disabled')
                self.assertNotEqual(owner.policy_target()['generation'],enabled_generation)
            finally:
                monitor.execute('tabs.monitor.stop',{})
