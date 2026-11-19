"""Native clock reader's process contract: no configured authority means hold."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO


class NativeQueueClockTests(unittest.TestCase):
    def test_qualified_process_output_labels_service_measurement_without_private_bridge(self):
        from codex_wake.native_queue_clock import main
        sample = dict(reason='authenticated_utc', valid_for_ns=9000000000,
                      utc=dict(status='network', lower=100., upper=100.1),
                      counter=dict(epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                                   counter=1000, frequency=10000000, rate_ppm=5000))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = StringIO()
            with patch.dict(os.environ), patch.object(sys, 'argv', ['reader', '--config', str(root/'client.json')]), patch(
                    'codex_wake.native_queue_clock.snapshot', return_value=sample), patch.object(
                    Path, 'home', return_value=root), redirect_stdout(output):
                self.assertEqual(main(), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value['valid_for_ns'], 9000000000)
            self.assertEqual(value['contract_version'], 2)
            self.assertEqual(value['basis'], 'service_measurement')
            self.assertIs(value['receipt_time_bound'], False)
            self.assertEqual(value['counter_source'], {'kind': 'stable_time_service_measurement'})
            self.assertEqual(value['counter'], sample['counter'])
            self.assertLess(value['lower'], 100.)
            self.assertGreater(value['upper'], 100.1)

    def test_missing_stable_time_configuration_holds_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-m', 'codex_wake.native_queue_clock',
                 '--config', str(Path(directory)/'absent.json')],
                capture_output=True, text=True, timeout=10,
                env=dict(os.environ, PYTHONPATH='src'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            'contract_version': 2, 'state': 'held', 'reason': 'stable_time_client_configuration_invalid'})
        self.assertEqual(result.stderr, '')
