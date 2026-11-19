"""Public controller seams, real files/accounting and native RPC boundary only."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from websockets.sync.server import unix_serve
from websockets.exceptions import ConnectionClosed

from codex_wake.goal_supervision import enroll,show,poll

THREAD='00000000-0000-7000-8000-000000000279'
NOW=1893456000


class GoalSupervisionTests(unittest.TestCase):
    def test_identical_reenrollment_retains_qualified_native_lease_without_rearming(self):
        from copy import deepcopy
        observation=dict(reason='authenticated_utc',utc=dict(status='network',lower=NOW,upper=NOW),
            valid_for_ns=300000000000,counter=dict(epoch='c357309d-c209-4467-b757-e1488e6b1aaa',
                counter=1000,frequency=1000,rate_ppm=0))
        controller=dict(fresh=True,generation='controller-original',governor_protocol=1)
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            native['lease_reply']=dict(armed=True,expired=False,stopVerified=False,ttlMs=10000)
            with patch('codex_wake.goal_supervision._heartbeat',return_value=controller),patch(
                    'codex_wake.goal_supervision.native_request',side_effect=request),patch(
                    'codex_wake.lifecycle_budget.trusted_upper',return_value=NOW),patch(
                    'codex_wake.measurements.snapshot',return_value=observation),patch(
                    'time.clock_gettime',return_value=10):
                first=enroll(root,policy,THREAD,100,120,requires_native_guard=True)
                self.assertEqual(first['native_guard']['status'],'armed')
                original=deepcopy(first['native_guard'])
                effects=len(native['lease_calls'])
                again=enroll(root,policy,THREAD,100,120,requires_native_guard=True)
                self.assertEqual(again['deadline'],first['deadline'])
                self.assertEqual(again['time_origin'],first['time_origin'])
                self.assertEqual(again['enrollment_revision'],first['enrollment_revision'])
                self.assertEqual(again['native_guard'],original)
                self.assertEqual(again['native_guard']['ack_clock'],observation)
                self.assertEqual(len(native['lease_calls']),effects)
                self.assertEqual(effects,1)
                tightened=enroll(root,policy,THREAD,90,120,requires_native_guard=True)
                self.assertEqual(tightened['deadline'],first['deadline'])
                self.assertGreater(tightened['enrollment_revision'],first['enrollment_revision'])
                self.assertNotEqual(tightened['native_guard']['lease_id'],original['lease_id'])
                self.assertEqual(len(native['lease_calls']),2)

    def test_initial_accounting_timeout_does_not_persist_an_irrecoverable_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                with patch('codex_wake.goal_supervision._usage',return_value=dict(
                        state='unknown',used_tokens=None,reason='usage_scan_time_limit')):
                    with self.assertRaisesRegex(ValueError,'initial accounting unavailable'):
                        enroll(root,policy,THREAD,100,120)
                self.assertEqual(list((root/'goal-supervision').glob('[0-9a-f]'*64+'.json')),[])
                accepted=enroll(root,policy,THREAD,100,120)
                self.assertEqual(accepted['state'],'armed')
                self.assertEqual(accepted['used_tokens'],40)
                self.assertFalse(accepted.get('stop_latched',False))
                self.assertFalse(any(method in ('thread/goal/set','turn/interrupt') for method,_ in native['calls']))

    def test_delegated_initial_scan_timeout_leaves_allocation_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            grant.pop('allocation_id')
            policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,
                allocations={},self_enrollment=grant)))
            context=dict(threadId=THREAD,sessionId=THREAD,callId='native-first-enrollment',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                with patch('codex_wake.goal_supervision._usage',return_value=dict(
                        state='unknown',used_tokens=None,reason='allocation_member_accounting_unknown',
                        member_thread_id=THREAD,member_reason='usage_scan_time_limit')):
                    with self.assertRaisesRegex(ValueError,'initial accounting unavailable'):
                        enroll(root,policy,THREAD,100,120,native_context=context)
                ledger=next((root/'goal-supervision/allocations').glob('*.json'))
                self.assertFalse(json.loads(ledger.read_text())['stop_latched'])
                accepted=enroll(root,policy,THREAD,100,120,native_context=context)
                self.assertEqual(accepted['state'],'armed')
                self.assertEqual(accepted['used_tokens'],40)
                self.assertEqual(accepted['deadline'],NOW+120)
                self.assertFalse(accepted.get('stop_latched',False))

    def test_recognizing_native_state_never_clears_an_existing_stop_latch(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            native['goal']['status']='futureUnknownState';native['active']=[]
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120)
                self.assertTrue(first['stop_latched'])
                native['goal']['status']='paused'
                later=enroll(root,policy,THREAD,100,120)
                self.assertEqual(later['state'],'held')
                self.assertTrue(later['stop_latched'])
                for key in ('generation','deadline','used_tokens'):
                    self.assertEqual(later[key],first[key])

    def test_known_inactive_goal_states_do_not_latch_a_resource_stop(self):
        for status in ('paused','blocked','complete','budgetLimited','usageLimited'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as directory:
                root,policy,_,native,_=self.fixture(directory)
                native['goal']['status']=status;native['active']=[]
                with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                    first=enroll(root,policy,THREAD,100,120)
                    self.assertEqual(first['state'],'armed')
                    self.assertFalse(first.get('stop_latched',False))
                    self.assertEqual(native['goal']['status'],status)
                    self.assertEqual(poll(root)[0]['state'],'armed')
                    self.assertFalse(any(m=='thread/goal/set' for m,_ in native['calls']))
                    native['goal']['status']='active'
                    later=poll(root)[0]
                    self.assertEqual(later['generation'],first['generation'])
                    self.assertEqual(later['deadline'],first['deadline'])
                    self.assertEqual(later['used_tokens'],first['used_tokens'])

    def test_first_enrollment_imports_host_renewal_boundary_without_replenishing_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            from codex_wake.goal_usage import observe_usage
            original=observe_usage(log.parent.parent,THREAD,NOW)
            self.assertEqual(original['used_tokens'],40)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            grant['initial_boundary']=dict(started_at=NOW+10,token_accounting='fresh',reset_anchor=original['anchor'])
            config=dict(version=2,native_caller_binding=True,default_allocation='renewal',allocations={'renewal':grant})
            policy.write_text(json.dumps(config))
            row=json.loads(log.read_text().splitlines()[-1]);row['payload']['response_id']='after-renewal'
            row['payload']['usage']=dict(input_tokens=28,cached_input_tokens=0,output_tokens=2,total_tokens=30)
            with log.open('a') as stream:stream.write(json.dumps(row)+'\n')
            context=dict(threadId=THREAD,sessionId=THREAD,callId='native-import',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            successor='00000000-0000-7000-8000-000000000294'
            rows=[json.loads(line) for line in log.read_text().splitlines()[:4]]
            rows=json.loads(json.dumps(rows).replace(THREAD,successor))
            rows[1]['payload']['goal']['createdAt']=NOW+15
            for event in rows[1:]:event['timestamp']='2030-01-01T00:00:15Z'
            rows[3]['payload']['usage']=dict(input_tokens=4,cached_input_tokens=0,output_tokens=1,total_tokens=5)
            (log.parent/'first-successor.jsonl').write_text(''.join(json.dumps(event)+'\n' for event in rows))
            native['siblings']={successor:dict(goal=dict(threadId=successor,createdAt=NOW+15,status='active'),active=['work'],calls=[])}
            successor_context=dict(threadId=successor,sessionId=successor,callId='native-successor-import',
                **{'x-codex-turn-metadata':dict(thread_id=successor,session_id=successor,turn_id='work')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+20):
                first=enroll(root,policy,successor,100,120,native_context=successor_context)
                self.assertEqual(first['used_tokens'],35)
                self.assertEqual(first['deadline'],NOW+130)
                receipt=enroll(root,policy,THREAD,100,120,native_context=context)
                self.assertEqual(receipt['state'],'armed')
                self.assertEqual(receipt['used_tokens'],35)
                self.assertEqual(receipt['time_origin'],NOW+10)
                self.assertEqual(receipt['deadline'],NOW+130)
                again=enroll(root,policy,THREAD,100,120,native_context=context)
                self.assertEqual(again['used_tokens'],35)
                self.assertEqual(again['deadline'],NOW+130)

    def test_host_boundary_rejects_changed_history_and_future_time_before_admission(self):
        for defect in ('changed-history','future-time'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as directory:
                root,policy,log,_,_=self.fixture(directory)
                from codex_wake.goal_usage import observe_usage
                anchor=observe_usage(log.parent.parent,THREAD,NOW)['anchor']
                if defect=='changed-history':anchor['response_hashes']={key:'0'*64 for key in anchor['response_hashes']}
                grant=json.loads(policy.read_text())['callers'][THREAD]
                grant['initial_boundary']=dict(started_at=NOW+100 if defect=='future-time' else NOW,
                    token_accounting='fresh',reset_anchor=anchor)
                policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,
                    default_allocation='import',allocations={'import':grant})))
                context=dict(threadId=THREAD,sessionId=THREAD,callId='native-import',
                    **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+20):
                    with self.assertRaisesRegex(ValueError,'boundary'):
                        enroll(root,policy,THREAD,100,120,native_context=context)
                self.assertFalse(list((root/'goal-supervision/allocations').glob('*.json')))

    def test_host_delegation_policy_preserves_existing_explicit_grants_and_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            legacy=json.loads(policy.read_text())
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120)
                upgraded=dict(version=2,native_caller_binding=True,callers=legacy['callers'],
                    allocations={'other':dict(legacy['callers'][THREAD],allocation_id='other')})
                policy.write_text(json.dumps(upgraded))
                again=enroll(root,policy,THREAD,100,120)
                self.assertEqual(again['state'],'armed')
                self.assertEqual(again['allocation_id'],first['allocation_id'])
                self.assertEqual(again['deadline'],first['deadline'])
                self.assertEqual(again['used_tokens'],40)
                self.assertEqual(poll(root)[0]['state'],'armed')
                self.assertEqual(native['goal']['status'],'active')
                with self.assertRaisesRegex(ValueError,'selected allocation'):
                    enroll(root,policy,THREAD,100,120,allocation_id='other')

    def test_native_first_enrollment_needs_no_named_allocation_or_default(self):
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            template=json.loads(policy.read_text())['callers'][THREAD]
            template.pop('allocation_id')
            template.update(max_tokens=100,max_seconds=120)
            config=dict(version=2,native_caller_binding=True,allocations={},self_enrollment=template)
            policy.write_text(json.dumps(config));before=policy.read_bytes()
            context=dict(threadId=THREAD,sessionId=THREAD,callId='first-native-goal',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            runner=CommandRunner(goal_limits_policy=policy,goal_limits_root=root)
            args=dict(caller_thread_id=THREAD,token_limit=100,time_limit_seconds=120)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                for invalid,metadata in ((dict(args,token_limit=101),context),(args,None),
                        (args,dict(context,threadId='00000000-0000-7000-8000-000000000290')),
                        (args,dict(context,sessionId='00000000-0000-7000-8000-000000000290')),
                        (dict(args,allocation_id='native-00000000-0000-7000-8000-000000000290'),context)):
                    denied,failed=runner.call('wake_goal_limits_set',invalid,native_context=metadata)
                    self.assertTrue(failed,denied)
                first,failed=runner.call('wake_goal_limits_set',args,native_context=context)
                self.assertFalse(failed,first)
                self.assertEqual(first['state'],'armed')
                self.assertEqual(first['used_tokens'],40)
                self.assertEqual(first['deadline'],NOW+120)
                again,failed=runner.call('wake_goal_limits_set',args,native_context=context)
                self.assertFalse(failed,again)
                for key in ('allocation_id','generation','deadline','used_tokens'):
                    self.assertEqual(again[key],first[key])
                shown,failed=runner.call('wake_goal_limits_show',dict(caller_thread_id=THREAD),native_context=context)
                self.assertFalse(failed,shown)
                self.assertEqual(shown['allocation_id'],first['allocation_id'])
                native['goal']['createdAt']=NOW+1
                continued,failed=runner.call('wake_goal_limits_set',args,native_context=context)
                self.assertFalse(failed,continued)
                for key in ('allocation_id','generation','deadline','used_tokens'):
                    self.assertEqual(continued[key],first[key])
                self.assertEqual(policy.read_bytes(),before)

    def test_native_successor_cannot_omit_existing_allocation_to_get_fresh_budget(self):
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,_,_=self.fixture(directory)
            template=json.loads(policy.read_text())['callers'][THREAD];template.pop('allocation_id')
            policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,allocations={},self_enrollment=template)))
            rows=[json.loads(line) for line in log.read_text().splitlines()]
            rows[0]['payload']['parent_thread_id']='00000000-0000-7000-8000-000000000290'
            log.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            context=dict(threadId=THREAD,sessionId=THREAD,callId='successor',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                result,failed=CommandRunner(goal_limits_policy=policy,goal_limits_root=root).call(
                    'wake_goal_limits_set',dict(caller_thread_id=THREAD,token_limit=100,time_limit_seconds=120),native_context=context)
                self.assertTrue(failed,result)
                self.assertIn('successor',result['error']['message'])

    def test_verified_successor_inherits_allocation_without_operator_selection(self):
        for source_status,enabled,accounting in (('active',True,'fresh'),('complete',True,'fresh'),
                ('blocked',True,'fresh'),('active',False,'fresh'),('active',True,'cache_inclusive')):
            from codex_wake.mcp_server import CommandRunner
            with self.subTest(source_status=source_status,enabled=enabled,accounting=accounting),tempfile.TemporaryDirectory() as directory:
                root,policy,log,native,_=self.fixture(directory)
                native['goal']['status']=source_status
                template=json.loads(policy.read_text())['callers'][THREAD];template.pop('allocation_id')
                policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,allocations={},self_enrollment=template)))
                successor='00000000-0000-7000-8000-000000000290'
                rows=json.loads(json.dumps([json.loads(line) for line in log.read_text().splitlines()]).replace(THREAD,successor))
                rows[0]['payload']['parent_thread_id']=THREAD
                rows[0]['payload']['session_id']=THREAD
                rows[0]['payload']['source']={'subagent':{'thread_spawn':{'parent_thread_id':THREAD}}}
                rows[-1]['payload']['session_id']=THREAD
                rows[-1]['payload']['response_id']='successor-response'
                rows[1]['payload']['goal']['createdAt']=NOW+10
                for row in rows[1:]:row['timestamp']='2030-01-01T00:00:10Z'
                rows.pop(1)  # Native create_goal during a child turn has no independent rollout boundary.
                (log.parent/'successor.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
                native['siblings']={successor:dict(goal=dict(threadId=successor,createdAt=NOW+10,status='active'),active=['work'],calls=[],parent_thread_id=THREAD)}
                context=lambda thread:dict(threadId=thread,sessionId=THREAD,callId='call-'+thread,
                    **{'x-codex-turn-metadata':dict(thread_id=thread,session_id=THREAD,turn_id='work')})
                runner=CommandRunner(goal_limits_policy=policy,goal_limits_root=root)
                with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+10):
                    first,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=THREAD,token_limit=100,time_limit_seconds=120,token_accounting=accounting),native_context=context(THREAD))
                    self.assertFalse(failed,first)
                    if not enabled:
                        from codex_wake.goal_governance import change
                        from codex_wake.session_permissions import Principal
                        change(root,THREAD,enabled=False,principal=Principal(THREAD,'operator'))
                    second,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=successor,token_limit=100,time_limit_seconds=120),native_context=context(successor))
                    self.assertFalse(failed,second)
                    self.assertEqual(second['allocation_id'],first['allocation_id'])
                    self.assertEqual(second['deadline'],first['deadline'])
                    self.assertEqual(second['used_tokens'],80)
                    self.assertEqual(second['token_accounting'],accounting)
                    self.assertEqual(second['continuation_source_thread_id'],THREAD)
                    self.assertEqual(second['state'],'armed' if enabled else 'inactive')
                    self.assertEqual(second['governor_enabled'],enabled)
                    self.assertFalse(any(method in ('thread/goal/set','turn/interrupt') for method,_ in native['calls']))

    def test_successor_automatic_selection_preserves_exhaustion(self):
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            template=json.loads(policy.read_text())['callers'][THREAD];template.pop('allocation_id')
            policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,allocations={},self_enrollment=template)))
            successor='00000000-0000-7000-8000-000000000290'
            rows=json.loads(json.dumps([json.loads(line) for line in log.read_text().splitlines()]).replace(THREAD,successor))
            rows[0]['payload']['parent_thread_id']=THREAD
            rows[0]['payload']['session_id']=THREAD
            rows[0]['payload']['source']={'subagent':{'thread_spawn':{'parent_thread_id':THREAD}}}
            rows[-1]['payload']['session_id']=THREAD
            rows[-1]['payload']['response_id']='successor-response'
            rows[1]['payload']['goal']['createdAt']=NOW+10
            for row in rows[1:]:row['timestamp']='2030-01-01T00:00:10Z'
            (log.parent/'successor.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            native['siblings']={successor:dict(goal=dict(threadId=successor,createdAt=NOW+10,status='active'),active=['work'],calls=[])}
            context=lambda thread:dict(threadId=thread,sessionId=thread,callId='call-'+thread,
                **{'x-codex-turn-metadata':dict(thread_id=thread,session_id=thread,turn_id='work')})
            runner=CommandRunner(goal_limits_policy=policy,goal_limits_root=root)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+10):
                first,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=THREAD,token_limit=80,time_limit_seconds=120),native_context=context(THREAD))
                self.assertTrue(failed,first)
                second,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=successor,token_limit=80,time_limit_seconds=120),native_context=context(successor))
                self.assertTrue(failed,second)
                self.assertEqual(second['allocation_id'],first['allocation_id'])
                self.assertEqual(second['deadline'],first['deadline'])
                self.assertEqual(second['used_tokens'],80)
                self.assertEqual(second['continuation_source_thread_id'],THREAD)
                self.assertEqual(second['state'],'held')
                self.assertTrue(second['stop_latched'])
                self.assertEqual(second['token_limit'],80)
                self.assertFalse(any(method in ('thread/goal/set','turn/interrupt') for method,_ in native['calls']))


    def test_unrelated_new_session_is_not_locked_by_old_exhausted_goal(self):
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            native['goal']['status']='blocked'
            template=json.loads(policy.read_text())['callers'][THREAD];template.pop('allocation_id')
            policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,allocations={},self_enrollment=template)))
            successor='00000000-0000-7000-8000-000000000290'
            rows=json.loads(json.dumps([json.loads(line) for line in log.read_text().splitlines()]).replace(THREAD,successor))
            rows[-1]['payload']['response_id']='successor-response'
            rows[1]['payload']['goal']['createdAt']=NOW+10
            for row in rows[1:]:row['timestamp']='2030-01-01T00:00:10Z'
            (log.parent/'successor.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            native['siblings']={successor:dict(goal=dict(threadId=successor,createdAt=NOW+10,status='active'),active=['work'],calls=[])}
            context=lambda thread:dict(threadId=thread,sessionId=thread,callId='call-'+thread,
                **{'x-codex-turn-metadata':dict(thread_id=thread,session_id=thread,turn_id='work')})
            runner=CommandRunner(goal_limits_policy=policy,goal_limits_root=root)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+10):
                first,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=THREAD,token_limit=40,time_limit_seconds=120),native_context=context(THREAD))
                self.assertTrue(failed,first)
                second,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=successor,token_limit=80,time_limit_seconds=120),native_context=context(successor))
                self.assertFalse(failed,second)
                self.assertNotEqual(second['allocation_id'],first['allocation_id'])
                self.assertEqual(first['deadline'],NOW+120)
                self.assertEqual(second['deadline'],NOW+130)
                self.assertEqual(second['used_tokens'],40)
                self.assertNotIn('continuation_source_thread_id',second)
                self.assertEqual(second['state'],'armed')
                self.assertTrue(first['stop_latched'])
                self.assertEqual(second['token_limit'],80)
                retained,_=runner.call('wake_goal_limits_show',dict(caller_thread_id=THREAD),native_context=context(THREAD))
                self.assertEqual(retained['allocation_id'],first['allocation_id'])
                self.assertTrue(retained['stop_latched'])
                self.assertFalse(any(method in ('thread/goal/set','turn/interrupt') for method,_ in native['calls']))


    def test_public_successor_joins_automatically_created_allocation(self):
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            template=json.loads(policy.read_text())['callers'][THREAD];template.pop('allocation_id')
            policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,allocations={},self_enrollment=template)))
            successor='00000000-0000-7000-8000-000000000290'
            rows=json.loads(json.dumps([json.loads(line) for line in log.read_text().splitlines()]).replace(THREAD,successor))
            rows[1]['payload']['goal']['createdAt']=NOW+10
            for row in rows[1:]:row['timestamp']='2030-01-01T00:00:10Z'
            (log.parent/'successor.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            native['siblings']={successor:dict(goal=dict(threadId=successor,createdAt=NOW+10,status='active'),active=['work'],calls=[])}
            context=lambda thread:dict(threadId=thread,sessionId=thread,callId='call-'+thread,
                **{'x-codex-turn-metadata':dict(thread_id=thread,session_id=thread,turn_id='work')})
            runner=CommandRunner(goal_limits_policy=policy,goal_limits_root=root)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+10):
                first,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=THREAD,token_limit=100,time_limit_seconds=120),native_context=context(THREAD))
                self.assertFalse(failed,first)
                second,failed=runner.call('wake_goal_limits_set',dict(caller_thread_id=successor,token_limit=100,time_limit_seconds=120,allocation_id=first['allocation_id']),native_context=context(successor))
                self.assertFalse(failed,second)
                self.assertEqual(second['allocation_id'],first['allocation_id'])
                self.assertEqual(second['deadline'],first['deadline'])
                self.assertEqual(second['used_tokens'],80)

    def test_host_delegated_caller_enrolls_without_uuid_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            old=json.loads(policy.read_text())['callers'][THREAD]
            policy.write_text(json.dumps(dict(version=2, default_allocation='allocation-1',
                allocations={'allocation-1':old}, native_caller_binding=True)))
            context=dict(threadId=THREAD, sessionId=THREAD, callId='native-call',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with self.controller(root), patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                with self.assertRaisesRegex(ValueError,'native caller'):
                    enroll(root,policy,THREAD,100,120)
                from codex_wake.mcp_server import CommandRunner
                runner=CommandRunner(goal_limits_policy=policy,goal_limits_root=root)
                arguments=dict(caller_thread_id=THREAD,token_limit=100,time_limit_seconds=120)
                denied,failed=runner.call('wake_goal_limits_set',arguments)
                self.assertTrue(failed)
                self.assertEqual(denied['state'],'held')
                forged=dict(context,threadId='00000000-0000-7000-8000-000000000290')
                self.assertTrue(runner.call('wake_goal_limits_set',arguments,native_context=forged)[1])
                receipt,failed=runner.call('wake_goal_limits_set',arguments,native_context=context)
                self.assertFalse(failed,receipt)
                self.assertEqual(receipt['state'],'armed')
                self.assertEqual(receipt['allocation_id'],'allocation-1')
                self.assertEqual(receipt['used_tokens'],40)
                self.assertEqual(receipt['deadline'],NOW+120)
                self.assertEqual(json.loads(policy.read_text())['allocations']['allocation-1'],old)
                self.assertNotIn('callers',json.loads(policy.read_text()))

    def test_successor_shares_spend_deadline_and_cannot_mint_another_allowance(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            policy.write_text(json.dumps(dict(version=2, default_allocation='allocation-1',
                allocations={'allocation-1':grant},native_caller_binding=True)))
            def context(thread):
                return dict(threadId=thread,sessionId=thread,callId='call-'+thread,
                    **{'x-codex-turn-metadata':dict(thread_id=thread,session_id=thread,turn_id='work')})
            successor='00000000-0000-7000-8000-000000000290'
            rows=[json.loads(line) for line in log.read_text().splitlines()]
            rows=json.loads(json.dumps(rows).replace(THREAD,successor))
            rows[1]['payload']['goal']['createdAt']=NOW+10
            rows[1]['timestamp']='2030-01-01T00:00:10Z'
            rows[2]['timestamp']='2030-01-01T00:00:10Z'
            rows[3]['timestamp']='2030-01-01T00:00:10Z'
            (log.parent/'successor.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            native['siblings']={successor:dict(goal=dict(threadId=successor,createdAt=NOW+10,status='active'),active=['work'],calls=[])}
            with self.controller(root), patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+10):
                first=enroll(root,policy,THREAD,100,120,native_context=context(THREAD))
                second=enroll(root,policy,successor,100,120,native_context=context(successor))
                self.assertEqual(second['used_tokens'],80)
                self.assertEqual(second['deadline'],NOW+120)
                self.assertEqual(second['time_origin'],NOW)
                repeated=enroll(root,policy,successor,100,120,native_context=context(successor))
                self.assertEqual(repeated['used_tokens'],80)
                self.assertEqual(repeated['deadline'],first['deadline'])
                with self.assertRaisesRegex(ValueError,'allocation'):
                    enroll(root,policy,successor,101,120,native_context=context(successor))
                control='00000000-0000-7000-8000-000000000292'
                control_policy=json.loads(policy.read_text())
                control_policy['allocations']['other-objective']=grant
                policy.write_text(json.dumps(control_policy))
                (log.parent/'control.jsonl').write_text(''.join(json.dumps(row).replace(successor,control)+'\n' for row in rows))
                native['siblings'][control]=dict(goal=dict(threadId=control,createdAt=NOW+10,status='active'),active=['work'],calls=[])
                unrelated=enroll(root,policy,control,100,120,native_context=context(control),allocation_id='other-objective')
                self.assertEqual(unrelated['used_tokens'],40)
                self.assertEqual(unrelated['deadline'],NOW+130)
                original=log.read_text()
                log.write_text(original+'{"type":')
                winding=poll(root)
                grace=min(value['winddown_deadline'] for value in winding if 'winddown_deadline' in value)
                self.assertEqual(next(value for value in winding if value['thread_id']==control)['state'],'armed')
                self.assertEqual(native['siblings'][control]['goal']['status'],'active')
                log.write_text(original)
                third='00000000-0000-7000-8000-000000000291'
                rows[3]['payload']['usage']=dict(input_tokens=0,cached_input_tokens=0,output_tokens=0,total_tokens=0)
                (log.parent/'third.jsonl').write_text(''.join(json.dumps(row).replace(successor,third)+'\n' for row in rows))
                native['siblings'][third]=dict(goal=dict(threadId=third,createdAt=NOW+10,status='active'),active=['work'],calls=[])
                held=enroll(root,policy,third,100,120,native_context=context(third))
                self.assertEqual(held['state'],'held')
                self.assertTrue(held['stop_latched'])
                self.assertEqual(held['allocation_winddown_deadline'],grace)


    def test_renewal_freezes_one_boundary_when_history_grows_between_reads(self):
        from codex_wake.goal_usage import observe_usage
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            config=dict(version=2,native_caller_binding=True,default_allocation='original',
                allocations={'original':grant,'renewed':dict(grant,renews_allocation='original')})
            policy.write_text(json.dumps(config))
            context=dict(threadId=THREAD,sessionId=THREAD,callId='native-call',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120,native_context=context)
                peer='00000000-0000-7000-8000-000000000293'
                (log.parent/'peer.jsonl').write_text(log.read_text().replace(THREAD,peer))
                native['siblings']={peer:dict(goal=dict(threadId=peer,createdAt=NOW,status='active'),active=['work'],calls=[])}
                peer_context=dict(context,threadId=peer,sessionId=peer,
                    **{'x-codex-turn-metadata':dict(thread_id=peer,session_id=peer,turn_id='work')})
                peer_first=enroll(root,policy,peer,100,120,native_context=peer_context)
                peer_path=next(p for p in (root/'goal-supervision').glob('*.json')
                    if json.loads(p.read_text()).get('thread_id')==peer)
                reads=0
                def growing_history(*args,**kwargs):
                    nonlocal reads
                    reads+=1
                    if reads==2:
                        row=json.loads(log.read_text().splitlines()[-1])
                        row['payload']['response_id']='after-frozen-boundary'
                        row['payload']['usage']=dict(input_tokens=5,cached_input_tokens=0,output_tokens=2,total_tokens=7)
                        with log.open('a') as stream:stream.write(json.dumps(row)+'\n')
                        # A peer's watcher may have sampled the departing
                        # member before finalization acquired the old ledger.
                        sampled=observe_usage(*args,**kwargs)
                        old_path=Path(first['allocation_path'])
                        old=json.loads(old_path.read_text())
                        peer_usage=observe_usage(grant['codex_home'],peer,NOW)
                        charges=dict(sampled['charges'],**peer_usage['charges'])
                        used=sum(v['tokens'] for v in charges.values())
                        old.update(charges=charges,used_tokens=used)
                        old_path.write_text(json.dumps(old))
                        cached=json.loads(peer_path.read_text())
                        cached['used_tokens']=used;cached['accounting']['used_tokens']=used
                        peer_path.write_text(json.dumps(cached))
                    return observe_usage(*args,**kwargs)
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+10), \
                        patch('codex_wake.goal_usage.observe_usage',side_effect=growing_history):
                    renewed=enroll(root,policy,THREAD,200,120,native_context=context,allocation_id='renewed')
                self.assertEqual(renewed['state'],'armed')
                self.assertEqual(renewed['used_tokens'],7)
                self.assertEqual(renewed['deadline'],NOW+130)
                old=json.loads(Path(first['allocation_path']).read_text())
                target=json.loads(Path(renewed['allocation_path']).read_text())
                frozen=old['members'][THREAD]['finalized_charges']
                self.assertEqual(sum(v['tokens'] for v in frozen.values()),40)
                self.assertEqual(old['used_tokens'],80)
                self.assertTrue(set(frozen).isdisjoint(target['charges']))
                self.assertEqual(sum(v['tokens'] for v in frozen.values())+target['used_tokens'],47)
                after={r['thread_id']:r for r in poll(root)}[peer]
                self.assertEqual(after['state'],'armed')
                self.assertEqual(after['used_tokens'],80)
                self.assertEqual(after['deadline'],peer_first['deadline'])
                self.assertFalse(after.get('stop_latched',False))
                self.assertEqual(after['accounting']['renewed_out_tokens'],7)
                again={r['thread_id']:r for r in poll(root)}[peer]
                self.assertEqual(again['state'],'armed')
                self.assertEqual(again['used_tokens'],80)


    def test_renewal_rejects_changed_response_before_frozen_boundary(self):
        from codex_wake.goal_usage import observe_usage
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,_,_=self.fixture(directory)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,
                default_allocation='original',allocations={'original':grant,
                    'renewed':dict(grant,renews_allocation='original')})))
            context=dict(threadId=THREAD,sessionId=THREAD,callId='native-call',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120,native_context=context)
                reads=0
                def changed_history(*args,**kwargs):
                    nonlocal reads
                    reads+=1
                    if reads==2:
                        rows=log.read_text().splitlines();row=json.loads(rows[-1])
                        row['payload']['usage']['input_tokens']+=1
                        row['payload']['usage']['total_tokens']+=1
                        rows[-1]=json.dumps(row);log.write_text('\n'.join(rows)+'\n')
                    return observe_usage(*args,**kwargs)
                with patch('codex_wake.goal_usage.observe_usage',side_effect=changed_history):
                    with self.assertRaisesRegex(ValueError,'renewal boundary changed'):
                        enroll(root,policy,THREAD,200,120,native_context=context,allocation_id='renewed')
                prior=json.loads(Path(first['allocation_path']).read_text())
                self.assertNotIn('finalized_charges',prior['members'][THREAD])
                self.assertEqual(prior['used_tokens'],40)


    def test_only_explicit_host_renewal_changes_allowance_and_preserves_prior_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            config=dict(version=2,default_allocation='allocation-1',native_caller_binding=True,
                allocations={'allocation-1':grant,'renewed':grant})
            policy.write_text(json.dumps(config))
            context=dict(threadId=THREAD,sessionId=THREAD,callId='native-call',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120,native_context=context)
                other='00000000-0000-7000-8000-000000000293'
                (log.parent/'old-member.jsonl').write_text(log.read_text().replace(THREAD,other))
                native['siblings']={other:dict(goal=dict(threadId=other,createdAt=NOW,status='active'),active=['work'],calls=[])}
                other_context=dict(context,threadId=other,sessionId=other,
                    **{'x-codex-turn-metadata':dict(thread_id=other,session_id=other,turn_id='work')})
                enroll(root,policy,other,100,120,native_context=other_context)
                with self.assertRaisesRegex(ValueError,'explicit host renewal'):
                    enroll(root,policy,THREAD,200,120,native_context=context,allocation_id='renewed')
                config['allocations']['renewed']=dict(grant,renews_allocation='allocation-1')
                policy.write_text(json.dumps(config))
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+10):
                    renewed=enroll(root,policy,THREAD,200,120,native_context=context,allocation_id='renewed')
                self.assertEqual(renewed['used_tokens'],0)
                self.assertEqual(renewed['time_origin'],NOW+10)
                self.assertEqual(renewed['deadline'],NOW+130)
                self.assertNotEqual(renewed['generation'],first['generation'])
                self.assertEqual(json.loads(Path(first['allocation_path']).read_text())['used_tokens'],80)
                row=json.loads(log.read_text().splitlines()[-1])
                row['payload']['response_id']='renewed-response'
                row['payload']['usage']=dict(input_tokens=28,cached_input_tokens=0,output_tokens=2,total_tokens=30)
                with log.open('a') as stream:stream.write(json.dumps(row)+'\n')
                results={value['thread_id']:value for value in poll(root)}
                self.assertEqual(results[THREAD]['used_tokens'],30)
                self.assertEqual(results[other]['used_tokens'],80)
                self.assertEqual(results[other]['state'],'armed')
                # Restart at the durable boundary after target admission but
                # before old-member finalization, with later usage now present.
                previous_path=Path(first['allocation_path'])
                previous=json.loads(previous_path.read_text())
                member=previous['members'][THREAD]
                for key in ('finalized_charges','final_anchor','renewed_into'):member.pop(key)
                previous_path.write_text(json.dumps(previous))
                receipt_path=next(path for path in (root/'goal-supervision').glob('*.json')
                    if path.name!='controller.json' and json.loads(path.read_text())['thread_id']==THREAD)
                pending=json.loads(receipt_path.read_text())['prior_allocation']
                receipt_path.write_text(json.dumps(pending))
                with self.assertRaisesRegex(ValueError,'renewal boundary'):
                    enroll(root,policy,THREAD,200,120,native_context=context,allocation_id='renewed')


    def test_resume_after_partially_verified_stop_gets_a_new_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,40,120)
                native['lose']='turn/interrupt'
                first=poll(root)[0]
                self.assertEqual(first['state'],'stop_unverified')
                self.assertEqual(native['goal']['status'],'paused')
                native['active']=[]
                native['goal']['status']='active'
                native.pop('lose')
                second=poll(root)[0]
                self.assertEqual(second['state'],'stopped')
                self.assertEqual(native['goal']['status'],'paused')
                self.assertEqual(sum(method=='thread/goal/set' for method,_ in native['calls']),2)
                self.assertTrue(any(effect['state']=='uncertain' for effect in second['effects'].values()))

    def test_paused_campaign_allows_operator_reply_on_later_polls(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,40,120)
                self.assertEqual(poll(root)[0]['state'],'stopped')
                native['active']=['operator-reply']
                poll(root)
                poll(root)
                self.assertEqual(native['goal']['status'],'paused')
                self.assertEqual(native['active'],['operator-reply'])
                self.assertNotIn(('turn/interrupt',dict(threadId=THREAD,turnId='operator-reply')),native['calls'])

    def test_poll_avoids_full_history_timeout_when_bounded_native_observation_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120)
                def bounded_read(endpoint,executable,method,params,timeout):
                    if method=='thread/read' and params.get('includeTurns'):
                        raise TimeoutError('full history hydration timed out')
                    if method=='thread/turns/list':
                        self.assertEqual(params['itemsView'],'notLoaded')
                        return dict(data=[dict(id=t,status='inProgress') for t in native['active']],nextCursor=None)
                    return request(endpoint,executable,method,params,timeout)
                with patch('codex_wake.goal_supervision.native_request',side_effect=bounded_read):
                    after=poll(root)[0]
                self.assertEqual(after['state'],'armed')
                self.assertFalse(after.get('stop_latched',False))
                self.assertEqual(after['deadline'],first['deadline'])
                self.assertEqual(native['active'],['work'])

    def test_native_turn_pagination_finds_active_turn_beyond_first_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,request=self.fixture(directory)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,100,120)
                row=json.loads(log.read_text().splitlines()[-1]);row['payload']['response_id']='exhausted'
                row['payload']['usage']=dict(input_tokens=60,cached_input_tokens=0,output_tokens=1,total_tokens=61)
                with log.open('a') as stream:stream.write(json.dumps(row)+'\n')
                def pages(endpoint,executable,method,params,timeout):
                    if method=='thread/turns/list':
                        if 'cursor' not in params:
                            return dict(data=[dict(id='newer-terminal',status='completed')],nextCursor='older')
                        self.assertEqual(params['cursor'],'older')
                        return dict(data=[dict(id='work',status='inProgress' if 'work' in native['active'] else 'interrupted')],nextCursor=None)
                    return request(endpoint,executable,method,params,timeout)
                with patch('codex_wake.goal_supervision.native_request',side_effect=pages):
                    final=poll(root)[0]
                self.assertEqual(final['state'],'stopped')
                self.assertEqual(final['stop_turns'],['work'])
                self.assertEqual(native['active'],[])

    def test_native_observation_failure_or_ambiguous_pagination_never_proves_idle(self):
        for failure in ('endpoint-timeout','repeated-cursor','unknown-status','two-active','page-bound'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                root,policy,_,native,request=self.fixture(directory)
                with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                    enroll(root,policy,THREAD,100,120)
                    page_count=0
                    def unavailable(endpoint,executable,method,params,timeout):
                        nonlocal page_count
                        if method=='thread/turns/list':
                            page_count+=1
                            if failure=='endpoint-timeout':raise TimeoutError('endpoint stalled')
                            if failure=='repeated-cursor':return dict(data=[],nextCursor='same')
                            if failure=='unknown-status':return dict(data=[dict(id='work',status='futureState')])
                            if failure=='two-active':return dict(data=[dict(id=t,status='inProgress') for t in ['work','other']])
                            return dict(data=[],nextCursor='page-'+str(page_count))
                        return request(endpoint,executable,method,params,timeout)
                    with patch('codex_wake.goal_supervision.native_request',side_effect=unavailable):
                        held=poll(root)[0]
                    self.assertEqual(held['state'],'stop_unverified')
                    self.assertEqual(held['reason'],'observation_unavailable')
                    self.assertTrue(held['stop_latched'])
                    self.assertEqual(native['active'],['work'])
                    if failure=='endpoint-timeout':
                        self.assertEqual(held['observation_error'],'TimeoutError')
                        self.assertEqual(held['observation_method'],'thread/turns/list')
                    self.assertLessEqual(page_count,64)  # observation plus stop verification

    def test_unknown_accounting_pauses_campaign_but_allows_bounded_checkpoint_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            with log.open('a') as stream:stream.write('{"type":')
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,100,120,checkpoint_seconds=30)
                first=poll(root)[0]
                self.assertEqual(first['state'],'winding_down')
                self.assertEqual(native['goal']['status'],'paused')
                self.assertEqual(native['active'],['work'])
                self.assertEqual(first['checkpoint']['state'],'acknowledged')
                limit=first['winddown_deadline']
                again=poll(root)[0]
                self.assertEqual(again['winddown_deadline'],limit)
                self.assertEqual(sum(m=='turn/steer' for m,_ in native['calls']),1)
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+31):
                    final=poll(root)[0]
                self.assertEqual(final['state'],'stopped',final)
                native['active']=['operator-reply']
                poll(root)
                self.assertEqual(native['active'],['operator-reply'])

    def test_winddown_grace_never_extends_original_deadline_or_restarts_on_enrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            with log.open('a') as stream:stream.write('{"type":')
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,100,20,checkpoint_seconds=60)
                first=poll(root)[0]
                self.assertEqual(first['winddown_deadline'],NOW+20)
                repeated=enroll(root,policy,THREAD,100,20,checkpoint_seconds=60)
                self.assertEqual(repeated['winddown_deadline'],first['winddown_deadline'])
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+21):
                    self.assertEqual(poll(root)[0]['state'],'stopped')
                self.assertEqual(native['active'],[])

    def test_explicit_resume_during_winddown_is_paused_again_without_renewing_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,native,_=self.fixture(directory)
            with log.open('a') as stream:stream.write('{"type":')
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,100,120,checkpoint_seconds=30)
                first=poll(root)[0]
                native['goal']['status']='active'
                second=poll(root)[0]
                self.assertEqual(second['winddown_deadline'],first['winddown_deadline'])
                self.assertEqual(native['goal']['status'],'paused')
                self.assertEqual(sum(m=='thread/goal/set' for m,_ in native['calls']),2)

    def test_new_enrollment_uses_fresh_tokens_and_preserves_basis_on_reenrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory,cached=37)
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120)
                self.assertEqual(first['used_tokens'],3)
                self.assertEqual(first['token_accounting'],'fresh')
                second=enroll(root,policy,THREAD,100,120)
                self.assertEqual(second['used_tokens'],3)
                inclusive=enroll(root,policy,THREAD,100,120,token_accounting='cache_inclusive')
                self.assertEqual(inclusive['used_tokens'],40)
                self.assertEqual(inclusive['deadline'],first['deadline'])
                self.assertEqual(inclusive['generation'],first['generation'])
                again=enroll(root,policy,THREAD,100,120)
                self.assertEqual(again['token_accounting'],'cache_inclusive')
                self.assertEqual(again['used_tokens'],40)

    def fixture(self,directory,cached=0):
        root=Path(directory)/'wake';root.mkdir(mode=0o700)
        home=Path(directory)/'home';home.mkdir(mode=0o700);(home/'sessions').mkdir(mode=0o700)
        policy=Path(directory)/'policy.json'
        policy.write_text(json.dumps(dict(version=1,callers={THREAD:dict(app_server='unix://'+directory+'/unused.sock',
            codex_path=sys.executable,codex_home=str(home),allocation_id='allocation-1',max_tokens=1000,max_seconds=300,rpc_timeout=1)})))
        policy.chmod(0o600)
        rows=[dict(type='session_meta',payload=dict(id=THREAD,session_id=THREAD,source='cli')),
            dict(type='event_msg',payload=dict(type='thread_goal_updated',threadId=THREAD,
                goal=dict(threadId=THREAD,createdAt=NOW,status='active'))),
            dict(type='event_msg',payload=dict(type='task_started',turn_id='work')),
            dict(type='token_usage_record',payload=dict(thread_id=THREAD,turn_id='work',session_id=THREAD,root_turn_id='work',
                response_id='response-1',usage=dict(input_tokens=38,cached_input_tokens=cached,output_tokens=2,total_tokens=40),
                turn_token_usage={},thread_token_usage={}))]
        log=home/'sessions/owned.jsonl'
        log.write_text(''.join(json.dumps(dict(timestamp='2030-01-01T00:00:00Z',**row))+'\n' for row in rows))
        native=dict(goal=dict(threadId=THREAD,createdAt=NOW,status='active'),active=['work'],calls=[])
        def request(endpoint,executable,method,params,timeout):
            selected=native if params['threadId']==THREAD else native['siblings'][params['threadId']]
            selected['calls'].append((method,params))
            if selected.get('request_hook'):selected['request_hook'](method,params)
            if method=='thread/goal/get':return {'goal':None if selected.get('goal_none') else dict(selected['goal'])}
            if method=='thread/read':
                items=selected.get('user_items', [dict(type='userMessage',content=[dict(type='text',text=selected['user_text'])])] if 'user_text' in selected else [])
                return {'thread':dict(id=params['threadId'],parentThreadId=selected.get('parent_thread_id'),turns=[dict(id=t,status='inProgress',items=items) for t in selected['active']])}
            if method=='thread/turns/list':return dict(data=[dict(id=t,status='inProgress') for t in selected['active']],nextCursor=None)
            if method=='thread/governorLease/set':
                if 'lease_reply' not in selected:raise NotImplementedError('fixture native runtime has no governor lease capability')
                selected.setdefault('lease_calls',[]).append(params)
                if params.get('query') and params['leaseId'].startswith('preflight:'):
                    return dict(leaseId=params['leaseId'],supported=True,armed=False,expired=False,stopVerified=False)
                return dict(selected['lease_reply'],leaseId=params['leaseId'])
            if method.startswith('thread/notice/') and 'notices' in selected:
                notice=selected['notices'].get(params['eventId'])
                if method=='thread/notice/append':
                    notice=dict(eventId=params['eventId'],text=params['text'])
                    selected['notices'][params['eventId']]=notice
                    return dict(eventId=params['eventId'],recorded=True,modelContextAvailable=True,notificationPublished=True)
                return dict(notice=notice,modelContextAvailable=notice is not None)
            if method.startswith('thread/notice/'):
                raise NotImplementedError('fixture native runtime has no notice capability')
            receipts=list((root/'goal-supervision').glob('*.json'))
            saved=next(value for p in receipts if p.name!='controller.json'
                for value in [json.loads(p.read_text())] if value['thread_id']==params['threadId'])
            self.assertTrue(any(effect['state']=='intended' and effect['method']==method for effect in saved['effects'].values()))
            if selected.get('lose')==method:raise TimeoutError('lost response')
            if method=='thread/goal/set':selected['goal']['status']='paused'
            if method=='turn/interrupt':selected['active'].remove(params['turnId'])
            if method=='turn/steer':self.assertEqual(params['expectedTurnId'],'work')
            return {}
        def handler(ws):
            try:
                for raw in ws:
                    message=json.loads(raw)
                    if 'id' not in message:continue
                    if message['method']=='initialize':result=native.get('metadata', {})
                    else:
                        try:result=request(None,None,message['method'],message['params'],None)
                        except NotImplementedError:
                            ws.send(json.dumps(dict(id=message['id'],error=dict(code=-32601,message='Method not found'))));continue
                        except TimeoutError:
                            ws.close();return
                    ws.send(json.dumps(dict(id=message['id'],result=result)))
            except ConnectionClosed:return
        server=unix_serve(handler,str(Path(directory)/'unused.sock'))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def close_server():
            server.shutdown();worker.join(timeout=2)
        self.addCleanup(close_server)
        return root,policy,log,native,request

    @contextmanager
    def controller(self,root,interval=5):
        process=subprocess.Popen([sys.executable,'-c',
            'from codex_wake.goal_supervision import watch; import sys; watch(sys.argv[1],interval=float(sys.argv[2]))',str(root),str(interval)],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            until=time.monotonic()+3
            while not (root/'goal-supervision/controller.json').exists():
                if process.poll() is not None:self.fail(process.stderr.read().decode())
                if time.monotonic()>until:self.fail('watch heartbeat missing')
                time.sleep(.01)
            yield process
        finally:
            process.kill();process.wait(timeout=3);process.stderr.close()

    def test_same_allocation_preserves_original_limits_across_replacement_native_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120)
                self.assertEqual(first['state'],'held')
                self.assertEqual(first['used_tokens'],40)
                native['goal']['createdAt']=NOW+20
                second=enroll(root,policy,THREAD,90,100)
                self.assertEqual(second['goal_created_at'],NOW)
                self.assertEqual(second['deadline'],NOW+100)
                self.assertEqual(first['started_boottime'],second['started_boottime'])
                self.assertEqual(first['generation'],second['generation'])
                with self.assertRaisesRegex(ValueError,'only tighten'):enroll(root,policy,THREAD,100,120)
                self.assertNotIn('grant',second)

    def test_checkpoint_then_original_token_limit_pause_and_interrupt_exact_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                result=enroll(root,policy,THREAD,100,120,checkpoint_token_percent=60,checkpoint_seconds=0)
                self.assertEqual(result['state'],'armed')
                result=poll(root)[0]
                self.assertEqual(result['state'],'checkpoint_requested')
                self.assertEqual(result['checkpoint']['state'],'acknowledged')
                enroll(root,policy,THREAD,40,120)
                result=poll(root)[0]
                self.assertEqual(result['state'],'stopped')
                self.assertEqual(native['goal']['status'],'paused')
                self.assertEqual(native['active'],[])
                self.assertEqual([m for m,p in native['calls'] if m=='turn/steer'],['turn/steer'])

    def test_lost_checkpoint_response_is_not_replayed_and_does_not_delay_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory);native['lose']='turn/steer'
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,100,120,checkpoint_token_percent=60,checkpoint_seconds=0)
                self.assertEqual(poll(root)[0]['checkpoint']['state'],'uncertain')
                poll(root)
                self.assertEqual([m for m,p in native['calls']].count('turn/steer'),1)
                enroll(root,policy,THREAD,40,120)
                self.assertEqual(poll(root)[0]['state'],'stopped')

    def test_explicit_host_allocation_reset_is_only_way_to_reset_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,_,request=self.fixture(directory)
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                first=enroll(root,policy,THREAD,100,120)
                value=json.loads(policy.read_text());value['callers'][THREAD]['allocation_id']='operator-reset-2'
                policy.write_text(json.dumps(value))
                self.assertEqual(show(root,policy,THREAD)['state'],'held')
                reset=enroll(root,policy,THREAD,200,200)
                self.assertEqual(reset['used_tokens'],0)
                self.assertNotEqual(first['generation'],reset['generation'])
                self.assertEqual(reset['goal_created_at'],NOW)

    def test_unknown_stop_response_and_same_generation_enrollment_cannot_replay_or_rearm(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory);native['lose']='thread/goal/set'
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,40,120)
                self.assertEqual(poll(root)[0]['state'],'stop_unverified')
                enrollment=enroll(root,policy,THREAD,40,120)
                self.assertEqual(enrollment['state'],'held')
                self.assertEqual(poll(root)[0]['state'],'stop_unverified')
                self.assertEqual([m for m,p in native['calls']].count('thread/goal/set'),1)
                self.assertEqual([m for m,p in native['calls']].count('turn/interrupt'),1)

    def test_default_checkpoint_and_original_elapsed_deadline_survive_controller_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,42,120)
                self.assertEqual(poll(root)[0]['state'],'checkpoint_requested')
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+121):
                    stopped=poll(root)[0]
                    self.assertEqual(stopped['state'],'stopped')
                    self.assertEqual(stopped['first_stop']['observed_upper'],NOW+121)
                    self.assertIsNone(stopped['first_stop']['observed_boottime'])
                    self.assertIsNone(stopped['stop_episodes'][-1]['observed_boottime'])
                self.assertEqual(native['active'],[])

    def test_unqualified_utc_stops_without_rewriting_original_allowance(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                original=enroll(root,policy,THREAD,100,120)
                with patch('codex_wake.lifecycle_budget.trusted_upper',side_effect=ValueError('unqualified')):
                    result=poll(root)[0]
                self.assertEqual(result['reason'],'clock_unqualified')
                self.assertEqual(result['state'],'stopped')
                self.assertEqual(native['active'],[])
                retained=show(root,policy,THREAD)
                self.assertFalse(retained['first_stop']['clock_qualified'])
                self.assertIsNone(retained['first_stop']['observed_upper'])
                self.assertIsNone(retained['first_stop']['observed_boottime'])
                self.assertEqual(retained['first_stop']['clock_reason'],'clock_unqualified')
                for name in ('deadline','time_origin','started_upper','used_tokens','token_limit'):
                    self.assertEqual(retained[name],original[name])

    def test_revoked_host_grant_stops_only_persisted_exact_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                enroll(root,policy,THREAD,100,120)
                value=json.loads(policy.read_text());value['callers']={};policy.write_text(json.dumps(value))
                result=poll(root)[0]
                self.assertEqual(result['state'],'stopped')
                self.assertEqual(native['goal']['status'],'paused')
                self.assertEqual(native['active'],[])

    def test_stale_or_dead_independent_controller_is_never_displayed_as_armed(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,_,request=self.fixture(directory)
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                with self.controller(root):
                    self.assertEqual(enroll(root,policy,THREAD,100,120)['state'],'armed')
                status=show(root,policy,THREAD)
                self.assertEqual(status['state'],'held')
                self.assertFalse(status['controller']['fresh'])

    def test_malformed_host_policy_is_refused_as_value_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,_,_=self.fixture(directory)
            for text in ('{"version":true,"callers":{}}','{"version":1,"version":1,"callers":{}}',
                         '{"version":1,"callers":{}}'):
                policy.write_text(text)
                with self.assertRaises(ValueError):enroll(root,policy,THREAD,100,120)
