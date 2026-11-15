#!/usr/bin/env python3
"""Opt-in deployed connector duplicate-input acceptance on one disposable thread.

Run with the installed connector Python. Secrets stay in process memory; only a
credential-free receipt is retained. No operator conversation is addressed.
"""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from codex_wake.controller_auth import OAuthAuthority
from codex_wake.local_sessions import discover
from codex_wake.native_protocol import native_request
from codex_wake.shared_app_server import locate_shared_endpoint


def decode(result):
    if getattr(result,'structured_content',None) is not None:return result.structured_content
    return json.loads(next(c.text for c in result.content if c.type=='text'))


async def main():
    config=json.loads((Path.home()/'.config/codex-wake/external-connector.json').read_text())
    root=Path(config['wake_root']);issuer=config['issuer'];endpoint=locate_shared_endpoint(timeout=10)
    authority=OAuthAuthority(root/'external-oauth/authority.sqlite',issuer=issuer,resource=issuer+'/mcp')
    output=Path.home()/'.local/state/codex-wake/connector-acceptance-spec/duplicate-live.json'
    grant=None;thread=None;receipt=dict(ticket=664,status='running',boundary='deployed HTTPS OAuth/MCP')
    def native(method,args):return native_request(endpoint,['codex'],method,args,60)
    try:
        with tempfile.TemporaryDirectory(prefix='cw664-') as cwd:
            thread=native('thread/start',dict(cwd=cwd,approvalPolicy='never',sandbox='read-only'))['thread']['id']
            native('turn/start',dict(threadId=thread,input=[dict(type='text',text='Reply exactly setup-ready. Do not use tools.')]))
            deadline=time.monotonic()+120
            from codex_wake.shared_app_server import SharedAppServerReader
            while time.monotonic()<deadline:
                with SharedAppServerReader(endpoint,timeout=10) as reader:
                    metadata=reader.read_thread(thread)
                if metadata.get('status',{}).get('type')=='idle':break
                await asyncio.sleep(1)
            assert metadata.get('status',{}).get('type')=='idle','setup turn did not finish'
            receipt['setup_turn']='completed separate native preparation'
            selected=discover(root,endpoint,thread_id=thread)['sessions']
            assert len(selected)==1, 'exact disposable thread discovery required'
            target=selected[0]['target']
            verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            redirect=config['redirect_uris'][0]
            async with httpx.AsyncClient(timeout=70) as http:
                reg=await http.post(issuer+'/register',json=dict(client_name='cw664-duplicate',redirect_uris=[redirect]));reg.raise_for_status();client=reg.json()['client_id']
                code=authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client,redirect_uri=redirect,resource=issuer+'/mcp',scopes=['observe','content.observe','control'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread)],code_challenge=challenge)
                response=await http.post(issuer+'/token',data=dict(grant_type='authorization_code',client_id=client,code=code,redirect_uri=redirect,code_verifier=verifier,resource=issuer+'/mcp'));response.raise_for_status();token=response.json()['access_token'];grant=authority.authenticate(token).grant_id
                async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=70) as transport:
                    async with streamable_http_client(issuer+'/mcp',http_client=transport) as streams:
                        async with ClientSession(streams[0],streams[1]) as session:
                            await session.initialize()
                            args=dict(selector='thread:'+thread,prompt='Reply exactly with duplicate-protection-confirmed. Do not use tools.',policy='reject',idempotency_key='cw664-'+secrets.token_hex(8),expected_target=target)
                            receipt['intent_key']=args['idempotency_key']
                            receipt['thread_id']=thread
                            first=decode(await session.call_tool('wake_environment_conversations_input_submit',args));assert first['status']=='completed',first
                            first=first['result']['operation'];identifier=first['operation_id'];receipt['operation_id']=identifier
                            second=decode(await session.call_tool('wake_environment_conversations_input_submit',args));assert second['result']['operation']['operation_id']==identifier
                            conflict=decode(await session.call_tool('wake_environment_conversations_input_submit',dict(args,prompt='Different intent must be refused.')))
                            assert 'idempotency_conflict' in json.dumps(conflict),conflict
                            deadline=time.monotonic()+120
                            result=first
                            while time.monotonic()<deadline:
                                result=decode(await session.call_tool('wake_environment_conversations_input_result',dict(operation_id=identifier)))['result']['operation']
                                if result['phase']=='terminal':break
                                await asyncio.sleep(1)
                            assert result['execution']=='completed',result
                            assert result['answer']['text'].strip()=='duplicate-protection-confirmed',result
                            observed=native('thread/read',dict(threadId=thread,includeTurns=True))['thread']
                            inputs=[item for turn in observed['turns'] for item in turn.get('items',[]) if item.get('type')=='userMessage' and item.get('clientId')==identifier]
                            assert len(inputs)==1,len(inputs)
                            receipt.update(status='passed',same_operation=True,native_input_count=1,conflicting_payload='refused',answer=result['answer']['text'],execution=result['execution'],native_turn_id=result['answer']['turn_id'])
    finally:
        try:
            if thread is not None:
                native('thread/archive',dict(threadId=thread));receipt['disposable_thread']='archived'
        finally:
            try:
                if grant is not None:
                    authority.revoke_grant(grant);receipt['temporary_grant']='revoked'
            finally:
                output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2));output.chmod(0o600)
                if receipt['status']=='running':receipt['status']='failed'
                output.write_text(json.dumps(receipt,indent=2))
                print(json.dumps(receipt))



if __name__=='__main__':asyncio.run(main())
