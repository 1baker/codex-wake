"""Observe a completed wake without hydrating unrelated conversation output."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.codex_runtime import CodexRuntimeAdapter
from codex_wake.records import WakeError


class SelectiveReconciliation(unittest.TestCase):
    def adapter(self, prompt, *, corrupt=False):
        self.calls = []
        user = dict(type='userMessage', id='message', clientId='client',
                    content=[dict(type='text', text=prompt)])

        def request(endpoint, executable, method, params, timeout):
            self.calls.append((method, params))
            if method == 'thread/queue/list':
                return dict(data=[], nextCursor=None)
            if method == 'thread/read':
                if params.get('includeTurns'):
                    raise TimeoutError('whole-history hydration exceeds deadline')
                return dict(thread=dict(id='owned'))
            if method == 'thread/turns/list':
                if params['itemsView'] == 'full':
                    raise TimeoutError('unrelated full tool output exceeds deadline')
                return dict(data=[dict(id='unrelated', status='completed', itemsView='summary', items=[]),
                                  dict(id='receipt-turn', status='completed', itemsView='summary',
                                       items=[user])], nextCursor=None)
            if method == 'thread/items/list':
                self.assertEqual(params['turnId'], 'receipt-turn')
                if not params.get('cursor'):
                    item = dict(user, clientId='changed') if corrupt else user
                    return dict(data=[dict(turnId='receipt-turn', item=item)], nextCursor='answer')
                return dict(data=[dict(turnId='receipt-turn', item=dict(
                    type='agentMessage', id='answer', text='finished'))], nextCursor=None)
            raise AssertionError('unexpected native method: ' + method)

        def forbidden(*args, **kwargs):
            raise AssertionError('reconciliation must not submit or resume native work')

        return CodexRuntimeAdapter(read_thread=forbidden, request=request,
                                   run=forbidden, project_failure=forbidden)

    def target(self):
        return dict(transport='native', thread_id='owned', endpoint='unix:///owned',
                    codex_cmd='/bin/true')

    def test_completed_wake_reconciles_without_unrelated_full_history(self):
        adapter = self.adapter('exact wake')
        result = adapter.reconcile(adapter.resolve(self.target()), 'exact wake')
        self.assertEqual(result.evidence['execution'], 'turn_completed')
        self.assertEqual(result.evidence['client_message_id'], 'client')
        self.assertEqual(result.evidence['output_summary']['text_bytes'], 8)
        self.assertFalse(any(method == 'thread/read' and params.get('includeTurns')
                             for method, params in self.calls))

    def test_summary_identity_must_match_hydrated_native_item(self):
        adapter = self.adapter('exact wake', corrupt=True)
        with self.assertRaises(WakeError):
            adapter.reconcile(adapter.resolve(self.target()), 'exact wake')

    def test_verified_completed_peer_releases_next_wake_admission(self):
        from codex_wake.native_delivery import native_prompt
        from codex_wake.wake_mode_runtime import _pending_peer
        target = self.target()
        peer = dict(id='earlier', prompt='completed work', target=target,
                    native_delivery=dict(state='accepted', submission_id='submission',
                                         prompt_sha256='checksum'))
        current = dict(id='next', target=target)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = native_prompt(root, peer)
            adapter = self.adapter(prompt)
            with patch('codex_wake.wake_mode_runtime._peer_records', return_value=iter([peer])):
                self.assertEqual(_pending_peer(root, current, adapter), (False, False))
            self.assertTrue(list((root / 'terminal-wake-evidence').glob('*.json')))
