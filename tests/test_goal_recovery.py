"""Public recovery preserves the original campaign after a transient native fault."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_goal_supervision as fixtures
from codex_wake.a2a_bus import BusStore
from codex_wake.cli import run
from codex_wake.goal_supervision import enroll, poll
from codex_wake.session_permissions import PermissionStore, Principal

THREAD, NOW = fixtures.THREAD, fixtures.NOW

class GoalRecoveryTests(unittest.TestCase):
    fixture = fixtures.GoalSupervisionTests.fixture
    controller = fixtures.GoalSupervisionTests.controller

    def test_operator_recovers_observation_fault_without_renewing_or_reinterrupting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, policy, _, native, request = self.fixture(tmp)
            bus, cap = BusStore.configure(Path(tmp)/'bus')
            PermissionStore(root).configure({'version':1}, Principal('operator','operator'), expected_revision=0)
            with self.controller(root), patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                original = enroll(root,policy,THREAD,100,120,permission_principal=Principal(THREAD))
                def timeout(endpoint, executable, method, params, limit):
                    if method=='thread/read': raise TimeoutError('transient fixture fault')
                    return request(endpoint,executable,method,params,limit)
                with patch('codex_wake.goal_supervision.native_request',side_effect=timeout):
                    failed = poll(root)[0]
                self.assertEqual(failed['reason'],'observation_unavailable')
                self.assertTrue(failed['stop_latched'])
                stopped=poll(root)[0]
                self.assertTrue(stopped['stop_latched'])  # Healthy read alone never recovers.
                native['active']=['operator-recovery-turn']
                output=StringIO()
                with redirect_stdout(output):
                    code=run(['--wake-root',str(root),'goal-limits','recover','--policy',str(policy),
                        '--caller-thread-id',THREAD,'--bus-root',str(bus.root),
                        '--operator-capability',str(cap),'--json'])
                recovered=json.loads(output.getvalue())
                self.assertEqual(code,0,recovered)
                from codex_wake.goal_notices import list_notices
                self.assertFalse(recovered['stop_latched'])
                self.assertEqual(recovered['first_stop'],failed['first_stop'])
                for key in ('deadline','used_tokens','token_limit','time_limit_seconds','generation','allocation_id'):
                    self.assertEqual(recovered[key],original[key],key)
                native['goal']['status']='active';native['active']=['operator-next-turn'];native['calls'].clear()
                later=poll(root)[0]
                self.assertEqual(later['state'],'armed')
                self.assertFalse(any(m in ('thread/goal/set','turn/interrupt') for m,_ in native['calls']))
                with patch('codex_wake.goal_supervision.native_request',side_effect=timeout):
                    second_fault=poll(root)[0]
                self.assertEqual(len(second_fault['stop_episodes']),2)
                self.assertEqual(second_fault['first_stop'],failed['first_stop'])
                self.assertNotEqual(second_fault['stop_episodes'][0]['id'],second_fault['stop_episodes'][1]['id'])
                self.assertEqual(recovered['recovery_events'][0]['stop_episode_id'],second_fault['stop_episodes'][0]['id'])
                stops=[event for event in list_notices(root,THREAD) if event['identity']['kind']=='stop']
                self.assertEqual(len(stops),2)
                self.assertCountEqual([event['identity']['stop_episode'] for event in stops],
                    [episode['id'] for episode in second_fault['stop_episodes']])
                recovery_notices=[event for event in list_notices(root,THREAD) if event['identity']['kind']=='recovery']
                self.assertEqual(len(recovery_notices),1)
                self.assertEqual(recovery_notices[0]['identity']['stop_episode'],failed['active_stop_id'])
                self.assertEqual(recovery_notices[0]['identity']['reason'],'observation_recovered')
                self.assertIn('goal remains paused',recovery_notices[0]['text'])

    def test_public_native_recovery_uses_approval_and_keeps_unrelated_campaign(self):
        from codex_wake.mcp_server import CommandRunner
        from codex_wake.goal_supervision import show
        peer='00000000-0000-7000-8000-000000000319'
        with tempfile.TemporaryDirectory() as tmp:
            root,policy,log,native,request=self.fixture(tmp)
            config=json.loads(policy.read_text());config['callers'][peer]=dict(config['callers'][THREAD],allocation_id='unrelated')
            policy.write_text(json.dumps(config))
            log.with_name('peer.jsonl').write_text(log.read_text().replace(THREAD,peer))
            native['siblings']={peer:dict(goal=dict(threadId=peer,createdAt=NOW,status='active'),active=['peer-work'],calls=[])}
            store=PermissionStore(root)
            store.configure({'version':1,'approvals':[dict(id='operator-recover',scope='standing',
                action='enforcement.recover',subject=THREAD,issuer='operator')]},Principal('operator','operator'),expected_revision=0)
            meta=dict(threadId=THREAD,sessionId=THREAD,callId='recover-request',**{
                'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='operator-reply')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                original=enroll(root,policy,THREAD,100,120,permission_principal=Principal(THREAD))
                unrelated=enroll(root,policy,peer,100,120,permission_principal=Principal(peer))
                def timeout(endpoint,executable,method,params,limit):
                    if method=='thread/read' and params['threadId']==THREAD:raise TimeoutError('fixture')
                    return request(endpoint,executable,method,params,limit)
                with patch('codex_wake.goal_supervision.native_request',side_effect=timeout):poll(root)
                poll(root)
                status=show(root,policy,THREAD,permission_principal=Principal(THREAD))
                self.assertEqual(status['recovery']['action'],'wake_goal_limits_recover')
                runner=CommandRunner(wake_root=root,goal_limits_policy=policy)
                result,failed=runner.call('wake_goal_limits_recover',dict(caller_thread_id=THREAD),native_context=meta)
                self.assertFalse(failed,result)
                self.assertFalse(result['stop_latched'])
                self.assertEqual(result['recovery_permission']['approval_id'],'operator-recover')
                self.assertEqual(result['deadline'],original['deadline'])
                current=show(root,policy,peer,permission_principal=Principal(peer))
                self.assertEqual(current['deadline'],unrelated['deadline'])
                self.assertEqual(current['used_tokens'],unrelated['used_tokens'])
                self.assertEqual(native['siblings'][peer]['goal']['status'],'active')
                self.assertFalse(any(m in ('thread/goal/set','turn/interrupt') for m,_ in native['siblings'][peer]['calls']))

    def test_recovery_refuses_lost_authority_or_unqualified_observation(self):
        from codex_wake.goal_recovery import recover
        from codex_wake.session_permissions import PermissionDenied
        scenarios=dict(revoked='permission_deny',accounting='recovery_accounting_unqualified',
            boot='recovery_boot_identity_changed',exhausted='recovery_resources_exhausted',
            expired_at_locked_admission='recovery_resources_exhausted',clock_unknown='recovery_clock_unqualified',
            active_work='recovery_native_stop_unverified',unobserved_scope='recovery_native_stop_unverified',changed_goal='recovery_goal_identity_changed')
        for scenario in scenarios:
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as tmp:
                root,policy,log,native,request=self.fixture(tmp)
                store=PermissionStore(root);store.configure({'version':1},Principal('operator','operator'),expected_revision=0)
                with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                    enroll(root,policy,THREAD,100,120,permission_principal=Principal(THREAD))
                    def timeout(endpoint,executable,method,params,limit):
                        if method=='thread/read':raise TimeoutError('fixture')
                        return request(endpoint,executable,method,params,limit)
                    with patch('codex_wake.goal_supervision.native_request',side_effect=timeout):poll(root)
                    if scenario=='unobserved_scope':native['goal']['status']='paused'
                    poll(root)
                    path=next(p for p in (root/'goal-supervision').glob('*.json') if p.name!='controller.json')
                    before=path.read_bytes();manager=None
                    if scenario=='revoked':store.configure({'version':1,'mandatory':['enforcement.recover']},Principal('operator','operator'),expected_revision=1)
                    if scenario=='accounting':log.write_text('{"type":')
                    if scenario=='boot':manager=patch('codex_wake.goal_supervision.boot_id_value',return_value='other-boot')
                    if scenario=='exhausted':
                        manager=patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+200)
                    if scenario=='expired_at_locked_admission':
                        manager=patch('codex_wake.lifecycle_budget.trusted_upper',side_effect=[NOW,NOW+200])
                    if scenario=='clock_unknown':
                        manager=patch('codex_wake.lifecycle_budget.trusted_upper',side_effect=ValueError('clock unavailable'))
                    if scenario=='active_work':native['active']=['work']
                    if scenario=='changed_goal':native['goal']['createdAt']=NOW+1
                    from contextlib import nullcontext
                    with manager or nullcontext():
                        with self.assertRaises(PermissionDenied) as denied:
                            recover(root,policy,THREAD,principal=Principal(THREAD,'operator'))
                        self.assertEqual(denied.exception.code,scenarios[scenario])
                    self.assertEqual(path.read_bytes(),before)

    def test_recovery_crash_reconciles_same_allocation_without_duplicate_history(self):
        import os
        from codex_wake.goal_recovery import recover
        from codex_wake.goal_supervision import show
        with tempfile.TemporaryDirectory() as tmp:
            root,policy,_,native,request=self.fixture(tmp)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,
                default_allocation='allocation-1',allocations={'allocation-1':grant})))
            PermissionStore(root).configure({'version':1},Principal('operator','operator'),expected_revision=0)
            meta=dict(threadId=THREAD,sessionId=THREAD,callId='admission',**{
                'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                original=enroll(root,policy,THREAD,100,120,permission_principal=Principal(THREAD),native_context=meta)
                def timeout(endpoint,executable,method,params,limit):
                    if method=='thread/read':raise TimeoutError('fixture')
                    return request(endpoint,executable,method,params,limit)
                with patch('codex_wake.goal_supervision.native_request',side_effect=timeout):poll(root)
                poll(root)
                ledger=Path(original['allocation_path']);replace=os.replace
                def crash_final_commit(source,destination):
                    if Path(destination)==ledger and not json.loads(Path(source).read_text()).get('stop_latched',True):
                        raise KeyboardInterrupt('crash after receipt and before ledger commit')
                    return replace(source,destination)
                with patch('os.replace',side_effect=crash_final_commit):
                    with self.assertRaises(KeyboardInterrupt):recover(root,policy,THREAD,principal=Principal(THREAD,'operator'),operation_id='recover-once')
                self.assertTrue(json.loads(ledger.read_text())['stop_latched'])
                pending=show(root,policy,THREAD,permission_principal=Principal(THREAD))
                self.assertEqual(pending['state'],'held')
                self.assertEqual(pending['recovery']['status'],'pending_reconciliation')
                reconciled=recover(root,policy,THREAD,principal=Principal(THREAD,'operator'),operation_id='recover-once')
                self.assertFalse(reconciled['stop_latched'])
                self.assertEqual(reconciled['deadline'],original['deadline'])
                self.assertEqual(reconciled['used_tokens'],40)
                self.assertEqual(len(reconciled['recovery_events']),1)
                self.assertFalse(json.loads(ledger.read_text())['stop_latched'])

    def test_explicit_operator_allocation_recovery_reconciles_all_members(self):
        from codex_wake.goal_recovery import recover
        peer='00000000-0000-7000-8000-000000000320'
        for fault_target in (THREAD,peer):
            with tempfile.TemporaryDirectory() as tmp:
                root,policy,log,native,request=self.fixture(tmp)
                grant=json.loads(policy.read_text())['callers'][THREAD]
                policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,
                    default_allocation='allocation-1',allocations={'allocation-1':grant})))
                log.with_name('peer.jsonl').write_text(log.read_text().replace(THREAD,peer))
                native['siblings']={peer:dict(goal=dict(threadId=peer,createdAt=NOW,status='active'),active=['peer-work'],calls=[])}
                PermissionStore(root).configure({'version':1},Principal('operator','operator'),expected_revision=0)
                def meta(thread):return dict(threadId=thread,sessionId=thread,callId='admit',**{
                    'x-codex-turn-metadata':dict(thread_id=thread,session_id=thread,turn_id='work')})
                with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW):
                    first=enroll(root,policy,THREAD,100,120,permission_principal=Principal(THREAD),native_context=meta(THREAD))
                    enroll(root,policy,peer,100,120,permission_principal=Principal(peer),native_context=meta(peer))
                    def timeout(endpoint,executable,method,params,limit):
                        if method=='thread/read' and params['threadId']==fault_target:raise TimeoutError('fixture')
                        return request(endpoint,executable,method,params,limit)
                    with patch('codex_wake.goal_supervision.native_request',side_effect=timeout):poll(root)
                    poll(root)
                    value=recover(root,policy,fault_target,principal=Principal(fault_target,'operator'),allocation_id='allocation-1')
                    self.assertFalse(value['stop_latched'])
                    self.assertEqual(value['used_tokens'],80)
                    self.assertEqual(value['deadline'],first['deadline'])
                    samples=poll(root)
                    self.assertTrue(all(not item['stop_latched'] for item in samples))
                    self.assertTrue(all(item['used_tokens']==80 for item in samples))
