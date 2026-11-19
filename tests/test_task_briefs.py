"""Task brief scope and revision continuity through its public store seam."""
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.task_briefs import BriefAuthority, TaskBriefError, TaskBriefStore


class TaskBriefTests(unittest.TestCase):
    def setUp(self):
        clock = patch('codex_wake.measurements.utc_bounds', return_value=(100, 101))
        clock.start()
        self.addCleanup(clock.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'wake'
        self.workspace = Path(self.temp.name) / 'workspace'
        self.workspace.mkdir()
        self.operator = BriefAuthority('operator:fixture', 'operator')
        self.worker = BriefAuthority('conversation:worker', 'worker', ('task-1',))
        self.content = dict(objective='Ship the approved change', phase='implementation',
            non_goals=['No deployment'], acceptance=['Public command returns expected result'],
            context=[], workspace=str(self.workspace), allocation_ref='allocation-existing',
            permission_ref='profile-existing')

    def test_proposal_approval_and_admission_use_qualified_utc_metadata(self):
        store = TaskBriefStore(self.root)
        with patch('codex_wake.task_briefs.datetime', create=True) as guest_datetime:
            guest_datetime.now.side_effect = AssertionError('WSL datetime measurement forbidden')
            proposed = store.propose('task-1', self.content, authority=self.worker)
            approved = store.approve('task-1', 1, authority=self.operator)
            admitted = store.admit('task-1', 'assignment-a', authority=self.worker)
        expected = '1970-01-01T00:01:41+00:00'
        self.assertEqual(proposed['proposed_at'], expected)
        self.assertEqual(approved['approval']['approved_at'], expected)
        self.assertEqual(admitted['admitted_at'], expected)

    def test_unqualified_time_preserves_revisions_and_admitted_assignment(self):
        from codex_wake.measurements import TimeUnavailable
        store = TaskBriefStore(self.root)
        store.propose('task-1', self.content, authority=self.worker)
        store.approve('task-1', 1, authority=self.operator)
        admitted = store.admit('task-1', 'assignment-a', authority=self.worker)
        store.propose('task-1', dict(self.content, objective='A second revision'), authority=self.worker)
        before = store.inspect('task-1')
        pin = store.assignment_pin('task-1', 'assignment-a', authority=self.worker)
        writes = (
            ('new-task', lambda: store.propose('task-2', self.content, authority=self.operator)),
            ('new-revision', lambda: store.propose('task-1', self.content, authority=self.worker)),
            ('approval', lambda: store.approve('task-1', 2, authority=self.operator)),
            ('admission', lambda: store.admit('task-1', 'assignment-b', authority=self.worker)),
        )
        with patch('codex_wake.measurements.utc_bounds', side_effect=TimeUnavailable('private-clock-detail')):
            for name, operation in writes:
                with self.subTest(operation=name):
                    with self.assertRaises(TaskBriefError) as held:
                        operation()
                    self.assertEqual(held.exception.code, 'qualified_time_unavailable')
                    self.assertNotIn('private-clock-detail', str(held.exception))
                    self.assertEqual(store.inspect('task-1'), before)
            self.assertEqual(store.inspect('task-2')['revisions'], [])
            self.assertEqual(store.admit('task-1', 'assignment-a', authority=self.worker), admitted)
            self.assertEqual(store.validate_pin(pin, authority=self.worker), pin)

    def test_worker_proposal_does_not_approve_or_admit_assignment(self):
        store = TaskBriefStore(self.root)
        proposed = store.propose('task-1', self.content, authority=self.worker)
        self.assertEqual(proposed['revision'], 1)
        self.assertEqual(proposed['status'], 'proposed')
        with self.assertRaises(TaskBriefError) as denied:
            store.approve('task-1', 1, authority=self.worker)
        self.assertEqual(denied.exception.code, 'authority_denied')
        with self.assertRaises(TaskBriefError) as unapproved:
            store.admit('task-1', 'assignment-a', authority=self.worker)
        self.assertEqual(unapproved.exception.code, 'brief_unapproved')
        self.assertIsNone(store.inspect('task-1')['approved_revision'])

    def test_assignment_pin_survives_new_approved_revision_and_restart(self):
        store = TaskBriefStore(self.root)
        store.propose('task-1', self.content, authority=self.worker)
        store.approve('task-1', 1, authority=self.operator)
        first = store.admit('task-1', 'assignment-a', authority=self.worker)
        revised = dict(self.content, objective='Ship the approved revised change')
        store.propose('task-1', revised, authority=self.worker)
        store.approve('task-1', 2, authority=self.operator)
        reconstructed = TaskBriefStore(self.root)
        self.assertEqual(reconstructed.admit('task-1', 'assignment-a', authority=self.worker), first)
        next_assignment = reconstructed.admit('task-1', 'assignment-b', authority=self.worker)
        self.assertEqual(first['pin']['revision'], 1)
        self.assertEqual(next_assignment['pin']['revision'], 2)
        with self.assertRaises(TaskBriefError) as conflict:
            reconstructed.admit('task-1', 'assignment-a', revision=2, authority=self.worker)
        self.assertEqual(conflict.exception.code, 'assignment_conflict')

    def test_required_context_must_still_match_before_new_assignment(self):
        evidence = self.workspace / 'acceptance.txt'
        evidence.write_text('Approved acceptance evidence')
        content = dict(self.content, context=[dict(path=str(evidence),
            sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(), required=True)])
        store = TaskBriefStore(self.root)
        store.propose('task-1', content, authority=self.worker)
        store.approve('task-1', 1, authority=self.operator)
        first = store.admit('task-1', 'assignment-a', authority=self.worker)
        evidence.write_text('Changed acceptance evidence')
        with self.assertRaises(TaskBriefError) as changed:
            store.admit('task-1', 'assignment-b', authority=self.worker)
        self.assertEqual(changed.exception.code, 'context_changed')
        self.assertEqual(store.admit('task-1', 'assignment-a', authority=self.worker), first)
        evidence.unlink()
        with self.assertRaises(TaskBriefError) as missing:
            store.admit('task-1', 'assignment-c', authority=self.worker)
        self.assertEqual(missing.exception.code, 'context_unavailable')
        self.assertEqual(len(store.inspect('task-1')['admissions']), 1)

    def test_scoped_controller_can_approve_only_its_delegated_task(self):
        store = TaskBriefStore(self.root)
        controller = BriefAuthority('controller:fixture', 'controller', ('task-1',))
        store.propose('task-1', self.content, authority=self.worker)
        store.approve('task-1', 1, authority=controller)
        admitted = store.admit('task-1', 'assignment-a', authority=self.worker)
        self.assertEqual(admitted['pin']['approval']['actor_id'], 'controller:fixture')
        other = BriefAuthority('worker:other', 'worker', ('task-2',))
        store.propose('task-2', self.content, authority=other)
        with self.assertRaises(TaskBriefError) as denied:
            store.approve('task-2', 1, authority=controller)
        self.assertEqual(denied.exception.code, 'authority_denied')

    def test_assignment_checkpoint_pin_rejects_tampering_after_restart(self):
        store = TaskBriefStore(self.root)
        store.propose('task-1', self.content, authority=self.worker)
        store.approve('task-1', 1, authority=self.operator)
        store.admit('task-1', 'assignment-a', authority=self.worker)
        pin = store.assignment_pin('task-1', 'assignment-a', authority=self.worker)
        self.assertEqual(pin['assignment_id'], 'assignment-a')
        restarted = TaskBriefStore(self.root)
        self.assertEqual(restarted.validate_pin(pin, authority=self.worker), pin)
        forged = dict(pin, revision=2)
        with self.assertRaises(TaskBriefError):
            restarted.validate_pin(forged, authority=self.worker)

    def test_concurrent_revision_and_assignment_admission_never_mix_content(self):
        import threading
        store = TaskBriefStore(self.root)
        store.propose('task-1', self.content, authority=self.worker)
        store.approve('task-1', 1, authority=self.operator)
        revised = dict(self.content, objective='Different approved objective')
        store.propose('task-1', revised, authority=self.worker)
        start = threading.Barrier(3)
        result, errors = [], []
        def approve():
            try:
                start.wait()
                TaskBriefStore(self.root).approve('task-1', 2, authority=self.operator)
            except Exception as error:
                errors.append(error)
        def admit():
            try:
                start.wait()
                result.append(TaskBriefStore(self.root).admit('task-1', 'assignment-a', authority=self.worker))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=approve), threading.Thread(target=admit)]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(result), 1)
        pin = store.assignment_pin('task-1', 'assignment-a', authority=self.worker)
        self.assertIn(pin['revision'], [1, 2])
        revision = store.inspect('task-1')['revisions'][pin['revision'] - 1]
        self.assertEqual(pin['digest'], revision['digest'])
        self.assertEqual(pin['approval']['actor_id'], 'operator:fixture')

    def test_context_bounds_and_unsafe_paths_do_not_admit(self):
        store = TaskBriefStore(self.root)
        large = self.workspace / 'large.txt'
        large.write_bytes(b'x' * (1024 * 1024 + 1))
        content = dict(self.content, context=[dict(path=str(large),
            sha256=hashlib.sha256(large.read_bytes()).hexdigest(), required=True)])
        store.propose('task-1', content, authority=self.worker)
        store.approve('task-1', 1, authority=self.operator)
        with self.assertRaises(TaskBriefError) as oversized:
            store.admit('task-1', 'assignment-a', authority=self.worker)
        self.assertEqual(oversized.exception.code, 'context_unavailable')
        outside = Path(self.temp.name) / 'private.txt'
        outside.write_text('Must not be read')
        link = self.workspace / 'link.txt'
        link.symlink_to(outside)
        linked = dict(self.content, context=[dict(path=str(link), sha256='a' * 64, required=True)])
        with self.assertRaises(TaskBriefError):
            store.propose('task-1', linked, authority=self.worker)
        self.assertEqual(store.inspect('task-1')['admissions'], [])

    def test_unknown_record_version_and_public_state_file_hold(self):
        import json
        store = TaskBriefStore(self.root)
        store.propose('task-1', self.content, authority=self.worker)
        path = next((self.root / 'task-briefs').glob('*.json'))
        state = json.loads(path.read_text())
        state['version'] = 2
        path.write_text(json.dumps(state))
        with self.assertRaises(TaskBriefError) as unknown:
            store.inspect('task-1')
        self.assertEqual(unknown.exception.code, 'store_invalid')
        path.chmod(0o644)
        from codex_wake.records import WakeError
        with self.assertRaises(WakeError):
            store.inspect('task-1')
