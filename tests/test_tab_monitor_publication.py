"""Public monitor publication preserves changes and bounds quiet disk writes."""
import json
import os
from pathlib import Path
import tempfile
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from codex_wake.tab_monitor import TabMonitor


class MonitorPublicationTests(unittest.TestCase):
    def test_background_owner_heartbeats_without_rewriting_unchanged_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'controller-tabs.json'
            path.write_text(json.dumps(dict(schema_version=1,workspaces={})));path.chmod(0o600)
            monitor=TabMonitor(root)
            monitor.execute('tabs.monitor.start',dict(interval=.2,stale_after=2.))
            try:
                until=time.monotonic()+3
                while True:
                    status=monitor.execute('tabs.monitor.status',{})
                    owner_record=json.loads((root/'tab-monitor'/'owner.json').read_text())
                    if status['snapshot'] and owner_record.get('last_cycle_at') is not None:
                        break
                    self.assertLess(time.monotonic(),until)
                    time.sleep(.01)
                snapshot_path=root/'tab-monitor'/'snapshot.json'
                owner_path=root/'tab-monitor'/'owner.json'
                original_snapshot=snapshot_path.stat().st_mtime_ns
                original_owner=owner_path.stat().st_mtime_ns
                original_ticks=status['monitor']['observer']['costs']['ticks']
                # Watch real atomic filesystem writes, not a mocked save helper.
                until=time.monotonic()+.7
                while owner_path.stat().st_mtime_ns==original_owner:
                    self.assertLess(time.monotonic(),until)
                    time.sleep(.01)
                self.assertEqual(snapshot_path.stat().st_mtime_ns,original_snapshot)
                current=monitor.execute('tabs.monitor.status',{})
                # A wall-clock reversal correctly marks a retained snapshot
                # stale. This process test checks monotonic publication cadence;
                # clock-controlled status tests cover freshness separately.
                self.assertEqual(current['monitor']['status'],'running')
                self.assertGreater(current['monitor']['observer']['costs']['ticks'],original_ticks)
                until=time.monotonic()+1.4
                while snapshot_path.stat().st_mtime_ns==original_snapshot:
                    self.assertLess(time.monotonic(),until)
                    time.sleep(.01)
                self.assertEqual(monitor.execute('tabs.monitor.status',{})['monitor']['status'],'running')
            finally:
                monitor.execute('tabs.monitor.stop',{})

    def test_quiet_owner_keeps_tick_cadence_until_longer_snapshot_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_WAKE_STABLE_TIME_CONFIG=''):
            root=Path(directory)
            path=root/'controller-tabs.json'
            path.write_text(json.dumps(dict(schema_version=1,workspaces={})));path.chmod(0o600)
            monitor=TabMonitor(root)
            monitor.execute('tabs.monitor.start',dict(interval=.5,stale_after=12.))
            try:
                until=time.monotonic()+3
                while True:
                    status=monitor.execute('tabs.monitor.status',{})
                    if status['snapshot'] and status['monitor']['observer']:
                        break
                    self.assertLess(time.monotonic(),until)
                    time.sleep(.02)
                first=status['snapshot']['observed_at']
                ticks=status['monitor']['observer']['costs']['ticks']
                until=time.monotonic()+9
                # Publication cadence uses monotonic time. Host wall-clock
                # corrections may move the next observation timestamp backward.
                while status['snapshot']['observed_at']==first:
                    self.assertLess(time.monotonic(),until)
                    time.sleep(.05)
                    status=monitor.execute('tabs.monitor.status',{})
                self.assertLessEqual(status['monitor']['observer']['costs']['ticks']-ticks,18,
                                     'quiet heartbeat deadline must not create a busy loop')
                self.assertEqual(status['monitor']['status'],'running')
                self.assertEqual(status['snapshot']['freshness'],'stale')
            finally:
                monitor.execute('tabs.monitor.stop',{})

    @unittest.skipUnless(shutil.which('tmux'),'tmux unavailable')
    def test_daemon_persists_full_rows_and_enabled_routing_receives_them(self):
        from codex_wake.controller_tabs import controller_tabs_from_root
        from codex_wake.terminal_routing import TerminalRouting
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_WAKE_STABLE_TIME_CONFIG=''):
            root=Path(directory);tmux=['tmux','-S',str(root/'tmux.sock')]
            subprocess.run([*tmux,'new-session','-d','-s','source','exec sleep 60'],check=True)
            subprocess.run([*tmux,'new-session','-d','-s','destination','exec sleep 60'],check=True)
            path=root/'controller-tabs.json'
            path.write_text(json.dumps(dict(schema_version=1,workspaces=dict(
                source=dict(kind='tmux',socket_path=str(root/'tmux.sock'),session_id='$0'),
                destination=dict(kind='tmux',socket_path=str(root/'tmux.sock'),session_id='$1')))));path.chmod(0o600)
            monitor=TabMonitor(root)
            try:
                monitor.execute('tabs.monitor.start',dict(interval=.2,stale_after=2.,health=False,errors=False))
                owner=controller_tabs_from_root(root)
                routing=TerminalRouting(root,tabs=owner)
                rule=routing.execute('tabs.route.save',dict(name='future',destination='destination',
                    selection=dict(field='harness',unknown=True),stability_seconds=0))['rule']
                routing.execute('tabs.route.enable',dict(rule_id=rule['id']))
                window=subprocess.check_output([*tmux,'new-window','-d','-t','source','-P','-F','#{window_id}','exec sleep 60'],text=True).strip()
                until=time.monotonic()+5
                while subprocess.check_output([*tmux,'display-message','-p','-t',window,'#{session_name}'],text=True).strip()!='destination':
                    self.assertLess(time.monotonic(),until,'enabled routing did not receive resource rows')
                    time.sleep(.02)
                until=time.monotonic()+3
                while True:
                    report=monitor.execute('tabs.monitor.status',{})
                    snapshot=report['snapshot']
                    if snapshot and snapshot.get('resource_count')==3:
                        break
                    self.assertLess(time.monotonic(),until)
                    time.sleep(.02)
                self.assertIsInstance(snapshot['resources'],list)
                self.assertEqual(len(snapshot['resources']),3)
                self.assertEqual(snapshot['freshness'],'stale')
                self.assertIn('last_formatting',report['monitor'])
            finally:
                monitor.execute('tabs.monitor.stop',{})
                subprocess.run([*tmux,'kill-server'],capture_output=True)

    def test_encoded_publication_preserves_full_rows_without_materializing_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=TabMonitor(directory)
            frame=dict(schema_version=1,origin='manual',observed_at=time.time(),resource_count=1,
                projection_revision='one',evidence_revision='one',workspaces=['fixture'],unavailable=[])
            rows=[dict(target=dict(workspace='fixture'),window=dict(window_id='@1'),
                monitor_observed_at=frame['observed_at'],monitor_unavailable=True,traits={})]
            def forbidden_loader():
                self.fail('encoded publication must not materialize rows')
            self.assertTrue(monitor.publish_observation(frame,{},resources_loader=forbidden_loader,
                resources_serializer=lambda:json.dumps(rows,allow_nan=False,separators=(',',':'))))
            self.assertNotIn('resources',frame)
            snapshot=monitor.execute('tabs.monitor.status',{})['snapshot']
            self.assertEqual(snapshot['resources'],[dict(rows[0],monitor_freshness='stale')])
            target=Path(directory)/'tab-monitor'/'snapshot.json'
            self.assertEqual(json.loads(target.read_text())['resources'],rows)
            self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_encoded_publication_failure_preserves_previous_snapshot(self):
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as directory:
            monitor=TabMonitor(directory)
            initial=dict(schema_version=1,origin='manual',observed_at=time.time(),resources=[],
                workspaces=[],unavailable=[],projection_revision='one',evidence_revision='one')
            monitor.publish_observation(initial,{})
            target=Path(directory)/'tab-monitor'/'snapshot.json'
            previous=target.read_bytes()
            frame={key:value for key,value in initial.items() if key!='resources'}
            frame['projection_revision']='two'
            # Rows fit alone; metadata pushes the complete document over1MiB.
            rows='["'+'x'*(1048576-5)+'"]'
            with self.assertRaises(InventoryError) as error:
                monitor.publish_observation(frame,{},resources_serializer=lambda:rows)
            self.assertEqual(error.exception.code,'monitor_capacity')
            self.assertEqual(target.read_bytes(),previous)
            self.assertEqual(list(target.parent.glob('.monitor-*')),[])
            frame['observed_at']=float('nan')
            with self.assertRaises(ValueError):
                monitor.publish_observation(frame,{},resources_serializer=lambda:'[]')
            self.assertEqual(target.read_bytes(),previous)
            frame['observed_at']=initial['observed_at']
            self.assertTrue(monitor.publish_observation(frame,{},resources_serializer=lambda:'[]'))

    def test_metadata_frames_are_materialized_only_for_actual_publication(self):
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as directory:
            mono=[0.];loads=[]
            monitor=TabMonitor(directory,monotonic=lambda:mono[0])
            record={}
            def frame(revision):
                return dict(schema_version=1,origin='manual',observed_at=time.time(),resource_count=1,
                    projection_revision=revision,evidence_revision=revision,workspaces=['fixture'],unavailable=[],
                    observer=dict(costs=dict(ticks=len(loads)),sources=[]))
            def loader(snapshot):
                def load():
                    loads.append(snapshot['observed_at'])
                    snapshot['resources']=[dict(target=dict(workspace='fixture'),window=dict(window_id='@1'),
                        monitor_observed_at=snapshot['observed_at'],traits={})]
                return load
            first=frame('first')
            self.assertTrue(monitor.publish_observation(first,record,resources_loader=loader(first)))
            self.assertEqual(len(loads),1)
            quiet=frame('first');mono[0]=1.
            self.assertFalse(monitor.publish_observation(quiet,record,resources_loader=loader(quiet)))
            self.assertNotIn('resources',quiet)
            self.assertEqual(len(loads),1)
            changed=frame('changed')
            self.assertTrue(monitor.publish_observation(changed,record,resources_loader=loader(changed)))
            self.assertEqual(len(loads),2)
            self.assertEqual(len(monitor.execute('tabs.monitor.status',{})['snapshot']['resources']),1)
            with self.assertRaises(InventoryError):
                monitor.publish_observation(frame('missing-loader'),record)
            self.assertEqual(len(monitor.execute('tabs.monitor.status',{})['snapshot']['resources']),1)
            mono[0]=11.
            pulse=frame('changed')
            self.assertTrue(monitor.publish_observation(pulse,record,resources_loader=loader(pulse)))
            self.assertEqual(len(loads),3)

    def test_publisher_writes_changed_evidence_immediately_before_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            mono=[0.]
            monitor=TabMonitor(directory,clock=lambda:1000.,monotonic=lambda:mono[0])
            record={}
            snapshot=dict(schema_version=1,origin='manual',observed_at=1000.,resources=[],
                workspaces=[],unavailable=[],evidence_revision='evidence-one',projection_revision='display-one',
                observer=dict(costs=dict(ticks=1),sources=[]))
            self.assertTrue(monitor.publish_observation(snapshot,record))
            target=Path(directory)/'tab-monitor'/'snapshot.json'
            written=target.stat().st_mtime_ns
            mono[0]=1.
            snapshot['observer']['costs']['ticks']=2
            self.assertFalse(monitor.publish_observation(snapshot,record))
            self.assertEqual(target.stat().st_mtime_ns,written)
            self.assertEqual(record['observer']['costs']['ticks'],2)
            snapshot.update(projection_revision='display-two')
            self.assertTrue(monitor.publish_observation(snapshot,record))
            snapshot.update(evidence_revision='evidence-two')
            self.assertTrue(monitor.publish_observation(snapshot,record))
            self.assertEqual(monitor.execute('tabs.monitor.status',{})['snapshot']['evidence_revision'],'evidence-two')
            mono[0]=6.
            self.assertFalse(monitor.publish_observation(snapshot,record))
            mono[0]=11.
            self.assertTrue(monitor.publish_observation(snapshot,record))


if __name__=='__main__':
    unittest.main()
