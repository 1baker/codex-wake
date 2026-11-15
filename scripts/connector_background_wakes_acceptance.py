#!/usr/bin/env python3
"""Opt-in OAuth/MCP background due wakes, first live then after owned tab closure.

One saved disposable UUID, two count=1 schedules, no permission policy changes.
Run only after acquiring the serialized live slot; secrets stay in memory.
"""
import asyncio
import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
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
from codex_wake.sessions import observe
from codex_wake.shared_app_server import locate_shared_endpoint


def decode(result):
    value=getattr(result,'structured_content',None)
    return value if value is not None else json.loads(next(c.text for c in result.content if c.type=='text'))


async def main(options):
    os.umask(0o077)
    config=json.loads((Path.home()/'.config/codex-wake/external-connector.json').read_text())
    root=Path(config['wake_root']);issuer=config['issuer'];endpoint=locate_shared_endpoint(timeout=10)
    authority=OAuthAuthority(root/'external-oauth/authority.sqlite',issuer=issuer,resource=issuer+'/mcp')
    output=options.receipt
    assert not output.exists(), 'preserve previous receipt; select a new path'
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    grant=None;thread=None;tmux=None;tui_pid=None;schedules=[]
    receipt=dict(ticket=669,status='running',boundary='deployed HTTPS OAuth/MCP',
        installed_prefix=sys.prefix, source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), prior_art='1de611fa91a6a17114b2d0ea82920f45c5b880a7')
    from codex_wake.monitor import read_monitor_health
    from codex_wake.signal_records import probe_managed_reader_capability
    health=read_monitor_health(root) or {}
    reader=probe_managed_reader_capability(root)
    ready=bool(reader and 8 in reader.schema_versions and health.get('mode')=='loop'
        and all(c in health.get('reader_capabilities',[]) for c in ('recurring_schedules_v1','wake_session_modes_v1')))
    receipt['monitor_preflight']=dict(health=health,managed_reader_present=reader is not None,ready=ready)
    if not ready:
        receipt.update(status='blocked',reason='persistent_monitor_not_ready',native_targets_created=0,
            grants_created=0,schedules_created=0,memory_disposition='forbidden',
            memory_reason='Task prohibits memory writes without explicit user request')
        output.write_text(json.dumps(receipt,indent=2));output.chmod(0o600)
        raise RuntimeError('Persistent monitor unavailable; no global worker activation authorized')
    from websockets.sync.client import unix_connect
    connection_context=unix_connect(endpoint[7:],open_timeout=10,close_timeout=1,compression=None,ping_interval=None,max_size=32*1024*1024)
    connection=connection_context.__enter__()
    sequence=0
    def native(method,args):
        nonlocal sequence
        receipt['native_method']=method
        output.write_text(json.dumps(receipt,indent=2));output.chmod(0o600)
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
    native('initialize',dict(clientInfo=dict(name='cw669_continuity',version='1'),capabilities=dict(experimentalApi=True)))
    connection.send(json.dumps(dict(method='initialized')))
    try:
        scratch=Path('/home/ecochran76/workspace.local/codex-wake/.scratch');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cw669-',dir=scratch) as temporary:
            cwd=Path(temporary)
            tmux=['tmux'];socket=None
            tmux_name='cw669-'+secrets.token_hex(6)
            if options.reuse_owned_thread:
                owned=json.loads((output.parent/'owned-threads.json').read_text())
                assert options.reuse_owned_thread in owned,'reuse requires a privately recorded owned preparation thread'
                thread=options.reuse_owned_thread;receipt['thread_id']=thread;save()
                native('thread/unarchive',dict(threadId=thread))
                resumed=native('thread/resume',dict(threadId=thread))['thread']
                assert resumed['id']==thread and resumed.get('name')=='CW669-background-wakes'
                cwd=Path(resumed['cwd']);receipt['preparation']='reused exact owned seeded conversation'
                assert cwd.parent==scratch and cwd.name.startswith('cw669-'),'owned scratch cwd required'
                cwd.mkdir(exist_ok=True)
            else:
                thread=native('thread/start',dict(cwd=str(cwd),ephemeral=False,approvalPolicy='never',sandbox='read-only'))['thread']['id']
                receipt['thread_id']=thread;save()
                manifest=output.parent/'owned-threads.json'
                owned=json.loads(manifest.read_text()) if manifest.exists() else []
                if thread not in owned:owned.append(thread)
                manifest.write_text(json.dumps(owned));manifest.chmod(0o600)
                native('thread/name/set',dict(threadId=thread,name='CW669-background-wakes'))
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
            subprocess.run(tmux+['new-session','-d','-s',tmux_name,'-n','continuity','-c',str(cwd),'sleep 600'],check=True,capture_output=True,text=True)
            subprocess.run(tmux+['set-option','-w','-t',tmux_name+':continuity','remain-on-exit','on'],check=True,capture_output=True)
            subprocess.run(tmux+['respawn-pane','-k','-t',tmux_name+':continuity',command],check=True,capture_output=True)
            deadline=time.monotonic()+90;attached=None
            while time.monotonic()<deadline:
                screen=subprocess.run(tmux+['capture-pane','-p','-t',tmux_name+':continuity'],capture_output=True,text=True).stdout
                if 'trust this' in screen.lower():raise AssertionError('pretrusted cwd unexpectedly requires trust; no global trust change authorized')
                discovery=observe(endpoint=endpoint,socket_path=socket,timeout=10)
                receipt['attachment_discovery']=dict(complete=discovery.get('complete'),sources=discovery.get('sources'),sessions=[r for r in discovery['sessions'] if r.get('thread_id')==thread or thread in r.get('candidates',[])])
                receipt['owned_pane_metadata']=subprocess.run(tmux+['list-panes','-t',tmux_name+':continuity','-F','#{pane_id}|#{pane_title}|#{pane_current_path}|#{pane_pid}'],capture_output=True,text=True).stdout
                save()
                rows=[r for r in discovery['sessions'] if r.get('thread_id')==thread]
                if discovery.get('complete') and len(rows)==1 and rows[0].get('binding_status')=='metadata_matched' and len(rows[0]['attachments'])==1:
                    attached=rows[0];break
                screen=subprocess.run(tmux+['capture-pane','-p','-t',tmux_name+':continuity'],capture_output=True,text=True).stdout
                if 'Do you trust' in screen or 'trust this' in screen.lower():raise AssertionError('unexpected trust dialog')
                await asyncio.sleep(1)
            if attached is None:
                receipt['owned_tui_screen']=screen[-1600:]
                snapshot=observe(endpoint=endpoint,timeout=10)
                receipt['failed_attachment_sources']=dict(complete=snapshot.get('complete'),sources=snapshot.get('sources'),rows=[r for r in snapshot.get('sessions',[]) if r.get('thread_id')==thread or thread in r.get('candidates',[])])
                save()
            assert attached is not None,'owned TUI did not establish exact native attachment'
            tui_pid=attached['attachments'][0]['client_pid'];receipt['live_tab_before']=True
            receipt['tui_pid']=tui_pid;receipt['initial_attachment']=attached;save()
            saved=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
            assert saved['id']==thread and saved.get('turns'),'exact saved conversation has no persisted preparation history'
            receipt['saved_before_close']=True
            # Keep this exact recipient alive for the first due wake.
            redirect=config['redirect_uris'][0];verifier=secrets.token_urlsafe(48)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            async with httpx.AsyncClient(timeout=70) as http:
                response=await http.post(issuer+'/register',json=dict(client_name='cw669-background-wakes',redirect_uris=[redirect]));response.raise_for_status();client=response.json()['client_id']
                code=authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client,redirect_uri=redirect,resource=issuer+'/mcp',scopes=['observe','content.observe','control'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread)],code_challenge=challenge)
                response=await http.post(issuer+'/token',data=dict(grant_type='authorization_code',client_id=client,code=code,redirect_uri=redirect,code_verifier=verifier,resource=issuer+'/mcp'));response.raise_for_status();token=response.json()['access_token'];grant=authority.authenticate(token).grant_id
                async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=70) as transport:
                    async with streamable_http_client(issuer+'/mcp',http_client=transport) as streams:
                        async with ClientSession(streams[0],streams[1]) as session:
                            await session.initialize()
                            async def call(name, arguments):
                                value=decode(await session.call_tool(name, arguments))
                                assert value.get('status')=='completed', value
                                return value['result']

                            async def due_case(label):
                                marker='CW669_'+label.upper()+'_'+secrets.token_hex(4)
                                request=dict(idempotency_key='cw669-'+secrets.token_hex(12),
                                    thread_id=thread,prompt='Reply exactly '+marker+'. Do not use tools.',
                                    session_mode='background',
                                    cadence=dict(kind='interval',seconds=45,start_at=(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()),
                                    end=dict(kind='count',count=1),missed=dict(policy='skip',max_lateness_seconds=120),
                                    overlap=dict(policy='skip'),delivery_window_seconds=120)
                                case=dict(request=request,expected_route='existing_tab' if label=='live' else 'background')
                                receipt.setdefault('cases',{})[label]=case;save()
                                schedule=await call('wake_wakes_schedules_register',dict(request=request))
                                schedules.append(schedule['id']);case['schedule_id']=schedule['id'];save()
                                assert schedule['armed'] and schedule['session_mode']=='background',schedule
                                deadline=time.monotonic()+240
                                while time.monotonic()<deadline:
                                    shown=await call('wake_wakes_schedules_show',dict(schedule_id=schedule['id']))
                                    case['schedule']=shown
                                    occurrences=shown.get('occurrences',[])
                                    if shown.get('attention') or any(o['state'] in ('attention','expired','failed','turn_failed','turn_interrupted','skipped') for o in occurrences):
                                        save();raise AssertionError('due wake did not complete: '+json.dumps(shown))
                                    if len(occurrences)==1 and occurrences[0]['state']=='completed':break
                                    await asyncio.sleep(1)
                                assert len(occurrences)==1 and occurrences[0]['state']=='completed',shown
                                wake_id=occurrences[0]['wake_id']
                                from codex_wake.records import find_record
                                wake=find_record(root,wake_id).record
                                case['wake']=wake
                                observed=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
                                matches=[]
                                for turn in observed['turns']:
                                    for item in turn.get('items',[]):
                                        if item.get('type')=='userMessage' and marker in json.dumps(item):matches.append((turn,item))
                                assert len(matches)==1, 'wake must produce exactly one native input'
                                turn,item=matches[0]
                                assert turn['status']=='completed',turn
                                assert wake_id in json.dumps(item), 'native input lacks exact wake identity'
                                delivery=wake.get('native_delivery',{})
                                assert delivery.get('state')=='accepted',delivery
                                if delivery.get('turn_id'):assert delivery['turn_id']==turn['id'],delivery
                                case['native_message_id']=item['id']
                                replies=[i['text'] for i in turn.get('items',[]) if i.get('type')=='agentMessage']
                                assert replies and replies[-1].strip()==marker,replies
                                assert observed['id']==thread
                                case.update(native_input_count=1,native_turn_id=turn['id'],answer=replies[-1],same_conversation=True)
                                # Require persisted dispatch route evidence, not mode inference.
                                assert delivery.get('route')==case['expected_route'],delivery
                                snapshot=observe(endpoint=endpoint,timeout=10)
                                case['final_observation_sources']=dict(complete=snapshot.get('complete'),sources=snapshot.get('sources'))
                                assert snapshot.get('complete'),snapshot.get('sources')
                                current=[r for r in snapshot['sessions'] if r.get('thread_id')==thread]
                                attachments=[a for row in current for a in row.get('attachments',[])]
                                if label=='live':
                                    assert len(current)==1 and current[0].get('binding_status')=='metadata_matched',current
                                    assert len(attachments)==1 and attachments[0]['client_pid']==tui_pid,'live recipient duplicated or replaced'
                                else:
                                    assert not attachments,'closed case created a visible tab'
                                case.update(attachments=attachments,status='passed');save()
                                current=await call('wake_wakes_schedules_show',dict(schedule_id=schedule['id']))
                                case['cleanup']=await call('wake_wakes_schedules_cancel',dict(schedule_id=schedule['id'],expected_revision=current['revision']))
                                assert case['cleanup']['state']=='cancelled',case['cleanup']
                                schedules.remove(schedule['id']);save()

                            try:
                                await due_case('live')
                                subprocess.run(tmux+['kill-window','-t',tmux_name+':continuity'],check=True,capture_output=True)
                                deadline=time.monotonic()+15
                                while time.monotonic()<deadline and Path('/proc',str(tui_pid)).exists():await asyncio.sleep(.2)
                                assert not Path('/proc',str(tui_pid)).exists(),'owned TUI survived closure'
                                assert subprocess.run(tmux+['has-session','-t',tmux_name],capture_output=True).returncode!=0
                                receipt['closed_before_second_due']=True;save()
                                await due_case('closed')
                                receipt['status']='passed'
                                final=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
                                synthetic=[i for t in final['turns'] for i in t.get('items',[]) if i.get('type')=='userMessage' and 'CW669_' in json.dumps(i)]
                                assert len(synthetic)==2,'unexpected additional native input'
                                receipt['total_wake_inputs']=len(synthetic)
                            finally:
                                for schedule_id in list(schedules):
                                    current=await call('wake_wakes_schedules_show',dict(schedule_id=schedule_id))
                                    cleaned=await call('wake_wakes_schedules_cancel',dict(schedule_id=schedule_id,expected_revision=current['revision']))
                                    receipt.setdefault('failure_schedule_cleanup',[]).append(cleaned)
                                    assert cleaned['state']=='cancelled',cleaned
                                    schedules.remove(schedule_id)
    except Exception as error:
        receipt['failure']=dict(type=type(error).__name__,message=str(error))
        receipt['status']='failed'
        raise
    finally:
        try:
            if tmux:subprocess.run(tmux+['kill-session','-t',tmux_name],capture_output=True)
            deadline=time.monotonic()+10
            while tui_pid and Path('/proc',str(tui_pid)).exists() and time.monotonic()<deadline:await asyncio.sleep(.1)
            receipt['owned_tui_absent']=tui_pid is None or not Path('/proc',str(tui_pid)).exists()
            receipt['schedules_cleaned']=not schedules
            receipt['memory_disposition']='forbidden'
            receipt['memory_reason']='No explicit memory write request'
            if thread:native('thread/archive',dict(threadId=thread));receipt['owned_thread']='archived'
        finally:
            try:
                if grant:
                    authority.revoke_grant(grant);receipt['temporary_grant']='revoked'
                    async with httpx.AsyncClient(timeout=15) as check:
                        rejected=await check.post(issuer+'/mcp',headers={'Authorization':'Bearer '+token},json={})
                        receipt['revoked_grant_http']=rejected.status_code
                        assert rejected.status_code==401,'revoked grant remained accepted'
            finally:
                if receipt['status']=='running' or not receipt.get('owned_tui_absent') or not receipt.get('schedules_cleaned') or receipt.get('temporary_grant')!='revoked' or receipt.get('owned_thread')!='archived':receipt['status']='failed'
                save();connection_context.__exit__(None,None,None);print(json.dumps(dict(status=receipt['status'],receipt=str(output))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-live',action='store_true',required=True);parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--reuse-owned-thread')
    asyncio.run(main(parser.parse_args()))
