"""Private bearer boundary: credentials never enter public readiness results."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from codex_wake.grok_provider_auth import GrokSession

CLOCK = dict(reason='authenticated_counter_only', counter=dict(
    epoch='00000000-0000-0000-0000-000000000001', counter=1000, frequency=1000, rate_ppm=0))


class GrokSessionTest(unittest.TestCase):
    def test_native_session_status_is_sanitized_and_bearer_requires_qualified_time(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            auth.write_text(json.dumps({'https://accounts.x.ai/sign-in': {
                'key': 'private-session-secret', 'auth_mode': 'web_login',
                'user_id': 'account-one', 'expires_at': '2030-01-01T00:00:00Z'}}))
            os.chmod(auth, 0o600)
            session = GrokSession(auth)
            status = session.status()
            self.assertEqual(status['authentication'], 'present')
            self.assertEqual(status['inference'], 'unverified')
            self.assertNotIn('private-session-secret', json.dumps(status))
            with self.assertRaisesRegex(ValueError, 'qualified_time_required'):
                session.bearer(None)
            self.assertEqual(session.bearer(1800000000), 'private-session-secret')

    def test_private_bearer_holds_expired_and_ambiguous_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            value = {'key': 'private-secret', 'auth_mode': 'oidc',
                     'expires_at': '2020-01-01T00:00:00Z'}
            auth.write_text(json.dumps({'https://auth.x.ai': value}))
            os.chmod(auth, 0o600)
            session = GrokSession(auth)
            with self.assertRaisesRegex(ValueError, 'native_refresh_required'):
                session.bearer(1800000000)
            auth.write_text(json.dumps({'https://auth.x.ai': value, 'other': value}))
            with self.assertRaisesRegex(ValueError, 'missing_or_ambiguous'):
                session.bearer(1800000000)

    def test_registration_pins_account_identity_across_native_rotation(self):
        from codex_wake.grok_provider_auth import GrokAccounts
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            value = {'key': 'first-secret', 'auth_mode': 'oidc', 'user_id': 'one',
                     'expires_at': '2030-01-01T00:00:00Z'}
            auth.write_text(json.dumps({'https://auth.x.ai': value}))
            os.chmod(auth, 0o600)
            accounts = GrokAccounts(Path(directory) / 'wake')
            accounts.register('personal', 'Personal Grok', auth)
            self.assertEqual(accounts.status('personal')['authentication'], 'present')
            value.update(key='rotated-secret', user_id='two')
            auth.write_text(json.dumps({'https://auth.x.ai': value}))
            self.assertEqual(accounts.status('personal')['authentication'], 'account_changed')
            with self.assertRaisesRegex(ValueError, 'account_changed'):
                accounts.bearer('personal', 1800000000)

    def test_login_never_relays_native_errors_or_treats_exit_zero_as_sign_in(self):
        from unittest.mock import patch
        from codex_wake.grok_provider_auth import login
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'grok'
            executable.write_text('#!/bin/sh\necho private-provider-secret >&2\nexit 0\n')
            executable.chmod(0o700)
            events = []
            with patch('codex_wake.measurements.snapshot', return_value=CLOCK):
                result = login(executable, Path(directory) / 'auth.json', emit=events.append)
            self.assertEqual(result['status'], 'login_finished')
            self.assertEqual(result['authentication'], 'unavailable')
            self.assertNotIn('private-provider-secret', json.dumps(events + [result]))

    def test_login_holds_before_starting_native_child_without_qualified_time(self):
        import shlex
        from unittest.mock import patch
        from codex_wake.grok_provider_auth import login
        from codex_wake.measurements import TimeUnavailable
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'native-started'
            executable = Path(directory) / 'grok'
            executable.write_text('#!/bin/sh\ntouch ' + shlex.quote(str(marker)) + '\n')
            executable.chmod(0o700)
            events = []
            with patch('codex_wake.measurements.snapshot', side_effect=TimeUnavailable('private-clock-detail')):
                result = login(executable, Path(directory) / 'auth.json', emit=events.append)
            self.assertEqual((result['status'], result['reason']), ('held', 'stable_time_unavailable'))
            self.assertFalse(marker.exists(), 'unqualified time must not start official device login')
            self.assertNotIn('private-clock-detail', json.dumps(events + [result]))

    def test_login_holds_and_reaps_owned_child_when_qualified_clock_is_lost(self):
        import subprocess
        from unittest.mock import patch
        from codex_wake.grok_provider_auth import login
        from codex_wake.measurements import TimeUnavailable
        children = []
        popen = subprocess.Popen
        def start(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'grok'
            executable.write_text('#!/bin/sh\nexec sleep 30\n')
            executable.chmod(0o700)
            events = []
            with patch('codex_wake.measurements.snapshot', side_effect=[CLOCK, TimeUnavailable('private-clock-detail')]), \
                    patch('subprocess.Popen', side_effect=start):
                result = login(executable, Path(directory) / 'auth.json', emit=events.append)
            self.assertEqual((result['status'], result['reason']), ('held', 'stable_time_unavailable'))
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll(), 'a clock hold must reap its owned native child')
            self.assertNotIn('private-clock-detail', json.dumps(events + [result]))

    def test_public_status_requires_exact_account_grant_before_credentials(self):
        from codex_wake.grok_provider_auth import GrokAccounts, observe
        from codex_wake.controller_auth import Actor, AuthError
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            auth.write_text(json.dumps({'https://auth.x.ai': {
                'key': 'private-secret', 'auth_mode': 'oidc', 'user_id': 'one'}}))
            auth.chmod(0o600)
            root = Path(directory) / 'wake'
            accounts = GrokAccounts(root)
            accounts.register('personal', 'Personal', auth)
            target = accounts.target('personal')
            arguments = dict(account='personal', expected_target=target)
            actor = Actor('subject', 'agent', 'client', 'grant', 'issuer', 'resource',
                          frozenset({'account.observe'}), [{'host': target['host']}], 4000000000)
            auth.unlink()
            with self.assertRaises(AuthError):
                observe(root, arguments, actor=actor, authorize=lambda: actor)
            actor = Actor('subject', 'agent', 'client', 'grant', 'issuer', 'resource',
                          frozenset({'account.observe'}), [target], 4000000000)
            result = observe(root, arguments, actor=actor, authorize=lambda: actor)
            self.assertEqual(result['result']['authentication']['authentication'], 'unavailable')
            from types import SimpleNamespace
            from unittest.mock import patch
            from codex_wake.controller_http import ProtectedOperations
            from codex_wake.mcp_server import CommandRunner
            api = ProtectedOperations(SimpleNamespace(authenticate=lambda token: actor),
                                      SimpleNamespace(inventory=SimpleNamespace(root=root)))
            self.assertEqual(api.execute('opaque-host-token', 'grok_auth.status', arguments)['result'], result['result'])
            with patch('codex_wake.operation_commands.local_actor', return_value=actor):
                value, failed = CommandRunner(wake_root=str(root)).call('wake_grok_auth_status', arguments)
            self.assertFalse(failed)
            self.assertEqual(value, result)

    def test_expired_broker_reuses_official_refresh_owner_and_rechecks_identity(self):
        from codex_wake.grok_provider_auth import GrokAccounts
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            value = {'key': 'expired-secret', 'auth_mode': 'oidc', 'user_id': 'one',
                     'expires_at': '2020-01-01T00:00:00Z'}
            auth.write_text(json.dumps({'https://auth.x.ai': value}))
            auth.chmod(0o600)
            executable = Path(directory) / 'grok'
            executable.write_text("#!/usr/bin/env python3\nimport json,os\np=os.environ['GROK_AUTH_PATH']\nd=json.load(open(p))\na=d['https://auth.x.ai']\na.update(key='rotated-secret', expires_at='2030-01-01T00:00:00Z')\nwith open(p,'w') as f: json.dump(d,f)\n")
            executable.chmod(0o700)
            accounts = GrokAccounts(Path(directory) / 'wake')
            accounts.register('personal', 'Personal', auth, executable=executable)
            self.assertEqual(accounts.bearer('personal', 1800000000), 'rotated-secret')

    def test_uncertain_native_refresh_is_not_replayed(self):
        from codex_wake.grok_provider_auth import GrokAccounts
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            auth.write_text(json.dumps({'https://auth.x.ai': {
                'key': 'expired-secret', 'auth_mode': 'oidc', 'user_id': 'one',
                'expires_at': '2020-01-01T00:00:00Z'}}))
            auth.chmod(0o600)
            executable = Path(directory) / 'grok'
            executable.write_text("#!/usr/bin/env python3\nimport os,json,pathlib\np=pathlib.Path(os.environ['GROK_AUTH_PATH'])\nm=p.with_name('attempted')\nif not m.exists():\n m.touch(); raise SystemExit(1)\nd=json.loads(p.read_text()); d['https://auth.x.ai'].update(key='replayed-secret',expires_at='2030-01-01T00:00:00Z'); p.write_text(json.dumps(d))\n")
            executable.chmod(0o700)
            accounts = GrokAccounts(Path(directory) / 'wake')
            accounts.register('personal', 'Personal', auth, executable=executable)
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
                    accounts.bearer('personal', 1800000000)

    def test_cli_registration_status_and_native_private_bearer_channel(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        from unittest.mock import patch
        from codex_wake.cli import run
        from codex_wake.time_provider import TimeDecision
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            auth.write_text(json.dumps({'https://auth.x.ai': {
                'key': 'synthetic-private-bearer', 'auth_mode': 'oidc', 'user_id': 'one',
                'expires_at': '2030-01-01T00:00:00Z'}}))
            auth.chmod(0o600)
            prefix = ['--wake-root', str(Path(directory) / 'wake'), 'grok', 'auth']
            public = io.StringIO()
            with redirect_stdout(public):
                self.assertEqual(run(prefix + ['register', 'personal', '--label', 'Personal', '--auth-path', str(auth)]), 0)
                self.assertEqual(run(prefix + ['status', 'personal']), 0)
            self.assertNotIn('synthetic-private-bearer', public.getvalue())
            # Official Grok 1.0.77 creates a nonsecret lock with mode 0644.
            # Keep its inode/mode unchanged while using the same flock.
            lock = auth.with_name('auth.json.lock')
            lock.touch(mode=0o644)
            lock.chmod(0o644)
            lock_inode = lock.stat().st_ino
            accepted_revision = json.loads(public.getvalue().splitlines()[-1])['registration_revision']
            private = io.StringIO()
            time = TimeDecision('network', ('stable-time:cloudflare', 'stable-time:netnod'), 1800000000, 1800000001)
            with patch('codex_wake.time_inspection.stable_time_config', return_value='configured'), patch('codex_wake.stable_time.service_time_decision', return_value=time), redirect_stdout(private):
                self.assertEqual(run(prefix + ['token', 'personal', '--expected-account-revision', accepted_revision]), 0)
            self.assertEqual(private.getvalue(), 'synthetic-private-bearer')
            self.assertEqual(lock.stat().st_ino, lock_inode)
            self.assertEqual(lock.stat().st_mode & 0o777, 0o644)
            lock.chmod(0o666)
            with self.assertRaisesRegex(ValueError, 'insecure_native_lock'):
                GrokSession(auth).bearer(1800000001)
            lock.chmod(0o644)
            rejected, errors = io.StringIO(), io.StringIO()
            with patch('codex_wake.time_inspection.stable_time_config', return_value='configured'), patch('codex_wake.stable_time.service_time_decision', return_value=time), redirect_stdout(rejected), redirect_stderr(errors):
                self.assertEqual(run(prefix + ['token', 'personal', '--expected-account-revision', 'stale']), 3)
            self.assertEqual(rejected.getvalue(), '')
            self.assertIn('account_registration_changed', errors.getvalue())
            self.assertNotIn('synthetic-private-bearer', errors.getvalue())

    def test_accepted_selection_holds_changed_registration_and_allows_token_rotation(self):
        from codex_wake.grok_provider_auth import GrokAccounts
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            value = {'key': 'original-secret', 'auth_mode': 'oidc', 'user_id': 'one',
                     'expires_at': '2030-01-01T00:00:00Z'}
            auth.write_text(json.dumps({'https://auth.x.ai': value}))
            auth.chmod(0o600)
            accounts = GrokAccounts(Path(directory) / 'wake')
            accounts.register('personal', 'Personal', auth)
            revision = accounts.status('personal')['registration_revision']
            with self.assertRaisesRegex(ValueError, 'account_registration_changed'):
                accounts.bearer('personal', 1800000000, expected_revision='stale-registration')
            value['key'] = 'rotated-secret'
            auth.write_text(json.dumps({'https://auth.x.ai': value}))
            self.assertEqual(accounts.bearer('personal', 1800000000, expected_revision=revision), 'rotated-secret')

    def test_cli_revocation_blocks_only_selected_account_and_retains_native_store(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        from unittest.mock import patch
        from codex_wake.cli import run
        from codex_wake.time_provider import TimeDecision
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            prefix = ['--wake-root', str(root), 'grok', 'auth']
            stores, targets = {}, {}
            for account in ('personal', 'work'):
                home = Path(directory) / account
                home.mkdir(mode=0o700)
                auth = home / 'auth.json'
                auth.write_text(json.dumps({'https://auth.x.ai': {
                    'key': 'synthetic-private-' + account, 'auth_mode': 'oidc',
                    'user_id': account, 'expires_at': '2030-01-01T00:00:00Z'}}))
                auth.chmod(0o600)
                stores[auth] = auth.read_bytes()
                public = io.StringIO()
                with redirect_stdout(public):
                    self.assertEqual(run(prefix + ['register', account, '--label', account,
                                                   '--auth-path', str(auth)]), 0)
                    self.assertEqual(run(prefix + ['status', account]), 0)
                targets[account] = json.loads(public.getvalue().splitlines()[-1])['target']
            public = io.StringIO()
            with redirect_stdout(public):
                self.assertEqual(run(prefix + ['revoke', 'personal', '--expected-target',
                                               json.dumps(targets['personal'])]), 0)
                self.assertEqual(run(prefix + ['status', 'personal']), 0)
                self.assertEqual(run(prefix + ['status', 'work']), 0)
            rows = [json.loads(line) for line in public.getvalue().splitlines()]
            self.assertEqual(rows[-2]['authentication'], 'revoked')
            self.assertEqual(rows[-1]['authentication'], 'present')
            self.assertEqual(rows[0]['provider_completion'], 'unknown')
            self.assertNotIn('synthetic-private-', public.getvalue())
            decision = TimeDecision('network', ('stable-time:cloudflare', 'stable-time:netnod'),
                                    1800000000, 1800000001)
            for account, expected in [('personal', 3), ('work', 0)]:
                private, errors = io.StringIO(), io.StringIO()
                with patch('codex_wake.time_inspection.stable_time_config', return_value='configured'), \
                     patch('codex_wake.stable_time.service_time_decision', return_value=decision), \
                     redirect_stdout(private), redirect_stderr(errors):
                    self.assertEqual(run(prefix + ['token', account]), expected)
                if account == 'personal':
                    self.assertEqual(private.getvalue(), '')
                    self.assertIn('account_revoked', errors.getvalue())
                else:
                    self.assertEqual(private.getvalue(), 'synthetic-private-work')
            for path, original in stores.items():
                self.assertEqual(path.read_bytes(), original)

    def test_public_revocation_requires_exact_account_grant_and_exposes_no_bearer(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from codex_wake.grok_provider_auth import GrokAccounts
        from codex_wake.controller_auth import Actor, AuthError
        from codex_wake.controller_http import ProtectedOperations
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            accounts = GrokAccounts(root)
            targets = {}
            for account in ('api', 'mcp'):
                home = Path(directory) / account
                home.mkdir(mode=0o700)
                auth = home / 'auth.json'
                auth.write_text(json.dumps({'https://auth.x.ai': {
                    'key': 'synthetic-private-' + account, 'auth_mode': 'oidc',
                    'user_id': account, 'expires_at': '2030-01-01T00:00:00Z'}}))
                auth.chmod(0o600)
                accounts.register(account, account, auth)
                targets[account] = accounts.target(account)
            def actor(scope, target):
                return Actor('subject', 'agent', 'client', 'grant', 'issuer', 'resource',
                             frozenset({scope}), [target], 4000000000)
            current = [actor('account.revoke', targets['api'])]
            api = ProtectedOperations(SimpleNamespace(authenticate=lambda _: current[0]),
                                      SimpleNamespace(inventory=SimpleNamespace(root=root)))
            result = api.execute('synthetic-host-token', 'grok_auth.revoke',
                                 dict(account='api', expected_target=targets['api']))
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['result']['authentication'], 'revoked')
            self.assertNotIn('synthetic-private-', json.dumps(result))
            current[0] = actor('account.observe', targets['mcp'])
            with self.assertRaises(AuthError):
                api.execute('synthetic-host-token', 'grok_auth.revoke',
                            dict(account='mcp', expected_target=targets['mcp']))
            current[0] = actor('account.revoke', {'host': targets['mcp']['host']})
            with self.assertRaises(AuthError):
                api.execute('synthetic-host-token', 'grok_auth.revoke',
                            dict(account='mcp', expected_target=targets['mcp']))
            self.assertEqual(accounts.status('mcp')['authentication'], 'present')
            current[0] = actor('account.revoke', targets['mcp'])
            with patch('codex_wake.operation_commands.local_actor', return_value=current[0]):
                result, failed = CommandRunner(wake_root=str(root)).call('wake_grok_auth_revoke',
                    dict(account='mcp', expected_target=targets['mcp']))
            self.assertFalse(failed, result)
            self.assertEqual(result['result']['authentication'], 'revoked')
            self.assertNotIn('synthetic-private-', json.dumps(result))

    def test_missing_native_store_is_unavailable_not_confirmed_logout(self):
        with tempfile.TemporaryDirectory() as directory:
            result = GrokSession(Path(directory) / 'auth.json').status()
            self.assertEqual(result['authentication'], 'unavailable')
            self.assertEqual(result['reason'], 'native_auth_missing')
            self.assertEqual(result['provider_logout'], 'unconfirmed')
