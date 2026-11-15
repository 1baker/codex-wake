"""Owned successor/preflight integration through CLI, native socket and real PTYs."""
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import pty
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from websockets.sync.server import unix_serve

from codex_wake.cli import run


class HandoffPreflightTests(unittest.TestCase):
    def setUp(self):
        isolated = tempfile.TemporaryDirectory()
        self.addCleanup(isolated.cleanup)
        environment = patch.dict(os.environ, {
            'XDG_CONFIG_HOME': str(Path(isolated.name) / 'config'),
            'XDG_STATE_HOME': str(Path(isolated.name) / 'state'),
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_common_policy_trigger_and_task_approval_reach_verified_successor(self):
        self.scenario(task_brief=True,common_permissions=True)

    def test_pinned_task_brief_reaches_successor_preflight(self):
        self.scenario(task_brief=True)

    def test_non_github_review_accepts_evidence_without_changing_native_guards(self):
        self.scenario(workflow='local-review')

    def test_preflight_references_exact_instruction_files_and_requires_native_read(self):
        self.scenario(reference_contract=True)

    def test_accept_assertion_cannot_replace_criterion_evidence(self):
        for defect in ('scope_drift', 'test_count_only', 'changed_evidence', 'unknown_criterion'):
            with self.subTest(defect=defect):
                self.scenario(bad_review=defect)

    def test_successor_goal_is_bounded_by_session_and_shared_objective_allowance(self):
        self.scenario(session_cap=100)

    def test_replacement_context_preserves_existing_session_deadline_through_goal_alias(self):
        self.scenario(inherited_deadline=1020)

    def test_defaults_cannot_silently_rewrite_an_existing_assignment(self):
        self.scenario(changed_defaults=True)

    def test_missing_writer_instruction_read_blocks_before_successor_admission(self):
        self.scenario(unread_writer=True)

    def test_bounded_correction_runs_owned_packet_then_accepts_actual_repair(self):
        self.scenario(correction='accept')

    def test_correction_cannot_widen_host_approved_scope(self):
        self.scenario(correction='drift')

    def test_repeated_rejection_stops_after_two_owned_correction_cycles(self):
        self.scenario(correction='reject')

    def test_ready_runtime_with_unsupported_completion_cannot_prepare_a_goal(self):
        self.scenario(work_verdict='correct')

    def test_one_successor_runs_preflight_without_two_active_goals_or_duplicate_assignment(self):
        self.scenario(inventory_budget_miss=True)

    def test_preflight_allowance_must_fit_before_creating_a_successor(self):
        self.scenario(source_budget=60)

    def test_lost_goal_creation_response_never_repeats_unobserved_creation(self):
        self.scenario(lost_goal=True)

    def test_usage_spent_while_pausing_is_deducted_before_successor_preparation(self):
        self.scenario(pause_used=53)

    def test_preflight_crossing_original_deadline_cannot_prepare_a_goal(self):
        self.scenario(expire_preflight=True)

    def test_daemon_expires_prepared_continuation_at_original_deadline(self):
        self.scenario(monitor_expiry=True)

    def test_continuous_monitor_activates_one_owner_with_remaining_allowance(self):
        self.scenario(activate=True)

    def test_monitor_charges_cached_rollout_tokens_instead_of_discounted_goal_counter(self):
        self.scenario(activate=True,session_cap=100,cached_goal=True)

    def test_unknown_clock_still_fences_active_owned_work(self):
        self.scenario(activate=True,enforce_deadline='unknown')

    def test_monitor_pauses_and_interrupts_owned_turn_before_original_deadline(self):
        self.scenario(activate=True,enforce_deadline=True)

    def test_lost_deadline_pause_response_reconciles_without_repeating_pause(self):
        self.scenario(activate=True,enforce_deadline=True,lost_pause=True)

    def test_lost_activation_response_reconciles_original_goal_without_reactivation(self):
        self.scenario(activate=True,lost_activate=True)

    def test_late_source_accounting_fences_active_successor(self):
        self.scenario(activate=True,late_source=True)

    def test_late_source_time_fences_active_successor(self):
        self.scenario(activate=True,late_source='time')

    def test_late_source_accounting_cannot_activate_prepared_successor(self):
        self.scenario(activate=True,before_source=True)

    def test_monitor_shutdown_pauses_owned_goal_and_preserves_allowance(self):
        self.scenario(activate=True,shutdown=True)

    def test_same_intent_cli_readback_preserves_active_monitor_ownership(self):
        self.scenario(activate=True,readback=True)

    def test_another_live_monitor_generation_cannot_be_taken_over_or_stopped(self):
        self.scenario(activate=True,foreign_monitor=True)

    def test_explicit_rollback_reuses_source_and_deducts_successor_spending_once(self):
        self.scenario(rollback=True)

    def test_lost_rollback_budget_response_reconciles_without_second_debit(self):
        self.scenario(rollback=True,lost_rollback=True)

    def test_rollback_cannot_debit_source_after_another_transition_takes_ownership(self):
        self.scenario(rollback=True,owner_conflict=True)

    def test_missing_first_usage_snapshot_observes_existing_turn_without_new_admission(self):
        self.scenario(pending_usage=True)

    def test_running_preflight_over_allowance_interrupts_exact_assignment_once(self):
        self.scenario(running_overspend=True)

    def test_lost_preflight_interrupt_response_reconciles_without_reinterrupt(self):
        self.scenario(running_overspend=True,lost_preflight_interrupt=True)

    def test_same_tab_uses_fresh_identity_in_original_owned_pane_once(self):
        self.scenario(same_tab=True)

    def test_same_tab_observes_owned_successor_after_detached_source_unloads(self):
        self.scenario(same_tab=True,unloaded_source=True)

    def test_unloaded_same_tab_source_with_active_native_turn_still_holds(self):
        self.scenario(same_tab=True,unloaded_source=True,unloaded_active=True)

    def test_same_tab_lost_respawn_response_reconciles_new_generation_without_respawn(self):
        self.scenario(same_tab=True,lost_respawn=True)

    def test_same_tab_stale_title_cannot_replace_pinned_source_generation(self):
        self.scenario(same_tab=True,stale_title=True)

    def test_rollback_pauses_owned_active_successor_before_restoring_source(self):
        self.scenario(rollback=True,active_rollback=True)

    def test_lost_active_rollback_pause_response_reconciles_without_repause(self):
        self.scenario(rollback=True,active_rollback=True,lost_rollback_pause=True)

    def test_rollback_restores_missing_source_in_the_owned_successor_pane(self):
        self.scenario(rollback=True,missing_source=True)

    def test_same_tab_rollback_restores_original_paused_conversation(self):
        self.scenario(same_tab=True,rollback=True)

    def test_same_tab_rollback_leaves_resumed_goal_paused_before_composer_check(self):
        self.scenario(same_tab=True,rollback=True,resume_modal=True)

    def test_lost_leave_paused_response_observes_composer_without_second_key(self):
        self.scenario(same_tab=True,rollback=True,resume_modal=True,lost_modal=True)

    def test_restored_unknown_dialog_never_receives_an_automatic_key(self):
        self.scenario(same_tab=True,rollback=True,resume_modal="other")

    def test_lost_source_restore_response_observes_existing_generation_without_respawn(self):
        self.scenario(rollback=True,missing_source=True,lost_restore=True)

    def test_cached_rollback_budget_charges_late_receiver_usage_once(self):
        self.scenario(rollback=True,lost_rollback=True,late_usage=True)

    def scenario(self,source_budget=1000,lost_goal=False,pause_used=None,expire_preflight=False,monitor_expiry=False,activate=False,enforce_deadline=False,lost_pause=False,lost_activate=False,shutdown=False,readback=False,foreign_monitor=False,rollback=False,lost_rollback=False,owner_conflict=False,running_overspend=False,lost_preflight_interrupt=False,same_tab=False,lost_respawn=False,stale_title=False,active_rollback=False,lost_rollback_pause=False,missing_source=False,lost_restore=False,late_usage=False,late_source=False,before_source=False,work_verdict=None,workflow='github-handoff',bad_review=None,unread_writer=False,changed_defaults=False,session_cap=1000,correction=None,pending_usage=False,unloaded_source=False,unloaded_active=False,inherited_deadline=None,cached_goal=False,reference_contract=False,resume_modal=False,lost_modal=False,task_brief=False,common_permissions=False,inventory_budget_miss=False):
        source='00000000-0000-7000-8000-000000000159'
        target='00000000-0000-7000-8000-000000000160'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);home=root/'home';(home/'sessions').mkdir(parents=True)
            (home/'sessions'/(source+'.jsonl')).write_text(json.dumps(dict(type='event_msg',payload=dict(type='token_count',info={'total_token_usage':{'total_tokens':50}})))+'\n')
            codex=root/'codex';codex.write_text(f'#!{sys.executable}\nimport ctypes,time\n'
                "ctypes.CDLL(None).prctl(15,b'codex',0,0,0)\nprint('ready',flush=True)\ntime.sleep(60)\n")
            codex.chmod(0o700)
            clients=[];fds=[];panes={};methods=[];threads={source:{'name':'original-worker','turns':[]}}
            goals={source:dict(threadId=source,objective='Finish fixture',status='active' if pause_used is not None else 'paused',
                tokenBudget=source_budget,tokensUsed=50,timeUsedSeconds=12,createdAt=100,updatedAt=100)}
            queue={};goal_sets=[];interrupts=[];respawns=[]
            external_run=subprocess.run
            visibility={'show_goal':not lost_goal,'stale_title':stale_title}
            clock={'utc':{'lower':1000,'upper':1001}}
            def launch(command,pane,name,thread):
                master,slave=pty.openpty();fds.extend([master,slave])
                client=subprocess.Popen(command,stdin=slave,stdout=subprocess.PIPE)
                clients.append(client);self.assertEqual(client.stdout.readline(),b'ready\n')
                panes[pane]=dict(pid=client.pid,tty=os.ttyname(slave),name=name,thread=thread)
            launch([str(codex),'resume',source],'%159','original-worker',source)
            checkpoint=root/'checkpoint.json';checkpoint.write_text(json.dumps(dict(source_thread_id=source,
                objective='Finish fixture',authority='operator fixture',next_packet='Run selected preflight',pending_obligations=[])))
            digest=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            threads[source]['turns']=[dict(id='writer-turn',status='completed',items=[dict(id='writer',
                type='commandExecution',status='completed',exitCode=0,cwd=tmp,
                aggregatedOutput='checkpoint:'+source+':'+digest)])]
            helper=root/'preflight.py'
            helper.write_text("""import os,sys,json,pathlib,hashlib
source,nonce,digest=sys.argv[1:]
p=pathlib.Path('checkpoint.json')
assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
target=os.environ['CODEX_THREAD_ID']
pathlib.Path('preflight.json').write_text(json.dumps(dict(version=1,state='passed',source_thread_id=source,successor_thread_id=target,checkpoint_sha256=digest,intent_fingerprint=nonce,selected_workflow='github-handoff',checks={'fixture':{'state':'passed'}})))
print('preflight:'+target+':'+nonce+':'+digest)
""")
            endpoint=root/'native.sock';profiles=root/'profiles.json'
            profile=dict(cwd=tmp,codex_home=str(home),app_server='unix://'+str(endpoint),
                codex_path=str(codex),tmux_session='owned',timeout=1)
            policy=dict(objective='Finish fixture',approval='operator fixture',token_cap=1000,
                time_cap_seconds=2000,tokens_before_source=0,seconds_before_source=0,
                started_at='1970-01-01T00:00:00Z',preflight=dict(script=str(helper),
                    sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),receipt='preflight.json',
                    workflow='github-handoff',required_checks=['fixture'],token_allowance=100))
            body=json.loads(checkpoint.read_text())
            body.update(repo=tmp,worktree=tmp,commit='a'*40,dirty_work='fixture; no Git changes',
                acceptance_remaining=['bounded continuation'],evidence=['native fixture writer'],
                pending_wakes=[],pending_messages=[],claim_holders=[],reply_route='original thread',
                hard_stops=['original expiry and caps'],expires_at='2030-01-01T00:00:00Z',
                resources={k:policy[k] for k in ('token_cap','time_cap_seconds','tokens_before_source','seconds_before_source','started_at')})
            if task_brief:
                from codex_wake.task_briefs import BriefAuthority, TaskBriefStore
                from codex_wake.lifecycle_budget import objective_identity
                briefs = TaskBriefStore(root)
                authority = BriefAuthority('operator:fixture', 'operator')
                brief_content = dict(objective=policy['objective'], phase='implementation',
                    non_goals=['Never deploy'], acceptance=['bounded continuation'], context=[],
                    workspace=tmp, allocation_ref=objective_identity(policy), permission_ref='worker')
                briefs.propose('fixture-task', brief_content, authority=authority)
                briefs.approve('fixture-task', 1, authority=authority)
                briefs.admit('fixture-task', 'original-instruction', authority=authority)
                body['task_brief'] = briefs.assignment_pin('fixture-task', 'original-instruction')
                briefs.propose('fixture-task', dict(brief_content, non_goals=['Future instructions only']), authority=authority)
                briefs.approve('fixture-task', 2, authority=authority)
            checkpoint.write_text(json.dumps(body));digest=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            threads[source]['turns'][0]['items'][0]['aggregatedOutput']='checkpoint:'+source+':'+digest
            if activate:policy['activation']=dict(approved=True,max_poll_seconds=1,deadline_margin_seconds=10)
            policy['preflight']['workflow']=workflow
            writer=root/'writer.md';writer.write_text('Write the complete evidence checkpoint.')
            reviewer=root/'reviewer.md';reviewer.write_text('Review progress against actual evidence.')
            if not unread_writer:
                read=external_run(['cat',str(writer)],capture_output=True,text=True,check=True)
                threads[source]['turns'][0]['items'].append(dict(id='writer-instructions',
                    type='commandExecution',status='completed',exitCode=read.returncode,cwd=tmp,
                    command=shlex.join(['cat',str(writer)]),aggregatedOutput=read.stdout))
            policy['acceptance_criteria']=['bounded continuation']
            if correction:
                policy['correction_scope']=['repair.txt']
                (root/'repair.txt').write_text('broken')
            defaults=dict(handoff_writer=dict(name='local-writer',path=str(writer)),
                preflight_reviewer=dict(name=workflow,path=str(reviewer)),session_token_limit=session_cap,
                session_time_limit_seconds=1000,objective_token_limit=1000,
                objective_time_limit_seconds=2000,max_correction_cycles=2)
            if common_permissions:policy['handoff_triggers']=['context_limit']
            profiles.write_text(json.dumps(dict(version=1,profiles={'worker':profile},
                lifecycle_defaults=defaults,continuations={source:policy})))
            if common_permissions:
                profiles.chmod(0o600)
                from codex_wake.session_permissions import PermissionStore,Principal
                PermissionStore(root).configure({'version':1,'global':{'actions':{'handoff.self':'approval_required'}},
                    'approvals':[dict(id='task-approval',action='handoff.self',subject=source,scope='task',
                        task_id='fixture-task',expires_at='2030-01-01T00:00:00Z',issuer='operator')]},
                    Principal('op','operator'),expected_revision=0)
                from codex_wake.a2a_bus import BusStore
                permission_bus,permission_capability=BusStore.configure(root/'permission-bus')
            if inherited_deadline:
                from codex_wake.lifecycle_configuration import effective_configuration
                from codex_wake.lifecycle_budget import objective_identity
                from codex_wake.objective_ledger import ObjectiveLedger
                cfg=effective_configuration(json.loads(profiles.read_text()),source,'worker')
                cfg={k:v for k,v in cfg.items() if k not in ('source_thread_id','profile')}
                ledger=ObjectiveLedger(root,objective_identity(policy))
                ledger.configure(cfg,policy['approval'],policy['tokens_before_source'],now=1000)
                ledger.reserve('original-session',1000,inherited_deadline-1000,now=1000)
                ledger.bind_goal('goal:'+source+':'+str(goals[source]['createdAt']),'original-session',0,now=1000)
            def handler(ws):
                for raw in ws:
                    req=json.loads(raw)
                    if 'id' not in req:continue
                    method=req['method'];params=req.get('params',{});methods.append(method)
                    tid=params.get('threadId',target)
                    if method=='initialize':value={'userAgent':'fixture'}
                    elif method=='thread/loaded/list':value={'data':[tid for tid in threads
                        if not (unloaded_source and tid==source and respawns)],'nextCursor':None}
                    elif method=='thread/start':threads[target]={'name':'','turns':[]};value={'thread':{'id':target}}
                    elif method=='thread/name/set':threads[tid]['name']=params['name'];value={}
                    elif method=='thread/read':
                        value={'thread':dict(id=tid,name=threads[tid]['name'],cwd=tmp,status={'type':'idle'},
                            canAcceptDirectInput=True,turns=threads[tid]['turns'],path=str(home/'sessions'/ (tid+'.jsonl')))}
                        if unloaded_active and tid==source and respawns:
                            value['thread']['turns']=value['thread']['turns']+[dict(id='foreign-source-turn',status='inProgress')]
                    elif method=='thread/goal/get':value={'goal':None if tid==target and not visibility['show_goal'] else goals.get(tid)}
                    elif method=='thread/goal/set':
                        goal_sets.append(params)
                        if tid==source:
                            goals[tid].update(status='paused',updatedAt=1002)
                            if pause_used is not None:goals[tid]['tokensUsed']=pause_used
                            if 'tokenBudget' in params:goals[tid]['tokenBudget']=params['tokenBudget']
                            if lost_rollback and 'tokenBudget' in params:ws.close();return
                            ws.send(json.dumps(dict(id=req['id'],result={'goal':goals[tid]})))
                            continue
                        if 'objective' not in params:
                            goals[tid].update(status=params['status'],updatedAt=1003)
                            if params['status']=='active' and (enforce_deadline or late_source or cached_goal):
                                threads[tid]['turns'].append(dict(id='autonomous-turn',status='inProgress',items=[]))
                            if params['status']=='active' and cached_goal:goals[tid]['tokensUsed']=1
                            if ((lost_pause or lost_rollback_pause) and params['status']=='paused') or (lost_activate and params['status']=='active'):ws.close();return
                            ws.send(json.dumps(dict(id=req['id'],result={'goal':goals[tid]})))
                            continue
                        goals[tid]=dict(threadId=tid,objective=params['objective'],status=params['status'],
                            tokenBudget=params['tokenBudget'],tokensUsed=0,timeUsedSeconds=0,createdAt=1001,updatedAt=1001)
                        if lost_goal:ws.close();return
                        value={'goal':goals[tid]}
                    elif method=='turn/interrupt':
                        interrupts.append(params)
                        for turn in threads[tid]['turns']:
                            if turn['id']==params['turnId']:turn['status']='interrupted'
                        if lost_preflight_interrupt:ws.close();return
                        value={}
                    elif method=='thread/queue/add':
                        queue[tid]=dict(id='preflight-queue',clientUserMessageId=params['clientUserMessageId'],input=params['input'])
                        value={'queuedSubmission':queue[tid]}
                    elif method=='thread/queue/list':value={'data':[queue[tid]] if tid in queue else [],'nextCursor':None}
                    elif method=='thread/queue/start':
                        q=queue.pop(tid);task=q['input'][0]['text']
                        if task.startswith('BOUNDED_ASSIGNMENT='):
                            task=json.loads(task.split('BOUNDED_ASSIGNMENT=',1)[1])['instructions']
                        contract=json.loads(task.split('PREFLIGHT_CONTRACT=',1)[1].split('\n',1)[0])
                        corrected='CORRECTION_PACKET=' in task
                        if corrected:
                            repair_cmd=[sys.executable,'-c',"from pathlib import Path; Path('repair.txt').write_text('corrected')"]
                            repair=external_run(repair_cmd,cwd=tmp,capture_output=True,text=True,check=True)
                        cmd=[sys.executable,str(helper),source,contract['intent_fingerprint'],digest]
                        p=external_run(cmd,cwd=tmp,env=dict(os.environ,CODEX_THREAD_ID=tid),capture_output=True,text=True,check=True)
                        proof=json.loads((root/'preflight.json').read_text())
                        proof['selected_workflow']=workflow
                        proof['configuration_revision']=contract['configuration_revision']
                        proof['work_review']=dict(verdict='accept',selected_review='local evidence review',
                            changes=['Outgoing checkpoint preserves remaining work'],
                            acceptance_progress=[dict(criterion='bounded continuation',change='Restart-safe checkpoint written',
                                evidence=[dict(path='checkpoint.json',sha256=digest)])],
                            scope_deviations=[],unsupported_claims=[],unfinished_work=['Native continuation'],
                            next_packet='Run selected preflight')
                        if bad_review=='scope_drift':proof['work_review']['scope_deviations']=['Changed unrelated service']
                        if bad_review=='test_count_only':proof['work_review']['acceptance_progress']=[]
                        if bad_review=='changed_evidence':proof['work_review']['acceptance_progress'][0]['evidence'][0]['sha256']='0'*64
                        if bad_review=='unknown_criterion':proof['work_review']['acceptance_progress'][0]['criterion']='invented acceptance'
                        (root/'preflight.json').write_text(json.dumps(proof))
                        if correction:
                            proof=json.loads((root/'preflight.json').read_text())
                            if not corrected or correction=='reject':
                                proof['work_review'].update(verdict='correct',unsupported_claims=['Repair still unaccepted'],
                                    correction_packet=dict(criterion='bounded continuation',paths=['repair.txt'],
                                        evidence=[dict(path='repair.txt',sha256=hashlib.sha256((root/'repair.txt').read_bytes()).hexdigest())],
                                        instructions='Repair the broken fixture and review the actual result.'))
                            else:
                                proof['work_review']['acceptance_progress'][0]['evidence']=[dict(path='repair.txt',
                                    sha256=hashlib.sha256((root/'repair.txt').read_bytes()).hexdigest())]
                            if correction=='drift':proof['work_review']['correction_packet']['paths']=['outside.txt']
                            (root/'preflight.json').write_text(json.dumps(proof))
                        if work_verdict:
                            proof=json.loads((root/'preflight.json').read_text())
                            proof['work_review']=dict(verdict=work_verdict,
                                unsupported_claims=['Completion based only on test count'])
                            (root/'preflight.json').write_text(json.dumps(proof))
                        prior_turns=threads[tid]['turns'] if correction else []
                        threads[tid]['turns']=prior_turns+[dict(id='preflight-turn-'+str(len(prior_turns)) if correction else 'preflight-turn',status='completed',items=[
                            dict(id='user',type='userMessage',clientId=q['clientUserMessageId'],content=q['input']),
                            dict(id='preflight-command',type='commandExecution',status='completed',exitCode=p.returncode,
                                cwd=tmp,command=shlex.join(cmd),aggregatedOutput=p.stdout)])]
                        read=external_run(['cat',str(reviewer)],capture_output=True,text=True,check=True)
                        threads[tid]['turns'][-1]['items'].append(dict(id='review-instructions',
                            type='commandExecution',status='completed',exitCode=read.returncode,cwd=tmp,
                            command=shlex.join(['cat',str(reviewer)]),aggregatedOutput=read.stdout))
                        (home/'sessions'/ (tid+'.jsonl')).write_text(json.dumps(dict(type='event_msg',payload=dict(
                            type='token_count',info={'total_token_usage':{'total_tokens':30*len(threads[tid]['turns']) if correction else 30}})))+'\n')
                        if pending_usage:
                            threads[tid]['turns'][0]['status']='inProgress'
                            (home/'sessions'/ (tid+'.jsonl')).write_text('')
                        if unloaded_active:
                            threads[tid]['turns'][0]['status']='inProgress'
                        if running_overspend:
                            threads[tid]['turns'][0]['status']='inProgress'
                            (home/'sessions'/ (tid+'.jsonl')).write_text(json.dumps(dict(type='event_msg',payload=dict(type='token_count',info={'total_token_usage':{'total_tokens':101}})))+'\n')
                        if expire_preflight:clock['utc'].update(lower=2001,upper=2002)
                        value={}
                    else:raise AssertionError('unexpected native method '+method)
                    ws.send(json.dumps(dict(id=req['id'],result=value)))
            modal={"visible":False,"dismissals":0}
            def command(argv,**kwargs):
                if 'list-panes' in argv:
                    if '-a' in argv:
                        out='\n'.join('\t'.join(['$1','owned','@'+pane[1:],'1',p['name'],pane,'0',
                            threads[source]['name'] if visibility['stale_title'] and p['thread']==target else threads[p['thread']]['name'],tmp,p['tty']]) for pane,p in panes.items())
                    else:out='\n'.join(p for p in panes if '@'+p[1:] in argv)
                elif 'capture-pane' in argv:
                    out=('\x1b[1mResume paused goal?\x1b[0m\n\x1b[1;7m› 1. Resume goal   Mark it active and continue when idle\n2. Leave paused  Keep it paused; use /goal resume later\nenter select · esc back' if modal['visible'] else '\n\n\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m\n')
                    if modal['visible'] and resume_modal=='other':out=out.replace('Resume paused goal?','Unknown dialog')
                elif 'send-keys' in argv:
                    self.assertEqual(argv[-1],'Escape');self.assertTrue(modal['visible'])
                    modal['visible']=False;modal['dismissals']+=1;out=''
                    if lost_modal:raise subprocess.TimeoutExpired(argv,1)
                elif 'display-message' in argv:out='2,2'
                elif 'respawn-pane' in argv:
                    self.assertTrue(same_tab or missing_source);respawns.append(argv)
                    pane=argv[argv.index('-t')+1]
                    self.assertEqual(pane,'%160' if missing_source else '%159')
                    old=next(c for c in clients if c.pid==panes[pane]['pid'])
                    old.terminate();old.wait(timeout=2)
                    restored=source if source in argv[-1] else target
                    modal['visible']=resume_modal and restored==source
                    launch(['sh','-c','exec '+argv[-1]],pane,'original-worker',restored);out=''
                    if lost_respawn or lost_restore and restored==source:raise subprocess.TimeoutExpired(argv,1)
                elif 'new-window' in argv:
                    self.assertFalse(same_tab)
                    launch(['sh','-c','exec '+argv[-1]],'%160',argv[argv.index('-n')+1],target);out='@160\t%160'
                else:out=''
                return subprocess.CompletedProcess(argv,0,out,'')
            argv=['--wake-root',tmp,'sessions','handoff','--profiles',str(profiles),'--profile','worker',
                '--intent','handoff-1','--thread-id',source,'--checkpoint','checkpoint.json',
                '--checkpoint-sha256',digest,'--expires-at','2030-01-01T00:00:00Z','--mode','same-tab' if same_tab else 'new-tab','--json']
            if common_permissions:
                argv+=['--bus-root',str(permission_bus.root),'--operator-capability',str(permission_capability),'--trigger','context_limit']
            # Preserve the exact readiness observation if the aggregate guard fails.
            from codex_wake.sessions import observe, revalidate_attachment, tmux_inventory, codex_client_identities_for_ttys
            readiness = {}
            readiness_deferrals = 0
            inventory_diagnostics = []
            budget_miss = dict(injected=False, base=0.0, offset=0.0, armed=False)
            def timed_identity(ttys):
                started = time.monotonic()
                try:
                    return codex_client_identities_for_ttys(ttys)
                finally:
                    inventory_diagnostics.append(dict(kind='identity', elapsed=time.monotonic()-started))
                    if budget_miss['armed']:
                        budget_miss.update(injected=True, armed=False, offset=2.0)
            def diagnosed_inventory(*args, **kwargs):
                started = time.monotonic()
                budget_miss.update(base=budget_miss['base']+budget_miss['offset']+1.0, offset=0.0, armed=inventory_budget_miss and not budget_miss['injected'] and len(panes)==2)
                try:
                    # Host scheduling and unrelated /proc size are not fixture inputs.
                    # Advance a monotonic observation clock between inventories; only
                    # the explicit miss advances during a real identity scan.
                    # Keep all process identity and uniqueness checks real.
                    with patch('codex_wake.sessions.time', SimpleNamespace(
                            monotonic=lambda:budget_miss['base']+budget_miss['offset'])):
                        return tmux_inventory(*args, **kwargs)
                except Exception as exc:
                    inventory_diagnostics.append(dict(kind='inventory_error', type=type(exc).__name__, message=str(exc)))
                    raise
                finally:
                    inventory_diagnostics.append(dict(kind='inventory', elapsed=time.monotonic()-started))
            def observed_readiness(**kwargs):
                inventory_diagnostics.clear()
                snapshot = observe(**kwargs)
                readiness.clear()
                readiness['snapshot'] = snapshot
                readiness['inventory'] = list(inventory_diagnostics)
                readiness['clock'] = dict(wall=time.time(), monotonic=time.monotonic(), native=json.loads(json.dumps(clock)))
                return snapshot
            def revalidated_readiness(attachment):
                valid = revalidate_attachment(attachment)
                readiness['revalidation'] = dict(attachment=attachment, valid=valid)
                return valid
            server=unix_serve(handler,str(endpoint));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                with patch('subprocess.run',side_effect=command),patch('codex_wake.native_clock.snapshot',
                        return_value=clock),patch('codex_wake.sessions.observe',side_effect=observed_readiness),patch(
                        'codex_wake.sessions.revalidate_attachment',side_effect=revalidated_readiness),patch(
                        'codex_wake.sessions.tmux_inventory',side_effect=diagnosed_inventory),patch(
                        'codex_wake.sessions.codex_client_identities_for_ttys',side_effect=timed_identity):
                    for _ in range(3 if pending_usage or correction or stale_title else 2):
                        output=StringIO()
                        if changed_defaults and _==1:
                            from codex_wake.records import WakeError
                            config=json.loads(profiles.read_text())
                            config['lifecycle_defaults']['session_token_limit']=400
                            profiles.write_text(json.dumps(config))
                            with self.assertRaisesRegex(WakeError, 'different lifecycle assignment'):
                                with redirect_stdout(output):run(argv)
                            self.assertEqual(methods.count('thread/start'),1)
                            self.assertEqual(goals[target]['status'],'paused')
                            return
                        with redirect_stdout(output):self.assertEqual(run(argv),5)
                        receipt=json.loads(output.getvalue())
                        if (receipt['state']=='awaiting_preflight' and receipt.get('successor',{}).get('reason')=='exact_idle_owned_client_not_ready'):
                            # An incomplete observation defers admission safely. Reconcile
                            # the same intent once, within the scenario's existing bound.
                            self.assertEqual(_,0,readiness)
                            readiness_deferrals += 1
                            self.assertEqual(methods.count('thread/start'),1)
                            self.assertEqual(methods.count('thread/queue/start'),0)
                            self.assertNotIn(target,goals)
                            if inventory_budget_miss:
                                self.assertTrue(budget_miss['injected'])
                                self.assertIn(dict(kind='inventory_error',type='SharedSourceError',
                                    message='tmux observation timed out'),readiness['inventory'])
                            continue
                        if common_permissions:
                            self.assertEqual(receipt['permission_context']['approval_id'],'task-approval')
                            self.assertEqual(receipt['permission_context']['trigger'],'context_limit')
                            if receipt['state']=='awaiting_activation':
                                self.assertEqual(receipt['permission_succession']['successor'],target)
                                self.assertEqual(receipt['permission_succession']['task_id'],'fixture-task')
                        if task_brief:
                            pin = body['task_brief']
                            self.assertEqual(receipt['intent']['task_brief'], pin)
                            self.assertEqual(receipt['successor']['intent']['task_brief'], pin)
                            self.assertIn('Never deploy', receipt['successor']['intent']['task'])
                            self.assertNotIn('Future instructions only', receipt['successor']['intent']['task'])
                            contract = json.loads(receipt['preflight_task'].split('PREFLIGHT_CONTRACT=', 1)[1].split('\n', 1)[0])
                            self.assertEqual(contract['task_brief'], pin)
                            self.assertEqual(len(briefs.inspect('fixture-task')['admissions']), 1)
                        if reference_contract:
                            contract=json.loads(receipt['preflight_task'].split('PREFLIGHT_CONTRACT=',1)[1].split('\n',1)[0])
                            for selection in ('handoff_writer','preflight_reviewer'):
                                self.assertEqual(set(contract[selection]),{'name','path','sha256'})
                                self.assertEqual(contract[selection]['sha256'],receipt['configuration'][selection]['sha256'])
                        if unloaded_active and _==0:
                            continue
                        if unread_writer:
                            self.assertEqual(receipt['reason'], 'handoff_writer_instructions_unverified')
                            self.assertEqual(methods.count('thread/start'), 0)
                            return
                        if pending_usage and _<2:
                            self.assertEqual(receipt['state'],'awaiting_preflight')
                            self.assertEqual(methods.count('thread/queue/add'),1)
                            self.assertNotIn(target,goals)
                            if _==1:
                                threads[target]['turns'][0]['status']='completed'
                                (home/'sessions'/ (target+'.jsonl')).write_text(json.dumps(dict(type='event_msg',
                                    payload=dict(type='token_count',info={'total_token_usage':{'total_tokens':30}})))+'\n')
                            continue
                        if correction:
                            if correction=='drift':
                                self.assertEqual(receipt['reason'],'work_review_correct')
                                self.assertEqual(receipt['objective_budget']['correction_cycles'],0)
                                self.assertEqual(methods.count('thread/queue/add'),1)
                                return
                            if receipt['state']=='correcting':
                                self.assertNotIn(target,goals)
                                self.assertEqual(receipt['objective_budget']['correction_cycles'],_+1)
                                continue
                            if correction=='reject':
                                self.assertEqual(receipt['reason'],'correction_cycles_exhausted')
                                self.assertEqual(receipt['objective_budget']['correction_cycles'],2)
                                self.assertEqual(methods.count('thread/queue/add'),3)
                                self.assertNotIn(target,goals)
                                repeated=StringIO()
                                with redirect_stdout(repeated):self.assertEqual(run(argv),5)
                                self.assertEqual(json.loads(repeated.getvalue())['reason'],'correction_cycles_exhausted')
                                self.assertEqual(methods.count('thread/queue/add'),3)
                                return
                            self.assertEqual(receipt['state'],'awaiting_activation')
                            self.assertEqual((root/'repair.txt').read_text(),'corrected')
                            self.assertEqual(receipt['preflight_tokens_used'],60)
                            self.assertEqual(receipt['remaining_tokens'],890)
                            self.assertEqual(methods.count('thread/start'),1)
                            return
                        if stale_title and _<2:
                            if _==0:self.assertEqual(receipt['state'],'awaiting_preflight')
                            else:
                                self.assertEqual(receipt['reason'],'source_attachment_generation_changed')
                                visibility['stale_title']=False
                            continue
                        if lost_respawn and _==0:
                            self.assertEqual(receipt['state'],'uncertain')
                            self.assertEqual(receipt['successor']['uncertain_effect'],'tmux/respawn-pane')
                            continue
                        if running_overspend:
                            self.assertEqual(receipt['state'],'uncertain' if lost_preflight_interrupt and _==0 else 'blocked')
                            if not (lost_preflight_interrupt and _==0):
                                self.assertEqual(receipt['reason'],'preflight_allowance_exhausted')
                            self.assertEqual(receipt['preflight_tokens_used'],101)
                            self.assertEqual(interrupts,[dict(threadId=target,turnId='preflight-turn')])
                            self.assertNotIn(target,goals)
                            self.assertEqual(methods.count('thread/start'),1)
                            if _==1:return
                            continue
                        if expire_preflight:
                            self.assertEqual(receipt['state'],'expired', {'receipt':receipt,'readiness':readiness})
                            self.assertEqual(receipt['reason'],'continuation_time_exhausted')
                            self.assertNotIn(target,goals)
                            self.assertEqual(goal_sets,[])
                            self.assertEqual(methods.count('thread/start'),1)
                            return
                        if bad_review:
                            successor = receipt.get('successor', {})
                            self.assertEqual(receipt['reason'], 'substantive_work_review_unverified', {
                                'handoff_state': receipt.get('state'),
                                'successor_state': successor.get('state'),
                                'successor_reason': successor.get('reason'),
                                'successor_uncertain_effect': successor.get('uncertain_effect'),
                                'successor_history': successor.get('history'),
                            })
                            self.assertNotIn(target, goals)
                            self.assertEqual(receipt['preflight_tokens_used'], 30)
                            return
                        if source_budget==60:
                            self.assertEqual(receipt['reason'],'preflight_allowance_insufficient')
                            self.assertEqual(methods.count('thread/start'),0)
                            self.assertEqual(goal_sets,[])
                            return
                        if lost_goal:
                            self.assertEqual(receipt['state'],'uncertain')
                            self.assertEqual(receipt['uncertain_effect'],'thread/goal/prepare_successor')
                            continue
                        if work_verdict:
                            self.assertEqual(receipt['reason'], 'work_review_correct')
                            self.assertNotIn(target, goals)
                            self.assertEqual(receipt['runtime_readiness']['state'], 'passed')
                            return
                        if unloaded_active:
                            self.assertEqual(receipt['state'],'blocked')
                            self.assertEqual(receipt['reason'],'detached_source_retirement_unverified')
                            self.assertNotIn(target,goals)
                            return
                        self.assertEqual(receipt['state'],'awaiting_activation',{'history':receipt.get('successor',{}).get('history'),'respawns':len(respawns),'readiness':readiness})
                        if inherited_deadline:
                            self.assertEqual(receipt['continuation_deadline'],inherited_deadline)
                            self.assertEqual(receipt['objective_budget']['actors'][receipt['budget_actor']]['session_deadline'],inherited_deadline)
                        self.assertEqual(receipt['successor_thread_id'],target)
                        self.assertEqual(receipt['remaining_tokens'],min(session_cap,950 if pause_used is None else 1000-pause_used)-30)
                        self.assertEqual(receipt['preflight']['state'],'passed')
                    if before_source:
                        from codex_wake.daemon import run as daemon_run
                        goals[source]['tokensUsed']=150
                        with redirect_stdout(StringIO()):
                            self.assertEqual(daemon_run(['--wake-root',tmp,'--once','--no-dispatch']),0)
                        saved=root/'lifecycle'/(hashlib.sha256(b'handoff-1').hexdigest()+'.json')
                        self.assertEqual(json.loads(saved.read_text())['reason'],'source_accounting_advanced')
                        self.assertEqual(goals[target]['status'],'paused')
                        self.assertEqual(len(goal_sets),1)
                        return
                    if rollback:
                        if missing_source:
                            clients[0].terminate();clients[0].wait(timeout=2);del panes['%159']
                        if active_rollback:
                            goals[target]['status']='active'
                            threads[target]['turns'].append(dict(id='autonomous-turn',status='inProgress',items=[]))
                            owner=root/'lifecycle'/ ('owner-'+hashlib.sha256(source.encode()).hexdigest()+'.json')
                            lease=json.loads(owner.read_text());lease['state']='active';owner.write_text(json.dumps(lease))
                        if owner_conflict:
                            owner=root/'lifecycle'/ ('owner-'+hashlib.sha256(source.encode()).hexdigest()+'.json')
                            lease=json.loads(owner.read_text());lease['intent_fingerprint']='another-transition';owner.write_text(json.dumps(lease))
                            out=StringIO()
                            with redirect_stdout(out):self.assertEqual(run(argv+['--rollback']),5)
                            self.assertEqual(json.loads(out.getvalue())['rollback']['reason'],'source_owned_by_another_transition')
                            self.assertEqual(goals[source]['tokenBudget'],1000)
                            self.assertEqual(len(goal_sets),1)
                            return
                        for index in range(3 if late_usage or lost_modal else 2):
                            out=StringIO()
                            with redirect_stdout(out):self.assertEqual(run(argv+['--rollback']),5 if resume_modal=="other" or late_usage and index<2 or lost_modal and index<2 or (lost_rollback or lost_rollback_pause or lost_restore or resume_modal) and index==0 else 0)
                            restored=json.loads(out.getvalue())['rollback']
                            if resume_modal=='other' and index==1:
                                self.assertEqual(restored['state'],'blocked')
                                self.assertEqual(modal['dismissals'],0)
                                self.assertEqual(goals[source]['status'],'paused')
                                self.assertEqual(goals[source]['tokenBudget'],1000)
                                self.assertEqual(len(respawns),2)
                                return
                            if lost_modal and index==1:
                                self.assertEqual(restored['state'],'uncertain')
                                self.assertEqual(restored['uncertain_effect'],'tmux/rollback_leave_paused')
                                self.assertEqual(modal['dismissals'],1)
                                continue
                            if resume_modal and index==0:
                                self.assertEqual(restored['state'],'uncertain')
                                self.assertEqual(goals[source]['status'],'paused')
                                continue
                            if lost_restore and index==0:
                                self.assertEqual(restored['state'],'uncertain')
                                self.assertEqual(restored['uncertain_effect'],'tmux/rollback_respawn')
                                self.assertEqual(goals[source]['tokenBudget'],1000)
                                continue
                            if lost_rollback_pause and index==0:
                                self.assertEqual(restored['state'],'uncertain')
                                self.assertEqual(restored['uncertain_effect'],'thread/goal/rollback_pause_successor')
                                self.assertEqual(goals[source]['tokenBudget'],1000)
                                continue
                            self.assertEqual(restored['state'],'uncertain' if late_usage and index<2 or lost_rollback and index==0 else 'completed')
                            self.assertEqual(restored['thread_id'],source)
                            self.assertEqual(restored['remaining_tokens'],910 if late_usage and index>0 else 920)
                            self.assertEqual(goals[source]['tokenBudget'],960 if late_usage and index>0 else 970)
                            if late_usage and index==0:
                                (home/'sessions'/ (target+'.jsonl')).write_text(json.dumps(dict(type='event_msg',payload=dict(type='token_count',info={'total_token_usage':{'total_tokens':40}})))+'\n')
                            self.assertEqual(goals[source]['tokensUsed'],50)
                        if resume_modal:self.assertEqual(modal['dismissals'],1)
                        if missing_source or same_tab:
                            self.assertIsNotNone(clients[0].poll())
                            self.assertEqual(restored['attachment']['pane_id'],'%159' if same_tab else '%160')
                            self.assertEqual(len(respawns),2 if same_tab else 1)
                        else:self.assertEqual(clients[0].poll(),None)
                        if active_rollback:
                            self.assertEqual(goals[target]['status'],'paused')
                            self.assertEqual(interrupts,[dict(threadId=target,turnId='autonomous-turn')])
                    if activate:
                        from codex_wake.daemon import run as daemon_run
                        sleeps=[]
                        def sleep(_):
                            sleeps.append(1)
                            if cached_goal:
                                if len(sleeps)==1:
                                    self.assertEqual(goals[target]['status'],'active')
                                    (home/'sessions'/ (target+'.jsonl')).write_text(json.dumps(dict(type='event_msg',payload=dict(type='token_count',info={'total_token_usage':{'total_tokens':120}})))+'\n')
                                    return
                                self.assertEqual(goals[target]['status'],'paused')
                                self.assertEqual(interrupts,[dict(threadId=target,turnId='autonomous-turn')])
                                saved=json.loads((root/'lifecycle'/(hashlib.sha256(b'handoff-1').hexdigest()+'.json')).read_text())
                                self.assertEqual(saved['objective_budget']['actors'][saved['budget_actor']]['used'],120)
                                raise KeyboardInterrupt
                            if late_source:
                                if len(sleeps)==1:
                                    self.assertEqual(goals[target]["status"],"active")
                                    if late_source=="time":goals[source]["timeUsedSeconds"]=13
                                    else:goals[source]["tokensUsed"]=150
                                    return
                                self.assertEqual(goals[target]["status"],"paused")
                                self.assertEqual(interrupts,[dict(threadId=target,turnId="autonomous-turn")])
                                saved=root/"lifecycle"/(hashlib.sha256(b"handoff-1").hexdigest()+".json")
                                self.assertEqual(json.loads(saved.read_text())["reason"],"source_accounting_advanced")
                                raise KeyboardInterrupt
                            if foreign_monitor and len(sleeps)==1:
                                from codex_wake.process import process_identity
                                saved=root/'lifecycle'/ (hashlib.sha256(b'handoff-1').hexdigest()+'.json')
                                lease=json.loads(saved.read_text())
                                lease['deadline_fence'].update(pid=clients[0].pid,identity=process_identity(clients[0].pid))
                                saved.write_text(json.dumps(lease))
                                clock['utc'].update(lower=1990,upper=1991)
                                return
                            if enforce_deadline and len(sleeps)==1:
                                self.assertEqual(goals[target]['status'],'active')
                                if enforce_deadline=='unknown':clock.clear()
                                else:clock['utc'].update(lower=1990,upper=1991)
                                return
                            if lost_pause and len(sleeps)==2:return
                            if lost_activate and len(sleeps)==1:return
                            if not enforce_deadline:
                                self.assertEqual(goals[target]['status'],'active')
                                if readback:
                                    out=StringIO()
                                    with redirect_stdout(out):self.assertEqual(run(argv),0)
                                    self.assertEqual(json.loads(out.getvalue())['state'],'active')
                                saved=root/'lifecycle'/ (hashlib.sha256(b'handoff-1').hexdigest()+'.json')
                                self.assertEqual(json.loads(saved.read_text())['state'],'active')
                            raise KeyboardInterrupt
                        with patch('codex_wake.daemon.time.sleep',side_effect=sleep),redirect_stdout(StringIO()):
                            with self.assertRaises(KeyboardInterrupt):
                                daemon_run(['--wake-root',tmp,'--no-dispatch','--interval','1'])
                        self.assertEqual(goals[target]['status'],'active' if foreign_monitor else 'paused')
                        if enforce_deadline:
                            self.assertEqual(interrupts,[dict(threadId=target,turnId='autonomous-turn')])
                            saved=root/'lifecycle'/ (hashlib.sha256(b'handoff-1').hexdigest()+'.json')
                            self.assertEqual(json.loads(saved.read_text())['state'],'blocked' if enforce_deadline=='unknown' else 'expired')
                        self.assertEqual(goals[source]['status'],'paused')
                        if lost_activate:
                            saved=root/'lifecycle'/ (hashlib.sha256(b'handoff-1').hexdigest()+'.json')
                            self.assertEqual(json.loads(saved.read_text())['reason'],'monitor_stopped')
                    if monitor_expiry:
                        from codex_wake.daemon import run as daemon_run
                        clock['utc'].update(lower=2001,upper=2002)
                        with redirect_stdout(StringIO()):
                            self.assertEqual(daemon_run(['--wake-root',tmp,'--once','--no-dispatch']),0)
                        saved=root/'lifecycle'/ (hashlib.sha256(b'handoff-1').hexdigest()+'.json')
                        monitored=json.loads(saved.read_text())
                        self.assertEqual(monitored['state'],'expired')
                        self.assertEqual(monitored['reason'],'continuation_time_exhausted')
                    if lost_goal:
                        self.assertEqual(len(goal_sets),1)
                        visibility['show_goal']=True
                        output=StringIO()
                        with redirect_stdout(output):self.assertEqual(run(argv),5)
                        self.assertEqual(json.loads(output.getvalue())['state'],'awaiting_activation')
                self.assertEqual(methods.count('thread/start'),1)
                self.assertEqual(methods.count('thread/queue/add'),1)
                if inventory_budget_miss:
                    self.assertEqual(readiness_deferrals,1)
                self.assertEqual(methods.count('thread/queue/start'),1)
                self.assertEqual(len(goal_sets),(2 if foreign_monitor else 3) if activate else (3 if active_rollback or late_usage else 2 if rollback or pause_used is not None else 1))
                self.assertEqual(goals[source]['tokensUsed'],150 if late_source and late_source!="time" else 50 if pause_used is None else pause_used)
                self.assertEqual(goals[source]['status'],'paused')
                self.assertEqual(goals[target]['status'],'active' if foreign_monitor else 'paused')
                self.assertEqual(goals[target]['tokenBudget'],min(session_cap,950 if pause_used is None else 1000-pause_used)-30)
                if same_tab:
                    self.assertIsNotNone(clients[0].poll())
                    self.assertEqual(list(panes),['%159'])
                    self.assertEqual(len(respawns),2 if rollback else 1)
                    self.assertEqual(receipt['successor']['pane_id'],'%159')
                    self.assertIsNone(clients[-1].poll())
                elif missing_source:self.assertIsNone(clients[-1].poll())
                else:self.assertTrue(all(c.poll() is None for c in clients))
            finally:
                server.shutdown();worker.join(2)
                for client in clients:client.terminate();client.wait(timeout=2);client.stdout.close()
                for fd in fds:os.close(fd)
