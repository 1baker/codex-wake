"""Exact target resolution must not depend on unrelated account discovery."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from codex_wake.local_sessions import resolve
from codex_wake.managed_inventory import InventoryError

class PinnedNativeLookupTests(TestCase):
 def test_exact_shared_target_survives_unrelated_daemon_discovery_failure(self):
  target=dict(host='host',home='/owned',conversation_id='thread',process={'pid':123})
  row=dict(thread_id='thread',target=target)
  def observe(root,endpoint='unix://',socket_path=None, **kwargs):
   if endpoint=='unix://':raise InventoryError('daemon_unavailable','unrelated registered account cannot be verified')
   return dict(sessions=[row],holds=[])
  with patch('codex_wake.local_sessions.locate_shared_endpoint',return_value='unix:///shared.sock'),patch('codex_wake.local_sessions.discover',side_effect=observe):
   self.assertEqual(resolve(Path('/root'),'thread:thread',target),row)

 def test_changed_target_cannot_use_fast_path(self):
  target=dict(home='/owned',conversation_id='thread',process={'pid':123})
  def observe(root,endpoint='unix://',socket_path=None, **kwargs):
   if endpoint=='unix://':raise InventoryError('daemon_unavailable','unverified fallback remains refused')
   return dict(sessions=[dict(thread_id='thread',target=dict(target,process={'pid':124}))],holds=[])
  with patch('codex_wake.local_sessions.locate_shared_endpoint',return_value='unix:///shared.sock'),patch('codex_wake.local_sessions.discover',side_effect=observe):
   with self.assertRaises(InventoryError):resolve(Path('/root'),'thread:thread',target)

 def test_unpinned_lookup_keeps_full_discovery(self):
  with patch('codex_wake.local_sessions.discover',side_effect=InventoryError('daemon_unavailable','unverified account')):
   with self.assertRaises(InventoryError):resolve(Path('/root'),'thread:thread')

 def test_exact_loaded_observation_does_not_read_unrelated_threads(self):
  from codex_wake.shared_app_server import SharedAppServerReader
  reader=SharedAppServerReader('unix:///unused.sock')
  reader.request=lambda method,params: dict(data=['other','thread'],nextCursor=None)
  def read(thread_id):
   self.assertEqual(thread_id,'thread')
   return dict(id=thread_id)
  reader.read_thread=read
  self.assertEqual(reader.loaded_threads(selected_thread_id='thread'),[dict(id='thread')])
