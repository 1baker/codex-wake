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
        clock = patch('codex_wake.native_clock.snapshot', return_value=dict(utc=dict(status='network', sources=['a','b'], lower=1791504000, upper=1791504000.2), counter=None))
        clock.start()
        self.addCleanup(clock.stop)
        from test_measurements import observation
        qualified = observation(1000)
        qualified['utc'] = dict(status='network', lower=1791504000, upper=1791504000.2)
        stable = patch('codex_wake.measurements.snapshot', return_value=qualified)
        stable.start()
        self.addCleanup(stable.stop)

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
                              now=datetime(2026, 10, 9, tzinfo=UTC),
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

            def submit_bounded(self, recipient, prompt, envelope):
                delivered.append((recipient.session_id, prompt, envelope))
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
            self.assertEqual(result.status, 'skipped')
            self.assertEqual(saved['status'], 'firing')
            self.assertEqual(delivered[0][2].client_user_message_id, saved['native_delivery']['submission_id'])
            self.assertEqual(delivered[0][2].expires_at_unix_micros, 1791504600000000)
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

            def submit_bounded(self, recipient, prompt, envelope):
                deliveries.append(prompt)
                raise OSError('accepted but response lost: PRIVATE_TRANSPORT_DETAIL')

            def reconcile_bounded(self, recipient, prompt, envelope):
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
            adapter.submit_bounded.return_value = RuntimeSubmission(
                'accepted', '01a12280-80ef-7772-a00a-c68bd32ecbba', 'terminal_observation',
            )
            adapter.reconcile_bounded.return_value = RuntimeReconciliation(
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
            adapter.submit_bounded.assert_called_once()

    def test_operator_unbounded_queue_retains_safe_diagnostics(self):
        """Operator queue compatibility remains separate from durable Wake dispatch."""
        import json
        import subprocess
        from codex_wake.codex_runtime import CodexRuntimeAdapter, submission_failure
        outcomes = [
            (subprocess.TimeoutExpired(['queue', 'PRIVATE_ARG'], 30,
                output=b'PRIVATE_OUTPUT', stderr=b'PRIVATE_SECRET' * 1000), 'queue_timeout'),
            (subprocess.CompletedProcess(['PRIVATE_ARG'], 0, 'PRIVATE_STDOUT', 'PRIVATE_UNKNOWN_ERROR'), 'queue_acceptance_unconfirmed'),
            (subprocess.CompletedProcess(['PRIVATE_ARG'], 7, 'PRIVATE_STDOUT', 'Error: thread not found; Bearer PRIVATE_TOKEN'), 'queue_exit_nonzero'),
            (PermissionError('PRIVATE_PATH'), 'queue_os_error'),
        ]
        from unittest.mock import Mock
        for outcome, reason in outcomes:
            with self.subTest(reason=reason):
                runner = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
                adapter = CodexRuntimeAdapter(read_thread=Mock(), request=Mock(), run=runner, project_failure=submission_failure)
                recipient = adapter.resolve(dict(transport='native', thread_id='thread', endpoint='unix://', codex_cmd='/codex'))
                result = adapter.submit(recipient, 'operator input')
                self.assertEqual((result.state, result.reason), ('uncertain', reason))
                self.assertLess(len(json.dumps(result.failure)), 1024)
                self.assertNotIn('PRIVATE_', json.dumps(result.failure))
                if reason == 'queue_timeout': self.assertTrue(result.failure['stderr']['truncated'])
                if reason == 'queue_exit_nonzero': self.assertEqual(result.failure['stderr']['hints'], ['thread_not_found'])
                runner.assert_called_once()

    def test_registered_due_wake_holds_without_qualified_bounded_backend(self):
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
            self.assertEqual(result.submitted, 0)
            record = all_records(root)[0].record
            self.assertEqual(record['status'], 'pending')
            self.assertNotIn('native_delivery', record)
            self.assertEqual(record['policy_outcome']['reason'], 'bounded_native_backend_not_qualified')

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

    def test_explicit_reconcile_clears_accepted_peer_hold_without_rewriting_history(self):
        from codex_wake.records import replace_record
        from codex_wake.wake_mode_runtime import registration_harness_readiness
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-submit')
            found = all_records(root)[0]
            record = dict(found.record, status='submitted', native_delivery={
                'state': 'accepted', 'execution': 'not_observed'})
            replace_record(root, found, record)
            original = all_records(root)[0].path.read_bytes()
            prompt = f"WAKE_TRIGGER_ID={record['id']}\nWAKE_TRIGGER_ROOT={root.resolve()}\nExecute the task"
            reader = root / 'selected-reader'
            reader.write_text('#!/bin/sh\nexit 1\n')
            reader.chmod(0o700)
            observed_status = 'inProgress'
            observed_thread = record['target']['thread_id']
            def native(endpoint, codex, method, params, timeout):
                if method != 'thread/read' or params.get('includeTurns') is not False:
                    self.assertEqual(codex, str(reader))
                if method == 'thread/queue/list':
                    return {'data': [], 'nextCursor': None}
                if method == 'thread/read':
                    return {'thread': {'id': observed_thread, 'status': {'type': 'idle'}}}
                if method == 'thread/turns/list':
                    return {'data': [{'id': 'turn-exact', 'status': observed_status, 'itemsView': 'full',
                        'items': [{'type': 'userMessage', 'id': 'message-exact', 'clientId': 'client-exact',
                                   'content': [{'type': 'text', 'text': prompt}]}]}], 'nextCursor': None}
                raise AssertionError('unexpected native operation: ' + method)
            current = dict(id='new-wake', target=record['target'])
            with patch('codex_wake.native_protocol.native_request', side_effect=native), patch(
                    'codex_wake.native_delivery.native_request', side_effect=native):
                self.assertEqual(registration_harness_readiness(root, current)['state'], 'held')
                command = ['--wake-root', str(root), 'native', 'reconcile', '--read-codex-path', str(reader), record['id']]
                reader.chmod(0o777)
                self.assertEqual(run(command), 0)
                self.assertEqual(registration_harness_readiness(root, current)['state'], 'held')
                reader.chmod(0o700)
                self.assertEqual(run(command), 0)
                self.assertEqual(registration_harness_readiness(root, current)['state'], 'held')
                observed_status = 'completed'
                observed_thread = 'wrong-conversation'
                self.assertEqual(run(command), 0)
                observed_thread = record['target']['thread_id']
                self.assertEqual(registration_harness_readiness(root, current)['state'], 'held')
                self.assertEqual(run(command), 0)
                self.assertEqual(registration_harness_readiness(root, current)['state'], 'ready')
                with patch('codex_wake.native_delivery.native_request', side_effect=AssertionError('receipt must be reused')):
                    self.assertEqual(run(command), 0)
            self.assertEqual(all_records(root)[0].path.read_bytes(), original)

    def test_cached_completion_does_not_bypass_changed_submission_payload(self):
        import contextlib
        import io
        import json
        from codex_wake.records import replace_record
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.native_record(root, root / 'must-not-run')
            found = all_records(root)[0]
            record = dict(found.record, status='submitted', native_delivery={
                'state': 'accepted', 'prompt_sha256': '0' * 64,
                'evidence': dict(source='native_turn', execution='turn_completed',
                    turn_id='turn', user_message_id='message', client_message_id='client')})
            replace_record(root, found, record)
            original = all_records(root)[0].path.read_bytes()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run(['--wake-root', str(root), 'native', 'reconcile', record['id']]), 0)
            self.assertEqual(json.loads(output.getvalue())['terminal_reconciliation'],
                dict(state='unresolved', reason='native_submission_payload_changed'))
            self.assertEqual(all_records(root)[0].path.read_bytes(), original)

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
            self.assertEqual(result.submitted,0)
            self.assertEqual(all_records(root)[0].record['policy_outcome']['reason'], 'bounded_native_backend_not_qualified')
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
