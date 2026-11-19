"""Managed identity is independent from the currently verified process/tab."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from codex_wake.managed_inventory_commands import execute
from codex_wake.managed_inventory import Observation

THREAD = '00000000-0000-7000-8000-000000000315'
SUCCESSOR = '00000000-0000-7000-8000-000000000316'
NOW = 1792872000.0


class StableInventoryClockTests(unittest.TestCase):
    def test_inventory_keeps_utc_metadata_and_uses_counter_evidence_for_freshness(self):
        from unittest.mock import patch
        from codex_wake import measurements
        from codex_wake.managed_inventory import ManagedInventory
        anchor = dict(reason='authenticated_counter_only', counter=dict(
            epoch='c357309d-c209-4467-b757-e1488e6b1aaa', counter=1000,
            frequency=1000, rate_ppm=0))
        current = dict(anchor, counter=dict(anchor['counter'], counter=2000))
        with tempfile.TemporaryDirectory() as temporary:
            sample = observation(clock_observation=anchor)
            with patch.object(measurements, 'snapshot', return_value=current), patch.object(measurements, 'utc_time', return_value=NOW-8):
                inventory = ManagedInventory(Path(temporary)/'wake')
                agent = inventory.enroll(sample, operator=True)['agent']
                self.assertTrue(agent['binding_current'])
                self.assertEqual(agent['observed_at'], NOW)
                self.assertEqual(agent['clock_observation'], anchor)
                changed_epoch = dict(current, counter=dict(current['counter'],
                    epoch='d357309d-c209-4467-b757-e1488e6b1aaa'))
                with patch.object(measurements, 'snapshot', return_value=changed_epoch):
                    self.assertEqual(inventory.inspect(agent['managed_agent_id'])['agent']['state'], 'stale')


def native_context(thread=THREAD):
    return {'threadId': thread, 'sessionId': thread, 'callId': 'call-315',
            'x-codex-turn-metadata': {'thread_id': thread, 'session_id': thread,
                                    'turn_id': 'turn-315'}}


def observation(thread=THREAD, **updates):
    value = dict(runtime='codex', namespace='codex:fixture', conversation_id=thread,
                 root='/fixture/repo', state='ready', observed_at=NOW,
                 source='native_metadata', process={'pid': 123, 'start_ticks': 500,
                                                   'boot_id': 'fixture-boot'},
                 attachments=[{'pane_id': '%1', 'window_id': '@1'}],
                 capabilities={'inspect': 'supported', 'refresh': 'not_qualified'},
                 profile=None)
    value.update(updates)
    return Observation(**value)


class ManagedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'wake'
        self.addCleanup(self.temp.cleanup)

    def call(self, action, arguments=None, *, sample=None, context=None, operator=False):
        return execute(action, arguments or {}, self.root,
                       native_context=native_context() if context is None else context,
                       observer=lambda _args: sample or observation(), operator=operator,
                       now=lambda: NOW)

    def test_verified_self_enrollment_is_default_and_durable_across_process_and_tab_change(self):
        first = self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD})
        self.assertEqual(first['status'], 'enrolled')
        agent = first['agent']['managed_agent_id']
        moved = observation(process={'pid': 456, 'start_ticks': 900, 'boot_id': 'new-boot'},
                            attachments=[{'pane_id': '%9', 'window_id': '@7'}])
        again = self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD}, sample=moved)
        self.assertEqual(again['agent']['managed_agent_id'], agent)
        view = self.call('show', {'managed_agent_id': agent})
        self.assertEqual(view['agent']['process']['pid'], 456)
        self.assertEqual(view['agent']['attachments'][0]['pane_id'], '%9')
        self.assertFalse(view['agent']['grants_operations'])

    def test_operator_policy_and_unenrollment_survive_default_changes_and_restart(self):
        self.call('configure', {'mode': 'operator_only'}, operator=True)
        with self.assertRaisesRegex(Exception, 'operator'):
            self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD})
        first = self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD}, operator=True)
        agent = first['agent']['managed_agent_id']
        self.call('unenroll', {'managed_agent_id': agent}, operator=True)
        self.call('configure', {'mode': 'self_enrollment'}, operator=True)
        suppressed = self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD})
        self.assertEqual(suppressed['status'], 'suppressed')
        self.assertEqual(self.call('list')['agents'][0]['enrollment'], 'suppressed')
        self.call('reenable', {'managed_agent_id': agent}, operator=True)
        self.assertEqual(self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD})['status'], 'enrolled')
        with self.assertRaisesRegex(Exception, 'operator'):
            self.call('configure', {'mode': 'self_enrollment'})

    def test_unavailable_reconciliation_preserves_identity_and_never_rebinds_another_conversation(self):
        first = self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD})['agent']
        args = {'managed_agent_id': first['managed_agent_id'], 'runtime': 'codex', 'conversation_id': THREAD}
        unavailable = observation(state='unavailable', process=None, attachments=[])
        result = self.call('reconcile', args, sample=unavailable)
        self.assertEqual(result['agent']['state'], 'unavailable')
        self.assertEqual(result['agent']['managed_agent_id'], first['managed_agent_id'])
        with self.assertRaisesRegex(Exception, 'identity'):
            self.call('reconcile', args, sample=observation(thread=SUCCESSOR))
        self.assertEqual(self.call('show', args)['agent']['state'], 'unavailable')
        with self.assertRaisesRegex(Exception, 'fresh'):
            self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD},
                      sample=observation(observed_at=NOW - 60))

    def test_successor_is_new_agent_with_continuing_task_and_allocation(self):
        parent = self.call('enroll', {'runtime': 'codex', 'conversation_id': THREAD,
                                    'task_id': 'task-1', 'allocation_id': 'allocation-1'})['agent']
        child = self.call('enroll', {'runtime': 'codex', 'conversation_id': SUCCESSOR,
                                   'predecessor': parent['managed_agent_id']},
                          sample=observation(thread=SUCCESSOR), context=native_context(SUCCESSOR))['agent']
        self.assertNotEqual(parent['managed_agent_id'], child['managed_agent_id'])
        self.assertEqual(child['predecessor'], parent['managed_agent_id'])
        self.assertEqual(child['task_id'], 'task-1')
        self.assertEqual(child['allocation_id'], 'allocation-1')

    def test_concurrent_enrollment_has_one_identity_and_spoofed_claim_has_no_record(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.call('enroll', {'conversation_id': THREAD})['agent']['managed_agent_id'], range(8)))
        self.assertEqual(len(set(ids)), 1)
        with self.assertRaisesRegex(Exception, 'identity'):
            self.call('enroll', {'conversation_id': SUCCESSOR}, sample=observation(thread=SUCCESSOR))
        self.assertEqual(len(self.call('list')['agents']), 1)

    def test_operator_selected_policy_and_expired_read_projection_do_not_claim_readiness(self):
        self.call('configure', {'mode': 'operator_selected', 'selected': [
            {'runtime': 'codex', 'namespace': 'codex:fixture', 'conversation_id': THREAD}]}, operator=True)
        first = self.call('enroll', {'conversation_id': THREAD})['agent']
        stale = execute('show', {'managed_agent_id': first['managed_agent_id']}, self.root,
                        now=lambda: NOW + 31)
        self.assertEqual(stale['agent']['state'], 'stale')
        self.assertFalse(stale['agent']['binding_current'])
        with self.assertRaisesRegex(Exception, 'operator'):
            self.call('enroll', {'conversation_id': SUCCESSOR}, sample=observation(thread=SUCCESSOR),
                      context=native_context(SUCCESSOR))

    def test_grok_self_enrollment_requires_host_bound_caller_evidence(self):
        args = {'runtime': 'grok', 'conversation_id': 'grok-session'}
        sample = observation(thread='grok-session', runtime='grok', namespace='grok:fixture',
                             source='host_bound_runtime')
        with self.assertRaisesRegex(Exception, 'caller'):
            self.call('enroll', args, sample=sample)
        authenticated = Observation(**dict(sample.__dict__, caller_verified=True))
        result = self.call('enroll', args, sample=authenticated)
        self.assertEqual(result['agent']['runtime'], 'grok')
        self.assertEqual(result['agent']['evidence_kind'], 'host_bound_runtime')

    def test_unknown_inventory_version_and_private_path_fail_closed(self):
        self.call('enroll', {'conversation_id': THREAD})
        path = self.root / 'managed-inventory' / 'inventory.json'
        value = json.loads(path.read_text())
        value['version'] = 999
        path.write_text(json.dumps(value))
        original = path.read_bytes()
        with self.assertRaisesRegex(Exception, 'version is unsupported'):
            self.call('list')
        self.assertEqual(path.read_bytes(), original)
        path.chmod(0o644)
        with self.assertRaisesRegex(Exception, 'owned and private'):
            self.call('list')

    def test_failed_native_observation_marks_exact_record_unavailable_without_new_identity(self):
        from codex_wake.managed_inventory import InventoryError
        first = self.call('enroll', {'conversation_id': THREAD})['agent']
        def lost(_):
            raise InventoryError('identity_unavailable', 'qualified source unavailable')
        args = {'managed_agent_id': first['managed_agent_id'], 'conversation_id': THREAD}
        result = execute('reconcile', args, self.root, native_context=native_context(),
                         observer=lost, now=lambda: NOW)
        self.assertEqual(result['agent']['state'], 'unavailable')
        self.assertEqual(result['agent']['managed_agent_id'], first['managed_agent_id'])
        self.assertEqual(len(self.call('list')['agents']), 1)
