import base64
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.controller_accounts import ControllerAccounts
from codex_wake.controller_auth import Actor, AuthError
from codex_wake.managed_inventory import InventoryError


UTC = 1800000000


class AccountObservationTests(unittest.TestCase):
    def test_remote_expiry_uses_qualified_upper_and_time_loss_refuses_private_read(self):
        from codex_wake.account_observation import execute
        from codex_wake.measurements import TimeUnavailable
        self.credentials()
        actor = self.actor(expires=200)
        with patch('codex_wake.measurements.utc_bounds', return_value=(198, 199)), \
                patch('codex_wake.account_observation.time', create=True) as guest_time:
            guest_time.time.side_effect = AssertionError('guest clock forbidden')
            result = execute(self.root, {'selector': 'alice'}, actor=actor, authorize=lambda: actor)
        self.assertEqual(result['result']['authentication']['state'], 'credentials_present')
        for clock, expected in (((199, 200), 'insufficient_scope'),
                                (TimeUnavailable('private-clock-detail'), 'qualified_time_unavailable')):
            with self.subTest(expected=expected), \
                    patch('codex_wake.measurements.utc_bounds', return_value=clock if isinstance(clock, tuple) else None,
                          side_effect=clock if isinstance(clock, Exception) else None), \
                    patch('codex_wake.account_observation._observation', side_effect=AssertionError('private read forbidden')):
                with self.assertRaises(AuthError) as held:
                    execute(self.root, {'selector': 'alice'}, actor=actor, authorize=lambda: actor)
                self.assertEqual(held.exception.code, expected)
                self.assertNotIn('private-clock-detail', str(held.exception))

    def test_cached_expiry_holds_unknown_without_mutating_credentials(self):
        from codex_wake.account_observation import execute
        from codex_wake.measurements import TimeUnavailable
        path = self.credentials()
        original = path.read_bytes()
        for bounds, expected in (((UTC+3598, UTC+3599), 'unknown'), ((UTC+3599, UTC+3600), 'stale')):
            with patch('codex_wake.measurements.utc_bounds', return_value=bounds):
                self.assertEqual(execute(self.root, {'selector': 'alice'})['result']['authentication']['freshness'], expected)
        with patch('codex_wake.measurements.utc_bounds', side_effect=TimeUnavailable('private-detail')):
            auth = execute(self.root, {'selector': 'alice'})['result']['authentication']
        self.assertEqual(auth['freshness'], 'unknown')
        self.assertEqual(auth['reason'], 'qualified_time_unavailable')
        self.assertFalse(auth['provider_verified'])
        self.assertEqual(auth['identity']['email'], 'alice@example.test')
        self.assertNotIn('private-detail', json.dumps(auth))
        self.assertEqual(path.read_bytes(), original)

    def setUp(self):
        clock = patch("codex_wake.measurements.utc_bounds", return_value=(UTC, UTC + 1))
        clock.start()
        self.addCleanup(clock.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'homes' / 'codex-alice'
        self.home.mkdir(parents=True, mode=0o700)
        self.config = self.root / 'controller-accounts.toml'
        self.config.write_text('[profiles]\nstate_root=' + json.dumps(str(self.root / 'homes')) + '\nknown_profiles=["alice"]\n[profiles.aliases]\nwork="alice"\n[configuration.account.codex-alice]\ncli_auth_credentials_store="file"\n')
        self.owner = ControllerAccounts(self.config, host=socket.gethostname(), environment=os.environ.get('WSL_DISTRO_NAME') or os.name)
        self.target = self.owner.execute('accounts.resolve', {'selector': 'alice'})['account']['target']

    def credentials(self, *, expired=False):
        claims = {'email': 'alice@example.test', 'exp': 1 if expired else UTC+3600,
                  'https://api.openai.com/auth': {'chatgpt_account_id': 'account-fixture', 'chatgpt_plan_type': 'pro'},
                  'secret_extra': 'NEVER_RETURN_PRIVATE_PAYLOAD'}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=').decode()
        value = {'auth_mode': 'chatgpt', 'tokens': {'id_token': 'eyJhbGciOiJub25lIn0.'+payload+'.fixture', 'access_token': 'NEVER_RETURN_ACCESS', 'refresh_token': 'NEVER_RETURN_REFRESH'}}
        path = self.home / 'auth.json'
        path.write_text(json.dumps(value)); path.chmod(0o600)
        return path

    def actor(self, target=None, *, scopes=('account.observe',), expires=None):
        return Actor('operator', 'owner', 'fixture-client', 'fixture-grant', 'local://fixture', 'wake:controller', frozenset(scopes), [self.target if target is None else target], UTC+120 if expires is None else expires)

    def test_cli_json_reports_only_unverified_cached_identity_without_native_or_network(self):
        self.credentials()
        from codex_wake.cli import main
        output = io.StringIO()
        with patch('subprocess.Popen', side_effect=AssertionError('native process forbidden')), patch('socket.socket', side_effect=AssertionError('network forbidden')), contextlib.redirect_stdout(output):
            self.assertEqual(main(['--wake-root', str(self.root), 'accounts', 'status', 'work', '--json']), 0)
        value = json.loads(output.getvalue()); auth = value['result']['authentication']
        self.assertEqual(value['operation'], 'accounts.status')
        self.assertEqual(auth['state'], 'credentials_present')
        self.assertIsNone(auth['signed_in'])
        self.assertEqual(auth['identity']['email'], 'alice@example.test')
        self.assertEqual(auth['plan'], 'pro')
        self.assertFalse(auth['provider_verified'])
        self.assertEqual(auth['evidence'], 'local_file_unverified')
        self.assertNotIn('NEVER_RETURN', output.getvalue())

    def test_expired_cached_identity_is_explicitly_stale_and_absence_signed_out_only_in_file_mode(self):
        from codex_wake.account_observation import execute
        self.credentials(expired=True)
        value = execute(self.root, {'selector': 'alice'})['result']['authentication']
        self.assertEqual(value['freshness'], 'stale')
        (self.home / 'auth.json').unlink()
        self.assertEqual(execute(self.root, {'selector': 'alice'})['result']['authentication']['state'], 'signed_out')
        self.config.write_text(self.config.read_text().replace('cli_auth_credentials_store="file"', 'cli_auth_credentials_store="auto"'))
        self.assertEqual(execute(self.root, {'selector': 'alice'})['result']['authentication']['state'], 'unknown')

    def test_nonprivate_malformed_and_symlinked_files_never_disclose_values(self):
        from codex_wake.account_observation import execute
        p = self.credentials(); p.chmod(0o644)
        value = execute(self.root, {'selector': 'alice'})
        self.assertEqual(value['result']['authentication']['state'], 'unavailable')
        self.assertNotIn('NEVER_RETURN', json.dumps(value))
        p.chmod(0o600);p.write_text('{"tokens":"NEVER_RETURN_MALFORMED"}')
        self.assertEqual(execute(self.root, {'selector': 'alice'})['result']['authentication']['state'], 'unknown')
        p.unlink();p.symlink_to(self.root / 'outside-auth.json')
        with self.assertRaises(InventoryError): execute(self.root, {'selector': 'alice'})

    def test_authorization_requires_exact_live_account_scope_and_rechecks_before_disclosure(self):
        from codex_wake.account_observation import execute
        self.credentials()
        for actor in (self.actor(scopes=('observe',)), self.actor(target={'host': socket.gethostname()}), self.actor(expires=UTC-1)):
            with self.assertRaises(AuthError): execute(self.root, {'selector': 'alice'}, actor=actor, authorize=lambda: actor)
        actor = self.actor(); calls=[]
        def revoked():
            calls.append(True)
            if len(calls)>1: raise AuthError('grant_revoked')
            return actor
        with self.assertRaises(AuthError): execute(self.root, {'selector': 'alice'}, actor=actor, authorize=revoked)
        self.config.write_text(self.config.read_text()+'\n# replaced configuration\n')
        with self.assertRaises(InventoryError): execute(self.root, {'selector': 'alice', 'expected_target': self.target})
        with self.assertRaises(AuthError): execute(self.root, {'selector': 'alice'}, actor=actor, authorize=lambda: actor)

    def test_protected_api_and_native_mcp_use_same_observation_and_reject_foreign_account(self):
        from codex_wake.account_observation import execute
        from codex_wake.controller_http import ProtectedOperations, TOOLS
        from codex_wake.controller_operations import ControllerOperations
        from codex_wake.managed_inventory import ManagedInventory
        from codex_wake.controller_client import OPERATIONS, MCP_TOOLS
        self.credentials()
        actor = self.actor()
        authority = type('Authority', (), {'authenticate': lambda unused, token: actor})()
        service=ProtectedOperations(authority, ControllerOperations(ManagedInventory(self.root), host=socket.gethostname(), environment=os.name, accounts=self.owner))
        observed=service.execute('fixture-token','accounts.status',{'selector':'alice'})
        self.assertEqual(observed['result']['authentication'], execute(self.root, {'selector':'alice'})['result']['authentication'])
        self.assertIn('accounts.status', OPERATIONS)
        self.assertEqual(TOOLS[MCP_TOOLS['accounts.status']][0], 'accounts.status')
        from codex_wake.mcp_server import CommandRunner
        local = self.root/'controller-messaging.json'
        local.write_text(json.dumps({'version':1,'local_caller': {'subject':actor.subject,'client_id':actor.client_id,'grant_id':actor.grant_id,'issuer':actor.issuer,'resource':actor.resource,'scopes':list(actor.scopes),'targets':actor.targets,'expires_at':actor.expires_at}}));local.chmod(0o600)
        value, failed=CommandRunner(wake_root=self.root).call(MCP_TOOLS['accounts.status'], {'selector':'alice'})
        self.assertFalse(failed, value)
        self.assertEqual(value['result']['authentication'], observed['result']['authentication'])
        actor = self.actor(scopes=('observe',))
        with self.assertRaises(AuthError): service.execute('fixture-token','accounts.status',{'selector':'alice'})


    def test_loopback_api_oauth_mcp_parity_revocation_and_target_replacement(self):
        import hashlib
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from codex_wake.controller_http import ControllerHTTPServer
        from codex_wake.controller_auth import OAuthAuthority
        from codex_wake.controller_operations import ControllerOperations
        from codex_wake.managed_inventory import ManagedInventory
        self.credentials()
        auth = OAuthAuthority(self.root / 'oauth.sqlite', issuer='https://fixture.test', resource='https://fixture.test/controller', now=lambda: UTC)
        client = auth.register({'redirect_uris': ['http://localhost/callback']})
        verifier = 'x' * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        code = auth.authorize(subject='operator', principal_kind='owner', client_id=client['client_id'],
            redirect_uri='http://localhost/callback', resource=auth.resource, scopes=['account.observe'],
            targets=[self.target], code_challenge=challenge)
        token = auth.token(dict(grant_type='authorization_code', client_id=client['client_id'], code=code,
            redirect_uri='http://localhost/callback', code_verifier=verifier, resource=auth.resource))['access_token']
        service = ControllerOperations(ManagedInventory(self.root), host=socket.gethostname(), environment=os.name, accounts=self.owner)
        server = ControllerHTTPServer(('127.0.0.1', 0), auth, service)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def request(path, body):
            req = Request('http://127.0.0.1:' + str(server.server_port) + path,
                data=json.dumps(body).encode(), headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
            try:
                with urlopen(req, timeout=5) as response: return response.status, json.load(response)
            except HTTPError as error: return error.code, json.load(error)
        api_body = {'operation':'accounts.status','arguments':{'selector':'work'}}
        mcp_body = {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'wake_controller_account_status','arguments':{'selector':'work'}}}
        try:
            status, api = request('/operations', api_body); self.assertEqual(status, 200)
            status, mcp = request('/mcp', mcp_body); self.assertEqual(status, 200)
            self.assertEqual(mcp['result']['structuredContent'], api)
            self.assertNotIn('NEVER_RETURN', json.dumps((api, mcp)))
            self.config.write_text(self.config.read_text()+'\n# configuration replaced\n')
            self.assertEqual(request('/operations', api_body)[0], 403)
            self.assertEqual(request('/mcp', mcp_body)[0], 403)
            auth.revoke_grant(auth.authenticate(token).grant_id)
            self.assertEqual(request('/operations', api_body)[0], 401)
            self.assertEqual(request('/mcp', mcp_body)[0], 401)
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=5)

if __name__ == '__main__': unittest.main()
