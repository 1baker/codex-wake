"""Cross-runtime permission, work-claim and notification invariants at public seams."""
import json
import tempfile
import unittest
from pathlib import Path

from codex_wake.a2a_bus import BusStore
from codex_wake.a2a_identity import BusError, RuntimeIdentity
from codex_wake.a2a_mailbox import Mailbox
from codex_wake.runtime_a2a import GrokMailboxRuntime

SESSION='01234567-89ab-cdef-0123-456789abcdef'
BINDING='grok_'+'a'*32

class Host:
    changed=False
    expected_digest="f"*64
    def load_binding(self, binding_id, expected_sha256=None):
        if binding_id!=BINDING or expected_sha256 not in (None,self.expected_digest):raise ValueError('binding changed')
        return dict(pid=123,start_ticks=42,boot_id='boot',session_id=SESSION,
                    executable='/opt/grok',executable_sha256='a'*64)
    def snapshot(self,binding):
        return dict(binding,start_ticks=43 if self.changed else 42,
                    frame=f'Shell version: 1.0.40 [stable]\nSession ID: {SESSION}\n')

class Process:
    descendant=True
    def __init__(self,root):self.root=root
    def cwd(self,pid):return self.root
    def owns_caller(self,binding):return self.descendant

class RuntimeA2ATests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.bus,self.operator=BusStore.configure(self.root/'bus')
        self.bus.enroll(self.repo,self.operator,notify=True)
        Mailbox.migrate(self.bus,self.operator)
        self.host=Host();self.process=Process(self.repo)
        self.runtime=GrokMailboxRuntime(self.root/'wake',host=self.host,process=self.process)
        self.mailbox=Mailbox(self.bus,clock=lambda:1_800_000_000.,monotonic=lambda:100.)

    def test_both_directions_require_real_capability_claim_and_correlated_reply(self):
        grok_cap,identity,issuance=self.runtime.issue_actor(self.bus,self.operator,self.repo,BINDING,binding_sha256='f'*64)
        grok=self.runtime.authenticate(self.bus,grok_cap,claimed_session=SESSION,invoking_cwd=self.repo)
        codex_identity=RuntimeIdentity.from_metadata({'id':'codex-thread','cwd':str(self.repo),'modelProvider':'openai'},{'codexHome':str(self.root/'codex')})
        cap,_=self.bus.issue_actor(codex_identity,self.repo,self.operator)
        codex=self.bus.authenticate(cap,codex_identity,invoking_cwd=self.repo)
        self.assertTrue(codex.namespace.startswith('codex:'))
        for sender,recipient,recipient_actor,key in ((codex,identity,grok,'to-grok'),(grok,codex_identity,codex,'to-codex')):
            original=self.mailbox.send(sender,recipient,body='bounded work',idempotency_key=key,delivery='inbox')['message']['message_id']
            with self.assertRaises(BusError):self.mailbox.ack(recipient_actor,original,outcome='completed')
            self.assertTrue(self.mailbox.ack(recipient_actor,original,outcome='accepted')['claimed'])
            self.assertFalse(self.mailbox.ack(recipient_actor,original,outcome='accepted')['claimed'])
            reply=self.mailbox.reply(recipient_actor,original,body='done',idempotency_key=key+'-reply',delivery='inbox')['message']
            self.assertEqual(self.mailbox.replies(sender,original)[0]['message_id'],reply['message_id'])
        with self.assertRaises(BusError):self.runtime.authenticate(self.bus,cap,claimed_session=SESSION,invoking_cwd=self.repo)
        with self.assertRaises(BusError):self.runtime.authenticate(self.bus,grok_cap,claimed_session='claimed-other',invoking_cwd=self.repo)
        self.process.descendant=False
        with self.assertRaises(BusError):self.runtime.authenticate(self.bus,grok_cap,invoking_cwd=self.repo)
        self.process.descendant=True;self.host.changed=True
        with self.assertRaises(BusError):self.runtime.authenticate(self.bus,grok_cap,invoking_cwd=self.repo)

    def test_terminal_notification_is_not_a_work_receipt_and_uncertainty_never_replays(self):
        from unittest.mock import patch
        from codex_wake.grok_terminal import GrokTerminalHost
        from codex_wake.a2a_delivery import NotificationDispatcher
        from codex_wake.a2a_scheduler import MailScheduler
        from codex_wake.records import WakeLifecycleLock
        import threading
        from codex_wake.runtime_a2a import bind_grok
        runtime_root=self.root/'wake';directory=runtime_root/'runtime-bindings';directory.mkdir(parents=True,mode=0o700)
        data=dict(Host().load_binding(BINDING),version=1,runtime='grok',allow_terminal_input=True,
                  socket=str(self.root/'terminal.sock'),pane='%1')
        file=directory/(BINDING+'.json');file.write_text(json.dumps(data));file.chmod(0o600)
        frame=f'Shell version: 1.0.40 [stable]\nSession ID: {SESSION}\nminimal · /help\n❯\nGrok 4.7 (high) · 27K / 256K (11%) · ctrl+o transcript\n'
        pasted=threading.Event()
        class Terminal(GrokTerminalHost):
            inputs=[]
            lost=False
            def snapshot(self,binding):return dict(binding,frame=self.frame)
            def refresh_identity(self,binding):pass
            def paste(self,binding,prompt,*,deadline=None):
                self.inputs.append(prompt);pasted.set()
                if self.lost:raise TimeoutError('lost terminal response')
                self.frame=frame.replace('minimal · /help',prompt+'\nminimal · /help')
        terminal=Terminal(runtime_root);terminal.frame=frame
        with patch('codex_wake.runtime_a2a.GrokTerminalHost',return_value=terminal),patch('codex_wake.runtime_a2a.ProcessContext',return_value=self.process),patch('codex_wake.service.user_state_dir',return_value=self.root/'state'):
            runtime=GrokMailboxRuntime(runtime_root)
            cap,identity,_=runtime.issue_actor(self.bus,self.operator,self.repo,BINDING)
            actor=runtime.authenticate(self.bus,cap,invoking_cwd=self.repo)
            sender_id=RuntimeIdentity('codex:fixture','sender',str(self.repo))
            sender_cap,_=self.bus.issue_actor(sender_id,self.repo,self.operator)
            sender=self.bus.authenticate(sender_cap,sender_id,invoking_cwd=self.repo)
            private=self.root/'dispatch';private.mkdir(mode=0o700);bindings=private/'bindings.json'
            bind_grok(self.bus,self.operator,bindings,runtime_root,BINDING)
            self.bus.set_paused(False,self.operator)
            scheduler=MailScheduler(self.mailbox,self.operator,lease_seconds=60)
            notification=NotificationDispatcher(scheduler,bindings)
            message=self.mailbox.send(sender,identity,body='private body is never pasted',idempotency_key='notify',delivery='notify')['message']['message_id']
            results=[]
            lock_key='grok-pane-'+data['socket']+':'+data['pane']
            with WakeLifecycleLock(self.root/'state'/'runtime-recipient-locks',lock_key):
                worker=threading.Thread(target=lambda:results.append(notification.tick()))
                worker.start()
                self.assertFalse(pasted.wait(.2),'A2A must share the ordinary wake pane lock')
            worker.join(3)
            self.assertFalse(worker.is_alive())
            result=results[0]
            self.assertEqual(result['submitted'],1)
            self.assertNotIn('private body',terminal.inputs[0])
            self.assertEqual(self.mailbox.show(sender,message)['state']['recipient'],'unread')
            self.assertEqual(notification.tick()['submitted'],0)
            self.assertEqual(len(terminal.inputs),1)
            self.assertTrue(self.mailbox.ack(actor,message,outcome='accepted')['claimed'])
            second=self.mailbox.send(sender,identity,body='second',idempotency_key='lost',delivery='notify')['message']['message_id']
            terminal.frame=frame;terminal.lost=True
            result=notification.tick()
            self.assertEqual(result['results'][0]['status'],'uncertain')
            restarted=NotificationDispatcher(MailScheduler(self.mailbox,self.operator,lease_seconds=60),bindings)
            self.assertEqual(restarted.tick()['submitted'],0)
            self.assertEqual(len(terminal.inputs),2)
            self.assertEqual(self.mailbox.show(sender,second)['state']['recipient'],'unread')

    def test_notification_context_latency_consumes_original_deadline(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from codex_wake.runtime_a2a import GrokNotificationBinding
        from codex_wake.runtime_delivery import RuntimeRecipient, RuntimeSubmission
        from test_measurements import observation
        clock=[1000]
        host=SimpleNamespace()
        recipient=RuntimeRecipient('grok',SESSION,dict(socket='/fixture.sock',pane='%1'))
        binding=GrokNotificationBinding('grok:'+'a'*64,SESSION,str(self.repo),str(self.root/'wake'),BINDING,'f'*64,123,42,'boot','generation')
        class Scheduler:
            lease_seconds=60
            def notification_context(unused,job,*,attempt_id):
                self.assertEqual(attempt_id,'original-attempt')
                clock[0]=4000
                return dict(dispatch_window_seconds=30)
        remaining=[]
        def submit(adapter,recipient,prompt):
            self.assertIs(adapter.deadline,host.deadline)
            remaining.append(adapter.deadline.remaining())
            self.assertIn('WAKE_RUNTIME_SUBMISSION_ID=',prompt)
            return RuntimeSubmission('not_sent',pre_io=True)
        with patch('codex_wake.measurements.snapshot',side_effect=lambda:observation(clock[0],rate=0)), patch.object(GrokNotificationBinding,'_recipient',return_value=(SimpleNamespace(host=host),recipient)), patch('codex_wake.grok_runtime.GrokRuntimeAdapter.submit',new=submit), patch('codex_wake.service.user_state_dir',return_value=self.root/'state'):
            result=binding.deliver({'attempt_id':'original-attempt'},{'message_id':'message'},self.bus.root,scheduler=Scheduler())
        self.assertEqual(result['status'],'unsent')
        self.assertGreater(remaining[0],24.99)
        self.assertLess(remaining[0],25)

    def test_cli_grok_actor_ignores_codex_claim_and_mcp_context_is_host_owned(self):
        from unittest.mock import patch
        import io,os
        from codex_wake.cli import main
        from codex_wake.mcp_server import CommandRunner
        cap,identity,_=self.runtime.issue_actor(self.bus,self.operator,self.repo,BINDING,binding_sha256='f'*64)
        with patch('codex_wake.runtime_a2a.GrokMailboxRuntime.from_actor',return_value=self.runtime),patch('pathlib.Path.cwd',return_value=self.repo),patch.dict(os.environ,{'CODEX_THREAD_ID':'unrelated-codex'}),patch('sys.stdout',new_callable=io.StringIO) as out:
            code=main(['messages','inbox','--actor-runtime','grok','--capability',str(cap),'--bus-root',str(self.bus.root),'--json'])
        self.assertEqual(code,0,out.getvalue())
        runner=CommandRunner(bus_root=self.bus.root,capability=cap,actor_runtime='grok',runtime_root=self.root/'wake')
        calls=[]
        runner._execute=lambda command,*args:(calls.append(command) or ({'fixture':True},False))
        args={'caller_thread_id':SESSION}
        value,failed=runner.call('wake_messages_inbox',args)
        self.assertFalse(failed)
        self.assertIn('--actor-runtime',calls[0]);self.assertIn('--caller-session-id',calls[0])
        for injected in ('actor_runtime','runtime_root','capability'):
            self.assertTrue(runner.call('wake_messages_inbox',{**args,injected:'spoof'})[1])
        self.assertEqual(len(calls),1)

    def test_operator_cli_issues_separate_grok_actor_with_real_audit_receipt(self):
        from unittest.mock import patch
        import io,hashlib
        from codex_wake.cli import main
        directory=self.runtime.root/'runtime-bindings';directory.mkdir(parents=True,mode=0o700)
        file=directory/(BINDING+'.json');file.write_text('{}');file.chmod(0o600)
        self.host.expected_digest=hashlib.sha256(file.read_bytes()).hexdigest()
        with patch('codex_wake.runtime_a2a.GrokMailboxRuntime',return_value=self.runtime),patch('sys.stdout',new_callable=io.StringIO) as out:
            code=main(['a2a','enroll',str(self.repo),'--thread','grok:'+BINDING,
                '--runtime-root',str(self.runtime.root),'--bus-root',str(self.bus.root),
                '--operator-capability',str(self.operator),'--notify','--json'])
        self.assertEqual(code,0,out.getvalue())
        value=json.loads(out.getvalue())
        self.assertTrue(value['namespace'].startswith('grok:'))
        self.assertTrue(value['actor_receipt_id'].startswith('receipt_'))
        self.assertEqual(value['native_caller_attestation'],'not_qualified')
        self.assertEqual(Path(value['actor_capability_file']).stat().st_mode&0o777,0o600)

    def test_grok_host_cannot_reuse_native_lifecycle_caller_grants(self):
        from codex_wake.mcp_server import CommandRunner
        calls=[]
        runner=CommandRunner(actor_runtime='grok',lifecycle_profiles=self.root/'profiles',wake_root=self.root/'wake')
        runner._execute=lambda *args:(calls.append(args) or ({'executed':True},False))
        value,failed=runner.call('wake_sessions_spawn',dict(profile='native-profile',intent='same-intent',name='worker',
            task='Synthetic',expires_at='2027-01-01T00:00:00Z',caller_thread_id=SESSION))
        self.assertTrue(failed)
        self.assertEqual(value['error']['code'],'native_caller_attestation_unavailable')
        self.assertEqual(calls,[])


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
