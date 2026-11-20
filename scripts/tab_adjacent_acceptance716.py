#!/usr/bin/env python3
"""Focused installed CLI/SDK-MCP placement journey; reuses native recovery acceptance setup."""
import argparse
import asyncio
import hashlib
import http.server
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    import codex_wake
    from codex_wake.native_protocol import native_request
    from codex_wake.process import process_identity
    from codex_wake.native_clock import configuration
    from codex_wake.tab_traits import session_rows
    clock_config = configuration()
    assert clock_config, 'Existing StableTime client configuration required for local authority'
    prefix = Path(sys.prefix).resolve()
    package = Path(codex_wake.__file__).resolve().parent
    assert package.is_relative_to(prefix) and not os.environ.get('PYTHONPATH')
    with zipfile.ZipFile(args.wheel) as wheel:
        members = [n for n in wheel.namelist() if n.endswith('.py')]
        assert all((package.parent / n).read_bytes() == wheel.read(n) for n in members)
    report = dict(status='running', source_commit=args.source, prefix=str(prefix),
                  wheel_sha256=hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
                  native_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                  python_members_verified=len(members), checks=[], provider_turns=0,
                  production_touched=False, tier='focused', budget_seconds=180)
    calls = []
    class Trap(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.command)
            self.send_response(503)
            self.end_headers()
        do_POST = do_GET
        def log_message(self, *unused):
            pass
    trap = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Trap)
    threading.Thread(target=trap.serve_forever, daemon=True).start()
    daemon = None
    owned = {}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='w716-') as directory:
        root = Path(directory)
        home = root / 'accounts/codex-test'
        home.mkdir(parents=True, mode=0o700)
        wake = root / 'wake'
        wake.mkdir(mode=0o700)
        workspace = root / 'work'
        workspace.mkdir()
        subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
        endpoint = 'unix://' + str(root / 'native.sock')
        mux = str(root / 'tmux.sock')
        url = 'http://127.0.0.1:' + str(trap.server_port)
        env = {k: os.environ[k] for k in ('PATH', 'LANG') if k in os.environ}
        env.update(HOME=str(root / 'house'), CODEX_HOME=str(home), TERM='xterm-256color',
                   HTTP_PROXY=url, HTTPS_PROXY=url, ALL_PROXY=url,
                   NO_PROXY='localhost,127.0.0.1', CODEX_BUILD_UPDATE_CHECK='0',
                   CODEX_WAKE_STABLE_TIME_CONFIG=clock_config)
        catalog = json.loads(args.catalog.read_text())
        (home / 'models.json').write_text(json.dumps(catalog))
        (home / 'config.toml').write_text(
            'model=' + json.dumps(catalog['models'][0]['slug']) + '\nmodel_provider="placement_fixture"\n'
            'model_catalog_json=' + json.dumps(str(home / 'models.json')) + '\ncheck_for_update_on_startup=false\n'
            '[analytics]\nenabled=false\n[model_providers.placement_fixture]\nname="No inference"\n'
            'base_url=' + json.dumps(url + '/no-turns') + '\nwire_api="responses"\nrequires_openai_auth=false\n'
            '[projects.' + json.dumps(str(workspace)) + ']\ntrust_level="trusted"\n')
        def tmux(*argv, check=True):
            return subprocess.run(['tmux', '-S', mux, *argv], env=env, text=True,
                                  capture_output=True, check=check, timeout=8).stdout.strip()
        def cli(*argv, expected=0):
            value = subprocess.run([str(prefix / 'bin/codex-wake'), '--wake-root', str(wake),
                                    'tabs', *argv, '--json'], env=env, cwd=directory,
                                   text=True, capture_output=True, timeout=30)
            assert value.returncode == expected, (argv, value.stdout, value.stderr)
            return json.loads(value.stdout)
        def operation(value):
            return value['result']['operation']
        def rpc(method, params):
            return native_request(endpoint, str(args.binary), method, params, 5)
        def roster():
            return cli('list')['resources']
        def bindings():
            view = session_rows(wake, socket_path=mux, endpoints=[endpoint], deadline=time.monotonic()+5)
            return {row['thread_id']: sorted(a['pane_id'] for a in row.get('attachments', []))
                    for row in view['sessions'] if row['thread_id'] in ids}
        try:
            with (root / 'native.log').open('wb') as log:
                daemon = subprocess.Popen([str(args.binary), 'app-server', '--listen', endpoint],
                                          env=env, cwd=workspace, stdout=log, stderr=log)
            owned[daemon.pid] = process_identity(daemon.pid)
            until = time.monotonic() + 15
            while not (root / 'native.sock').exists():
                assert daemon.poll() is None and time.monotonic() < until, 'native startup failed'
                time.sleep(.05)
            endpoint = 'unix://' + str((root / 'native.sock').resolve(strict=True))
            control = home / 'app-server-control'
            control.mkdir(mode=0o700, exist_ok=True)
            (control / 'app-server-control.sock').symlink_to(root / 'native.sock')
            (wake / 'controller-accounts.toml').write_text(
                '[profiles]\nstate_root=' + json.dumps(str(home.parent)) + '\nknown_profiles=["test"]\nshared_links=[]\n'
                '[accounts]\nenabled=["codex-test"]\n')
            config = wake / 'controller-tabs.json'
            config.write_text(json.dumps(dict(schema_version=1, workspaces=dict(fixture=dict(
                kind='tmux', socket_path=mux, session_id='$0')))))
            config.chmod(0o600)
            tmux('new-session', '-d', '-s', 'fixture', '-n', 'notes', '-x', '140', '-y', '45', 'exec sleep 180')
            tmux('set-option', '-g', 'automatic-rename', 'off')
            ids = []
            windows = []
            for i in range(3):
                identifier = str(uuid.uuid4())
                ids.append(identifier)
                # Deliberately synthetic fixed history time; not a trusted-time measurement.
                stamp = '2026-11-20T00:00:00Z'
                rollout = home / 'sessions/2026/11/20' / ('rollout-2026-11-20T00-00-00-' + identifier + '.jsonl')
                rollout.parent.mkdir(parents=True, exist_ok=True)
                meta = dict(id=identifier, session_id=identifier, timestamp=stamp, cwd=str(workspace),
                            originator='codex_cli_rs', cli_version='0.169.0', source='cli',
                            model_provider='placement_fixture', base_instructions={'text': 'Synthetic provider-free placement acceptance.'})
                rollout.write_text(json.dumps(dict(timestamp=stamp, type='session_meta', payload=meta))+'\n')
                rpc('thread/resume', dict(threadId=identifier))
                rpc('thread/name/set', dict(threadId=identifier, name='native-'+str(i)))
                command = shlex.join([str(args.binary), '--remote', endpoint, 'resume', identifier, '--no-alt-screen'])
                windows.append(tmux('new-window', '-d', '-P', '-F', '#{window_id}', '-n', 'native-'+str(i),
                                    '-c', str(workspace), command))
            tmux('select-window', '-t', windows[0])
            until = time.monotonic() + 20
            while True:
                initial_bindings = bindings()
                if len(initial_bindings) == 3 and all(initial_bindings.values()):
                    break
                assert time.monotonic() < until, 'native bindings unavailable'
                time.sleep(.1)
            before = roster()
            births = {r['window']['window_id']: [(p['pane_id'], p['pid'], p['process_generation'])
                      for p in r['window']['panes']] for r in before}
            for values in births.values():
                for _, pid, identity in values:
                    owned[pid] = identity
            anchor, _, companion = windows
            target_index = next(r['window']['index'] for r in before if r['window']['window_id'] == anchor)+1
            preview = operation(cli('move', '--workspace', 'fixture', '--window', companion,
                                    '--destination', 'fixture', '--index', str(target_index), '--dry-run', '--request-id', 'preview'))
            assert preview['result']['status'] == 'preview', preview
            assert not preview['result']['requires_force'], preview
            tmux('select-pane', '-t', '@0', '-T', 'owned unrelated display activity')
            moved = operation(cli('move', '--workspace', 'fixture', '--window', companion,
                                  '--destination', 'fixture', '--index', str(target_index), '--request-id', 'place'))
            assert moved['execution'] == 'completed' and moved['result']['status'] == 'applied', moved
            assert operation(cli('result', '--request-id', 'place')) == moved
            assert operation(cli('move', '--workspace', 'fixture', '--window', companion,
                                 '--destination', 'fixture', '--index', str(target_index), '--request-id', 'place')) == moved
            report['checks'].append('installed-cli-no-force-native-adjacency-retained-result-and-replay')
            async def mcp_journey():
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
                params = StdioServerParameters(command=str(prefix/'bin/codex-wake-mcp'),
                    args=['--wake-root', str(wake)], env=env)
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        async def call(name, arguments):
                            result = await session.call_tool(name, arguments)
                            return json.loads(result.content[0].text)
                        listed = await call('wake_tabs_list', {})
                        pin = listed['result']['resources'][0]['lifecycle_target']
                        def request(key, index):
                            return dict(workspace='fixture', window=companion, destination='fixture', index=index,
                                expected_target=pin, expected_destination=pin, preview=True,
                                _request=dict(operation_id=key, idempotency_key=key, correlation_id=key,
                                              binding='acceptance716', target=pin))
                        tmux('select-pane', '-t', '@0', '-T', 'after MCP discovery')
                        args_preview = request('mcp-preview', 3)
                        assert operation(await call('wake_tabs_move', args_preview))['result']['status'] == 'preview'
                        args_apply = request('mcp-apply', 3)
                        args_apply['preview'] = False
                        applied = operation(await call('wake_tabs_move', args_apply))
                        assert applied['result']['status'] == 'applied', applied
                        assert operation(await call('wake_tabs_move', args_apply)) == applied
                        stale = operation(await call('wake_tabs_move', request('mcp-stale-layout', 2)))
                        assert stale['phase'] == 'uncertain' and stale['reason'] == 'stale_target', stale
                        fresh = await call('wake_tabs_list', {})
                        pin = fresh['result']['resources'][0]['lifecycle_target']
                        final = request('mcp-adjacent', target_index)
                        final['preview'] = False
                        assert operation(await call('wake_tabs_move', final))['result']['status'] == 'applied'
            asyncio.run(mcp_journey())
            report['checks'].append('actual-installed-sdk-mcp-metadata-stable-preview-apply-replay-and-stale-layout-refusal')
            after = roster()
            assert bindings() == initial_bindings
            order = [r['window']['window_id'] for r in sorted(after, key=lambda r:r['window']['index'])]
            assert order[order.index(anchor)+1] == companion
            assert [r['window']['window_id'] for r in after if r['window']['focused']] == [anchor]
            assert {r['window']['window_id']: [(p['pane_id'], p['pid'], p['process_generation'])
                    for p in r['window']['panes']] for r in after} == births
            assert [r['window']['window_id'] for r in before if r['window']['window_id'] != companion] == [w for w in order if w != companion]
            report['checks'].append('both-native-conversation-bindings-pane-births-focus-and-unrelated-order-preserved')
            report['conversation_bindings_verified'] = 3
            report['status'] = 'PASS'
        except BaseException as error:
            report.update(status='FAIL', error=str(error)[:3000])
            raise
        finally:
            tmux('kill-server', check=False)
            if daemon:
                daemon.terminate()
                try:
                    daemon.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait(timeout=5)
            trap.shutdown()
            trap.server_close()
            until = time.monotonic()+5
            while any(process_identity(pid) == identity for pid, identity in owned.items()) and time.monotonic()<until:
                time.sleep(.05)
            report['owned_processes_remaining'] = [pid for pid, identity in owned.items() if process_identity(pid) == identity]
            report['owned_environment_processes_remaining'] = []
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit():
                    continue
                try:
                    if ('CODEX_HOME='+str(home)).encode() in (proc/'environ').read_bytes().split(b'\0'):
                        report['owned_environment_processes_remaining'].append(int(proc.name))
                except OSError:
                    pass
            report['trap_requests'] = calls
            report['elapsed_seconds'] = round(time.monotonic()-started, 3)
            report['budget_breach'] = report['elapsed_seconds'] > report['budget_seconds']
            report['owned_namespace_removed'] = subprocess.run(
                ['tmux', '-S', mux, 'list-sessions'], capture_output=True, timeout=5).returncode != 0
            if calls or report['owned_processes_remaining'] or report['owned_environment_processes_remaining'] or report['budget_breach']:
                report['status'] = 'FAIL'
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['status']=='PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
