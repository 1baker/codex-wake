"""Current-thread refresh at public admission and independent controller seams."""
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.session_permissions import PermissionStore, Principal

THREAD='00000000-0000-7000-8000-000000000318'
PEER='00000000-0000-7000-8000-000000000319'


class ScopedRefreshTests(unittest.TestCase):
    def test_selected_refresh_leaves_active_peer_untouched_and_verifies_version(self):
        self.scenario()

    def test_unsupported_native_scope_never_queues_or_falls_back(self):
        self.scenario(unsupported=True)

    def test_lost_admission_response_reconciles_without_replaying(self):
        self.scenario(lost=True)

    def test_stale_resource_expires_without_claiming_refresh_completion(self):
        self.scenario(stale=True)

    def test_goal_counter_regression_blocks_completion(self):
        self.scenario(reset=True)

    def test_missing_thread_ownership_never_queues(self):
        self.scenario(wrong_cwd=True)

    def test_active_goal_stays_active_without_reset_or_explicit_resume(self):
        self.scenario(goal_active=True)

    def scenario(self, unsupported=False, lost=False, stale=False, reset=False, wrong_cwd=False, goal_active=False):
        from websockets.sync.server import unix_serve
        from codex_wake.a2a_bus import BusStore
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'wake';root.mkdir(mode=0o700)
            PermissionStore(root).configure({'version':1},Principal('op','operator'),expected_revision=0)
            bus,capability=BusStore.configure(base/'bus')
            checkpoint=base/'checkpoint.json'
            checkpoint.write_text(json.dumps(dict(source_thread_id=THREAD,objective='Same goal',
                authority='user',next_packet='Continue',pending_obligations=[])))
            calls=[];state={'reloaded':False}
            goal=dict(threadId=THREAD,objective='Same goal',createdAt=1,status='active' if goal_active else 'paused',
                tokenBudget=100,tokensUsed=40,timeUsedSeconds=20,updatedAt=1)
            def dispatch(ws):
                for message in ws:
                    request=json.loads(message)
                    if 'id' not in request:continue
                    method=request['method'];params=request.get('params');calls.append((method,params))
                    if method=='initialize':value={}
                    elif method=='thread/mcpServer/reload':
                        if unsupported or wrong_cwd:
                            ws.send(json.dumps(dict(id=request['id'],error=dict(code=-32601,message='unsupported'))));continue
                        self.assertEqual(params['threadId'],THREAD)
                        if not params.get('dryRun'):
                            state['reloaded']=True
                            if lost:ws.close();return
                        value=dict(threadId=THREAD,queued=not params.get('dryRun',False))
                    elif method=='thread/read':
                        value=dict(thread=dict(id=params['threadId'],cwd='/' if wrong_cwd else tmp,
                            status=dict(type='active' if params['threadId']==PEER else 'idle',activeFlags=[])))
                    elif method=='thread/goal/get':value=dict(goal=dict(goal,tokensUsed=0) if reset and state['reloaded'] else goal)
                    elif method=='mcpServerStatus/list':
                        self.assertTrue(params.get('runtimeOnly'))
                        value=dict(data=[dict(name='toy',
                        serverInfo=dict(version='v2' if state['reloaded'] and not stale else 'v1'),
                        tools={'version':dict(inputSchema=dict(properties={}))})],nextCursor=None)
                    elif method=='mcpServer/tool/call':value=dict(content=[dict(type='text',text='v2' if state['reloaded'] and not stale else 'v1')],isError=False)
                    else:raise AssertionError(method)
                    ws.send(json.dumps(dict(id=request['id'],result=value)))
            def serve(ws):
                from websockets.exceptions import ConnectionClosed
                try:dispatch(ws)
                except ConnectionClosed:pass  # The bounded client closes at expiry.
            sock=base/'native.sock';server=unix_serve(serve,path=str(sock))
            threading.Thread(target=server.serve_forever,daemon=True).start()
            profile=base/'profiles.json';profile.write_text(json.dumps(dict(version=1,callers={},profiles={'self':dict(
                refresh_mode='thread_mcp_idle',scope_approval='selected thread only',cwd=tmp,
                app_server='unix://'+str(sock),codex_path='/bin/true',timeout=1,
                resources={'toy':dict(kind='mcp_catalog',server='toy',version='v2',tools={'version':[]})})})));profile.chmod(0o600)
            from datetime import datetime, timezone
            if stale:
                from tests.test_shared_refresh import refresh_fixture_clock, REFRESH_CLOCK_BOOTSTRAP
                fixture_clock = base / 'explicit-utc-fixture'
                fixture_clock.write_text('1000')
                clock = patch('codex_wake.measurements.snapshot',
                              side_effect=lambda: refresh_fixture_clock(fixture_clock))
                clock.start()
                self.addCleanup(clock.stop)
            expiry=datetime.fromtimestamp(1003 if stale else time.time()+15,timezone.utc).isoformat()
            common=['--wake-root',str(root),'sessions']
            identity=['--profiles',str(profile),'--profile','self','--thread-id',THREAD,
                '--caller-thread-id',THREAD,'--scope','current_connection','--bus-root',str(bus.root),
                '--operator-capability',str(capability),'--json']
            def invoke(operation):
                output=StringIO()
                args=common+[operation]+identity
                if operation=='refresh':args+=['--intent','owned-scope','--checkpoint','checkpoint.json',
                    '--checkpoint-sha256',hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                    '--resource','toy','--expires-at',expiry]
                with patch('codex_wake.lifecycle_budget.trusted_upper',
                        side_effect=lambda: float(fixture_clock.read_text()) if stale else time.time()),redirect_stdout(output):
                    code=run(args)
                return code,json.loads(output.getvalue())
            watcher=None
            try:
                code,config=invoke('configuration')
                self.assertEqual(code,0,config)
                self.assertEqual(config['capability'],'unsupported' if unsupported or wrong_cwd else 'supported',config)
                self.assertEqual(config['native_scope'],'thread_mcp_connections')
                self.assertFalse(state['reloaded'])
                if unsupported or wrong_cwd:
                    code,value=invoke('refresh');self.assertNotEqual(code,0,value)
                    self.assertFalse((root/'shared-refresh').exists());return
                env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
                watch_args=['--wake-root',str(root),'sessions','refresh-watch','--interval','0.05']
                watch_command=([sys.executable,'-c',REFRESH_CLOCK_BOOTSTRAP,
                    str(Path(__file__).resolve().parents[1]),str(fixture_clock),*watch_args]
                    if stale else [sys.executable,'-m','codex_wake',*watch_args])
                watcher=subprocess.Popen(watch_command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    heartbeat=root/'shared-refresh/controller.json'
                    if heartbeat.exists() and json.loads(heartbeat.read_text()).get('active'):break
                    time.sleep(.02)
                code,value=invoke('refresh');self.assertEqual(code,0,value)
                while time.monotonic()<deadline:
                    code,value=invoke('refresh')
                    if stale and state['reloaded'] and value.get('resource_status'):
                        fixture_clock.write_text('1004')
                    if value.get('state') in ('completed','expired','blocked'):break
                    time.sleep(.03)
                self.assertEqual(value['state'],'expired' if stale else 'blocked' if reset else 'completed',value)
                self.assertEqual(value['refresh_scope'],'current_connection')
                self.assertEqual(value['expires_at'],expiry)
                effects=[params for method,params in calls if method=='thread/mcpServer/reload' and not params.get('dryRun')]
                self.assertEqual(effects,[dict(threadId=THREAD)])
                self.assertNotIn('config/mcpServer/reload',[method for method,_ in calls])
                self.assertNotIn('thread/goal/set',[method for method,_ in calls])
                self.assertFalse(any(params and params.get('threadId')==PEER for _,params in calls))
                if not stale and not reset:
                    self.assertEqual(value['goal_before'],goal)
                    self.assertEqual(value['goal_after'],goal)
            finally:
                if watcher:
                    watcher.terminate();watcher.wait(timeout=5);watcher.stderr.close()
                server.shutdown()
