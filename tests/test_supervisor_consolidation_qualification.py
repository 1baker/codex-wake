from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ConsolidationQualificationTests(unittest.TestCase):
    def test_public_disposable_qualification_produces_acceptance_receipt(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'receipt.json'
            result = subprocess.run([
                sys.executable, str(repo / 'scripts/supervisor_consolidation_qualification.py'),
                '--python', sys.executable, '--source-root', str(repo), '--output', str(output),
            ], capture_output=True, text=True, timeout=55)
            diagnostic = output.read_text() if output.exists() else 'qualification receipt missing'
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr + diagnostic)
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt['status'], 'passed')
            self.assertEqual(receipt['final_owned_processes'], [])
            self.assertTrue(receipt['checks']['rollback_restored_dedicated_owner'])
            self.assertTrue(receipt['checks']['restart_retained_uncertain_hold'])
