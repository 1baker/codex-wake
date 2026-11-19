"""Selected host qualification through public spawn, using the existing native fixture."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.goal_supervision import enroll, poll, show
from codex_wake.goal_notices import list_notices, present_notice
from tests import test_goal_supervision as fixtures

THREAD, NOW = fixtures.THREAD, fixtures.NOW


class HostPreflightTests(unittest.TestCase):
    def test_disabled_control_remains_inspectable_with_qualified_or_unknown_metadata_time(self):
        from codex_wake.goal_host_preflight import inspect_host
        from codex_wake.measurements import TimeUnavailable
        helper=fixtures.GoalSupervisionTests()
        self.addCleanup(helper.doCleanups)
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,_,_=helper.fixture(directory)
            grant=json.loads(policy.read_text())['callers'][THREAD]
            profile=dict(app_server=grant['app_server'],codex_path=grant['codex_path'],
                governance_preflight=dict(policy=str(policy),requested_mode='sampled_stop'))
            for observed in (1234.0,None):
                with self.subTest(observed=observed), \
                        patch('codex_wake.goal_host_preflight._static',return_value=dict(cache='unavailable')), \
                        patch('codex_wake.goal_governance.snapshot',return_value=dict(state='available',enabled=False,scope=grant['allocation_id'])), \
                        patch('codex_wake.measurements.utc_time',**({'return_value':observed} if observed is not None else {'side_effect':TimeUnavailable('unqualified')})):
                    result=inspect_host(root,profile,THREAD)
                self.assertEqual(result['mode'],'inactive')
                self.assertFalse(result['effect_attempted'])
                self.assertFalse(result['resources_renewed'])
                self.assertEqual(result['observed_at'],observed)

    def test_static_receipt_reuse_binary_metadata_drift_and_fresh_controller_check(self):
        helper = fixtures.GoalSupervisionTests()
        self.addCleanup(helper.doCleanups)
        with tempfile.TemporaryDirectory() as tmp:
            root, policy, _, native, _ = helper.fixture(tmp)
            native['notices'] = {}
            native['metadata'] = dict(userAgent='qualified-fixture-v1')
            client = Path(tmp) / 'selected-client'
            client.write_text('#!/bin/sh\nexit 0\n')
            client.chmod(0o700)
            config = json.loads(policy.read_text())
            config['callers'][THREAD]['codex_path'] = str(client)
            policy.write_text(json.dumps(config))
            grant = config['callers'][THREAD]
            profile = dict(cwd=tmp, app_server=grant['app_server'], codex_path=str(client),
                codex_home=grant['codex_home'], tmux_session='fixture', timeout=1,
                governance_preflight=dict(policy=str(policy), requested_mode='sampled_stop'))
            profiles = Path(tmp) / 'profiles.json'
            def write_profile():
                profiles.write_text(json.dumps(dict(version=1, profiles={'worker': profile},
                    callers={THREAD: ['worker']})))
            write_profile()
            def invoke(intent='preflight-once'):
                output = StringIO()
                with redirect_stdout(output):
                    code = run(['--wake-root', str(root), 'sessions', 'spawn', '--profiles', str(profiles),
                        '--profile', 'worker', '--caller-thread-id', THREAD, '--intent', intent,
                        '--name', 'worker', '--task', 'Inspect approved fixture',
                        '--expires-at', '2029-01-01T00:00:00Z', '--json'])
                self.assertEqual(code, 5, output.getvalue())
                return json.loads(output.getvalue())['compatibility_preflight']
            from codex_wake.native_clock import snapshot as host_snapshot
            def fixture_clock():
                value=host_snapshot()
                return dict(value,utc=dict(status='network',lower=NOW,upper=NOW+1))
            with helper.controller(root, interval=.05) as controller, patch('codex_wake.lifecycle_budget.trusted_upper', return_value=NOW), patch('codex_wake.native_clock.snapshot',side_effect=fixture_clock):
                enroll(root, policy, THREAD, 100, 120)
                poll(root)
                # Test readiness is an ordinary wait; real engagement checks
                # still validate the resident controller's qualified evidence.
                deadline = time.monotonic() + 6
                while not show(root, policy, THREAD)['engagement']['engaged']:
                    self.assertIsNone(controller.poll())
                    self.assertLess(time.monotonic(), deadline,
                        'resident first poll did not qualify: ' + json.dumps(show(root, policy, THREAD)['engagement']))
                    time.sleep(.02)
                for event in list_notices(root, THREAD):
                    present_notice(root, event['event_id'])
                with patch('codex_wake.measurements.utc_time',return_value=NOW):
                    first = invoke()
                self.assertEqual(first['mode'], 'sampled_stop', json.dumps(first, sort_keys=True))
                self.assertTrue(first['admitted'])
                self.assertEqual(first['static']['cache'], 'created')
                self.assertEqual(first['static']['binding']['server']['pid'], os.getpid())
                self.assertFalse(first['static']['capabilities']['hard_admission'])
                self.assertFalse(first['static']['capabilities']['client_server_same_binary'])
                self.assertEqual(first['dynamic']['accounting']['used_tokens'], 40)
                with patch('codex_wake.measurements.utc_time',return_value=NOW+1):
                    repeated = invoke()
                self.assertEqual(repeated['static']['cache'], 'reused')
                self.assertEqual(repeated['static']['receipt_id'], first['static']['receipt_id'])
                self.assertGreater(repeated['dynamic']['observed_at'], first['dynamic']['observed_at'])
                client.write_text(client.read_text() + '# different selected binary\n')
                changed = invoke()
                self.assertEqual(changed['static']['cache'], 'created')
                self.assertNotEqual(changed['static']['receipt_id'], repeated['static']['receipt_id'])
                native['metadata']['userAgent'] = 'qualified-fixture-v2'
                server_changed = invoke()
                self.assertEqual(server_changed['static']['cache'], 'created')
                self.assertNotEqual(server_changed['static']['receipt_id'], changed['static']['receipt_id'])
                retained_notices = native['notices']
                native['notices'] = {}
                missing_delivery = invoke()
                self.assertEqual(missing_delivery['mode'], 'degraded')
                self.assertEqual(missing_delivery['static']['cache'], 'reused')
                self.assertTrue(missing_delivery['dynamic']['controller']['fresh'])
                self.assertTrue(all(not item['current_model_context']
                    for item in missing_delivery['dynamic']['notice_surfaces'].values()))
                native['notices'] = retained_notices
                profile['tmux_session'] = 'another-approved-tab-group'
                write_profile()
                config_changed = invoke('preflight-new-configuration')
                self.assertEqual(config_changed['static']['cache'], 'created')
                self.assertNotEqual(config_changed['static']['receipt_id'], server_changed['static']['receipt_id'])
                controller.kill()
                controller.wait(timeout=3)
                stale = invoke('preflight-new-configuration')
                self.assertEqual(stale['mode'], 'degraded')
                self.assertFalse(stale['admitted'])
                self.assertEqual(stale['static']['cache'], 'reused')
                self.assertFalse(stale['dynamic']['controller']['fresh'])
                self.assertFalse(any(method in ('thread/start', 'thread/queue/add', 'thread/goal/set', 'turn/interrupt')
                    for method, _ in native['calls']))
