from __future__ import annotations

import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from codex_wake.records import WakeError
from codex_wake.shared_app_server import SharedAppServerReader, SharedSourceError, locate_shared_endpoint


class FakeConnection:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []
        self.closed = False

    def send(self, text):
        self.sent.append(json.loads(text))

    def recv(self, timeout):
        return json.dumps(next(self.replies))

    def close(self):
        self.closed = True


def result(identifier, value):
    return {"id": identifier, "result": value}


class SharedReaderTests(unittest.TestCase):
    def setUp(self):
        clock = dict(reason='authenticated_utc', valid_for_ns=1000000000,
            utc=dict(status='network', lower=1700000000, upper=1700000001),
            counter=dict(epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                counter=1000, frequency=1000, rate_ppm=5000))
        for target, value in (('configuration', '/explicit-test-clock'), ('snapshot', clock)):
            context = patch('codex_wake.native_clock.' + target, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'daemon.sock'
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(self.path))
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.sock.close)

    def test_metadata_transport_does_not_require_time_authority(self):
        reader, connection = self.reader([result(1, {}), result(2, {'data': [], 'nextCursor': None})])
        with patch('codex_wake.native_clock.configuration', return_value=None):
            with reader:
                self.assertEqual(reader.loaded_threads(), [])
        self.assertTrue(connection.closed)
        self.assertEqual([item['method'] for item in connection.sent],
                         ['initialize', 'initialized', 'thread/loaded/list'])

    def reader(self, replies):
        connection = FakeConnection(replies)
        reader = SharedAppServerReader('unix://' + str(self.path),
                                       connector=lambda *a, **kw: connection)
        return reader, connection

    def test_pages_and_metadata_only_without_lifecycle_calls(self):
        reader, connection = self.reader([
            result(1, {}),
            {"method": "thread/status/changed", "params": {}},
            result(2, {"data": ['a'], "nextCursor": 'next'}),
            result(3, {"data": ['b'], "nextCursor": None}),
            result(4, {"thread": {"id": 'a', "name": 'wake', "turns": ['PRIVATE']}}),
            result(5, {"thread": {"id": 'b', "status": {"type": 'idle'}}}),
        ])
        with reader:
            threads = reader.loaded_threads()
        self.assertEqual([x['id'] for x in threads], ['a', 'b'])
        self.assertNotIn('turns', threads[0])
        self.assertEqual([x['method'] for x in connection.sent],
                         ['initialize', 'initialized', 'thread/loaded/list',
                          'thread/loaded/list', 'thread/read', 'thread/read'])
        self.assertTrue(all(x['params']['includeTurns'] is False
                            for x in connection.sent if x['method'] == 'thread/read'))
        self.assertTrue(connection.closed)

    def test_duplicate_pages_fail_closed(self):
        reader, connection = self.reader([
            result(1, {}), result(2, {"data": ['a'], "nextCursor": 'x'}),
            result(3, {"data": ['a'], "nextCursor": None}),
        ])
        with self.assertRaises(SharedSourceError):
            with reader:
                reader.loaded_threads()
        self.assertTrue(connection.closed)

    def test_mismatched_thread_identity_fail_closed(self):
        reader, connection = self.reader([result(1, {}), result(2, {"thread": {"id": 'wrong'}})])
        with self.assertRaises(SharedSourceError):
            with reader:
                reader.read_thread('intended')
        self.assertTrue(connection.closed)

    def test_failed_initialize_closes_connection(self):
        reader, connection = self.reader([{"id": 1, "error": {"message": 'PRIVATE'}}])
        with self.assertRaisesRegex(SharedSourceError, 'initialize'):
            with reader:
                self.fail('must not open')
        self.assertTrue(connection.closed)

    def test_population_bound_does_not_return_partial_inventory(self):
        reader, _ = self.reader([result(1, {}), result(2, {"data": ['a', 'b'], "nextCursor": None})])
        with self.assertRaises(SharedSourceError):
            with reader:
                reader.loaded_threads(maximum=1)

    def test_lifecycle_methods_rejected_before_send(self):
        reader, connection = self.reader([result(1, {})])
        with reader:
            for method in ['thread/resume', 'turn/start', 'thread/subscribe']:
                with self.assertRaises(WakeError):
                    reader.request(method, {})
        self.assertEqual(len(connection.sent), 2)

    def test_plain_file_and_symlink_rejected(self):
        plain = Path(self.tmp.name) / 'plain'
        plain.touch()
        link = Path(self.tmp.name) / 'link'
        link.symlink_to(self.path)
        for path in [plain, link]:
            with self.assertRaises(SharedSourceError):
                with SharedAppServerReader('unix://' + str(path)):
                    self.fail('must reject')

    def test_invalid_timeouts_and_endpoint(self):
        for timeout in [0, -1, float('inf'), float('nan'), 61, True, None, '1']:
            with self.assertRaises(WakeError):
                SharedAppServerReader('unix://' + str(self.path), timeout=timeout)
        for endpoint in ['stdio://', 'unix://', 'unix://relative']:
            with self.assertRaises(WakeError):
                SharedAppServerReader(endpoint)

    def test_supported_locator_resolves_owned_control_symlink(self):
        link = Path(self.tmp.name) / 'control.sock'
        link.symlink_to(self.path)
        response = SimpleNamespace(stdout=json.dumps(dict(status='running', socketPath=str(link))))
        with patch('codex_wake.shared_app_server.subprocess.run', return_value=response) as run:
            self.assertEqual(locate_shared_endpoint(), 'unix://' + str(self.path))
        self.assertEqual(run.call_args.args[0], ['codex', 'app-server', 'daemon', 'version'])

    def test_stopped_locator_does_not_start_daemon(self):
        response = SimpleNamespace(stdout=json.dumps(dict(status='stopped')))
        with patch('codex_wake.shared_app_server.subprocess.run', return_value=response) as run:
            with self.assertRaises(SharedSourceError):
                locate_shared_endpoint()
        self.assertEqual(run.call_count, 1)
