#!/usr/bin/env python3
"""Opt-in #672: retain one real OAuth/MCP operation across a connector restart.

The controller performs the sole service restart after checkpoint.json appears,
then creates restart-complete in --output. No restart command runs here. Tokens
stay in this process; a crashed run cannot resume by minting another grant.
"""
import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-real-agent', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-pid', type=int, required=True)
    options = parser.parse_args()
    if not options.approve_real_agent:
        parser.error('requires an exclusive approved live slot and --approve-real-agent')
    options.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    asyncio.run(run(options))


async def run(options):
    import httpx2 as httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from websockets.sync.client import unix_connect
    from codex_wake.controller_auth import OAuthAuthority
    from codex_wake.local_sessions import discover
    from codex_wake.shared_app_server import locate_shared_endpoint

    config = json.loads((Path.home()/'.config/codex-wake/external-connector.json').read_text())
    root = Path(config['wake_root']); issuer = config['issuer'].rstrip('/')
    endpoint = locate_shared_endpoint(timeout=10)
    authority = OAuthAuthority(root/'external-oauth/authority.sqlite', issuer=issuer, resource=issuer+'/mcp')
    receipt = dict(ticket=672, verdict='INCOMPLETE', boundary='deployed HTTPS OAuth/MCP', checks={}, cleanup={},
                   python_executable=sys.executable, installed_auth_module=__import__('codex_wake.controller_auth',fromlist=['__file__']).__file__)
    receipt['script_source_commit'] = subprocess.run(['git','-C',str(Path(__file__).resolve().parent.parent),'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
    thread = grant = token = None
    def save(name='result.json'):
        path = options.output/name
        path.write_text(json.dumps(receipt, indent=2)+'\n'); path.chmod(0o600)
    def native_identity():
        proc = Path('/proc')/str(options.native_pid)
        # The start-time field survives changes to CPU counters and detects PID reuse.
        return dict(pid=options.native_pid, start_ticks=(proc/'stat').read_text().rsplit(')',1)[1].split()[19],
                    executable=str((proc/'exe').resolve(strict=True)), endpoint=locate_shared_endpoint(timeout=10))
    def connector_pid():
        value = subprocess.run(['systemctl','--user','show','codex-wake-connector.service','--property=MainPID','--value'], check=True, capture_output=True, text=True).stdout.strip()
        assert int(value)>0, 'connector service has no running PID'
        return int(value)
    connection_context = unix_connect(endpoint[7:], open_timeout=10, close_timeout=1, ping_interval=None, compression=None, max_size=32*1024*1024)
    connection = connection_context.__enter__(); sequence = 0
    def native(method, params):
        nonlocal sequence
        sequence += 1; identifier = sequence
        connection.send(json.dumps(dict(id=identifier, method=method, params=params)))
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            value = json.loads(connection.recv(timeout=max(.01,deadline-time.monotonic())))
            if value.get('id')!=identifier: continue
            if 'error' in value:
                receipt.setdefault('native_errors',[]).append(dict(method=method,error=value['error']))
                save(); raise RuntimeError('native '+method+' refused')
            return value['result']
        raise TimeoutError('native '+method+' observation deadline')
    native('initialize', dict(clientInfo=dict(name='cw672_restart_acceptance',version='1'),capabilities=dict(experimentalApi=True)))
    connection.send(json.dumps(dict(method='initialized')))
    async def read():
        return (await asyncio.to_thread(native,'thread/read',dict(threadId=thread,includeTurns=True)))['thread']
    def loaded():
        identifiers = []; cursor = None
        for _ in range(100):
            page = native('thread/loaded/list',dict(limit=100,cursor=cursor))
            identifiers.extend(page['data']); cursor = page.get('nextCursor')
            if not cursor: return identifiers
        raise AssertionError('loaded-session census exceeded 10000 entries')
    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=70) as transport:
            async with streamable_http_client(issuer+'/mcp',http_client=transport) as streams:
                async with ClientSession(streams[0],streams[1]) as session:
                    await session.initialize(); yield session
    async def tool(session,name,args):
        response = await session.call_tool(name,args)
        value = getattr(response,'structured_content',None)
        if value is None: value = json.loads(''.join(c.text for c in response.content if getattr(c,'type',None)=='text'))
        assert not response.is_error, value
        assert value['status']=='completed', value
        return value['result']['operation']
    def inputs(history, identifier):
        return [item for turn in history['turns'] for item in turn.get('items',[]) if item.get('type')=='userMessage' and item.get('clientId')==identifier]
    try:
        receipt['native_before'] = native_identity(); receipt['connector_pid_before'] = connector_pid()
        before = loaded(); receipt['unrelated_loaded_before'] = before
        created = native('thread/start',dict(cwd=str(options.output),ephemeral=False,approvalPolicy='never',sandbox='danger-full-access',developerInstructions='Disposable restart acceptance. Execute only the specifically requested local sleep command. Do not access other files, services, agents, configuration or schedules.'))
        thread = created['thread']['id']; receipt['thread_id'] = thread; save()
        native('thread/name/set',dict(threadId=thread,name='CW672-restart-continuity'))
        native('turn/start',dict(threadId=thread,input=[dict(type='text',text='Reply exactly setup-ready. Do not use tools.')]))
        deadline = time.monotonic()+120; metadata = None
        while time.monotonic()<deadline:
            try: metadata = await read()
            except (RuntimeError,TimeoutError):
                await asyncio.sleep(1); continue
            if metadata.get('status',{}).get('type')=='idle': break
            await asyncio.sleep(1)
        assert metadata and metadata.get('status',{}).get('type')=='idle', 'same owned setup did not become ready'
        selected = discover(root,endpoint,thread_id=thread)['sessions']; assert len(selected)==1
        target = selected[0]['target']; receipt['target'] = target
        redirect = config['redirect_uris'][0]; verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        async with httpx.AsyncClient(timeout=70) as http:
            response = await http.post(issuer+'/register',json=dict(client_name='cw672-restart',redirect_uris=[redirect])); response.raise_for_status()
            client_id = response.json()['client_id']
            code = authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client_id,redirect_uri=redirect,resource=issuer+'/mcp',scopes=['observe','content.observe','control'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread)],code_challenge=challenge)
            response = await http.post(issuer+'/token',data=dict(grant_type='authorization_code',client_id=client_id,code=code,redirect_uri=redirect,code_verifier=verifier,resource=issuer+'/mcp')); response.raise_for_status()
            token = response.json()['access_token']; grant = authority.authenticate(token).grant_id
        receipt['grant_id'] = grant
        args = dict(selector='thread:'+thread,prompt='Run the shell command sleep 60 exactly once, wait until it finishes, then reply exactly RESTART_CONTINUITY_CONFIRMED. This is the entire bounded task.',policy='reject',idempotency_key='cw672-'+secrets.token_hex(12),expected_target=target)
        receipt['intent_key'] = args['idempotency_key']
        async with client() as session:
            original = await tool(session,'wake_environment_conversations_input_submit',args)
            identifier = original['operation_id']; receipt['operation_id'] = identifier
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                history = await read()
                active = [turn for turn in history['turns'] if turn.get('status')=='inProgress' and any(i.get('clientId')==identifier for i in turn.get('items',[]))]
                if active: break
                await asyncio.sleep(.2)
            assert active and len(inputs(history,identifier))==1, 'no single in-flight native effect'
            receipt['inflight_turn_id'] = active[0]['id']
            observed = await tool(session,'wake_environment_conversations_input_result',dict(operation_id=identifier))
            assert observed['phase']!='terminal', 'operation completed before restart checkpoint'
        receipt['checkpoint'] = 'MCP disconnected; original operation in flight; root may restart connector only'
        receipt['checkpoint_unix'] = time.time(); save('checkpoint.json'); save()
        deadline = time.monotonic()+180
        while not (options.output/'restart-complete').exists() and time.monotonic()<deadline:
            await asyncio.sleep(.25)
        assert (options.output/'restart-complete').exists(), 'controller restart release deadline exceeded'
        # systemctl returning does not prove the public reverse-proxy upstream
        # is ready. Observe metadata only; do not retry operation submissions.
        deadline = time.monotonic()+60
        readiness = []
        async with httpx.AsyncClient(timeout=5) as http:
            while time.monotonic()<deadline:
                try:
                    response = await http.get(issuer+'/.well-known/oauth-protected-resource/mcp')
                    if response.status_code==200 and response.json().get('resource')==issuer+'/mcp':
                        anonymous = await http.post(issuer+'/mcp',json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'cw672-readiness','version':'1'}}})
                        readiness.append(dict(metadata=response.status_code,anonymous_mcp=anonymous.status_code))
                        if anonymous.status_code==401: break
                    else: readiness.append(dict(metadata=response.status_code))
                except (httpx.HTTPError,ValueError): readiness.append('transport_unavailable')
                await asyncio.sleep(.25)
            else: raise AssertionError('public metadata did not become ready after restart')
        receipt['post_restart_readiness'] = readiness
        receipt['native_after'] = native_identity(); receipt['connector_pid_after'] = connector_pid()
        assert receipt['native_after']==receipt['native_before'], 'native daemon identity changed'
        assert receipt['connector_pid_after']!=receipt['connector_pid_before'], 'connector PID did not change'
        assert authority.authenticate(token).grant_id==grant
        async with client() as session:
            retried = await tool(session,'wake_environment_conversations_input_submit',args)
            assert retried['operation_id']==identifier, 'same-key retry changed operation custody'
            receipt['checks']['same_operation_same_grant'] = True
            deadline = time.monotonic()+150
            while time.monotonic()<deadline:
                final = await tool(session,'wake_environment_conversations_input_result',dict(operation_id=identifier))
                if final['phase']=='terminal': break
                await asyncio.sleep(1)
            assert final['execution']=='completed', final
            assert final['answer']['text'].strip()=='RESTART_CONTINUITY_CONFIRMED', final
            assert final['target']['conversation_id']==thread
            assert final['answer']['turn_id']==receipt['inflight_turn_id']
            history = await read(); assert len(inputs(history,identifier))==1
            receipt['checks'].update(native_input_count=1, correlated_final_reply=True,native_daemon_preserved=True)
            receipt['answer'] = final['answer']; receipt['execution'] = final['execution']
        after = loaded(); receipt['unrelated_loaded_after'] = after
        assert set(before).issubset(after), 'unrelated loaded session disappeared'
        receipt['checks']['unrelated_loaded_sessions_preserved'] = True
        receipt['verdict'] = 'PASS'
    except BaseException as error:
        # No HTTP request/headers or credential-bearing exceptions are retained.
        receipt['error'] = dict(type=type(error).__name__,message=str(error)[:1200] if isinstance(error,AssertionError) else 'see sanitized native_errors or failing stage')
        raise
    finally:
        if thread:
            try:
                for turn in (await read())['turns']:
                    if turn.get('status')=='inProgress': native('turn/interrupt',dict(threadId=thread,turnId=turn['id']))
                terminals = native('thread/backgroundTerminals/list',dict(threadId=thread))
                for terminal in terminals['data']: native('thread/backgroundTerminals/terminate',dict(threadId=thread,processId=terminal['processId']))
                native('thread/archive',dict(threadId=thread)); receipt['cleanup']['owned_thread_archived'] = True
            except BaseException as error: receipt['cleanup']['native_error'] = type(error).__name__
        if grant:
            authority.revoke_grant(grant); receipt['cleanup']['own_grant_revoked'] = True
            try:
                async with httpx.AsyncClient(timeout=20) as http:
                    response = await http.post(issuer+'/mcp',headers={'Authorization':'Bearer '+token},json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'cw672-revoked','version':'1'}}})
                    receipt['cleanup']['revoked_public_status'] = response.status_code
            except BaseException as error: receipt['cleanup']['revocation_probe_error'] = type(error).__name__
        remaining = []
        for process in Path('/proc').iterdir():
            if not process.name.isdigit(): continue
            try:
                if process.stat().st_uid==os.getuid() and (process/'cwd').resolve(strict=True)==options.output.resolve() and (process/'comm').read_text().strip() in ('sleep','bash','zsh','sh'): remaining.append(int(process.name))
            except (OSError,ValueError): pass
        receipt['cleanup']['owned_shell_processes_remaining'] = remaining
        if remaining or not receipt['cleanup'].get('owned_thread_archived') or receipt['cleanup'].get('revoked_public_status')!=401: receipt['verdict']='INCOMPLETE'
        connection_context.__exit__(None,None,None); save()
        print(json.dumps(dict(verdict=receipt['verdict'],checks=receipt['checks'],cleanup=receipt['cleanup'],receipt=str(options.output/'result.json'))))


if __name__=='__main__': main()
