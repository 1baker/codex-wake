"""Explicit modes and verified session closure through native registration/poll."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from codex_wake.cli import run
from codex_wake.daemon import poll_once
from codex_wake.records import all_records
from codex_wake.process import process_identity
THREAD = "11111111-1111-4111-8111-111111111111"
CLOCK = {"utc": {"lower": 2000000000, "upper": 2000000000, "status": "network", "sources": ["clock-a", "clock-b"]}, "counter": None}
class WakeSessionModes(unittest.TestCase):
    def test_live_registration_exposes_missing_restoration_before_claiming_armed(self):
        out = io.StringIO()
        reader = type('Reader', (), dict(schema_versions=[8]))()
        health = dict(mode='loop', reader_capabilities=['wake_session_modes_v1'])
        with tempfile.TemporaryDirectory() as d, patch('codex_wake.sessions.observe', return_value={'complete': True, 'sessions': []}), patch('codex_wake.native_clock.snapshot', return_value=CLOCK), patch('codex_wake.native_protocol.native_request', return_value={'thread': {'id': THREAD, 'status': {'type': 'notLoaded'}}}), patch('codex_wake.signal_records.probe_managed_reader_capability', return_value=reader), patch('codex_wake.monitor.read_monitor_health', return_value=health), contextlib.redirect_stdout(out):
            self.assertEqual(run(['--wake-root', d, 'native', 'after', '--json', '--session-mode', 'reopen_live', '--codex-path', sys.executable, THREAD, '1h', '--', 'check']), 0)
            receipt = json.loads(out.getvalue())
            self.assertFalse(receipt['armed'])
            self.assertEqual(receipt['harness']['reason'], 'live_restore_configuration_required')

    def test_session_only_survives_detach_and_cancels_after_exact_process_exits(self):
        with tempfile.TemporaryDirectory() as d:
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                identity = process_identity(child.pid)
                snapshot = {"complete": True, "sessions": [{"thread_id": THREAD, "binding_status": "metadata_matched", "attachments": [{"client_pid": child.pid, "client_start_time_ticks": identity["start_time_ticks"], "pane_id": "%1", "socket": None}]}]}
                out = io.StringIO()
                with patch("codex_wake.sessions.observe", return_value=snapshot), patch("codex_wake.native_clock.snapshot", return_value=CLOCK), contextlib.redirect_stdout(out):
                    code = run(["--wake-root", d, "native", "after", "--json", "--session-mode", "session_only", "--codex-path", sys.executable, THREAD, "1h", "--", "check"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(out.getvalue())["session_mode"], "session_only")
                with patch("codex_wake.native_clock.snapshot", return_value=CLOCK): poll_once(Path(d), dispatch=False)
                self.assertEqual(all_records(Path(d))[0].record["status"], "pending")
                child.terminate(); child.wait(timeout=5)
                with patch("codex_wake.native_clock.snapshot", return_value=CLOCK): poll_once(Path(d), dispatch=False)
                self.assertEqual(all_records(Path(d))[0].record["status"], "cancelled")
                self.assertEqual(all_records(Path(d))[0].record["attempts"], 0)
            finally:
                if child.poll() is None: child.terminate(); child.wait(timeout=5)
    def test_session_only_can_bind_complete_metadata_slower_than_five_seconds(self):
        from codex_wake.shared_app_server import SharedSourceError
        identity=process_identity(os.getpid())
        snapshot={"complete":True,"sessions":[{"thread_id":THREAD,"binding_status":"metadata_matched","attachments":[{"client_pid":os.getpid(),"client_start_time_ticks":identity["start_time_ticks"],"pane_id":"%1","socket":None}]}]}
        def native_metadata(**kwargs):
            # The external source requires six seconds; deadlines are enforced
            # without spending wall-clock time in this deterministic regression.
            if kwargs['timeout'] < 6:raise SharedSourceError('native metadata observation deadline')
            return snapshot
        with tempfile.TemporaryDirectory() as d, patch('codex_wake.sessions.observe',side_effect=native_metadata), patch('codex_wake.native_clock.snapshot',return_value=CLOCK),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(['--wake-root',d,'native','after','--json','--session-mode','session_only','--codex-path',sys.executable,THREAD,'1h','--','check']),0)
            self.assertEqual(all_records(Path(d))[0].record['target']['session_owner']['pid'],os.getpid())

    def test_native_agent_schema_requires_explicit_mode(self):
        from codex_wake.harness_mcp import tool_specs
        for verb in ("after", "at", "file"):
            self.assertIn("session_mode", tool_specs()["wake_native_" + verb][4])
    def test_old_monitor_does_not_claim_support_for_explicit_modes(self):
        from codex_wake.monitor import write_monitor_health
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'XDG_STATE_HOME':d}):
            root=Path(d)/'wake'
            write_monitor_health(wake_root=root,source='old-worker',mode='loop',extra={'reader_capabilities':['signal_records_v2']})
            output=io.StringIO()
            with patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}), patch('codex_wake.native_clock.snapshot',return_value=CLOCK),contextlib.redirect_stdout(output):
                run(['--wake-root',str(root),'native','after','--json','--session-mode','background','--idempotency-key','compat','--codex-path',sys.executable,THREAD,'1h','--','check'])
            value=json.loads(output.getvalue())
            self.assertFalse(value['armed'])
            self.assertEqual(value['requires_worker_capabilities'],['wake_session_modes_v1'])
            self.assertEqual(value['wake_policy']['session_mode'],'background')
    def test_unsupported_grok_modes_are_not_advertised_or_silently_ignored(self):
        from codex_wake.mcp_server import SPECS
        for verb in ('after','at','file'):
            self.assertNotIn('session_mode', SPECS['wake_grok_'+verb][3])
