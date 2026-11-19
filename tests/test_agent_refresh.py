"""Refresh safety through the public lifecycle CLI."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import hashlib
import json
import tempfile
import os
import pty
import subprocess
import sys
import threading
from unittest.mock import patch
from websockets.sync.server import unix_serve
import unittest

from codex_wake.cli import run
from codex_wake.records import WakeError


class AgentRefreshTests(unittest.TestCase):
    def test_changed_checkpoint_is_rejected_before_runtime_or_journal_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / 'checkpoint.json'
            checkpoint.write_text('{"source_thread_id":"00000000-0000-7000-8000-000000000158"}')
            original = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            checkpoint.write_text('{"source_thread_id":"changed"}')
            profiles = root / 'profiles.json'
            profiles.write_text(json.dumps({'version': 1, 'profiles': {'worker': dict(
                cwd=tmp, app_server='unix:///missing.sock', codex_path='/bin/true',
                tmux_session='owned', timeout=1)}}))
            argv = ['--wake-root', tmp, 'sessions', 'refresh', '--profiles', str(profiles),
                    '--profile', 'worker', '--intent', 'refresh-1', '--thread-id',
                    '00000000-0000-7000-8000-000000000158', '--checkpoint', 'checkpoint.json',
                    '--checkpoint-sha256', original, '--resource', 'updated-skill',
                    '--expires-at', '2030-01-01T00:00:00Z', '--json']
            with redirect_stdout(StringIO()), self.assertRaisesRegex(WakeError, 'checkpoint hash'):
                run(argv)
            self.assertFalse((root / 'lifecycle').exists())

    def test_unsupported_resource_proof_is_rejected_before_journal_or_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            checkpoint=root/'checkpoint.json'
            checkpoint.write_text(json.dumps(dict(source_thread_id='00000000-0000-7000-8000-000000000158',
                objective='Finish fixture',authority='operator fixture',next_packet='Check resource',pending_obligations=[])))
            profiles=root/'profiles.json'
            profiles.write_text(json.dumps({'version':1,'profiles':{'worker':dict(cwd=tmp,
                app_server='unix:///missing.sock',codex_path='/bin/true',tmux_session='owned',timeout=1,
                resources={'unsupported':{'kind':'arbitrary-command','command':'unsafe'}})}}))
            argv=['--wake-root',tmp,'sessions','refresh','--profiles',str(profiles),'--profile','worker',
                '--intent','invalid-proof','--thread-id','00000000-0000-7000-8000-000000000158',
                '--checkpoint','checkpoint.json','--checkpoint-sha256',hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                '--resource','unsupported','--expires-at','2030-01-01T00:00:00Z','--json']
            definitions=[{'kind':'arbitrary-command','command':'unsafe'}, {'kind':'skill'},
                         {'kind':'mcp','read_only':True}]
            for definition in definitions:
                registry=json.loads(profiles.read_text())
                registry['profiles']['worker']['resources']['unsupported']=definition
                profiles.write_text(json.dumps(registry))
                with self.subTest(definition=definition),redirect_stdout(StringIO()),self.assertRaisesRegex(WakeError,'proof'):
                    run(argv)
                self.assertFalse((root/'lifecycle').exists())

    def test_configured_expired_original_session_preserves_client(self):
        self.refresh_scenario(draft=False, budget=True, session_limit=1000)

    def test_configured_refresh_twice_charges_same_goal_once(self):
        self.refresh_scenario(draft=False, budget=True, twice=True)

    def test_local_draft_preserves_old_generation_and_blocks_refresh(self):
        self.refresh_scenario(draft=True)

    def test_refresh_resumes_same_thread_and_proves_changed_skill_catalog(self):
        self.refresh_scenario(draft=False)

    def test_new_client_with_old_mcp_behavior_blocks_full_refresh(self):
        self.refresh_scenario(draft=False, stale_mcp=True)

    def test_lost_new_tab_response_reconciles_existing_refresh_without_replacement(self):
        self.refresh_scenario(draft=False, loss='new-window')

    def test_lost_stop_response_observes_old_exit_without_stopping_twice(self):
        self.refresh_scenario(draft=False, loss='kill-pane')

    def test_fixed_expiry_after_stop_prevents_replacement_without_reset(self):
        self.refresh_scenario(draft=False, expire_after_stop=True)

    def test_unapproved_probe_is_rejected_before_stopping_original_client(self):
        self.refresh_scenario(draft=False, stale_mcp=True, unapproved_probe=True)

    def test_refresh_preserves_native_goal_authority_with_monotonic_usage(self):
        self.refresh_scenario(draft=False, advancing_usage=True)

    def test_active_unknown_split_or_unaccounted_pending_work_preserves_client(self):
        for guard in ('active','unknown','split','pending'):
            with self.subTest(guard=guard):self.refresh_scenario(draft=False,recipient_guard=guard)

    def test_goal_budget_change_or_counter_reset_holds_without_mutating_goal(self):
        for change in ('budget','reset'):
            with self.subTest(change=change):self.refresh_scenario(draft=False,goal_change=change)

    def test_actual_updated_mcp_behavior_establishes_requested_readiness(self):
        self.refresh_scenario(draft=False,mcp_ready=True)

    def test_active_goal_is_paused_before_client_stop_and_restored_after_readiness(self):
        self.refresh_scenario(draft=False, original_status='active')

    def test_active_goal_stays_paused_when_replacement_mcp_is_stale(self):
        self.refresh_scenario(draft=False, original_status='active', stale_mcp=True)

    def test_lost_activation_readback_reconciles_without_activating_twice(self):
        self.refresh_scenario(draft=False, original_status='active', resume_readback_loss=True)

    def test_independent_client_refresh_waits_for_source_without_shared_reload(self):
        self.refresh_scenario(draft=False, original_status='active', client_idle=True)

    def test_themed_empty_composer_allows_single_client_refresh(self):
        self.refresh_scenario(draft=False,original_status='active',client_idle=True,managed_default=True,background=True)

    def test_managed_default_resume_verifies_actual_mcp_catalog(self):
        self.refresh_scenario(draft=False, original_status='active', client_idle=True, managed_default=True)

    def test_new_behavior_with_stale_mcp_catalog_cannot_resume_goal(self):
        self.refresh_scenario(draft=False, original_status='active', client_idle=True, managed_default=True,
                              mcp_ready=True,stale_catalog=True)

    def test_managed_default_refuses_missing_catalog_or_wrong_daemon_before_pause(self):
        for guard in ('missing-catalog','wrong-endpoint'):
            with self.subTest(guard=guard):
                self.refresh_scenario(draft=False,original_status='active',client_idle=True,
                                      managed_default=True,managed_guard=guard)

    def test_refresh_watcher_shutdown_fences_goal_and_pane_effects(self):
        for boundary in (3,5):
            with self.subTest(goal_read=boundary):
                self.refresh_scenario(draft=False, original_status='active', client_idle=True, client_idle_stop=boundary)

    def test_inactive_goals_are_not_activated_by_refresh(self):
        for status in ('blocked', 'complete', 'paused'):
            with self.subTest(status=status):
                self.refresh_scenario(draft=False, original_status=status)

    def test_rollback_reuses_original_conversation_without_goal_or_client_duplication(self):
        self.refresh_scenario(draft=False,stale_mcp=True,rollback_requested=True)

    def test_rollback_reattaches_after_proven_owned_tab_absence(self):
        self.refresh_scenario(draft=False,loss='new-window',rollback_absence=True)

    def test_handoff_preserves_unaccounted_pending_work_and_original_client(self):
        self.refresh_scenario(draft=False,recipient_guard='pending',operation='handoff')

    def test_handoff_preserves_unsubmitted_source_draft(self):
        self.refresh_scenario(draft=True,operation='handoff')

    def refresh_scenario(self, *, draft, stale_mcp=False, loss=None, expire_after_stop=False, unapproved_probe=False, advancing_usage=False, recipient_guard=None, goal_change=None, mcp_ready=False, rollback_requested=False, rollback_absence=False,operation='refresh', budget=False, session_limit=2000, twice=False, original_status='paused', resume_readback_loss=False, client_idle=False, client_idle_stop=0, managed_default=False, stale_catalog=False, managed_guard='', background=False):
        thread_id = '00000000-0000-7000-8000-000000000158'
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {'XDG_CONFIG_HOME': str(Path(tmp) / 'config')}):
            root = Path(tmp)
            client_script = root / 'codex'
            client_script.write_text(f'#!{sys.executable}\nimport ctypes,time\n'
                "ctypes.CDLL(None).prctl(15,b'codex',0,0,0)\n"
                "print('ready',flush=True)\ntime.sleep(60)\n")
            client_script.chmod(0o700)
            master, slave = pty.openpty()
            client = subprocess.Popen([str(client_script)], stdin=slave, stdout=subprocess.PIPE)
            self.assertEqual(client.stdout.readline(), b'ready\n')
            def fixture_clock():
                upper = 1893456001 if expire_after_stop and client.poll() is not None else 1001
                return {'utc': {'lower': upper - 1, 'upper': upper}}
            utc = patch('codex_wake.measurements.utc_bounds',
                        side_effect=lambda: tuple(fixture_clock()['utc'].values()))
            utc.start()
            self.addCleanup(utc.stop)
            tty = os.ttyname(slave)
            endpoint = root / 'native.sock'
            methods, effects = [], []
            original_pid = client.pid
            tab = {'name':'worker', 'source_busy':client_idle}
            lost_resume = []
            skill = root / 'skill.md'
            skill.write_text('---\nname: updated-skill\ndescription: Updated fixture\n---\nChanged instructions.\n')
            goal = dict(objective='Finish fixture', status=original_status, tokenBudget=1000,
                        tokensUsed=50, timeUsedSeconds=12, createdAt=100, updatedAt=100)
            if operation=='handoff' or budget:goal['threadId']=thread_id
            def handler(ws):
                for raw in ws:
                    request = json.loads(raw)
                    if 'id' not in request: continue
                    method = request['method']; methods.append(method)
                    if method == 'thread/loaded/list':
                        value = dict(data=[thread_id,*(['00000000-0000-7000-8000-000000000159'] if client_idle else [])], nextCursor=None)
                    elif method == 'thread/read':
                        requested_thread=request['params']['threadId']
                        peer=requested_thread!=thread_id
                        turns=[]
                        if operation=='handoff':turns=[dict(id='writer-turn',status='completed',items=[
                            dict(id='writer-command',type='commandExecution',status='completed',exitCode=0,
                                cwd=tmp,aggregatedOutput='checkpoint:'+thread_id+':'+hashlib.sha256(checkpoint.read_bytes()).hexdigest())])]
                        value = dict(thread=dict(id=requested_thread, name='busy-peer' if peer else 'owned-worker', cwd=tmp,
                            status={'type':'active' if peer or tab['source_busy'] else recipient_guard if recipient_guard in ('active','unknown') else 'idle'}, canAcceptDirectInput=True, turns=turns))
                    elif method == 'thread/goal/get':
                        if client_idle_stop and methods.count(method)==client_idle_stop:
                            from codex_wake import shared_refresh
                            shared_refresh._stopping=True
                            tab['effects_at_shutdown']=len(effects)
                        if resume_readback_loss and methods.count('thread/goal/set')==2 and not lost_resume:
                            lost_resume.append(True);ws.close();break
                        observed=dict(goal)
                        if advancing_usage and methods.count(method)>1:
                            observed.update(tokensUsed=51,timeUsedSeconds=13,updatedAt=101)
                        if goal_change and methods.count(method)>1:
                            observed.update(tokenBudget=2000) if goal_change == 'budget' else observed.update(tokensUsed=0)
                        value={'goal':observed}
                    elif method == 'mcpServer/tool/call':
                        value = {'content':[{'type':'text','text':'new-version' if mcp_ready else 'old-version'}],'isError':False}
                    elif method == 'mcpServerStatus/list':
                        value=dict(data=[dict(name='fixture',serverInfo=dict(version='v1' if stale_catalog else 'v2'),
                            tools={'version':dict(inputSchema=dict(properties={}))})])
                    elif method == 'thread/goal/set':
                        self.assertEqual(request['params']['threadId'],thread_id)
                        goal['status'] = request['params']['status']
                        value = {'goal':dict(goal)}
                    elif method == 'skills/list': value = {'data': [dict(cwd=tmp, errors=[], skills=[
                        dict(name='updated-skill',path=str(skill),description='Updated fixture',enabled=True)])]}
                    else: value = {}
                    ws.send(json.dumps(dict(id=request['id'],result=value)))
            def command(argv, **kwargs):
                nonlocal client
                if 'list-panes' in argv and tab.get('absent'):
                    return subprocess.CompletedProcess(argv,0,'','')
                if 'list-panes' in argv:
                    value = (('%158\n%159' if recipient_guard == 'split' else '%158') if '-a' not in argv else '\t'.join([
                        '$1','owned','@158','1',tab['name'],'%158','0','owned-worker',tmp,tty]))
                elif 'capture-pane' in argv:
                    text = 'UNSUBMITTED_DRAFT_158' if draft else '\x1b[2mAsk Codex to do anything\x1b[0m'
                    value = '\n\n\x1b[1m›\x1b[0m ' + text + '\n'
                    if background:value=value.replace('\x1b[0m','\x1b[0m\x1b[48;2;41;41;41m')
                elif 'display-message' in argv: value = '23,2' if draft else '2,2'
                elif 'kill-pane' in argv:
                    if original_status == 'active':
                        self.assertEqual(goal['status'], 'paused')
                    effects.append(argv); client.terminate();client.wait(timeout=2);client.stdout.close();value=''
                    if loss == 'kill-pane':raise subprocess.TimeoutExpired(argv,1)
                elif 'new-window' in argv:
                    effects.append(argv)
                    if managed_default:self.assertNotIn('--remote',argv[-1])
                    tab['name']=argv[argv.index('-n')+1];tab['absent']=False
                    client=subprocess.Popen(['sh','-c','exec '+argv[-1]],stdin=slave,stdout=subprocess.PIPE)
                    self.assertEqual(client.stdout.readline(),b'ready\n');value='@158\t%158'
                    if loss == 'new-window' and sum('new-window' in x for x in effects)==1:raise subprocess.TimeoutExpired(argv,1)
                else:
                    effects.append(argv); value = ''
                return subprocess.CompletedProcess(argv,0,value,'')
            checkpoint = root / 'checkpoint.json'
            checkpoint.write_text(json.dumps(dict(source_thread_id=thread_id, objective='Finish fixture',
                authority='operator fixture', next_packet='Check skill', pending_obligations=[])))
            profiles = root / 'profiles.json'
            profiles.write_text(json.dumps({'version':1,'profiles':{'worker':dict(cwd=tmp,
                app_server='unix://'+str(endpoint),codex_path=str(client_script),tmux_session='owned',
                timeout=1,resources={'updated-skill':dict(kind='skill',path=str(skill),
                    description='Updated fixture',sha256=hashlib.sha256(skill.read_bytes()).hexdigest())})}}))
            if original_status == 'active':
                registry=json.loads(profiles.read_text())
                registry['profiles']['worker']['goal_supervision']=dict(root=tmp,policy=str(profiles),allocation_id='fixture')
                profiles.write_text(json.dumps(registry))
            if client_idle:
                registry=json.loads(profiles.read_text())
                registry['profiles']['worker'].update(refresh_mode='client_idle',scope_approval='operator approved exact client')
                registry['callers']={thread_id:['worker']}
                profiles.write_text(json.dumps(registry));profiles.chmod(0o600)
            if managed_default:
                registry=json.loads(profiles.read_text());profile=registry['profiles']['worker']
                profile.update(client_connection='managed_default',codex_home=tmp)
                profile['resources']['catalog']=dict(kind='mcp_catalog',server='fixture',version='v2',tools={'version':[]})
                profiles.write_text(json.dumps(registry))
            if budget:
                registry=json.loads(profiles.read_text())
                registry['continuations']={thread_id:dict(objective='Finish fixture',approval='operator fixture',
                    tokens_before_source=20,started_at='1970-01-01T00:00:00Z')}
                selection=dict(name='fixture',path=str(skill))
                registry['lifecycle_defaults']=dict(handoff_writer=selection,preflight_reviewer=selection,
                    session_token_limit=1000,session_time_limit_seconds=session_limit,
                    objective_token_limit=2000,objective_time_limit_seconds=4000,max_correction_cycles=1)
                profiles.write_text(json.dumps(registry))
            if stale_mcp or mcp_ready:
                registry=json.loads(profiles.read_text())
                registry['profiles']['worker']['resources']['updated-skill']=dict(kind='mcp',
                    server='fixture',tool='version',arguments={},read_only=not unapproved_probe,
                    expected_content=[{'type':'text','text':'new-version'}])
                profiles.write_text(json.dumps(registry))
            if recipient_guard == 'pending':
                (root/'pending').mkdir()
                (root/'pending/unaccounted.json').write_text('{"target":null}')
            if operation=='handoff':
                registry=json.loads(profiles.read_text())
                registry['continuations']={thread_id:dict(objective='Finish fixture',approval='operator fixture',
                    token_cap=1000,time_cap_seconds=2000,tokens_before_source=0,seconds_before_source=0,
                    started_at='1970-01-01T00:00:00Z')}
                profiles.write_text(json.dumps(registry))
                body=json.loads(checkpoint.read_text());policy=registry['continuations'][thread_id]
                body.update(repo=tmp,worktree=tmp,commit='a'*40,dirty_work='isolated fixture',
                    acceptance_remaining=['bounded handoff'],evidence=['source writer fixture'],
                    pending_wakes=[],pending_messages=[],claim_holders=[],reply_route='original thread',
                    hard_stops=['fixed caps and expiry'],expires_at='2030-01-01T00:00:00Z',
                    resources={k:policy[k] for k in ('token_cap','time_cap_seconds','tokens_before_source','seconds_before_source','started_at')})
                checkpoint.write_text(json.dumps(body))
            argv = ['--wake-root',tmp,'sessions','refresh','--profiles',str(profiles),
                '--profile','worker','--intent','refresh-1','--thread-id',thread_id,
                '--checkpoint','checkpoint.json','--checkpoint-sha256',
                hashlib.sha256(checkpoint.read_bytes()).hexdigest(),'--resource','updated-skill',
                '--expires-at','2030-01-01T00:00:00Z','--json']
            if operation=='handoff':
                argv[argv.index('refresh')]='handoff';index=argv.index('--resource');del argv[index:index+2]
                argv+=['--mode','new-tab']
            if client_idle:argv+=['--caller-thread-id',thread_id]
            if managed_default and managed_guard!='missing-catalog':argv+=['--resource','catalog']
            try:
                with unix_serve(handler,str(endpoint)) as server:
                    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                    try:
                        with patch('codex_wake.shared_app_server.locate_shared_endpoint',return_value='unix:///wrong.sock' if managed_guard=='wrong-endpoint' else 'unix://'+str(endpoint)),patch('codex_wake.goal_supervision._heartbeat',return_value=dict(fresh=True)),patch('codex_wake.goal_supervision.show',return_value=dict(state='armed',stop_latched=False,
                                controller=dict(fresh=True),accounting=dict(state='qualified'),used_tokens=50,
                                token_limit=1000,deadline=10000)), patch('subprocess.run',side_effect=command), patch(
                                'codex_wake.native_clock.snapshot',side_effect=fixture_clock):
                            if unapproved_probe:
                                with redirect_stdout(StringIO()),self.assertRaisesRegex(WakeError,'read-only'):
                                    run(argv)
                                self.assertEqual(effects,[])
                                self.assertIsNone(client.poll())
                                self.assertFalse((root/'lifecycle').exists())
                                return
                            if loss:
                                first=StringIO()
                                with redirect_stdout(first):self.assertEqual(run(argv),5)
                                held=json.loads(first.getvalue())
                                self.assertEqual(held['state'],'uncertain')
                                self.assertEqual(held['uncertain_effect'],'tmux/'+loss)
                                if rollback_absence:
                                    client.terminate();client.wait(timeout=2);client.stdout.close();tab['absent']=True
                                    restored=StringIO()
                                    with redirect_stdout(restored):self.assertEqual(run([*argv,'--rollback']),0,restored.getvalue())
                                    receipt=json.loads(restored.getvalue())
                                    self.assertEqual(receipt['rollback']['state'],'completed')
                                    self.assertEqual(receipt['rollback']['thread_id'],thread_id)
                                    self.assertEqual(sum('new-window' in x for x in effects),2)
                                    self.assertEqual(sum('kill-pane' in x for x in effects),1)
                                    self.assertIsNone(client.poll())
                                    return
                            if resume_readback_loss:
                                uncertain=StringIO()
                                with redirect_stdout(uncertain):self.assertEqual(run(argv),5)
                                held=json.loads(uncertain.getvalue())
                                self.assertEqual(held['state'],'uncertain')
                                self.assertEqual(held['uncertain_effect'],'native/goal_resume')
                                self.assertEqual(goal['status'],'active')
                            if client_idle:
                                from codex_wake.shared_refresh import poll
                                queued=StringIO()
                                if managed_guard:
                                    with redirect_stdout(queued):self.assertEqual(run(argv),2)
                                    self.assertIn('managed',json.loads(queued.getvalue())['error']['message'])
                                    self.assertEqual(effects,[])
                                    self.assertNotIn('thread/goal/set',methods)
                                    self.assertEqual(goal['status'],'active')
                                    return
                                with redirect_stdout(queued):self.assertEqual(run(argv),0)
                                self.assertEqual(json.loads(queued.getvalue())['state'],'queued')
                                self.assertEqual(effects,[])
                                self.assertEqual(goal['status'],'paused')
                                poll(root)
                                self.assertEqual(effects,[])
                                tab['source_busy']=False
                                poll(root)
                                if client_idle_stop:
                                    from codex_wake import shared_refresh
                                    shared_refresh._stopping=False
                                    self.assertEqual(len(effects),tab['effects_at_shutdown'])
                                    self.assertIsNone(client.poll())
                                    self.assertEqual(methods.count('thread/goal/set'),1)
                                    return
                            output=StringIO()
                            with redirect_stdout(output): self.assertEqual(run(argv),5 if draft or stale_mcp or stale_catalog or expire_after_stop or recipient_guard or goal_change or (budget and session_limit<=1001) else 0,output.getvalue())
                            receipt=json.loads(output.getvalue())
                            if budget and session_limit<=1001:
                                self.assertEqual(receipt['state'],'blocked')
                                self.assertEqual(receipt['reason'],'objective_budget_or_accounting_stop')
                                self.assertEqual(effects,[])
                                self.assertIsNone(client.poll())
                                self.assertEqual(client.pid,original_pid)
                                self.assertEqual(receipt['assignment_deadline'],1000)
                            elif recipient_guard:
                                self.assertEqual(receipt['state'],'blocked')
                                if operation=='handoff':self.assertEqual(receipt['reason'],'pending_thread_work')
                                self.assertEqual(effects,[])
                                self.assertIsNone(client.poll())
                                self.assertEqual(client.pid,original_pid)
                            elif expire_after_stop:
                                self.assertEqual(receipt['state'],'expired')
                                self.assertEqual(sum('kill-pane' in x for x in effects),1)
                                self.assertFalse(any('new-window' in x for x in effects))
                                count=len(effects)
                                with redirect_stdout(StringIO()):self.assertEqual(run(argv),5)
                                self.assertEqual(len(effects),count)
                            elif draft:
                                self.assertEqual(receipt['state'],'blocked')
                                self.assertEqual(receipt['reason'],'local_composer_not_proven_empty')
                                self.assertEqual(effects,[])
                                self.assertIsNone(client.poll())
                            elif goal_change:
                                self.assertEqual(receipt['state'],'blocked')
                                self.assertEqual(receipt['reason'],'goal_changed_during_refresh')
                                self.assertEqual(receipt['goal_before'],dict(goal,status='paused') if original_status=='active' else goal)
                            elif stale_mcp or stale_catalog:
                                self.assertEqual(receipt['state'],'blocked')
                                self.assertNotEqual(client.pid,original_pid)
                                if stale_catalog:self.assertEqual(receipt['resources']['catalog']['state'],'blocked')
                                else:self.assertEqual(receipt['resources']['updated-skill']['observed_content'],
                                    [{'type':'text','text':'old-version'}])
                                self.assertEqual(methods.count('mcpServer/tool/call'),1)
                                self.assertEqual(receipt['goal_after'],goal)
                                if rollback_requested:
                                    count=len(effects);rolled=StringIO()
                                    with redirect_stdout(rolled):self.assertEqual(run([*argv,'--rollback']),0)
                                    restored=json.loads(rolled.getvalue())
                                    self.assertEqual(restored['rollback']['state'],'completed')
                                    self.assertEqual(restored['rollback']['thread_id'],thread_id)
                                    self.assertEqual(len(effects),count)
                                    self.assertEqual(restored['rollback']['goal'],goal)
                            else:
                                self.assertEqual(receipt['state'],'completed')
                                self.assertEqual(sum('new-window' in x for x in effects),1)
                                self.assertEqual(sum('kill-pane' in x for x in effects),1)
                                self.assertEqual(receipt['thread_id'],thread_id)
                                self.assertNotEqual(client.pid,original_pid)
                                self.assertEqual(receipt['goal_before'],dict(goal,status='paused') if original_status=='active' else goal)
                                self.assertEqual(receipt['goal_after'],dict(goal,tokensUsed=51,timeUsedSeconds=13,updatedAt=101) if advancing_usage else goal)
                                self.assertEqual(receipt['resources']['updated-skill']['state'],'ready')
                                if mcp_ready:self.assertEqual(methods.count('mcpServer/tool/call'),1)
                                count=len(effects)
                                with redirect_stdout(StringIO()):self.assertEqual(run(argv),0)
                                self.assertEqual(len(effects),count)
                                if budget:
                                    self.assertEqual(receipt['objective_budget']['tokens_used'],70)
                                    self.assertEqual(receipt['assignment_deadline'],2000)
                                    if twice:
                                        argv[argv.index('--intent')+1]='refresh-2'
                                        again=StringIO()
                                        with redirect_stdout(again):self.assertEqual(run(argv),0,again.getvalue())
                                        second=json.loads(again.getvalue())
                                        self.assertEqual(second['assignment_deadline'],receipt['assignment_deadline'])
                                        self.assertEqual(second['objective_budget']['tokens_used'],70)
                                        self.assertEqual(len(second['objective_budget']['actors']),1)
                                        self.assertEqual(sum('new-window' in x for x in effects),2)
                                        self.assertEqual(sum('kill-pane' in x for x in effects),2)
                                else:
                                    self.assertNotIn('objective_budget',receipt)
                            self.assertFalse(any(x in methods for x in ('thread/start','turn/start')))
                            self.assertNotIn('config/mcpServer/reload',methods)
                            self.assertEqual(methods.count('thread/goal/set'),
                                (1 if stale_mcp or stale_catalog else 2) if original_status=='active' else 0)
                    finally:server.shutdown();worker.join(timeout=2)
            finally:
                if client_idle_stop:
                    from codex_wake import shared_refresh
                    shared_refresh._stopping=False
                client.terminate();client.wait(timeout=2);client.stdout.close()
                os.close(master);os.close(slave)
