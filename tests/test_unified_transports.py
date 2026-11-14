"""Canonical API/MCP/CLI callers retain one program and wake across reconnects."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from codex_wake.controller_auth import OAuthAuthority
from codex_wake.controller_http import ControllerHTTPServer
from codex_wake.controller_operations import ControllerOperations
from codex_wake.controller_tabs import ControllerTabs
from codex_wake.managed_inventory import ManagedInventory
from test_recurring_schedules import request

class UnifiedTransportTests(unittest.TestCase):
    def test_connector_keeps_original_program_and_schedule_handles_across_transports(self):
        from test_unified_connectors import ConnectorTests
        with tempfile.TemporaryDirectory() as d,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            root=Path(d);host=socket.gethostname();environment=os.environ.get('WSL_DISTRO_NAME') or os.name
            auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            token=ConnectorTests().token(auth,['observe','control','content.observe'],[dict(host=host,environment=environment)])
            token_file=root/'token';token_file.write_text(token);token_file.chmod(0o600)
            tabs=ControllerTabs(root,workspaces={},host=host,environment=environment)
            tabs.execute('tabs.session.create',{'name':'dev tabs'})
            tabs.execute('tabs.session.create',{'name':'codex-bots'})
            tabs.execute('tabs.family.register',{'bot_id':'parent','name':'Parent'})
            tabs.execute('tabs.family.register',{'bot_id':'child','name':'Child','parent_bot_id':'parent'})
            operations=ControllerOperations(ManagedInventory(root),host=host,environment=environment,tabs=tabs)
            server=ControllerHTTPServer(('127.0.0.1',0),auth,operations)
            owner=threading.Thread(target=server.serve_forever,daemon=True);owner.start()
            endpoint='http://127.0.0.1:'+str(server.server_port)
            def call(operation,args,*,mcp=False):
                body=dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='wake_'+operation.replace('.','_'),arguments=args)) if mcp else dict(operation=operation,arguments=args)
                req=Request(endpoint+('/mcp' if mcp else '/operations'),data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
                with urlopen(req,timeout=10) as response:value=json.load(response)
                return value['result']['structuredContent'] if mcp else value
            try:
                view=call('environment.snapshot',{})['result']
                self.assertEqual({s['name'] for s in view['sessions']},{'dev tabs','codex-bots'})
                self.assertEqual(next(a for a in view['agents'] if a['bot_id']=='child')['parent_bot_id'],'parent')
                schedule=call('wakes.schedules.register',{'request':request()},mcp=True)['result']
                definition=dict(id='connector-journey',version=1,entry='read',nodes=[dict(id='read',type='call',operation='wakes.schedules.show',arguments={'schedule_id':schedule['id']},next='done'),dict(id='done',type='end',value={'ref':'steps.read.result.id'})])
                call('programs.definitions.publish',{'definition':definition})
                run=call('programs.runs.start',dict(flow_id='connector-journey',version=1,inputs={},intent='one',binding='connector'),mcp=True)['result']
                completed=call('programs.runs.advance',{'run_id':run['run_id']})['result']
                self.assertEqual((completed['phase'],completed['result']),('completed',schedule['id']))
                # A fresh CLI process reconnects through MCP without repeating start/register.
                args=[sys.executable,'-m','codex_wake.cli','controller','remote','--endpoint',endpoint,'--token-file',str(token_file),'--transport','mcp','programs.runs.show','--arguments',json.dumps({'run_id':run['run_id']})]
                result=subprocess.run(args,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(json.loads(result.stdout)['result']['run_id'],run['run_id'])
                same=call('wakes.schedules.register',{'request':request()})['result']
                self.assertEqual(same['id'],schedule['id'])
            finally:
                server.shutdown();server.server_close();owner.join(timeout=5)
