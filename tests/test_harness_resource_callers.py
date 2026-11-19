"""CLI and MCP share the public resource custody gate; host evidence stays external."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.managed_inventory import ManagedInventory, Observation
from codex_wake.mcp_server import CommandRunner, SPECS
from tests.test_measurements import observation

THREAD = '00000000-0000-7000-8000-000000000331'
META = dict(threadId=THREAD, sessionId=THREAD, callId='resource-call',
            **{'x-codex-turn-metadata': dict(thread_id=THREAD, session_id=THREAD, turn_id='turn-resource')})


class ResourceCallerTests(unittest.TestCase):
    def test_cli_and_mcp_share_claim_and_refuse_spoofed_owner_authority(self):
        clock = observation(1000)
        with tempfile.TemporaryDirectory() as tmp, patch(
                "codex_wake.measurements.snapshot", return_value=clock):
            root = Path(tmp)
            sample = Observation('codex', 'codex:fixture', THREAD, str(root), 'ready', clock['utc']['upper'],
                                 'native_metadata', dict(pid=123, start_ticks=42, boot_id='boot'), [], {'inspect': 'supported'},
                                 clock_observation=clock)
            agent = ManagedInventory(root).enroll(sample, operator=True)['agent']['managed_agent_id']
            runner = CommandRunner(wake_root=root)
            with patch('codex_wake.managed_inventory_commands.RuntimeObserver.__call__', return_value=sample):
                value, failed = runner.call('wake_resources_claim', dict(managed_agent_id=agent,
                    kind='worktree', path=str(root)), native_context=META)
                self.assertFalse(failed, value)
                claim = value
                admitted, failed = runner.call('wake_resources_check', dict(managed_agent_id=agent,
                    claim_id=claim['claim_id'], generation=claim['generation']), native_context=META)
                self.assertFalse(failed, admitted)
                self.assertTrue(admitted['point_in_time_only'])
                denied, failed = runner.call('wake_resources_release', dict(managed_agent_id=agent,
                    claim_id=claim['claim_id'], generation=claim['generation']))
                self.assertTrue(failed, denied)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = run(['--wake-root', str(root), 'resources', 'show', '--claim-id', claim['claim_id'], '--json'])
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['status'], 'active')
            self.assertNotIn('wake_resources_transfer', SPECS)
            for name in ('wake_resources_claim', 'wake_resources_check', 'wake_resources_release'):
                self.assertNotIn('operator', SPECS[name][3])
