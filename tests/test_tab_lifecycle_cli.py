import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class LifecycleCLITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('tmux'), 'tmux unavailable')
    def test_cli_and_mcp_move_preview_accept_public_lifecycle_targets(self):
        from codex_wake.cli import run
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory(prefix='wake719-') as directory:
            root = Path(directory)
            socket = root / 'mux.sock'
            wake = root / 'wake'
            wake.mkdir(mode=0o700)
            def tmux(*args):
                return subprocess.check_output(['tmux', '-S', str(socket), *args], text=True).strip()
            tmux('new-session', '-d', '-s', 'source', '-n', 'anchor', 'sleep 120')
            self.addCleanup(subprocess.run, ['tmux', '-S', str(socket), 'kill-server'], capture_output=True)
            window = tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-t', 'source:', '-n', 'companion', 'sleep 120')
            tmux('new-session', '-d', '-s', 'destination', '-n', 'other', 'sleep 120')
            config = wake / 'controller-tabs.json'
            config.write_text(json.dumps(dict(schema_version=1, workspaces={
                name: dict(kind='tmux', socket_path=str(socket), session_id=sid)
                for name, sid in [('source', '$0'), ('destination', '$1')]})))
            config.chmod(0o600)
            runner = CommandRunner(wake_root=wake)
            def rows():
                value, failed = runner.call('wake_tabs_list', {})
                self.assertFalse(failed, value)
                return {row['target']['workspace']: row for row in value['result']['resources']}
            def preview(pins, field, request):
                target = pins['source'][field]
                value, failed = runner.call('wake_tabs_move', dict(
                    workspace='source', window=window, destination='destination', index=1,
                    expected_target=target, expected_destination=pins['destination'][field], preview=True,
                    _request=dict(operation_id=request, idempotency_key=request,
                                  correlation_id=request, binding='fixture', target=target)))
                return value, failed
            pins = rows()
            value, failed = preview(pins, 'target', 'fresh-discovery')
            self.assertFalse(failed, value)
            self.assertEqual(value['result']['operation']['execution'], 'completed', value)
            self.assertEqual(value['result']['operation']['result']['status'], 'preview')
            pins = rows()
            tmux('select-pane', '-t', window, '-T', 'coding activity changed')
            tmux('select-pane', '-t', 'destination:', '-T', 'destination activity changed')
            value, failed = preview(pins, 'lifecycle_target', 'stable-discovery')
            self.assertFalse(failed, value)
            self.assertEqual(value['result']['operation']['execution'], 'completed', value)
            self.assertEqual(value['result']['operation']['result']['status'], 'preview')
            with patch.dict(os.environ, {'CODEX_WAKE_ROOT': str(wake)}), contextlib.redirect_stdout(io.StringIO()) as output:
                code = run(['tabs', 'move', '--workspace', 'source', '--window', window,
                            '--destination', 'destination', '--index', '1', '--dry-run', '--json'])
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['result']['operation']['result']['status'], 'preview')
            tmux('new-window', '-d', '-t', 'destination:', '-n', 'manual-change', 'sleep 120')
            value, failed = preview(pins, 'lifecycle_target', 'changed-placement')
            self.assertEqual(value['result']['operation']['phase'], 'uncertain', value)
            self.assertEqual(value['result']['operation']['reason'], 'stale_target')

    def test_ordinary_local_cli_creates_and_renames_without_grant_files(self):
        if not shutil.which('tmux'):self.skipTest('tmux unavailable')
        from codex_wake.cli import run
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);socket=root/'mux.sock'
            subprocess.run(['tmux','-S',str(socket),'new-session','-d','-s','fixture','-n','source','sleep 90'],check=True)
            self.addCleanup(subprocess.run,['tmux','-S',str(socket),'kill-server'],capture_output=True)
            env={'TMUX':str(socket)+',1,0','CODEX_WAKE_ROOT':str(root/'wake')}
            def cli(*args):
                output=io.StringIO()
                with patch.dict(os.environ,env), contextlib.redirect_stdout(output):code=run(['tabs',*args,'--json'])
                self.assertEqual(code,0,output.getvalue())
                return json.loads(output.getvalue())
            rows=cli('list')['resources'];workspace=next(r['target']['workspace'] for r in rows if r['window']['name']=='source')
            created=cli('create','--workspace',workspace,'--name','created','--cwd',directory)
            op=created['result']['operation'];self.assertEqual(op['execution'],'completed',created)
            window=op['result']['window']['window_id']
            cli('rename','--workspace',workspace,'--window',window,'--name','renamed')
            rows=cli('list')['resources']
            self.assertTrue(any(r['window']['name']=='renamed' for r in rows))
            self.assertFalse((root/'wake/controller-messaging.json').exists())
            from codex_wake.mcp_server import CommandRunner
            target=next(r['target'] for r in rows if r['target']['workspace']==workspace)
            payload=dict(workspace=workspace,window=window,name='native-mcp-renamed',expected_target=target)
            payload['_request']=dict(operation_id='native-rename',idempotency_key='native-rename',correlation_id='native-rename',binding='fixture',target=target)
            with patch.dict(os.environ,env):
                native,failed=CommandRunner(wake_root=root/'wake').call('wake_tabs_rename',payload)
            self.assertFalse(failed,native)
            self.assertEqual(native['result']['operation']['execution'],'completed',native)
