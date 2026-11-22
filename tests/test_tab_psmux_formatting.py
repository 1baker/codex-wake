"""Finite native formatting boundary; installed acceptance is separate."""
from itertools import groupby
import time
import unittest

from codex_wake.controller_tab_adapters import PsmuxAttachmentTransport
from codex_wake.managed_inventory import InventoryError
from codex_wake.tab_psmux_bridge import BridgeError, PsmuxHost


class PsmuxFormattingTests(unittest.TestCase):
    def test_transport_exposes_only_typed_formatting_and_preserves_generation(self):
        def bridge(action,arguments,deadline):
            self.assertEqual(action,'formatting')
            self.assertEqual(arguments,dict(action='read',window='@1'))
            return dict(generation='current',result={'window-status-format':dict(explicit=False,value=None,effective='#W')})
        transport=PsmuxAttachmentTransport(bridge,generation='current')
        self.assertFalse(transport.formatting('read',dict(window='@1'),time.monotonic()+1)['window-status-format']['explicit'])
        with self.assertRaises(InventoryError):
            transport.formatting('execute',dict(argv=['never']),time.monotonic()+1)

    def test_native_window_baseline_uses_local_listing_not_effective_single_option(self):
        class Native(PsmuxHost):
            def __init__(self):
                self.session='fixture';self.generation='pinned';self.local={'window-status-format':'local #W'}
                self.effective={'window-status-format':'global #W','window-status-current-format':'[#W]',
                                'window-status-style':'fg=white','window-status-current-style':'bold'}
            def _current(self):pass
            def _rows(self):return []
            def _snapshot(self,rows):return dict(windows=[dict(window_id='@1',index=0,panes=[])],session_id='$1')
            def command(self, *args, timeout=4):
                output = []
                for separator, entries in groupby(args, lambda arg: arg == ';'):
                    if separator:
                        continue
                    command = tuple(entries)
                    assert 'fixture:@1' in command, command
                    if command[0] == 'display-message':
                        output.append(command[-1])
                    elif command == ('show-options', '-w', '-t', 'fixture:@1'):
                        output.extend(k + ' ' + v for k, v in self.local.items())
                    else:
                        name = command[-1]
                        values = self.effective if '-g' in command else dict(self.effective, **self.local)
                        output.append(values[name])
                return '\n'.join(output) + '\n'
        host=Native()
        result=host.execute(dict(action='formatting',arguments=dict(action='read',window='@1')))['result']
        self.assertTrue(result['window-status-format']['explicit'])
        self.assertEqual(result['window-status-format']['value'],'local #W')
        self.assertEqual(result['window-status-format']['parent'],'global #W')
        self.assertFalse(result['window-status-style']['explicit'])
        self.assertIsNone(result['window-status-style']['value'])
        self.assertEqual(result['window-status-style']['effective'],'fg=white')

    def test_batch_rejects_invalid_member_before_any_native_write(self):
        class Native(PsmuxHost):
            def __init__(self):self.session='fixture';self.generation='pinned';self.writes=[]
            def _current(self):pass
            def _rows(self):return []
            def _snapshot(self,rows):return dict(windows=[dict(window_id='@1',index=0,panes=[])],session_id='$1')
            def command(self,*args,timeout=4):
                self.writes.append(args);raise AssertionError('invalid batch must not reach terminal')
        host=Native()
        request=dict(action='formatting_batch',arguments=dict(requests=[
            dict(action='write',window='@1',values={'window-status-format':'safe'}),
            dict(action='write',window='@1',values={'default-shell':'never'})]))
        with self.assertRaises(BridgeError):host.execute(request)
        self.assertEqual(host.writes,[])
        request['arguments']['requests'][1]=dict(action='write',window='@9',values={'window-status-format':'wrong namespace'})
        with self.assertRaises(BridgeError):host.execute(request)
        self.assertEqual(host.writes,[])

    def test_oversized_batch_is_rejected_before_native_bridge_effects(self):
        called=[]
        def bridge(*arguments):called.append(arguments);return dict(generation='pinned',result=[])
        transport=PsmuxAttachmentTransport(bridge,generation='pinned')
        requests=[dict(action='write',window='@'+str(i),values={'window-status-format':'x'*8192}) for i in range(10)]
        with self.assertRaises(InventoryError) as error:transport.formatting_batch(requests,time.monotonic()+1)
        self.assertEqual(error.exception.code,'capacity')
        self.assertEqual(called,[])
