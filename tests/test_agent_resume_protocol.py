"""Real Unix protocol and private attachment evidence at both public callers."""
import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

from websockets.sync.server import unix_serve
from codex_wake.a2a_bus import BusStore
from codex_wake.a2a_identity import RuntimeIdentity
from codex_wake.agent_resume import SavedRuntime
from codex_wake.agent_resume_commands import mcp_call, register_parser, run
from codex_wake.managed_inventory import ManagedInventory, Observation
from codex_wake.process import process_identity
from codex_wake.session_permissions import PermissionStore, Principal
from tests.test_agent_resume import THREAD, NOW


class ResumeProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'wake';self.home=self.base/'home';self.home.mkdir()
        self.thread=dict(id=THREAD,cwd=str(self.base),modelProvider='openai')
        self.metadata=dict(codexHome=str(self.home));self.methods=[];self.commands=[]
        self.namespace=RuntimeIdentity.from_metadata(self.thread,self.metadata).namespace
        self.current=False;self.lost=False;self.missing=False;self.revoke=False
        self.binding_file=self.base/'attachment.json'
        self.identity=dict(process_identity(os.getpid()),pid=os.getpid())
        self.binding_file.write_text(json.dumps(self.identity));self.binding_file.chmod(0o600)
        def handler(ws):
            for raw in ws:
                message=json.loads(raw)
                if 'id' not in message:continue
                method=message['method'];self.methods.append(method)
                if method=='initialize':result=self.metadata
                elif method=='thread/read':
                    if self.missing:
                        ws.send(json.dumps(dict(id=message['id'],error={'code':-1,'message':'not accessible'})));continue
                    result={'thread':self.thread}
                else:raise AssertionError('unexpected native effect '+method)
                ws.send(json.dumps(dict(id=message['id'],result=result)))
        self.socket=self.base/'native.sock';self.server=unix_serve(handler,str(self.socket))
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.addCleanup(self.stop)
        self.config={'version':1,'profiles':{'saved':dict(cwd=str(self.base),codex_home=str(self.home),
            codex_path=sys.executable,app_server='unix://'+str(self.socket),tmux_session='fixture',timeout=1)},
            'callers':{THREAD:['saved']}}
        self.profiles=self.base/'profiles.json'
        self.save_profiles()
        self.inv=ManagedInventory(self.root,now=lambda:NOW)
        # Recovery must replace an ended generation, never the live test caller.
        prior = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            self.binding_file.write_text(json.dumps(dict(process_identity(prior.pid), pid=prior.pid)))
            baseline=self.sample(True)
            self.agent=self.inv.enroll(baseline)['agent']
        finally:
            prior.terminate(); prior.wait(timeout=5)
            self.binding_file.write_text(json.dumps(self.identity))
        self.config['recovery_callers']={'local-operator':[self.agent['managed_agent_id']]};self.save_profiles()
        PermissionStore(self.root).configure({'version':1,'global':{'actions':{'resume.recover':'allow'}}},Principal('op','operator'),expected_revision=0)
        self.arguments=dict(managed_agent_id=self.agent['managed_agent_id'],profile='saved',intent='protocol',
            expires_at='2027-01-16T09:00:00+00:00',caller_thread_id=THREAD)
        self.runtime=SavedRuntime(binding_source=lambda record,profile:self.sample(self.current),terminal=self.terminal)
        self.runner=SimpleNamespace(wake_root=self.root,lifecycle_profiles=self.profiles)
        self.context=dict(threadId=THREAD,sessionId=THREAD,callId='fixture',**{
            'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='turn')})
    def enroll_ended_generation(self, *, inventory=None):
        """A detached attachment must name an ended process, never this runner."""
        prior = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            self.binding_file.write_text(json.dumps(dict(process_identity(prior.pid), pid=prior.pid)))
            self.agent = (inventory or self.inv).enroll(self.sample(True), operator=True)['agent']
        finally:
            prior.terminate(); prior.wait(timeout=5)
            self.binding_file.write_text(json.dumps(self.identity))
        return self.agent

    def stop(self):
        self.server.shutdown();self.worker.join(timeout=2)
    def save_profiles(self):self.profiles.write_text(json.dumps(self.config));self.profiles.chmod(0o600)
    def sample(self,current):
        stored=json.loads(self.binding_file.read_text())
        fresh=dict(process_identity(stored['pid']),pid=stored['pid'])
        ready=current and fresh==stored
        return Observation('codex',self.namespace,THREAD,str(self.base),'ready' if ready else 'unavailable',
            NOW,'native_metadata',dict(pid=stored['pid'],start_ticks=stored['start_time_ticks'],boot_id=stored['boot_id']) if ready else None,
            [dict(pane_id='%7',window_id='@4')] if ready else [],{'inspect':'supported'})
    def terminal(self,args,*command):
        if self.revoke and command[0]=='new-window':
            PermissionStore(self.root).configure({'version':1,'mandatory':['resume.self','resume.recover']},Principal('op','operator'),expected_revision=1)
        args.effect_guard()
        self.commands.append(command)
        if command[0]=='new-window':
            self.current=True
            if self.lost:raise OSError('lost after attachment created')
            return '@4\t%7'
        return ''
    def mcp(self):return mcp_call(self.runner,self.arguments,self.context,runtime=self.runtime,now=lambda:NOW)
    def test_mcp_real_protocol_launch_and_reconstructed_owner_exact_identity(self):
        original=self.root/'objective-ledgers';original.mkdir();ledger=original/'prior.json';ledger.write_bytes(b'{"used":93,"deadline":1800000010,"unknown":true}')
        pending=self.root/'pending';pending.mkdir();work=pending/'uncertain.json';work.write_bytes(b'{"status":"uncertain"}')
        result=self.mcp();self.assertEqual(result['status'],'resumed',result)
        self.assertEqual(self.mcp()['managed_agent_id'],self.agent['managed_agent_id'])
        self.assertEqual(len([c for c in self.commands if c[0]=='new-window']),1)
        argv=shlex.split(self.commands[-1][-1]);self.assertIn(THREAD,argv);self.assertIn('resume',argv)
        self.assertIn('CODEX_HOME='+str(self.home),argv)
        self.assertEqual(ledger.read_bytes(),b'{"used":93,"deadline":1800000010,"unknown":true}')
        self.assertEqual(work.read_bytes(),b'{"status":"uncertain"}')
        self.assertEqual(set(self.methods),{'initialize','thread/read'})
    def cli(self):
        bus,cap=BusStore.configure(self.base/'bus')
        parser=argparse.ArgumentParser();register_parser(parser.add_subparsers(dest='command'))
        args=parser.parse_args(['resume','--managed-agent-id',self.agent['managed_agent_id'],'--profile','saved',
            '--intent','operator','--expires-at',self.arguments['expires_at'],'--profiles',str(self.profiles),
            '--bus-root',str(bus.root),'--operator-capability',str(cap),'--json'])
        out=StringIO()
        with redirect_stdout(out):status=run(args,self.root,runtime=self.runtime,now=lambda:NOW)
        return status,json.loads(out.getvalue())
    def test_cli_real_operator_capability_and_same_protocol(self):
        status,result=self.cli()
        self.assertEqual(status,0,result);self.assertEqual(result['status'],'resumed')
    def test_operator_recovery_revocation_prevents_launch(self):
        self.revoke=True
        status,result=self.cli()
        self.assertEqual(status,2,result)
        self.assertFalse(any(c[0]=='new-window' for c in self.commands))
        self.assertEqual(result['status'],'uncertain')
    def test_forged_native_caller_cannot_resume(self):
        self.context['threadId']='foreign'
        self.assertEqual(self.mcp()['status'],'held');self.assertEqual(self.commands,[])
    def test_missing_history_or_namespace_change_never_launches(self):
        self.missing=True
        self.assertEqual(self.mcp()['status'],'held');self.assertEqual(self.commands,[])
        self.missing=False;self.metadata['codexHome']=str(self.base/'different-home')
        self.assertEqual(self.mcp()['reason'],'resume_identity_changed');self.assertEqual(self.commands,[])
    def test_lost_launch_and_changed_intent_are_fenced_until_exact_reconciliation(self):
        self.lost=True
        self.assertEqual(self.mcp()['status'],'uncertain')
        self.arguments['intent']='other'
        self.assertEqual(self.mcp()['error']['code'],'resume_original_intent_required')
        self.arguments['intent']='protocol'
        self.assertEqual(self.mcp()['status'],'resumed')
        self.assertEqual(len([c for c in self.commands if c[0]=='new-window']),1)
    def test_revoked_policy_immediately_before_effect_leaves_unknown_and_no_launch(self):
        self.revoke=True
        self.assertEqual(self.mcp()['status'],'uncertain')
        self.assertFalse(any(c[0]=='new-window' for c in self.commands))
        self.assertEqual(self.mcp()['error']['code'],'permission_deny')
