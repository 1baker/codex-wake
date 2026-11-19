"""Effective lifecycle policy through the public CLI/MCP, without native effects."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.mcp_server import CommandRunner


class LifecycleConfigurationTests(unittest.TestCase):
    def test_objective_override_selects_actual_instructions_before_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = root / 'writer.md'
            reviewer = root / 'reviewer.md'
            alternate = root / 'alternate.md'
            writer.write_text('Write an evidence checkpoint.')
            reviewer.write_text('Route the substantive review.')
            alternate.write_text('Review local evidence without GitHub.')
            profiles = root / 'profiles.json'
            profiles.write_text(json.dumps(dict(
                profiles={'worker': {'cwd': tmp}},
                lifecycle_defaults=dict(
                    handoff_writer={'name': 'writer', 'path': str(writer)},
                    preflight_reviewer={'name': 'router', 'path': str(reviewer)},
                    session_token_limit=100, session_time_limit_seconds=60,
                    objective_token_limit=500, objective_time_limit_seconds=300,
                    max_correction_cycles=2),
                continuations={'source': dict(objective='Finish the feature',
                    approval='operator', started_at='2030-01-01T00:00:00Z',
                    configuration={'preflight_reviewer': {'name': 'local-review', 'path': str(alternate)}})})))
            output = StringIO()
            with redirect_stdout(output):
                code = run(['sessions', 'configuration', '--profiles', str(profiles),
                            '--profile', 'worker', '--thread-id', 'source', '--json'])
            self.assertEqual(code, 0)
            effective = json.loads(output.getvalue())
            self.assertEqual(effective['preflight_reviewer']['name'], 'local-review')
            self.assertEqual(effective['preflight_reviewer']['instructions'],
                             'Review local evidence without GitHub.')
            self.assertEqual(effective['handoff_writer']['instructions'], 'Write an evidence checkpoint.')
            self.assertEqual(effective['objective_deadline'], '2030-01-01T00:05:00+00:00')
            self.assertEqual(effective['session_token_limit'], 100)
            self.assertEqual(len(effective['revision']), 64)
            runner = CommandRunner(lifecycle_profiles=profiles, wake_root=root / 'wake')
            value, failed = runner.call('wake_sessions_configuration', dict(profile='worker',
                thread_id='source', caller_thread_id='00000000-0000-7000-8000-000000000159'))
            self.assertTrue(failed)
            self.assertIn('unavailable', value['error']['message'])
            config = json.loads(profiles.read_text())
            caller = '00000000-0000-7000-8000-000000000159'
            config['continuations'][caller] = config['continuations'].pop('source')
            config['callers'] = {caller: ['worker']}
            profiles.write_text(json.dumps(config))
            value, failed = runner.call('wake_sessions_configuration', dict(profile='worker',
                thread_id=caller, caller_thread_id=caller))
            self.assertFalse(failed, value)
            self.assertEqual(value['preflight_reviewer']['instructions'], 'Review local evidence without GitHub.')
            from codex_wake.objective_ledger import ObjectiveLedger
            from codex_wake.lifecycle_budget import objective_identity
            ledger = ObjectiveLedger(root / 'wake', objective_identity(config['continuations'][caller]))
            selected = {key: item for key, item in value.items()
                        if key not in ('source_thread_id', 'profile', 'objective_budget')}
            ledger.configure(selected, 'operator', prior_tokens=10, now=1893456000)
            ledger.record('previous-session', 30, settled=True, now=1893456000)
            with patch('codex_wake.measurements.utc_bounds', return_value=(1893456000, 1893456001)):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(run(['--wake-root', str(root / 'wake'), 'sessions', 'configuration',
                        '--profiles', str(profiles), '--profile', 'worker', '--thread-id', caller, '--json']), 0)
                current = json.loads(output.getvalue())
                self.assertEqual(current['objective_budget']['tokens_used'], 40)
                self.assertEqual(current['objective_budget']['remaining_tokens'], 460)
                config['lifecycle_defaults']['objective_token_limit'] = 600
                profiles.write_text(json.dumps(config))
                output = StringIO()
                with redirect_stdout(output):
                    run(['--wake-root', str(root / 'wake'), 'sessions', 'configuration', '--profiles', str(profiles),
                         '--profile', 'worker', '--thread-id', caller, '--json'])
                preview = json.loads(output.getvalue())
                self.assertEqual(preview['objective_budget']['objective_token_limit'], 500)
                config['continuations'][caller]['budget_authorization'] = dict(action='extend',
                    approval='explicit operator extension', revision=preview['revision'])
                profiles.write_text(json.dumps(config))
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(run(['--wake-root', str(root / 'wake'), 'sessions', 'configuration',
                        '--profiles', str(profiles), '--profile', 'worker', '--thread-id', caller,
                        '--apply-budget-authorization', '--json']), 0)
                extended = json.loads(output.getvalue())['objective_budget']
                self.assertEqual(extended['tokens_used'], 40)
                self.assertEqual(extended['remaining_tokens'], 560)
                self.assertEqual(len(extended['authorization_history']), 2)
                config['lifecycle_defaults']['objective_token_limit'] = 100
                profiles.write_text(json.dumps(config))
                output = StringIO()
                with redirect_stdout(output):
                    run(['--wake-root', str(root / 'wake'), 'sessions', 'configuration', '--profiles', str(profiles),
                         '--profile', 'worker', '--thread-id', caller, '--json'])
                revision = json.loads(output.getvalue())['revision']
                config['continuations'][caller]['budget_authorization'] = dict(action='reset',
                    approval='explicit operator reset', revision=revision)
                profiles.write_text(json.dumps(config))
                for attempt in range(2):
                    output = StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(run(['--wake-root', str(root / 'wake'), 'sessions', 'configuration',
                            '--profiles', str(profiles), '--profile', 'worker', '--thread-id', caller,
                            '--apply-budget-authorization', '--json']), 0)
                    reset = json.loads(output.getvalue())['objective_budget']
                    self.assertEqual(reset['tokens_used'], 40)
                    self.assertEqual(reset['remaining_tokens'], 60)
                    self.assertEqual(len(reset['authorization_history']), 3)
            alternate.unlink()
            value, failed = runner.call('wake_sessions_configuration', dict(profile='worker',
                thread_id=caller, caller_thread_id=caller))
            self.assertTrue(failed)
            self.assertEqual(value['error']['code'], 'configuration_unavailable')
            self.assertNotIn('preflight_reviewer', value)
