"""Live acceptance must refuse an existing evidence destination before effects."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class AcceptanceReceiptTests(unittest.TestCase):
    def test_continuity_cli_preserves_existing_receipt_before_loading_live_config(self):
        script=Path(__file__).resolve().parents[1]/'scripts/connector_background_continuity_acceptance.py'
        with tempfile.TemporaryDirectory() as directory:
            receipt=Path(directory)/'failed-result.json'
            evidence=b'{"status":"failed","original_native_effect":"unknown"}'
            receipt.write_bytes(evidence)
            result=subprocess.run([sys.executable,str(script),'--receipt',str(receipt)],
                env=dict(os.environ,HOME=directory),capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('FileExistsError',result.stderr)
            self.assertEqual(receipt.read_bytes(),evidence)
