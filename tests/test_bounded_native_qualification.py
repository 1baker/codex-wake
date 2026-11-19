"""Host approval gates the real Unix transport before bounded input."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import unix_serve

from codex_wake.bounded_native_qualification import (
    BoundedNativePreIORefusal, QualifiedBoundedNativeRequest,
)
from codex_wake.runtime_delivery import RuntimeRecipient, RuntimeSubmissionEnvelope


_CLIENT = '4d18e29e-9c05-45e7-a387-e50459dd3496'
_QUEUE = '4d18e29e-9c05-45e7-a387-e50459dd3497'
_THREAD = '01a1227e-a041-7b72-9c36-18349e7dd22c'
_EXPIRY = 1791504600000000
_CAPABILITIES = dict(version=1, clockSource='stable_time', clockConfigured=True,
    expiryAtAdmission=True, pendingIsolatedFromLegacy=True)


def _pin_report(root, report):
    path = root / 'report.json'
    path.write_text(json.dumps(report))
    path.chmod(0o600)
    policy = root / 'policy.json'
    policy.write_text(json.dumps(dict(schema_version=1, qualification_report=str(path),
        qualification_sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
    policy.chmod(0o600)


@contextmanager
def _peer(*, capabilities=None, after_capabilities=None, lose_add_reply=False):
    # Minimal real Unix protocol peer: it does not claim native qualification.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        digest = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
        _pin_report(root, dict(native_source_commit='a' * 40,
            package=dict(files={'bin/codex': digest}),
            bounded_native_admission=dict(contract_version=1, state='qualified',
                checks={name: True for name in ('expiry', 'unknown', 'cancellation',
                    'restart', 'history_isolation', 'final_send', 'rollback', 'ownership', 'reconnect')})))
        calls = []
        def handler(ws):
            try:
                for raw in ws:
                    request = json.loads(raw)
                    calls.append((id(ws), request))
                    method = request['method']
                    if 'id' not in request:
                        continue
                    if method.endswith('/capabilities'):
                        if after_capabilities:
                            after_capabilities(root)
                        result = _CAPABILITIES if capabilities is None else capabilities
                    elif method.endswith('/add'):
                        if lose_add_reply:
                            ws.close()
                            return
                        params = request['params']
                        result = dict(queuedSubmission=dict(id=_QUEUE,
                            clientUserMessageId=params['clientUserMessageId'],
                            expiresAtUnixMicros=params['expiresAtUnixMicros'], input=params['input']))
                    else:
                        result = {}
                    ws.send(json.dumps(dict(id=request['id'], result=result)))
            except ConnectionClosed:
                return
        with unix_serve(handler, str(root / 'native.sock')) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with patch.dict(os.environ, {'CODEX_WAKE_BOUNDED_NATIVE_POLICY': str(root / 'policy.json')}):
                    yield root, calls
            finally:
                server.shutdown()
                thread.join(3)


def _request(root):
    return QualifiedBoundedNativeRequest()('unix://' + str(root / 'native.sock'),
        sys.executable, 'thread/queue/bounded/add', dict(threadId=_THREAD,
            clientUserMessageId=_CLIENT, expiresAtUnixMicros=_EXPIRY, input=[]), 2)


class BoundedNativeQualificationTests(unittest.TestCase):
    def setUp(self):
        clock = dict(reason='authenticated_utc', valid_for_ns=1000000000,
            utc=dict(status='network', lower=1700000000, upper=1700000001),
            counter=dict(epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                counter=1000, frequency=1000, rate_ppm=5000))
        for target, value in (('configuration', '/explicit-test-clock'), ('snapshot', clock)):
            context = patch('codex_wake.native_clock.' + target, return_value=value)
            context.start()
            self.addCleanup(context.stop)

    def test_queue_inspection_and_cancellation_survive_clock_client_outage(self):
        from codex_wake.measurements import TimeUnavailable
        with _peer() as (root, calls), patch('codex_wake.measurements.snapshot',
                side_effect=TimeUnavailable('clock client unavailable')):
            request = QualifiedBoundedNativeRequest()
            for operation in ('read', 'delete', 'capabilities'):
                with self.subTest(operation=operation):
                    request('unix://' + str(root / 'native.sock'), sys.executable,
                        'thread/queue/bounded/' + operation,
                        dict(threadId=_THREAD, id=_QUEUE), 2)
            methods = [item[1]['method'] for item in calls]
            self.assertIn('thread/queue/bounded/read', methods)
            self.assertIn('thread/queue/bounded/delete', methods)
            self.assertNotIn('thread/queue/bounded/add', methods)

    def test_default_factory_preserves_envelope_and_negotiates_on_submission_connection(self):
        from codex_wake.native_delivery import _codex_adapter
        with _peer() as (root, calls):
            adapter = _codex_adapter()
            recipient = adapter.resolve(dict(transport='native', thread_id=_THREAD,
                endpoint='unix://' + str(root / 'native.sock'), codex_cmd=sys.executable))
            result = adapter.submit_bounded(recipient, 'wake', RuntimeSubmissionEnvelope(_CLIENT, _EXPIRY))
            self.assertEqual((result.state, result.receipt_id), ('accepted', _QUEUE))
            self.assertEqual([item[1]['method'] for item in calls], ['initialize', 'initialized',
                'thread/queue/bounded/capabilities', 'thread/queue/bounded/add'])
            self.assertEqual(len({item[0] for item in calls}), 1)
            self.assertEqual(calls[2][1]['params'], {'threadId': _THREAD})
            self.assertEqual(calls[3][1]['params'], dict(threadId=_THREAD,
                clientUserMessageId=_CLIENT, expiresAtUnixMicros=_EXPIRY,
                input=[dict(type='text', text='wake', text_elements=[])]))

    def test_absent_or_invalid_host_approval_never_connects(self):
        for invalid in ('missing', 'wide_mode', 'symlink', 'changed_report', 'unqualified'):
            with self.subTest(invalid=invalid), _peer() as (root, calls):
                policy = root / 'policy.json'
                if invalid == 'missing':
                    os.environ.pop('CODEX_WAKE_BOUNDED_NATIVE_POLICY')
                elif invalid == 'wide_mode':
                    policy.chmod(0o644)
                elif invalid == 'symlink':
                    policy.rename(root / 'real-policy.json')
                    policy.symlink_to(root / 'real-policy.json')
                elif invalid == 'changed_report':
                    with (root / 'report.json').open('a') as stream:
                        stream.write(' ')
                else:
                    report = json.loads((root / 'report.json').read_text())
                    report['bounded_native_admission']['checks']['final_send'] = False
                    _pin_report(root, report)
                with self.assertRaises(BoundedNativePreIORefusal):
                    _request(root)
                self.assertEqual(calls, [])

    def test_other_actual_executable_is_refused_before_capability_or_input(self):
        with _peer() as (root, calls):
            report = json.loads((root / 'report.json').read_text())
            report['package']['files']['bin/codex'] = '0' * 64
            _pin_report(root, report)
            with self.assertRaises(BoundedNativePreIORefusal):
                _request(root)
            self.assertEqual([item[1]['method'] for item in calls], ['initialize', 'initialized'])

    def test_incompatible_capabilities_refuse_input(self):
        for capabilities in (dict(_CAPABILITIES, version=2), dict(_CAPABILITIES, clockConfigured=False)):
            with self.subTest(capabilities=capabilities), _peer(capabilities=capabilities) as (root, calls):
                with self.assertRaises(BoundedNativePreIORefusal):
                    _request(root)
                self.assertNotIn('thread/queue/bounded/add', [item[1]['method'] for item in calls])

    def test_revocation_during_negotiation_refuses_input(self):
        with _peer(after_capabilities=lambda root: (root / 'policy.json').unlink()) as (root, calls):
            with self.assertRaises(BoundedNativePreIORefusal):
                _request(root)
            self.assertNotIn('thread/queue/bounded/add', [item[1]['method'] for item in calls])

    def test_lost_input_reply_is_not_misclassified_as_pre_io(self):
        with _peer(lose_add_reply=True) as (root, calls):
            with self.assertRaises(ConnectionClosed):
                _request(root)
            self.assertEqual(calls[-1][1]['method'], 'thread/queue/bounded/add')

    def test_capability_probe_uses_one_scoped_metadata_request(self):
        with _peer() as (root, calls):
            recipient = RuntimeRecipient('codex', _THREAD, dict(endpoint='unix://' + str(root / 'native.sock'),
                codex_cmd=sys.executable))
            result = QualifiedBoundedNativeRequest().capability(recipient)
            self.assertEqual(result.state, 'supported')
            self.assertEqual([item[1]['method'] for item in calls], ['initialize', 'initialized',
                'thread/queue/bounded/capabilities'])
