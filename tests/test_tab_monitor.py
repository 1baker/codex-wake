import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


class TabMonitorTests(unittest.TestCase):
    def test_uncertain_or_expired_clock_does_not_rebase_a_saved_observation(self):
        from codex_wake.tab_monitor import TabMonitor
        anchor = dict(epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                      counter=1000, frequency=1000, rate_ppm=0)
        current = [dict(utc=None, reason='authenticated_counter_only', counter=anchor)]
        provider = lambda: current[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'controller-tabs.json'
            config.write_text(json.dumps(dict(schema_version=1, workspaces={})))
            config.chmod(0o600)
            TabMonitor(root, clock=lambda:1000., clock_provider=provider).execute('tabs.monitor.refresh', {})
            cases = [('unavailable', None), ('unauthenticated', dict(counter=anchor))]
            for name, changes in (
                    ('rollback', dict(counter=500)),
                    ('epoch', dict(epoch='21e310d8-f6ac-42de-ac42-f1bc34090131')),
                    ('frequency', dict(frequency=2000)),
                    ('invalid_rate', dict(rate_ppm=6000)),
                    ('expired', dict(counter=22000))):
                cases.append((name, dict(utc=None, reason='authenticated_counter_only',
                                         counter=dict(anchor, **changes))))
            for name, sample in cases:
                with self.subTest(name=name):
                    current[0] = sample
                    reader = TabMonitor(root, clock=lambda:1000., clock_provider=provider)
                    self.assertEqual(reader.execute('tabs.monitor.status', {})['snapshot']['freshness'], 'stale')

    def test_default_monitor_expires_from_stable_time_without_waiting_for_wall_time(self):
        from codex_wake.tab_monitor import TabMonitor
        counter = [1000]
        def clock_provider():
            return dict(utc=None, reason='authenticated_counter_only', counter=dict(
                epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                counter=counter[0], frequency=1000, rate_ppm=0))
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, CODEX_WAKE_STABLE_TIME_CONFIG='/host-clock.json'), patch(
                'codex_wake.native_clock.snapshot', side_effect=clock_provider):
            root = Path(directory)
            config = root/'controller-tabs.json'
            config.write_text(json.dumps(dict(schema_version=1, workspaces={})))
            config.chmod(0o600)
            TabMonitor(root).execute('tabs.monitor.refresh', {})
            counter[0] = 22000  # 21 elapsed seconds; default freshness window is20.
            self.assertEqual(TabMonitor(root).execute('tabs.monitor.status', {})['snapshot']['freshness'], 'stale')

    def test_qualified_freshness_survives_guest_wall_rollback_across_readers(self):
        from codex_wake.tab_monitor import TabMonitor
        wall = [1000.0]
        counter = [1000]
        def clock_provider():
            return dict(utc=None, reason='authenticated_counter_only', counter=dict(
                epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                counter=counter[0], frequency=1000, rate_ppm=0))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'controller-tabs.json'
            config.write_text(json.dumps(dict(schema_version=1, workspaces={})))
            config.chmod(0o600)
            writer = TabMonitor(root, clock=lambda: wall[0], clock_provider=clock_provider)
            writer.execute('tabs.monitor.refresh', {})
            wall[0] = 993.0
            counter[0] = 2000
            reader = TabMonitor(root, clock=lambda: wall[0], clock_provider=clock_provider)
            self.assertEqual(reader.execute('tabs.monitor.status', {})['snapshot']['freshness'], 'fresh')

    def test_public_refresh_is_derived_read_only_observation(self):
        from codex_wake.tab_monitor import TabMonitor
        if not shutil.which('tmux'):
            self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sock=root/'tmux.sock'
            tmux=['tmux','-S',str(sock)]
            subprocess.run([*tmux,'new-session','-d','-s','fixture','printf KEEP_DRAFT; exec sleep 60'],check=True)
            try:
                path=root/'controller-tabs.json'
                path.write_text(json.dumps(dict(schema_version=1,workspaces=dict(fixture=dict(kind='tmux',socket_path=str(sock),session_id='$0')))))
                path.chmod(0o600)
                until=time.monotonic()+2
                while 'KEEP_DRAFT' not in subprocess.check_output([*tmux,'capture-pane','-p','-t','%0'],text=True):
                    self.assertLess(time.monotonic(),until);time.sleep(.01)
                before=subprocess.check_output([*tmux,'capture-pane','-p','-t','%0'],text=True)
                owner=TabMonitor(root,clock=lambda:1000.)
                result=owner.execute('tabs.monitor.refresh',{})
                self.assertEqual(result['snapshot']['freshness'],'fresh')
                self.assertEqual(result['snapshot']['resources'][0]['target']['workspace'],'fixture')
                self.assertFalse(result['application_effects'])
                self.assertEqual(before,subprocess.check_output([*tmux,'capture-pane','-p','-t','%0'],text=True))
                self.assertEqual(owner.execute('tabs.monitor.status',{})['snapshot']['freshness'],'fresh')
            finally:
                subprocess.run([*tmux,'kill-server'],check=True)

    def test_one_background_owner_reconnect_and_force_loss_are_observable(self):
        import signal
        from codex_wake.tab_monitor import TabMonitor
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_WAKE_STABLE_TIME_CONFIG=''):
            root=Path(directory)
            (root/'controller-tabs.json').write_text(json.dumps(dict(schema_version=1,workspaces={})))
            (root/'controller-tabs.json').chmod(0o600)
            owner=TabMonitor(root)
            started=owner.execute('tabs.monitor.start',dict(interval=.2,probe_timeout=.2,stale_after=.5,cycle_timeout=1))
            pid=started['monitor']['process']['pid']
            try:
                self.assertEqual(started['monitor']['status'],'running')
                duplicate=TabMonitor(root).execute('tabs.monitor.start',{})
                self.assertEqual(duplicate['monitor']['process']['pid'],pid)
                self.assertTrue(duplicate['already_running'])
                until=time.monotonic()+3
                while not owner.execute('tabs.monitor.status',{})['snapshot']:
                    self.assertLess(time.monotonic(),until);time.sleep(.02)
                live = TabMonitor(root).execute('tabs.monitor.status',{})
                self.assertEqual(live['monitor']['status'], 'running')
                self.assertEqual(live['snapshot']['freshness'], 'stale')
                self.assertEqual(live['snapshot']['freshness_basis'], 'clock_continuity_unavailable')
                os.kill(pid,signal.SIGKILL)
                until=time.monotonic()+2
                while owner.execute('tabs.monitor.status',{})['monitor']['status']=='running':
                    self.assertLess(time.monotonic(),until);time.sleep(.02)
                lost=TabMonitor(root).execute('tabs.monitor.status',{})
                self.assertEqual(lost['monitor']['status'],'lost')
                self.assertEqual(lost['snapshot']['freshness'],'stale')
                self.assertTrue(owner.execute('tabs.monitor.stop',{})['already_stopped'])
            finally:
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:os.waitpid(pid,0)
                except ChildProcessError:pass

    def test_slow_bridge_is_bounded_while_other_workspace_is_observed(self):
        import sys
        from codex_wake.tab_monitor import TabMonitor
        if not shutil.which('tmux'):self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sock=root/'tmux.sock';marker=root/'slow.pid'
            tmux=['tmux','-S',str(sock)]
            subprocess.run([*tmux,'new-session','-d','-s','fixture','exec sleep 60'],check=True)
            bridge=root/'slow.py'
            bridge.write_text('import os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(30)\n')
            config=dict(schema_version=1,workspaces=dict(a_slow=dict(kind='psmux',bridge_command=[sys.executable,str(bridge)],bridge_generation='fixture'),
                        z_good=dict(kind='tmux',socket_path=str(sock),session_id='$0')))
            (root/'controller-tabs.json').write_text(json.dumps(config));(root/'controller-tabs.json').chmod(0o600)
            try:
                owner=TabMonitor(root)
                began=time.monotonic();result=owner.execute('tabs.monitor.refresh',{})
                self.assertLess(time.monotonic()-began,4)
                self.assertEqual(result['snapshot']['resources'][0]['target']['workspace'],'z_good')
                self.assertTrue(result['snapshot']['unavailable'])
                self.assertEqual(result['snapshot']['status'],'partial')
                if marker.exists():
                    pid=int(marker.read_text())
                    until=time.monotonic()+1
                    while Path('/proc',str(pid)).exists():
                        self.assertLess(time.monotonic(),until,'slow bridge process leaked')
                        time.sleep(.01)
            finally:
                subprocess.run([*tmux,'kill-server'],check=True)

    def test_graceful_stop_and_stale_traits_reject_unrelated_owner_record(self):
        from codex_wake.tab_monitor import TabMonitor
        from codex_wake.process import process_identity
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'controller-tabs.json';path.write_text(json.dumps(dict(schema_version=1,workspaces={})));path.chmod(0o600)
            owner=TabMonitor(root)
            started=owner.execute('tabs.monitor.start',dict(interval=.2,probe_timeout=.2,stale_after=.5,cycle_timeout=1))
            pid=started['monitor']['process']['pid']
            try:
                stopped=TabMonitor(root).execute('tabs.monitor.stop',dict(timeout=3))
                self.assertEqual(stopped['monitor']['status'],'stopped')
                self.assertTrue(stopped['stop_requested'])
                birth=process_identity(os.getpid())
                owner_path=root/'tab-monitor/owner.json'
                owner_path.write_text(json.dumps(dict(state='running',generation='invalid',process=dict(pid=os.getpid(),start_ticks=birth['start_time_ticks'],boot_id=birth['boot_id']))));owner_path.chmod(0o600)
                self.assertEqual(owner.execute('tabs.monitor.stop',{})['monitor']['status'],'lost')
                snapshot=root/'tab-monitor/snapshot.json'
                snapshot.write_text(json.dumps(dict(observed_at=time.time()-2,origin='manual',projection_revision='old-display',evidence_revision='old-evidence',resources=[dict(projection_revision='old-tab',evidence_revision='old-tab-evidence',monitor_observed_at=time.time()-2,traits=dict(activity=dict(value='running',status='observed',source='native',observed_at=time.time()-2,freshness='fresh')))])));snapshot.chmod(0o600)
                result=owner.execute('tabs.monitor.status',{})
                self.assertEqual(result['snapshot']['freshness'],'stale')
                self.assertNotIn('projection_revision',result['snapshot'])
                self.assertNotIn('evidence_revision',result['snapshot']['resources'][0])
                self.assertEqual(result['snapshot']['resources'][0]['traits']['activity']['freshness'],'stale')
            finally:
                try:os.waitpid(pid,os.WNOHANG)
                except ChildProcessError:pass
