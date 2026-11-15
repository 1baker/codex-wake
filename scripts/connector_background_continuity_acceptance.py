#!/usr/bin/env python3
"""Opt-in real OAuth/MCP continuation after closing one disposable Codex tab."""
import asyncio
import argparse
import base64
import hashlib
import json
from pathlib import Path
import secrets
import shlex
import subprocess
import tempfile
import time

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from codex_wake.controller_auth import OAuthAuthority
from codex_wake.local_sessions import discover
from codex_wake.shared_app_server import SharedAppServerReader, locate_shared_endpoint


def decode(result):
    value=getattr(result,'structured_content',None)
    return value if value is not None else json.loads(next(c.text for c in result.content if c.type=='text'))


async def main(options):
    directory=Path.home()/'.local/state/codex-wake/connector-background-continuity'
    output=options.receipt or directory/('result-'+secrets.token_hex(8)+'.json')
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    # Reserve custody before discovery, connection, or any native effect. Only
    # this invocation may update its checkpoints; prior receipts stay intact.
    with output.open('x'):
        pass
    output.chmod(0o600)
    config=json.loads((Path.home()/'.config/codex-wake/external-connector.json').read_text())
    root=Path(config['wake_root']);issuer=config['issuer'];endpoint=locate_shared_endpoint(timeout=10)
    authority=OAuthAuthority(root/'external-oauth/authority.sqlite',issuer=issuer,resource=issuer+'/mcp')
    grant=None;thread=None;tmux=None;tui_pid=None
    receipt=dict(ticket=666,status='running',boundary='deployed HTTPS OAuth/MCP',receipt_path=str(output))
    from websockets.sync.client import unix_connect
    connection_context=unix_connect(endpoint[7:],open_timeout=10,close_timeout=1,compression=None,max_size=32*1024*1024)
    connection=connection_context.__enter__()
    sequence=0
    def native(method,args):
        nonlocal sequence
        sequence+=1;identifier=sequence;connection.send(json.dumps(dict(id=identifier,method=method,params=args)))
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            response=json.loads(connection.recv(timeout=max(.01,deadline-time.monotonic())))
            if response.get('id')!=identifier:continue
            if 'error' in response:
                receipt.setdefault('native_errors',[]).append(dict(method=method,error=response['error']))
                raise RuntimeError(json.dumps(response['error']))
            return response['result']
        raise TimeoutError(method+' observation deadline')
    def save():
        output.write_text(json.dumps(receipt,indent=2));output.chmod(0o600)
    native('initialize',dict(clientInfo=dict(name='cw666_continuity',version='1'),capabilities=dict(experimentalApi=True)))
    connection.send(json.dumps(dict(method='initialized')))
    try:
        scratch=Path('/home/ecochran76/workspace.local/codex-wake/.scratch');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cw666-',dir=scratch) as temporary:
            cwd=Path(temporary);socket=str(output.parent/'tmux.sock')
            tmux=['tmux','-S',socket]
            if options.reuse_owned_thread:
                owned=json.loads((output.parent/'owned-threads.json').read_text())
                assert options.reuse_owned_thread in owned,'reuse requires a privately recorded owned preparation thread'
                thread=options.reuse_owned_thread;receipt['thread_id']=thread;save()
                native('thread/unarchive',dict(threadId=thread))
                resumed=native('thread/resume',dict(threadId=thread))['thread']
                assert resumed['id']==thread and resumed.get('name')=='CW666-background-continuity'
                cwd=Path(resumed['cwd']);receipt['preparation']='reused exact owned seeded conversation'
            else:
                thread=native('thread/start',dict(cwd=str(cwd),ephemeral=False,approvalPolicy='never',sandbox='read-only'))['thread']['id']
                receipt['thread_id']=thread;save()
                manifest=output.parent/'owned-threads.json'
                owned=json.loads(manifest.read_text()) if manifest.exists() else []
                if thread not in owned:owned.append(thread)
                manifest.write_text(json.dumps(owned));manifest.chmod(0o600)
                native('thread/name/set',dict(threadId=thread,name='CW666-background-continuity'))
                native('turn/start',dict(threadId=thread,input=[dict(type='text',text='Reply exactly setup-ready. Do not use tools.')]))
            deadline=time.monotonic()+120;metadata=None
            while time.monotonic()<deadline:
                try:metadata=native('thread/read',dict(threadId=thread,includeTurns=False))['thread']
                except (RuntimeError,TimeoutError):
                    save();await asyncio.sleep(1);continue
                if metadata.get('status',{}).get('type')=='idle':break
                await asyncio.sleep(1)
            assert metadata is not None and metadata.get('status',{}).get('type')=='idle','same owned setup did not become ready within observation bound'
            target=discover(root,endpoint,thread_id=thread)['sessions'][0]['target']
            executable=target['executable']
            command=shlex.join(['env','-u','CODEX_THREAD_ID','-u','CODEX_SESSION_ID','-u','TMUX_PANE',executable,'resume','--remote',endpoint,'--no-alt-screen','-C',str(cwd),thread])
            subprocess.run(tmux+['new-session','-d','-s','cw666','-n','continuity','-c',str(cwd),'sleep 600'],check=True,capture_output=True,text=True)
            subprocess.run(tmux+['set-option','-w','-t','cw666:continuity','remain-on-exit','on'],check=True,capture_output=True)
            subprocess.run(tmux+['respawn-pane','-k','-t','cw666:continuity',command],check=True,capture_output=True)
            deadline=time.monotonic()+90;attached=None
            while time.monotonic()<deadline:
                screen=subprocess.run(tmux+['capture-pane','-p','-t','cw666:continuity'],capture_output=True,text=True).stdout
                if 'trust this' in screen.lower():raise AssertionError('pretrusted cwd unexpectedly requires trust; no global trust change authorized')
                rows=discover(root,endpoint,socket_path=socket,thread_id=thread)['sessions']
                if len(rows)==1 and rows[0]['attachments']:
                    attached=rows[0];break
                screen=subprocess.run(tmux+['capture-pane','-p','-t','cw666:continuity'],capture_output=True,text=True).stdout
                if 'Do you trust' in screen or 'trust this' in screen.lower():raise AssertionError('unexpected trust dialog')
                await asyncio.sleep(1)
            if attached is None:
                receipt['owned_tui_screen']=screen[-1600:]
            assert attached is not None,'owned TUI did not establish exact native attachment'
            tui_pid=attached['attachments'][0]['client_pid'];receipt['live_tab_before']=True
            receipt['tui_pid']=tui_pid
            saved=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
            assert saved['id']==thread and saved.get('turns'),'exact saved conversation has no persisted preparation history'
            receipt['saved_before_close']=True
            subprocess.run(tmux+['kill-window','-t','cw666:continuity'],check=True,capture_output=True)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline and Path('/proc',str(tui_pid)).exists():await asyncio.sleep(.2)
            assert not Path('/proc',str(tui_pid)).exists(),'owned TUI survived tab closure'
            assert subprocess.run(tmux+['has-session','-t','cw666'],capture_output=True).returncode!=0
            receipt['live_tab_after']=False;receipt['tui_process_after']='exited'
            saved=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
            with SharedAppServerReader(endpoint,timeout=60) as reader:loaded=reader.loaded_threads(selected_thread_id=thread)
            assert saved['id']==thread and saved.get('turns'),'saved identity/history lost after closure'
            assert len(loaded)==1 and loaded[0]['id']==thread,'same native runtime is not available for background continuation'
            receipt['saved_after_close']=True;receipt['native_loaded_after_close']=True
            redirect=config['redirect_uris'][0];verifier=secrets.token_urlsafe(48)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            async with httpx.AsyncClient(timeout=70) as http:
                response=await http.post(issuer+'/register',json=dict(client_name='cw666-background-continuity',redirect_uris=[redirect]));response.raise_for_status();client=response.json()['client_id']
                code=authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client,redirect_uri=redirect,resource=issuer+'/mcp',scopes=['observe','content.observe','control'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread)],code_challenge=challenge)
                response=await http.post(issuer+'/token',data=dict(grant_type='authorization_code',client_id=client,code=code,redirect_uri=redirect,code_verifier=verifier,resource=issuer+'/mcp'));response.raise_for_status();token=response.json()['access_token'];grant=authority.authenticate(token).grant_id
                async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=70) as transport:
                    async with streamable_http_client(issuer+'/mcp',http_client=transport) as streams:
                        async with ClientSession(streams[0],streams[1]) as session:
                            await session.initialize()
                            args=dict(selector='thread:'+thread,prompt='Reply exactly BACKGROUND_CONTINUITY_CONFIRMED. Do not use tools.',policy='reject',idempotency_key='cw666-'+secrets.token_hex(8),expected_target=target)
                            result=decode(await session.call_tool('wake_environment_conversations_input_submit',args))
                            assert result['status']=='completed',result
                            operation=result['result']['operation'];identifier=operation['operation_id'];receipt['operation_id']=identifier
                            deadline=time.monotonic()+120
                            while time.monotonic()<deadline:
                                operation=decode(await session.call_tool('wake_environment_conversations_input_result',dict(operation_id=identifier)))['result']['operation']
                                if operation['phase']=='terminal':break
                                await asyncio.sleep(1)
                            assert operation['execution']=='completed',operation
                            assert operation['answer']['text'].strip()=='BACKGROUND_CONTINUITY_CONFIRMED',operation
                            assert operation['target']['conversation_id']==thread
                            assert subprocess.run(tmux+['has-session','-t','cw666'],capture_output=True).returncode!=0,'background input recreated visible tab'
                            receipt.update(status='passed',execution=operation['execution'],answer=operation['answer']['text'],same_conversation=True,visible_tab_created=False)
    finally:
        try:
            if tmux:subprocess.run(tmux+['kill-server'],capture_output=True)
            if thread:native('thread/archive',dict(threadId=thread));receipt['owned_thread']='archived'
        finally:
            try:
                if grant:authority.revoke_grant(grant);receipt['temporary_grant']='revoked'
            finally:
                if receipt['status']=='running':receipt['status']='failed'
                save();connection_context.__exit__(None,None,None);print(json.dumps(receipt))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--reuse-owned-thread')
    parser.add_argument('--receipt',type=Path,help='Fresh per-run receipt; existing paths are refused')
    asyncio.run(main(parser.parse_args()))
