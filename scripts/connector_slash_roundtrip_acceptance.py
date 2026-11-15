#!/usr/bin/env python3
"""Opt-in deployed OAuth/MCP structured slash acceptance on a disposable thread.

Uses a separate locally authorized exact-conversation grant and public token/MCP
endpoints. Credentials stay in memory; receipts contain only synthetic evidence.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    from codex_wake.external_connector import load_config
    from codex_wake.controller_auth import OAuthAuthority
    from codex_wake.local_sessions import discover
    from codex_wake.native_protocol import native_request
    from codex_wake.shared_app_server import locate_shared_endpoint, SharedAppServerReader
    config = load_config(args.config)
    root = Path(config['wake_root']); issuer = config['issuer'].rstrip('/')
    authority = OAuthAuthority(root/'external-oauth/authority.sqlite', issuer=issuer, resource=issuer+'/mcp')
    endpoint = locate_shared_endpoint(timeout=10)
    report = dict(ticket=670, status='running', boundary='deployed public HTTPS OAuth/MCP', checks={})
    thread_id = grant_id = token = None
    sequence = 0
    def native(method, params):
        return native_request(endpoint, ['codex'], method, params, 60)
    def http(path, body, bearer=None, form=False):
        headers = {'Accept':'application/json, text/event-stream', 'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json'}
        if bearer: headers['Authorization'] = 'Bearer '+bearer
        payload = (urlencode(body) if form else json.dumps(body)).encode()
        try:
            with urlopen(Request(issuer+path, data=payload, headers=headers), timeout=60) as response:
                return response.status, json.loads(response.read() or b'{}')
        except HTTPError as error:
            return error.code, json.loads(error.read() or b'{}')
    def rpc(method, params=None):
        nonlocal sequence
        sequence += 1
        return http('/mcp', dict(jsonrpc='2.0', id=sequence, method=method, **({'params':params} if params is not None else {})), token)
    def tool(name, arguments):
        status, body = rpc('tools/call', dict(name=name, arguments=arguments))
        assert status == 200, dict(stage='MCP tool', status=status)
        assert 'result' in body, dict(stage='MCP RPC error', error=body.get('error'))
        value = body['result']
        return value.get('structuredContent') or json.loads(value['content'][0]['text'])
    def user_inputs(thread):
        return [(item.get('clientId'),item.get('content')) for turn in thread['turns'] for item in turn.get('items',[]) if item.get('type')=='userMessage']
    try:
        with tempfile.TemporaryDirectory(prefix='cw670-slash-') as cwd:
            created = native('thread/start', dict(cwd=cwd, approvalPolicy='never', sandbox='read-only'))['thread']
            thread_id = created['id']
            # Empty native conversations do not yet expose history. One separate
            # setup turn makes before/after user-input evidence available.
            native('turn/start', dict(threadId=thread_id, input=[dict(type='text',text='Reply exactly CW670_SETUP_READY. Do not use tools.')]))
            deadline = time.monotonic()+120
            while time.monotonic()<deadline:
                with SharedAppServerReader(endpoint, timeout=10) as reader: metadata=reader.read_thread(thread_id)
                if metadata['status']['type']=='idle': break
                time.sleep(1)
            assert metadata['status']['type']=='idle', 'Disposable setup did not finish'
            before = native('thread/read', dict(threadId=thread_id, includeTurns=True))['thread']
            before_inputs = user_inputs(before)
            assert len(before_inputs)==1, 'One separate native setup input required'
            rows = discover(root, endpoint, thread_id=thread_id)['sessions']
            assert len(rows)==1 and rows[0]['thread_id']==thread_id
            target = rows[0]['target']; selector='thread:'+thread_id
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            client = authority.register(dict(client_name='cw670-slash',redirect_uris=[config['redirect_uris'][0]]))
            code = authority.authorize(subject=config['owner'],principal_kind='owner',client_id=client['client_id'],redirect_uri=client['redirect_uris'][0],resource=authority.resource,scopes=['observe','content.observe','control'],targets=[dict(host=config['host'],environment=config['environment'],conversation_id=thread_id)],code_challenge=challenge)
            status, value = http('/token',dict(grant_type='authorization_code',client_id=client['client_id'],code=code,redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=authority.resource),form=True)
            assert status==200, dict(stage='token',status=status)
            token=value['access_token'];grant_id=authority.authenticate(token).grant_id
            status, initialized=rpc('initialize',dict(protocolVersion='2025-03-26',capabilities={},clientInfo=dict(name='cw670-slash',version='1')))
            assert status==200 and 'result' in initialized
            status, listed=rpc('tools/list');assert status==200
            names=[row['name'] for row in listed['result']['tools']]
            def named(suffix):
                matches=[name for name in names if name.endswith('_slash_'+suffix)]
                assert len(matches)==1, dict(stage='tool discovery',suffix=suffix,matches=matches)
                return matches[0]
            catalog=tool(named('list'),dict(selector=selector,expected_target=target))
            commands=catalog.get('commands') or catalog.get('result',{}).get('commands')
            assert any(c['command']=='/status' and c.get('method')=='thread/read' for c in commands), 'Qualified harmless /status absent'
            assert catalog.get('prompt_fallback') is False
            report['checks']['supported_catalog_discovered']=True
            result=tool(named('run'),dict(selector=selector,expected_target=target,command='/status',idempotency_key='cw670-status-'+secrets.token_hex(8)))
            operation=result['result']['operation'];operation_id=operation['operation_id']
            assert operation['execution']=='completed', operation['execution']
            readback=tool(named('result'),dict(operation_id=operation_id))['result']['operation']
            assert readback['operation_id']==operation_id and readback['execution']=='completed'
            proof=readback['result']
            assert proof['command']=='/status' and proof['native_method']=='thread/read'
            assert proof['model_submission'] is False and proof['observation']['thread_id']==thread_id
            assert proof['completed'] is True
            report['checks']['structured_status_correlated_result']=True
            report['operation_id']=operation_id
            unsupported=tool(named('run'),dict(selector=selector,expected_target=target,command='/model',idempotency_key='cw670-unsupported-'+secrets.token_hex(8)))
            error=unsupported.get('error')
            error_code=error.get('code') if isinstance(error,dict) else error
            assert unsupported.get('status')=='failed' and error_code=='unsupported_slash_command', unsupported
            report['checks']['unsupported_refused_without_fallback']='unsupported_slash_command'
            after=native('thread/read',dict(threadId=thread_id,includeTurns=True))['thread']
            assert user_inputs(after)==before_inputs, 'Slash action submitted an ordinary native user input'
            assert after['status']['type']=='idle'
            assert native('thread/queue/list',dict(threadId=thread_id))['data']==[]
            assert after.get('name')==before.get('name') and after['cwd']==before['cwd']
            report['checks']['native_user_inputs_unchanged']=True
            report['checks']['native_queue_empty_and_idle']=True
            report['checks']['native_name_and_cwd_unchanged']=True
            report['thread_id']=thread_id
            report['status']='passed'
    finally:
        try:
            if grant_id is not None:
                authority.revoke_grant(grant_id)
                status, unused=rpc('tools/list')
                report['checks']['temporary_grant_revoked']=status==401
                assert status==401, 'Own revoked bearer still accepted'
        finally:
            try:
                if thread_id is not None:
                    native('thread/archive',dict(threadId=thread_id))
                    report['checks']['owned_thread_archived']=True
            finally:
                if report['status']=='running':report['status']='failed'
                report['memory_disposition']='forbidden'
                report['memory_reason']='No explicit memory write requested'
                args.receipt.parent.mkdir(parents=True,exist_ok=True)
                args.receipt.write_text(json.dumps(report,indent=2));args.receipt.chmod(0o600)
                print(json.dumps(report))


if __name__=='__main__':main()
