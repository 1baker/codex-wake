"""Public lifecycle behavior; fixture profiles never grant live authority."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import os
import pty
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from websockets.sync.server import unix_serve

from codex_wake.cli import run
from codex_wake.records import WakeError


class AgentSpawnTests(unittest.TestCase):
    def test_configured_spawn_without_resident_supervisor_admits_no_native_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);instructions=root/'instructions.md';instructions.write_text('Review approved work.')
            profiles=root/'profiles.json';endpoint=root/'native.sock'
            selection=dict(name='fixture',path=str(instructions))
            profiles.write_text(json.dumps(dict(version=1,profiles={'worker':dict(cwd=tmp,
                app_server='unix://'+str(endpoint),codex_path='/bin/true',tmux_session='fixture',timeout=1)},
                lifecycle_defaults=dict(handoff_writer=selection,preflight_reviewer=selection,
                    session_token_limit=100,session_time_limit_seconds=100,
                    objective_token_limit=1000,objective_time_limit_seconds=1000,max_correction_cycles=2),
                continuations={'bootstrap':dict(approval='operator fixture',objective='Finish fixture',
                    started_at='1970-01-01T00:16:40Z')})))
            calls=[]
            def handler(ws):
                for raw in ws:calls.append(json.loads(raw))
            with unix_serve(handler,str(endpoint)) as server:
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                try:
                    output=StringIO()
                    with redirect_stdout(output),patch('subprocess.run'),patch(
                            'codex_wake.native_clock.snapshot',return_value={'utc':{'lower':1000,'upper':1001}}):
                        self.assertEqual(run(['--wake-root',tmp,'sessions','spawn','--profiles',str(profiles),
                            '--profile','worker','--objective-ref','bootstrap','--intent','supervised',
                            '--name','worker','--task','Report42','--expires-at','2030-01-01T00:00:00Z','--json']),5)
                    self.assertEqual(json.loads(output.getvalue())['reason'],'resident_objective_supervisor_required')
                    self.assertEqual(calls,[])
                finally:server.shutdown();worker.join(2)

    def test_configured_spawn_requires_an_approved_objective_before_native_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profiles=root/'profiles.json'
            profiles.write_text(json.dumps(dict(version=1,lifecycle_defaults={'session_token_limit':100},
                profiles={'worker':dict(cwd=tmp,app_server='unix:///missing.sock',codex_path='/bin/true',
                    tmux_session='fixture',timeout=1)})))
            with self.assertRaisesRegex(WakeError,'approved objective reference'):
                run(['--wake-root',tmp,'sessions','spawn','--profiles',str(profiles),'--profile','worker',
                     '--intent','missing-objective','--name','worker','--task','Report42',
                     '--expires-at','2030-01-01T00:00:00Z','--json'])
            self.assertFalse((root/'lifecycle').exists())
    def test_symlink_endpoint_is_rejected_before_creation_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);endpoint=root/'native.sock';link=root/'locator.sock'
            with unix_serve(lambda ws: None,str(endpoint)) as server:
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                link.symlink_to(endpoint)
                profiles=root/'profiles.json'
                profiles.write_text(json.dumps({'version':1,'profiles':{'worker':dict(
                    cwd=tmp,app_server='unix://'+str(link),codex_path='/bin/true',
                    tmux_session='fixture',timeout=1)}}))
                try:
                    with redirect_stdout(StringIO()),patch('subprocess.run'),patch(
                            'codex_wake.native_clock.snapshot',return_value={'utc':{'lower':1000,'upper':1001}}), \
                            self.assertRaisesRegex(WakeError,'owned Unix socket'):
                        run(['--wake-root',tmp,'sessions','spawn','--profiles',str(profiles),
                            '--profile','worker','--intent','invalid-endpoint','--name','worker',
                            '--task','Report readiness.','--expires-at','2030-01-01T00:00:00Z','--json'])
                    self.assertFalse((root/'lifecycle').exists())
                finally:server.shutdown();worker.join(2)

    def test_unapproved_profile_is_rejected_before_runtime_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles = Path(tmp) / 'profiles.json'
            profiles.write_text(json.dumps({'version': 1, 'profiles': {}}))
            with redirect_stdout(StringIO()), self.assertRaisesRegex(WakeError, 'approved launch profile'):
                run(['--wake-root', tmp, 'sessions', 'spawn', '--profiles', str(profiles),
                     '--profile', 'unapproved', '--intent', 'first-worker', '--name', 'worker',
                     '--task', 'Report readiness.', '--expires-at', '2030-01-01T00:00:00Z', '--json'])

    def test_malformed_host_profile_is_rejected_without_creating_journal(self):
        invalid = [('cwd', None), ('timeout', '1'), ('timeout', True),
                   ('app_server', []), ('codex_path', None), ('tmux_session', ''),
                   ('codex_home', []), ('tmux_socket', 42)]
        for field, value in invalid:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                profiles = Path(tmp) / 'profiles.json'
                profile = dict(cwd=tmp, app_server='unix:///missing.sock',
                               codex_path='/bin/true', tmux_session='fixture', timeout=1)
                profile[field] = value
                profiles.write_text(json.dumps({'version': 1, 'profiles': {'worker': profile}}))
                with redirect_stdout(StringIO()), self.assertRaisesRegex(WakeError, 'profile'):
                    run(['--wake-root', tmp, 'sessions', 'spawn', '--profiles', str(profiles),
                         '--profile', 'worker', '--intent', 'malformed', '--name', 'worker',
                         '--task', 'Report readiness.', '--expires-at', '2030-01-01T00:00:00Z', '--json'])
                self.assertFalse((Path(tmp) / 'lifecycle').exists())

    def test_unknown_thread_creation_is_retained_without_duplicate_retry(self):
        starts = []
        def handler(ws):
            for raw in ws:
                request = json.loads(raw)
                if 'id' not in request:
                    continue
                if request['method'] == 'thread/start':
                    starts.append(request['params'])
                    ws.close()
                    return
                ws.send(json.dumps({'id': request['id'], 'result': {}}))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            endpoint = root / 'native.sock'
            profiles = root / 'profiles.json'
            profiles.write_text(json.dumps({'version': 1, 'profiles': {'worker': {
                'cwd': tmp, 'app_server': 'unix://' + str(endpoint),
                'codex_path': '/bin/true', 'tmux_session': 'fixture', 'timeout': 1,
            }}}))
            argv = ['--wake-root', tmp, 'sessions', 'spawn', '--profiles', str(profiles),
                    '--profile', 'worker', '--intent', 'one-worker', '--name', 'worker',
                    '--task', 'Report readiness.', '--expires-at', '2030-01-01T00:00:00Z', '--json']
            with unix_serve(handler, str(endpoint)) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    with patch('subprocess.run') as command, patch(
                            'codex_wake.native_clock.snapshot', return_value={
                                'utc': {'lower': 1000, 'upper': 1001}, 'counter': None}):
                        command.return_value.stdout = ''
                        for _ in range(2):
                            output = StringIO()
                            with redirect_stdout(output):
                                self.assertEqual(run(argv), 5)
                            receipt = json.loads(output.getvalue())
                            self.assertEqual(receipt['state'], 'uncertain')
                            self.assertEqual(receipt['uncertain_effect'], 'thread/start')
                        self.assertEqual(len(starts), 1)
                finally:
                    server.shutdown()
                    worker.join(timeout=2)

    def test_peer_cannot_select_profile_without_host_caller_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles = Path(tmp) / 'profiles.json'
            profiles.write_text(json.dumps({'version': 1, 'profiles': {'worker': {
                'cwd': tmp, 'app_server': 'unix:///missing.sock', 'codex_path': '/bin/true',
                'tmux_session': 'fixture', 'timeout': 1,
            }}, 'callers': {'00000000-0000-7000-8000-000000000011': ['worker']}}))
            with redirect_stdout(StringIO()), self.assertRaisesRegex(WakeError, 'caller grant'):
                run(['--wake-root', tmp, 'sessions', 'spawn', '--profiles', str(profiles),
                     '--profile', 'worker', '--intent', 'unauthorized', '--name', 'worker',
                     '--task', 'Report readiness.', '--expires-at', '2030-01-01T00:00:00Z',
                     '--caller-thread-id', '00000000-0000-7000-8000-000000000099', '--json'])

    def test_spawn_executes_exact_assignment_once_across_pending_observation(self):
        self.spawn_scenario()

    def test_configured_spawn_reserves_and_settles_one_shared_actor(self):
        self.spawn_scenario(budget=True)

    def test_daemon_interrupts_only_owned_spawn_at_original_session_deadline(self):
        self.spawn_scenario(budget=True,budget_stop=True)

    def test_completed_native_turn_holds_until_final_rollout_accounting_marker(self):
        self.spawn_scenario(budget=True,budget_delayed=True)

    def test_daemon_does_not_complete_spawn_from_stale_usage_after_rollout_read_error(self):
        self.spawn_scenario(budget=True,budget_read_error=True)

    def test_daemon_cancels_exact_queued_spawn_after_lost_admission_response_and_expiry(self):
        self.spawn_scenario(budget=True,loss='queue/add',budget_queue_stop=True)

    def test_host_lower_spawn_allowance_blocks_completed_native_overspend(self):
        self.spawn_scenario(budget=True,budget_overrun=True)

    def test_lost_task_admission_response_reconciles_exact_queue_without_resend(self):
        self.spawn_scenario(loss='queue/add')

    def test_lost_turn_start_response_reconciles_completion_without_restart(self):
        self.spawn_scenario(loss='queue/start')

    def test_lost_tab_creation_response_reconciles_owned_generation_without_replacement(self):
        self.spawn_scenario(loss='new-window')

    def test_spawn_does_not_inherit_parent_actor_or_mailbox_capability(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'parent', 'TMUX_PANE': '%parent',
                                    'CODEX_WAKE_A2A_CAPABILITY': '/parent/capability',
                                    'CODEX_WAKE_A2A_BUS_ROOT': '/parent/bus',
                                    'CODEX_WAKE_SENDER_RECEIPT_AUTHORITY': '/parent/authority'}):
            self.spawn_scenario(check_environment=True)

    def test_fixed_expiry_survives_startup_and_prevents_late_task_admission(self):
        self.spawn_scenario(expire_at_task=True)

    def test_reconciled_completion_keeps_original_uncertain_effect_history(self):
        self.spawn_scenario(loss='queue/add', check_history=True)

    def test_host_profile_uses_exact_isolated_socket_and_codex_home(self):
        self.spawn_scenario(isolated_profile=True)

    def test_native_default_text_elements_do_not_make_exact_admission_uncertain(self):
        self.spawn_scenario(normalized_input=True)

    def test_tui_auto_start_is_observed_without_starting_another_turn(self):
        self.spawn_scenario(auto_start=True)

    def test_rendered_local_draft_prevents_native_assignment(self):
        self.spawn_scenario(composer='draft')

    def test_background_painted_empty_composer_is_accepted(self):
        """#214 S214-EMPTY-COMPOSER-RENDER-03: Codex 0.169 paints the empty composer row's background."""
        self.spawn_scenario(composer='background')

    def test_restart_rechecks_draft_before_prepared_task_admission(self):
        self.spawn_scenario(interrupted_admission=True)

    def test_active_unknown_or_split_recipient_is_held_without_task_admission(self):
        for guard in ('active', 'unknown', 'split'):
            with self.subTest(guard=guard):
                self.spawn_scenario(recipient_guard=guard)

    def test_shared_profile_resource_checks_do_not_override_spawn_launch(self):
        self.spawn_scenario(resource_profile=True)

    def spawn_scenario(self, *, loss=None, check_environment=False, expire_at_task=False,
                       check_history=False, isolated_profile=False, normalized_input=False, auto_start=False, composer=None, interrupted_admission=False, recipient_guard=None, resource_profile=False,budget=False,budget_stop=False,budget_delayed=False,budget_read_error=False,budget_queue_stop=False,budget_overrun=False):
        thread_id = '00000000-0000-7000-8000-000000000157'
        starts, tasks, windows = [], [], []
        turn_starts = []
        interrupts=[]
        queue_deletes=[]
        state = {'name': None, 'turns': [], 'loaded': False}
        def handler(ws):
            for raw in ws:
                request = json.loads(raw)
                if 'id' not in request:
                    continue
                method, params = request['method'], request.get('params', {})
                thread = dict(id=thread_id, name=state['name'], cwd=tmp, status={'type': recipient_guard if recipient_guard in ('active', 'unknown') else 'idle'},
                              canAcceptDirectInput=True, turns=state['turns'])
                if budget:thread['path']=str(rollout)
                if method == 'thread/start':
                    starts.append(params)
                    result = {'thread': thread}
                elif method == 'thread/name/set':
                    state['name'] = params['name']
                    result = {}
                elif method == 'thread/loaded/list':
                    result = {'data': [thread_id] if state['loaded'] else [], 'nextCursor': None}
                elif method == 'thread/read':
                    result = {'thread': thread}
                elif method == 'thread/queue/add':
                    tasks.append(params)
                    result = {'queuedSubmission': dict(id='queue157', **params)}
                    if normalized_input:
                        result['queuedSubmission']['input'] = [
                            dict(params['input'][0], text_elements=[])]
                    if auto_start:
                        state['turns'] = [dict(id='turn157', status='inProgress', items=[
                            dict(id='user157', type='userMessage', clientId=params['clientUserMessageId'],
                                 content=params['input'])])]
                    if loss == 'queue/add':
                        ws.close()
                        return
                elif method == 'thread/queue/start':
                    turn_starts.append(params)
                    task = tasks[-1]
                    state['turns'] = [dict(id='turn157',
                        status='completed' if loss else 'inProgress', items=[
                        dict(id='user157', type='userMessage', clientId=task['clientUserMessageId'],
                             content=task['input'])])]
                    result = {'turn': state['turns'][0]}
                    if loss == 'queue/start':
                        ws.close()
                        return
                elif method == 'thread/queue/list':
                    result = {'data': [dict(id='queue157', **tasks[-1])]
                              if tasks and not state['turns'] and not queue_deletes else [], 'nextCursor': None}
                elif method == 'thread/queue/delete':
                    queue_deletes.append(params);result={'deleted':True}
                elif method == 'turn/interrupt':
                    interrupts.append(params);state['turns'][0]['status']='interrupted';result={}
                else:
                    result = {}
                ws.send(json.dumps({'id': request['id'], 'result': result}))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            endpoint = root / 'native.sock'
            profiles = root / 'profiles.json'
            client_script = root / 'codex'
            client_script.write_text(f'#!{sys.executable}\n'
                'import ctypes,time,os,json,pathlib\n'
                "ctypes.CDLL(None).prctl(15,b'codex',0,0,0)\n"
                f'pathlib.Path({str(root / "client-env.json")!r}).write_text(json.dumps('
                '{k:v for k,v in os.environ.items() if k.startswith("CODEX_WAKE_") '
                'or k in ("CODEX_THREAD_ID","TMUX_PANE","CODEX_HOME")}))\n'
                "print('ready',flush=True)\ntime.sleep(60)\n")
            client_script.chmod(0o700)
            profile = {
                'cwd': tmp, 'app_server': 'unix://' + str(endpoint), 'codex_path': str(client_script),
                'tmux_session': 'fixture', 'timeout': 1,
            }
            if resource_profile:
                profile['resources']={'version':{'kind':'mcp','server':'unused','tool':'version',
                    'arguments':{},'read_only':True,'expected_content':[{'type':'text','text':'v2'}]}}
            if isolated_profile:
                (root / 'codex-home').mkdir()
                profile.update(tmux_socket=str(root / 'tmux.sock'), codex_home=str(root / 'codex-home'))
            registry={'version': 1, 'profiles': {'worker': profile}}
            if budget:
                home=root/'home';(home/'sessions').mkdir(parents=True)
                profile['codex_home']=str(home);rollout=home/'sessions/fixture.jsonl'
                rollout.write_text(json.dumps(dict(type='event_msg',payload=dict(type='token_count',
                    info=dict(total_token_usage=dict(total_tokens=20)))))+'\n')
                instructions=root/'instructions.md';instructions.write_text('Review approved work.')
                selection=dict(name='fixture',path=str(instructions))
                registry.update(lifecycle_defaults=dict(handoff_writer=selection,preflight_reviewer=selection,
                    session_token_limit=100,session_time_limit_seconds=100,
                    objective_token_limit=1000,objective_time_limit_seconds=1000,max_correction_cycles=2),
                    continuations={'bootstrap':dict(approval='operator fixture',objective='Finish fixture',
                        started_at='1970-01-01T00:16:40Z')})
                if budget_overrun:registry['continuations']['bootstrap']['spawn_token_limit']=50
            profiles.write_text(json.dumps(registry))
            master, slave = pty.openpty()
            client = None
            tty = os.ttyname(slave)
            def command(argv, **kwargs):
                nonlocal client
                if isolated_profile:
                    self.assertEqual(argv[:3], ['tmux', '-S', str(root / 'tmux.sock')])
                if 'new-window' in argv:
                    windows.append(argv)
                    client = subprocess.Popen(['sh', '-c', 'exec ' + argv[-1]],
                                              stdin=slave, stdout=subprocess.PIPE)
                    self.assertEqual(client.stdout.readline(), b'ready\n')
                    state['loaded'] = True
                    if loss == 'new-window':
                        raise subprocess.TimeoutExpired(argv, 1)
                    output = '@157\t%157'
                elif 'capture-pane' in argv:
                    text = 'UNSUBMITTED_DRAFT_157' if composer == 'draft' else '\x1b[2mAsk Codex to do anything\x1b[0m'
                    output = '\n\n\x1b[1m›\x1b[0m ' + text + '\n\n  GPT-6.1-Sol low · fixture\n'
                    if composer == 'background':     # exact Codex 0.169 render captured from a held helper (#214)
                        output = ('\n\n\x1b[1m›\x1b[0m\x1b[48;2;41;41;41m \x1b[2mAsk Codex to do anything\x1b[0m'
                                  '\x1b[48;2;41;41;41m\n\n  GPT-6.1-Sol low · fixture\n')
                elif 'display-message' in argv:
                    output = '23,2' if composer == 'draft' else '2,2'
                elif 'list-panes' in argv:
                    output = (('%157\n%158' if recipient_guard == 'split' else '%157') if '-a' not in argv else '\t'.join([
                        '$1', 'fixture', '@157', '1', 'worker', '%157', '0', state['name'], tmp, tty, '']))
                else:
                    output = ''
                return subprocess.CompletedProcess(argv, 0, output, '')
            argv = ['--wake-root', tmp, 'sessions', 'spawn', '--profiles', str(profiles),
                    '--profile', 'worker', '--intent', 'one-worker', '--name', 'worker',
                    '--task', 'Calculate 6 * 7 and report 42.',
                    '--expires-at', '2030-01-01T00:00:00Z', '--json']
            if budget:argv.extend(['--objective-ref','bootstrap'])
            interrupted = False
            budget_expired=False
            def clock():
                nonlocal interrupted
                if interrupted_admission and state['loaded'] and not interrupted:
                    interrupted = True
                    raise SystemExit('fixture controller termination before admission')
                upper = 1102 if budget_expired else 1893456001 if expire_at_task and state['loaded'] else 1001
                return {'utc': {'lower': upper - 1, 'upper': upper}, 'counter': None}
            try:
                with unix_serve(handler, str(endpoint)) as server:
                    worker = threading.Thread(target=server.serve_forever, daemon=True)
                    worker.start()
                    try:
                        with patch('subprocess.run', side_effect=command), patch(
                                'codex_wake.native_clock.snapshot', side_effect=clock):
                            if budget:
                                from codex_wake.lifecycle_supervision import publish_supervision
                                publish_supervision(root,1)
                            if interrupted_admission:
                                with redirect_stdout(StringIO()), self.assertRaises(SystemExit):
                                    run(argv)
                                composer = 'draft'
                            pending = StringIO()
                            with redirect_stdout(pending):
                                self.assertEqual(run(argv), 5, pending.getvalue())
                            if recipient_guard:
                                self.assertEqual(tasks, [])
                                self.assertEqual(len(starts), 1)
                                self.assertEqual(len(windows), 1)
                                self.assertEqual(json.loads(pending.getvalue())['reason'],
                                    'split_or_changed_tab' if recipient_guard == 'split' else 'exact_idle_owned_client_not_ready')
                                return
                            if composer == 'draft':
                                self.assertEqual(tasks, [], 'native idle must not overwrite a local draft')
                                self.assertEqual(json.loads(pending.getvalue())['reason'], 'local_composer_not_proven_empty')
                                return
                            if normalized_input:
                                self.assertEqual(json.loads(pending.getvalue())['state'], 'awaiting_preflight')
                            if expire_at_task:
                                self.assertEqual(json.loads(pending.getvalue())['state'], 'expired')
                                with redirect_stdout(StringIO()):
                                    self.assertEqual(run(argv), 5)
                                self.assertEqual(len(starts), 1)
                                self.assertEqual(len(windows), 1)
                                self.assertEqual(tasks, [])
                                return
                            if budget_stop:
                                from codex_wake.daemon import poll_once
                                budget_expired=True
                                poll_once(root,dispatch=False)
                                self.assertEqual(interrupts,[dict(threadId=thread_id,turnId='turn157')])
                                poll_once(root,dispatch=False)
                                self.assertEqual(len(interrupts),1)
                                self.assertEqual(len(tasks),1)
                                self.assertEqual(len(starts),1)
                                ledger=json.loads(next((root/'objective-ledgers').glob('*.json')).read_text())
                                self.assertEqual(len(ledger['actors']),1)
                                self.assertEqual(next(iter(ledger['actors'].values()))['used'],20)
                                return
                            if budget_queue_stop:
                                from codex_wake.daemon import poll_once
                                budget_expired=True
                                poll_once(root,dispatch=False)
                                self.assertEqual(queue_deletes,[dict(threadId=thread_id,queuedSubmissionId='queue157')])
                                poll_once(root,dispatch=False)
                                self.assertEqual(len(queue_deletes),1)
                                self.assertEqual(turn_starts,[])
                                self.assertEqual(len(tasks),1)
                                ledger=json.loads(next((root/'objective-ledgers').glob('*.json')).read_text())
                                actor=next(iter(ledger['actors'].values()))
                                self.assertTrue(actor['settled'])
                                self.assertEqual(actor['used'],0)
                                return
                            if state['turns']:
                                state['turns'][0]['status'] = 'completed'
                            if budget_read_error:
                                from codex_wake.daemon import poll_once
                                rollout.write_text('malformed fixture rollout\n')
                                poll_once(root,dispatch=False)
                                saved=json.loads(next(p for p in (root/'lifecycle').glob('*.json')
                                    if p.name!='supervision.json').read_text())
                                self.assertNotEqual(saved['state'],'completed')
                                return
                            if budget:
                                rollout.write_text(json.dumps(dict(type='event_msg',payload=dict(type='token_count',
                                    info=dict(total_token_usage=dict(total_tokens=70)))))+'\n')
                                if budget_delayed:
                                    held=StringIO()
                                    with redirect_stdout(held):self.assertEqual(run(argv),5)
                                    self.assertEqual(json.loads(held.getvalue())['reason'],'final_usage_unknown')
                                with rollout.open('a') as stream:
                                    stream.write(json.dumps(dict(type='event_msg',payload=dict(type='task_complete',turn_id='turn157')))+'\n')
                                if budget_overrun:
                                    held=StringIO()
                                    with redirect_stdout(held):self.assertEqual(run(argv),5)
                                    receipt=json.loads(held.getvalue())
                                    self.assertEqual(receipt['state'],'blocked')
                                    self.assertEqual(receipt['reason'],'session_token_allowance_exceeded')
                                    actor=receipt['objective_budget']['actors'][receipt['budget_actor']]
                                    self.assertEqual(actor['reservation'],50)
                                    self.assertEqual(actor['used'],70)
                                    self.assertEqual(len(tasks),1)
                                    return
                            for _ in range(2):
                                output = StringIO()
                                with redirect_stdout(output):
                                    self.assertEqual(run(argv), 0, output.getvalue())
                                receipt = json.loads(output.getvalue())
                                self.assertEqual(receipt['state'], 'completed')
                                self.assertEqual(receipt['thread_id'], thread_id)
                                self.assertEqual(receipt['execution']['turn_id'], 'turn157')
                                if budget:
                                    view=receipt['objective_budget']
                                    self.assertEqual(view['tokens_used'],70)
                                    self.assertEqual(view['tokens_reserved'],0)
                                    self.assertEqual(len(view['actors']),1)
                                    self.assertEqual(receipt['assignment_deadline'],1101)
                                if check_history:
                                    self.assertIn({'state': 'uncertain', 'effect': 'thread/queue/add',
                                                   'reason': 'ConnectionClosedOK'}, receipt['history'])
                                    self.assertIsNone(receipt.get('reason'))
                            self.assertEqual(len(starts), 1)
                            self.assertEqual(len(tasks), 1)
                            self.assertEqual(len(windows), 1)
                            self.assertEqual(len(turn_starts), 0 if auto_start else 1)
                            self.assertEqual(tasks[0]['input'], [
                                {'type': 'text', 'text': 'Calculate 6 * 7 and report 42.'}])
                            if check_environment:
                                variables = json.loads((root / 'client-env.json').read_text())
                                self.assertFalse(set(variables) & {
                                    'CODEX_THREAD_ID', 'TMUX_PANE', 'CODEX_WAKE_A2A_CAPABILITY',
                                    'CODEX_WAKE_A2A_BUS_ROOT', 'CODEX_WAKE_SENDER_RECEIPT_AUTHORITY'})
                            if isolated_profile:
                                self.assertEqual(json.loads((root / 'client-env.json').read_text())['CODEX_HOME'],
                                                 str(root / 'codex-home'))
                    finally:
                        server.shutdown()
                        worker.join(timeout=2)
            finally:
                if client:
                    client.terminate()
                    client.wait(timeout=2)
                    client.stdout.close()
                os.close(master)
                os.close(slave)
