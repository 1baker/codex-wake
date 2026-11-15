from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.daemon import poll_once
from codex_wake.time_provider import TimeDecision
from codex_wake.records import all_records, build_record, write_record


class NativeDeliveryTests(unittest.TestCase):
    def setUp(self):
        from codex_wake.time_provider import TimeDecision
        reading = TimeDecision('network', ('a','b'), 1791504000, 1791504000.2)
        provider = patch('codex_wake.time_inspection.network_time_decision', return_value=reading)
        provider.start()
        self.addCleanup(provider.stop)

    def test_file_wake_expires_even_if_file_never_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            record = all_records(root)[0].record
            record['predicate'] = {'type': 'file_exists', 'path': str(root / 'missing')}
            from codex_wake.records import replace_record
            replace_record(root, all_records(root)[0], record)
            poll_once(root, datetime(2026, 10, 9, 0, 11, tzinfo=UTC))
            self.assertEqual(all_records(root)[0].record['status'], 'failed')

    def native_record(self, root, executable):
        record = build_record(predicate={'type': 'not_before', 'due_at': '2026-10-09T00:00:00Z'},
                              prompt='Execute the task', cwd=root,
                              target={'transport': 'native', 'thread_id': '01a1227e-a041-7b72-9c36-18349e7dd22c',
                                      'endpoint': 'unix://', 'codex_cmd': str(executable),
                                      'expires_at': '2026-10-09T00:10:00Z'})
        write_record(root, record)

    def test_busy_recipient_holds_until_expiry_without_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            with patch('codex_wake.native_delivery.read_native_thread',
                       return_value={'id': '01a1227e-a041-7b72-9c36-18349e7dd22c', 'status': {'type': 'active'}}):
                result = poll_once(root, datetime(2026, 10, 9, tzinfo=UTC))
            self.assertEqual(result.requeued, 1)
            self.assertEqual(all_records(root)[0].record['status'], 'pending')
            self.assertEqual(all_records(root)[0].record['attempts'], 0)
            result = poll_once(root, datetime(2026, 10, 9, 0, 11, tzinfo=UTC))
            self.assertEqual(result.failed, 1)
            self.assertNotIn('native_delivery', all_records(root)[0].record)
            self.assertEqual(all_records(root)[0].record['attempts'], 0)

    def test_busy_recipient_reports_runtime_readiness_without_consuming_an_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            with patch('codex_wake.native_delivery.read_native_thread',
                       return_value={'id': '01a1227e-a041-7b72-9c36-18349e7dd22c',
                                     'status': {'type': 'active'}}):
                result = poll_once(root, datetime(2026, 10, 9, tzinfo=UTC))
            record = all_records(root)[0].record
            self.assertEqual(result.requeued, 1)
            self.assertEqual(record['attempts'], 0)
            observation = record['runtime_observation']
            self.assertEqual(observation['version'], 1)
            self.assertEqual(observation['runtime'], 'codex')
            self.assertEqual(observation['session_id'], record['target']['thread_id'])
            self.assertEqual(observation['state'], 'busy')
            self.assertEqual(observation['capabilities']['submit']['state'], 'supported')
            self.assertEqual(observation['capabilities']['busy_queue']['state'], 'not_qualified')
            self.assertEqual(observation['capabilities']['interrupt']['state'], 'unsupported')

    def test_dispatcher_uses_runtime_interface_for_submission(self):
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import replace_record
        from codex_wake.runtime_delivery import (
            RuntimeObservation, RuntimeRecipient, RuntimeSubmission,
        )
        receipt = '01a12280-80ef-7772-a00a-c68bd32ecbba'
        delivered = []

        class Runtime:
            def resolve(self, target):
                return RuntimeRecipient('codex', target['thread_id'], {})

            def observe(self, recipient):
                return RuntimeObservation('ready', 'fixture_recipient_idle', {})

            def submit(self, recipient, prompt):
                delivered.append((recipient.session_id, prompt))
                return RuntimeSubmission('accepted', receipt_id=receipt,
                                         evidence_kind='native_queue_acceptance')

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            found = all_records(root)[0]
            record = dict(found.record, status='firing')
            replace_record(root, found, record)
            with patch('codex_wake.native_delivery.read_native_thread',
                       side_effect=AssertionError('Codex I/O bypassed the runtime seam')), patch(
                       'codex_wake.native_delivery.subprocess.run',
                       side_effect=AssertionError('submission bypassed the runtime seam')):
                result = dispatch_firing_record(
                    root, all_records(root)[0], now=datetime(2026, 10, 9, tzinfo=UTC),
                    runtime_adapter=Runtime(),
                )
            saved = all_records(root)[0].record
            self.assertEqual(result.status, 'submitted')
            self.assertEqual(saved['native_delivery']['queue_id'], receipt)
            self.assertEqual(saved['attempts'], 1)
            self.assertEqual(len(delivered), 1)
            self.assertEqual(delivered[0][0], saved['target']['thread_id'])
            self.assertIn('WAKE_NATIVE_SUBMISSION_ID=', delivered[0][1])
            self.assertEqual(saved['native_delivery']['acknowledgment'], 'not_observed')

    def test_dispatcher_reconciles_runtime_acceptance_without_replaying_lost_response(self):
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import replace_record
        from codex_wake.runtime_delivery import (
            RuntimeObservation, RuntimeRecipient, RuntimeReconciliation,
        )
        deliveries = []

        class Runtime:
            def resolve(self, target):
                return RuntimeRecipient('codex', target['thread_id'], {})

            def observe(self, recipient):
                return RuntimeObservation('ready', 'fixture_recipient_idle', {})

            def submit(self, recipient, prompt):
                deliveries.append(prompt)
                raise OSError('accepted but response lost: PRIVATE_TRANSPORT_DETAIL')

            def reconcile(self, recipient, prompt):
                if deliveries != [prompt]:
                    raise AssertionError('reconciliation changed the original submission')
                return RuntimeReconciliation({
                    'source': 'native_turn', 'turn_id': 'turn-exact',
                    'user_message_id': 'message-exact', 'client_message_id': 'client-exact',
                    'execution': 'turn_completed',
                })

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            found = all_records(root)[0]
            replace_record(root, found, dict(found.record, status='firing'))
            runtime = Runtime()
            with patch('codex_wake.native_delivery.native_request',
                       side_effect=AssertionError('reconciliation bypassed runtime interface')), patch(
                       'codex_wake.native_delivery.subprocess.run',
                       side_effect=AssertionError('submission bypassed runtime interface')):
                first = dispatch_firing_record(
                    root, all_records(root)[0], now=datetime(2026, 10, 9, tzinfo=UTC),
                    runtime_adapter=runtime,
                )
                self.assertEqual(first.status, 'skipped')
                self.assertEqual(all_records(root)[0].record['native_delivery']['state'], 'uncertain')
                second = dispatch_firing_record(
                    root, all_records(root)[0], now=datetime(2026, 10, 9, 0, 1, tzinfo=UTC),
                    runtime_adapter=runtime,
                )
            import json
            saved = all_records(root)[0].record
            self.assertEqual(second.status, 'submitted')
            self.assertEqual(len(deliveries), 1)
            self.assertEqual(saved['attempts'], 1)
            self.assertEqual(saved['native_delivery']['execution'], 'turn_completed')
            self.assertEqual(saved['native_delivery']['acknowledgment'], 'not_observed')
            self.assertNotIn('PRIVATE_TRANSPORT_DETAIL', json.dumps(saved))

    def test_runtime_observation_failure_holds_without_attempt_or_private_detail(self):
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import replace_record
        from codex_wake.runtime_delivery import RuntimeRecipient

        class Runtime:
            def resolve(self, target):
                return RuntimeRecipient('codex', target['thread_id'], {})

            def observe(self, recipient):
                raise OSError('PRIVATE_RUNTIME_ENDPOINT')

            def submit(self, recipient, prompt):
                raise AssertionError('must not submit without readiness')

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            found = all_records(root)[0]
            replace_record(root, found, dict(found.record, status='firing'))
            result = dispatch_firing_record(
                root, all_records(root)[0], now=datetime(2026, 10, 9, tzinfo=UTC),
                runtime_adapter=Runtime(),
            )
            saved = all_records(root)[0].record
            self.assertEqual(result.status, 'requeued')
            self.assertEqual(saved['attempts'], 0)
            self.assertEqual(saved['runtime_observation']['state'], 'unavailable')
            self.assertNotIn('PRIVATE_RUNTIME_ENDPOINT', str(saved))

    def test_unknown_runtime_envelope_and_changed_identity_hold_before_observation(self):
        from unittest.mock import Mock
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import replace_record
        from codex_wake.runtime_delivery import RuntimeRecipient
        for runtime, identity, version, state in (
            ('codex', None, 2, 'unsupported'),
            ('grok', None, 1, 'unavailable'),
            ('codex', 'different-thread', 1, 'unavailable'),
        ):
            with self.subTest(runtime=runtime, identity=identity, version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.native_record(root, root / 'must-not-run')
                found = all_records(root)[0]
                replace_record(root, found, dict(found.record, status='firing'))
                adapter = Mock()
                adapter.resolve.return_value = RuntimeRecipient(
                    runtime, identity or found.record['target']['thread_id'], {}, version,
                )
                result = dispatch_firing_record(
                    root, all_records(root)[0], now=datetime(2026, 10, 9, tzinfo=UTC),
                    runtime_adapter=adapter,
                )
                saved = all_records(root)[0].record
                self.assertEqual(result.status, 'requeued')
                self.assertEqual(saved['attempts'], 0)
                self.assertEqual(saved['runtime_observation']['state'], state)
                adapter.observe.assert_not_called()
                adapter.submit.assert_not_called()

    def test_terminal_observation_cannot_confirm_native_acceptance_or_reconciliation(self):
        from unittest.mock import Mock
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import replace_record
        from codex_wake.runtime_delivery import (
            RuntimeRecipient, RuntimeObservation, RuntimeSubmission, RuntimeReconciliation,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            found = all_records(root)[0]
            replace_record(root, found, dict(found.record, status='firing'))
            adapter = Mock()
            adapter.resolve.return_value = RuntimeRecipient('codex', found.record['target']['thread_id'], {})
            adapter.observe.return_value = RuntimeObservation('ready', 'idle', {})
            adapter.submit.return_value = RuntimeSubmission(
                'accepted', '01a12280-80ef-7772-a00a-c68bd32ecbba', 'terminal_observation',
            )
            adapter.reconcile.return_value = RuntimeReconciliation(
                {'source': 'terminal_observation', 'execution': 'turn_completed'},
            )
            for minute in (0, 1):
                result = dispatch_firing_record(
                    root, all_records(root)[0], now=datetime(2026, 10, 9, 0, minute, tzinfo=UTC),
                    runtime_adapter=adapter,
                )
                self.assertEqual(result.status, 'skipped')
                self.assertEqual(all_records(root)[0].record['native_delivery']['state'], 'uncertain')
            self.assertEqual(all_records(root)[0].record['attempts'], 1)
            adapter.submit.assert_called_once()

    def test_uncertain_acceptance_is_not_resubmitted_on_another_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / 'codex'
            counter = root / 'calls'
            executable.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\n'
                                  'if sys.argv[1] != "queue": sys.exit(2)\n'
                                  f'with Path({str(counter)!r}).open("a") as f: f.write("call\\n")\n'
                                  'print("Unknown result")\n')
            executable.chmod(0o700)
            self.native_record(root, executable)
            with patch('codex_wake.native_delivery.read_native_thread',
                       return_value={'id': '01a1227e-a041-7b72-9c36-18349e7dd22c', 'status': {'type': 'idle'}}):
                poll_once(root, datetime(2026, 10, 9, tzinfo=UTC))
                poll_once(root, datetime(2026, 10, 9, 0, 1, tzinfo=UTC))
            self.assertEqual(counter.read_text(), 'call\n')
            self.assertEqual(all_records(root)[0].record['native_delivery']['state'], 'uncertain')
            self.assertEqual(all_records(root)[0].record['native_delivery']['reconciliation']['state'], 'unresolved')
            self.assertEqual(all_records(root)[0].record['attempts'], 1)

    def test_rejected_queue_retains_safe_diagnostics_without_resend(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / 'codex'
            counter = root / 'calls'
            executable.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                'if sys.argv[1] != "queue": sys.exit(2)\n'
                f'with Path({str(counter)!r}).open("a") as f: f.write("call\\n")\n'
                'print("PRIVATE_STDOUT")\n'
                'print("Error: thread not found; Bearer PRIVATE_TOKEN", file=sys.stderr)\n'
                'sys.exit(7)\n')
            executable.chmod(0o700)
            self.native_record(root, executable)
            with patch('codex_wake.native_delivery.read_native_thread',
                return_value={'id': '01a1227e-a041-7b72-9c36-18349e7dd22c', 'status': {'type': 'idle'}}):
                poll_once(root, datetime(2026, 10, 9, tzinfo=UTC))
                initial = all_records(root)[0].record
                diagnostic = initial['native_delivery']['submission_failure']
                self.assertEqual(diagnostic['reason'], 'queue_exit_nonzero')
                self.assertEqual(diagnostic['returncode'], 7)
                self.assertEqual(diagnostic['stderr']['hints'], ['thread_not_found'])
                self.assertNotIn('PRIVATE_TOKEN', json.dumps(initial))
                self.assertNotIn('PRIVATE_STDOUT', json.dumps(initial))
                self.assertLess(len(json.dumps(diagnostic)), 1024)
                poll_once(root, datetime(2026, 10, 9, 0, 1, tzinfo=UTC))
            final = all_records(root)[0].record
            self.assertEqual(counter.read_text(), 'call\n')
            self.assertEqual(final['attempts'], 1)
            self.assertEqual(final['native_delivery']['state'], 'uncertain')
            self.assertEqual(final['native_delivery']['submission_failure'], diagnostic)

    def test_queue_timeout_and_unconfirmed_output_keep_bounded_failure_evidence(self):
        import json
        import subprocess
        outcomes = [
            (subprocess.TimeoutExpired(['queue', 'PRIVATE_ARG'], 30,
                output=b'PRIVATE_OUTPUT', stderr=b'PRIVATE_SECRET' * 1000), 'queue_timeout'),
            (subprocess.CompletedProcess(['PRIVATE_ARG'], 0, 'PRIVATE_STDOUT',
                'PRIVATE_UNKNOWN_ERROR'), 'queue_acceptance_unconfirmed'),
            (PermissionError('PRIVATE_PATH'), 'queue_os_error'),
        ]
        for outcome, reason in outcomes:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.native_record(root, root / 'must-not-run')
                options = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
                with patch('codex_wake.native_delivery.read_native_thread',
                    return_value={'id': '01a1227e-a041-7b72-9c36-18349e7dd22c', 'status': {'type': 'idle'}}), patch(
                    'codex_wake.native_delivery.subprocess.run', **options) as submit, patch(
                    'codex_wake.native_delivery.native_request', side_effect=RuntimeError('unavailable')):
                    poll_once(root, datetime(2026, 10, 9, tzinfo=UTC))
                    initial = all_records(root)[0].record
                    diagnostic = initial['native_delivery']['submission_failure']
                    self.assertEqual(diagnostic['reason'], reason)
                    self.assertLess(len(json.dumps(diagnostic)), 1024)
                    self.assertNotIn('PRIVATE_', json.dumps(initial))
                    if reason == 'queue_timeout':
                        self.assertTrue(diagnostic['stderr']['truncated'])
                        self.assertEqual(diagnostic['stderr']['hints'], [])
                    poll_once(root, datetime(2026, 10, 9, 0, 1, tzinfo=UTC))
                self.assertEqual(submit.call_count, 1)
                final = all_records(root)[0].record
                self.assertEqual(final['attempts'], 1)
                self.assertEqual(final['native_delivery']['state'], 'uncertain')
                self.assertEqual(final['native_delivery']['submission_failure'], diagnostic)

    def test_persisted_due_wake_uses_native_queue_and_records_acceptance(self):
        thread = '01a1227e-a041-7b72-9c36-18349e7dd22c'
        queue = '01a12280-80ef-7772-a00a-c68bd32ecbba'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'wake'
            executable = Path(tmp) / 'codex'
            executable.write_text('#!/usr/bin/env python3\nimport sys\n'
                                  'assert sys.argv[1] == "queue"\n'
                                  f'print("Queued message {queue} for thread {thread}.")\n')
            executable.chmod(0o700)
            self.assertEqual(run(['--wake-root', str(root), 'native', 'at',
                                  '--codex-path', str(executable), thread,
                                  '2026-10-09T00:00:00Z', '--', 'Do the scheduled task']), 0)
            with patch('codex_wake.native_delivery.read_native_thread',
                       return_value={'id': thread, 'status': {'type': 'idle'}}), patch(
                       'codex_wake.injector.SubprocessTmuxRunner') as tmux:
                result = poll_once(root, datetime(2026, 10, 9, tzinfo=UTC), time_provider=lambda: TimeDecision('network', ('a', 'b'), 1791504001, 1791504001.1))
            tmux.assert_not_called()
            self.assertEqual(result.submitted, 1)
            record = all_records(root)[0].record
            self.assertEqual(record['attempts'], 1)
            self.assertEqual(record['native_delivery']['queue_id'], queue)
            self.assertEqual(record['native_delivery']['execution'], 'not_observed')
            self.assertEqual(record['native_delivery']['acknowledgment'], 'not_observed')

    def test_reconcile_recovers_exact_native_turn_without_resending(self):
        from codex_wake.records import replace_record
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root/'must-not-submit')
            found = all_records(root)[0]
            record = dict(found.record, status='firing', native_delivery={
                'state':'uncertain','execution':'not_observed','acknowledgment':'not_observed'})
            replace_record(root, found, record)
            prompt = f"WAKE_TRIGGER_ID={record['id']}\nWAKE_TRIGGER_ROOT={root.resolve()}\nExecute the task"
            def native(endpoint, codex, method, params, timeout):
                if method == 'thread/queue/list':
                    return {'data':[], 'nextCursor':None}
                if method=='thread/read':return {'thread':{'id':record['target']['thread_id']}}
                return {'data':[
                    {'id':'turn-exact','status':'completed','itemsView':'full','items':[{'type':'userMessage',
                     'id':'message-exact','clientId':'client-exact',
                     'content':[{'type':'text','text':prompt}]}]}],'nextCursor':None}
            with patch('codex_wake.native_delivery.native_request', side_effect=native), patch(
                    'codex_wake.native_delivery.subprocess.run') as effect:
                self.assertEqual(run(['--wake-root',str(root),'native','reconcile',record['id']]),0)
            effect.assert_not_called()
            recovered = all_records(root)[0].record
            self.assertEqual(recovered['status'],'submitted')
            self.assertEqual(recovered['native_delivery']['state'],'accepted')
            self.assertEqual(recovered['native_delivery']['execution'],'turn_completed')
            self.assertEqual(recovered['native_delivery']['evidence']['turn_id'],'turn-exact')
            self.assertEqual(recovered['native_delivery']['acknowledgment'],'not_observed')

    def test_explicit_missing_resume_uses_same_thread_without_opening_a_tab(self):
        thread='01a1227e-a041-7b72-9c36-18349e7dd22c'
        queue='01a12280-80ef-7772-a00a-c68bd32ecbba'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wakes'; executable=Path(tmp)/'codex'
            executable.write_text('#!/usr/bin/env python3\n'+f'print("Queued message {queue} for thread {thread}.")\n')
            executable.chmod(0o700)
            self.assertEqual(run(['--wake-root',str(root),'native','at','--resume-missing',
                '--codex-path',str(executable),thread,'2026-10-09T00:00:00Z','--','Resume this exact thread']),0)
            with patch('codex_wake.native_delivery.read_native_thread',side_effect=[
                    {'id':thread,'status':{'type':'notLoaded'}},{'id':thread,'status':{'type':'idle'}}]), patch(
                    'codex_wake.native_delivery.native_request',return_value={'thread':{'id':thread}}) as native, patch(
                    'codex_wake.injector.SubprocessTmuxRunner') as tmux:
                result=poll_once(root,datetime(2026,10,9,tzinfo=UTC), time_provider=lambda: TimeDecision('network', ('a', 'b'), 1791504001, 1791504001.1))
            self.assertEqual(result.submitted,1)
            self.assertEqual(native.call_args.args[2:4],('thread/resume',{'threadId':thread}))
            tmux.assert_not_called()
            self.assertEqual(all_records(root)[0].record['target']['thread_id'],thread)

    def test_duplicate_native_turns_remain_uncertain_even_with_same_client_identity(self):
        from codex_wake.records import replace_record
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.native_record(root,root/'must-not-submit')
            found=all_records(root)[0]
            record=dict(found.record,status='firing',native_delivery={'state':'uncertain'})
            replace_record(root,found,record)
            prompt=f"WAKE_TRIGGER_ID={record['id']}\nWAKE_TRIGGER_ROOT={root.resolve()}\nExecute the task"
            def native(endpoint,codex,method,params,timeout):
                if method=='thread/queue/list':return {'data':[]}
                if method=='thread/read':return {'thread':{'id':record['target']['thread_id']}}
                return {'data':[
                    {'id':'turn-'+suffix,'status':'completed','itemsView':'full','items':[{'type':'userMessage',
                     'id':'message-'+suffix,'clientId':'same-client',
                     'content':[{'type':'text','text':prompt}]}]} for suffix in ('one','two')],'nextCursor':None}
            with patch('codex_wake.native_delivery.native_request',side_effect=native), patch(
                    'codex_wake.native_delivery.subprocess.run') as effect:
                run(['--wake-root',str(root),'native','reconcile',record['id']])
            effect.assert_not_called()
            self.assertEqual(all_records(root)[0].record['native_delivery']['state'],'uncertain')
