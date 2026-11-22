"""Bounded native delivery at the public runtime adapter seam."""
import unittest

from codex_wake.codex_runtime import CodexRuntimeAdapter
from codex_wake.runtime_delivery import RuntimeCapability, RuntimeSubmissionEnvelope


class BoundedNativeDeliveryTests(unittest.TestCase):
    def test_busy_queue_observation_requires_host_qualification(self):
        from codex_wake.bounded_native import BoundedNativeAdapter
        from codex_wake.runtime_delivery import RuntimeCapability
        def forbidden(*args):
            self.fail('observation submitted input')
        for qualified in (False, True):
            with self.subTest(qualified=qualified):
                bounded = BoundedNativeAdapter(request=forbidden)
                if qualified:
                    bounded = BoundedNativeAdapter(request=forbidden,
                        qualification=lambda recipient:RuntimeCapability('supported', 'host_qualified_bounded_native'))
                adapter = CodexRuntimeAdapter(read_thread=lambda target:dict(id=target['thread_id'], status=dict(type='active')),
                    request=forbidden, run=forbidden, project_failure=forbidden, bounded_adapter=bounded)
                recipient = adapter.resolve(dict(transport='native', thread_id='01a1227e-a041-7b72-9c36-18349e7dd22c',
                    endpoint='unix://', codex_cmd='/codex'))
                observed = adapter.observe(recipient)
                self.assertEqual(observed.state, 'busy')
                self.assertEqual(observed.capabilities['busy_queue'].state, 'supported' if qualified else 'not_qualified')

    def test_host_refusal_is_pre_io_but_lost_reply_remains_uncertain(self):
        from codex_wake.bounded_native import BoundedNativeAdapter
        from codex_wake.bounded_native_qualification import BoundedNativePreIORefusal
        from codex_wake.runtime_delivery import RuntimeRecipient
        recipient = RuntimeRecipient('codex', 'thread', dict(endpoint='unix://', codex_cmd='/codex'))
        envelope = RuntimeSubmissionEnvelope('4d18e29e-9c05-45e7-a387-e50459dd3496', 1791504600000000)
        for error, expected in (
            (BoundedNativePreIORefusal('revoked'), ('not_sent', True)),
            (TimeoutError('reply lost'), ('uncertain', False)),
        ):
            with self.subTest(error=type(error).__name__):
                def request(*args):
                    raise error
                outcome = BoundedNativeAdapter(request=request).submit_bounded(recipient, 'wake', envelope)
                self.assertEqual((outcome.state, outcome.pre_io), expected)

    def test_unqualified_backend_refuses_before_submission_io(self):
        def forbidden(*args, **kwargs):
            self.fail('unqualified native backend performed submission I/O')
        adapter = CodexRuntimeAdapter(read_thread=forbidden, request=forbidden,
            run=forbidden, project_failure=forbidden)
        recipient = adapter.resolve(dict(transport='native', thread_id='01a1227e-a041-7b72-9c36-18349e7dd22c',
            endpoint='unix://', codex_cmd='/codex'))
        outcome = adapter.submit_bounded(recipient, 'wake', RuntimeSubmissionEnvelope(
            '4d18e29e-9c05-45e7-a387-e50459dd3496', 1791504600000000))
        self.assertEqual((outcome.state, outcome.pre_io, outcome.reason),
            ('not_sent', True, 'bounded_native_backend_not_qualified'))

    def test_native_pending_is_not_observed_delivery(self):
        from codex_wake.bounded_native import BoundedNativeAdapter
        envelope = RuntimeSubmissionEnvelope('4d18e29e-9c05-45e7-a387-e50459dd3496', 1791504600000000)
        requests = []
        def request(endpoint, command, method, params, timeout):
            requests.append((method, params))
            inspection = dict(state='pending', queuedSubmission=dict(id='4d18e29e-9c05-45e7-a387-e50459dd3497',
                clientUserMessageId=envelope.client_user_message_id,
                expiresAtUnixMicros=1791504600000000,
                input=[dict(type='text', text='wake', text_elements=[])]), turnId=None, clockEvidence=None)
            return dict(queuedSubmission=inspection['queuedSubmission']) if method.endswith('/add') else dict(inspection=inspection)
        adapter = BoundedNativeAdapter(request=request)
        from codex_wake.runtime_delivery import RuntimeRecipient
        recipient = RuntimeRecipient('codex', 'thread', dict(endpoint='unix://', codex_cmd='/codex'))
        outcome = adapter.submit_bounded(recipient, 'wake', envelope)
        observed = adapter.reconcile_bounded(recipient, 'wake', envelope)
        self.assertEqual((outcome.state, observed.evidence, observed.reason),
            ('accepted', None, 'bounded_native_pending'))
        self.assertEqual(requests[0], ('thread/queue/bounded/add', dict(threadId='thread',
            input=[dict(type='text', text='wake', text_elements=[])],
            clientUserMessageId=envelope.client_user_message_id, expiresAtUnixMicros=1791504600000000)))
        self.assertEqual(requests[1], ('thread/queue/bounded/read', dict(threadId='thread',
            clientUserMessageId=envelope.client_user_message_id)))

    def test_public_cancel_retires_exact_pending_bounded_submission(self):
        self.scenario_public_cancel()

    def test_lost_cancel_reply_holds_until_exact_tombstone_reconciles(self):
        self.scenario_public_cancel(lose_reply=True)

    def scenario_public_cancel(self, lose_reply=False):
        from datetime import UTC, datetime
        from pathlib import Path
        from copy import deepcopy
        import contextlib
        import io
        import json
        import tempfile
        from unittest.mock import patch
        from codex_wake.bounded_native import BoundedNativeAdapter
        from codex_wake.cli import main
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import all_records, build_record, write_record
        calls = []
        row = None
        deleted = False
        def request(endpoint, command, method, params, timeout):
            nonlocal row, deleted
            calls.append((method, deepcopy(params)))
            if method.endswith('/add'):
                row = dict(id='4d18e29e-9c05-45e7-a387-e50459dd3497',
                    input=params['input'], clientUserMessageId=params['clientUserMessageId'],
                    expiresAtUnixMicros=params['expiresAtUnixMicros'])
                return dict(queuedSubmission=row)
            if method.endswith('/delete'):
                self.assertEqual(params, dict(threadId=target['thread_id'], queuedSubmissionId=row['id']))
                deleted = True
                if lose_reply:raise TimeoutError('synthetic lost delete reply')
                return dict(deleted=True, inspection=dict(state='canceled', queuedSubmission=row))
            return dict(inspection=dict(state='canceled' if deleted else 'pending', queuedSubmission=row))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = dict(transport='native', thread_id='01a1227e-a041-7b72-9c36-18349e7dd22c',
                endpoint='unix://', codex_cmd='/codex', expires_at='2026-10-09T00:10:00Z')
            record = build_record(predicate=dict(type='not_before', due_at='2026-10-09T00:00:00Z'),
                prompt='wake', cwd=root, target=target, now=datetime(2026, 10, 9, tzinfo=UTC))
            record['status'] = 'firing'; write_record(root, record)
            adapter = CodexRuntimeAdapter(read_thread=lambda unused:dict(id=target['thread_id'], status=dict(type='idle')),
                request=request, run=lambda *a, **k:self.fail('unbounded submission'), project_failure=lambda *a:None,
                bounded_adapter=BoundedNativeAdapter(request=request,
                    qualification=lambda recipient: RuntimeCapability('supported', 'host_qualified_bounded_native')))
            dispatch_firing_record(root, all_records(root)[0], now=datetime(2026,10,9,tzinfo=UTC), runtime_adapter=adapter)
            pending = all_records(root)[0]
            before_bytes = pending.path.read_bytes()
            before = deepcopy(pending.record['native_delivery'])
            denied = io.StringIO()
            with patch('codex_wake.native_delivery._codex_adapter', return_value=adapter), contextlib.redirect_stdout(denied):
                denied_code = main(['--wake-root', str(root), 'cancel', record['id'],
                    '--caller-wake-subject', '01a1227e-a041-7b72-9c36-18349e7dd22d', '--json'])
            self.assertEqual(denied_code, 5)
            self.assertIn('outside verified caller scope', denied.getvalue())
            self.assertEqual(len(calls), 1)
            self.assertEqual(pending.path.read_bytes(), before_bytes)
            if lose_reply:
                uncertain = io.StringIO()
                with patch('codex_wake.native_delivery._codex_adapter', return_value=adapter), contextlib.redirect_stdout(uncertain):
                    uncertain_code = main(['--wake-root', str(root), 'cancel', record['id'], '--json'])
                self.assertEqual(uncertain_code, 5)
                self.assertIn('TimeoutError', uncertain.getvalue())
                self.assertEqual(pending.path.read_bytes(), before_bytes)
            output = io.StringIO()
            with patch('codex_wake.native_delivery._codex_adapter', return_value=adapter), contextlib.redirect_stdout(output):
                code = main(['--wake-root', str(root), 'cancel', record['id'], '--json'])
            result = json.loads(output.getvalue())['roots'][0]['results'][0]
            self.assertEqual((code, result['state']), (0, 'cancelled'))
            saved = all_records(root)[0].record
            self.assertEqual(saved['status'], 'cancelled')
            self.assertEqual(saved['native_delivery']['submission_id'], before['submission_id'])
            self.assertEqual(saved['native_delivery']['expires_at_unix_micros'], before['expires_at_unix_micros'])
            self.assertEqual(saved['native_delivery']['reconciliation']['reason'], 'bounded_native_canceled')
            self.assertEqual([method for method, _ in calls],
                ['thread/queue/bounded/add', 'thread/queue/bounded/read', 'thread/queue/bounded/delete']
                + (['thread/queue/bounded/read'] if lose_reply else []))

    def test_bounded_cancel_never_claims_to_undo_admitted_or_uncertain_work(self):
        from copy import deepcopy
        from codex_wake.bounded_native import BoundedNativeAdapter
        from codex_wake.runtime_delivery import RuntimeRecipient
        envelope = RuntimeSubmissionEnvelope('4d18e29e-9c05-45e7-a387-e50459dd3496', 1791504600000000)
        row = dict(id='4d18e29e-9c05-45e7-a387-e50459dd3497',
            input=[dict(type='text', text='wake', text_elements=[])],
            clientUserMessageId=envelope.client_user_message_id, expiresAtUnixMicros=envelope.expires_at_unix_micros)
        recipient = RuntimeRecipient('codex', 'thread', dict(endpoint='unix://', codex_cmd='/codex'))
        admission = dict(state='admitted', queuedSubmission=row, turnId='turn-owned',
            clockEvidence=dict(lower=1, upper=2, authority=dict(contract_version=1, state='qualified',
                lower=1, upper=2, counter=dict(epoch='4d18e29e-9c05-45e7-a387-e50459dd3498',
                    counter=1, frequency=10000000, rate_ppm=5000))))
        for state in ('admitted', 'notFound', 'ambiguous', 'expired', 'canceled'):
            with self.subTest(state=state):
                calls = []
                def request(endpoint, command, method, params, timeout):
                    calls.append(method)
                    return dict(inspection=admission if state == 'admitted' else dict(state=state, queuedSubmission=row))
                observed = BoundedNativeAdapter(request=request).cancel_bounded(recipient, 'wake', envelope, row['id'])
                self.assertEqual(observed.reason, 'bounded_native_' + state)
                self.assertIsNone(observed.evidence)
                self.assertEqual(calls, ['thread/queue/bounded/read'])
        for defect in ('queue_identity', 'deadline', 'input', 'delete_timeout', 'delete_malformed'):
            with self.subTest(defect=defect):
                calls = []
                def request(endpoint, command, method, params, timeout):
                    calls.append(method)
                    changed = deepcopy(row)
                    if method.endswith('/read'):
                        if defect == 'queue_identity':changed['id']='4d18e29e-9c05-45e7-a387-e50459dd3499'
                        if defect == 'deadline':changed['expiresAtUnixMicros']+=1
                        if defect == 'input':changed['input'][0]['text']='another prompt'
                        return dict(inspection=dict(state='pending', queuedSubmission=changed))
                    if defect == 'delete_timeout':raise TimeoutError('synthetic lost delete reply')
                    return dict(inspection=dict(state='canceled', queuedSubmission=None))
                with self.assertRaises((ValueError, TimeoutError)):
                    BoundedNativeAdapter(request=request).cancel_bounded(recipient, 'wake', envelope, row['id'])
                self.assertEqual(len(calls), 2 if defect.startswith('delete_') else 1)

    def test_original_expiry_preserves_microseconds_and_earlier_stop(self):
        from codex_wake.runtime_delivery import original_submission_expiry
        record = dict(scheduling_intent=dict(schedule=dict(kind='at', due_at='2026-10-09T00:00:00Z'),
            ttl_seconds=600.75, stop_at='2026-10-09T00:10:00.125Z'))
        self.assertEqual(original_submission_expiry(record), 1791504600125000)

    def test_explicit_busy_queue_never_downgrades_to_idle_submission(self):
        from datetime import UTC, datetime
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from codex_wake.daemon import poll_once
        from codex_wake.records import all_records, build_record, write_record
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = dict(transport='native', thread_id='01a1227e-a041-7b72-9c36-18349e7dd22c', endpoint='unix://',
                codex_cmd='/codex', busy_policy='queue', expires_at='2026-10-09T00:10:00Z')
            write_record(root, build_record(predicate=dict(type='not_before', due_at='2026-10-09T00:00:00Z'),
                prompt='wake', cwd=root, target=target, now=datetime(2026, 10, 9, tzinfo=UTC)))
            with patch('codex_wake.native_delivery.read_native_thread', return_value=dict(id='01a1227e-a041-7b72-9c36-18349e7dd22c', status=dict(type='idle'))), patch(
                'codex_wake.native_delivery.subprocess.run', side_effect=AssertionError('unbounded submission')):
                poll_once(root, datetime(2026, 10, 9, tzinfo=UTC))
            saved = all_records(root)[0].record
            self.assertEqual((saved['status'], saved['policy_outcome']['reason']),
                ('pending', 'bounded_native_backend_not_qualified'))
            self.assertNotIn('native_delivery', saved)

    def test_bounded_pending_keeps_persisted_identity_until_native_terminal(self):
        from datetime import UTC, datetime
        from pathlib import Path
        import tempfile
        from codex_wake.injector import dispatch_firing_record
        from codex_wake.records import all_records, build_record, write_record
        from codex_wake.runtime_delivery import RuntimeRecipient, RuntimeObservation, RuntimeSubmission, RuntimeReconciliation
        envelopes = []
        class Runtime:
            def resolve(self, target):
                return RuntimeRecipient('codex', target['thread_id'], target)
            def observe(self, recipient):
                return RuntimeObservation('ready', 'idle', {})
            def submit_bounded(self, recipient, prompt, envelope):
                envelopes.append(envelope)
                return RuntimeSubmission('accepted', receipt_id='4d18e29e-9c05-45e7-a387-e50459dd3497', evidence_kind='native_queue_acceptance')
            def reconcile_bounded(self, recipient, prompt, envelope):
                envelopes.append(envelope)
                return RuntimeReconciliation(None, 'bounded_native_pending' if len(envelopes) == 2 else 'bounded_native_expired')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = dict(transport='native', thread_id='01a1227e-a041-7b72-9c36-18349e7dd22c', endpoint='unix://', codex_cmd='/codex', expires_at='2026-10-09T00:10:00Z')
            record = build_record(predicate=dict(type='not_before', due_at='2026-10-09T00:00:00Z'), prompt='wake', cwd=root, target=target, now=datetime(2026, 10, 9, tzinfo=UTC))
            record['status'] = 'firing'
            write_record(root, record)
            adapter = Runtime()
            for instant in (0, 10, 20):
                dispatch_firing_record(root, all_records(root)[0], now=datetime(2026, 10, 9, 0, 0, instant, tzinfo=UTC), runtime_adapter=adapter)
                if instant < 20:
                    self.assertEqual(all_records(root)[0].record['status'], 'firing')
                if instant == 0:
                    # Cancellation must not claim success while native pending
                    # work remains executable. The default production backend is
                    # unqualified, so the public command explicitly holds.
                    import contextlib
                    import io
                    import json
                    from codex_wake.cli import main
                    pending = all_records(root)[0]
                    before = pending.path.read_bytes()
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = main(['--wake-root', str(root), 'cancel', pending.record['id'], '--json'])
                    result = json.loads(output.getvalue())['roots'][0]['results'][0]
                    self.assertEqual((code, result['state']), (5, 'held'))
                    self.assertIn('reconcile original effect before cancellation', result['reason'])
                    self.assertEqual(pending.path.read_bytes(), before)

            saved = all_records(root)[0].record
            self.assertEqual((saved['status'], saved['attempts']), ('expired', 1))
            self.assertEqual(envelopes, [envelopes[0]] * 3)
            self.assertEqual(envelopes[0].client_user_message_id, saved['native_delivery']['submission_id'])
            self.assertEqual(envelopes[0].expires_at_unix_micros, 1791504600000000)
            from unittest.mock import patch
            from codex_wake.wake_mode_runtime import registration_harness_readiness
            with patch('codex_wake.native_protocol.native_request', return_value=dict(thread=dict(id=target['thread_id'], status=dict(type='idle')))):
                readiness = registration_harness_readiness(root, dict(id='next-occurrence', target=target))
            self.assertEqual(readiness['state'], 'ready')


    def test_native_admission_requires_original_payload_and_qualified_clock(self):
        from copy import deepcopy
        from codex_wake.bounded_native import BoundedNativeAdapter
        from codex_wake.runtime_delivery import RuntimeRecipient
        envelope = RuntimeSubmissionEnvelope('4d18e29e-9c05-45e7-a387-e50459dd3496', 1791504600000000)
        authority = dict(contract_version=1, state='qualified', lower=1791504000, upper=1791504001,
            counter=dict(epoch='4d18e29e-9c05-45e7-a387-e50459dd3498', counter=123, frequency=1000, rate_ppm=10))
        response = dict(state='admitted', queuedSubmission=dict(id='4d18e29e-9c05-45e7-a387-e50459dd3497',
            clientUserMessageId=envelope.client_user_message_id, expiresAtUnixMicros=1791504600000000,
            input=[dict(type='text', text='wake', text_elements=[])]), turnId='turn-exact',
            clockEvidence=dict(lower=1791504000, upper=1791504001, authority=authority))
        recipient = RuntimeRecipient('codex', 'thread', dict(endpoint='unix://', codex_cmd='/codex'))
        for change in ('expiry', 'input', 'clock', 'late'):
            with self.subTest(change=change):
                malformed = deepcopy(response)
                if change == 'expiry': malformed['queuedSubmission']['expiresAtUnixMicros'] += 1
                if change == 'input': malformed['queuedSubmission']['input'][0]['text'] = 'changed'
                if change == 'clock': malformed['clockEvidence'] = None
                if change == 'late': malformed['clockEvidence']['upper'] = 1791504600
                adapter = BoundedNativeAdapter(request=lambda *args: dict(inspection=malformed))
                with self.assertRaises(ValueError):
                    adapter.reconcile_bounded(recipient, 'wake', envelope)
        # Existing admitted v1 records remain reconcilable; new admissions label
        # the explicitly accepted service measurement basis.
        for version in (1, 2):
            response['clockEvidence']['authority'] = dict(authority)
            if version == 2:
                response['clockEvidence']['authority'].update(contract_version=2,
                    basis='service_measurement', receipt_time_bound=False,
                    counter_source=dict(kind='stable_time_service_measurement'))
            adapter = BoundedNativeAdapter(request=lambda *args: dict(inspection=response))
            observed = adapter.reconcile_bounded(recipient, 'wake', envelope)
            self.assertEqual((observed.evidence['source'], observed.evidence['execution'], observed.evidence['turn_id']),
                ('bounded_native_admission', 'not_observed', 'turn-exact'))
        for defect in ('missing_basis', 'receipt_claim', 'private_bridge'):
            changed = deepcopy(response)
            evidence = changed['clockEvidence']['authority']
            if defect == 'missing_basis': evidence.pop('basis')
            if defect == 'receipt_claim': evidence['receipt_time_bound'] = True
            if defect == 'private_bridge': evidence['counter_source']['kind'] = 'windows_qpc_private_bridge'
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                BoundedNativeAdapter(request=lambda *args: dict(inspection=changed)).reconcile_bounded(recipient, 'wake', envelope)

    def test_admitted_wire_rounding_preserves_conservative_expiry(self):
        from copy import deepcopy
        from codex_wake.bounded_native import BoundedNativeAdapter
        from codex_wake.runtime_delivery import RuntimeRecipient
        envelope = RuntimeSubmissionEnvelope('4d18e29e-9c05-45e7-a387-e50459dd3496', 1794885320000000)
        recipient = RuntimeRecipient('codex', 'thread', dict(endpoint='unix://', codex_cmd='/codex'))
        # Exact numeric pair observed in a real native RPC response after persistence.
        inspection = dict(state='admitted', queuedSubmission=dict(id='4d18e29e-9c05-45e7-a387-e50459dd3497',
            clientUserMessageId=envelope.client_user_message_id, expiresAtUnixMicros=envelope.expires_at_unix_micros,
            input=[dict(type='text', text='wake', text_elements=[])]), turnId='turn-exact',
            clockEvidence=dict(lower=1794885199.5396998, upper=1794885200.049925,
                authority=dict(contract_version=1, state='qualified', lower=1794885199.5396998,
                    upper=1794885200.0499253, counter=dict(epoch='4d18e29e-9c05-45e7-a387-e50459dd3498',
                        counter=123, frequency=10000000, rate_ppm=5000))))
        calls = []
        def request(*args):
            calls.append(args[2])
            return dict(inspection=inspection)
        outcome = BoundedNativeAdapter(request=request).cancel_bounded(recipient, 'wake', envelope)
        self.assertEqual(outcome.reason, 'bounded_native_admitted')
        self.assertEqual(calls, ['thread/queue/bounded/read'])
        for defect in ('more_than_wire_rounding', 'authority_reaches_expiry'):
            with self.subTest(defect=defect):
                changed = deepcopy(inspection)
                clock = changed['clockEvidence']
                selected = envelope
                if defect == 'more_than_wire_rounding':
                    clock['authority']['upper'] = 1794885200.0499256
                else:
                    selected = RuntimeSubmissionEnvelope(envelope.client_user_message_id, 1794885200000000)
                    changed['queuedSubmission']['expiresAtUnixMicros'] = selected.expires_at_unix_micros
                    clock['upper'] = 1794885199.9999998
                    clock['authority']['upper'] = 1794885200.0
                with self.assertRaises(ValueError):
                    BoundedNativeAdapter(request=lambda *args:dict(inspection=changed)).cancel_bounded(recipient, 'wake', selected)
