"""Public MCP renewal preserves a legacy explicit contract without live effects."""
import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from codex_wake.cli import run
from codex_wake.mcp_server import CommandRunner
from codex_wake.records import all_records
from codex_wake.session_permissions import PermissionStore,Principal
THREAD='11111111-1111-4111-8111-111111111111'
META=dict(threadId=THREAD,sessionId=THREAD,callId='fixture',**{'x-codex-turn-metadata':dict(thread_id=THREAD,session_id=THREAD,turn_id='fixture')})
CLOCK={'utc':{'status':'network','sources':['fixture-a','fixture-b'],'lower':2000000000,'upper':2000000000.1},'counter':None}
ROUTES=['existing_tab','background','new_tab']

class ExplicitPolicy(unittest.TestCase):
 def test_renew_legacy_key_and_create_successor_without_contract_migration(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);PermissionStore(root).configure({'version':1,'global':{'actions':{'wake.'+r:'allow' for r in ROUTES}}},Principal('fixture','operator'),expected_revision=0)
   argv=['--wake-root',d,'native','at','--json','--codex-path',sys.executable,'--wake-lifetime','persistent','--recipient-startup','create_load_run','--ttl','12h','--idempotency-key','legacy']
   for route in ROUTES:argv+=['--wake-route',route]
   argv += [THREAD,'2033-05-18T05:33:20Z','--','review fixture']
   with patch('codex_wake.native_clock.snapshot',return_value=CLOCK),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(run(argv,permission_principal=Principal(THREAD,'session',())),0)
   original=all_records(root)[0].record
   runner=CommandRunner(wake_root=root)
   body=dict(caller_thread_id=THREAD,trigger='2033-05-18T05:33:20Z',prompt='review fixture',idempotency_key='legacy',session_mode='explicit_policy',wake_lifetime='persistent',recipient_startup='create_load_run',routes=ROUTES,ttl='12h')
   with patch('codex_wake.native_clock.snapshot',return_value=CLOCK),patch('codex_wake.app_server.resolve_codex_cmd',return_value=sys.executable):
    value,failed=runner.call('wake_native_at',body,native_context=META)
    self.assertFalse(failed,value)
    self.assertEqual(len(all_records(root)),1);self.assertEqual(all_records(root)[0].record['target'],original['target'])
    self.assertEqual(all_records(root)[0].record['scheduling_intent']['fingerprint'],original['scheduling_intent']['fingerprint'])
    value,failed=runner.call('wake_native_at',{**body,'idempotency_key':'successor'},native_context=META)
    self.assertFalse(failed,value);self.assertEqual(len(all_records(root)),2)
    for item in all_records(root):
     self.assertEqual(item.record['wake_policy']['routes'],ROUTES);self.assertEqual(item.record['wake_policy']['lifetime'],'persistent');self.assertNotIn('session_mode',item.record['target'])
 def test_incomplete_explicit_policy_never_registers(self):
  for missing in ('wake_lifetime','recipient_startup','routes'):
   with self.subTest(missing=missing),tempfile.TemporaryDirectory() as d:
    body=dict(caller_thread_id=THREAD,trigger='1h',prompt='fixture',idempotency_key='incomplete',session_mode='explicit_policy',wake_lifetime='persistent',recipient_startup='create_load_run',routes=ROUTES);body.pop(missing)
    value,failed=CommandRunner(wake_root=Path(d)).call('wake_native_after',body,native_context=META)
    self.assertTrue(failed);self.assertFalse(all_records(Path(d)))
 def test_explicit_policy_does_not_bypass_route_denial(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);PermissionStore(root).configure({'version':1,'global':{'actions':{'wake.new_tab':'deny'}}},Principal('fixture','operator'),expected_revision=0)
   body=dict(caller_thread_id=THREAD,trigger='1h',prompt='fixture',idempotency_key='denied',session_mode='explicit_policy',wake_lifetime='persistent',recipient_startup='create_load_run',routes=ROUTES)
   with patch('codex_wake.native_clock.snapshot',return_value=CLOCK),patch('codex_wake.app_server.resolve_codex_cmd',return_value=sys.executable):
    value,failed=CommandRunner(wake_root=root).call('wake_native_after',body,native_context=META)
   self.assertTrue(failed);self.assertFalse(all_records(root))
 def test_explicit_policy_cannot_remove_existing_session_lifecycle(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);runner=CommandRunner(wake_root=root)
   body=dict(caller_thread_id=THREAD,trigger='1h',prompt='fixture',idempotency_key='bound',session_mode='background',wake_lifetime='persistent',recipient_startup='background_saved')
   with patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}),patch('codex_wake.native_clock.snapshot',return_value=CLOCK),patch('codex_wake.app_server.resolve_codex_cmd',return_value=sys.executable):
    value,failed=runner.call('wake_native_after',body,native_context=META);self.assertFalse(failed,value)
    before=all_records(root)[0].record
    value,failed=runner.call('wake_native_after',{**body,'session_mode':'explicit_policy','routes':['background']},native_context=META)
    self.assertTrue(failed);self.assertEqual(all_records(root)[0].record,before)
