"""Finite psmux transport contract; actual Windows acceptance is separate."""
import time
import unittest
from codex_wake.controller_tab_adapters import PsmuxAttachmentTransport
from codex_wake.managed_inventory import InventoryError


class PsmuxTransportTests(unittest.TestCase):
    def test_finite_lifecycle_and_visible_screen_preserve_pinned_bridge(self):
        seen = []
        def bridge(action, arguments, deadline):
            seen.append((action, arguments))
            return dict(generation='pinned', result='screen' if action == 'visible_screen' else dict(window_id='@1'))
        owner = PsmuxAttachmentTransport(bridge, generation='pinned')
        result = owner.lifecycle('rename', dict(window='@1', name='renamed'), time.monotonic() + 1)
        self.assertEqual(result['window_id'], '@1')
        self.assertEqual(owner.visible_screen('%1', time.monotonic() + 1), 'screen')
        self.assertEqual(owner.pinned_server_id, 'pinned')
        self.assertEqual(seen[0], ('lifecycle', dict(action='rename', window='@1', name='renamed')))
        with self.assertRaises(InventoryError):
            owner.lifecycle('execute', dict(argv=['never']), time.monotonic() + 1)

    def test_bridge_error_and_replaced_generation_are_typed(self):
        owner = PsmuxAttachmentTransport(lambda *a: dict(generation='pinned', error=dict(code='unsupported_operation', message='finite operation only')), generation='pinned')
        with self.assertRaises(InventoryError) as caught:
            owner.snapshot(time.monotonic() + 1)
        self.assertEqual(caught.exception.code, 'unsupported_operation')
        owner = PsmuxAttachmentTransport(lambda *a: dict(generation='replacement', result={}), generation='pinned')
        with self.assertRaises(InventoryError) as caught:
            owner.snapshot(time.monotonic() + 1)
        self.assertEqual(caught.exception.code, 'stale_target')


    def test_session_server_identity_and_finite_input_are_not_argv(self):
        from codex_wake.tab_psmux_bridge import BridgeError, PsmuxHost
        first = PsmuxAttachmentTransport(lambda *a: None, generation='source-pid-birth')
        second = PsmuxAttachmentTransport(lambda *a: None, generation='holding-pid-birth')
        self.assertFalse(first.same_server(second))
        self.assertFalse(first.same_server(object()))
        # Public host validation rejects command injection before any native I/O.
        owner = object.__new__(PsmuxHost)
        with self.assertRaises(BridgeError) as caught:
            owner.execute(dict(action='execute', arguments={'argv': ['never']}))
        self.assertEqual(caught.exception.code, 'unsupported_operation')
        with self.assertRaises(BridgeError):
            owner.execute(dict(action='snapshot', arguments={}, argv=['never']))

    def test_native_relative_move_dispatches_exact_ids_and_checks_readback(self):
        from codex_wake.tab_psmux_bridge import BridgeError, PsmuxHost
        owner = object.__new__(PsmuxHost)
        owner.session = 'test'
        windows = [dict(window_id='@4', index=0, focused=True, panes=[]),
                   dict(window_id='@5', index=1, focused=False, panes=[])]
        snapshot = dict(session_id='$0', windows=windows)
        observed = dict(session_id='$0', windows=[dict(windows[1], index=0), dict(windows[0], index=1)])
        commands = []
        owner.command = lambda *args: commands.append(args)
        owner._rows = lambda: [{'session_id': '$0'}]
        owner._snapshot = lambda rows, destination: observed
        args = dict(action='move', window='@5', position='before', anchor='@4')
        owner._lifecycle(args, snapshot, [])
        self.assertEqual(commands, [('move-window', '-d', '-b', '-s', 'test:@5', '-t', 'test:@4')])
        owner._snapshot = lambda rows, destination: snapshot
        with self.assertRaises(BridgeError) as error:
            owner._lifecycle(args, snapshot, [])
        self.assertEqual(error.exception.code, 'effect_uncertain')
