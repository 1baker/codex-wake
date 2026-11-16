"""Shared MCP refresh through the public lifecycle CLI and separate watcher."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest

from codex_wake.cli import run


THREAD = '00000000-0000-7000-8000-000000000168'


class SharedRefreshTests(unittest.TestCase):
    def test_refresh_configuration_does_not_require_or_create_an_objective_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            policy = base / 'profiles.json'
            policy.write_text(json.dumps(dict(version=1, callers={THREAD: ['self']}, profiles={
                'self': dict(refresh_mode='shared_mcp_idle', scope_approval='explicit user approval',
                             cwd=tmp, app_server='unix:///missing.sock', codex_path='/bin/true',
                             timeout=1, resources={'wake': dict(kind='skill', path='/missing',
                                 description='Wake', sha256='a'*64)})})))
            policy.chmod(0o600)
            output = StringIO()
            with redirect_stdout(output):
                code = run(['--wake-root', str(base/'runtime'), 'sessions', 'configuration',
                    '--profiles', str(policy), '--profile', 'self', '--thread-id', THREAD,
                    '--caller-thread-id', THREAD, '--json'])
            self.assertEqual(code, 0, output.getvalue())
            value = json.loads(output.getvalue())
            self.assertEqual(value['refresh_scope'], 'shared_server_mcp')
            self.assertTrue(value['idle_required'])
            self.assertEqual(value['resources'], ['wake'])
            self.assertEqual(value['operations'], ['configuration', 'refresh'])
            self.assertFalse((base/'runtime'/'objective-ledgers').exists())

    def test_legacy_profile_revocation_fences_adopted_pending_refresh(self):
        self.shared_scenario(common_policy=True,revoke_legacy=True)

    def test_common_permissions_revocation_blocks_queued_controller_effects(self):
        self.shared_scenario(common_policy=True,revoke_common=True)

    def test_common_permissions_survive_independent_refresh_controller(self):
        self.shared_scenario(common_policy=True)

    def test_active_self_request_waits_then_reloads_once_with_same_goals(self):
        self.shared_scenario()

    def test_native_observation_timeout_preserves_queued_intent_until_its_deadline(self):
        self.shared_scenario(observation_timeout=True)

    def test_lost_reload_response_is_verified_without_replaying_the_reload(self):
        self.shared_scenario(lost_reload=True)

    def test_peer_activity_also_prevents_shared_reload(self):
        self.shared_scenario(peer_busy=True)

    def test_peer_that_becomes_active_during_preflight_prevents_reload(self):
        self.shared_scenario(racing_peer=True)

    def test_stale_resource_expires_without_retrying_reload(self):
        self.shared_scenario(stale_mcp=True)

    def test_counter_reset_after_reload_holds_completion(self):
        self.shared_scenario(reset_counter=True)

    def test_controller_shutdown_during_preflight_never_starts_reload(self):
        self.shared_scenario(stop_during_preflight=True)

    def test_source_workspace_mismatch_blocks_before_shared_reload(self):
        self.shared_scenario(cwd_mismatch=True)

    def shared_scenario(self, lost_reload=False, peer_busy=False, racing_peer=False,
                        stale_mcp=False, reset_counter=False, stop_during_preflight=False,
                        cwd_mismatch=False, observation_timeout=False, common_policy=False, revoke_common=False, revoke_legacy=False):
        import hashlib
        import subprocess
        import sys
        import threading
        import time
        from unittest.mock import patch
        from websockets.sync.server import unix_serve
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = base/'runtime'
            runtime.mkdir(mode=0o700)
            skill = base/'SKILL.md'; skill.write_text('new skill')
            checkpoint = base/'checkpoint.json'
            checkpoint.write_text(json.dumps(dict(source_thread_id=THREAD,
                objective='Continue same work', authority='user approved shared refresh',
                next_packet='Read refreshed tools', pending_obligations=[])))
            native = dict(active=not peer_busy, peer_active=peer_busy, reloaded=False, raced=False)
            peer='00000000-0000-7000-8000-000000000169'
            requests=[]
            goal=dict(threadId=THREAD,objective='Retain work',createdAt=1,status='paused',
                      tokenBudget=100,tokensUsed=40,timeUsedSeconds=20,updatedAt=1)
            def serve(ws):
                for message in ws:
                    r=json.loads(message);method=r['method'];params=r.get('params');requests.append(method)
                    if 'id' not in r:continue
                    if method=='initialize':result={}
                    elif method=='thread/loaded/list':result=dict(data=[THREAD,peer],nextCursor=None)
                    elif method=='thread/read':
                        if observation_timeout and not native.get('timeout_observed'):
                            native['timeout_observed']=True
                            time.sleep(1.2)  # Exceed the1s RPC cap, well before the2030 intent deadline.
                        result=dict(thread=dict(id=params['threadId'],cwd='/' if cwd_mismatch and params['threadId']==THREAD else tmp,
                            status=dict(type='active' if native['active' if params['threadId']==THREAD else 'peer_active'] else 'idle',activeFlags=[])))
                    elif method=='thread/goal/get':
                        if stop_during_preflight and not native.get('stop_sent'):
                            native['stop_sent']=True;watcher.terminate()
                        if racing_peer and not native['raced']:
                            native['peer_active']=True;native['raced']=True
                        result=dict(goal=dict(goal,threadId=params['threadId'],
                            tokensUsed=0 if reset_counter and native['reloaded'] else 40))
                    elif method=='config/mcpServer/reload':
                        self.assertIsNone(params);native['reloaded']=True;result={}
                        if lost_reload:
                            ws.close();return
                    elif method=='skills/list':result=dict(data=[dict(cwd=tmp,errors=[],skills=[dict(
                        path=str(skill),enabled=True,description='new skill')])])
                    elif method=='mcpServer/tool/call':result=dict(isError=False,content=[dict(type='text',
                        text='v2' if native['reloaded'] and not stale_mcp else 'v1')])
                    else:raise AssertionError(method)
                    try:ws.send(json.dumps(dict(id=r['id'],result=result)))
                    except Exception:return  # The fixed expiry may close an owned fixture request.
            socket=base/'native.sock'
            server=unix_serve(serve,path=str(socket));threading.Thread(target=server.serve_forever,daemon=True).start()
            policy=base/'profiles.json'
            policy.write_text(json.dumps(dict(version=1,callers={THREAD:['self']},profiles={'self':dict(
                refresh_mode='shared_mcp_idle',scope_approval='user approved shared reload after idle check',
                cwd=tmp,app_server='unix://'+str(socket),codex_path='/bin/true',timeout=1,
                resources={'skill':dict(kind='skill',path=str(skill),description='new skill',
                    sha256=hashlib.sha256(skill.read_bytes()).hexdigest()),
                    'mcp':dict(kind='mcp',server='toy',tool='version',arguments={},read_only=True,
                        expected_content=[dict(type='text',text='v2')])})})))
            policy.chmod(0o600)
            from datetime import datetime, timezone
            wall_anchor, elapsed_anchor = time.time(), time.monotonic()
            expiry=datetime.fromtimestamp(wall_anchor+2,timezone.utc).isoformat() if stale_mcp else '2030-01-01T00:00:00Z'
            argv=['--wake-root',str(runtime),'sessions','refresh','--profiles',str(policy),
                '--profile','self','--intent','self-refresh','--thread-id',THREAD,
                '--caller-thread-id',THREAD,'--checkpoint','checkpoint.json','--checkpoint-sha256',
                hashlib.sha256(checkpoint.read_bytes()).hexdigest(),'--resource','skill','--resource','mcp',
                '--expires-at',expiry,'--json']
            if common_policy:
                from codex_wake.session_permissions import PermissionStore,Principal
                PermissionStore(runtime).configure({'version':1,'approvals':[
                    dict(id='shared-approval',action='refresh.shared',subject=THREAD,scope='standing',issuer='operator',target='shared-server')]},Principal('op','operator'),expected_revision=0)
                saved=json.loads(policy.read_text());saved['callers']={};policy.write_text(json.dumps(saved));policy.chmod(0o600)
                from codex_wake.a2a_bus import BusStore
                bus,operator_capability=BusStore.configure(base/'bus')
                argv+=['--bus-root',str(bus.root),'--operator-capability',str(operator_capability)]
            def invoke():
                output=StringIO()
                # Keep this injected authority continuous when guest UTC steps;
                # the independent watcher still enforces the original expiry.
                with patch('codex_wake.lifecycle_budget.trusted_upper',return_value=wall_anchor+time.monotonic()-elapsed_anchor),redirect_stdout(output):
                    code=run(argv)
                return code,json.loads(output.getvalue())
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
            watcher=subprocess.Popen([sys.executable,'-m','codex_wake','--wake-root',str(runtime),
                'sessions','refresh-watch','--interval','0.05'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+5
                while True:
                    try:
                        code,receipt=invoke()
                        if code != 2:break
                        if time.monotonic()>=deadline:self.fail(receipt)
                        time.sleep(.05)
                    except Exception as exc:
                        if time.monotonic()>=deadline:raise
                        time.sleep(.05)
                self.assertEqual(code,0)
                self.assertEqual(receipt['state'],'queued')
                time.sleep(.15)
                self.assertNotIn('config/mcpServer/reload',requests)
                if revoke_common or revoke_legacy:
                    if revoke_common:
                        PermissionStore(runtime).configure({'version':1,'mandatory':['refresh.shared']},Principal('op','operator'),expected_revision=1)
                    else:
                        data=json.loads(policy.read_text());data['callers'][THREAD]=[];policy.write_text(json.dumps(data));policy.chmod(0o600)
                    while time.monotonic()<deadline:
                        files=list((runtime/'shared-refresh').glob('*.json'))
                        saved=next((json.loads(f.read_text()) for f in files if 'fingerprint' in json.loads(f.read_text())),{})
                        if saved.get('state')=='blocked':break
                        time.sleep(.02)
                    self.assertEqual(saved['state'],'blocked',saved)
                    self.assertEqual(saved['reason'],'permission_revoked' if revoke_common else 'permission_legacy_profile_denied')
                    self.assertNotIn('config/mcpServer/reload',requests)
                    self.assertNotIn('thread/goal/set',requests)
                    return
                native['active']=False
                native['peer_active']=False
                if racing_peer:
                    while not native['raced'] and time.monotonic()<deadline:time.sleep(.02)
                    time.sleep(.15)
                    self.assertNotIn('config/mcpServer/reload',requests)
                    native['peer_active']=False
                if stop_during_preflight:
                    watcher.wait(timeout=3)
                    self.assertNotIn('config/mcpServer/reload',requests)
                    return
                while time.monotonic()<deadline:
                    code,receipt=invoke()
                    if receipt['state'] in ('completed','expired','blocked'):break
                    time.sleep(.05)
                if cwd_mismatch:
                    self.assertEqual(code,5,receipt)
                    self.assertEqual(receipt['state'],'blocked')
                    self.assertEqual(receipt['reason'],'source_workspace_mismatch')
                    self.assertNotIn('config/mcpServer/reload',requests)
                    return
                if stale_mcp or reset_counter:
                    self.assertEqual(code,5,receipt)
                    self.assertEqual(receipt['state'],'expired' if stale_mcp else 'blocked')
                    self.assertEqual(requests.count('config/mcpServer/reload'),1)
                    self.assertNotIn('thread/goal/set',requests)
                    return
                self.assertEqual(code,0,receipt)
                self.assertEqual(receipt['state'],'completed')
                self.assertEqual(receipt['expires_at'],expiry)
                self.assertEqual(receipt['refresh_scope'],'shared_server_mcp')
                self.assertEqual(requests.count('config/mcpServer/reload'),1)
                self.assertEqual(receipt['goal_before'],goal)
                self.assertEqual(receipt['goal_after'],goal)
                self.assertNotIn('thread/goal/set',requests)
                self.assertNotIn('turn/start',requests)
                self.assertNotIn('turn/interrupt',requests)
                invoke()
                self.assertEqual(requests.count('config/mcpServer/reload'),1)
            finally:
                watcher.terminate();watcher.wait(timeout=5)
                if watcher.stderr:watcher.stderr.close()
                server.shutdown()

    def test_missing_independent_monitor_returns_a_structured_setup_refusal(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            checkpoint=base/'checkpoint.json'
            checkpoint.write_text(json.dumps(dict(source_thread_id=THREAD,objective='Keep work',
                authority='user approval',next_packet='Refresh',pending_obligations=[])))
            policy=base/'profiles.json'
            policy.write_text(json.dumps(dict(version=1,callers={THREAD:['self']},profiles={'self':dict(
                refresh_mode='shared_mcp_idle',scope_approval='user explicit approval',cwd=tmp,
                app_server='unix:///missing.sock',codex_path='/bin/true',timeout=1,
                resources={'skill':dict(kind='skill',path=str(checkpoint),description='Skill',sha256='a'*64)})})))
            policy.chmod(0o600)
            output=StringIO()
            with redirect_stdout(output):
                code=run(['--wake-root',tmp,'sessions','refresh','--profiles',str(policy),
                    '--profile','self','--intent','missing-watch','--thread-id',THREAD,
                    '--caller-thread-id',THREAD,'--checkpoint','checkpoint.json','--checkpoint-sha256',
                    hashlib.sha256(checkpoint.read_bytes()).hexdigest(),'--resource','skill',
                    '--expires-at','2030-01-01T00:00:00Z','--json'])
            self.assertEqual(code,2)
            value=json.loads(output.getvalue())
            self.assertEqual(value['error']['code'],'shared_refresh_unavailable')
            self.assertIn('independent',value['error']['message'])
            self.assertNotIn('reconciliation_required',value)
