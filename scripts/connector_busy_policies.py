"""Opt-in real deployed OAuth/MCP busy-input acceptance for issue #665.

Runs bounded provider work in one newly created disposable native conversation.
Never uses browser tokens, restarts a service, or changes another conversation.
Private receipts contain synthetic prompts and operation bindings, not credentials.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-real-agent',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path.home()/'.config/codex-wake/external-connector.json')
    options=parser.parse_args()
    if not options.approve_real_agent:parser.error('real disposable native work requires --approve-real-agent')
    options.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    asyncio.run(run(options))


async def run(options):
    import httpx2 as httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from codex_wake.controller_auth import OAuthAuthority
    from websockets.sync.client import unix_connect
    from codex_wake.local_sessions import resolve
    from codex_wake.shared_app_server import locate_shared_endpoint

    config=json.loads(options.config.read_text());root=Path(config['wake_root'])
    issuer=config['issuer'].rstrip('/');endpoint=locate_shared_endpoint(timeout=10)
    authority=OAuthAuthority(root/'external-oauth/authority.sqlite',issuer=issuer,resource=issuer+'/mcp')
    thread_id=None;grant_id=None;session=None
    result=dict(ticket=665,transport='deployed OAuth MCP',verdict='INCOMPLETE',checks={},cleanup={})
    def save():
        path=options.output/'result.json';path.write_text(json.dumps(result,indent=2)+'\n');path.chmod(0o600)
    # Keep the creator attached: an empty new conversation is not a persisted
    # resumable conversation merely because thread/start returned its ID.
    connection_context=unix_connect(endpoint[7:],open_timeout=10,close_timeout=1,compression=None,max_size=32*1024*1024)
    connection=connection_context.__enter__()
    sequence=0
    def native(method,params):
        nonlocal sequence
        sequence+=1;identifier=sequence
        connection.send(json.dumps(dict(id=identifier,method=method,params=params)))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            value=json.loads(connection.recv(timeout=max(.01,deadline-time.monotonic())))
            if value.get('id')!=identifier:continue
            if 'error' in value:raise RuntimeError('native '+method+' refused: '+json.dumps(value['error']))
            return value['result']
        raise TimeoutError('native '+method+' deadline')
    native('initialize',dict(clientInfo=dict(name='cw665_busy_acceptance',version='1'),capabilities=dict(experimentalApi=True)))
    connection.send(json.dumps(dict(method='initialized')))

    async def read():return await asyncio.to_thread(native,'thread/read',dict(threadId=thread_id,includeTurns=True))
    async def tool(name,args):
        response=await session.call_tool(name,args)
        value=response.structured_content
        if value is None:
            text=''.join(block.text for block in response.content if getattr(block,'type',None)=='text')
            value=json.loads(text)
        result.setdefault('calls',[]).append(dict(tool=name,is_error=response.is_error,value=value))
        save()
        return response.is_error,value
    def operation(value):
        if 'result' in value and isinstance(value['result'],dict) and 'operation' in value['result']:return value['result']['operation']
        raise AssertionError('expected retained operation envelope: '+str(list(value)))
    async def submit(policy,prompt,key):
        error,value=await tool('wake_environment_conversations_input_submit',dict(selector='thread:'+thread_id,prompt=prompt,policy=policy,idempotency_key=key,expected_target=target))
        return error,value
    async def await_result(identifier,seconds=120):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            error,value=await tool('wake_environment_conversations_input_result',dict(operation_id=identifier))
            if error:raise AssertionError('result tool refused: '+json.dumps(value))
            value=operation(value)
            if value['phase']=='terminal':return value
            await asyncio.sleep(.5)
        raise AssertionError('bounded original-operation result deadline exceeded')
    try:
        started=await asyncio.to_thread(native,'thread/start',dict(cwd=str(options.output),approvalPolicy='never',sandbox='danger-full-access',developerInstructions='You are a disposable connector acceptance conversation. Use only local shell commands explicitly requested by the operator. Do not read other files, contact services, create agents, schedule wakes, or modify configuration. Reply to exact markers as requested.'))
        thread_id=started['thread']['id'];result['thread_id']=thread_id;save()
        # Obtain all target-generation fields through host-owned discovery, not a guessed identity.
        row=await asyncio.to_thread(resolve,root,'thread:'+thread_id,None,endpoint=endpoint)
        target=row['target'];result['target']=target;result['endpoint']=endpoint;save()
        client=authority.register(dict(client_name='cw665-busy',redirect_uris=[config['redirect_uris'][0]]))
        verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        code=authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client['client_id'],redirect_uri=client['redirect_uris'][0],resource=issuer+'/mcp',scopes=['control','observe','content.observe'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread_id)],code_challenge=challenge)
        async with httpx.AsyncClient(timeout=120) as http:
            exchange=await http.post(issuer+'/token',data=dict(grant_type='authorization_code',client_id=client['client_id'],code=code,redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=issuer+'/mcp'));exchange.raise_for_status();token=exchange.json()['access_token']
            grant_id=authority.authenticate(token).grant_id;result['grant_id']=grant_id;save()
            async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=120) as mcp_http:
                async with streamable_http_client(issuer+'/mcp',http_client=mcp_http) as streams:
                    async with ClientSession(streams[0],streams[1]) as connected:
                        session=connected;await session.initialize()
                        started=await asyncio.to_thread(native,'turn/start',dict(threadId=thread_id,input=[dict(type='text',text='Run the shell command sleep 45 exactly once, wait for it, then reply exactly BUSY_ORIGINAL_DONE. This bounded wait is the acceptance task.')]))
                        active=started['turn']['id'];result['original_turn']=active;save()
                        before=(await read())['thread']
                        assert any(t['id']==active and t['status']=='inProgress' for t in before['turns'])
                        error,value=await submit('reject','REJECT_MUST_NOT_APPEAR','cw665-reject')
                        assert error and 'session_busy' in json.dumps(value),value
                        after=(await read())['thread']
                        assert not any('REJECT_MUST_NOT_APPEAR' in json.dumps(item) for t in after['turns'] for item in t.get('items',[]))
                        result['checks']['reject_no_effect']=True;save()
                        error,value=await submit('queue','Reply exactly BUSY_QUEUE_DONE.','cw665-queue');assert not error,value
                        queued=operation(value);result['queue_operation']=queued['operation_id']
                        assert queued['result']['kind']=='native_queue'
                        current=(await read())['thread'];assert any(t['id']==active and t['status']=='inProgress' for t in current['turns'])
                        result['checks']['queue_preserves_active_turn']=True;save()
                        error,value=await submit('steer','After the requested sleep finishes, reply exactly BUSY_STEER_DONE instead.','cw665-steer');assert not error,value
                        steered=operation(value);result['steer_operation']=steered['operation_id'];assert steered['result']['turn_id']==active
                        result['checks']['steer_exact_active_turn']=True;save()
                        queued_final=await await_result(queued['operation_id']);steer_final=await await_result(steered['operation_id'])
                        result['queue_result']={k:queued_final.get(k) for k in ['execution','acceptance','answer']};result['steer_result']={k:steer_final.get(k) for k in ['execution','acceptance','answer']}
                        assert queued_final['execution']=='completed' and queued_final['answer']['text'].strip()=='BUSY_QUEUE_DONE'
                        assert steer_final['execution']=='completed' and steer_final['answer']['text'].strip()=='BUSY_STEER_DONE'
                        error,value=await submit('steer','IDLE_STEER_MUST_NOT_APPEAR','cw665-idle-steer');assert error and 'turn_unavailable' in json.dumps(value),value
                        result['checks']['idle_steer_refused_without_fallback']=True;save()
                        started=await asyncio.to_thread(native,'turn/start',dict(threadId=thread_id,input=[dict(type='text',text='Run shell sleep 45 exactly once, then reply INTERRUPT_ORIGINAL_DONE. This disposable work will be explicitly interrupted.')]))
                        original=started['turn']['id'];error,value=await submit('interrupt_then_submit','Reply exactly BUSY_INTERRUPT_REPLACEMENT_DONE.','cw665-interrupt');assert not error,value
                        interrupted=operation(value);result['interrupt_operation']=interrupted['operation_id'];assert interrupted['result']['interrupted_turn_id']==original
                        final=await await_result(interrupted['operation_id']);result['interrupt_result']={k:final.get(k) for k in ['execution','acceptance','answer']}
                        assert final['execution']=='completed' and final['answer']['text'].strip()=='BUSY_INTERRUPT_REPLACEMENT_DONE'
                        result['checks']['interrupt_exact_turn_and_one_replacement']=True
                        turns=(await read())['thread']['turns']
                        replacement=[t for t in turns if any(i.get('type')=='userMessage' and i.get('clientId')==interrupted['operation_id']+'.after-interrupt' for i in t.get('items',[]))]
                        assert len(replacement)==1
                        result['native_turns']=[dict(id=t['id'],status=t['status']) for t in turns]
                        result['stale_turn_evidence']='Live idle refusal and exact acknowledged active turn; changed-turn-between-observations refusal uses existing deterministic input-owner regression (no caller-selectable expected turn parameter).'
                        result['verdict']='PASS'
    except BaseException as error:
        result['error']=dict(type=type(error).__name__,message=str(error)[:2000]);raise
    finally:
        if thread_id:
            try:
                turns=(await read())['thread']['turns']
                for turn in turns:
                    if turn['status']=='inProgress':await asyncio.to_thread(native,'turn/interrupt',dict(threadId=thread_id,turnId=turn['id']))
                terminals=await asyncio.to_thread(native,'thread/backgroundTerminals/list',dict(threadId=thread_id))
                for terminal in terminals['data']:await asyncio.to_thread(native,'thread/backgroundTerminals/terminate',dict(threadId=thread_id,processId=terminal['processId']))
                await asyncio.to_thread(native,'thread/archive',dict(threadId=thread_id))
                result['cleanup']['owned_thread_archived']=True
            except BaseException as error:result['cleanup']['error']=type(error).__name__+': '+str(error)[:500]
        if grant_id:
            authority.revoke_grant(grant_id);result['cleanup']['own_grant_revoked']=True
        remaining=[]
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():continue
            try:
                if (process.stat().st_uid==os.getuid() and (process/'cwd').resolve(strict=True)==options.output.resolve()
                    and (process/'comm').read_text().strip() in ('sleep','bash','zsh','sh')):remaining.append(int(process.name))
            except (OSError,ValueError):pass
        result['cleanup']['owned_shell_processes_remaining']=remaining
        if remaining or not result['cleanup'].get('owned_thread_archived') or not result['cleanup'].get('own_grant_revoked'):result['verdict']='INCOMPLETE'
        connection_context.__exit__(None,None,None)
        save()
        print(json.dumps(dict(verdict=result['verdict'],checks=result['checks'],cleanup=result['cleanup'],receipt=str(options.output/'result.json'))))

if __name__=='__main__':main()
