#!/usr/bin/env python3
"""Opt-in deployed connector session-only lifecycle acceptance on one disposable thread.

Run with the installed connector Python. Secrets stay in process memory; only a
credential-free receipt is retained. No operator conversation is addressed.
"""
import argparse
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time
import subprocess
import shlex
from datetime import datetime, timezone, timedelta

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from codex_wake.controller_auth import OAuthAuthority
from codex_wake.local_sessions import discover
from codex_wake.shared_app_server import locate_shared_endpoint


def decode(result):
    if getattr(result,'structured_content',None) is not None:return result.structured_content
    return json.loads(next(c.text for c in result.content if c.type=='text'))


async def main(reuse_thread=None):
    config=json.loads((Path.home()/'.config/codex-wake/external-connector.json').read_text())
    root=Path(config['wake_root']);issuer=config['issuer'];endpoint=locate_shared_endpoint(timeout=10)
    authority=OAuthAuthority(root/'external-oauth/authority.sqlite',issuer=issuer,resource=issuer+'/mcp')
    import os
    os.umask(0o077)
    output=Path.home()/'.local/state/codex-wake/connector-acceptance-spec'/('session-only-'+secrets.token_hex(4)+'.json')
    grant=None;thread=None;created_tmux=False;attach_pid=None;pty_master=None;receipt=dict(ticket=667,status='running',boundary='deployed HTTPS OAuth/MCP')
    from websockets.sync.client import unix_connect
    connection=unix_connect(endpoint[7:],open_timeout=10,close_timeout=1,compression=None,max_size=32*1024*1024)
    sequence=0
    def native(method,args):
        nonlocal sequence
        sequence+=1;identifier=sequence
        connection.send(json.dumps(dict(id=identifier,method=method,params=args)))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            value=json.loads(connection.recv(timeout=max(.01,deadline-time.monotonic())))
            if value.get('id')!=identifier:continue
            if 'error' in value:
                receipt.setdefault('native_errors',[]).append(dict(method=method,error=value['error']))
                raise RuntimeError('native request refused: '+method+' '+json.dumps(value['error']))
            return value['result']
        raise TimeoutError('native request deadline: '+method)
    native('initialize',dict(clientInfo=dict(name='cw667_lifecycle_acceptance',version='1'),capabilities=dict(experimentalApi=True)))
    connection.send(json.dumps(dict(method='initialized')))

    try:
        scratch=Path('/home/ecochran76/workspace.local/codex-wake/.scratch');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cw667-',dir=scratch) as cwd:
            if reuse_thread:
                thread=reuse_thread
                native('thread/unarchive',dict(threadId=thread))
                resumed=native('thread/resume',dict(threadId=thread))['thread']
                cwd=resumed['cwd']
                assert resumed.get('name')=='cw667-session-only' and Path(cwd).parent==scratch and Path(cwd).name.startswith('cw667-'),'prior owned disposable required'
                Path(cwd).mkdir(parents=True,exist_ok=True)
            else:
                thread=native('thread/start',dict(cwd=cwd,approvalPolicy='never',sandbox='read-only'))['thread']['id']
                native('turn/start',dict(threadId=thread,input=[dict(type='text',text='Reply exactly setup-ready. Do not use tools.')]))
            receipt['thread_id']=thread
            deadline=time.monotonic()+120
            metadata={}
            while time.monotonic()<deadline:
                try:
                    metadata=native('thread/read',dict(threadId=thread,includeTurns=False))['thread']
                except Exception as error:
                    receipt.setdefault('setup_read_errors',[]).append(type(error).__name__)
                    await asyncio.sleep(1)
                    continue
                if metadata.get('status',{}).get('type')=='idle':break
                await asyncio.sleep(1)
            assert metadata.get('status',{}).get('type')=='idle','setup turn did not finish'
            receipt['setup_turn']='completed separate native preparation'
            native('thread/name/set',dict(threadId=thread,name='cw667-session-only'))
            selected=discover(root,endpoint,thread_id=thread)['sessions']
            assert len(selected)==1, 'exact disposable thread discovery required'
            target=selected[0]['target']
            tmux_name='cw667-session-only'
            assert subprocess.run(['tmux','has-session','-t',tmux_name],capture_output=True).returncode!=0,'owned session name already exists'
            receipt['sessions_before']=subprocess.check_output(['tmux','list-sessions','-F','#{session_id}:#{session_name}'],text=True).splitlines()
            command=shlex.join(['env','-u','CODEX_THREAD_ID','-u','CODEX_SESSION_ID','-u','TMUX_PANE',target['executable'],'resume','--remote',endpoint,'--no-alt-screen','-C',cwd,thread])
            subprocess.run(['tmux','new-session','-d','-s',tmux_name,'-c',cwd,'-x','120','-y','35',command],check=True)
            created_tmux=True
            from codex_wake.sessions import build_snapshot,tmux_inventory
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                native_metadata=native('thread/read',dict(threadId=thread,includeTurns=False))['thread']
                snap=build_snapshot([native_metadata],[p for p in tmux_inventory(None,5) if p['pane_current_path']==cwd],{'native':{'availability':'available'}})
                rows=[r for r in snap['sessions'] if r.get('thread_id')==thread and r.get('attachments')]
                if len(rows)==1:break
                await asyncio.sleep(1)
            receipt['native_attachment_snapshot']=snap
            assert len(rows)==1,'native attachment missing'
            receipt['attachment']=rows[0]['attachments'][0]
            def clients():
                command=subprocess.Popen(['tmux','list-clients','-F','#{client_pid}\t#{session_name}\t#{client_tty}'],stdout=subprocess.PIPE,text=True)
                stdout,_=command.communicate(timeout=5)
                assert command.returncode==0
                found=[dict(zip(('pid','session','tty'),line.split('\t'))) for line in stdout.splitlines() if len(line.split('\t'))==3 and line.split('\t')[1]==tmux_name]
                # tmux includes its transient command client; exclude only this exact owned PID.
                return [row for row in found if row['pid']!=str(command.pid)]
            receipt['clients_before_attach']=clients()
            import pty
            import os
            attach_pid,pty_master=pty.fork()
            if attach_pid==0:
                os.environ.pop('TMUX',None);os.environ['TERM']='xterm-256color'
                os.execvp('tmux',['tmux','attach-session','-t',tmux_name])
            os.set_blocking(pty_master,False)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                try:os.read(pty_master,65536)
                except BlockingIOError:pass
                attached_clients=clients()
                if any(row['pid']==str(attach_pid) for row in attached_clients):break
                await asyncio.sleep(.1)
            owned_clients=[row for row in attached_clients if row['pid']==str(attach_pid)]
            assert len(owned_clients)==1 and owned_clients[0]['tty'],attached_clients
            receipt['attached_client']=owned_clients[0]
            receipt['other_clients_while_attached']=[row for row in attached_clients if row['pid']!=str(attach_pid)]


            verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            redirect=config['redirect_uris'][0]
            async with httpx.AsyncClient(timeout=70) as http:
                reg=await http.post(issuer+'/register',json=dict(client_name='cw667-session-only',redirect_uris=[redirect]));reg.raise_for_status();client=reg.json()['client_id']
                code=authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client,redirect_uri=redirect,resource=issuer+'/mcp',scopes=['observe','content.observe','control'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread)],code_challenge=challenge)
                response=await http.post(issuer+'/token',data=dict(grant_type='authorization_code',client_id=client,code=code,redirect_uri=redirect,code_verifier=verifier,resource=issuer+'/mcp'));response.raise_for_status();token=response.json()['access_token'];grant=authority.authenticate(token).grant_id
                async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=70) as transport:
                    async with streamable_http_client(issuer+'/mcp',http_client=transport) as streams:
                        async with ClientSession(streams[0],streams[1]) as session:
                            await session.initialize()
                            request=dict(idempotency_key='cw667-'+secrets.token_hex(8),thread_id=thread,prompt='Reply session-only-unexpected-delivery. Do not use tools.',session_mode='session_only',cadence=dict(kind='interval',seconds=30,start_at=(datetime.now(timezone.utc)+timedelta(seconds=45)).isoformat()),end=dict(kind='count',count=2),missed=dict(policy='skip',max_lateness_seconds=15),overlap=dict(policy='skip'),delivery_window_seconds=15)
                            receipt['thread_id']=thread;receipt['request']=request
                            missing=dict(request);missing.pop('session_mode')
                            try:
                                refused=decode(await session.call_tool('wake_wakes_schedules_register',dict(request=missing)))
                            except Exception as error:
                                refused=dict(error_type=type(error).__name__,message=str(error))
                            assert 'explicit_schedule_fields_required' in json.dumps(refused),refused
                            receipt['missing_mode']='refused'
                            try:
                                registered=decode(await session.call_tool('wake_wakes_schedules_register',dict(request=request)))
                            except Exception as error:
                                receipt['registration_refusal']=dict(error_type=type(error).__name__,message=str(error))
                                raise
                            receipt['registration']=registered
                            assert registered.get('status')=='completed',registered
                            schedule=registered['result'];receipt['schedule_id']=schedule['id']
                            assert schedule['armed'],schedule
                            # Detach only the real PTY client created by this process.
                            assert [row for row in clients() if row['pid']==str(attach_pid)]==[receipt['attached_client']]
                            subprocess.run(['tmux','detach-client','-t',receipt['attached_client']['tty']],check=True)
                            os.waitpid(attach_pid,0);attach_pid=None
                            os.close(pty_master);pty_master=None
                            receipt['clients_after_detach']=clients()
                            assert not any(row['pid']==receipt['attached_client']['pid'] for row in receipt['clients_after_detach'])
                            receipt['attached_client_transition']='1_to_0'
                            await asyncio.sleep(3)
                            shown=decode(await session.call_tool('wake_wakes_schedules_show',dict(schedule_id=schedule['id'])))['result']
                            assert shown['state']=='enabled',shown
                            receipt['detached_survives']=True
                            subprocess.run(['tmux','kill-session','-t',tmux_name],check=True)
                            deadline=time.monotonic()+65
                            while time.monotonic()<deadline:
                                shown=decode(await session.call_tool('wake_wakes_schedules_show',dict(schedule_id=schedule['id'])))['result']
                                if datetime.now(timezone.utc)>datetime.fromisoformat(request['cadence']['start_at'])+timedelta(seconds=5):break
                                await asyncio.sleep(1)
                            receipt['after_due']=shown
                            assert shown['state']=='cancelled' and shown['reason']=='session_closed',shown
                            assert not shown['occurrences'],shown
                            observed=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
                            messages=[i for t in observed['turns'] for i in t.get('items',[]) if i.get('type')=='userMessage']
                            assert len(messages)==1,messages
                            receipt.update(status='passed',native_inputs_after_closure=0,observed_past_due=True)

    finally:
        if attach_pid is not None:
            attached=receipt.get('attached_client')
            if attached:subprocess.run(['tmux','detach-client','-t',attached['tty']],capture_output=True)
            try:os.waitpid(attach_pid,0)
            except ChildProcessError:pass
        if pty_master is not None:os.close(pty_master)
        if receipt.get('schedule_id'):
            try:
                from codex_wake.recurring_schedules import ScheduleStore
                from codex_wake.session_permissions import Principal
                store=ScheduleStore(root);retained=store.read(receipt['schedule_id'])
                if retained['state']!='cancelled':
                    store.cancel(receipt['schedule_id'],retained['revision'],principal=Principal('local-operator','operator'))
                receipt['schedule_cleanup']=store.read(receipt['schedule_id'])['state']
            except Exception as error:
                receipt['schedule_cleanup_error']=str(error)
                receipt['status']='failed'
        if created_tmux:subprocess.run(['tmux','kill-session','-t','cw667-session-only'],capture_output=True)
        receipt['owned_session_absent']='cw667-session-only' not in subprocess.check_output(['tmux','list-sessions','-F','#{session_name}'],text=True).splitlines()
        try:
            if thread is not None:
                native('thread/archive',dict(threadId=thread));receipt['disposable_thread']='archived'
                if reuse_thread and 'cwd' in locals() and Path(cwd).parent==scratch and Path(cwd).name.startswith('cw667-'):
                    import shutil
                    shutil.rmtree(cwd)
        finally:
            try:
                if grant is not None:
                    authority.revoke_grant(grant);receipt['temporary_grant']='revoked'
            finally:
                output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2));output.chmod(0o600)
                if receipt['status']=='running':receipt['status']='failed'
                output.write_text(json.dumps(receipt,indent=2))
                connection.close()
                print(json.dumps(dict(receipt=str(output),**{k:receipt[k] for k in ('ticket','status','owned_session_absent','disposable_thread','temporary_grant') if k in receipt})))



if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live',action='store_true',required=True,help='authorize this bounded disposable native/OAuth acceptance')
    parser.add_argument('--reuse-thread',help='reuse only an earlier owned #667 disposable thread')
    options=parser.parse_args()
    asyncio.run(main(options.reuse_thread))
