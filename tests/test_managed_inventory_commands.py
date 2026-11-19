"""Public command/observer integration uses runtime and process seams only."""
import argparse
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.a2a_bus import BusStore
from codex_wake.managed_inventory_commands import RuntimeObserver, execute, register_parser, run
from codex_wake.runtime_a2a import GrokMailboxRuntime
from test_managed_inventory import THREAD, native_context, observation


class Reader:
    def __init__(self, endpoint, **_):
        self.server_metadata = {'codexHome': '/fixture/codex'}
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read_thread(self, identifier):
        return {'id': identifier, 'cwd': '/fixture/repo', 'modelProvider': 'openai'}


class ManagedInventoryCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_native_observer_uses_exact_metadata_and_process_without_projecting_endpoints(self):
        snapshot = {'complete': True, 'sources': {'app_server': {'availability': 'available'}},
                    'sessions': [{'thread_id': THREAD, 'cwd': '/fixture/repo', 'attachments': [
                        {'pane_id': '%1', 'window_id': '@2', 'client_pid': 123,
                         'client_start_time_ticks': 42, 'socket': '/private/socket'}]}]}
        observer = RuntimeObserver(endpoint='unix:///fixture/server')
        with patch('codex_wake.shared_app_server.SharedAppServerReader', Reader), \
             patch('codex_wake.sessions.observe', return_value=snapshot), \
             patch('codex_wake.process.process_identity', return_value={'boot_id': 'boot', 'start_time_ticks': 42}):
            value = execute('enroll', {'conversation_id': THREAD}, self.root / 'wake',
                            native_context=native_context(), observer=observer)
        self.assertEqual(value['agent']['process']['start_ticks'], 42)
        self.assertNotIn('/private/socket', json.dumps(value))
        self.assertNotIn('/fixture/server', json.dumps(value))
        snapshot['sessions'][0]['attachments'][0]['client_start_time_ticks'] = 41
        with patch('codex_wake.shared_app_server.SharedAppServerReader', Reader), \
             patch('codex_wake.sessions.observe', return_value=snapshot), \
             patch('codex_wake.process.process_identity', return_value={'boot_id': 'boot', 'start_time_ticks': 42}):
            with self.assertRaisesRegex(Exception, 'ready verified binding'):
                execute('enroll', {'conversation_id': THREAD}, self.root / 'wake2',
                        native_context=native_context(), observer=observer)

    def test_saved_unloaded_recipient_is_observable_without_claiming_a_live_binding(self):
        class SavedReader(Reader):
            def read_thread(self, identifier):
                return dict(super().read_thread(identifier),name='saved-recipient',status={'type':'notLoaded'})
        snapshot={'complete':True,'sources':{'app_server':{'availability':'available'},
            'tmux':{'availability':'available'}},'sessions':[]}
        observer=RuntimeObserver(endpoint='unix:///fixture/server')
        with patch('codex_wake.shared_app_server.SharedAppServerReader',SavedReader),patch(
                'codex_wake.sessions.observe',return_value=snapshot):
            sample=observer({'conversation_id':THREAD})
            self.assertEqual(sample.conversation_id,THREAD)
            self.assertEqual(sample.state,'unavailable')
            self.assertEqual(sample.attachments,[])
            self.assertIsNone(sample.process)
            snapshot['complete']=False
            with self.assertRaises(Exception):observer({'conversation_id':THREAD})
            snapshot['complete']=True
            snapshot['sessions']=[dict(thread_id=None,name='saved-recipient',cwd='/fixture/repo',
                attachments=[dict(client_pid=123,client_start_time_ticks=42)])]
            with self.assertRaises(Exception):observer({'conversation_id':THREAD})

    def test_saved_recovery_holds_loaded_native_recipient_without_visible_attachment(self):
        from codex_wake.agent_resume import SavedRuntime
        from codex_wake.managed_inventory import InventoryError
        snapshot = {'complete': True, 'sources': {'app_server': {'availability': 'available'},
                    'tmux': {'availability': 'available'}}, 'sessions': [dict(
                    thread_id=THREAD, cwd='/fixture/repo', attachments=[])]}
        with patch('codex_wake.shared_app_server.SharedAppServerReader', Reader), patch(
                'codex_wake.sessions.observe', return_value=snapshot):
            with self.assertRaises(InventoryError):
                SavedRuntime().binding({'conversation_id': THREAD}, dict(
                    app_server='unix:///fixture/server', timeout=1))

    def test_cli_and_direct_mcp_handler_share_policy_and_suppression(self):
        parser = argparse.ArgumentParser()
        register_parser(parser.add_subparsers(dest='command', required=True))
        args = parser.parse_args(['agents', 'enroll', '--conversation-id', THREAD, '--operator', '--json'])
        observer = lambda _: observation(observed_at=100)
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(run(args, self.root / 'wake', observer=observer, now=lambda:100), 0)
        agent = json.loads(out.getvalue())['agent']['managed_agent_id']
        args = parser.parse_args(['agents', 'unenroll', '--managed-agent-id', agent, '--operator'])
        with patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(run(args, self.root / 'wake', now=lambda:100), 0)
        result = execute('enroll', {'conversation_id': THREAD}, self.root / 'wake',
                         native_context=native_context(), observer=observer, now=lambda:100)
        self.assertEqual(result['status'], 'suppressed')
        args = parser.parse_args(['agents', 'reenable', '--managed-agent-id', agent, '--json'])
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(run(args, self.root / 'wake', now=lambda:100), 2)
        self.assertEqual(json.loads(out.getvalue())['error']['code'], 'policy_denied')

    def test_real_grok_actor_authentication_is_required_and_changed_generation_is_rejected(self):
        session = '01234567-89ab-cdef-0123-456789abcdef'
        binding = 'grok_' + 'a' * 32
        repo = self.root / 'repo'
        repo.mkdir()
        class Host:
            changed = False
            def load_binding(self, identifier, sha=None):
                if identifier != binding or sha != 'f' * 64:
                    raise ValueError('changed binding')
                return dict(pid=123, start_ticks=42, boot_id='boot', session_id=session,
                            executable='/fixture/grok', executable_sha256='a' * 64, pane='%3')
            def snapshot(self, value):
                return dict(value, start_ticks=43 if self.changed else 42,
                            frame='Shell version: 1.0.40 [stable]\nSession ID: ' + session)
        class Process:
            descendant = True
            def cwd(self, _):
                return repo
            def owns_caller(self, _):
                return self.descendant
        host, process = Host(), Process()
        runtime = GrokMailboxRuntime(self.root / 'runtime', host=host, process=process)
        bus, operator = BusStore.configure(self.root / 'bus')
        bus.enroll(repo, operator, notify=True)
        capability, _, _ = runtime.issue_actor(bus, operator, repo, binding, binding_sha256='f' * 64)
        observer = RuntimeObserver(grok_runtime=runtime, bus=bus, capability=capability)
        args = {'runtime': 'grok', 'conversation_id': session}
        with patch('pathlib.Path.cwd', return_value=repo):
            first = execute('enroll', args, self.root / 'wake', observer=observer)
            self.assertEqual(first['agent']['evidence_kind'], 'host_bound_runtime')
            process.descendant = False
            with self.assertRaisesRegex(Exception, 'unavailable'):
                execute('enroll', args, self.root / 'wake', observer=observer)
            process.descendant = True
            host.changed = True
            with self.assertRaisesRegex(Exception, 'unavailable'):
                execute('enroll', args, self.root / 'wake', observer=observer)
        self.assertEqual(len(execute('list', {}, self.root / 'wake')['agents']), 1)
