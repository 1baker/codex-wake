"""Provided authority pins cannot be reused for another workspace's policy."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest

from codex_wake.controller_auth import Actor
from codex_wake.controller_http import ProtectedOperations
from codex_wake.controller_operations import ControllerOperations
from codex_wake.controller_tab_adapters import TmuxAttachmentTransport
from codex_wake.controller_tabs import ControllerTabs
from codex_wake.managed_inventory import ManagedInventory


@unittest.skipUnless(shutil.which('tmux'), 'tmux unavailable')
class FormattingScopeTests(unittest.TestCase):
    def test_workspace_grant_and_pin_cannot_configure_another_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            socket=str(Path(directory)/'tmux.sock')
            def tmux(*args,check=True):
                return subprocess.run(['tmux','-S',socket,*args],capture_output=True,text=True,check=check,timeout=5)
            tmux('new-session','-d','-s','work','sleep 30')
            try:
                tmux('new-session','-d','-s','other','sleep 30')
                workspaces={name:dict(kind='tmux',transport=TmuxAttachmentTransport(socket,session))
                            for name,session in (('work','$0'),('other','$1'))}
                tabs=ControllerTabs(directory,workspaces=workspaces,host='host',environment='local')
                pin=tabs.format_target(workspace='work')
                scope={key:value for key,value in pin.items() if key!='generation'}
                actor=Actor('caller','service','client','grant','issuer','resource',frozenset(('control','observe')),
                            [scope],time.time()+60)
                facade=ProtectedOperations(SimpleNamespace(authenticate=lambda token:actor),
                    ControllerOperations(ManagedInventory(directory),host='host',environment='local',tabs=tabs))
                envelope=facade.execute('token','tabs.format.configure',dict(workspace='other',
                    expected_target=pin,policy={'show_model':True},_request=dict(
                        operation_id='wrong-workspace',idempotency_key='wrong-workspace',
                        correlation_id='wrong-workspace',binding='scope-test',target=pin)))
                operation=envelope['result']['operation']
                self.assertEqual(operation['reason'],'stale_target')
                self.assertFalse(tabs.execute('tabs.format.inspect',dict(workspace='other'))['policy']['show_model'])
                allowed=facade.execute('token','tabs.format.configure',dict(workspace='work',
                    expected_target=pin,policy={'show_model':True},_request=dict(
                        operation_id='right-workspace',idempotency_key='right-workspace',
                        correlation_id='right-workspace',binding='scope-test',target=pin)))
                self.assertEqual(allowed['result']['operation']['result']['status'],'configured')
                self.assertTrue(tabs.execute('tabs.format.inspect',dict(workspace='work'))['policy']['show_model'])
            finally:
                tmux('kill-server',check=False)

    def test_linked_override_requires_control_of_all_terminal_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory) / 'tmux.sock')
            def tmux(*args, check=True):
                return subprocess.run(['tmux', '-S', socket, *args], capture_output=True, text=True,
                                      check=check, timeout=5).stdout
            tmux('new-session', '-d', '-s', 'work', 'sleep 30')
            try:
                tmux('new-session', '-d', '-s', 'other', 'sleep 30')
                tmux('link-window', '-s', 'work:0', '-t', 'other:1')
                tmux('link-window', '-s', 'work:0', '-t', 'work:3')
                tmux('select-window', '-t', 'work:3')
                workspaces = {name: dict(kind='tmux', transport=TmuxAttachmentTransport(socket, session))
                              for name, session in (('work', '$0'), ('other', '$1'))}
                tabs = ControllerTabs(directory, workspaces=workspaces, host='host', environment='local')
                window, = tabs.execute('tabs.list', {})['resources'][:1]
                self.assertTrue(window['window']['focused'])
                self.assertEqual(len(window['window']['panes']), 1)
                self.assertEqual(window['window']['linked_appearances'], [
                    {'session_id': '$0', 'index': 0}, {'session_id': '$0', 'index': 3},
                    {'session_id': '$1', 'index': 1}])
                pin = tabs.format_target(workspace='work')
                scopes = [{k: v for k, v in target.items() if k != 'generation'}
                          for target in (pin, tabs.format_target(workspace='other'))]
                operations = ControllerOperations(ManagedInventory(directory), host='host',
                                                  environment='local', tabs=tabs)
                def set_style(request_id, targets):
                    actor = Actor('caller', 'service', 'client', 'grant', 'issuer', 'resource',
                                  frozenset(('control', 'observe')), targets, time.time() + 60)
                    facade = ProtectedOperations(SimpleNamespace(authenticate=lambda token: actor), operations)
                    return facade.execute('token', 'tabs.format.override-set', dict(
                        workspace='work', window='@0', expected_target=pin,
                        style=dict(foreground='yellow', background='blue', attributes=['bold']),
                        _request=dict(operation_id=request_id, idempotency_key=request_id,
                                      correlation_id=request_id, binding='scope-test', target=pin)))['result']['operation']
                self.assertEqual(set_style('linked-source-only', scopes[:1])['reason'], 'insufficient_scope')
                self.assertEqual(tmux('show-options', '-w', '-v', '-t', '@0', 'window-status-style'), '')
                transport = workspaces['work']['transport']
                original_formatting = transport.formatting
                def change_links(action, arguments, deadline):
                    value = original_formatting(action, arguments, deadline)
                    if action == 'read':
                        tmux('link-window', '-s', 'work:0', '-t', 'other:7')
                    return value
                transport.formatting = change_links
                self.assertEqual(set_style('changed-links', scopes)['reason'], 'stale_target')
                self.assertEqual(tmux('show-options', '-w', '-v', '-t', '@0', 'window-status-style'), '')
                transport.formatting = original_formatting
                tmux('unlink-window', '-t', 'other:7')
                accepted = set_style('linked-all-scopes', scopes)
                self.assertEqual(accepted['execution'], 'completed', accepted)
                inspected = tabs.execute('tabs.format.override-inspect', dict(workspace='other', window='@0'))
                self.assertEqual(inspected['override']['foreground'], 'yellow')
                self.assertEqual(inspected['options']['window-status-style']['value'], 'fg=yellow,bg=blue,bold')
            finally:
                tmux('kill-server', check=False)
