"""Public model selection separates independent qualification from native credentials."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.time_provider import TimeDecision


class GrokModelCatalogTest(unittest.TestCase):
    def test_cli_model_metadata_never_qualifies_account_and_default_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'wake'
            auth = Path(directory) / 'auth.json'
            auth.write_text(json.dumps({'https://auth.x.ai': {
                'key': 'synthetic-private-bearer', 'auth_mode': 'oidc', 'user_id': 'one',
                'expires_at': '2030-01-01T00:00:00Z'}}))
            auth.chmod(0o600)
            prefix = ['--wake-root', str(root), 'grok']
            def invoke(arguments):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = run(prefix + arguments)
                return code, json.loads(output.getvalue())
            self.assertEqual(invoke(['auth', 'register', 'personal', '--label', 'Personal Grok', '--auth-path', str(auth)])[0], 0)
            metadata = Path(directory) / 'metadata.json'
            metadata.write_text(json.dumps({'schema': 1, 'source': 'operator-model-metadata',
                'issued_at': 1799999000, 'expires_at': 1800001000,
                'models': [{'id': 'grok-build', 'label': 'Grok Build', 'context_window': 32000,
                            'capabilities': dict(text=True, streaming=True, terminal=True, file_editing=True, mcp=True,
                                                 image_generation=False, web_search=False, reasoning_summary=False)}]}))
            clock = TimeDecision('network', ('stable-time:one',), 1800000000, 1800000001)
            with patch('codex_wake.grok_model_catalog.qualified_time', return_value=clock):
                self.assertEqual(invoke(['models', 'import', 'personal', '--metadata', str(metadata)])[0], 0)
                code, catalog = invoke(['models', 'list', 'personal'])
                self.assertEqual(code, 0)
                choice = catalog['selections'][0]
                self.assertEqual(choice['readiness'], 'unverified')
                self.assertEqual(choice['accountLabel'], 'Personal Grok')
                self.assertFalse(choice['defaultForAccount'])
                self.assertNotIn('synthetic-private-bearer', json.dumps(catalog))
                code, held = invoke(['models', 'resolve', 'personal'])
                self.assertEqual(code, 3)
                self.assertEqual(held['reason'], 'explicit_account_default_required')
                receipt = Path(directory) / 'qualification.json'
                receipt.write_text(json.dumps({'schema': 1, 'source': 't8-independent-account-coding-receipt',
                    'account': 'personal', 'account_revision': choice['accountRevision'],
                    'catalog_revision': choice['catalogRevision'], 'model': 'grok-build',
                    'issued_at': 1799999000, 'expires_at': 1800000100,
                    'entitlement': True, 'inference': True,
                    'capabilities': dict(text=True, streaming=True, terminal=True, file_editing=True, mcp=True)}))
                self.assertEqual(invoke(['models', 'qualify', 'personal', '--receipt', str(receipt)])[0], 0)
                self.assertEqual(invoke(['models', 'default', 'personal', 'grok-build'])[0], 0)
                code, selection = invoke(['models', 'resolve', 'personal'])
                self.assertEqual(code, 0)
                self.assertEqual(selection['selection']['readiness'], 'qualified')
                self.assertEqual(selection['selection']['modelId'], 'grok-build')
                self.assertEqual(selection['selection']['accountLabel'], 'Personal Grok')
                self.assertTrue(selection['selection']['defaultForAccount'])
                self.assertEqual(selection['selection']['disabledFeatures'], ['image_generation', 'web_search', 'reasoning_summary'])
                self.assertEqual(invoke(['models', 'resolve', 'personal', '--model', 'other-model',
                    '--selection-id', selection['selection']['selectionId']])[0], 3)
                code, native = invoke(['models', 'native-catalog', '--wake-executable', '/operator/bin/codex-wake'])
                self.assertEqual(code, 0)
                self.assertEqual(native['selections'][0], selection['selection'])
                provider = native['providers']['grok__personal']
                self.assertEqual(provider['wire_api'], 'grok')
                self.assertEqual(provider['name'], 'Grok')
                self.assertEqual(provider['base_url'], 'https://cli-chat-proxy.grok.com/v1')
                self.assertEqual(provider['auth']['args'][-6:], ['grok', 'auth', 'token', 'personal',
                    '--expected-account-revision', selection['selection']['accountRevision']])
                self.assertEqual(provider['auth']['refresh_interval_ms'], 0)
                self.assertNotIn(str(auth), json.dumps(native))
                self.assertNotIn('synthetic-private-bearer', json.dumps(native))
                from types import SimpleNamespace
                from codex_wake.grok_provider_auth import GrokAccounts
                from codex_wake.controller_auth import Actor, AuthError
                from codex_wake.controller_http import ProtectedOperations
                from codex_wake.mcp_server import CommandRunner
                target = GrokAccounts(root).target('personal')
                actor = Actor('subject', 'agent', 'client', 'grant', 'issuer', 'resource',
                              frozenset({'account.observe'}), [target], 4000000000)
                arguments = dict(account='personal', expected_target=target)
                api = ProtectedOperations(SimpleNamespace(authenticate=lambda token: actor),
                                          SimpleNamespace(inventory=SimpleNamespace(root=root)))
                listed = api.execute('opaque-host-token', 'grok_models.list', arguments)
                self.assertEqual(listed['result']['selections'][0]['accountLabel'], 'Personal Grok')
                with patch('codex_wake.operation_commands.local_actor', return_value=actor):
                    value, failed = CommandRunner(wake_root=str(root)).call('wake_grok_models_resolve', arguments)
                self.assertFalse(failed)
                self.assertEqual(value['result'], selection)
                wrong = Actor('subject', 'agent', 'client', 'grant', 'issuer', 'resource',
                              frozenset({'account.observe'}), [{'host': target['host']}], 4000000000)
                api.authority.authenticate = lambda token: wrong
                with self.assertRaises(AuthError):
                    api.execute('opaque-host-token', 'grok_models.list', arguments)

                code, held = invoke(['models', 'resolve', 'personal', '--selection-id', choice['selectionId']])
                self.assertEqual(code, 3)
                self.assertEqual(held['reason'], 'stale_inference_selection')
            expired = TimeDecision('network', ('stable-time:one',), 1800000200, 1800000201)
            with patch('codex_wake.grok_model_catalog.qualified_time', return_value=expired):
                code, catalog = invoke(['models', 'list', 'personal'])
                self.assertEqual(catalog['selections'][0]['readiness'], 'stale')
                self.assertEqual(invoke(['models', 'resolve', 'personal'])[0], 3)

            with patch('codex_wake.grok_model_catalog.qualified_time', return_value=clock):
                content = json.loads(metadata.read_text())
                content['models'][0]['capabilities']['terminal'] = False
                metadata.write_text(json.dumps(content))
                code, catalog = invoke(['models', 'import', 'personal', '--metadata', str(metadata)])
                self.assertEqual(code, 0)
                self.assertEqual(catalog['selections'][0]['readiness'], 'unavailable')
                self.assertIn('required_capability_missing:terminal', catalog['selections'][0]['reasons'])
                self.assertEqual(invoke(['models', 'default', 'personal', 'grok-build'])[0], 3)
                # Shared revocation is an account event, not a model/capability claim.
                previous_revision = catalog['selections'][0]['accountRevision']
                _, status = invoke(['auth', 'status', 'personal'])
                self.assertEqual(invoke(['auth', 'revoke', 'personal', '--expected-target',
                                         json.dumps(status['target'])])[0], 0)
                code, revoked = invoke(['models', 'native-catalog', '--wake-executable', '/operator/bin/codex-wake'])
                self.assertEqual(code, 0)
                choice = revoked['selections'][0]
                self.assertEqual(choice['readiness'], 'unavailable')
                self.assertEqual(choice['reasons'], ['authentication_revoked'])
                self.assertNotEqual(choice['accountRevision'], previous_revision)
                self.assertEqual(choice['accountLabel'], 'Personal Grok')
                self.assertEqual(revoked['providers']['grok__personal']['auth']['args'][-1], choice['accountRevision'])
                self.assertNotIn('synthetic-private-bearer', json.dumps(revoked))
