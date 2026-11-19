"""Own-session setup through the public hook and real controller process."""
from contextlib import contextmanager
import json
import os
import signal
import tempfile
import time
import unittest
from unittest.mock import patch
import test_goal_supervision as fixtures
THREAD, NOW = fixtures.THREAD, fixtures.NOW


@contextmanager
def fixture_clock(directory, observation):
    """Share injected measurement evidence with only this case's owned watcher."""
    from pathlib import Path
    import subprocess
    clock_path = Path(directory) / 'measurement.json'
    controller_path = Path(directory) / 'wake/goal-supervision/controller.json'
    def publish():
        temporary = clock_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(observation))
        temporary.replace(clock_path)
    def sample():
        publish()
        return json.loads(json.dumps(observation))
    def synchronize():
        publish()
        if controller_path.exists():
            end = time.monotonic() + 3
            while time.monotonic() < end:
                if json.loads(controller_path.read_text()).get('clock_observation') == observation:
                    return
                time.sleep(.01)
            raise AssertionError('owned watcher did not observe fixture measurement')
    bootstrap = """import json,runpy,sys
from pathlib import Path
from codex_wake import measurements,native_clock
path=Path(sys.argv.pop(1))
mode=sys.argv.pop(1);entry=sys.argv.pop(1)
def sample():return json.loads(path.read_text())
measurements.snapshot=sample
native_clock.snapshot=sample
if mode=='module':runpy.run_module(entry,run_name='__main__')
else:
 # Counter scenarios drive poll explicitly against their injected native peer.
 # The child supplies the real singleton lock, process and clock heartbeat.
 from codex_wake import goal_supervision
 goal_supervision.poll=lambda root: []
 exec(entry)
"""
    original = subprocess.Popen
    def launch(command, *args, **kwargs):
        command = list(command)
        if command[1:3] == ['-m', 'codex_wake.self_limits']:
            command = [command[0], '-c', bootstrap, str(clock_path), 'module', command[2], *command[3:]]
        elif len(command)>2 and command[1]=='-c' and 'from codex_wake.goal_supervision import watch' in command[2]:
            command = [command[0], '-c', bootstrap, str(clock_path), 'code', command[2], *command[3:]]
        return original(command, *args, **kwargs)
    publish()
    with patch('codex_wake.measurements.snapshot',side_effect=sample), patch(
            'codex_wake.native_clock.snapshot',side_effect=sample), patch('subprocess.Popen',side_effect=launch):
        yield synchronize


class SelfLimitsTests(unittest.TestCase):
    fixture = fixtures.GoalSupervisionTests.fixture
    def test_own_setup_starts_controller_and_stops_at_existing_usage(self):
        from codex_wake.self_limits import execute
        with tempfile.TemporaryDirectory() as directory, self.controllers():
            root, policy, _, native, _ = self.fixture(directory)
            grant = json.loads(policy.read_text())['callers'][THREAD]
            grant.pop('allocation_id')
            policy.write_text(json.dumps(dict(version=2, native_caller_binding=True,
                allocations={}, self_enrollment=grant)))
            context = dict(threadId=THREAD, sessionId=THREAD, callId='self-test',
                **{'x-codex-turn-metadata': dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            observation=dict(reason='authenticated_utc',valid_for_ns=300000000000,
                utc=dict(status='network',lower=NOW,upper=NOW),counter=dict(
                    epoch='c357309d-c209-4467-b757-e1488e6b1aaa',counter=1000,frequency=1000,rate_ppm=0))
            with fixture_clock(directory,observation), patch('codex_wake.lifecycle_budget.trusted_upper', return_value=NOW), patch('codex_wake.goal_watcher.watcher_status', return_value=dict(reason='watcher_not_installed')):
                first = execute(root, policy, 'set', dict(token_limit=100,time_limit_seconds=120), native_context=context)
                self.assertIn('pid', first['controller'], (first, (root/'goal-supervision/self-watcher.log').read_text() if (root/'goal-supervision/self-watcher.log').exists() else 'no log'))
                pid = first['controller']['pid']
                self.assertTrue(first['controller']['fresh'])
                self.assertEqual(first['used_tokens'],40)
                with self.assertRaisesRegex(ValueError, 'tighten'):
                    execute(root,policy,'set',dict(token_limit=101,time_limit_seconds=120),native_context=context)
                tightened = execute(root,policy,'set',dict(token_limit=39,time_limit_seconds=120),native_context=context)
                self.assertEqual(tightened['lifetime_used_tokens'],40)
                end=time.monotonic()+6
                while time.monotonic()<end and native['goal']['status']!='paused':
                    time.sleep(.05)
                self.assertEqual(native['goal']['status'],'paused')
                self.assertEqual(native['active'],[])

    def test_mask_and_inherited_ceiling_are_preserved(self):
        from codex_wake.self_limits import execute, _CHILDREN
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            context=dict(threadId=THREAD,sessionId=THREAD,callId='self-test',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW), patch(
                    'codex_wake.goal_watcher.watcher_status',return_value=dict(reason='watcher_masked')):
                with self.assertRaisesRegex(ValueError,'inherited host ceilings'):
                    execute(root,policy,'set',dict(token_limit=1001,time_limit_seconds=120),native_context=context)
                result=execute(root,policy,'set',dict(token_limit=100,time_limit_seconds=120),native_context=context)
                self.assertEqual(result['watcher_setup']['reason'],'watcher_masked')
                self.assertFalse(result['engagement']['engaged'])
                self.assertFalse(_CHILDREN)
                with self.assertRaisesRegex(ValueError,'show and set/tighten only'):
                    execute(root,policy,'disable',{},native_context=context)
                self.assertFalse(any(method in ('thread/goal/set','turn/interrupt') for method,_ in native['calls']))

    def test_default_policy_allows_self_watcher_but_external_deny_wins(self):
        from codex_wake.self_limits import execute
        from codex_wake.session_permissions import PermissionStore, Principal
        for denied in (False, True):
            with self.subTest(denied=denied), tempfile.TemporaryDirectory() as directory, self.controllers():
                root,policy,_,_,_=self.fixture(directory)
                rules={'version':1}
                if denied:
                    rules['mandatory']=['enforcement.watcher_start']
                PermissionStore(root).configure(rules,Principal('operator','operator'),expected_revision=0)
                context=dict(threadId=THREAD,sessionId=THREAD,callId='self-test',
                    **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW), patch(
                        'codex_wake.goal_watcher.watcher_status',return_value=dict(reason='watcher_not_installed')):
                    result=execute(root,policy,'set',dict(token_limit=100,time_limit_seconds=120),native_context=context)
                    self.assertEqual(result['engagement']['engaged'],not denied)
                    if denied:
                        self.assertEqual(result['watcher_setup']['reason'],'permission_deny')
                        self.assertFalse(result['watcher_setup']['start_attempted'])

    def test_configured_watcher_starts_without_claiming_readiness(self):
        from codex_wake.self_limits import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,_,_=self.fixture(directory)
            context=dict(threadId=THREAD,sessionId=THREAD,callId='self-test',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
            with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW), patch(
                    'codex_wake.goal_watcher.watcher_status', side_effect=[
                        dict(reason='watcher_not_running'),dict(reason='watcher_not_running'),dict(reason='watcher_running')]), patch(
                    'codex_wake.self_limits.subprocess.run',return_value=SimpleNamespace(returncode=0)) as runner:
                result=execute(root,policy,'set',dict(token_limit=100,time_limit_seconds=120),native_context=context)
                self.assertEqual(runner.call_args.args[0],['systemctl','--user','start','codex-wake-goal-limits.service'])
                self.assertTrue(result['watcher_setup']['start_attempted'])
                self.assertFalse(result['engagement']['engaged'])
                self.assertFalse(result['controller']['fresh'])

    def test_fresh_usage_has_no_goal_or_grant_requirement(self):
        from codex_wake.goal_usage import observe_session_usage
        with tempfile.TemporaryDirectory() as directory:
            _, _, log, _, _ = self.fixture(directory)
            rows=[json.loads(row) for row in log.read_text().splitlines()]
            log.write_text(''.join(json.dumps(row)+'\n' for row in rows if row.get('payload',{}).get('type')!='thread_goal_updated'))
            usage=observe_session_usage(log.parent.parent,THREAD)
            self.assertEqual(usage['state'],'qualified')
            self.assertEqual(usage['used_tokens'],40)

    @contextmanager
    def controllers(self):
        from codex_wake.self_limits import _CHILDREN
        try:
            yield
        finally:
            for pid, process in list(_CHILDREN.items()):
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
                del _CHILDREN[pid]


class SelfLimitsAdmissionTests(unittest.TestCase):
    fixture = fixtures.GoalSupervisionTests.fixture
    controller = fixtures.GoalSupervisionTests.controller

    def test_missing_clock_rejects_before_creating_native_goal_or_work(self):
        from codex_wake.self_limits import execute
        from test_goal_time import ANCHOR
        with tempfile.TemporaryDirectory() as directory:
            root,policy,log,_,_=self.fixture(directory)
            context=dict(threadId=THREAD,sessionId=THREAD,callId='rejected-self-set',
                **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='caller')})
            calls=[];goal=None
            def native(endpoint,executable,method,params,timeout):
                nonlocal goal
                calls.append(method)
                if method=='thread/goal/get':return dict(goal=goal)
                if method=='thread/read':return dict(thread=dict(id=THREAD,path=str(log),parentThreadId=None))
                if method=='thread/turns/list':return dict(data=[],nextCursor=None)
                if method=='thread/goal/set':
                    goal=dict(threadId=THREAD,createdAt=NOW,status=params['status'])
                    return dict(goal=goal)
                raise AssertionError(method)
            with patch('codex_wake.goal_supervision.native_request',side_effect=native), patch(
                    'codex_wake.lifecycle_budget.trusted_upper',side_effect=ValueError('admissible time unavailable')), patch(
                    'codex_wake.native_clock.snapshot',return_value=dict(utc=None,counter=ANCHOR,reason='authenticated_counter_only')):
                with self.assertRaisesRegex(ValueError,'admissible time unavailable'):
                    execute(root,policy,'set',dict(token_limit=100,time_limit_seconds=120),native_context=context)
            self.assertNotIn('thread/goal/set',calls)
            self.assertNotIn('turn/start',calls)
            self.assertNotIn('turn/steer',calls)
            self.assertIsNone(goal)

    def test_counter_only_session_enrolls_without_goal_and_stops_exact_owned_turn(self):
        from codex_wake.goal_supervision import enroll,poll
        from test_goal_time import ANCHOR
        from copy import deepcopy
        for fault,existing_goal in [('exhaustion',None),('continuity',None),('exhaustion',dict(threadId=THREAD,createdAt=NOW,status='paused',tokenBudget=50))]:
            with self.subTest(fault=fault,existing_goal=existing_goal),tempfile.TemporaryDirectory() as directory:
                root,policy,log,_,_=self.fixture(directory)
                template=json.loads(policy.read_text())['callers'][THREAD];template.pop('allocation_id')
                policy.write_text(json.dumps(dict(version=2,native_caller_binding=True,allocations={},self_enrollment=template)))
                context=dict(threadId=THREAD,sessionId=THREAD,callId='counter-self-set',
                    **{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='work')})
                calls=[];active=['work'];clock=dict(utc=None,counter=dict(ANCHOR),reason='authenticated_counter_only')
                def native(endpoint,executable,method,params,timeout):
                    calls.append(method)
                    if method=='thread/goal/get':return dict(goal=existing_goal)
                    if method=='thread/read':return dict(thread=dict(id=THREAD,path=str(log),parentThreadId=None))
                    if method=='thread/turns/list':return dict(data=[dict(id=t,status='inProgress') for t in active],nextCursor=None)
                    if method=='turn/interrupt':active.remove(params['turnId']);return {}
                    raise AssertionError(method)
                with fixture_clock(directory,clock) as synchronize, self.controller(root,interval=.05) as watcher,patch('codex_wake.goal_supervision.native_request',side_effect=native),patch(
                        'codex_wake.lifecycle_budget.trusted_upper',side_effect=ValueError('admissible time unavailable')):
                    anchor = dict(ANCHOR,counter=31000)
                    clock['counter'] = dict(anchor)
                    synchronize()
                    def at_seconds(seconds):
                        return dict(anchor,counter=anchor['counter']+seconds*anchor['frequency'])
                    if fault=='exhaustion' and existing_goal is None:
                        # Freeze publication while asserting a retained stale owner.
                        os.kill(watcher.pid,signal.SIGSTOP)
                        try:
                            path=root/'goal-supervision/controller.json';compatible=json.loads(path.read_text())
                            stale=deepcopy(compatible);stale.pop('time_bases');stale.pop('session_scope_without_goal')
                            stale['clock_observation']['counter']['counter']-=30*anchor['frequency']
                            for missing_heartbeat in (False,True):
                                if missing_heartbeat:path.unlink()
                                else:path.write_text(json.dumps(stale))
                                with self.assertRaisesRegex(ValueError,'existing watcher owner is stale'):
                                    enroll(root,policy,THREAD,100,120,native_context=context,session_scope=True,prepare_only=True)
                                self.assertEqual([p.name for p in (root/'goal-supervision').glob('*.json')],[] if missing_heartbeat else ['controller.json'])
                                self.assertFalse(list((root/'goal-supervision/allocations').glob('*.json')))
                                path.write_text(json.dumps(compatible))
                        finally:
                            os.kill(watcher.pid,signal.SIGCONT)
                    first=enroll(root,policy,THREAD,100,120,native_context=context,session_scope=True)
                    self.assertEqual(first['state'],'armed')
                    self.assertEqual(first['time_basis'],'authenticated_host_counter')
                    self.assertIsNone(first['deadline'])
                    self.assertEqual(first['lifetime_used_tokens'],40)
                    if fault=='exhaustion' and existing_goal is None:
                        # Interrupted publication: allocation committed but its
                        # session projection was not retained. Reuse its anchor.
                        for path in (root/'goal-supervision').glob('*.json'):
                            if json.loads(path.read_text()).get('thread_id')==THREAD:path.unlink()
                        clock['counter']=at_seconds(1)
                        synchronize()
                        recovered=enroll(root,policy,THREAD,100,120,native_context=context,session_scope=True)
                        self.assertEqual(recovered['clock_anchor'],first['clock_anchor'])
                        self.assertEqual(recovered['elapsed_limit_seconds'],120)
                        self.assertGreaterEqual(recovered['elapsed_upper_seconds'],1)
                        self.assertEqual(recovered['lifetime_used_tokens'],40)
                        first=recovered
                    clock['counter']=at_seconds(1)
                    synchronize()
                    tightened=enroll(root,policy,THREAD,90,110,native_context=context,session_scope=True)
                    self.assertEqual(tightened['clock_anchor'],first['clock_anchor'])
                    self.assertEqual(tightened['generation'],first['generation'])
                    self.assertEqual(tightened['lifetime_used_tokens'],40)
                    self.assertGreaterEqual(tightened['elapsed_upper_seconds'],1)
                    self.assertEqual(tightened['elapsed_limit_seconds'],110)
                    clock['counter']=dict(anchor,epoch='replacement') if fault=='continuity' else at_seconds(111)
                    synchronize()
                    stopped=poll(root)[0]
                    self.assertEqual(stopped['state'],'stopped')
                    self.assertTrue(stopped['stop_proof'])
                    if fault=='continuity':
                        self.assertEqual(stopped['reason'],'counter_continuity_lost')
                        self.assertFalse(stopped['first_stop']['clock_qualified'])
                        self.assertIsNone(stopped['first_stop']['observed_upper'])
                    if existing_goal is not None:self.assertEqual(existing_goal['status'],'paused')
                    self.assertEqual(active,[])
                    clock['counter']=at_seconds(2 if fault=='continuity' else 112)
                    synchronize()
                    retry=enroll(root,policy,THREAD,90,110,native_context=context,session_scope=True)
                    self.assertTrue(retry['stop_latched'])
                    self.assertEqual(retry['state'],'held')
                    self.assertEqual(retry['clock_anchor'],first['clock_anchor'])
                    self.assertEqual(retry['generation'],first['generation'])
                    self.assertNotIn('thread/goal/set',calls)
                    self.assertNotIn('turn/start',calls)
                    self.assertNotIn('turn/steer',calls)
                    if fault=='exhaustion' and existing_goal is None:
                        from codex_wake.goal_governance import change
                        from codex_wake.session_permissions import Principal
                        change(root,THREAD,enabled=False,principal=Principal(THREAD,'operator'))
                        for path in (root/'goal-supervision').glob('*.json'):
                            if json.loads(path.read_text()).get('thread_id')==THREAD:path.unlink()
                        prepared=enroll(root,policy,THREAD,90,110,native_context=context,session_scope=True,prepare_only=True)
                        self.assertEqual(prepared['state'],'inactive')
                        self.assertFalse(any(json.loads(path.read_text()).get('thread_id')==THREAD for path in (root/'goal-supervision').glob('*.json')))

    def test_existing_external_utc_origin_and_native_goal_are_preserved(self):
        from codex_wake.goal_supervision import enroll
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,_=self.fixture(directory)
            before=dict(native['goal'])
            with self.controller(root),patch('codex_wake.lifecycle_budget.trusted_upper',return_value=NOW+60):
                first=enroll(root,policy,THREAD,100,120,session_scope=True)
                self.assertEqual(first['deadline'],NOW+120)
                self.assertEqual(native['goal'],before)
                self.assertEqual(native['active'],['work'])
                self.assertFalse(any(method in ('thread/goal/set','turn/start','turn/steer','turn/interrupt') for method,_ in native['calls']))
