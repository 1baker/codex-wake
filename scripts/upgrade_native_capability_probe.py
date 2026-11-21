#!/usr/bin/env python3
"""Owned native missing-custom-output/accounting probe; local scripted SSE only.

This proves the historical orphan_output capability's repaired *missing output*
case. An output without a matching call remains a separate debug-assert boundary.
Authenticated test-account homes are never used by this probe.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex',type=Path,required=True)
    parser.add_argument('--models',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,required=True)
    args=parser.parse_args()
    root=args.artifacts.resolve();root.mkdir(parents=True,mode=0o700,exist_ok=False)
    home=root/'home';home.mkdir(mode=0o700)
    binary=args.codex.resolve(strict=True)
    requests=[]
    class LocalOnly(BaseHTTPRequestHandler):
        def log_message(self,*unused):pass
        def do_POST(self):
            if len(requests)>=4:self.send_error(429);return
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            events=[{'type':'response.created','response':{'id':'qualification-response'}},
                {'type':'response.output_item.done','item':{'type':'message','id':'qualification-message','role':'assistant','content':[{'type':'output_text','text':'LOCAL FIXTURE COMPLETED'}]}},
                {'type':'response.completed','response':{'id':'qualification-response','usage':{'input_tokens':11,'input_tokens_details':{'cached_tokens':2},'output_tokens':4,'total_tokens':15}}}]
            for event in events:self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
    server=ThreadingHTTPServer(('127.0.0.1',0),LocalOnly)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    model=json.loads(args.models.read_text())['models'][0]
    (home/'models.json').write_text(json.dumps({'models':[model]}))
    (home/'config.toml').write_text(f'''model={json.dumps(model['slug'])}
model_provider="upgrade_local"
model_catalog_json={json.dumps(str(home/'models.json'))}
check_for_update_on_startup=false
approval_policy="never"
[analytics]
enabled=false
[model_providers.upgrade_local]
name="Owned scripted local fixture, no model inference"
base_url="http://127.0.0.1:{server.server_port}/v1"
wire_api="responses"
requires_openai_auth=false
supports_websockets=false
request_max_retries=0
stream_max_retries=0
[projects.{json.dumps(str(root))}]
trust_level="trusted"
''')
    env={key:value for key,value in os.environ.items() if key in ('PATH','LANG','LC_ALL')}
    env.update(HOME=str(home),CODEX_HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'),XDG_DATA_HOME=str(home/'.local/share'))
    log=(root/'native.log').open('wb')
    process=subprocess.Popen([str(binary),'app-server'],cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,start_new_session=True)
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    pending=b'';frames=[];counter=0;deadline=time.monotonic()+60
    report=dict(schema_version=1,status='failed',model_requests=0,external_provider_requests=0,
        scripted_provider_requests=0,checks={},owned_processes_remaining=[],native_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        orphan_output_scope='missing custom_tool_call output synthesized as aborted; raw orphan output without matching call not qualified')
    def receive():
        nonlocal pending
        while True:
            if b'\n' in pending:
                line,pending=pending.split(b'\n',1);frame=json.loads(line);frames.append(frame);return frame
            if time.monotonic()>=deadline:raise TimeoutError('owned native capability probe deadline exhausted')
            if not selector.select(.1):
                if process.poll() is not None:raise RuntimeError('owned native app-server exited')
                continue
            chunk=os.read(process.stdout.fileno(),65536)
            if not chunk:raise RuntimeError('owned native app-server closed connection')
            pending+=chunk
            if len(pending)>1024*1024:raise RuntimeError('native response exceeds limit')
    def rpc(method,params):
        nonlocal counter
        counter+=1;identifier=counter
        process.stdin.write((json.dumps({'id':identifier,'method':method,'params':params})+'\n').encode());process.stdin.flush()
        while True:
            frame=receive()
            if frame.get('id')==identifier:
                if 'error' in frame:raise RuntimeError('native request rejected '+method+': '+json.dumps(frame['error']))
                return frame['result']
    try:
        rpc('initialize',{'clientInfo':{'name':'upgrade_native_qualification','version':'1'},'capabilities':{'experimentalApi':True}})
        process.stdin.write(b'{"method":"initialized"}\n');process.stdin.flush()
        raw_id=str(uuid4())
        history=[{'type':'message','role':'user','content':[{'type':'input_text','text':'Synthetic prior user request for missing-output regression.'}]},
            {'type':'custom_tool_call','call_id':'dangling-custom-call','name':'qualification_tool','input':'synthetic'}]
        resumed=rpc('thread/resume',{'threadId':raw_id,'history':history,'cwd':str(root)})
        thread=resumed['thread']['id']
        started=rpc('turn/start',{'threadId':thread,'input':[{'type':'text','text':'Complete the bounded local qualification fixture.'}]})
        turn=started['turn']['id'];completed=None
        while completed is None:
            frame=receive()
            if frame.get('method')=='turn/completed' and frame.get('params',{}).get('turn',{}).get('id')==turn:completed=frame['params']['turn']
        if completed.get('status')!='completed':raise RuntimeError('synthetic normalization turn did not complete: '+str(completed.get('status')))
        actual=rpc('thread/read',{'threadId':thread,'includeTurns':True})['thread']
        payloads=[body for body in requests if any(item.get('type')=='custom_tool_call' and item.get('call_id')=='dangling-custom-call' for item in body.get('input',[]) if isinstance(item,dict))]
        if not payloads:raise AssertionError('no actual normalized dangling-call input reached scripted provider')
        if not all(any(item.get('type')=='custom_tool_call_output' and item.get('call_id')=='dangling-custom-call' and item.get('output')=='aborted' for item in body.get('input',[]) if isinstance(item,dict)) for body in payloads):
            raise AssertionError('missing custom-call output was not synthesized as aborted')
        tokens=[frame['params']['tokenUsage'] for frame in frames if frame.get('method')=='thread/tokenUsage/updated' and frame.get('params',{}).get('threadId')==thread]
        if not tokens:raise AssertionError('native thread usage notification missing')
        last=tokens[-1]['last']
        if not (last.get('inputTokens')==11 and last.get('cachedInputTokens')==2 and last.get('outputTokens')==4):raise AssertionError('native usage differs from independently scripted11/2/4 counts')
        recorded=next(item for item in actual['turns'] if item['id']==turn)
        if recorded.get('rootTurnId')!=turn:raise AssertionError('native usage turn lost root-turn attribution')
        peer=rpc('thread/start',{'cwd':str(root),'ephemeral':False})['thread']['id']
        event='qualification-notice-'+uuid4().hex
        text='Owned durable no-model notice for qualification. [External supervision event '+event+']'
        appended=rpc('thread/notice/append',{'threadId':thread,'eventId':event,'text':text})
        duplicate=rpc('thread/notice/append',{'threadId':thread,'eventId':event,'text':text})
        if appended.get('recorded') is not True or duplicate.get('recorded') is not True or appended.get('alreadyRecorded') is not False or duplicate.get('alreadyRecorded') is not True:
            raise AssertionError('notice append was not idempotent')
        if rpc('thread/notice/read',{'threadId':peer,'eventId':event}).get('notice') is not None:
            raise AssertionError('notice leaked to peer thread')
        selector.unregister(process.stdout)
        os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=2)
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.stdin.close();process.stdout.close()
        process=subprocess.Popen([str(binary),'app-server'],cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,start_new_session=True)
        selector.register(process.stdout,selectors.EVENT_READ);pending=b''
        rpc('initialize',{'clientInfo':{'name':'upgrade_native_qualification_cold','version':'1'},'capabilities':{'experimentalApi':True}})
        process.stdin.write(b'{"method":"initialized"}\n');process.stdin.flush()
        cold=rpc('thread/resume',{'threadId':thread})['thread']
        notice=rpc('thread/notice/read',{'threadId':thread,'eventId':event})
        if cold['id']!=thread or notice.get('notice')!={'eventId':event,'text':text} or notice.get('modelContextAvailable') is not True:
            raise AssertionError('durable notice missing after cold native restart')
        if len(requests)!=1:raise AssertionError('notice or cold restart started an additional scripted model turn')
        report.update(status='passed',checks={'orphan_output':True,'caller_accounting':True,'durable_notices':True},
            notice_scope='idempotent append, peer isolation and model-readable context after cold native restart',
            accounting_scope='native thread usage11input/2cached/4output and stable rootTurnId; MCP caller identity requires scoped reload probe',
            thread_id=thread,turn_id=turn,usage=last,scripted_provider_requests=len(requests))
    except Exception as error:report.update(reason=type(error).__name__+': '+str(error),scripted_provider_requests=len(requests))
    finally:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait()
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        selector.close();process.stdin.close();process.stdout.close();log.close();server.shutdown();server.server_close()
        (root/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
        (root/'frames.json').write_text(json.dumps(frames,indent=2)+'\n')
    print(json.dumps(report,sort_keys=True));return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
