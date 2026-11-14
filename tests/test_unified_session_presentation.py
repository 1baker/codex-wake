"""Conversation presentation changes preserve exact identity and unrelated panes."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from codex_wake.daemon_commands import local_operator

class SessionPresentationTests(unittest.TestCase):
    def test_parked_live_route_is_not_claimed_as_headless_execution(self):
        from codex_wake.unified_session_presentation import SessionPresentation
        with tempfile.TemporaryDirectory() as d:
            native=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread')
            row=dict(thread_id='thread',target=native,endpoint='unix:///owned',codex_cmd=['codex'],attachments=[dict(pane_id='%1',window_id='@1',socket='/owned-tmux',evidence='metadata_matched')])
            source=dict(host='h',environment='e',workspace='dev',presentation='byobu',generation='birth-dev')
            dest=dict(source,workspace='parked',generation='birth-parked')
            calls=[]
            class Tabs:
                host='h';environment='e'
                workspaces={'dev':{'transport':type('T',(),{'socket':'/owned-tmux'})()},'parked':{}}
                def execute(self,operation,args):
                    calls.append((operation,args))
                    if operation=='tabs.show':return {'resources':[dict(target=source,lifecycle_target=source,window=dict(window_id='@1',panes=[dict(pane_id='%1',pid=123,process_generation='original')]))]}
                    if operation=='tabs.park':return {'status':'applied','receipt_id':'placement-one','target':dest}
                    raise AssertionError(operation)
            with patch('codex_wake.unified_session_presentation.resolve',return_value=row):
                owner=SessionPresentation(Path(d),tabs=Tabs(),authorize=lambda target,action:local_operator(target,('control','content.observe')))
                request=dict(selector='thread:thread',expected_target=native,workspace='dev',window='@1',expected_presentation=source,destination='parked',expected_destination=dest,idempotency_key='park-one',route='park_live')
                first=owner.execute('environment.conversations.presentation.background',request)['result']['operation']
                owner.execute('environment.conversations.presentation.background',request)
                self.assertEqual(first['result']['route'],'parked_live_tui')
                self.assertFalse(first['result']['headless'])
                self.assertEqual(first['result']['conversation_id'],'thread')
                self.assertEqual(sum(op=='tabs.park' for op,args in calls),1)

    def test_multi_pane_tab_is_never_parked_on_behalf_of_one_conversation(self):
        from codex_wake.unified_session_presentation import SessionPresentation
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as d:
            native=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread')
            row=dict(thread_id='thread',target=native,endpoint='unix:///owned',codex_cmd=['codex'],attachments=[dict(pane_id='%1',window_id='@1',socket='/owned-tmux',evidence='metadata_matched')])
            source=dict(host='h',environment='e',workspace='dev',presentation='byobu',generation='birth')
            class Tabs:
                host='h';environment='e'
                workspaces={'dev':{'transport':type('T',(),{'socket':'/owned-tmux'})()}}
                def execute(self,operation,args):
                    if operation!='tabs.show':raise AssertionError('unrelated pane was moved')
                    return {'resources':[dict(target=source,lifecycle_target=source,window=dict(window_id='@1',panes=[dict(pane_id='%1'),dict(pane_id='%2')]))]}
            with patch('codex_wake.unified_session_presentation.resolve',return_value=row):
                owner=SessionPresentation(Path(d),tabs=Tabs(),authorize=lambda target,action:local_operator(target,('control',)))
                with self.assertRaisesRegex(InventoryError,'single'):
                    owner.execute('environment.conversations.presentation.background',dict(selector='thread:thread',expected_target=native,workspace='dev',window='@1',expected_presentation=source,destination='parked',expected_destination=source,idempotency_key='one',route='park_live'))

    def test_private_tmux_park_and_restore_preserve_the_injected_conversation_attachment(self):
        import shutil
        import subprocess
        from codex_wake.controller_tab_adapters import TmuxAttachmentTransport
        from codex_wake.controller_tabs import ControllerTabs
        from codex_wake.tab_lifecycle import TabLifecycle
        from codex_wake.unified_session_presentation import SessionPresentation
        executable=shutil.which('tmux')
        if executable is None:self.skipTest('tmux is not installed')
        with tempfile.TemporaryDirectory(prefix='p638-') as d:
            socket=str(Path(d)/'s')
            subprocess.run([executable,'-S',socket,'new-session','-d','-s','dev','-n','client','sleep 60'],check=True)
            try:
                subprocess.run([executable,'-S',socket,'new-window','-d','-t','dev','-n','spare','sleep 60'],check=True)
                subprocess.run([executable,'-S',socket,'new-session','-d','-s','parked','-n','sentinel','sleep 60'],check=True)
                tabs=ControllerTabs(d,workspaces={name:dict(transport=TmuxAttachmentTransport(socket,session),kind='byobu',privacy=lambda pane:'safe',observer=lambda timeout:{}) for name,session in [('dev','$0'),('parked','$1')]},host='h',environment='e')
                native=dict(host='h',environment='e',uid=os.getuid(),home=d,conversation_id='thread')
                row=dict(thread_id='thread',target=native,endpoint='unix:///injected-native',codex_cmd=['codex'],attachments=[dict(pane_id='%0',window_id='@0',socket=socket,evidence='metadata_matched')])
                def resource(workspace):return next(r for r in tabs.execute('tabs.show',dict(workspace=workspace))['resources'] if r['window']['window_id']=='@0')
                lifecycle=TabLifecycle(d,workspaces=tabs.workspaces,host='h',environment='e')
                before=resource('dev')
                birth=before['window']['panes'][0]['process_generation']
                with patch('codex_wake.unified_session_presentation.resolve',return_value=row):
                    owner=SessionPresentation(d,tabs=tabs,authorize=lambda target,action:local_operator(target,('control',)))
                    parked=owner.execute('environment.conversations.presentation.background',dict(selector='thread:thread',expected_target=native,workspace='dev',window='@0',expected_presentation=before['lifecycle_target'],destination='parked',expected_destination=lifecycle.inspect('parked')['target'],idempotency_key='park-real',route='park_live',force=True))['result']['operation']
                    self.assertEqual(parked['result']['route'],'parked_live_tui')
                    current=resource('parked')
                    self.assertEqual(current['window']['panes'][0]['process_generation'],birth)
                    restored=owner.execute('environment.conversations.presentation.foreground',dict(selector='thread:thread',expected_target=native,workspace='parked',window='@0',expected_presentation=current['lifecycle_target'],destination='dev',expected_destination=lifecycle.inspect('dev')['target'],idempotency_key='restore-real',route='restore_live',force=True,receipt_id=parked['result']['placement']['receipt_id']))['result']['operation']
                    self.assertEqual(restored['result']['route'],'foreground_live_tui')
                    self.assertEqual(resource('dev')['window']['panes'][0]['process_generation'],birth)
                    self.assertFalse(restored['result']['turn_interrupted'])
            finally:subprocess.run([executable,'-S',socket,'kill-server'],check=False,capture_output=True)
