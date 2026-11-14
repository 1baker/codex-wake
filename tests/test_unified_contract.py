"""Canonical control names preserve owner behavior and transport admission."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from codex_wake.cli import run
from codex_wake.local_control_service import LocalOperations
from codex_wake.managed_inventory import InventoryError

class UnifiedContractTests(unittest.TestCase):
    def test_connector_discovers_hierarchy_from_the_cli(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=run(['environment','capabilities'])
        self.assertEqual(code,0)
        value=json.loads(out.getvalue())
        self.assertEqual(value['families'],['environment','wakes','programs','accounts','harnesses','operations','connectors'])
        self.assertIn('environment.conversations.prompt',value['operations'])
    def test_canonical_local_output_uses_original_operation_owner(self):
        with tempfile.TemporaryDirectory() as d:
            owner=LocalOperations(Path(d))
            failures=[]
            for operation in ('local.output','environment.conversations.output'):
                with self.assertRaises(InventoryError) as e:owner.execute(operation,{'operation_id':'missing'})
                failures.append(e.exception.code)
            self.assertEqual(failures,['operation_not_found','operation_not_found'])
    def test_canonical_cli_help_preserves_prompt_controls(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out),self.assertRaises(SystemExit) as e:run(['environment','conversations','prompt','--help'])
        self.assertEqual(e.exception.code,0)
        self.assertIn('--idempotency-key',out.getvalue())
        self.assertIn('--expected-target',out.getvalue())
