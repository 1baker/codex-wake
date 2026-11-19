import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

THREAD = '01a123a8-5782-7d43-a214-55b293bbd65f'


class ControllerHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'controller-accounts.toml'
        self.path.write_text(f'''[profiles]
state_root="{self.root / 'homes'}"
known_profiles=["alice","bob"]
[history]
readable_accounts=["alice","bob"]
''')
        for name in ('alice', 'bob'):
            home = self.root / 'homes' / ('codex-' + name)
            (home / 'sessions').mkdir(parents=True)
            rollout = home / 'sessions' / 'saved.jsonl'
            rollout.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': THREAD}}) + '\n' +
                               json.dumps({'type': 'response_item', 'payload': {'content': name + ' evidence'}}) + '\n')
            with sqlite3.connect(home / 'state_5.sqlite') as db:
                db.execute('create table threads (id text primary key, cwd text, title text, rollout_path text)')
                db.execute('insert into threads values(?,?,?,?)', (THREAD, str(self.root), name + ' report', str(rollout)))

    def owner(self, accounts=('alice', 'bob'), **kwargs):
        from codex_wake.controller_history import ControllerHistory
        return ControllerHistory(self.path, root=self.root / 'wake', host='local', environment='test',
                                 authorized_accounts=accounts, **kwargs)

    def test_registered_stock_history_uses_original_home_and_stable_store_identity(self):
        from codex_wake.controller_accounts import ControllerAccounts
        home = self.root / 'homes' / 'codex-alice'
        accounts = ControllerAccounts(self.path, host='local', environment='test')
        store = accounts.execute('stores.register', {'selector': 'stock', 'home': str(home)})['store']
        self.path.write_text(self.path.read_text().replace('readable_accounts=["alice","bob"]', 'readable_accounts=["stock"]'))
        owner = self.owner(('stock',))
        found = owner.execute('history.search', {'owners': ['stock']})
        self.assertEqual(len(found['sessions']), 1)
        session = found['sessions'][0]
        self.assertEqual(session['owner'], 'stock')
        self.assertEqual(session['provenance']['store_id'], store['store_id'])
        self.assertEqual(session['provenance']['namespace'], str(home))
        read = owner.execute('history.read', {'owner': 'stock', 'thread_id': THREAD})
        self.assertEqual(read['records'][1]['payload']['content'], 'alice evidence')

    def test_search_and_read_keep_duplicate_ids_bound_to_their_permitted_owner(self):
        owner = self.owner()
        found = owner.execute('history.search', {'query': 'report'})
        self.assertEqual([row['owner'] for row in found['sessions']], ['codex-alice', 'codex-bob'])
        first = found['sessions'][0]
        self.assertEqual(first['target']['conversation_id'], THREAD)
        self.assertEqual(first['provenance']['native_schema'], 5)
        read = owner.execute('history.read', {'owner': 'alice', 'thread_id': THREAD,
                                            'expected_target': first['target']})
        self.assertEqual(read['session']['owner'], 'codex-alice')
        self.assertEqual(read['records'][1]['payload']['content'], 'alice evidence')
        only_alice = self.owner(('alice',)).execute('history.search', {})
        self.assertEqual([row['owner'] for row in only_alice['sessions']], ['codex-alice'])

    def test_resume_uses_existing_permission_and_durable_attachment_owner(self):
        from codex_wake.controller_history import ManagedHistoryResume
        from codex_wake.session_permissions import Principal
        from tests.test_agent_resume_protocol import ResumeProtocolTests
        fixture = ResumeProtocolTests(methodName='test_mcp_real_protocol_launch_and_reconstructed_owner_exact_identity')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Bind this saved history to the fixture's existing account/backend.
        data = self.path.read_text().replace('readable_accounts=["alice","bob"]', 'readable_accounts=["alice","bob"]\nresume_enabled=true')
        data += f'''\n[history.bindings."{THREAD}"]
account="codex-alice"
managed_agent_id="{fixture.agent['managed_agent_id']}"
profile="saved"
profiles="{fixture.profiles}"
'''
        self.path.write_text(data)
        from codex_wake.a2a_identity import RuntimeIdentity
        fixture.metadata['codexHome'] = str(self.root / 'homes' / 'codex-alice')
        fixture.namespace = RuntimeIdentity.from_metadata(fixture.thread, fixture.metadata).namespace
        fixture.agent = fixture.enroll_ended_generation()
        data = data.replace(data.split('managed_agent_id=')[1].split('\n')[0], '"' + fixture.agent['managed_agent_id'] + '"')
        self.path.write_text(data)
        config = fixture.config
        config['recovery_callers'] = {'local-operator': [fixture.agent['managed_agent_id']]}
        config['profiles']['saved']['codex_home'] = str(self.root / 'homes' / 'codex-alice')
        config['profiles']['saved']['cwd'] = str(self.root)
        fixture.save_profiles()
        # Existing inventory namespace is protocol-derived; adopt its precise
        # root/account in the saved DB rather than manufacturing an enrollment.
        with sqlite3.connect(self.root / 'homes' / 'codex-alice' / 'state_5.sqlite') as db:
            db.execute('update threads set cwd=?', (str(fixture.base),))
        config['profiles']['saved']['cwd'] = str(fixture.base)
        fixture.save_profiles()
        adapter = ManagedHistoryResume(fixture.root, Principal('local-operator', 'operator'),
                                       runtime=fixture.runtime, now=lambda: fixture.inv.now())
        owner = self.owner(resume_owner=adapter)
        session = owner.execute('history.search', {'owners': ['alice']})['sessions'][0]
        result = owner.execute('history.resume', {'owner': 'alice', 'thread_id': THREAD,
            'expected_target': session['target'], 'intent': 'unified-history',
            'expires_at': '2027-01-16T09:00:00+00:00'})
        self.assertEqual(result['resume']['status'], 'resumed')
        self.assertEqual(result['session']['owner'], 'codex-alice')
        self.assertEqual(result['attachment']['state'], 'ready')
        self.assertEqual(result['attachment']['attachments'][0]['pane_id'], '%7')
        replay = owner.execute('history.resume', {'owner': 'alice', 'thread_id': THREAD,
            'expected_target': session['target'], 'intent': 'unified-history',
            'expires_at': '2027-01-16T09:00:00+00:00'})
        self.assertEqual(replay['resume']['status'], 'resumed')
        self.assertEqual(len([command for command in fixture.commands if command[0] == 'new-window']), 1)
        from codex_wake.managed_inventory import InventoryError
        unauthorized_owner = self.owner(resume_owner=ManagedHistoryResume(fixture.root,
            Principal('untrusted-controller', 'controller'), runtime=fixture.runtime, now=lambda: fixture.inv.now()))
        with self.assertRaises(InventoryError) as denied:
            unauthorized_owner.execute('history.resume', {'owner': 'alice', 'thread_id': THREAD,
                'expected_target': session['target'], 'intent': 'intruder', 'expires_at': '2027-01-16T09:00:00+00:00'})
        self.assertEqual(denied.exception.code, 'resume_recovery_authority_required')
        ledger_dir = fixture.root / 'objective-ledgers'
        ledger_dir.mkdir(exist_ok=True)
        ledger = ledger_dir / 'existing.json'
        ledger.write_bytes(b'{"used":93,"original_deadline":1800000010,"unknown":true}')
        preserved = ledger.read_bytes()
        fixture.current = False
        fixture.enroll_ended_generation()
        fixture.lost = True
        uncertain_args = dict(owner='alice', thread_id=THREAD, expected_target=session['target'],
            intent='lost-response', expires_at='2027-01-16T09:00:00+00:00')
        uncertain = owner.execute('history.resume', uncertain_args)
        self.assertEqual(uncertain['resume']['status'], 'uncertain')
        self.assertEqual(uncertain['resume']['effects_attempted'], 1)
        reconciled = owner.execute('history.resume', uncertain_args)
        self.assertEqual(reconciled['resume']['status'], 'resumed')
        self.assertEqual(len([command for command in fixture.commands if command[0] == 'new-window']), 2)
        self.assertEqual(ledger.read_bytes(), preserved)
        import argparse
        import contextlib
        import io
        from codex_wake.a2a_bus import BusStore
        from codex_wake.history_commands import command, execute, mcp_call, register_parser
        (fixture.root / 'controller-accounts.toml').write_text(data + f'\n[history.callers]\n"{THREAD}"=["alice"]\n')
        public = execute('history.read', {'owner': 'alice', 'thread_id': THREAD}, fixture.root,
                         authorized_accounts=['alice'])['result']['session']
        bus, capability = BusStore.configure(fixture.base / 'history-bus')
        parser = argparse.ArgumentParser()
        register_parser(parser.add_subparsers(dest='command', required=True))
        args = parser.parse_args(['history', 'resume', THREAD, '--owner', 'alice', '--intent', 'cli-history',
            '--expires-at', '2027-01-16T09:00:00+00:00', '--expected-target', json.dumps(public['target']),
            '--bus-root', str(bus.root), '--operator-capability', str(capability), '--json'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(command(args, fixture.root, runtime=fixture.runtime, now=lambda: fixture.inv.now()), 0)
        self.assertEqual(json.loads(output.getvalue())['result']['resume']['status'], 'resumed')
        mcp, failed = mcp_call(type('Runner', (), {'wake_root': fixture.root})(),
            dict(owner='alice', thread_id=THREAD, caller_thread_id=THREAD, intent='mcp-history',
                 expires_at='2027-01-16T09:00:00+00:00', expected_target=public['target']),
            fixture.context, 'resume', runtime=fixture.runtime, now=lambda: fixture.inv.now())
        self.assertFalse(failed, mcp)
        self.assertEqual(mcp['result']['resume']['status'], 'resumed')

    def test_unauthorized_stale_and_compressed_targets_refuse_before_resume(self):
        from codex_wake.managed_inventory import InventoryError
        owner = self.owner(('alice',))
        for operation, arguments, code in (
            ('history.read', {'owner': 'bob', 'thread_id': THREAD}, 'unauthorized_target'),
            ('history.search', {'owners': ['bob']}, 'unauthorized_target'),
            ('history.read', {'owner': 'alice', 'thread_id': THREAD, 'principal': 'operator'}, 'invalid_argument'),
        ):
            with self.assertRaises(InventoryError) as error:
                owner.execute(operation, arguments)
            self.assertEqual(error.exception.code, code)
        row = owner.execute('history.search', {})['sessions'][0]
        rollout = Path(row['rollout_path'])
        rollout.write_text(rollout.read_text() + '{}\n')
        with self.assertRaises(InventoryError) as error:
            owner.execute('history.resume', {'owner': 'alice', 'thread_id': THREAD,
                'expected_target': row['target'], 'intent': 'stale', 'expires_at': '2027-01-01T00:00:00Z'})
        self.assertEqual(error.exception.code, 'stale_target')
        compressed = rollout.with_suffix('.jsonl.zst')
        rollout.rename(compressed)
        with sqlite3.connect(self.root / 'homes' / 'codex-alice' / 'state_5.sqlite') as db:
            db.execute('update threads set rollout_path=?', (str(compressed),))
        with self.assertRaises(InventoryError) as error:
            owner.execute('history.read', {'owner': 'alice', 'thread_id': THREAD})
        self.assertEqual(error.exception.code, 'unsupported_target')

    def test_standalone_cli_and_mcp_adapters_share_permitted_history_contract(self):
        import argparse
        import contextlib
        import io
        from types import SimpleNamespace
        from codex_wake.history_commands import command, mcp_call, register_parser
        caller = THREAD
        self.path.write_text(self.path.read_text() + f'\n[history.callers]\n"{caller}"=["alice"]\n')
        # The fixed adapter root owns both host policy and runtime receipts.
        parser = argparse.ArgumentParser()
        register_parser(parser.add_subparsers(dest='command', required=True))
        args = parser.parse_args(['history', 'read', THREAD, '--owner', 'alice', '--json'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(command(args, self.root), 0)
        context = dict(threadId=caller, sessionId=caller, callId='fixture', **{
            'x-codex-turn-metadata': dict(thread_id=caller, session_id=caller, turn_id='turn')})
        mcp, failed = mcp_call(SimpleNamespace(wake_root=self.root),
            {'caller_thread_id': caller, 'owner': 'alice', 'thread_id': THREAD}, context, 'read')
        self.assertFalse(failed)
        self.assertEqual(json.loads(output.getvalue()), mcp)
        unauthorized, failed = mcp_call(SimpleNamespace(wake_root=self.root),
            {'caller_thread_id': caller, 'owner': 'bob', 'thread_id': THREAD}, context, 'read')
        self.assertTrue(failed)
        self.assertEqual(unauthorized['error']['code'], 'unauthorized_target')

    def test_trusted_authorization_guard_can_revoke_before_native_source_access(self):
        from codex_wake.managed_inventory import InventoryError
        calls = []
        def revoked(operation, arguments):
            calls.append(operation)
            raise InventoryError('unauthorized_target', 'grant revoked')
        owner = self.owner(authorization_guard=revoked)
        # Even an unusable source must produce authorization denial first.
        (self.root / 'homes' / 'codex-alice' / 'state_5.sqlite').write_bytes(b'invalid')
        with self.assertRaises(InventoryError) as error:
            owner.execute('history.search', {'owners': ['alice']})
        self.assertEqual(error.exception.code, 'unauthorized_target')
        self.assertEqual(calls, ['history.search'])
