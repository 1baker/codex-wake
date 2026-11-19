"""Frozen permission routes through public registration and independent dispatch."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from codex_wake.a2a_bus import BusStore
from codex_wake.cli import run
from codex_wake.daemon import poll_once
from codex_wake.injector import dispatch_firing_record
from codex_wake.records import all_records, classify_record
from codex_wake.runtime_delivery import RuntimeCapability, RuntimeObservation, RuntimeRecipient, RuntimeSubmission, RuntimeReconciliation
from codex_wake.session_permissions import PermissionStore, Principal

THREAD='00000000-0000-7000-8000-000000000324'
CLOCK={'utc':{'status':'network','sources':['a','b'],'lower':1800000000,'upper':1800000000},'counter':{'epoch':'wake-route-fixture','counter':1000,'frequency':1000,'rate_ppm':0}}
DUE={'utc':{'status':'network','sources':['a','b'],'lower':1800000061,'upper':1800000061},'counter':dict(CLOCK['counter'],counter=62000)}


class RouteAdapter:
    def __init__(self,first='not_sent'):
        self.first=first;self.submits=[];self.observed=[];self.reconciles=0;self.targets=[];self.reconciled_routes=[]
    def resolve(self,target):
        self.targets.append(target['thread_id']);return RuntimeRecipient('codex',target['thread_id'],target)
    def observe(self,recipient):
        route=recipient.binding.get('wake_route');self.observed.append(route)
        return RuntimeObservation('ready','fixture',{'submit':RuntimeCapability('supported','fixture'),
            'active_tab':RuntimeCapability('supported','fixture exact attachment')})
    def submit_bounded(self,recipient,prompt,envelope):
        route=recipient.binding.get('wake_route');self.submits.append(route)
        if route=='existing_tab' and self.first=='not_sent':
            return RuntimeSubmission('not_sent',reason='definite unavailable before I/O',pre_io=True)
        if route=='existing_tab' and self.first=='uncertain':return RuntimeSubmission('uncertain',reason='lost response')
        return RuntimeSubmission('accepted',receipt_id=str(uuid4()),evidence_kind='native_queue_acceptance')
    def reconcile_bounded(self,recipient,prompt,envelope):
        self.reconciles+=1;self.reconciled_routes.append(recipient.binding.get('wake_route'));return RuntimeReconciliation(reason='no accepted evidence yet')


class WakeRoutePermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bus,self.capability=BusStore.configure(self.root/'bus')
        PermissionStore(self.root).configure({'version':1},Principal('op','operator'),expected_revision=0)
    def register(self,*options,key='routes',thread=THREAD):
        argv=['--wake-root',str(self.root),'native','after','--json','--codex-path',sys.executable,
            '--bus-root',str(self.bus.root),'--operator-capability',str(self.capability),
            '--idempotency-key',key,*options,thread,'1m','--','Continue approved work']
        with patch('codex_wake.native_clock.snapshot',return_value=CLOCK),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(argv),0)
        return next(x.record for x in all_records(self.root) if x.record['scheduling_intent']['idempotency_key']==key)
    def fire(self,adapter):
        with patch('codex_wake.native_clock.snapshot',return_value=DUE):
            poll_once(self.root,dispatch=False)
            found=next(x for x in all_records(self.root) if x.record['scheduling_intent']['idempotency_key']=='routes')
            return dispatch_firing_record(self.root,found,runtime_adapter=adapter)
    def test_public_registration_freezes_order_and_provenance(self):
        original=self.register('--wake-route','existing_tab','--wake-route','background')
        self.assertEqual(original['wake_policy']['routes'],['existing_tab','background'])
        self.assertEqual(original['wake_policy']['version'],2)
        self.assertEqual(original['wake_policy']['permission_context']['revision'],1)
        PermissionStore(self.root).configure({'version':1,'global':{'actions':{'wake.new_tab':'deny'}}},Principal('op','operator'),expected_revision=1)
        self.assertEqual(self.register(),original)
        with self.assertRaises(Exception):self.register('--wake-route','background','--wake-route','existing_tab')
        mutated=json.loads(json.dumps(original));mutated['wake_policy']['routes'].reverse()
        self.assertEqual(classify_record(mutated),'hold')
    def test_definite_pre_io_failure_can_fall_back_without_changing_recipient(self):
        self.register('--wake-route','existing_tab','--wake-route','background')
        adapter=RouteAdapter();self.fire(adapter)
        self.assertEqual(adapter.submits,['existing_tab','background'])
        saved=all_records(self.root)[0].record
        self.assertEqual(saved['status'],'firing')
        self.assertEqual(saved['target']['thread_id'],THREAD)
        self.assertEqual(saved['native_delivery']['route'],'background')
    def test_uncertain_submission_is_reconciled_without_fallback(self):
        self.register('--wake-route','existing_tab','--wake-route','background')
        adapter=RouteAdapter('uncertain');self.fire(adapter);self.fire(adapter)
        self.assertEqual(adapter.submits,['existing_tab'])
        self.assertEqual(adapter.reconciles,1)
        self.assertEqual(adapter.reconciled_routes,['existing_tab'])
        self.assertEqual(all_records(self.root)[0].record['native_delivery']['state'],'uncertain')

    def test_revocation_in_an_independent_dispatcher_blocks_new_effects(self):
        self.register('--wake-route','background')
        PermissionStore(self.root).configure({'version':1,'mandatory':['wake.background']},Principal('op','operator'),expected_revision=1)
        child=r'''
import json,sys
from pathlib import Path
from unittest.mock import patch
from codex_wake.daemon import poll_once
from codex_wake.injector import dispatch_firing_record
from codex_wake.records import all_records
from codex_wake.runtime_delivery import RuntimeRecipient,RuntimeObservation,RuntimeCapability,RuntimeSubmission
root=Path(sys.argv[1])
class Adapter:
 def resolve(self,target):return RuntimeRecipient('codex',target['thread_id'],target)
 def observe(self,recipient):return RuntimeObservation('ready','fixture',{'submit':RuntimeCapability('supported','fixture')})
 def submit_bounded(self,recipient,prompt,envelope):
  (root/'UNEXPECTED_EFFECT').write_text('submitted')
  raise AssertionError('revoked route submitted')
clock={'utc':None,'counter':{'epoch':'wake-route-fixture','counter':62000,'frequency':1000,'rate_ppm':0}}
with patch('codex_wake.native_clock.snapshot',return_value=clock):
 poll_once(root,dispatch=False)
 result=dispatch_firing_record(root,all_records(root)[0],runtime_adapter=Adapter())
print(json.dumps({'result':result.status,'record':all_records(root)[0].record}))
'''
        result=subprocess.run([sys.executable,'-c',child,str(self.root)],env=dict(os.environ,
            PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')),capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(value['record']['status'],'pending')
        self.assertEqual(value['record']['attempts'],0)
        self.assertFalse((self.root/'UNEXPECTED_EFFECT').exists())
        self.assertEqual(value['record']['wake_policy']['routes'],['background'])
        self.assertEqual(value['record']['scheduling_intent']['counter_anchor'],CLOCK['counter'])

    def test_unsupported_new_tab_never_submits_or_uses_an_unlisted_route(self):
        self.register('--wake-route','new_tab')
        adapter=RouteAdapter('accepted');self.fire(adapter)
        self.assertEqual(adapter.submits,[])
        self.assertEqual(all_records(self.root)[0].record['attempts'],0)
        self.assertEqual(all_records(self.root)[0].record['status'],'pending')
        self.assertIn('new_tab:unsupported',all_records(self.root)[0].record['policy_outcome']['routes'])

    def test_route_revocation_after_first_pre_io_attempt_prevents_second(self):
        self.register('--wake-route','existing_tab','--wake-route','background')
        store=PermissionStore(self.root)
        class Revoking(RouteAdapter):
            def submit_bounded(inner,recipient,prompt,envelope):
                outcome=super().submit_bounded(recipient,prompt,envelope)
                store.configure({'version':1,'mandatory':['wake.background']},Principal('op','operator'),expected_revision=1)
                return outcome
        adapter=Revoking();self.fire(adapter)
        self.assertEqual(adapter.submits,['existing_tab'])
        record=all_records(self.root)[0].record
        self.assertEqual(record['status'],'pending')
        self.assertNotIn('native_delivery',record)
        self.assertEqual(record['wake_route_progress']['next'],1)

    def test_public_native_mcp_uses_host_identity_and_retains_route_selection(self):
        from codex_wake.mcp_server import CommandRunner
        runner=CommandRunner(wake_root=self.root)
        meta=dict(threadId=THREAD,sessionId=THREAD,callId='wake-call',**{
            'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='wake-turn')})
        arguments=dict(caller_thread_id=THREAD,trigger='1m',prompt='Continue approved work',
            idempotency_key='native-mcp', session_mode='background',routes=['existing_tab','background'])
        with patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}), patch('codex_wake.native_clock.snapshot',return_value=CLOCK), patch('codex_wake.app_server.resolve_codex_cmd',return_value=sys.executable):
            value,failed=runner.call('wake_native_after',arguments,native_context=meta)
        self.assertFalse(failed,value)
        self.assertEqual(value['wake_policy']['routes'],['existing_tab','background'])
        self.assertEqual(value['wake_policy']['permission_context']['subject'],THREAD)
        rejected,failed=runner.call('wake_native_after',dict(arguments,idempotency_key='spoofed'),native_context={})
        self.assertTrue(failed,rejected)
        self.assertEqual(len(all_records(self.root)),1)

    def test_unproven_non_submission_never_unlocks_fallback(self):
        self.register('--wake-route','existing_tab','--wake-route','background')
        class Unproven(RouteAdapter):
            def submit_bounded(inner,recipient,prompt,envelope):
                inner.submits.append(recipient.binding['wake_route'])
                return RuntimeSubmission('not_sent',reason='no conclusive pre-I/O proof',pre_io=False)
        adapter=Unproven();self.fire(adapter)
        self.assertEqual(adapter.submits,['existing_tab'])
        self.assertEqual(all_records(self.root)[0].record['native_delivery']['state'],'uncertain')

    def test_task_owned_route_retires_on_verified_completion(self):
        from codex_wake.wake_policy import complete_owner
        original=self.register('--wake-route','background','--wake-lifetime','task','--owner-id','task')
        complete_owner(self.root,{'kind':'task','id':'task'},'completed',actor='operator:fixture')
        self.assertEqual(all_records(self.root)[0].record['status'],'cancelled')
        self.assertEqual(all_records(self.root)[0].record['scheduling_intent'],original['scheduling_intent'])

    def test_fallback_does_not_touch_another_due_conversation(self):
        peer='00000000-0000-7000-8000-000000000325'
        self.register('--wake-route','existing_tab','--wake-route','background')
        self.register('--wake-route','background',key='peer',thread=peer)
        adapter=RouteAdapter()
        with patch('codex_wake.native_clock.snapshot',return_value=DUE):
            poll_once(self.root,dispatch=False)
            peer_before=next(x.record for x in all_records(self.root) if x.record['target']['thread_id']==peer)
            target=next(x for x in all_records(self.root) if x.record['target']['thread_id']==THREAD)
            dispatch_firing_record(self.root,target,runtime_adapter=adapter)
        self.assertEqual(adapter.targets,[THREAD,THREAD])
        self.assertEqual(next(x.record for x in all_records(self.root) if x.record['target']['thread_id']==peer),peer_before)

    def test_operator_grok_route_is_fenced_and_uncertainty_does_not_replay(self):
        from codex_wake.time_provider import TimeDecision
        from test_grok_runtime import FRAME,SESSION
        class Host:
            inputs=0
            def load_binding(inner,*args):
                return dict(start_ticks=42,boot_id='boot',pid=123,session_id=SESSION,
                    executable_sha256='a'*64,allow_terminal_input=True,allow_terminal_fallback=True)
            def snapshot(inner,binding):return dict(binding,frame=FRAME)
            def refresh_identity(inner,binding):pass
            def paste(inner,binding,prompt,*,deadline=None):
                inner.inputs+=1;raise OSError('outcome may have reached exact TUI')
        host=Host();clock=dict(utc=dict(status='network',sources=['one','two'],lower=1800000000,upper=1800000000.1),counter=dict(CLOCK['counter'],epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6'),reason='authenticated_utc',valid_for_ns=1000000000)
        argv=['--wake-root',str(self.root),'grok','after','--ttl','2m','--json',
            '--bus-root',str(self.bus.root),'--operator-capability',str(self.capability),
            '--wake-route','existing_tab','--idempotency-key','grok-route','grok_'+'a'*32,'1s','--','Synthetic task']
        with patch('codex_wake.runtime_wakes.GrokTerminalHost',return_value=host),patch(
                'codex_wake.runtime_wakes.binding_digest',return_value='b'*64),patch(
                'codex_wake.service.user_state_dir',return_value=self.root/'shared-locks'),patch(
                'codex_wake.native_clock.snapshot',return_value=clock),patch('codex_wake.measurements.snapshot',return_value=clock),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(argv),0)
            original=all_records(self.root)[0].record
            self.assertEqual(original['wake_policy']['routes'],['existing_tab'])
            due=lambda:TimeDecision('network',('one','two'),1800000002,1800000002.1)
            poll_once(self.root,time_provider=due)
            PermissionStore(self.root).configure({'version':1,'mandatory':['wake.existing_tab']},Principal('op','operator'),expected_revision=1)
            poll_once(self.root,time_provider=due)
        self.assertEqual(host.inputs,1)
        self.assertEqual(all_records(self.root)[0].record['runtime_delivery']['state'],'uncertain')
        self.assertEqual(all_records(self.root)[0].record['target'],original['target'])
