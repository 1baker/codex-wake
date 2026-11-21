import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from datetime import UTC, datetime
from codex_wake.cli import main

class WakeControlTests(unittest.TestCase):
    def command(self,root,*arguments):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=main(['--wake-root',str(root),*arguments,'--json'])
        return code,json.loads(out.getvalue())

    def test_pause_persists_across_cli_calls_and_resume_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            code,result=self.command(root,'pause')
            self.assertEqual(code,0)
            self.assertTrue(result['roots'][0]['paused'])
            self.assertTrue(self.command(root,'pause-status')[1]['roots'][0]['paused'])
            self.assertFalse(self.command(root,'resume')[1]['roots'][0]['paused'])

    def test_pause_blocks_actual_dispatch_and_retains_the_record(self):
        from codex_wake.records import build_record,write_record,WakePath
        from codex_wake.injector import dispatch_firing_record
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            record=build_record(predicate={'type':'not_before','due_at':'2020-01-01T00:00:00Z'},prompt='hello',cwd=Path(tmp),
                target={'transport':'tmux','pane_id':'%1','session_id':'fixture','socket_path':'/fixture'},
                            now=datetime(2025,1,1,tzinfo=UTC))
            record['status']='firing'
            path=write_record(root,record)
            self.command(root,'pause')
            runner=Mock()
            result=dispatch_firing_record(root,WakePath(path,record),runner=runner)
            self.assertEqual(result.status,'skipped')
            self.assertIn('emergency_paused',result.message)
            self.assertEqual(json.loads(path.read_text())['status'],'firing')
            self.assertEqual(runner.mock_calls,[])

    def write_wake(self,root,identifier,status='pending',uncertain=False):
        from codex_wake.records import build_record,write_record
        record=build_record(predicate={'type':'not_before','due_at':'2030-01-01T00:00:00Z'},prompt='payload',cwd=root,
                            target={'transport':'tmux','pane_id':'%1','session_id':'fixture','socket_path':'/fixture'},
                            now=datetime(2025,1,1,tzinfo=UTC))
        record.update(id=identifier,status=status)
        if uncertain:record['native_delivery']={'state':'uncertain','submission_id':'submission'}
        return write_record(root,record)

    def test_bulk_cancel_reports_uncertain_and_terminal_records_without_erasing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            self.write_wake(root,'wake_pending')
            self.write_wake(root,'wake_uncertain','firing',True)
            terminal=self.write_wake(root,'wake_done','submitted');original=terminal.read_bytes()
            code,result=self.command(root,'cancel','--all')
            self.assertEqual(code,5)
            states={x['wake_id']:x['state'] for x in result['roots'][0]['results']}
            self.assertEqual(states,{'wake_pending':'cancelled','wake_uncertain':'held','wake_done':'skipped'})
            cancelled=json.loads((root/'cancelled/wake_pending.json').read_text())
            self.assertEqual(cancelled['predicate']['due_at'],'2030-01-01T00:00:00Z')
            self.assertEqual(cancelled['events'][-1]['type'],'cancelled')
            self.assertEqual(terminal.read_bytes(),original)

    def test_registered_scope_includes_disabled_roots_and_frozen_grant_rejects_new_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);a=base/'a';b=base/'b';registry=base/'registry';registry.mkdir()
            for i,root in enumerate((a,b)):
                self.write_wake(root,'wake_'+str(i))
                (registry/(str(i)+'.json')).write_text(json.dumps({'schema_version':1,'wake_root':str(root),'enabled':False}))
            code,result=self.command(a,'pause','--all-roots','--registry-dir',str(registry),'--authorized-root',str(a))
            self.assertEqual(code,2)
            self.assertFalse((a/'emergency-control/state.json').exists())
            code,result=self.command(a,'pause','--all-roots','--registry-dir',str(registry))
            self.assertEqual(code,0)
            self.assertEqual({x['wake_root'] for x in result['roots']},{str(a),str(b)})
            self.assertTrue(all(x['paused'] for x in result['roots']))

    def test_corrupt_pause_state_blocks_dispatch_and_resume(self):
        from codex_wake.wake_control import paused
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            self.command(root,'pause')
            (root/'emergency-control/state.json').write_text('{broken')
            self.assertTrue(paused(root))
            code,result=self.command(root,'resume')
            self.assertEqual(code,5)
            self.assertIn('corrupt',result['roots'][0]['message'])

    def test_pause_reports_in_flight_admission_without_waiting_and_blocks_next_generation(self):
        import threading
        from codex_wake.wake_control import delivery_guard
        from codex_wake.records import WakeError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';entered=threading.Event();release=threading.Event()
            def admitted():
                with delivery_guard(root):
                    entered.set();release.wait(2)
            worker=threading.Thread(target=admitted);worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(self.command(root,'pause')[1]['roots'][0]['in_flight'])
                with self.assertRaises(WakeError):
                    with delivery_guard(root):pass
            finally:
                release.set();worker.join(2)
            self.assertFalse(self.command(root,'pause-status')[1]['roots'][0]['in_flight'])

    def test_new_process_observes_same_pause_and_explicit_interrupt_requires_it(self):
        import subprocess,sys,os
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            code,result=self.command(root,'interrupt')
            self.assertEqual(code,5)
            self.command(root,'pause')
            observed=subprocess.run([sys.executable,'-m','codex_wake','--wake-root',str(root),'pause-status','--json'],
                                    capture_output=True,text=True,env={**os.environ,'PYTHONPATH':'src'})
            self.assertEqual(observed.returncode,0)
            self.assertTrue(json.loads(observed.stdout)['roots'][0]['paused'])
            code,result=self.command(root,'interrupt')
            self.assertEqual(code,0)
            self.assertTrue(result['roots'][0]['interrupt_requested'])
            self.assertFalse(self.command(root,'resume')[1]['roots'][0]['interrupt_requested'])

    def test_registered_inventory_reports_unreadable_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'wake';self.write_wake(root,'wake_valid')
            (root/'pending/broken.json').write_text('{broken')
            registry=base/'registry';registry.mkdir()
            (registry/'fixture.json').write_text(json.dumps({'schema_version':1,'wake_root':str(root)}))
            code,result=self.command(root,'list','--all-roots','--registry-dir',str(registry))
            self.assertEqual(code,5)
            self.assertEqual(result['roots'][0]['inventory_errors'],['pending/broken.json'])

    def test_cancel_during_slow_predicate_cannot_resurrect_legacy_wake(self):
        from codex_wake.daemon import poll_once
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';self.write_wake(root,'wake_race')
            # Move its due time into the past, independently of wall time.
            path=root/'pending/wake_race.json';record=json.loads(path.read_text())
            record['next_attempt_at']='2020-01-01T00:00:00Z';path.write_text(json.dumps(record))
            def predicate(record,now):
                self.assertEqual(self.command(root,'cancel','wake_race')[0],0)
                return True,'ready'
            with patch('codex_wake.daemon.predicate_is_ready',side_effect=predicate):
                poll_once(root,now=datetime(2031,1,1,tzinfo=UTC),dispatch=False)
            self.assertTrue((root/'cancelled/wake_race.json').exists())
            self.assertFalse((root/'firing/wake_race.json').exists())

    def test_interrupt_reports_corrupt_submitted_inventory_as_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';(root/'submitted').mkdir(parents=True)
            (root/'submitted/owned.json').write_text('{corrupt')
            self.command(root,'pause')
            code,result=self.command(root,'interrupt')
            self.assertEqual(code,5)
            self.assertEqual(result['roots'][0]['inventory_errors'],['submitted/owned.json'])

    def test_duplicate_pause_keys_are_corrupt_not_permission_to_deliver(self):
        from codex_wake.wake_control import paused
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';self.command(root,'pause')
            (root/'emergency-control/state.json').write_text('{"version":1,"paused":true,"paused":false,"interrupt_requested":false,"revision":1,"history":[]}')
            self.assertTrue(paused(root))

    def test_effect_gate_excludes_bulk_cancel_across_os_processes(self):
        import os,select,subprocess,sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';self.write_wake(root,'wake_owned')
            source="from pathlib import Path\nimport sys\nfrom codex_wake.wake_control import delivery_guard\nwith delivery_guard(Path(sys.argv[1])):\n print('ready',flush=True)\n sys.stdin.readline()\n"
            child=subprocess.Popen([sys.executable,'-c',source,str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   text=True,env={**os.environ,'PYTHONPATH':'src'})
            try:
                self.assertTrue(select.select([child.stdout],[],[],5)[0])
                self.assertEqual(child.stdout.readline().strip(),'ready')
                self.assertTrue(self.command(root,'pause')[1]['roots'][0]['in_flight'])
                code,queued=self.command(root,'cancel','--all')
                self.assertEqual(code,0)
                self.assertEqual(queued['roots'][0]['results'],[dict(wake_id='wake_owned',state='pending',reason='delivery_in_flight')])
                self.assertTrue((root/'pending/wake_owned.json').exists())
                listed=self.command(root,'list')[1]
                self.assertEqual(listed[0]['cancellation']['state'],'pending')
                self.assertEqual(self.command(root,'cancel','wake_owned')[1]['roots'][0]['results'][0]['state'],'pending')
                # Bulk cancellation freezes only the wakes present at request time.
                self.write_wake(root,'wake_later')
            finally:
                child.communicate('\n',timeout=5)
            self.assertEqual(child.returncode,0)
            # A fresh monitor process consumes the persisted cancellation, not
            # an in-memory callback from the original cancelling process.
            observed=subprocess.run([sys.executable,'-c',
                'from pathlib import Path; import sys; from codex_wake.daemon import poll_once; poll_once(Path(sys.argv[1]),dispatch=False)',str(root)],
                capture_output=True,text=True,env={**os.environ,'PYTHONPATH':'src'},timeout=10)
            self.assertEqual(observed.returncode,0,observed.stderr)
            self.assertTrue((root/'cancelled/wake_owned.json').exists())
            self.assertTrue((root/'pending/wake_later.json').exists())
            self.assertEqual(self.command(root,'cancel','wake_owned')[1]['roots'][0]['results'],[dict(wake_id='wake_owned',state='cancelled')])

    def test_pause_keeps_marker_but_reports_observed_incompatible_worker_as_held(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            with patch('codex_wake.wake_control.worker_enforcement',return_value='upgrade_required_observed_worker'):
                code,result=self.command(root,'pause')
            self.assertEqual(code,5)
            self.assertTrue(result['roots'][0]['paused'])
            self.assertEqual(result['roots'][0]['state'],'held')

    def test_uncertain_cancellation_is_retained_without_blocking_peer_effects(self):
        from codex_wake.daemon import poll_once
        from codex_wake.wake_control import delivery_guard
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import find_record
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';path=self.write_wake(root,'wake_uncertain','firing',True)
            before=path.read_bytes()
            code,result=self.command(root,'cancel','wake_uncertain')
            self.assertEqual(code,5)
            self.assertEqual(result['roots'][0]['results'][0]['state'],'held')
            poll_once(root,dispatch=False)
            self.assertEqual(path.read_bytes(),before)
            # A request to stop this wake is not a root-wide emergency pause.
            with delivery_guard(root):pass
            runner=Mock()
            stopped=dispatch_firing_record(root,find_record(root,'wake_uncertain'),runner=runner)
            self.assertEqual(stopped.status,'skipped')
            self.assertEqual(runner.mock_calls,[])
            value=json.loads(path.read_text());value.pop('native_delivery');path.write_text(json.dumps(value))
            poll_once(root,dispatch=False)
            self.assertTrue((root/'cancelled/wake_uncertain.json').exists())

    def test_queued_cancellation_cannot_apply_to_changed_wake_identity(self):
        from codex_wake.wake_control import delivery_guard
        from codex_wake.daemon import poll_once
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';path=self.write_wake(root,'wake_changed')
            with delivery_guard(root):
                self.assertEqual(self.command(root,'cancel','wake_changed')[0],0)
            value=json.loads(path.read_text());value['target']['pane_id']='%different';path.write_text(json.dumps(value))
            poll_once(root,dispatch=False)
            self.assertTrue(path.exists())
            wake=self.command(root,'list')[1][0]
            self.assertEqual(wake['cancellation']['reason'],'cancellation_identity_changed')
            self.assertEqual(wake['status'],'pending')
