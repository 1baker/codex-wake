"""Pinned local build launches that cannot attach to the shared daemon.

The registration manifest is a host trust input, not upstream signature proof.
This module verifies registered bytes; actual account identity remains unverified
until a native account observation is available. Same-home launches serialize
until native multi-backend database ownership is qualified.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import select
import shlex
import socket
import struct
import time
from urllib.parse import urlparse
import stat
import subprocess
import sys
import tempfile
from typing import Iterator, TextIO
from .config import account_environment
from . import __version__


class BuildError(ValueError):
    """Launch cannot establish the selected build or safe ownership."""


@dataclass(frozen=True)
class Build:
    channel: str
    executable: Path
    sha256: str
    upstream_version: str
    revision: str
    source: str
    read_schemas: tuple[int, ...] | None = None
    tenant_home: str | None = None
    backend: str = 'private'


def load_build(manifest: Path, channel: str = 'modded', account_home: Path | None = None) -> Build:
    if channel not in ('stock', 'modded'):
        raise BuildError('channel must be stock or modded')
    try:
        payload = json.loads(manifest.read_text())
        if payload.get('schema_version') != 1:
            raise BuildError('unsupported build manifest version')
        row = payload.get('builds', {}).get(channel)
        if account_home is not None:
            row = payload.get('tenants', {}).get(str(account_home.resolve()), {}).get('builds', {}).get(channel, row)
        if row is None:
            raise BuildError('selected build is not registered for this tenant')
        path = Path(row['executable'])
        if not path.is_absolute():
            raise BuildError('build executable must be absolute')
        digest = row['sha256']
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise BuildError('build SHA256 is invalid')
        fields = [row['upstream_version'], row['revision'], row['source']]
        if any(not isinstance(value, str) or not value or len(value) > 512
               or any(ord(c) < 32 for c in value) for value in fields):
            raise BuildError('build metadata is invalid')
        if channel == 'stock' and not row['source'].startswith('https://github.com/openai/codex/releases/download/'):
            raise BuildError('stock requires registered official release provenance')
        schemas = row.get('read_schemas')
        if schemas is not None and (not isinstance(schemas, list) or not schemas or any(type(value) is not int or value < 1 for value in schemas)):
            raise BuildError('registered history compatibility is invalid')
        backend = row.get('backend', 'private')
        if backend not in ('private', 'managed'):
            raise BuildError('registered backend must be private or managed')
        return Build(channel, path.resolve(strict=True), digest, *fields,
                     tuple(schemas) if schemas is not None else None, row.get('tenant_home'), backend)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BuildError('build registration is unavailable or invalid') from exc


@contextmanager
def _pinned_executable(build: Build) -> Iterator[int]:
    descriptor = os.open(build.executable, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
            raise BuildError('registered build is not an executable regular file')
        digest = hashlib.sha256()
        with os.fdopen(os.dup(descriptor), 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != build.sha256:
            raise BuildError('registered build bytes changed; launch held')
        yield descriptor
    finally:
        os.close(descriptor)


def _process_start_ticks(pid: int) -> str | None:
    try:
        # The comm field can contain spaces and parentheses.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _lock_owner(descriptor: int) -> str:
    try:
        record = json.loads(os.pread(descriptor, 4096, 0))
        pid = record.get('pid')
        ticks = record.get('start_ticks')
        if (type(pid) is int and pid > 0 and isinstance(ticks, str)
                and ticks == _process_start_ticks(pid)):
            channel = record.get('channel')
            suffix = f' (channel {channel})' if channel in ('stock', 'modded') else ''
            return f'recorded launcher PID {pid}{suffix}'
    except (OSError, ValueError, AttributeError):
        pass
    return 'launcher identity unavailable'


@contextmanager
def _home_ownership(home: Path, *, channel: str | None = None, build_sha256: str | None = None) -> Iterator[int]:
    if not home.is_dir() or home.is_symlink():
        raise BuildError('tenant home must be an existing real directory')
    if home.stat().st_uid != os.getuid():
        raise BuildError('tenant home must be owned by invoking user')
    path = home / '.build-channel.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise BuildError('tenant ownership lock is not private')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            owner = _lock_owner(descriptor)
            raise BuildError(
                'tenant already has a private build client; native concurrent-store safety is unqualified. '
                f'Account home: {home}; {owner}. '
                'Close the existing client for this account, then retry. '
                f'Inspect processes using its lock with: fuser -- {shlex.quote(str(path))}'
            ) from exc
        owner = dict(pid=os.getpid(), start_ticks=_process_start_ticks(os.getpid()), channel=channel)
        if build_sha256 is not None:owner['build_sha256']=build_sha256
        record = json.dumps(owner).encode()
        os.ftruncate(descriptor, 0)
        os.pwrite(descriptor, record, 0)
        yield descriptor
    finally:
        os.close(descriptor)


def validate_history(build: Build, home: Path) -> None:
    if build.tenant_home is not None and build.tenant_home != str(home.resolve()):
        raise BuildError('registered build belongs to another tenant')
    versions = set()
    for path in home.glob('state_*.sqlite'):
        match = re.fullmatch(r'state_(\d+)\.sqlite', path.name)
        if match is None:
            raise BuildError('unknown tenant history schema')
        versions.add(int(match.group(1)))
    if versions and (build.read_schemas is None or not versions.issubset(build.read_schemas)):
        raise BuildError('selected build history compatibility is unqualified for this tenant')


def inspect_account(build: Build, account_home: Path, *, timeout: float = 5.0, routing_url: str | None = None) -> dict:
    """Verify native initialization, retaining an explicit account-identity gap.

    Native account/read can perform remote workspace routing even with token
    refresh disabled. Do not invoke it here. Account identity needs a separately
    isolated routing fixture or an attested native observation.
    """
    home = account_home.absolute()
    if routing_url is not None:
        address = urlparse(routing_url)
        if (address.scheme != 'http' or address.hostname != '127.0.0.1' or not address.port
                or os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net')):
            raise BuildError('account fixture RPC requires loopback routing in an isolated network namespace')
    requests = [
        {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'codex-profiles', 'version': __version__}, 'capabilities': {'experimentalApi': True}}},
        {'method': 'initialized'},
    ]
    env = account_environment(home, home.name)
    with _home_ownership(home, channel=build.channel, build_sha256=build.sha256) as lock, _pinned_executable(build) as executable:
        validate_history(build, home)
        command = [f'/proc/self/fd/{executable}']
        if routing_url is not None:
            command += ['-c', 'chatgpt_base_url=' + json.dumps(routing_url)]
        process = subprocess.Popen([*command, 'app-server'], env=env,
                                   pass_fds=(executable, lock), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, start_new_session=True)
        pending = b''
        deadline = time.monotonic() + timeout

        def reply(request_id):
            nonlocal pending
            while time.monotonic() < deadline:
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(value, dict) and value.get('id') == request_id:
                        return value
                ready, _, _ = select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))
                if not ready:
                    break
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending += chunk
                if len(pending) > 1024 * 1024:
                    break
            return None

        try:
            process.stdin.write(json.dumps(requests[0]) + '\n')
            process.stdin.flush()
            initialized = reply(1)
            if not initialized or 'error' in initialized:
                return {'status': 'unverified', 'reason': 'native initialization unavailable'}
            native = initialized.get('result', {})
            if not isinstance(native, dict) or native.get('codexHome') != str(home):
                return {'status': 'unverified', 'reason': 'native home identity unavailable or mismatched'}
            runtime = {'codex_home': native['codexHome'], 'user_agent': native.get('userAgent')}
            if routing_url is not None:
                process.stdin.write(json.dumps({'method': 'initialized'}) + '\n')
                process.stdin.write(json.dumps({'id': 2, 'method': 'account/read', 'params': {'refreshToken': False}}) + '\n')
                process.stdin.flush()
                response = reply(2)
                result = response.get('result') if isinstance(response, dict) else None
                if isinstance(result, dict):
                    account = result.get('account')
                    if isinstance(account, dict):
                        return {'status': 'native_observed', 'native_runtime': runtime, 'account': {
                            key: account[key] for key in ('type', 'id', 'email', 'planType') if key in account}}
                    return {'status': 'unauthenticated', 'native_runtime': runtime, 'account': None}
                return {'status': 'unverified', 'native_runtime': runtime, 'reason': 'isolated native account read unavailable'}
            return {'status': 'unverified', 'reason': 'account identity requires isolated routing qualification',
                    'runtime_status': 'native_observed', 'native_runtime': runtime}
        except (BrokenPipeError, OSError):
            return {'status': 'unverified', 'reason': 'native account transport unavailable'}
        finally:
            if process.stdin:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()


def _managed_endpoint(build: Build, home: Path, executable: int, env: dict) -> str:
    """Bootstrap only an empty account or start the exact already-selected build."""
    selected = home / 'packages/app-server-daemon/current/bin/codex'
    control = home / 'app-server-control/app-server-control.sock'

    def lifecycle(verb: str, *args: str) -> dict:
        try:
            result = subprocess.run([f'/proc/self/fd/{executable}', 'app-server', 'daemon', verb, *args],
                                    env=env, pass_fds=(executable,), capture_output=True,
                                    text=True, timeout=100, check=False,
                                    umask=0o077 if build.channel == 'modded' else -1)
        except subprocess.TimeoutExpired as exc:
            raise BuildError(f'account daemon {verb} timed out; outcome is unknown; '
                             'inspect daemon status and package selection, then reconcile '
                             'before retrying or rolling back') from exc
        if result.returncode:
            raise BuildError(f'account daemon {verb} failed: {result.stderr.strip()}')
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except ValueError as exc:
            raise BuildError('account daemon returned an invalid lifecycle result') from exc

    if selected.exists():
        with selected.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != build.sha256:
            raise BuildError('account daemon uses a different build; explicitly qualify and upgrade or roll back before launching')
    else:
        if selected.is_symlink() or os.path.lexists(control):
            raise BuildError('account daemon selection is incomplete; inspect existing state before recovery')
        lifecycle('start')
        lifecycle('update', '--from-cli', '--yes')
    lifecycle('start')
    version = lifecycle('version')
    if version.get('status') != 'running' or version.get('socketPath') != str(control):
        raise BuildError('account daemon running endpoint is unverified')
    physical = control.resolve(strict=True)
    info = physical.lstat()
    parent = physical.parent.stat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
            or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
        raise BuildError('account daemon socket is not private and user-owned')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(5)
        peer.connect(str(physical))
        pid, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != os.getuid():
        raise BuildError('account daemon peer belongs to another user')
    with Path(f'/proc/{pid}/exe').open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != build.sha256:
        raise BuildError('account daemon peer does not match the registered build')
    marker = ('CODEX_HOME=' + str(home)).encode()
    if marker not in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
        raise BuildError('account daemon peer does not own the selected account home')
    return 'unix://' + str(physical)


def _inspect_version(
    build: Build, profile: str, args: list[str], output: TextIO
) -> int:
    """Run only exact version flags with neutral state and no account ownership."""
    with (
        _pinned_executable(build) as executable,
        tempfile.TemporaryDirectory(prefix="codex-version-", dir="/tmp") as temporary,
    ):
        home = Path(temporary)
        env = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL")
            if key in os.environ
        }
        env.update(
            HOME=temporary,
            CODEX_HOME=str(home / ".codex"),
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_DATA_HOME=str(home / ".local/share"),
            XDG_STATE_HOME=str(home / ".local/state"),
            XDG_CACHE_HOME=str(home / ".cache"),
            CODEX_BUILD_CHANNEL=build.channel,
        )
        (home / ".codex").mkdir(mode=0o700)
        print(
            f"[{build.channel.upper()} | {profile} | {build.upstream_version}+{build.revision}] "
            f"version inspection of registered executable SHA256 {build.sha256}; account identity: unverified",
            file=output,
            flush=True,
        )
        process = subprocess.Popen(
            [f"/proc/self/fd/{executable}", *args],
            env=env,
            cwd=home,
            stdin=subprocess.DEVNULL,
            pass_fds=(executable,),
            start_new_session=True,
            umask=0o077,
        )
        try:
            try:
                return process.wait(timeout=15)
            except subprocess.TimeoutExpired as error:
                raise BuildError("version inspection timed out") from error
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

def run_build(build: Build, account_home: Path, profile: str, args: list[str], *,
              output: TextIO | None = None) -> int:
    """Launch exact registered bytes through the registered account backend.

    This is a conservative local-client path. It does not grant recovery rights,
    make an official provenance claim beyond registration, or change account auth.
    """
    output = output or sys.stderr
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', profile):
        raise BuildError('profile alias must be a simple printable identifier')
    if any(a == '--remote' or a.startswith('--remote=') for a in args):
        raise BuildError('remote override could bypass selected account/build')
    if args and args[0] not in ('resume', '--version', '-V') and not args[0].startswith('-'):
        # A bare first argument is an initial prompt. Administrative subcommands
        # cannot be routed through this local-client launch boundary.
        if args[0] in ('app-server', 'update', 'exec', 'mcp', 'debug'):
            raise BuildError('administrative command requires a separate explicit operation')
    if args in (['--version'], ['-V']):
        return _inspect_version(build, profile, args, output)
    home = account_home.absolute()
    with _home_ownership(home, channel=build.channel, build_sha256=build.sha256) as lock, _pinned_executable(build) as executable:
        if (build.backend == 'private' and args not in (['--version'], ['-V'])
                and (os.path.lexists(home / 'packages/app-server-daemon/current')
                     or os.path.lexists(home / 'app-server-control/app-server-control.sock'))):
            raise BuildError('private writer cannot open this account; use its registered managed backend')
        if args not in (['--version'], ['-V']):
            validate_history(build, home)
        label = f'{build.channel.upper()} | {profile} | {build.upstream_version}+{build.revision}'
        backend_label = 'managed account backend' if build.backend == 'managed' else 'private backend'
        print(f'[{label}] {backend_label}; account identity: unverified; executable SHA256 {build.sha256}',
              file=output, flush=True)
        if output.isatty():
            print(f'\033]0;{label}\007', end='', file=output, flush=True)
        env = account_environment(home, profile)
        env['CODEX_BUILD_CHANNEL'] = build.channel
        env.pop('CODEX_THREAD_ID', None)
        # A pinned file descriptor avoids selection-link races between hash and exec.
        title_options = ['-c', 'tui.terminal_title=[]'] if output.isatty() else []
        backend = (['--remote', _managed_endpoint(build, home, executable, env)]
                   if build.backend == 'managed' and args not in (['--version'], ['-V'])
                   else ['--no-daemon'])
        command = [f'/proc/self/fd/{executable}', *backend, *title_options, *args]
        descriptors = (executable, lock)
        if build.backend == 'managed' and args not in (['--version'], ['-V']):
            # Only the verified account daemon owns the store. Other clients may
            # attach after setup; embedded private writers still retain the lock.
            fcntl.flock(lock, fcntl.LOCK_UN)
            descriptors = (executable,)
        return subprocess.run(command, env=env, pass_fds=descriptors, check=False,
                              umask=0o077 if build.channel == 'modded' else -1).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--profile')
    parser.add_argument('--channel', choices=['stock', 'modded'], default='modded')
    parser.add_argument('args', nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    from .config import load_settings
    settings = load_settings(options.config)
    try:
        profile = settings.resolve_profile_name(options.profile, os.environ.get('CODEX_PROFILE'))
        args = options.args[1:] if options.args[:1] == ['--'] else options.args
        home = settings.account_root(profile)
        return run_build(load_build(options.manifest, options.channel, home), home, profile, args)
    except (BuildError, OSError, ValueError) as exc:
        print(f'build launch held: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
