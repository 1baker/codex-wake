import base64
import hashlib
import tempfile
import unittest
from pathlib import Path


class OAuthTests(unittest.TestCase):
    def test_default_oauth_lifetimes_use_lower_issue_bound_and_upper_expiry_guard(self):
        from unittest.mock import patch
        from codex_wake.controller_auth import OAuthAuthority,AuthError
        from codex_wake.measurements import TimeUnavailable
        with tempfile.TemporaryDirectory() as directory:
            auth=OAuthAuthority(Path(directory)/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            client=auth.register(dict(redirect_uris=['http://localhost/callback']))
            verifier='x'*43
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            with patch('codex_wake.measurements.utc_bounds',return_value=(100,110)):
                code=auth.authorize(subject='owner',principal_kind='owner',client_id=client['client_id'],
                    redirect_uri=client['redirect_uris'][0],resource=auth.resource,scopes=['observe'],
                    targets=[dict(host='fixture')],code_challenge=challenge)
                with auth.connect() as database:
                    self.assertEqual(database.execute('SELECT expires FROM codes').fetchone()[0],220)
                tokens=auth.token(dict(grant_type='authorization_code',client_id=client['client_id'],
                    code=code,redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=auth.resource))
                actor=auth.authenticate(tokens['access_token'])
            self.assertEqual(actor.expires_at,700)
            self.assertEqual(tokens['expires_in'],590)
            with patch('codex_wake.measurements.utc_bounds',return_value=(699,701)):
                with self.assertRaises(AuthError):auth.authenticate(tokens['access_token'])
            with patch('codex_wake.measurements.utc_bounds',side_effect=TimeUnavailable('unqualified')):
                self.assertEqual(auth.revoke_grant(actor.grant_id)['status'],'revoked')

    def test_default_clock_loss_refuses_new_grant_without_partial_authority(self):
        from unittest.mock import patch
        from codex_wake.controller_auth import OAuthAuthority,AuthError
        from codex_wake.measurements import TimeUnavailable
        with tempfile.TemporaryDirectory() as directory:
            auth=OAuthAuthority(Path(directory)/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            client=auth.register(dict(redirect_uris=['http://localhost/callback']))
            challenge=base64.urlsafe_b64encode(hashlib.sha256(('x'*43).encode()).digest()).rstrip(b'=').decode()
            with patch('codex_wake.measurements.utc_bounds',side_effect=TimeUnavailable('unqualified')):
                with self.assertRaises(AuthError) as held:
                    auth.authorize(subject='owner',principal_kind='owner',client_id=client['client_id'],
                        redirect_uri=client['redirect_uris'][0],resource=auth.resource,scopes=['observe'],
                        targets=[dict(host='fixture')],code_challenge=challenge)
            self.assertEqual(held.exception.code,'qualified_time_unavailable')
            with auth.connect() as database:
                self.assertEqual(database.execute('SELECT COUNT(*) FROM grants').fetchone()[0],0)
                self.assertEqual(database.execute('SELECT COUNT(*) FROM codes').fetchone()[0],0)

    def test_pkce_grant_exact_resource_rotation_and_independent_revocation(self):
        from codex_wake.controller_auth import OAuthAuthority, AuthError
        with tempfile.TemporaryDirectory() as directory:
            auth = OAuthAuthority(Path(directory) / 'auth.sqlite', issuer='https://wake.test', resource='https://wake.test/controller', now=lambda: 100)
            client = auth.register({'redirect_uris': ['http://127.0.0.1:45000/callback'], 'client_name': 'fixture'})
            verifier = 'x' * 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            code = auth.authorize(subject='alice', principal_kind='owner', client_id=client['client_id'], redirect_uri=client['redirect_uris'][0], resource=auth.resource, scopes=['observe'], targets=[{'host': 'fixture'}], code_challenge=challenge)
            args = dict(grant_type='authorization_code', client_id=client['client_id'], code=code, redirect_uri=client['redirect_uris'][0], code_verifier=verifier, resource=auth.resource)
            tokens = auth.token(args)
            actor = auth.authenticate(tokens['access_token'])
            self.assertEqual((actor.subject, actor.client_id, actor.scopes), ('alice', client['client_id'], frozenset({'observe'})))
            self.assertEqual(actor.targets, [{'host': 'fixture'}])
            with self.assertRaises(AuthError): auth.token(args)
            with self.assertRaises(AuthError): auth.token(dict(grant_type='refresh_token', refresh_token=tokens['refresh_token'], client_id=client['client_id'], resource=auth.resource + '/other'))
            rotated = auth.token(dict(grant_type='refresh_token', refresh_token=tokens['refresh_token'], client_id=client['client_id'], resource=auth.resource))
            with self.assertRaises(AuthError): auth.authenticate(tokens['access_token'])
            self.assertEqual(auth.authenticate(rotated['access_token']).grant_id, actor.grant_id)
            auth.revoke_grant(actor.grant_id)
            with self.assertRaises(AuthError): auth.authenticate(rotated['access_token'])

    def test_store_identity_grant_round_trips_without_broadening_targets(self):
        from codex_wake.controller_auth import OAuthAuthority, AuthError
        with tempfile.TemporaryDirectory() as directory:
            auth = OAuthAuthority(Path(directory) / 'auth.sqlite', issuer='https://wake.test', resource='https://wake.test/controller')
            client = auth.register({'redirect_uris': ['http://localhost/callback']})
            verifier = 'x' * 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            target = dict(host='fixture', environment='test', store_id='stable-stock', home='/fixture/stock', home_generation='1:2')
            values = dict(subject='owner', principal_kind='owner', client_id=client['client_id'],
                redirect_uri=client['redirect_uris'][0], resource=auth.resource,
                scopes=['configuration.observe'], targets=[target], code_challenge=challenge)
            code = auth.authorize(**values)
            token = auth.token(dict(grant_type='authorization_code', code=code, code_verifier=verifier,
                redirect_uri=client['redirect_uris'][0], resource=auth.resource, client_id=client['client_id']))['access_token']
            self.assertEqual(auth.authenticate(token).targets, [target])
            with self.assertRaises(AuthError):
                auth.authorize(**dict(values, targets=[dict(target, arbitrary_path='/unapproved')]))

    def test_http_api_and_oauth_mcp_share_target_scopes_and_reauthenticate(self):
        import json
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from codex_wake.controller_http import ControllerHTTPServer
        from codex_wake.controller_auth import OAuthAuthority
        from codex_wake.controller_operations import ControllerOperations
        from codex_wake.managed_inventory import ManagedInventory, Observation
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = ManagedInventory(root / 'wake', now=lambda: 100)
            for account in ('alice', 'bob'):
                inventory.enroll(Observation('codex', 'account:' + account, account, '/fixture', 'ready', 100, 'native_metadata', {'pid': 123, 'start_ticks': 42, 'boot_id': 'fixture'}, [], {}), operator=True)
            auth = OAuthAuthority(root / 'auth.sqlite', issuer='https://wake.test', resource='https://wake.test/controller')
            client = auth.register({'redirect_uris': ['http://127.0.0.1:45000/callback']})
            verifier = 'x' * 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            code = auth.authorize(subject='robot', principal_kind='service', client_id=client['client_id'], redirect_uri=client['redirect_uris'][0], resource=auth.resource, scopes=['observe'], targets=[{'host': 'fixture', 'namespace': 'account:alice'}], code_challenge=challenge)
            token = auth.token(dict(grant_type='authorization_code', client_id=client['client_id'], code=code, redirect_uri=client['redirect_uris'][0], code_verifier=verifier, resource=auth.resource))['access_token']
            server = ControllerHTTPServer(('127.0.0.1', 0), auth, ControllerOperations(inventory, host='fixture', environment='test'))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            def request(path, body, bearer=token, headers=None):
                req = Request('http://127.0.0.1:' + str(server.server_port) + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + bearer, **(headers or {})})
                try:
                    with urlopen(req) as response: return response.status, json.load(response)
                except HTTPError as error: return error.code, json.load(error)
            try:
                status, api = request('/operations', {'operation': 'inventory.list', 'arguments': {}})
                self.assertEqual(status, 200)
                self.assertEqual(api['actor']['subject'], 'robot')
                self.assertEqual([r['target']['namespace'] for r in api['result']['resources']], ['account:alice'])
                status, mcp = request('/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'wake_controller_list', 'arguments': {}}})
                self.assertEqual(mcp['result']['structuredContent'], api)
                status, denied = request('/operations', {'operation': 'inventory.resolve', 'arguments': {'selector': 'bob'}})
                self.assertEqual(status, 403)
                status, denied = request('/operations', {'operation': 'runtime.input', 'arguments': {}})
                self.assertEqual(status, 403)
                status, denied = request('/operations', {'operation': 'inventory.list', 'arguments': {}}, headers={'X-Wake-Subject': 'owner'})
                self.assertEqual(status, 400)
                status, missing = request('/operations', {'operation': 'inventory.resolve', 'arguments': {'selector': 'missing'}})
                self.assertEqual((status, missing['error']['code']), (400, 'target_not_found'))
                original = api['result']['resources'][0]
                inventory.reconcile(original['id'], Observation('codex', 'account:alice', 'alice', '/fixture', 'ready', 100, 'native_metadata', {'pid': 123, 'start_ticks': 99, 'boot_id': 'fixture'}, [], {}))
                status, stale = request('/operations', {'operation': 'inventory.resolve', 'arguments': {'selector': 'alice', 'expected_target': original['target']}})
                self.assertEqual((status, stale['error']['code']), (400, 'stale_target'))
                actor = auth.authenticate(token)
                self.assertEqual(auth.revoke_grant(actor.grant_id)['cancellation'], 'not_configured')
                self.assertEqual(request('/operations', {'operation': 'inventory.list', 'arguments': {}})[0], 401)
                self.assertEqual(request('/mcp', {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})[0], 401)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_refresh_replay_and_expiry_preserve_unrelated_principals(self):
        from codex_wake.controller_auth import OAuthAuthority, AuthError
        with tempfile.TemporaryDirectory() as directory:
            clock = [100]
            auth = OAuthAuthority(Path(directory) / 'auth.sqlite', issuer='https://wake.test', resource='https://wake.test/controller', now=lambda: clock[0])
            def grant(subject, scopes):
                client = auth.register({'redirect_uris': ['http://localhost/callback']})
                verifier = 'x' * 43
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                code = auth.authorize(subject=subject, principal_kind='service', client_id=client['client_id'], redirect_uri='http://localhost/callback', resource=auth.resource, scopes=scopes, targets=[{'host': 'fixture'}], code_challenge=challenge)
                return client, auth.token(dict(grant_type='authorization_code', client_id=client['client_id'], code=code, redirect_uri='http://localhost/callback', code_verifier=verifier, resource=auth.resource))
            alice, original = grant('alice', ['observe'])
            bob, separate = grant('bob', ['recovery'])
            refresh = dict(grant_type='refresh_token', client_id=alice['client_id'], refresh_token=original['refresh_token'], resource=auth.resource)
            rotated = auth.token(refresh)
            with self.assertRaises(AuthError): auth.token(refresh)
            with self.assertRaises(AuthError): auth.authenticate(rotated['access_token'])
            self.assertEqual(auth.authenticate(separate['access_token']).subject, 'bob')
            clock[0] = 701
            with self.assertRaises(AuthError): auth.authenticate(separate['access_token'])
            with self.assertRaises(ValueError): OAuthAuthority(auth.path, issuer='https://another.test', resource=auth.resource)

    def test_integrated_account_grants_filter_each_account_and_redact_configuration(self):
        from codex_wake.controller_auth import OAuthAuthority, AuthError
        from codex_wake.controller_accounts import ControllerAccounts
        from codex_wake.controller_operations import ControllerOperations
        from codex_wake.controller_http import ProtectedOperations
        from codex_wake.managed_inventory import ManagedInventory
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            homes = root / 'homes'
            for account in ('alice', 'bob'):
                (homes / ('codex-' + account)).mkdir(parents=True)
            config = root / 'controller-accounts.toml'
            config.write_text('[profiles]\nstate_root = "' + str(homes) + '"\nknown_profiles = ["alice", "bob"]\n[configuration.base.mcp_servers.example.env]\nAPI_KEY = "private-fixture"\n')
            accounts = ControllerAccounts(config, host='host', environment='test')
            target = accounts.execute('accounts.resolve', {'selector': 'alice'})['account']['target']
            authority = OAuthAuthority(root / 'oauth.sqlite', issuer='https://wake.test', resource='https://wake.test/mcp')
            client = authority.register({'redirect_uris': ['http://localhost/callback']})
            verifier = 'x' * 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            code = authority.authorize(subject='service-alice', principal_kind='service',
                client_id=client['client_id'], redirect_uri=client['redirect_uris'][0], resource=authority.resource,
                scopes=['account.observe', 'configuration.observe'], targets=[target], code_challenge=challenge)
            token = authority.token(dict(grant_type='authorization_code', client_id=client['client_id'],
                code=code, redirect_uri=client['redirect_uris'][0], code_verifier=verifier,
                resource=authority.resource))['access_token']
            service = ProtectedOperations(authority, ControllerOperations(ManagedInventory(root / 'wake'),
                host='host', environment='test', accounts=accounts))
            rows = service.execute(token, 'accounts.list', {})['result']['accounts']
            self.assertEqual([row['id'] for row in rows], ['codex-alice'])
            view = service.execute(token, 'configuration.explain', {'selector': 'alice'})
            self.assertNotIn('private-fixture', str(view))
            with self.assertRaises(AuthError):
                service.execute(token, 'configuration.explain', {'selector': 'bob'})
            with self.assertRaises(AuthError):
                service.execute(token, 'accounts.resolve', {'selector': 'bob'})
            config.write_text(config.read_text() + '\n# new generation\n')
            with self.assertRaises(AuthError):
                service.execute(token, 'accounts.resolve', {'selector': 'alice'})

    def test_revocation_commits_before_requesting_owned_work_cancellation(self):
        from codex_wake.controller_auth import OAuthAuthority, AuthError
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            token_holder = []
            def cancelled(grant_id, *, issuer, resource):
                with self.assertRaises(AuthError):
                    auth.authenticate(token_holder[0])
                calls.append((grant_id, issuer, resource))
                return {'cancellation': 'requested', 'uncertain_effects': ['owned-fixture']}
            auth = OAuthAuthority(Path(directory) / 'auth.sqlite', issuer='https://wake.test',
                resource='https://wake.test/mcp', on_revoke=cancelled)
            client = auth.register({'redirect_uris': ['http://localhost/callback']})
            verifier = 'x' * 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            code = auth.authorize(subject='operator', principal_kind='owner', client_id=client['client_id'],
                redirect_uri=client['redirect_uris'][0], resource=auth.resource, scopes=['observe'],
                targets=[{'host': 'fixture'}], code_challenge=challenge)
            token = auth.token(dict(grant_type='authorization_code', client_id=client['client_id'],
                code=code, redirect_uri=client['redirect_uris'][0], code_verifier=verifier, resource=auth.resource))['access_token']
            token_holder.append(token)
            grant = auth.authenticate(token).grant_id
            outcome = auth.revoke_grant(grant)
            self.assertEqual(calls, [(grant, auth.issuer, auth.resource)])
            self.assertEqual(outcome['cancellation'], 'requested')

    def test_interrupted_cancellation_request_is_recovered_after_authority_restart(self):
        from codex_wake.controller_auth import OAuthAuthority
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.sqlite'
            def interrupted(*args, **kwargs):
                raise SystemExit('fixture process termination')
            first = OAuthAuthority(path, issuer='https://wake.test', resource='https://wake.test/mcp', on_revoke=interrupted)
            with self.assertRaises(SystemExit):
                first.revoke_grant('owned-fixture-grant')
            recovered = []
            def cancelled(grant_id, **context):
                recovered.append(grant_id)
                return {'cancellation': 'requested', 'uncertain_effects': []}
            restarted = OAuthAuthority(path, issuer='https://wake.test', resource='https://wake.test/mcp', on_revoke=cancelled)
            self.assertEqual(recovered, ['owned-fixture-grant'])
            restarted.recover_revocations()
            self.assertEqual(recovered, ['owned-fixture-grant'])
