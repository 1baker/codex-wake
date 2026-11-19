"""Common-policy decisions at the public CLI/MCP boundary (#320)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SessionPermissionsTests(unittest.TestCase):
    def setUp(self):
        clock = patch('codex_wake.measurements.utc_bounds', return_value=(100, 100))
        clock.start()
        self.addCleanup(clock.stop)

    def test_bounded_approval_uses_stable_time_upper_without_renewing_expiry(self):
        from codex_wake.session_permissions import PermissionStore, Principal
        with tempfile.TemporaryDirectory() as tmp:
            configured = PermissionStore(tmp, now=lambda: 100)
            configured.configure({'version': 1, 'approvals': [
                dict(id='approval', action='job.launch', subject='worker', scope='task',
                     task_id='task', expires_at='1970-01-01T00:03:20Z', issuer='operator')]},
                Principal('operator', 'operator'), expected_revision=0)
            policy_bytes = configured.path.read_bytes()
            actor = Principal('worker', tasks=('task',))
            with patch('codex_wake.measurements.utc_bounds', return_value=(198, 199)), \
                    patch('time.time', return_value=10000):
                before = PermissionStore(tmp).evaluate('job.launch', actor, task_id='task')
            self.assertEqual(before['permission'], 'allow')
            with patch('codex_wake.measurements.utc_bounds', return_value=(199, 200)), \
                    patch('time.time', return_value=-10000):
                at_expiry = PermissionStore(tmp).evaluate('job.launch', actor, task_id='task')
            self.assertEqual(at_expiry['permission'], 'approval_required')
            self.assertEqual(configured.path.read_bytes(), policy_bytes)

    def test_unqualified_time_holds_bounded_approvals_but_preserves_standing_control(self):
        from codex_wake.measurements import TimeUnavailable
        from codex_wake.session_permissions import PermissionStore, Principal, PermissionDenied, check_operation
        with tempfile.TemporaryDirectory() as tmp:
            actor = Principal('worker', tasks=('task',))
            with patch('codex_wake.measurements.utc_time', side_effect=TimeUnavailable('private-clock-detail')):
                store = PermissionStore(tmp)
                store.configure({'version': 1, 'approvals': [
                    dict(id='bounded', action='job.launch', subject='worker', scope='task',
                         task_id='task', expires_at='1970-01-01T00:03:20Z', issuer='operator'),
                    dict(id='standing-stop', action='job.cancel', subject='worker', scope='standing',
                         issuer='operator')]}, Principal('operator', 'operator'), expected_revision=0)
                decision = store.evaluate('job.launch', actor, task_id='task')
                self.assertEqual((decision['permission'], decision['rule']),
                                 ('approval_required', 'qualified_time_unavailable'))
                with self.assertRaises(PermissionDenied) as refused:
                    check_operation(tmp, 'job.launch', actor, task_id='task')
                self.assertEqual(refused.exception.code, 'permission_approval_required')
                self.assertEqual(store.evaluate('job.cancel', actor)['approval_id'], 'standing-stop')
                self.assertEqual(store.evaluate('session.inspect', actor)['permission'], 'allow')
            audit = json.loads(store.path.read_text())['history'][-1]
            self.assertIsNone(audit['at'])
            self.assertEqual(audit['time_state'], 'unavailable')
            self.assertNotIn('private-clock-detail', json.dumps(decision))
            self.assertEqual(PermissionStore(tmp, now=lambda: 100).evaluate(
                'job.launch', actor, task_id='task')['approval_id'], 'bounded')

    def test_public_mcp_inspects_new_native_self_without_uuid_grant(self):
        from codex_wake.mcp_server import CommandRunner
        from codex_wake.session_permissions import PermissionStore, Principal
        thread='00000000-0000-7000-8000-000000000320'
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp)
            store.configure({'version':1},Principal('operator','operator'),expected_revision=0)
            runner=CommandRunner(wake_root=Path(tmp))
            meta=dict(threadId=thread,sessionId=thread,callId='call',**{
                'x-codex-turn-metadata':dict(thread_id=thread,session_id=thread,turn_id='turn')})
            value,failed=runner.call('wake_permissions_show',dict(caller_thread_id=thread,
                action='refresh.self'),native_context=meta)
            self.assertFalse(failed,value)
            self.assertEqual(value['permission'],'allow')
            self.assertEqual(value['relationship'],'self')
            self.assertEqual(value['readiness'],'not_observed')
            denied,failed=runner.call('wake_permissions_show',dict(caller_thread_id=thread,
                action='refresh.self'),native_context={})
            self.assertTrue(failed,denied)

    def test_global_override_mandatory_and_revision_are_enforced(self):
        from codex_wake.session_permissions import PermissionStore,Principal,PermissionDenied
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp);operator=Principal('op','operator');actor=Principal('self')
            store.configure({'version':1,'global':{'actions':{'refresh.self':'deny'}},
                'sessions':{'self':{'actions':{'refresh.self':'allow'}}},
                'mandatory':['refresh.shared']},operator,expected_revision=0)
            self.assertEqual(store.evaluate('refresh.self',actor)['permission'],'allow')
            self.assertEqual(store.evaluate('refresh.shared',actor,target='daemon',relationship='shared')['permission'],'deny')
            with self.assertRaises(PermissionDenied):
                store.configure({'version':1},operator,expected_revision=0)
            with self.assertRaises(PermissionDenied):
                store.change_session('self',{'actions':{'refresh.self':'allow'}},actor,expected_revision=1)
            store.change_session('self',{'actions':{'refresh.self':'deny'}},actor,expected_revision=1)
            self.assertEqual(store.evaluate('refresh.self',actor)['permission'],'deny')

    def test_new_actions_and_scoped_approvals_do_not_renew_authority(self):
        from codex_wake.session_permissions import PermissionStore,Principal
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp,now=lambda:100)
            store.configure({'version':1,'known_actions':['session.inspect'], 'approvals':[
                dict(id='approval',action='enforcement.increase',subject='self',scope='task',
                     task_id='task',expires_at='1970-01-01T00:03:20Z',issuer='operator')]},
                Principal('op','operator'),expected_revision=0)
            actor=Principal('self',tasks=('task',))
            self.assertEqual(store.evaluate('refresh.self',actor)['permission'],'approval_required')
            self.assertEqual(store.evaluate('enforcement.increase',actor,task_id='task')['approval_id'],'approval')
            self.assertEqual(store.evaluate('enforcement.increase',actor)['permission'],'approval_required')
            store.now=lambda:201
            self.assertEqual(store.evaluate('enforcement.increase',actor,task_id='task')['permission'],'approval_required')

    def test_scoped_refresh_refuses_shared_fallback_before_any_admission(self):
        from codex_wake.session_permissions import PermissionStore,Principal
        from codex_wake.mcp_server import CommandRunner
        thread='00000000-0000-7000-8000-000000000320'
        with tempfile.TemporaryDirectory() as tmp:
            PermissionStore(tmp).configure({'version':1},Principal('op','operator'),expected_revision=0)
            profile=Path(tmp)/'profiles.json'
            profile.write_text(json.dumps(dict(version=1,callers={},profiles={'self':dict(
                refresh_mode='shared_mcp_idle',scope_approval='standing host approval',cwd=tmp,
                app_server='unix:///missing',codex_path='/bin/true',timeout=1,resources={'wake':{}})})))
            profile.chmod(0o600)
            runner=CommandRunner(wake_root=Path(tmp),lifecycle_profiles=profile)
            meta=dict(threadId=thread,sessionId=thread,callId='call',**{'x-codex-turn-metadata':
                dict(thread_id=thread,session_id=thread,turn_id='turn')})
            result,failed=runner.call('wake_sessions_refresh',dict(caller_thread_id=thread,
                thread_id=thread,profile='self',intent='scope-test',scope='current_connection',
                checkpoint='missing',checkpoint_sha256='a'*64,resources=['wake'],expires_at='2030-01-01T00:00:00Z'),native_context=meta)
            self.assertTrue(failed,result)
            self.assertEqual(result['error']['code'],'refresh_scope_unsupported')
            self.assertFalse((Path(tmp)/'shared-refresh').exists())
            self.assertEqual(json.loads(profile.read_text())['callers'],{})

    def test_operator_cli_and_native_mcp_share_policy(self):
        from codex_wake.a2a_bus import BusStore
        from codex_wake.cli import run
        from io import StringIO
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bus,capability=BusStore.configure(root/'bus')
            policy=root/'policy.json';policy.write_text(json.dumps({'version':1,'global':{'actions':{'refresh.self':'deny'}}}));policy.chmod(0o600)
            common=['--wake-root',str(root/'state'),'permissions']
            with redirect_stdout(StringIO()):
                code=run(common+['configure','--bus-root',str(bus.root),'--operator-capability',str(capability),'--file',str(policy),'--expected-revision','0','--json'])
            self.assertEqual(code,0)
            output=StringIO()
            with redirect_stdout(output):
                code=run(common+['show','--bus-root',str(bus.root),'--operator-capability',str(capability),'--subject','self','--action','refresh.self','--json'])
            self.assertEqual(code,0)
            self.assertEqual(json.loads(output.getvalue())['permission'],'deny')

    def test_native_updates_cannot_self_promote_but_delegation_is_scoped(self):
        from codex_wake.session_permissions import PermissionStore,Principal
        from codex_wake.mcp_server import CommandRunner
        caller='00000000-0000-7000-8000-000000000320'
        peer='00000000-0000-7000-8000-000000000321'
        meta=dict(threadId=caller,sessionId=caller,callId='call',**{'x-codex-turn-metadata':dict(thread_id=caller,session_id=caller,turn_id='turn')})
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp);store.configure({'version':1},Principal('op','operator'),expected_revision=0)
            runner=CommandRunner(wake_root=Path(tmp))
            value,failed=runner.call('wake_permissions_update',dict(caller_thread_id=caller,
                subject=caller,layer={'actions':{'refresh.self':'allow'}},expected_revision=1),native_context=meta)
            self.assertTrue(failed,value)
            self.assertEqual(value['error']['code'],'permission_self_promotion')
            store.configure({'version':1,'delegations':{caller:{'actions':['refresh.self'],'sessions':[peer]}}},Principal('op','operator'),expected_revision=1)
            value,failed=runner.call('wake_permissions_update',dict(caller_thread_id=caller,
                subject=peer,layer={'actions':{'refresh.self':'deny'}},expected_revision=2),native_context=meta)
            self.assertFalse(failed,value)
            self.assertEqual(store.evaluate('refresh.self',Principal(peer))['permission'],'deny')
            value,failed=runner.call('wake_permissions_update',dict(caller_thread_id=caller,
                subject=peer,layer={'actions':{'enforcement.increase':'allow'}},expected_revision=3),native_context=meta)
            self.assertTrue(failed,value)
            self.assertEqual(value['error']['code'],'permission_delegation_exceeded')

    def test_malformed_policy_unknown_action_and_private_path_fail_closed(self):
        from codex_wake.session_permissions import PermissionStore,Principal,PermissionDenied
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp);op=Principal('op','operator')
            for value in ({'version':True},{'version':1,'global':{'actions':{'typo':'allow'}}},
                          {'version':1,'mandatory':'refresh.self'}, {'version':1,'future_actions_inherit':'yes'}):
                with self.assertRaises(ValueError):store.configure(value,op,expected_revision=0)
            store.configure({'version':1},op,expected_revision=0)
            with self.assertRaises(PermissionDenied):store.evaluate('typo',Principal('self'))
            store.path.chmod(0o644)
            with self.assertRaises(Exception):store.evaluate('refresh.self',Principal('self'))

    def test_task_approval_transfers_by_default_and_completion_revokes_it(self):
        from codex_wake.session_permissions import PermissionStore,Principal
        from codex_wake.wake_policy import complete_owner
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp,now=lambda:100)
            store.configure({'version':1,'approvals':[dict(id='approve',action='enforcement.increase',
                subject='source',scope='task',task_id='task',expires_at='1970-01-01T00:03:20Z',issuer='op')]},
                Principal('op','operator'),expected_revision=0)
            successor=Principal('next',tasks=('task',),predecessor='source')
            self.assertEqual(store.evaluate('enforcement.increase',successor,task_id='task')['permission'],'allow')
            complete_owner(Path(tmp),{'kind':'task','id':'task'},'done',actor='operator:owner')
            self.assertEqual(store.evaluate('enforcement.increase',successor,task_id='task')['permission'],'deny')

    def test_globally_preauthorized_profile_needs_no_session_uuid_entry(self):
        from codex_wake.session_permissions import PermissionStore,Principal
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp)
            store.configure({'version':1,'global':{'authorized_profiles':['review']},
                'profiles':{'review':{'default':'deny','actions':{'session.inspect':'allow'}}}},
                Principal('op','operator'),expected_revision=0)
            actor=Principal('new-session')
            store.change_session('new-session',{'profile':'review'},actor,expected_revision=1)
            self.assertEqual(store.evaluate('refresh.self',actor)['permission'],'deny')
            self.assertEqual(store.evaluate('session.inspect',actor)['permission'],'allow')

    def test_explicit_configuration_and_deny_win_over_new_action_default(self):
        from codex_wake.session_permissions import PermissionStore,Principal
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp)
            store.configure({'version':1,'known_actions':[],
                'global':{'actions':{'refresh.self':'allow','enforcement.recover':'deny'}}},
                Principal('op','operator'),expected_revision=0)
            self.assertEqual(store.evaluate('refresh.self',Principal('self'))['permission'],'allow')
            self.assertEqual(store.evaluate('enforcement.recover',Principal('self'))['permission'],'deny')
            self.assertEqual(store.evaluate('resume.self',Principal('self'))['permission'],'approval_required')

    def test_operator_pins_one_policy_across_separate_execution_roots(self):
        from codex_wake.session_permissions import PermissionStore,Principal,PermissionDenied
        with tempfile.TemporaryDirectory() as tmp:
            common=Path(tmp)/'common';lifecycle=Path(tmp)/'lifecycle';goals=Path(tmp)/'goals'
            operator=Principal('op','operator');policy=PermissionStore(common)
            policy.configure({'version':1},operator,expected_revision=0)
            policy.bind_domain(lifecycle,operator);policy.bind_domain(goals,operator)
            self.assertEqual(PermissionStore(lifecycle).root,common)
            policy.configure({'version':1,'mandatory':['refresh.self','enforcement.enroll']},operator,expected_revision=1)
            self.assertEqual(PermissionStore(lifecycle).evaluate('refresh.self',Principal('self'))['permission'],'deny')
            self.assertEqual(PermissionStore(goals).evaluate('enforcement.enroll',Principal('self'))['permission'],'deny')
            self.assertFalse((lifecycle/'session-permissions').exists())
            policy.path.unlink()
            self.assertTrue(PermissionStore(goals).active())
            with self.assertRaises(Exception):PermissionStore(goals).evaluate('enforcement.enroll',Principal('self'))
            with self.assertRaises(PermissionDenied):policy.bind_domain(Path(tmp)/'new',Principal('self'))

    @unittest.skipIf(__import__('os').name=='nt','POSIX flock boundary')
    def test_held_policy_lock_returns_bounded_effect_uncertainty(self):
        import fcntl,time
        from codex_wake.session_permissions import PermissionStore,Principal
        from codex_wake.mcp_server import CommandRunner
        caller='00000000-0000-7000-8000-000000000320'
        meta=dict(threadId=caller,sessionId=caller,callId='call',**{'x-codex-turn-metadata':dict(thread_id=caller,session_id=caller,turn_id='turn')})
        with tempfile.TemporaryDirectory() as tmp:
            store=PermissionStore(tmp);store.configure({'version':1},Principal('op','operator'),expected_revision=0)
            lock=store.directory/'policy.lock'
            with lock.open('a') as held:
                fcntl.flock(held,fcntl.LOCK_EX)
                runner=CommandRunner(wake_root=Path(tmp),call_timeout=.2)
                before=time.monotonic()
                result,failed=runner.call('wake_permissions_update',dict(caller_thread_id=caller,
                    subject=caller,layer={'actions':{'refresh.self':'deny'}},expected_revision=1),native_context=meta)
                self.assertTrue(failed,result)
                self.assertEqual(result['error']['code'],'effect_uncertain')
                self.assertLess(time.monotonic()-before,2)
            self.assertEqual(store._read()['revision'],1)
