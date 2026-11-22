"""Durable schedule behavior through registration/inspection and polling."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from codex_wake.cli import run
from codex_wake.records import all_records

THREAD = '11111111-1111-4111-8111-111111111111'
def request(**changes):
    value = dict(idempotency_key='twice', thread_id=THREAD, prompt='Check status', session_mode='background',
        cadence=dict(kind='interval', seconds=43200, start_at='2033-05-18T03:33:20Z'),
        end=dict(kind='count', count=3), missed=dict(policy='latest', max_lateness_seconds=86400),
        overlap=dict(policy='queue', limit=2), delivery_window_seconds=3600)
    value.update(changes)
    return value

class RecurringSchedules(unittest.TestCase):
    def cli(self, root, *args):
        out = io.StringIO()
        with patch("codex_wake.sessions.observe", return_value={"complete": False, "sessions": []}), contextlib.redirect_stdout(out):
            code = run(['--wake-root', str(root), 'schedules', *args])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())
    def test_interval_occurrences_survive_restart_without_rearming_or_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); spec=root/'request.json'; spec.write_text(json.dumps(request()))
            registered=self.cli(root, 'register', '--request', str(spec), '--codex-path', sys.executable)
            self.assertEqual(registered['session_mode'], 'background')
            self.assertFalse(registered['armed'])
            from codex_wake.recurring_schedules import poll_schedules
            clock={'utc': {'lower':2000000000,'upper':2000000000,'status':'network','sources':['clock-a','clock-b']}, 'counter':None}
            poll_schedules(root, clock)
            first=self.cli(root, 'show', registered['id'])
            self.assertEqual(len(first['occurrences']),1)
            self.assertEqual(first['occurrences'][0]['due_at'],'2033-05-18T03:33:20Z')
            poll_schedules(root, clock)
            self.assertEqual(len(all_records(root)),1)
            self.assertEqual(self.cli(root, 'show', registered['id'])['occurrences'],first['occurrences'])
            poll_schedules(root, {'utc':dict(clock['utc'],lower=2000043200,upper=2000043200),'counter':None})
            self.assertEqual(len(self.cli(root,'show',registered['id'])['occurrences']),2)
    def test_unconfirmed_submission_does_not_block_an_independent_schedule_after_restart(self):
        from codex_wake.recurring_schedules import poll_schedules
        from codex_wake.records import replace_record

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / 'request.json'
            clock = {'utc': {'lower': 2000000000, 'upper': 2000000000,
                             'status': 'network', 'sources': ['clock-a', 'clock-b']}, 'counter': None}
            spec.write_text(json.dumps(request()))
            first = self.cli(root, 'register', '--request', str(spec), '--codex-path', sys.executable)
            poll_schedules(root, clock)
            wake, = all_records(root)
            replace_record(root, wake, dict(wake.record, status='firing',
                native_delivery={'state': 'uncertain'},
                runtime_observation={'state': 'unavailable', 'reason': 'attachment_lost'}))

            spec.write_text(json.dumps(request(idempotency_key='independent')))
            second = self.cli(root, 'register', '--request', str(spec), '--codex-path', sys.executable)
            with patch('codex_wake.recurring_schedules.scheduler_generation', return_value={'pid': 1}):
                poll_schedules(root, clock)
                poll_schedules(root, clock)

            first_now = self.cli(root, 'show', first['id'])
            self.assertEqual(first_now['state'], 'enabled')
            self.assertEqual(first_now['occurrences'][0]['reconciliation_reason'], 'delivery_outcome_unknown')
            self.assertEqual(first_now['occurrences'][0]['wake_id'], wake.record['id'])
            self.assertEqual(first_now['delivery']['uncertain_occurrences'][0]['reconciliation'],
                {'reason': 'delivery_outcome_unknown', 'command': ['native', 'reconcile', wake.record['id']]})
            self.assertEqual(self.cli(root, 'show', second['id'])['occurrences'][0]['state'], 'pending')
            self.assertEqual(len(all_records(root)), 2)

    def test_missing_explicit_mode_rejected_without_creating_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); spec=root/'request.json'; value=request();value.pop('session_mode');spec.write_text(json.dumps(value))
            from codex_wake.records import WakeError
            with self.assertRaisesRegex(WakeError,'session_mode'):
                self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
    def test_downtime_counts_misses_and_latest_keeps_original_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); spec=root/'request.json'
            spec.write_text(json.dumps(request(delivery_window_seconds=172800, missed=dict(policy='latest',max_lateness_seconds=172800))))
            registered=self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
            from codex_wake.recurring_schedules import poll_schedules
            clock={'utc':{'lower':2000086400,'upper':2000086400,'status':'network','sources':['a','b']},'counter':None}
            poll_schedules(root,clock)
            value=self.cli(root,'show',registered['id'])
            self.assertEqual([x['state'] for x in value['occurrences']],['coalesced','coalesced','pending'])
            self.assertEqual(value['next_index'],3)
            self.assertEqual(len(all_records(root)),1)
            self.assertEqual(value['occurrences'][-1]['due_at'],'2033-05-19T03:33:20Z')
    def test_daemon_registers_due_occurrence_and_cancel_preserves_history(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); spec=root/'request.json'; spec.write_text(json.dumps(request()))
            registered=self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
            from codex_wake.daemon import poll_once
            clock={'utc':{'lower':2000000000,'upper':2000000000,'status':'network','sources':['a','b']},'counter':None}
            with patch('codex_wake.native_clock.snapshot',return_value=clock):
                poll_once(root,dispatch=False)
            self.assertEqual(len(all_records(root)),1)
            value=request();value['cadence']['seconds']=86400;spec.write_text(json.dumps(value))
            changed=self.cli(root,'revise',registered['id'],'--request',str(spec),'--expected-revision','1','--codex-path',sys.executable)
            self.assertEqual(changed['revision'],2)
            self.assertEqual(changed['occurrences'][0]['due_at'],'2033-05-18T03:33:20Z')
            cancelled=self.cli(root,'cancel',registered['id'],'--expected-revision','2')
            self.assertEqual(cancelled['state'],'cancelled')
            self.assertEqual(all_records(root)[0].record['status'],'cancelled')
            with patch('codex_wake.native_clock.snapshot',return_value=clock):
                poll_once(root,dispatch=False)
            self.assertEqual(len(all_records(root)),1)
    def test_native_mcp_schedule_tools_bind_exact_caller_and_hide_peer(self):
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as d:
            runner=CommandRunner(wake_root=Path(d))
            meta=dict(threadId=THREAD,sessionId=THREAD,callId='schedule',**{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='test-turn')})
            with patch('codex_wake.app_server.resolve_codex_cmd',return_value=sys.executable), patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
                value,failed=runner.call('wake_schedules_register',dict(caller_thread_id=THREAD,request=request()),native_context=meta)
            self.assertFalse(failed,value)
            self.assertFalse(value['armed'])
            other='22222222-2222-4222-8222-222222222222'
            othermeta=dict(threadId=other,sessionId=other,callId='peer',**{'x-codex-turn-metadata':dict(thread_id=other,session_id=other,turn_id='test-turn')})
            denied,failed=runner.call('wake_schedules_show',dict(caller_thread_id=other,schedule_id=value['id']),native_context=othermeta)
            self.assertTrue(failed,denied)
    def test_large_prompt_backlog_remains_inspectable_without_copying_prompt_per_occurrence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); spec=root/'request.json'
            value=request(prompt='x'*32000,cadence=dict(kind='interval',seconds=1,start_at='2033-05-18T03:33:20Z'),end=dict(kind='count',count=130),missed=dict(policy='latest',max_lateness_seconds=600),delivery_window_seconds=600)
            spec.write_text(json.dumps(value))
            registered=self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
            from codex_wake.recurring_schedules import poll_schedules
            poll_schedules(root,{'utc':{'lower':2000000129,'upper':2000000129,'status':'network','sources':['a','b']},'counter':None})
            saved=self.cli(root,'show',registered['id'])
            self.assertEqual(len(saved['occurrences']),130)
            self.assertEqual(saved['request']['prompt'],'x'*32000)
    def test_ordinary_poll_jitter_does_not_turn_skip_policy_into_skip_every_check(self):
        from codex_wake.recurring_schedules import poll_schedules
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); spec=root/'request.json';value=request(cadence=dict(kind='interval',seconds=60,start_at='2033-05-18T03:34:20Z'),missed=dict(policy='skip',max_lateness_seconds=300));spec.write_text(json.dumps(value))
            saved=self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
            def clock(now):return {'utc':{'lower':now,'upper':now,'status':'network','sources':['a','b']},'counter':None}
            poll_schedules(root,clock(2000000000))
            poll_schedules(root,clock(2000000060.1))
            self.assertEqual(self.cli(root,'show',saved['id'])['occurrences'][0]['state'],'pending')
    def test_missed_latest_does_not_coalesce_an_on_time_overlap_queue(self):
        from codex_wake.recurring_schedules import poll_schedules
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);spec=root/'request.json';spec.write_text(json.dumps(request(cadence=dict(kind='interval',seconds=60,start_at='2033-05-18T03:33:20Z'),end=dict(kind='count',count=4),missed=dict(policy='latest',max_lateness_seconds=600),delivery_window_seconds=600)))
            saved=self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
            for now in (2000000000,2000000060,2000000120):
                poll_schedules(root,{'utc':{'lower':now,'upper':now,'status':'network','sources':['a','b']},'counter':None})
            self.assertEqual([x['state'] for x in self.cli(root,'show',saved['id'])['occurrences']],['pending','queued','queued'])
    def test_revising_to_old_one_second_cadence_is_bounded(self):
        import subprocess
        from codex_wake.recurring_schedules import poll_schedules
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);spec=root/'request.json';spec.write_text(json.dumps(request()))
            saved=self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
            poll_schedules(root,{'utc':{'lower':2000000000,'upper':2000000000,'status':'network','sources':['a','b']},'counter':None})
            value=request(cadence=dict(kind='interval',seconds=1,start_at='2000-01-01T00:00:00Z'));spec.write_text(json.dumps(value))
            import os
            env=dict(os.environ)
            for key in ('HOME','CODEX_HOME','XDG_CONFIG_HOME','XDG_STATE_HOME','XDG_RUNTIME_DIR'):
                directory=root/key.lower();directory.mkdir();env[key]=str(directory)
            env.pop('TMUX',None);env.pop('CODEX_THREAD_ID',None)
            result=subprocess.run([sys.executable,'-m','codex_wake','--wake-root',str(root),'schedules','revise',saved['id'],'--request',str(spec),'--expected-revision','1','--codex-path',sys.executable],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['next_due_at'],'2033-05-18T03:33:21Z')
    def test_confirmed_monitor_restart_applies_skip_to_a_missed_occurrence(self):
        from codex_wake.recurring_schedules import poll_schedules
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);spec=root/'request.json';spec.write_text(json.dumps(request(cadence=dict(kind='interval',seconds=60,start_at='2033-05-18T03:34:20Z'),missed=dict(policy='skip',max_lateness_seconds=300))))
            saved=self.cli(root,'register','--request',str(spec),'--codex-path',sys.executable)
            def clock(now):return {'utc':{'lower':now,'upper':now,'status':'network','sources':['a','b']},'counter':None}
            poll_schedules(root,clock(2000000000))
            with patch('codex_wake.process.process_identity',return_value={'boot_id':'new-monitor-boot','start_time_ticks':123}):
                poll_schedules(root,clock(2000000061))
            self.assertEqual(self.cli(root,'show',saved['id'])['occurrences'][0]['state'],'skipped')
