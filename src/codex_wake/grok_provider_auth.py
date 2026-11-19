"""Read official Grok sessions without exposing credentials in public status.

The private bearer method is consumed only by the command-auth broker. Presence
is deliberately separate from entitlement and inference qualification.
"""
from datetime import datetime
import fcntl
import hashlib
import re
import json
import math
import os
from pathlib import Path
import stat


class GrokSession:
    def __init__(self, auth_path, expected_binding=None):
        self.auth_path = Path(auth_path)
        self.expected_binding = expected_binding

    def _read(self):
        fd = os.open(self.auth_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('insecure_native_auth')
            if info.st_size > 1024 * 1024:
                raise ValueError('invalid_native_auth')
            try:
                raw = stream.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError('invalid_native_auth')
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ValueError('invalid_native_auth') from None
        if not isinstance(data, dict):
            raise ValueError('invalid_native_auth')
        sessions = [value for value in data.values() if isinstance(value, dict)
                    and value.get('auth_mode') in ('web_login', 'grok', 'oidc', 'external')
                    and isinstance(value.get('key'), str) and value['key']]
        if len(sessions) != 1:
            raise ValueError('native_session_missing_or_ambiguous')
        session = sessions[0]
        if len(session['key']) > 32768 or any(ord(c) < 33 or ord(c) == 127 for c in session['key']):
            raise ValueError('invalid_native_auth')
        if self.expected_binding and identity_binding(session) != self.expected_binding:
            raise ValueError('account_changed')
        return session

    def status(self):
        reason = None
        try:
            credential = self._read()
            authentication = 'present'
            if not credential.get('expires_at'):
                reason = 'native_expiry_unknown'
        except FileNotFoundError:
            authentication, reason = 'unavailable', 'native_auth_missing'
        except ValueError as error:
            authentication = 'account_changed' if str(error) == 'account_changed' else 'unavailable'
            reason = str(error) if str(error) in ('account_changed', 'insecure_native_auth', 'invalid_native_auth', 'native_session_missing_or_ambiguous') else 'native_auth_unavailable'
        except OSError:
            authentication = 'unavailable'
        return dict(authentication=authentication, entitlement='unverified', inference='unverified',
                    freshness='unverified', reason=reason, provider_logout='unconfirmed')

    def bearer(self, qualified_upper):
        """Return a private token only before its expiry's conservative boundary.

        Caller supplies a qualified StableTime upper bound, never guest wall time.
        Rotation remains owned by official Grok until refresh is qualified.
        """
        if (type(qualified_upper) not in (int, float)
                or not math.isfinite(qualified_upper)):
            raise ValueError('qualified_time_required')
        lock_path = self.auth_path.with_name(self.auth_path.name + '.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            info = os.fstat(lock.fileno())
            # Official Grok creates this nonsecret synchronization file as 0644.
            # Readers cannot replace or mutate it; reject other-user writes,
            # retain exact owner/type/inode and the official flock protocol.
            if info.st_uid != os.getuid() or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
                raise ValueError('insecure_native_lock')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('native_auth_busy') from None
            current = os.stat(lock_path, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError('native_lock_replaced')
            session = self._read()
            try:
                expiry = datetime.fromisoformat(session['expires_at'].replace('Z', '+00:00'))
                if expiry.tzinfo is None:
                    raise ValueError()
                expires_at = expiry.timestamp()
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                raise ValueError('native_expiry_unknown') from None
            if qualified_upper + 30 >= expires_at:
                raise ValueError('native_refresh_required')
            return session['key']


def register_parser(commands):
    parser = commands.add_parser('auth', help='official Grok session status and private native command auth')
    verbs = parser.add_subparsers(dest='grok_auth_command', required=True)
    register = verbs.add_parser('register', help='operator-only account binding to an existing official session')
    register.add_argument('account')
    register.add_argument('--label', required=True)
    register.add_argument('--auth-path', type=Path, required=True)
    register.add_argument('--executable', type=Path, help='pin official Grok binary for native refresh')
    login_parser = verbs.add_parser('login', help='operator-only official device login with sanitized progress')
    login_parser.add_argument('--executable', type=Path, required=True)
    login_parser.add_argument('--auth-path', type=Path, required=True)
    revoke = verbs.add_parser('revoke', help='revoke this harness account admission; provider completion remains unknown')
    revoke.add_argument('account')
    revoke.add_argument('--expected-target', type=json.loads, required=True)
    for verb in ('status', 'token'):
        command = verbs.add_parser(verb)
        command.add_argument('account')
        if verb == 'token':
            command.add_argument('--expected-account-revision')


def command(args, root):
    """Local operator boundary; token is intentionally absent from MCP tools."""
    import sys
    if args.grok_auth_command == 'login':
        result = login(args.executable, args.auth_path, emit=lambda event: print(json.dumps(event), flush=True))
        print(json.dumps(result, sort_keys=True))
        return 0 if result['authentication'] == 'present' else 3
    accounts = GrokAccounts(root)
    if args.grok_auth_command == 'register':
        print(json.dumps(accounts.register(args.account, args.label, args.auth_path, executable=args.executable), sort_keys=True))
        return 0
    if args.grok_auth_command == 'status':
        print(json.dumps(dict(target=accounts.target(args.account), **accounts.status(args.account)), sort_keys=True))
        return 0
    if args.grok_auth_command == 'revoke':
        print(json.dumps(accounts.revoke(args.account, args.expected_target), sort_keys=True))
        return 0
    if sys.stdout.isatty():
        print('private_channel_required', file=sys.stderr)
        return 3
    from .time_inspection import stable_time_config
    from .stable_time import service_time_decision
    from .time_provider import require_time_decision
    config = stable_time_config()
    try:
        decision = service_time_decision(config) if config else None
        upper = require_time_decision(decision).upper if decision else None
        accounts.bearer(args.account, upper, expected_revision=args.expected_account_revision)
        # Metadata refresh may have waited on the native writer. Acquire fresh
        # qualified time and revalidate account/expiry immediately before use.
        current = require_time_decision(service_time_decision(config))
        token = accounts.bearer(args.account, current.upper, refresh=False, expected_revision=args.expected_account_revision)
    except (OSError, ValueError) as error:
        # Native Codex includes command stderr in its own diagnostics. Never emit
        # provider exceptions, native login output, paths or credential contents.
        reason = ':' + str(error) if str(error) in ('account_registration_changed', 'account_revoked') else ''
        print('grok_auth_unavailable' + reason, file=sys.stderr)
        return 3
    sys.stdout.write(token)
    return 0


def identity_binding(session):
    identity = session.get('user_id')
    if not isinstance(identity, str) or not identity:
        raise ValueError('native_identity_unknown')
    # Team/principal selection is part of account identity, not only the human.
    value = [identity, session.get('principal_type'), session.get('principal_id'),
             session.get('team_id'), session.get('organization_id')]
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def registration_revision(record):
    """Identity of the operator registration, independent of native token rotation."""
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class GrokAccounts:
    """Operator-owned references to official stores; never a credential copy."""
    def __init__(self, root):
        self.directory = Path(root) / 'grok-provider-accounts'

    def _path(self, account):
        if not isinstance(account, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', account):
            raise ValueError('invalid_grok_account')
        return self.directory / (account + '.json')

    def register(self, account, label, auth_path, *, executable=None):
        path = self._path(account)
        if not isinstance(label, str) or not label.strip() or len(label) > 100 or any(ord(c) < 32 for c in label):
            raise ValueError('invalid_grok_account_label')
        auth_path = Path(auth_path).absolute()
        session = GrokSession(auth_path)._read()
        record = dict(schema=1, account=account, label=label,
                      auth_path=str(auth_path), identity_binding=identity_binding(session))
        if executable is not None:
            executable = Path(executable).absolute()
            record.update(executable=str(executable), executable_sha256=executable_digest(executable))
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return self.status(account)

    def _record(self, account):
        fd = os.open(self._path(account), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                raise ValueError('insecure_grok_registration')
            record = json.load(stream)
        if record.get('schema') != 1 or record.get('account') != account:
            raise ValueError('invalid_grok_registration')
        return record

    def target(self, account):
        import socket
        record = self._record(account)
        home = Path(record['auth_path']).parent
        info = home.stat()
        target = dict(host=socket.gethostname(), environment=os.environ.get('WSL_DISTRO_NAME') or os.name,
                      provider='grok', account=record['account'], home=str(home),
                      home_generation=f'{info.st_dev}:{info.st_ino}',
                      configuration_revision=hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest())
        return target

    def revoke(self, account, expected_target):
        """Fence harness access without deleting or rewriting the official store."""
        import tempfile
        lock_path = self._path(account).with_suffix('.revoke.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            info = os.fstat(lock.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
                raise ValueError('insecure_grok_revocation_lock')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = os.stat(lock_path, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError('grok_revocation_lock_replaced')
            record = self._record(account)
            if record.get('revoked'):
                if expected_target != record.get('revocation_target'):
                    raise ValueError('stale_grok_account_target')
            else:
                if expected_target != self.target(account):
                    raise ValueError('stale_grok_account_target')
                record.update(revoked=True, revocation_target=expected_target)
                descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix='.revoke-')
                try:
                    with os.fdopen(descriptor, 'w') as stream:
                        json.dump(record, stream, sort_keys=True)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, self._path(account))
                    directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            return dict(account=account, authentication='revoked', target=self.target(account),
                        provider_completion='unknown', provider_logout='unconfirmed',
                        owned_work_interruption='pending_native_observation')

    def status(self, account):
        record = self._record(account)
        if record.get('revoked'):
            return dict(account=account, label=record['label'],
                        registration_revision=registration_revision(record), authentication='revoked',
                        entitlement='unverified', inference='unverified', freshness='unverified',
                        reason='account_revoked', provider_logout='unconfirmed')
        session = GrokSession(record['auth_path'], record['identity_binding'])
        return dict(account=account, label=record['label'],
                    registration_revision=registration_revision(record), **session.status())

    def bearer(self, account, qualified_upper, *, refresh=True, expected_revision=None):
        record = self._record(account)
        if record.get('revoked'):
            raise ValueError('account_revoked')
        if expected_revision is not None and registration_revision(record) != expected_revision:
            raise ValueError('account_registration_changed')
        session = GrokSession(record['auth_path'], record['identity_binding'])
        try:
            return session.bearer(qualified_upper)
        except ValueError as error:
            if str(error) != 'native_refresh_required' or not refresh or not record.get('executable'):
                raise
        native_refresh(self.directory, record, session)
        return session.bearer(qualified_upper)


def login(executable, auth_path, *, emit, timeout=600):
    """Run official login; relay only a validated human verification URL.

    The native program owns OAuth and all credential writes. Its arbitrary
    diagnostic text is discarded, including errors. A successful process exit
    does not establish a usable session or entitlement.
    """
    import selectors
    import subprocess
    from . import measurements
    from urllib.parse import urlsplit, parse_qsl
    executable = Path(executable).absolute()
    info = executable.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in (0, os.getuid()):
        raise ValueError('untrusted_grok_executable')
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('XAI_', 'GROK_', 'OAUTH_'))}
    environment['GROK_AUTH_PATH'] = str(Path(auth_path).absolute())
    environment['GROK_HOME'] = str(Path(auth_path).absolute().parent)
    environment['RUST_LOG'] = 'off'
    held = dict(status='held', authentication='unavailable', entitlement='unverified',
                inference='unverified', freshness='unverified', reason='stable_time_unavailable',
                provider_logout='unconfirmed')
    try:
        deadline = measurements.deadline(timeout)
    except measurements.TimeUnavailable:
        return held
    process = subprocess.Popen([str(executable), 'login', '--device-auth'],
                               env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    buffer = b''
    sent = set()
    awaiting_user_code = False
    awaiting_verification_uri = False
    with selectors.DefaultSelector() as selector:
        selector.register(process.stderr, selectors.EVENT_READ)
        try:
            while selector.get_map():
                remaining = deadline.remaining()
                if remaining <= 0:
                    process.terminate()
                    break
                for key, _ in selector.select(min(remaining, 1)):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer += chunk
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if len(line) > 4096:
                            continue
                        candidate = line.decode('utf-8', errors='replace').strip()
                        if candidate == 'To sign in, open this URL in your browser:':
                            awaiting_verification_uri = True
                            continue
                        if candidate in ('Confirm this code in your browser:', 'Then enter this code:'):
                            awaiting_user_code = True
                            continue
                        if awaiting_user_code and candidate:
                            awaiting_user_code = False
                            if re.fullmatch(r'[A-Za-z0-9-]{1,32}', candidate):
                                emit(dict(status='login_pending', user_code=candidate))
                            continue
                        if not candidate or not awaiting_verification_uri:
                            continue
                        awaiting_verification_uri = False
                        try:
                            url = urlsplit(candidate)
                            port = url.port
                        except ValueError:
                            continue
                        if (url.scheme != 'https' or url.hostname not in ('auth.x.ai', 'accounts.x.ai', 'grok.com')
                                or url.username or url.password or port not in (None, 443)
                                or url.fragment or any(ord(c) < 33 for c in candidate)
                                or len(candidate) > 2048):
                            continue
                        query = parse_qsl(url.query, keep_blank_values=True)
                        if any(name != 'user_code' or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', value)
                               for name, value in query):
                            continue
                        if candidate not in sent:
                            emit(dict(status='login_pending', verification_uri=candidate))
                            sent.add(candidate)
                    if len(buffer) > 4096:
                        buffer = b''
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        except measurements.TimeUnavailable:
            return held
        finally:
            process.stderr.close()
            if process.poll() is None:
                process.kill()
                process.wait()
    result = GrokSession(auth_path).status()
    return dict(status='login_finished' if process.returncode == 0 else 'login_failed', **result)


def tool_specs():
    return {'wake_grok_auth_status': ('grok-provider-auth', 'grok_auth.status',
        'Inspect sanitized native Grok account authentication; presence does not qualify entitlement or inference. Requires an exact account grant.',
        {'account': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9_-]{0,63}$'},
         'expected_target': {'type': 'object'}}, ['account', 'expected_target'], True),
        'wake_grok_auth_revoke': ('grok-provider-auth', 'grok_auth.revoke',
        'Revoke one exact registered Grok account for this harness. Provider completion/logout remain unconfirmed; owned native interruption is observed separately.',
        {'account': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9_-]{0,63}$'},
         'expected_target': {'type': 'object'}}, ['account', 'expected_target'], False)}


def observe(root, arguments, *, actor, authorize, operation="grok_auth.status"):
    """Admit an exact account grant before opening its native credential file."""
    from .controller_auth import Actor, AuthError
    from .managed_inventory import InventoryError
    if set(arguments) != {'account', 'expected_target'}:
        raise InventoryError('invalid_argument', 'Exact Grok account target required.')
    if operation not in ('grok_auth.status', 'grok_auth.revoke'):
        raise InventoryError('unsupported_operation', 'Unsupported Grok account operation.')
    required = 'account.revoke' if operation == 'grok_auth.revoke' else 'account.observe'
    accounts = GrokAccounts(root)
    target = accounts.target(arguments['account'])
    fields = set(target)
    def guard(readback=target):
        current = authorize()
        if (not isinstance(actor, Actor) or current != actor or required not in actor.scopes
                or not any(fields <= scope.keys() and all(target.get(k) == v for k, v in scope.items())
                           for scope in actor.targets)):
            raise AuthError('insufficient_scope')
        if arguments['expected_target'] != target or accounts.target(arguments['account']) != readback:
            raise InventoryError('stale_target', 'Grok account target changed.')
    guard()
    if operation == 'grok_auth.revoke':
        result = accounts.revoke(arguments['account'], target)
        guard(result['target'])
        return dict(schema_version=1, operation=operation, status='completed', result=result)
    result = accounts.status(arguments['account'])
    guard()
    return dict(schema_version=1, operation='grok_auth.status', status='completed',
                result=dict(target=target, authentication=result))


def protected_observe(root, arguments, operation="grok_auth.status"):
    from .operation_commands import local_actor
    return observe(root, arguments, actor=local_actor(root), authorize=lambda: local_actor(root), operation=operation)


def executable_digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in (0, os.getuid()):
            raise ValueError('untrusted_grok_executable')
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def native_refresh(directory, record, session):
    """Ask official metadata utility to service auth; never write credentials.

    Official `models` performs catalog initialization with its AuthManager and
    shuts down its in-process shell. No coding turn is submitted. Native flock,
    refresh-token rotation and atomic persistence remain owned by Grok. A failed
    or interrupted attempt stays held until the native credential changes.
    """
    import subprocess
    executable = Path(record['executable'])
    if executable_digest(executable) != record['executable_sha256']:
        raise ValueError('native_executable_changed')
    credential = session._read()
    generation = hashlib.sha256(json.dumps(credential, sort_keys=True).encode()).hexdigest()
    marker = Path(directory) / (record['account'] + '-refresh-' + generation + '.json')
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise ValueError('native_refresh_requires_reconciliation') from None
    with os.fdopen(fd, 'w') as stream:
        json.dump(dict(state='attempted', operation='official_catalog_auth_refresh'), stream)
        stream.flush()
        os.fsync(stream.fileno())
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('XAI_', 'GROK_', 'OAUTH_'))}
    environment.update(GROK_AUTH_PATH=record['auth_path'],
                       GROK_HOME=str(Path(record['auth_path']).parent),
                       GROK_DISABLE_API_KEY_AUTH='true', RUST_LOG='off')
    try:
        result = subprocess.run([str(executable), 'models'], env=environment,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('native_refresh_requires_reconciliation') from None
    if result.returncode != 0:
        raise ValueError('native_refresh_requires_reconciliation')
