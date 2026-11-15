#!/usr/bin/env python3
"""Opt-in deployed OAuth/MCP permission acceptance on one empty native thread.

Run with the installed connector Python and an operator-private deployment config.
Local authority approval is explicit; all credentials remain process-local.
No prompt is expected to reach the native thread. Only this run's grants/thread
are revoked/archived. Receipts omit bearer tokens, codes and raw inventory.
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
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    # Reserve exclusively before any live effects; preserve every prior receipt.
    with args.receipt.open('x'):
        pass
    from codex_wake.external_connector import load_config
    from codex_wake.controller_auth import OAuthAuthority
    from codex_wake.local_sessions import discover
    from codex_wake.native_protocol import native_request
    from codex_wake.shared_app_server import locate_shared_endpoint
    config = load_config(args.config)
    root = Path(config['wake_root'])
    issuer = config['issuer'].rstrip('/')
    authority = OAuthAuthority(root/'external-oauth/authority.sqlite', issuer=issuer, resource=issuer+'/mcp')
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    protected_clients = {client for delegation in config.get('consent_delegations', []) for client in delegation['client_ids']}
    def protected_grants():
        with authority.connect() as db:
            return sorted(row for row in db.execute('SELECT id,subject,kind,client,scopes,targets,revoked FROM grants') if row[3] in protected_clients)
    baseline_grants = protected_grants()
    def http(path, body, token=None, form=False):
        headers = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
        if token: headers['Authorization'] = 'Bearer '+token
        data = (urlencode(body) if form else json.dumps(body)).encode()
        try:
            with urlopen(Request(issuer+path, data=data, headers=headers), timeout=35) as response:
                return response.status, json.loads(response.read() or b'{}')
        except HTTPError as error:
            return error.code, json.loads(error.read() or b'{}')
    sequence = 0
    def rpc(token, method, params=None):
        nonlocal sequence
        sequence += 1
        return http('/mcp', dict(jsonrpc='2.0', id=sequence, method=method, **({'params': params} if params is not None else {})), token)
    def tool(token, name, arguments):
        status, response = rpc(token, 'tools/call', dict(name=name, arguments=arguments))
        assert status == 200, dict(stage='MCP call', status=status)
        value = response['result']
        return value.get('structuredContent') or json.loads(value['content'][0]['text'])
    grants = []
    clients = []
    tokens = []
    thread_id = None
    report = dict(ticket=671, issuer=issuer, started_at=time.time(), source='installed package', checks={})
    endpoint = locate_shared_endpoint(timeout=10)
    def native(method, params):
        return native_request(endpoint, ['codex'], method, params, 30)
    try:
        with tempfile.TemporaryDirectory(prefix='cw671-permissions-') as directory:
            created = native('thread/start', dict(cwd=directory, approvalPolicy='never', sandbox='read-only'))['thread']
            thread_id = created['id']
            assert created.get('turns', []) == []
            rows = discover(root, endpoint, thread_id=thread_id)['sessions']
            assert len(rows) == 1 and rows[0]['thread_id'] == thread_id
            target = rows[0]['target']
            before = native('thread/read', dict(threadId=thread_id, includeTurns=False))['thread']
            assert before['status']['type'] == 'idle'
            assert native('thread/queue/list', dict(threadId=thread_id))['data'] == []
            def grant(scopes, scope_target, purpose):
                verifier = secrets.token_urlsafe(48)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                client = authority.register(dict(client_name='cw671-permissions-'+purpose, redirect_uris=[config['redirect_uris'][0]]))
                clients.append(client['client_id'])
                code = authority.authorize(subject=config['owner'], principal_kind='owner', client_id=client['client_id'], redirect_uri=client['redirect_uris'][0], resource=authority.resource, scopes=scopes, targets=[scope_target], code_challenge=challenge)
                status, value = http('/token', dict(grant_type='authorization_code', client_id=client['client_id'], code=code, redirect_uri=client['redirect_uris'][0], code_verifier=verifier, resource=authority.resource), form=True)
                assert status == 200, dict(stage='token exchange', status=status)
                token = value['access_token']
                identifier = authority.authenticate(token).grant_id
                grants.append(identifier)
                tokens.append(token)
                status, initialized = rpc(token, 'initialize', dict(protocolVersion='2025-03-26', capabilities={}, clientInfo=dict(name='cw671-permissions', version='1')))
                assert status == 200 and 'result' in initialized
                return token
            scope_target = dict(host=config['host'], environment=config['environment'], conversation_id=thread_id)
            readonly = grant(['observe'], scope_target, 'read-only')
            observed = tool(readonly, 'wake_environment_snapshot', {})
            assert observed.get('status') == 'completed', dict(stage='allowed read', result=observed.get('status'))
            snapshot = observed['result']
            assert snapshot['host'] == config['host'] and snapshot['environment'] == config['environment']
            # This is a terminal-placement projection, not a native-thread list.
            # A conversation-only grant has no terminal resources or content.
            for collection in ('sessions', 'unplaced_tabs', 'agents', 'bindings', 'unavailable'):
                assert snapshot[collection] == [], dict(stage='metadata isolation', collection=collection)
            report['checks']['allowed_scoped_read'] = True
            report['checks']['snapshot_ungranted_resources_absent'] = True
            content_request = dict(selector='thread:'+thread_id, turn_id='cw671-denied-content', expected_target=target)
            no_content = tool(readonly, 'wake_environment_conversations_observe', content_request)
            assert no_content.get('error') == 'insufficient_scope', dict(stage='metadata-only content refusal', status=no_content.get('status'), error=no_content.get('error'))
            report['checks']['target_content_without_content_scope_refused'] = 'insufficient_scope'
            request = dict(selector='thread:'+thread_id, prompt='CW671 denied input must not execute', policy='queue', idempotency_key='cw671-denied-'+thread_id, expected_target=target)
            denied = tool(readonly, 'wake_environment_conversations_input_submit', request)
            assert denied.get('error') == 'insufficient_scope', dict(stage='read-only write refusal', result=denied)
            report['checks']['read_only_write_refused'] = 'insufficient_scope'
            other_scope = dict(scope_target, conversation_id='cw671-different-conversation')
            limited_control = grant(['observe', 'control'], other_scope, 'other-target')
            outside = tool(limited_control, 'wake_environment_conversations_input_submit', request)
            assert outside.get('error') == 'insufficient_scope', dict(stage='target refusal', result=outside)
            report['checks']['outside_target_refused'] = 'insufficient_scope'
            other_content = grant(['observe', 'content.observe'], other_scope, 'other-target-content')
            outside_content = tool(other_content, 'wake_environment_conversations_observe', content_request)
            assert outside_content.get('error') == 'insufficient_scope', dict(stage='outside-target content refusal', status=outside_content.get('status'), error=outside_content.get('error'))
            report['checks']['outside_target_content_refused'] = 'insufficient_scope'
            control = grant(['observe', 'control'], scope_target, 'stale-generation')
            stale_target = dict(target, socket_generation='stale-cw671-generation')
            stale = tool(control, 'wake_environment_conversations_input_submit', dict(request, expected_target=stale_target))
            stale_code = stale.get('error')
            if isinstance(stale_code, dict): stale_code = stale_code.get('code')
            if stale_code is None: stale_code = (stale.get('result') or {}).get('reason')
            assert stale.get('status') == 'failed', dict(stage='stale generation refusal', result=stale)
            report['checks']['stale_generation_refused'] = stale_code
            report['stale_result'] = stale
            after = native('thread/read', dict(threadId=thread_id, includeTurns=False))['thread']
            assert after['status']['type'] == 'idle'
            assert native('thread/queue/list', dict(threadId=thread_id))['data'] == [], 'A denied queued input reached the disposable native thread'
            report['checks']['native_queued_user_inputs'] = 0
            report['checks']['native_idle_before_and_after'] = True
            report['native_history_limitation'] = 'New empty native thread includeTurns=true rejects list_turns; initial start turns empty, metadata remains idle, native queue remains empty. Denied requests use queue policy only.'
            report['thread_id'] = thread_id
            assert protected_grants() == baseline_grants, 'Existing operator grants changed'
            assert hashlib.sha256(args.config.read_bytes()).hexdigest() == config_hash, 'Connector policy changed'
            report['checks']['operator_grants_and_config_unchanged'] = True
    finally:
        for identifier in grants: authority.revoke_grant(identifier)
        revoked = []
        for token in tokens:
            status, unused = rpc(token, 'tools/list')
            revoked.append(status == 401)
        report['checks']['temporary_grants_revoked'] = len(grants) > 0 and all(revoked)
        report['temporary_grants'] = grants
        report['temporary_clients'] = clients
        if thread_id is not None:
            native('thread/archive', dict(threadId=thread_id))
            report['checks']['owned_thread_archived'] = True
        report['completed_at'] = time.time()
        report['memory_disposition'] = 'forbidden'
        report['memory_reason'] = 'No explicit memory write requested'
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(report, indent=2))
        args.receipt.chmod(0o600)
    assert report['checks']['temporary_grants_revoked']
    print(json.dumps(dict(ticket=671, status='passed', checks=report['checks'], receipt=str(args.receipt))))


if __name__ == '__main__': main()
