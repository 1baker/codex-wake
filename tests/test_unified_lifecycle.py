"""Existing lifecycle owners remain behind canonical transport names."""
import unittest
from codex_wake.mcp_server import SPECS
from codex_wake.controller_http import TOOLS

class UnifiedLifecycleTests(unittest.TestCase):
    def test_history_alias_retains_native_caller_attestation(self):
        alias=SPECS['wake_environment_conversations_history_read']
        self.assertEqual(alias[:2],SPECS['wake_controller_history_read'][:2])
        self.assertIn('caller_thread_id',alias[4])
        self.assertNotIn('caller_thread_id',TOOLS['wake_environment_conversations_history_read'][1]['properties'])
    def test_account_profile_and_harness_runtime_names_keep_existing_owners(self):
        self.assertEqual(TOOLS['wake_accounts_profiles_resolve'][0],'accounts.resolve')
        self.assertEqual(SPECS['wake_harnesses_runtimes_status'][:2],SPECS['wake_daemons_status'][:2])
