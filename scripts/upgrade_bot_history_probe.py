#!/usr/bin/env python3
"""Exact-package private profile/history compatibility; no managed-daemon cutover."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from uuid import uuid4


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def settings(root):
    from codex_profiles.config import Settings
    return Settings(state_root=root/'homes', source_root=root/'homes', account_prefix='',
                    known_profiles=('default', 'account', 'shared'))


def disposable_lab():
    if os.getuid() == 1017:
        return Path('/home/codex-daemon-test/codex-profile-lab')
    if os.getuid() == 1000 and os.environ.get('WSL_DISTRO_NAME') == 'wsl-test':
        return Path('/home/ubuntu/codex-profile-lab')
    raise RuntimeError('designated disposable test environment required')


def child(argv):
    root, profile, operation = Path(argv[0]), argv[1], argv[2]
    lab = disposable_lab()
    if root.resolve() == lab or not root.resolve().is_relative_to(lab):
        raise RuntimeError('owned qualification child required')
    from codex_profiles.build_channels import load_build, run_build
    from codex_profiles.history import resume
    value = json.loads((root/'sessions.json').read_text())
    home = settings(root).account_root(profile)
    manifest = root/('incompatible.json' if operation == 'incompatible' else 'builds.json')
    if operation == 'failed-start':
        return run_build(load_build(manifest, 'modded', home), home, profile,
                         ['--codex-upgrade-qualification-invalid-option'])
    return resume(settings(root), value[profile]['thread_id'], manifest, owner=profile)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'baseline', 'root', 'wake-prefix'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--models', type=Path)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args(argv)
    try:
        lab = disposable_lab()
    except RuntimeError as error:
        parser.error(str(error))
    root = args.root.resolve()
    if root == lab or not root.is_relative_to(lab) or not 1 <= args.timeout <= 600:
        parser.error('bounded owned disposable child root required')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o022 or (root/'receipt.json').exists():
        parser.error('fresh private owned evidence root required')
    import pyte
    from codex_profiles.history import discover

    binary = (args.package/'bin/codex').resolve(strict=True)
    baseline = (args.baseline/'bin/codex').resolve(strict=True)
    models = args.models or args.wake_prefix.parent/'models.json'
    model = json.loads(models.read_text())['models'][0]
    python = str(args.wake_prefix/'bin/python')
    start = time.monotonic()
    deadline = start+args.timeout
    report = dict(schema_version=1, status='failed', native_sha256=sha(binary),
                  baseline_sha256=sha(baseline), checks={}, model_requests=0,
                  external_provider_requests=0, scripted_provider_requests=0,
                  owned_processes_remaining=[], scope='private profile launch/history compatibility; no managed-daemon recovery',
                  root=str(root), started_at=time.time(), harness_sha256=sha(Path(__file__)),
                  rollback_scope='private registered-build compatibility; public UpgradeJobs.rollback remains post-promotion acceptance',
                  failed_start_injection='invalid CLI option on exact registered candidate, followed by successful native profile resume')
    calls, blocked, processes, sessions = [], [], [], {}

    class LocalOnly(BaseHTTPRequestHandler):
        def log_message(self, *_unused):
            pass

        def do_CONNECT(self):
            blocked.append(self.path)
            self.send_error(503)

        def do_GET(self):
            blocked.append(self.path)
            self.send_error(503)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if not self.path.endswith('/responses') or len(calls) >= 12:
                blocked.append(self.path)
                self.send_error(503)
                return
            text = json.dumps(body)
            token = next((v['token'] for v in sessions.values() if v['token'] in text), 'SYNTHETIC_HISTORY')
            calls.append({'path': self.path, 'token': token})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            events = [
                {'type': 'response.created', 'response': {'id': 'owned-history'}},
                {'type': 'response.output_item.done', 'item': {'type': 'message', 'id': 'owned-message', 'role': 'assistant',
                  'content': [{'type': 'output_text', 'text': token}]}},
                {'type': 'response.completed', 'response': {'id': 'owned-history', 'usage': {
                    'input_tokens': 5, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens': 2, 'total_tokens': 7}}},
            ]
            for event in events:
                self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode())
                self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), LocalOnly)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proxy = 'http://127.0.0.1:'+str(server.server_port)
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'WSL_DISTRO_NAME')}
    operator_home = root/'operator-home'
    operator_home.mkdir(mode=0o700)
    env.update(HOME=str(operator_home), XDG_CONFIG_HOME=str(operator_home/'.config'), XDG_DATA_HOME=str(operator_home/'.local/share'),
               XDG_STATE_HOME=str(operator_home/'.local/state'), TERM='xterm-256color', PYTHONDONTWRITEBYTECODE='1',
               HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy, NO_PROXY='127.0.0.1,localhost')

    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError('private history qualification deadline')

    def stop(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def register(executable):
        value = dict(schema_version=1, builds={'modded': dict(executable=str(executable), sha256=sha(executable),
                     upstream_version='0.166.0' if executable == binary else '0.165.0', revision='qualified-private-history',
                     source='actual complete package under qualification', read_schemas=[5], backend='private')})
        path = root/'builds.json'
        temporary = root/'builds.next'
        temporary.write_text(json.dumps(value))
        temporary.replace(path)

    def native_pid(parent, expected):
        pending = [parent]
        seen = set()
        while pending:
            parent = pending.pop()
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit() or int(proc.name) in seen:
                    continue
                try:
                    fields = (proc/'stat').read_text().rsplit(')', 1)[1].split()
                    if int(fields[1]) != parent:
                        continue
                    seen.add(int(proc.name))
                    pending.append(int(proc.name))
                    if sha(proc/'exe') == expected:
                        return int(proc.name)
                except (OSError, ValueError, IndexError):
                    pass
        return None

    def show(profile, label, lock=False):
        check()
        selected = json.loads((root/'builds.json').read_text())['builds']['modded']
        master, slave = pty.openpty()
        import fcntl
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 180, 0, 0))
        def setup():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        command = [python, '-I', '-B', str(Path(__file__).resolve()), '--profile-child', str(root), profile, 'resume']
        process = subprocess.Popen(command, env=env, cwd=root, stdin=slave, stdout=slave, stderr=slave, preexec_fn=setup)
        processes.append(process)
        os.close(slave)
        os.set_blocking(master, False)
        screen = pyte.Screen(180, 45)
        stream = pyte.ByteStream(screen)
        until = min(deadline, time.monotonic()+30)
        captured = bytearray()
        try:
            while time.monotonic() < until:
                check()
                if select.select([master], [], [], .05)[0]:
                    try:
                        data = os.read(master, 65536)
                    except BlockingIOError:
                        continue
                    captured.extend(data)
                    stream.feed(data)
                    if b'\x1b[6n' in data:
                        os.write(master, f'\x1b[{screen.cursor.y+1};{screen.cursor.x+1}R'.encode())
                    if b'\x1b[c' in data:
                        os.write(master, b'\x1b[?1;2c')
                visible = '\n'.join(screen.display)
                actual = native_pid(process.pid, selected['sha256'])
                if sessions[profile]['token'] in visible and actual:
                    if lock:
                        other = subprocess.run(command, env=env, cwd=root, capture_output=True, text=True, timeout=10)
                        assert other.returncode != 0 and 'tenant already has a private build client' in other.stderr, other.stderr
                        assert str(process.pid) in other.stderr, 'lock refusal must identify actual owner'
                        report['checks']['private_client_ownership'] = True
                    report.setdefault('launches', []).append(dict(label=label, profile=profile, thread_id=sessions[profile]['thread_id'],
                        executable_sha256=sha(Path('/proc', str(actual), 'exe')), actual_pid=actual, visible_history=True))
                    return
                if process.poll() is not None:
                    raise RuntimeError(label+' launcher exited: '+captured.decode(errors='replace')[-1600:])
            raise TimeoutError(label+' did not show saved history: '+captured.decode(errors='replace')[-1600:])
        finally:
            stop(process)
            os.close(master)
            (root/(label+'.terminal')).write_bytes(captured)

    def unchanged():
        for value in sessions.values():
            assert Path(value['rollout']).read_bytes().startswith(bytes.fromhex(value['prefix'])), 'saved history was rewritten'
        found = discover(settings(root))
        assert found['status'] == 'complete', found
        assert {(v['profile'], v['thread_id']) for v in found['sessions']} == {(k, v['thread_id']) for k, v in sessions.items()}, found

    try:
        for profile in settings(root).known_profiles:
            home = settings(root).account_root(profile)
            home.mkdir(parents=True, mode=0o700)
            token = 'QUAL_HISTORY_'+profile+'_'+uuid4().hex[:8]
            sessions[profile] = dict(token=token)
            (home/'models.json').write_text(json.dumps({'models': [model]}))
            (home/'config.toml').write_text('model='+json.dumps(model['slug'])+'\nmodel_provider="qualification_local"\nmodel_catalog_json='+json.dumps(str(home/'models.json'))+'\ncheck_for_update_on_startup=false\napproval_policy="never"\n[analytics]\nenabled=false\n[model_providers.qualification_local]\nname="Owned synthetic history, no inference"\nbase_url='+json.dumps(proxy+'/v1')+'\nwire_api="responses"\nrequires_openai_auth=false\nsupports_websockets=false\nrequest_max_retries=0\nstream_max_retries=0\n[projects.'+json.dumps(str(root))+']\ntrust_level="trusted"\n')
            native_env = dict(env, HOME=str(home), CODEX_HOME=str(home))
            with (root/(profile+'.seed.log')).open('wb') as log:
                process = subprocess.Popen([str(baseline), 'app-server'], env=native_env, cwd=root,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, start_new_session=True)
                processes.append(process)
                pending = b''
                counter = 0
                frames = []
                def receive():
                    nonlocal pending
                    until = min(deadline, time.monotonic()+15)
                    while time.monotonic() < until:
                        check()
                        if b'\n' in pending:
                            line, pending = pending.split(b'\n', 1)
                            value = json.loads(line)
                            frames.append(value)
                            return value
                        if select.select([process.stdout], [], [], .05)[0]:
                            data = os.read(process.stdout.fileno(), 65536)
                            if not data:
                                raise RuntimeError('owned seed stdio app-server closed')
                            pending += data
                            if len(pending) > 1024*1024:
                                raise RuntimeError('owned seed frame exceeds bound')
                        elif process.poll() is not None:
                            raise RuntimeError('owned seed app-server exited')
                    raise TimeoutError('owned seed response deadline')
                def rpc(method, params):
                    nonlocal counter
                    counter += 1
                    identifier = counter
                    process.stdin.write((json.dumps(dict(id=identifier, method=method, params=params))+'\n').encode())
                    process.stdin.flush()
                    while True:
                        value = receive()
                        if value.get('id') == identifier:
                            if 'error' in value:
                                raise RuntimeError(method+' rejected: '+str(value['error']))
                            return value['result']
                try:
                    initialized = rpc('initialize', dict(clientInfo=dict(name='upgrade_history_qualification', version='1'),
                                                        capabilities=dict(experimentalApi=True)))
                    assert initialized.get('codexHome') == str(home), 'native seed home identity mismatch'
                    process.stdin.write(b'{"method":"initialized"}\n')
                    process.stdin.flush()
                    thread = rpc('thread/start', dict(cwd=str(root)))['thread']
                    tid = thread['id']
                    turn_id = rpc('turn/start', dict(threadId=tid, input=[dict(type='text', text=token)]))['turn']['id']
                    while True:
                        event = receive()
                        params = event.get('params', {})
                        completed = params.get('turn', {})
                        if (event.get('method') == 'turn/completed' and params.get('threadId') == tid
                                and completed.get('id') == turn_id):
                            if completed.get('status') != 'completed':
                                raise RuntimeError('owned seed turn did not complete successfully')
                            break
                    value = rpc('thread/read', dict(threadId=tid, includeTurns=False))['thread']
                    rollout = Path(value['path'])
                    sessions[profile].update(thread_id=tid, rollout=str(rollout), prefix=rollout.read_bytes().hex())
                finally:
                    stop(process)
                    process.stdin.close()
                    process.stdout.close()
                    (root/(profile+'.seed-frames.json')).write_text(json.dumps(frames, indent=2))
        (root/'sessions.json').write_text(json.dumps(sessions))
        before_turns = len(calls)
        assert before_turns >= 3, 'synthetic seed requests unproved'
        register(baseline)
        unchanged()
        for profile in sessions:
            show(profile, 'baseline-'+profile)
        register(binary)
        for profile in sessions:
            show(profile, 'candidate-'+profile, lock=profile == 'default')
        unchanged()
        show('default', 'reconnect-candidate')
        before_failure = {k: Path(v['rollout']).read_bytes() for k, v in sessions.items()}
        failed = subprocess.run([python, '-I', '-B', str(Path(__file__).resolve()), '--profile-child', str(root), 'default', 'failed-start'],
                                env=env, cwd=root, capture_output=True, text=True, timeout=10)
        assert failed.returncode != 0 and 'unexpected argument' in failed.stderr, failed.stderr
        assert all(Path(sessions[k]['rollout']).read_bytes() == v for k, v in before_failure.items()), 'failed start changed history'
        show('default', 'recovered-candidate')
        incompatible = json.loads((root/'builds.json').read_text())
        incompatible['builds']['modded']['read_schemas'] = [999]
        (root/'incompatible.json').write_text(json.dumps(incompatible))
        held = subprocess.run([python, '-I', '-B', str(Path(__file__).resolve()), '--profile-child', str(root), 'default', 'incompatible'],
                              env=env, cwd=root, capture_output=True, text=True, timeout=10)
        assert held.returncode != 0 and 'history compatibility is unqualified' in held.stderr, held.stderr
        register(baseline)
        for profile in sessions:
            show(profile, 'rollback-'+profile)
        unchanged()
        assert len(calls) == before_turns, 'profile qualification submitted an unintended turn'
        report['checks'].update(history_visibility=True, failed_start_recovery=True, compatible_rollback=True,
                                reconnect=True, incompatible_history_refused=True)
        report['status'] = 'passed'
    except Exception as error:
        report['reason'] = type(error).__name__+': '+str(error)
    finally:
        for process in processes:
            stop(process)
        server.shutdown()
        server.server_close()
        remaining = []
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit() or int(proc.name) == os.getpid():
                continue
            try:
                values = (proc/'environ').read_bytes().split(b'\0')
                home = next((os.fsdecode(v[11:]) for v in values if v.startswith(b'CODEX_HOME=')), '')
                if home and Path(home).is_relative_to(root):
                    remaining.append(int(proc.name))
            except (OSError, ValueError):
                pass
        report.update(scripted_provider_requests=len(calls), blocked_background_attempts=blocked,
                      owned_processes_remaining=remaining, finished_at=time.time(), elapsed_seconds=time.monotonic()-start)
        if remaining:
            report.update(status='failed', reason='owned history process survived teardown')
        (root/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--profile-child':
        raise SystemExit(child(sys.argv[2:]))
    raise SystemExit(main())
