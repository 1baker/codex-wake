"""Public tab discovery and ordinary CLI transport contract."""
import json
import os
import subprocess
import sys
import unittest


class TabContractTests(unittest.TestCase):
    def test_schema_discovery_is_portable_without_linux_runtime_owners(self):
        script = '''
import builtins
original=builtins.__import__
def portable(name,*args,**kwargs):
    if name == 'fcntl':raise ImportError('Linux owner unavailable on Windows')
    return original(name,*args,**kwargs)
builtins.__import__=portable
from codex_wake.tab_commands import tool_specs
assert 'wake_tabs_recovery_apply' in tool_specs()
'''
        result = subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_ordinary_flags_are_operation_specific_and_keep_request_identity(self):
        from codex_wake.cli import build_parser
        parser=build_parser()
        args=parser.parse_args(['tabs','input','--workspace','work','--pane','%1','--input','hello',
            '--custody','{"owner_id":"host"}','--transport','structured','--request-id','send-1'])
        self.assertEqual(args.pane,'%1')
        self.assertEqual(args.request_id,'send-1')
        with self.assertRaises(SystemExit):
            parser.parse_args(['tabs','monitor-status','--retire-source'])
        with self.assertRaises(SystemExit):
            parser.parse_args(['tabs','list','--force'])

    def test_same_uid_request_result_survives_closed_workspace_without_replay(self):
        import shutil,tempfile,time
        from pathlib import Path
        from codex_wake.controller_tab_adapters import TmuxAttachmentTransport
        from codex_wake.controller_tabs import ControllerTabs
        from codex_wake.tab_commands import operator_execute
        from codex_wake.controller_runtime import ControllerRuntime
        if not shutil.which('tmux'):self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            socket=str(Path(directory)/'tmux.sock')
            subprocess.run(['tmux','-S',socket,'new-session','-d','-s','fixture','sleep 60'],check=True)
            class LostResponseTabs(ControllerTabs):
                def execute(self,operation,arguments):
                    value=super().execute(operation,arguments)
                    if operation=='tabs.close':raise OSError('synthetic response lost after effect')
                    return value
            owner=LostResponseTabs(directory,workspaces={'fixture':dict(kind='tmux',transport=TmuxAttachmentTransport(socket,'$0'))},host='host',environment='test')
            try:
                arguments=dict(workspace='fixture',window='@0',force=True)
                result=operator_execute('tabs.close',arguments,directory,owner=owner,request_id='close-1')
                self.assertEqual(result['result']['operation']['phase'],'uncertain')
                retry=operator_execute('tabs.close',arguments,directory,owner=owner,request_id='close-1')
                self.assertEqual(retry['result']['operation']['operation_id'],'tab-cli-close-1')
                retained=ControllerRuntime(directory).local_tab_result('tab-cli-close-1')
                self.assertEqual(retained['result']['operation']['phase'],'uncertain')
                from codex_wake.managed_inventory import InventoryError
                with self.assertRaises(InventoryError):
                    operator_execute('tabs.close',dict(arguments,window='@9'),directory,owner=owner,request_id='close-1')
            finally:
                subprocess.run(['tmux','-S',socket,'kill-server'],capture_output=True)

    def test_shared_unlink_and_confirmed_destroy_use_public_journal(self):
        import shutil
        import tempfile
        from pathlib import Path

        from codex_wake.controller_tab_adapters import TmuxAttachmentTransport
        from codex_wake.controller_tabs import ControllerTabs
        from codex_wake.tab_commands import operator_execute
        from codex_wake.controller_runtime import ControllerRuntime

        if not shutil.which('tmux'):
            self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory) / 'tmux.sock')

            def tmux(*arguments):
                return subprocess.check_output(['tmux', '-S', socket, *arguments], text=True).strip()

            tmux('new-session', '-d', '-s', 'one', '-n', 'keep', 'sleep 60')
            self.addCleanup(subprocess.run, ['tmux', '-S', socket, 'kill-server'], capture_output=True)
            tmux('new-session', '-d', '-s', 'two', '-n', 'keep', 'sleep 60')
            window = tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-t', 'one:', 'sleep 60')
            tmux('link-window', '-s', 'one:' + window, '-t', 'two:3')
            calls = []
            change_membership = []

            class LostResponseTransport(TmuxAttachmentTransport):
                def command(self, deadline, *arguments):
                    destroy = arguments[0] == 'if-shell' and arguments[-2].startswith('kill-window')
                    if destroy and change_membership:
                        change_membership.pop()
                        super().command(deadline, 'link-window', '-d', '-s', 'one:' + window, '-t', 'two:4')
                    result = super().command(deadline, *arguments)
                    if destroy and result.strip() != 'stale_target':
                        calls.append(arguments[-2])
                        raise OSError('test response lost after real effect')
                    return result

            owner = ControllerTabs(directory, host='host', environment='test', workspaces={
                'one': dict(kind='tmux', transport=LostResponseTransport(socket, '$0')),
                'two': dict(kind='tmux', transport=TmuxAttachmentTransport(socket, '$1')),
            })

            def execute(verb, request, **arguments):
                result = operator_execute('tabs.' + verb, dict(workspace='one', window=window, **arguments),
                                          directory, owner=owner, request_id=request)
                return result['result']['operation']

            pane = tmux('display-message', '-p', '-t', 'one:' + window, '#{pane_id}')
            tmux('link-window', '-s', 'one:' + window, '-t', 'one:4')
            ambiguous = execute('unlink', 'unlink-ambiguous')
            self.assertEqual(ambiguous['reason'], 'ambiguous_target', ambiguous)
            duplicate = execute('unlink', 'unlink-at-index', index=4)
            self.assertEqual(duplicate['execution'], 'completed', duplicate)
            self.assertEqual(tmux('display-message', '-p', '-t', 'one:' + window, '#{pane_id}'), pane)
            unlink = execute('unlink', 'unlink-one')
            self.assertEqual(unlink['execution'], 'completed', unlink)
            self.assertEqual(unlink['result']['remaining_sessions'], [{'session_id': '$1', 'index': 3}])
            self.assertEqual(tmux('display-message', '-p', '-t', 'two:' + window, '#{pane_id}'), pane)
            tmux('link-window', '-s', 'two:' + window, '-t', 'one:2')
            preview = execute('destroy', 'preview-shared', preview=True)
            self.assertEqual(preview['execution'], 'completed', preview)
            impact = preview['result']
            self.assertEqual([item['session_id'] for item in impact['affected_sessions']], ['$0', '$1'])
            self.assertEqual(impact['pane_ids'], [pane])
            change_membership.append(True)
            changed = execute('destroy', 'destroy-membership-race', confirmation=impact['confirmation'])
            self.assertEqual(changed['reason'], 'stale_target', changed)
            self.assertFalse(calls)
            tmux('unlink-window', '-t', 'two:4')
            unknown = execute('destroy', 'destroy-shared', confirmation=impact['confirmation'])
            self.assertEqual(unknown['phase'], 'uncertain', unknown)
            retry = execute('destroy', 'destroy-shared', confirmation=impact['confirmation'])
            self.assertEqual(retry['operation_id'], unknown['operation_id'])
            retained = ControllerRuntime(directory).local_tab_result(unknown['operation_id'])
            self.assertEqual(retained['result']['operation']['phase'], 'uncertain')
            self.assertEqual(calls, ["kill-window -t '$0:2'"])
            self.assertNotIn(window, tmux('list-windows', '-a', '-F', '#{window_id}').splitlines())

    def test_generated_contract_mcp_api_help_and_completion_agree(self):
        from codex_wake.tab_contract import tool_specs,cli_verb
        from codex_wake.controller_http import TOOLS
        from codex_wake.mcp_server import SPECS
        from codex_wake.command_contract import public_tools,coverage_report
        from codex_wake.cli import build_parser
        from codex_wake.completion import candidates
        from jsonschema import Draft202012Validator
        parser=build_parser()
        canonical=public_tools()
        for tool,spec in tool_specs().items():
            operation=spec[1]
            with self.subTest(operation=operation):
                self.assertEqual(TOOLS[tool],canonical[tool])
                self.assertEqual(SPECS[tool][3],canonical[tool][1]['properties'])
                Draft202012Validator.check_schema(TOOLS[tool][1])
                verb=cli_verb(operation)
                self.assertIn(verb,candidates(['tabs',''],1,parser=parser))
        flags=candidates(['tabs','input','--'],2,parser=parser)
        self.assertIn('--pane',flags)
        self.assertIn('--request-id',flags)
        self.assertNotIn('--retire-source',flags)
        report=coverage_report(parser)
        self.assertFalse([name for name in report['deferred_commands'] if name.startswith('tabs.')])
        self.assertEqual(report['tab_capabilities']['selected_profile_create']['status'],'conditional')

    def test_typed_cli_real_tmux_uses_same_user_without_grants_and_retains_result(self):
        import tempfile,shutil
        from pathlib import Path
        if not shutil.which('tmux'):self.skipTest('tmux unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);socket=str(root/'tmux.sock')
            subprocess.run(['tmux','-S',socket,'new-session','-d','-s','fixture','sleep 60'],check=True)
            config=root/'controller-tabs.json'
            config.write_text(json.dumps(dict(schema_version=1,workspaces={'work':dict(kind='tmux',socket_path=socket,session_id='$0')})))
            config.chmod(0o600)
            def cli(*args,expected=0):
                result=subprocess.run([sys.executable,'-m','codex_wake.entrypoint','--wake-root',directory,'tabs',*args,'--json'],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
                return json.loads(result.stdout)
            try:
                created=cli('create','--workspace','work','--name','ordinary','--cwd',directory,'--request-id','create-1')
                self.assertEqual(created['result']['operation']['result']['status'],'applied')
                retried=cli('create','--workspace','work','--name','ordinary','--cwd',directory,'--request-id','create-1')
                self.assertEqual(retried['result']['operation']['operation_id'],'tab-cli-create-1')
                shown=cli('show','--workspace','work','--selector','ordinary')
                self.assertEqual(len(shown['resources']),1)
                self.assertEqual(cli('result','--request-id','create-1')['result']['operation']['phase'],'terminal')
                held=cli('show','--workspace','work','--selector','missing',expected=2)
                self.assertEqual(held['error']['code'],'target_not_found')
                conflict=cli('create','--workspace','work','--name','different','--request-id','create-1',expected=2)
                self.assertEqual(conflict['error']['code'],'idempotency_conflict')
                subprocess.run(['tmux','-S',socket,'new-window','-d','-n','ordinary','sleep 60'],check=True)
                ambiguous=cli('show','--workspace','work','--selector','ordinary',expected=2)
                self.assertEqual(ambiguous['error']['code'],'ambiguous_target')
                stale=cli('create','--workspace','work','--name','must-not-exist','--expected-target',json.dumps(created['result']['operation']['target']),'--request-id','stale-1',expected=3)
                self.assertEqual(stale['result']['operation']['reason'],'stale_target')
            finally:
                subprocess.run(['tmux','-S',socket,'kill-server'],capture_output=True)
