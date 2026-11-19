import contextlib
import json
from datetime import UTC, datetime
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake import cli
from codex_wake.daemon import poll_once
from codex_wake.records import find_record, iter_records
from codex_wake.time_provider import TimeDecision


class NetworkWakeTests(unittest.TestCase):
    def test_cli_creation_and_poll_use_network_bounds_and_keep_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'wake'
            creation=TimeDecision('network',('a','b'),1800000000,1800000000.2)
            output=io.StringIO()
            with patch('codex_wake.time_inspection.network_time_decision',return_value=creation),contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['--wake-root',str(root),'after','--network-time','--app-server-thread-id','fixture','1m','--','Resume fixture']),0)
            record=iter_records(root)[0].record
            self.assertEqual(record['schema_version'],3)
            self.assertEqual(record['predicate']['due_at'],'2027-01-15T08:01:01Z')
            boundary=TimeDecision('network',('a','b'),1800000060.9,1800000061.2)
            held=poll_once(root,dispatch=False,time_provider=lambda:boundary)
            self.assertEqual(held.fired,0)
            self.assertEqual(find_record(root,record['id']).record['status'],'pending')
            due=TimeDecision('network',('a','b'),1800000061.1,1800000061.2)
            self.assertEqual(poll_once(root,dispatch=False,time_provider=lambda:due).fired,1)
            durable=find_record(root,record['id']).record
            self.assertEqual(durable['predicate'],record['predicate'])
            self.assertEqual(durable['prompt'],'Resume fixture')

    def test_outage_and_sleep_keep_deadline_and_allow_cancel_without_utc(self):
        from codex_wake.records import cancel_record
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'wake'
            reading=TimeDecision('network',('a','b'),1800000000,1800000000.2)
            with patch('codex_wake.time_inspection.network_time_decision',return_value=reading),contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--wake-root',str(root),'after','--network-time','--app-server-thread-id','fixture','1m','--','resume'])
            record=iter_records(root)[0].record
            original=record['predicate']
            outage=TimeDecision('uncertain',reason='network_outage')
            self.assertEqual(poll_once(root,dispatch=False,time_provider=lambda:outage).fired,0)
            with patch('codex_wake.time_inspection.network_time_decision',return_value=outage):
                cancel_record(root,record['id'])
            cancelled=find_record(root,record['id']).record
            self.assertEqual(cancelled['status'],'cancelled')
            self.assertEqual(cancelled['predicate'],original)
            self.assertIsNone(cancelled['events'][-1]['at'])

    def test_cancellation_during_acquisition_cannot_be_overwritten_by_firing(self):
        from codex_wake.records import cancel_record
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'wake'
            reading=TimeDecision('network',('a','b'),1800000000,1800000000.2)
            with patch('codex_wake.time_inspection.network_time_decision',return_value=reading),contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--wake-root',str(root),'after','--network-time','--app-server-thread-id','fixture','1m','--','resume'])
            identifier=iter_records(root)[0].record['id']
            def acquisition():
                cancel_record(root,identifier)
                return TimeDecision('network',('a','b'),1800003600,1800003600.2)
            self.assertEqual(poll_once(root,dispatch=False,time_provider=acquisition).fired,0)
            self.assertEqual([r.record['status'] for r in iter_records(root)],['cancelled'])

    def test_direct_dispatch_cannot_bypass_network_uncertainty_or_due_gate(self):
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import move_record
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'wake'
            reading=TimeDecision('network',('a','b'),1800000000,1800000000.2)
            with patch('codex_wake.time_inspection.network_time_decision',return_value=reading),contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--wake-root',str(root),'after','--network-time','--app-server-thread-id','fixture','1m','--','resume'])
            found=iter_records(root)[0]
            move_record(root,found,'firing',event_type='fixture',message='Controlled interrupted firing',now=datetime.fromtimestamp(1800000000,UTC))
            found=find_record(root,found.record['id'])
            for decision in [TimeDecision('uncertain'),reading]:
                with self.subTest(decision=decision):
                    result=dispatch_firing_record(root,found,time_provider=lambda:decision)
                    self.assertEqual(result.status,'skipped')
                    self.assertEqual(find_record(root,found.record['id']).record['attempts'],0)

    def test_absolute_fractional_deadline_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'wake'
            reading=TimeDecision('network',('a','b'),1800000000,1800000000.2)
            with patch('codex_wake.time_inspection.network_time_decision',return_value=reading),contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--wake-root',str(root),'at','--network-time','--app-server-thread-id','fixture','2027-01-15T08:01:00.123456Z','--','resume'])
            self.assertEqual(iter_records(root)[0].record['predicate']['due_at'],'2027-01-15T08:01:00.123456Z')
            before=TimeDecision('network',('a','b'),1800000060.05,1800000060.2)
            self.assertEqual(poll_once(root,dispatch=False,time_provider=lambda:before).fired,0)

    def test_fresh_post_sleep_observation_resolves_unchanged_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'wake'
            reading=TimeDecision('network',('a','b'),1800000000,1800000000.2)
            with patch('codex_wake.time_inspection.network_time_decision',return_value=reading),contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--wake-root',str(root),'after','--network-time','--app-server-thread-id','fixture','1m','--','resume'])
            original=iter_records(root)[0].record
            outage=TimeDecision('uncertain',reason='foreign_boot_or_outage')
            self.assertEqual(poll_once(root,dispatch=False,time_provider=lambda:outage).fired,0)
            fresh=TimeDecision('network',('a','b'),1800003600,1800003600.2)
            self.assertEqual(poll_once(root,dispatch=False,time_provider=lambda:fresh).fired,1)
            self.assertEqual(find_record(root,original['id']).record['predicate'],original['predicate'])

    def test_network_archive_and_cleanup_do_not_use_guest_wall_clock(self):
        from datetime import timedelta
        from codex_wake.records import archive_record, cancel_record, cleanup_archived_records
        from codex_wake.records import WakeError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'wake'
            reading = TimeDecision('network', ('a','b'), 1800000000, 1800000000.2)
            with patch('codex_wake.time_inspection.network_time_decision', return_value=reading), contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--wake-root',str(root),'after','--network-time','--app-server-thread-id','fixture','1m','--','resume'])
            identifier = iter_records(root)[0].record['id']
            cancel_record(root, identifier)
            with patch('codex_wake.time_inspection.network_time_decision', return_value=TimeDecision('uncertain')):
                with self.assertRaises(WakeError):
                    archive_record(root, identifier)
            with patch('codex_wake.time_inspection.network_time_decision', return_value=reading):
                path = archive_record(root, identifier)
                self.assertEqual(cleanup_archived_records(root, older_than=timedelta(seconds=1), now=datetime(2099,1,1,tzinfo=UTC), delete=True), [])
            self.assertTrue(path.exists())

            # The old accepted upper was truncated by its UTC string formatter.
            stored=json.loads(path.read_text())
            stored.pop('archive_time_bounds',None)
            path.write_text(json.dumps(stored))
            later=TimeDecision('network',('a','b'),1800000001.5,1800000001.7)
            with patch('codex_wake.time_inspection.network_time_decision',return_value=later):
                self.assertEqual(cleanup_archived_records(root,older_than=timedelta(seconds=1),
                    now=datetime(2099,1,1,tzinfo=UTC),delete=True),[])
            self.assertTrue(path.exists())
