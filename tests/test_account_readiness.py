import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from codex_wake.controller_auth import AuthError

from codex_wake.controller_accounts import ControllerAccounts


class AccountReadinessTests(unittest.TestCase):
    def test_remote_expiry_uses_qualified_upper_and_missing_clock_holds(self):
        from codex_wake.account_readiness import execute
        from codex_wake.controller_auth import Actor
        from codex_wake.measurements import TimeUnavailable
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'homes'/'codex-alice').mkdir(parents=True, mode=0o700)
            config = root/'accounts.toml'
            config.write_text('[profiles]\nstate_root='+json.dumps(str(root/'homes'))+'\nknown_profiles=["alice"]\n')
            accounts = ControllerAccounts(config, host='fixture', environment='test')
            target = accounts.execute('accounts.resolve', {'selector':'alice'})['account']['target']
            actor = Actor('operator', 'owner', 'client', 'grant', 'local://fixture', 'wake:controller', frozenset({'account.observe'}), [target], 200)
            with patch('codex_wake.measurements.utc_bounds', return_value=(198,199)), patch('codex_wake.goal_watcher.watcher_status', return_value=dict(reason='fixture', next_action='Inspect')):
                self.assertEqual(execute(root, {'selector':'alice'}, accounts=accounts, actor=actor, authorize=lambda:actor)['result']['status'], 'incomplete')
            for bounds, code in (((199,200), 'insufficient_scope'), (TimeUnavailable('private-detail'), 'qualified_time_unavailable')):
                with self.subTest(code=code), patch('codex_wake.measurements.utc_bounds', return_value=bounds if isinstance(bounds,tuple) else None, side_effect=bounds if isinstance(bounds,Exception) else None), patch('codex_wake.goal_watcher.watcher_status', side_effect=AssertionError('private read forbidden')):
                    with self.assertRaises(AuthError) as held:
                        execute(root, {'selector':'alice'}, accounts=accounts, actor=actor, authorize=lambda:actor)
                    self.assertEqual(held.exception.code, code)
                    self.assertNotIn('private-detail', str(held.exception))


    def test_missing_registration_is_actionable_without_claiming_runtime_readiness(self):
        from codex_wake.account_readiness import execute
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'homes' / 'codex-alice'
            home.mkdir(parents=True, mode=0o700)
            config = root / 'accounts.toml'
            config.write_text('[profiles]\nstate_root=' + json.dumps(str(root/'homes')) + '\nknown_profiles=["alice"]\n')
            accounts = ControllerAccounts(config, host='fixture', environment='test')
            before = sorted(str(p) for p in root.rglob('*'))
            with patch('codex_wake.goal_watcher.watcher_status', return_value=dict(reason='watcher_scope_mismatch', next_action='Reconcile selected root', start_attempted=False)):
                result = execute(root, {'selector':'alice'}, accounts=accounts)['result']
            self.assertEqual(result['checks']['watcher']['state'], 'watcher_scope_mismatch')
            self.assertEqual(result['checks']['client']['state'], 'unavailable')
            with patch('codex_wake.goal_watcher.watcher_status', side_effect=AssertionError('unauthorized observation')):
                with self.assertRaises(AuthError):
                    execute(root, {'selector':'alice'}, accounts=accounts, actor=object())
            self.assertEqual(result['status'], 'incomplete')
            self.assertEqual(result['checks']['build']['state'], 'missing')
            self.assertTrue(result['checks']['build']['remedy'])
            self.assertEqual(result['checks']['limits']['state'], 'not_qualified')
            self.assertEqual(before, sorted(str(p) for p in root.rglob('*')))

    def test_registered_backend_is_observed_without_a_tui_binding(self):
        import hashlib
        from codex_wake.account_readiness import execute
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root/'homes'/'codex-alice'
            home.mkdir(parents=True, mode=0o700)
            config = root/'accounts.toml'
            config.write_text('[profiles]\nstate_root='+json.dumps(str(root/'homes'))+'\nknown_profiles=["alice"]\n')
            accounts = ControllerAccounts(config, host='fixture', environment='test')
            executable = root/'codex'
            executable.write_text('#!/bin/sh\nexit 0\n'); executable.chmod(0o700)
            manifest = root/'builds.json'
            manifest.write_text(json.dumps(dict(schema_version=1, builds=dict(modded=dict(
                executable=str(executable), sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                upstream_version='fixture', revision='fixture', source='fixture', backend='managed')))))
            with patch('codex_wake.goal_watcher.watcher_status', return_value=dict(reason='watcher_running', next_action='Inspect enrollment', start_attempted=False)):
                checks = execute(root, dict(selector='alice', manifest=str(manifest)), accounts=accounts)['result']['checks']
            self.assertEqual(checks['backend']['state'], 'unavailable')
            self.assertEqual(checks['backend']['observation']['channel'], 'modded')
            self.assertEqual(checks['client']['state'], 'unavailable')
            self.assertFalse(checks['watcher']['selected_goal_enforced'])
            with patch('codex_wake.controller_daemons.ControllerDaemons.execute', return_value=dict(daemon=dict(
                    state='running', channel='modded', selected_build_running=True, account_identity='unverified'))), patch(
                    'codex_wake.goal_watcher.watcher_status', return_value=dict(reason='watcher_running', next_action='Inspect enrollment')):
                checks = execute(root, dict(selector='alice', manifest=str(manifest)), accounts=accounts)['result']['checks']
            self.assertEqual(checks['backend']['state'], 'running')
            self.assertTrue(checks['backend']['observation']['selected_build_running'])
            self.assertEqual(checks['client']['state'], 'unavailable')
            self.assertEqual(checks['limits']['state'], 'not_qualified')
