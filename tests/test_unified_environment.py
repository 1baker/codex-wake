"""The operator navigates physical Byobu placement and independent bot ancestry."""
import tempfile
import unittest
from codex_wake.controller_tabs import ControllerTabs

class UnifiedEnvironmentTests(unittest.TestCase):
    def test_saved_sessions_and_bot_children_remain_distinct_resources(self):
        from codex_wake.unified_environment import Environment
        with tempfile.TemporaryDirectory() as d:
            tabs=ControllerTabs(d,workspaces={},host='h',environment='byobu')
            tabs.execute('tabs.session.create',{'name':'dev tabs'})
            tabs.execute('tabs.session.create',{'name':'codex-bots'})
            tabs.execute('tabs.family.register',{'bot_id':'parent','name':'Parent'})
            tabs.execute('tabs.family.register',{'bot_id':'child','name':'Child','parent_bot_id':'parent'})
            view=Environment(d,tabs=tabs).snapshot()
            self.assertEqual({s['name'] for s in view['sessions']},{'dev tabs','codex-bots'})
            self.assertTrue(all(s['tabs']==[] for s in view['sessions']))
            child=next(b for b in view['agents'] if b['bot_id']=='child')
            self.assertEqual(child['parent_bot_id'],'parent')
            self.assertEqual(view['host'],'h')
            self.assertFalse(view['grants_authority'])
