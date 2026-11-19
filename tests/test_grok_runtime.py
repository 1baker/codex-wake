import unittest
from codex_wake.runtime_delivery import RuntimeRecipient

SESSION = 'fce842bc-e502-40ba-a892-6d7778283ef1'
FRAME = f'''  Shell version: 1.0.40 [stable]
  Session ID: {SESSION}
minimal · /help
❯
Grok 4.7 (high) · 27K / 256K (11%) · ctrl+o transcript
'''

class GrokRuntimeTests(unittest.TestCase):
    def test_qualified_idle_is_distinct_from_draft_unknown_ui_and_changed_process(self):
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            frame = FRAME
            generation = 42
            def snapshot(self, binding):
                return dict(start_ticks=self.generation, boot_id='boot', pid=123,
                            session_id=SESSION, executable_sha256='a'*64, frame=self.frame)
        host = Host()
        binding = dict(start_ticks=42, boot_id='boot', pid=123, session_id=SESSION,
                       executable_sha256='a'*64)
        adapter = GrokRuntimeAdapter(host)
        recipient = RuntimeRecipient('grok', SESSION, binding)
        ready = adapter.observe(recipient)
        self.assertEqual(ready.state, 'ready')
        self.assertEqual(ready.capabilities['submit'].state, 'supported')
        self.assertEqual(ready.capabilities['receiver_acknowledgment'].state, 'not_qualified')
        for frame, generation in ((FRAME.replace('❯\n', '❯ unsent draft\n'), 42),
                                   (FRAME+'Permission required\n', 42),
                                   (FRAME.replace('minimal · /help','No active session\nminimal · /help'), 42),
                                   (FRAME.replace(SESSION, 'different-session'), 42),
                                   (FRAME, 43)):
            with self.subTest(frame=frame, generation=generation):
                host.frame, host.generation = frame, generation
                self.assertNotEqual(adapter.observe(recipient).state, 'ready')

    def test_submission_rechecks_identity_and_reconciles_only_accepted_marker_without_replay(self):
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            frame = FRAME
            inputs = []
            def snapshot(self, binding):
                return dict(binding, frame=self.frame)
            def refresh_identity(self,binding):
                pass
            def paste(self, binding, prompt, *, deadline=None):
                self.inputs.append(prompt)
                self.frame = FRAME.replace('minimal · /help', prompt+'\nminimal · /help')
        host = Host()
        binding = dict(start_ticks=42, boot_id='boot', pid=123, session_id=SESSION,
                       executable_sha256='a'*64)
        adapter = GrokRuntimeAdapter(host)
        recipient = RuntimeRecipient('grok', SESSION, binding)
        prompt = 'WAKE_RUNTIME_SUBMISSION_ID=01234567-89ab-cdef-0123-456789abcdef\nSynthetic task'
        result = adapter.submit(recipient, prompt)
        self.assertEqual(result.state, 'accepted')
        self.assertEqual(result.evidence_kind, 'terminal_observation')
        self.assertEqual(result.evidence['execution'],'not_observed')
        self.assertEqual(adapter.reconcile(recipient, prompt).evidence['execution'], 'not_observed')
        self.assertEqual(host.inputs, [prompt])
        host.frame = FRAME.replace('❯\n', '❯ '+prompt.splitlines()[0]+'\n')
        self.assertIsNone(adapter.reconcile(recipient, prompt).evidence)
        self.assertEqual(adapter.submit(recipient, prompt).state, 'not_sent')
        self.assertEqual(host.inputs, [prompt])

class GrokStableDeadlineTests(unittest.TestCase):
    def test_missing_clock_refuses_before_identity_or_prompt_input(self):
        from unittest.mock import patch
        from codex_wake.measurements import TimeUnavailable
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            def snapshot(self,binding):raise AssertionError('observation forbidden')
            def refresh_identity(self,binding):raise AssertionError('identity input forbidden')
            def paste(self,*args,**kwargs):raise AssertionError('prompt input forbidden')
        with patch('codex_wake.measurements.deadline',side_effect=TimeUnavailable('private-clock')):
            result=GrokRuntimeAdapter(Host()).submit(RuntimeRecipient('grok',SESSION,{}),'Task')
        self.assertEqual(result.state,'not_sent')
        self.assertTrue(result.pre_io)
        self.assertEqual(result.reason,'qualified_time_unavailable')

    def test_clock_loss_after_possible_paste_preserves_uncertainty_and_parent(self):
        from unittest.mock import patch
        from codex_wake import measurements
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            inputs=[]
            def snapshot(self,binding):return dict(binding,frame=FRAME)
            def refresh_identity(self,binding):pass
            def paste(self,binding,prompt,*,deadline=None):
                self.inputs.append(prompt)
                self.received_deadline=deadline
                raise measurements.TimeUnavailable('private-clock-loss')
        host=Host()
        recipient=RuntimeRecipient('grok',SESSION,dict(start_ticks=42,boot_id='boot',pid=123,session_id=SESSION,executable_sha256='a'*64,allow_terminal_input=True,allow_terminal_fallback=True))
        parent=measurements.deadline(30)
        with patch('codex_wake.measurements.deadline',side_effect=AssertionError('parent must not renew')):
            result=GrokRuntimeAdapter(host,deadline=parent,preferred_method='native_preferred').submit(recipient,'Task')
        self.assertEqual(result.state,'uncertain')
        self.assertFalse(result.pre_io)
        self.assertEqual(host.inputs,['Task'])
        self.assertIs(host.received_deadline,parent)
        self.assertIs(host.deadline,parent)
        self.assertNotIn('private-clock-loss',str(result))

    def test_late_or_clock_lost_receipt_never_accepts_after_possible_paste(self):
        from unittest.mock import patch
        from codex_wake import measurements
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        from test_measurements import observation
        prompt='WAKE_RUNTIME_SUBMISSION_ID=01234567-89ab-cdef-0123-456789abcdef\nTask'
        for failure in ('elapsed','unavailable'):
            clock=[1000]
            class Host:
                pasted=False
                inputs=[]
                def snapshot(self,binding):
                    if self.pasted:
                        clock[0]=40000 if failure=='elapsed' else None
                        return dict(binding,frame=FRAME.replace('minimal · /help',prompt+'\nminimal · /help'))
                    return dict(binding,frame=FRAME)
                def refresh_identity(self,binding):pass
                def paste(self,binding,prompt,*,deadline=None):
                    self.inputs.append(prompt);self.pasted=True
            def read_clock():
                if clock[0] is None:raise measurements.TimeUnavailable('private-clock-loss')
                return observation(clock[0],rate=0)
            host=Host()
            recipient=RuntimeRecipient('grok',SESSION,dict(start_ticks=42,boot_id='boot',pid=123,session_id=SESSION,executable_sha256='a'*64))
            with self.subTest(failure=failure), patch('codex_wake.measurements.snapshot',side_effect=read_clock):
                result=GrokRuntimeAdapter(host).submit(recipient,prompt)
                self.assertEqual(result.state,'uncertain')
                self.assertFalse(result.pre_io)
                self.assertEqual(host.inputs,[prompt])
                self.assertNotIn('private-clock-loss',str(result))

    def test_identity_commands_share_parent_and_five_second_phase(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from contextlib import nullcontext
        from pathlib import Path
        import socket,tempfile
        from codex_wake import measurements
        from codex_wake.grok_terminal import GrokTerminalHost
        from test_measurements import observation
        clock=[1000]
        timeouts=[]
        def run(*args,**kwargs):
            timeouts.append(kwargs['timeout'])
            clock[0]+=2000
            return SimpleNamespace(returncode=0,stdout=b'')
        with tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_UNIX) as endpoint:
            path=Path(directory)/'terminal.sock';endpoint.bind(str(path));path.chmod(0o600)
            with patch('codex_wake.measurements.snapshot',side_effect=lambda:observation(clock[0],rate=0)):
                parent=measurements.deadline(30)
                host=GrokTerminalHost(directory,deadline=parent)
                with patch.object(host,'snapshot',side_effect=[{'frame':'  Session ID: old'}, {'frame':'  Session ID: old\n  Session ID: current'}]), patch('codex_wake.grok_terminal.subprocess.run',side_effect=run), patch('codex_wake.guarded_interactions.automated_input_guard',return_value=nullcontext()):
                    host.refresh_identity({'socket':str(path),'pane':'%1'})
                self.assertIs(host.deadline,parent)
                self.assertIsNone(host._phase_deadline)
        self.assertEqual(len(timeouts),2)
        self.assertLessEqual(timeouts[0],3)
        self.assertLess(timeouts[1],3)
        self.assertGreater(timeouts[1],2.99)

    def test_numeric_deadline_is_refused_without_observation(self):
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            def snapshot(self,binding):raise AssertionError('observation forbidden')
        outcome=GrokRuntimeAdapter(Host(),deadline=1800000000).submit(RuntimeRecipient('grok',SESSION,{}),'Task')
        self.assertEqual(outcome.state,'not_sent')
        self.assertTrue(outcome.pre_io)
        self.assertEqual(outcome.reason,'qualified_time_unavailable')

class GrokScheduleTests(unittest.TestCase):
    def test_cli_retains_versioned_grok_intent_and_daemon_dispatches_once_across_polls(self):
        import contextlib, io, json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from codex_wake.cli import run
        from codex_wake.records import all_records, classify_record
        from codex_wake.daemon import poll_once
        from codex_wake.time_provider import TimeDecision
        from codex_wake.runtime_delivery import RuntimeObservation, RuntimeReconciliation, RuntimeSubmission
        binding_id = 'grok_'+'a'*32
        binding = dict(session_id=SESSION)
        reading = TimeDecision('network', ('one','two'), 1800000000, 1800000000.1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('codex_wake.grok_terminal.GrokTerminalHost.load_binding', return_value=binding), patch(
                    'codex_wake.runtime_wakes.binding_digest', return_value='b'*64), patch(
                    'codex_wake.native_clock.snapshot', return_value=dict(utc=dict(status='network', sources=['one','two'],lower=reading.lower,upper=reading.upper),counter=None)), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(['--wake-root',str(root),'grok','after','--ttl','2m','--idempotency-key','original',binding_id,'1s','--','Synthetic wake']),0)
            authority_path=all_records(root)[0].path
            record=all_records(root)[0].record
            self.assertEqual(record['schema_version'],8)
            self.assertEqual(record['intent_schema_version'],7)
            self.assertEqual(classify_record(record),'runtime_intent_v7')
            self.assertEqual(classify_record(dict(record,schema_version=1)),'hold')
            with patch('codex_wake.grok_runtime.GrokRuntimeAdapter.resolve', return_value=RuntimeRecipient('grok',SESSION,{})), patch(
                    'codex_wake.grok_runtime.GrokRuntimeAdapter.observe', return_value=RuntimeObservation('ready','idle',{})), patch(
                    'codex_wake.grok_runtime.GrokRuntimeAdapter.submit', return_value=RuntimeSubmission('accepted',evidence_kind='terminal_observation')) as send:
                due=lambda:TimeDecision('network',('one','two'),1800000002,1800000002.1)
                self.assertEqual(poll_once(root,time_provider=due).submitted,1)
                self.assertEqual(poll_once(root,time_provider=due).submitted,0)
                self.assertEqual(send.call_count,1)
            saved=all_records(root)[0].record
            self.assertEqual(all_records(root)[0].path,authority_path)
            self.assertEqual(saved['attempts'],1)
            self.assertEqual(saved['runtime_delivery']['evidence_kind'],'terminal_observation')
            self.assertEqual(saved['runtime_delivery']['execution'],'not_observed')
            self.assertEqual(saved['runtime_delivery']['acknowledgment'],'not_observed')
            from codex_wake.mcp_server import CommandRunner
            value,error=CommandRunner(wake_root=root).call('wake_grok_show',{'wake_id':saved['id']})
            self.assertFalse(error,value)
            self.assertEqual(value['runtime_delivery']['evidence_kind'],'terminal_observation')
            self.assertNotIn('prompt',value)

    def test_cancel_expiry_and_ambiguous_submission_preserve_original_attempt(self):
        import contextlib, io, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from codex_wake.cli import run
        from codex_wake.records import all_records, cancel_record
        from codex_wake.daemon import poll_once
        from codex_wake.runtime_delivery import RuntimeObservation, RuntimeReconciliation
        from codex_wake.time_provider import TimeDecision
        for scenario in ('wait','cancel','expire','lost_response'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                clock=dict(utc=dict(status='network',sources=['one','two'],lower=1800000000,upper=1800000000.1),counter=None)
                with patch('codex_wake.grok_terminal.GrokTerminalHost.load_binding',return_value=dict(session_id=SESSION)), patch(
                        'codex_wake.runtime_wakes.binding_digest',return_value='b'*64), patch(
                        'codex_wake.native_clock.snapshot',return_value=clock), contextlib.redirect_stdout(io.StringIO()):
                    args=['--wake-root',str(root),'grok','after','--ttl','2m','--idempotency-key','intent','grok_'+'a'*32,'1s','--','Synthetic']
                    self.assertEqual(run(args),0)
                    self.assertEqual(run(args),0)
                    self.assertEqual(len(all_records(root)),1)
                original=all_records(root)[0].record
                if scenario=='cancel':
                    cancel_record(root,original['id'])
                with patch('codex_wake.grok_runtime.GrokRuntimeAdapter.resolve',return_value=RuntimeRecipient('grok',SESSION,{})), patch(
                        'codex_wake.grok_runtime.GrokRuntimeAdapter.observe',return_value=RuntimeObservation('unavailable' if scenario=='wait' else 'ready','fixture',{})), patch(
                        'codex_wake.grok_runtime.GrokRuntimeAdapter.submit',side_effect=OSError('PRIVATE_LOST_RESPONSE')) as send, patch(
                        'codex_wake.grok_runtime.GrokRuntimeAdapter.reconcile',return_value=RuntimeReconciliation(reason='not_observed')):
                    when=1800000200 if scenario=='expire' else 1800000002
                    poll_once(root,time_provider=lambda:TimeDecision('network',('one','two'),when,when+.1))
                    poll_once(root,time_provider=lambda:TimeDecision('uncertain'))
                    saved=all_records(root)[0].record
                    self.assertEqual(send.call_count,1 if scenario=='lost_response' else 0)
                    self.assertEqual(saved['attempts'],1 if scenario=='lost_response' else 0)
                    self.assertEqual(saved['scheduling_intent'],original['scheduling_intent'])
                    self.assertNotIn('PRIVATE_LOST_RESPONSE',str(saved))
                    if scenario=='lost_response':
                        self.assertEqual(saved['runtime_delivery']['state'],'uncertain')
                    else:
                        self.assertEqual(saved['status'],'pending' if scenario=='wait' else 'cancelled' if scenario=='cancel' else 'failed')

class GrokMCPTests(unittest.TestCase):
    def test_tools_require_host_root_and_never_admit_socket_or_operator_binding(self):
        from codex_wake.mcp_server import SPECS, CommandRunner
        self.assertTrue('wake_grok_sessions' in SPECS)
        self.assertTrue('wake_grok_show' in SPECS)
        self.assertNotIn('wake_grok_bind',SPECS)
        runner=CommandRunner()
        value,error=runner.call('wake_grok_after',dict(binding_id='grok_'+'a'*32,trigger='1m',prompt='Synthetic',idempotency_key='key'))
        self.assertTrue(error)
        self.assertEqual(value['error']['code'],'runtime_host_scope_unavailable')
        value,error=runner.call('wake_grok_after',dict(binding_id='grok_'+'a'*32,trigger='1m',prompt='Synthetic',idempotency_key='key',socket='/chosen/socket'))
        self.assertTrue(error)
        self.assertEqual(value['error']['code'],'invalid_argument')

class GrokFreshIdentityTests(unittest.TestCase):
    def test_changed_conversation_in_same_process_is_detected_before_prompt(self):
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            frame=FRAME
            prompts=[]
            def snapshot(self,binding):return dict(binding,frame=self.frame)
            def refresh_identity(self,binding):self.frame=FRAME.replace(SESSION,'new-conversation')
            def paste(self,binding,prompt, *, deadline=None):self.prompts.append(prompt)
        host=Host()
        recipient=RuntimeRecipient('grok',SESSION,dict(start_ticks=42,boot_id='boot',pid=123,session_id=SESSION,executable_sha256='a'*64))
        outcome=GrokRuntimeAdapter(host).submit(recipient,'WAKE_RUNTIME_SUBMISSION_ID=01234567-89ab-cdef-0123-456789abcdef\nTask')
        self.assertEqual(outcome.state,'not_sent')
        self.assertEqual(host.prompts,[])

    def test_expired_handoff_window_prevents_even_identity_control_input(self):
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            def snapshot(self,binding):raise AssertionError('expired attempt must not inspect or input')
            def refresh_identity(self,binding):raise AssertionError('expired attempt must not input')
        recipient=RuntimeRecipient('grok',SESSION,{})
        self.assertEqual(GrokRuntimeAdapter(Host(),deadline=0).submit(recipient,'Task').state,'not_sent')

class GrokBindingFileTests(unittest.TestCase):
    def test_binding_digest_permissions_and_symlinks_refuse_changed_host_scope(self):
        import tempfile,hashlib
        from pathlib import Path
        from codex_wake.grok_terminal import GrokTerminalHost
        from codex_wake.records import WakeError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'runtime-bindings';directory.mkdir()
            identity='grok_'+'a'*32
            path=directory/(identity+'.json')
            data=b'{"version":1,"allow_terminal_input":true,"session_id":"fixture"}\n'
            path.write_bytes(data);path.chmod(0o600)
            checksum=hashlib.sha256(data).hexdigest()
            host=GrokTerminalHost(root)
            self.assertEqual(host.load_binding(identity,checksum)['session_id'],'fixture')
            path.write_bytes(data.replace(b'fixture',b'replacement'))
            with self.assertRaises(WakeError):host.load_binding(identity,checksum)
            path.write_bytes(data);path.chmod(0o644)
            with self.assertRaises(WakeError):host.load_binding(identity,checksum)
            path.unlink();real=root/'real';real.write_bytes(data);real.chmod(0o600);path.symlink_to(real)
            with self.assertRaises(WakeError):host.load_binding(identity,checksum)

class GrokMonitorReceiptTests(unittest.TestCase):
    def test_missing_worker_returns_inspectable_retained_intent_without_rebasing(self):
        import contextlib,io,json,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from codex_wake.cli import run
        from codex_wake.records import all_records
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            args=['--wake-root',str(root),'grok','after','--require-monitor','--json','--idempotency-key','same-intent','grok_'+'a'*32,'1m','--','Task']
            ids=[]
            for _ in range(2):
                output=io.StringIO()
                with patch('codex_wake.grok_terminal.GrokTerminalHost.load_binding',return_value=dict(session_id=SESSION)),patch(
                        'codex_wake.runtime_wakes.binding_digest',return_value='b'*64),patch(
                        'codex_wake.native_clock.snapshot',return_value=dict(utc=None,counter=None)),patch(
                        'codex_wake.signal_records.probe_managed_reader_capability',return_value=None),contextlib.redirect_stdout(output):
                    code=run(args)
                self.assertEqual(code,3)
                value=json.loads(output.getvalue())
                self.assertEqual(value['reason'],'compatible_monitor_unavailable')
                ids.append(value['id'])
            self.assertEqual(ids[0],ids[1])
            self.assertEqual(len(all_records(root)),1)
            self.assertEqual(all_records(root)[0].record['attempts'],0)


class GrokDelayedPaintTests(unittest.TestCase):
    def test_submission_waits_for_original_marker_without_second_paste(self):
        from codex_wake.grok_runtime import GrokRuntimeAdapter
        class Host:
            prompt=None
            paints=0
            inputs=[]
            def refresh_identity(self,binding):pass
            def snapshot(self,binding):
                if self.prompt is not None:self.paints+=1
                frame=FRAME
                if self.paints>=2:frame=frame.replace('minimal · /help',self.prompt+'\nminimal · /help')
                return dict(binding,frame=frame)
            def paste(self,binding,prompt,*,deadline=None):
                self.inputs.append(prompt);self.prompt=prompt
        host=Host()
        binding=dict(start_ticks=42,boot_id='boot',pid=123,session_id=SESSION,executable_sha256='a'*64)
        recipient=RuntimeRecipient('grok',SESSION,binding)
        prompt='WAKE_RUNTIME_SUBMISSION_ID=01234567-89ab-cdef-0123-456789abcdef\nSynthetic task'
        result=GrokRuntimeAdapter(host).submit(recipient,prompt)
        self.assertEqual(result.state,'accepted')
        self.assertEqual(host.inputs,[prompt])


def setUpModule():
    from itertools import count
    from unittest.mock import patch
    from test_measurements import observation
    global _qualified_clock_patch
    counters=count(1000,100)
    _qualified_clock_patch=patch('codex_wake.measurements.snapshot', side_effect=lambda:observation(next(counters),rate=0))
    _qualified_clock_patch.start()


def tearDownModule():
    _qualified_clock_patch.stop()
