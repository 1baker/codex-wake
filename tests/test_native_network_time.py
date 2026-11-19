"""Historical schema5/6 clock and delivery compatibility; schema8 is tested separately."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from legacy_native_fixture import run_legacy_native as run
from codex_wake.records import all_records
from codex_wake.time_provider import TimeDecision

THREAD = '01a1227e-a041-7b72-9c36-18349e7dd22c'

class NativeNetworkTimeTests(unittest.TestCase):
    def arm(self, root, verb='after', trigger='1m', decision=None):
        reading = decision or TimeDecision('network', ('a','b'), 1800000000, 1800000000.2)
        with patch('codex_wake.time_inspection.network_time_decision', return_value=reading), contextlib.redirect_stdout(io.StringIO()):
            return run(['--wake-root',str(root),'native',verb,'--codex-path',sys.executable,
                        '--ttl','2m',THREAD,trigger,'--','Continue'])

    def test_relative_arm_uses_external_upper_bound_not_guest_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            self.arm(root)
            record=all_records(root)[0].record
            self.assertEqual(record['predicate']['due_at'],'2027-01-15T08:01:01Z')
            self.assertEqual(record['target']['expires_at'],'2027-01-15T08:03:01Z')
            self.assertEqual(record['schema_version'],5)
            self.assertEqual(record['time_policy']['mode'],'network-first')

    def test_uncertain_arm_retains_non_dispatchable_intent(self):
        from codex_wake.daemon import poll_once
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            with patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None, 'reason': 'outage'}):
                self.assertEqual(self.arm(root,decision=TimeDecision('uncertain',reason='outage')), 0)
            record=all_records(root)[0].record
            self.assertEqual(record['schema_version'],6)
            self.assertEqual(record['time_recovery']['state'],'pending_time')
            self.assertEqual(poll_once(root,dispatch=False,time_provider=lambda:TimeDecision('uncertain')).fired,0)

    def test_absolute_fraction_and_file_ttl_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            self.arm(root,'at','2027-01-15T09:01:00.123456+01:00')
            record=all_records(root)[0].record
            self.assertEqual(record['predicate']['due_at'],'2027-01-15T08:01:00.123456Z')
            self.assertEqual(record['target']['expires_at'],'2027-01-15T08:03:00.123456Z')
            self.arm(root,'file',str(Path(tmp)/'marker'))
            record=next(r.record for r in all_records(root) if r.record['predicate']['type']=='file_exists')
            self.assertEqual(record['target']['expires_at'],'2027-01-15T08:02:01Z')

    def test_guest_skew_and_outage_cannot_fire_or_expire_new_native_wake(self):
        from datetime import UTC, datetime
        from codex_wake.daemon import poll_once
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'; self.arm(root)
            original=all_records(root)[0].record
            early=TimeDecision('network',('a','b'),1800000060,1800000060.5)
            self.assertEqual(poll_once(root,datetime(2099,1,1,tzinfo=UTC),dispatch=False,time_provider=lambda:early).fired,0)
            due=TimeDecision('network',('a','b'),1800000061,1800000061.2)
            self.assertEqual(poll_once(root,dispatch=False,time_provider=lambda:due).fired,1)
            record=all_records(root)[0].record
            self.assertEqual(record['predicate'],original['predicate'])
            self.assertEqual(record['target']['expires_at'],original['target']['expires_at'])

    def test_interrupted_firing_cannot_bypass_time_gate(self):
        from datetime import UTC, datetime
        from codex_wake.records import move_record, find_record
        from codex_wake.injector import dispatch_firing_record
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'; self.arm(root)
            found=all_records(root)[0]
            move_record(root,found,'firing',event_type='fixture',message='Interrupted evaluation',now=datetime(2027,1,15,tzinfo=UTC))
            found=find_record(root,found.record['id'])
            with patch('codex_wake.native_delivery.read_native_thread',return_value={'id':THREAD,'status':{'type':'active'}}):
                result=dispatch_firing_record(root,found,time_provider=lambda:TimeDecision('uncertain'))
            self.assertEqual(result.status,'skipped')
            self.assertEqual(find_record(root,found.record['id']).record['status'],'firing')

    def test_outage_expiry_boundary_restart_and_cancellation_keep_original_deadlines(self):
        from datetime import UTC, datetime
        from codex_wake.daemon import poll_once
        from codex_wake.records import cancel_record
        import json, subprocess, os
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'; self.arm(root,'file',str(Path(tmp)/'missing'))
            found=all_records(root)[0]; original=found.record
            for reading in (TimeDecision('uncertain'),TimeDecision('network',('a','b'),1800000120.9,1800000121.1)):
                result=poll_once(root,datetime(2099,1,1,tzinfo=UTC),time_provider=lambda:reading)
                self.assertEqual(result.failed,0)
                self.assertEqual(all_records(root)[0].record['status'],'pending')
            restored=json.loads(subprocess.check_output([sys.executable,'-c',
                'import json,sys;from pathlib import Path;from codex_wake.records import all_records;print(json.dumps(all_records(Path(sys.argv[1]))[0].record))',str(root)],text=True))
            self.assertEqual(restored,original)
            result=poll_once(root,time_provider=lambda:TimeDecision('network',('a','b'),1800000121,1800000121.2))
            self.assertEqual(result.failed,1)
            self.assertEqual(all_records(root)[0].record['target'],original['target'])
            self.arm(root)
            found=next(r for r in all_records(root) if r.record['status']=='pending')
            cancel_record(root,found.record['id'])
            cancelled=next(r.record for r in all_records(root) if r.record['id']==found.record['id'])
            self.assertEqual(cancelled['status'],'cancelled')
            self.assertIsNone(cancelled['events'][-1]['at'])

    def test_malformed_policy_and_observation_are_held_without_effect(self):
        from codex_wake.daemon import poll_once
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';self.arm(root)
            found=all_records(root)[0]; original=found.record
            for key,value in [('time_policy',{}),('time_observation',{}),('time_observation',{'status':'network','sources':['a'],'lower':1,'upper':1}),('attempts',True),('time_observation',{'status':'network','sources':'ab','lower':1800000000,'upper':1800000000.2})]:
                found.path.write_text(json.dumps(dict(original,**{key:value})))
                before=found.path.read_bytes()
                result=poll_once(root,time_provider=lambda:TimeDecision('network',('a','b'),1800009999,1800009999.2))
                self.assertEqual(result.failed,0)
                self.assertEqual(result.dispatched,0)
                self.assertEqual(found.path.read_bytes(),before)

    def test_provider_fallback_and_invalid_observations_at_cli(self):
        from codex_wake.records import WakeError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            self.arm(root,decision=TimeDecision('windows',('windows',),1800000000,1800000000.2))
            self.assertEqual(all_records(root)[0].record['time_observation']['status'],'windows')
            for reading in (TimeDecision('uncertain',reason='competing_network_consensuses'),TimeDecision('network',('a','b'),float('nan'),1)):
                with patch('codex_wake.native_clock.snapshot', return_value={'utc': None, 'counter': None, 'reason': 'invalid_time'}):
                    self.assertEqual(self.arm(root,decision=reading),0)
            self.assertEqual(len(all_records(root)),2)
            retained=next(item.record for item in all_records(root) if item.record['schema_version']==6)
            self.assertEqual(retained['time_recovery']['state'],'pending_time')

    def test_uncertain_submission_reconciles_read_only_during_time_outage(self):
        from codex_wake.records import replace_record, find_record
        from codex_wake.daemon import poll_once
        from codex_wake.native_delivery import native_prompt
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';self.arm(root)
            found=all_records(root)[0]
            record=dict(found.record,status='firing',attempts=1,native_delivery={'state':'uncertain','submission_id':'retained-nonce'})
            replace_record(root,found,record)
            prompt=native_prompt(root,record)
            def native(endpoint,codex,method,params,timeout):
                if method=='thread/queue/list':return {'data':[],'nextCursor':None}
                if method=='thread/read':return {'thread':{'id':THREAD}}
                return {'data':[{'id':'completed','status':'completed','itemsView':'full','items':[{'type':'userMessage','id':'message','clientId':'client','content':[{'type':'text','text':prompt}]}]}], 'nextCursor':None}
            with patch('codex_wake.native_delivery.native_request',side_effect=native),patch('codex_wake.native_delivery.subprocess.run') as submit:
                poll_once(root,time_provider=lambda:TimeDecision('uncertain'))
            submit.assert_not_called()
            recovered=find_record(root,record['id']).record
            self.assertEqual(recovered['status'],'submitted')
            self.assertEqual(recovered['attempts'],1)
            self.assertIsNone(recovered['native_delivery']['reconciliation']['checked_at'])

    def test_fractional_expiry_does_not_fail_early_at_native_transport(self):
        from codex_wake.daemon import poll_once
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';self.arm(root,'at','2027-01-15T08:01:00.123456Z')
            reading=TimeDecision('network',('a','b'),1800000180.05,1800000180.1)
            with patch('codex_wake.native_delivery.read_native_thread',return_value={'id':THREAD,'status':{'type':'active'}}):
                result=poll_once(root,time_provider=lambda:reading)
            self.assertEqual(result.failed,0)
            self.assertEqual(result.requeued,1)
