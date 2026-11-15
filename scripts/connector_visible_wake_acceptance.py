#!/usr/bin/env python3
"""Opt-in deployed connector visible restoration probe on one disposable thread.

Requires one privately prepared, verified disposable recipient and host-owned
restore binding. Certifies acceptance only after native result and restored
harness/cwd checks pass.

Run with the installed connector Python. Secrets stay in process memory; only a
credential-free receipt is retained. No operator conversation is addressed.
"""
import argparse
import os
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import secrets
from contextlib import nullcontext
import time
import subprocess
from datetime import datetime, timezone, timedelta

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from codex_wake.controller_auth import OAuthAuthority
from codex_wake.local_sessions import discover
from codex_wake.sessions import observe
from codex_wake.shared_app_server import locate_shared_endpoint


def decode(result):
    if getattr(result,'structured_content',None) is not None:return result.structured_content
    return json.loads(next(c.text for c in result.content if c.type=='text'))


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live',action='store_true',required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--owned-target',type=Path,default=Path.home()/'.local/state/codex-wake/connector-visible-668/target.json')
    args=parser.parse_args()
    os.umask(0o077)
    config=json.loads((Path.home()/'.config/codex-wake/external-connector.json').read_text())
    root=Path(config['wake_root']);issuer=config['issuer'];endpoint=locate_shared_endpoint(timeout=10)
    authority=OAuthAuthority(root/'external-oauth/authority.sqlite',issuer=issuer,resource=issuer+'/mcp')
    output=args.receipt
    assert not output.exists(), 'Receipt already exists; preserve previous evidence'
    tmux_name='cw668-visible-'+secrets.token_hex(4)
    owned_session=False
    import sys
    import codex_wake
    grant=None;thread=None;receipt=dict(ticket=668,status='running',boundary='deployed HTTPS OAuth/MCP',python=sys.executable,package=str(Path(codex_wake.__file__).resolve()),started_at=datetime.now(timezone.utc).isoformat())
    from websockets.sync.client import unix_connect
    connection_context=unix_connect(endpoint[7:],ping_interval=None,max_size=32*1024*1024)
    connection=connection_context.__enter__()
    sequence=0
    def native(method,args):
        nonlocal sequence
        sequence+=1;connection.send(json.dumps(dict(id=sequence,method=method,params=args)))
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            response=json.loads(connection.recv(timeout=max(.01,deadline-time.monotonic())))
            if response.get('id')!=sequence:continue
            if 'error' in response:raise RuntimeError(json.dumps(response['error']))
            return response['result']
        raise TimeoutError(method)
    native('initialize',dict(clientInfo=dict(name='cw668_visible_acceptance',version='1'),capabilities=dict(experimentalApi=True)))
    connection.send(json.dumps(dict(method='initialized')))
    try:
        with nullcontext():
            owned=json.loads(args.owned_target.read_text())
            assert owned['endpoint']==endpoint,'prepared native endpoint changed'
            thread=owned['thread_id'];cwd=owned['cwd']
            receipt.update(thread_id=thread,cwd=cwd)
            selected=discover(root,endpoint,thread_id=thread)['sessions']
            assert len(selected)==1 and len(selected[0]['attachments'])==1
            target=selected[0]['target'];receipt['target_before']=target;before=selected[0]['attachments'][0]
            tmux_name=before['session_name'];owned_session=True
            receipt['owned_session']=tmux_name;receipt['attachment_before']=before
            windows=subprocess.check_output(['tmux','list-windows','-t',tmux_name,'-F','#{window_name}'],text=True).splitlines()
            if 'owned-container' not in windows:
                subprocess.run(['tmux','new-window','-d','-t',tmux_name,'-n','owned-container','sleep 1200'],check=True)
            saved=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
            baseline=[i for t in saved['turns'] for i in t.get('items',[]) if i.get('type')=='userMessage']
            assert len(baseline)==1,'one owned setup input required'
            receipt['stage']='public OAuth/MCP'
            verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            redirect=config['redirect_uris'][0]
            async with httpx.AsyncClient(timeout=70) as http:
                reg=await http.post(issuer+'/register',json=dict(client_name='cw668-visible-wake',redirect_uris=[redirect]));reg.raise_for_status();client=reg.json()['client_id']
                code=authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client,redirect_uri=redirect,resource=issuer+'/mcp',scopes=['observe','content.observe','control'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread)],code_challenge=challenge)
                response=await http.post(issuer+'/token',data=dict(grant_type='authorization_code',client_id=client,code=code,redirect_uri=redirect,code_verifier=verifier,resource=issuer+'/mcp'));response.raise_for_status();token=response.json()['access_token'];grant=authority.authenticate(token).grant_id
                async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=70) as transport:
                    async with streamable_http_client(issuer+'/mcp',http_client=transport) as streams:
                        async with ClientSession(streams[0],streams[1]) as session:
                            await session.initialize()
                            request=dict(idempotency_key='cw668-'+secrets.token_hex(8),thread_id=thread,prompt='Reply exactly CW668_VISIBLE_RESTORATION. Do not use tools.',session_mode='reopen_live',cadence=dict(kind='interval',seconds=30,start_at=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat()),end=dict(kind='count',count=1),missed=dict(policy='skip',max_lateness_seconds=120),overlap=dict(policy='skip'),delivery_window_seconds=120)
                            receipt['thread_id']=thread;receipt['request']=request
                            missing=dict(request);missing.pop('session_mode')
                            try:
                                refused=decode(await session.call_tool('wake_wakes_schedules_register',dict(request=missing)))
                            except Exception as error:
                                refused=str(error)
                            assert 'explicit_schedule_fields_required' in json.dumps(refused),refused
                            receipt['missing_mode_response']=refused
                            receipt['missing_mode']='refused'
                            receipt['stage']='schedule registration'
                            registered=decode(await session.call_tool('wake_wakes_schedules_register',dict(request=request)))
                            schedule=None
                            try:
                                receipt['registration']=registered
                                assert registered.get('status')=='completed',registered
                                schedule=registered['result'];receipt['schedule_id']=schedule['id']
                                assert schedule['armed'],schedule
                                receipt['persisted_schedule']=decode(await session.call_tool('wake_wakes_schedules_show',dict(schedule_id=schedule['id'])))['result']
                                # The exact owned recipient is genuinely closed before due time.
                                subprocess.run(['tmux','kill-window','-t',before['window_id']],check=True)
                                assert datetime.now(timezone.utc)<datetime.fromisoformat(request['cadence']['start_at'])
                                receipt['closed_before_due']=True
                                receipt['closed_at']=datetime.now(timezone.utc).isoformat()
                                receipt['stage']='closed recipient due wake'
                                deadline=time.monotonic()+240
                                while time.monotonic()<deadline:
                                    shown=decode(await session.call_tool('wake_wakes_schedules_show',dict(schedule_id=schedule['id'])))['result']
                                    receipt['after_due']=shown
                                    if shown.get('occurrences'):
                                        if any(o.get('state') in ('turn_failed','turn_interrupted','attention','failed','cancelled','expired') for o in shown['occurrences']):break
                                        observed=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
                                        if len(observed.get('turns',[]))==2 and observed['turns'][-1].get('status')=='completed':break
                                    await asyncio.sleep(1)
                                if len(shown.get('occurrences',[]))==1 and shown['occurrences'][0].get('wake_id'):
                                    from codex_wake.records import find_record
                                    receipt['wake_record']=find_record(root,shown['occurrences'][0]['wake_id']).record
                                assert len(shown.get('occurrences',[]))==1 and shown['occurrences'][0]['state'] not in ('turn_failed','turn_interrupted','attention','failed','cancelled','expired'),shown
                                from codex_wake.records import find_record
                                wake=find_record(root,shown['occurrences'][0]['wake_id']).record
                                receipt['wake_record']=wake
                                assert wake.get('attempts')==1 and wake.get('native_delivery',{}).get('state')=='accepted',wake
                                observed=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
                                messages=[i for t in observed['turns'] for i in t.get('items',[]) if i.get('type')=='userMessage']
                                receipt['native_inputs_after_closure']=len(messages)-1
                                receipt['restoration_attachments']=[r['attachments'] for r in observe(endpoint=endpoint,timeout=10)['sessions'] if r.get('thread_id')==thread]
                                restored=[r for r in observe(endpoint=endpoint,timeout=30)['sessions'] if r.get('thread_id')==thread]
                                assert len(restored)==1 and len(restored[0]['attachments'])==1
                                after=restored[0]['attachments'][0]
                                assert restored[0]['cwd']==cwd and after['pane_current_path']==cwd
                                assert after['session_name']==tmux_name and after['client_pid']!=before['client_pid']
                                assert restored[0]['binding_status']=='metadata_matched'
                                assert discover(root,endpoint,thread_id=thread)['sessions'][0]['target']['executable']==target['executable']
                                receipt['restored_executable']=target['executable']
                                receipt['owned_screen']=subprocess.check_output(['tmux','capture-pane','-p','-t',after['pane_id']],text=True)
                                assert receipt['native_inputs_after_closure']==1
                                replies=[i for t in observed['turns'][1:] for i in t.get('items',[]) if i.get('type')=='agentMessage']
                                assert len(observed['turns'])==2 and observed['turns'][-1].get('status')=='completed'
                                receipt['native_turn_id']=observed['turns'][-1]['id']
                                assert len(replies)==1 and replies[0].get('text','').strip()=='CW668_VISIBLE_RESTORATION'
                                receipt.update(status='passed',attachment_after=after,final_reply=replies[0],same_conversation=True,restored_cwd=cwd)
                            finally:
                                if schedule is not None:
                                    current=decode(await session.call_tool('wake_wakes_schedules_show',dict(schedule_id=schedule['id'])))['result']
                                    receipt['schedule_cleanup']=decode(await session.call_tool('wake_wakes_schedules_cancel',dict(schedule_id=schedule['id'],expected_revision=current['revision'])))

    except Exception as error:
        receipt['failure_type']=type(error).__name__
        raise
    finally:
        if owned_session:
            try:
                final_snapshot=observe(endpoint=endpoint,timeout=30)
                receipt['observation_before_cleanup']={key:final_snapshot.get(key) for key in ('complete','sources','observed_at')}
                receipt['observation_before_cleanup']['sessions']=[row for row in final_snapshot.get('sessions',[]) if row.get('thread_id')==thread or thread in row.get('candidates',[])]
            except Exception as error:
                receipt['observation_before_cleanup_error']=dict(type=type(error).__name__,message=str(error))
            receipt['owned_panes_before_cleanup']=subprocess.run(['tmux','list-panes','-s','-t',tmux_name,'-F','#{pane_id}\t#{pane_pid}\t#{pane_title}\t#{pane_current_path}'],capture_output=True,text=True).stdout
            panes=subprocess.run(['tmux','list-panes','-s','-t',tmux_name,'-F','#{pane_id}'],capture_output=True,text=True)
            receipt['owned_screens_before_cleanup']={pane:subprocess.run(['tmux','capture-pane','-p','-t',pane],capture_output=True,text=True).stdout for pane in panes.stdout.splitlines()}
            subprocess.run(['tmux','kill-session','-t',tmux_name],capture_output=True)
        listed=subprocess.run(['tmux','list-sessions','-F','#{session_name}'],capture_output=True,text=True)
        receipt['owned_session_absent']=tmux_name not in listed.stdout.splitlines()
        receipt['memory_disposition']='forbidden'
        receipt['memory_reason']='No explicit memory write request'
        try:
            if thread is not None:
                native('thread/archive',dict(threadId=thread));receipt['disposable_thread']='archived'
        finally:
            try:
                if grant is not None:
                    authority.revoke_grant(grant);receipt['temporary_grant']='revoked'
            finally:
                receipt['finished_at']=datetime.now(timezone.utc).isoformat()
                output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2));output.chmod(0o600)
                if receipt['status']=='running':receipt['status']='failed'
                output.write_text(json.dumps(receipt,indent=2))
                connection_context.__exit__(None,None,None)
                print(json.dumps(dict(status=receipt['status'],receipt=str(output),stage=receipt.get('stage'))))



if __name__=='__main__':asyncio.run(main())
