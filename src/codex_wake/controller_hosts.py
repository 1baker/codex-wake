"""Registered host/environment identities and pinned SSH execution authority.

The registry is host configuration, not a client-selected path. Destinations and
forced commands come only from local operator registration. Native processes,
credentials and provider work remain with the selected execution environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .managed_inventory import InventoryError

READ_OPERATIONS = frozenset({'inventory.list', 'inventory.resolve', 'accounts.list', 'accounts.resolve', 'configuration.explain'})
CAPABILITIES = {'inventory.list': 'observe', 'inventory.resolve': 'observe',
                'accounts.list': 'account.observe', 'accounts.resolve': 'account.observe',
                'configuration.explain': 'configuration.observe'}
# New connector observations can be registered explicitly; preserve the legacy
# default capability set for existing host-registration identity comparisons.
CONNECTOR_READS={'environment.snapshot':'observe','environment.children':'observe',
    'local.observe':'content.observe','local.observation.output':'content.observe',
    'local.observation.result':'content.observe','local.observation.cancel':'content.observe'}
REGISTERED_MANAGEMENT={**{'flows.'+verb:'control' for verb in ('publish','start','advance','reconcile','cancel')},
    **{'sessions.'+verb:'control' for verb in ('create','prompt','cancel','fork')},
    'environment.panes.paste':'terminal.input','environment.panes.keys':'terminal.input'}
CONNECTOR_READS.update({'flows.'+verb:'observe' for verb in ('propose','definition','inspect')})
CONNECTOR_READS.update({'environment.panes.'+verb:'content.observe' for verb in ('capture','observe','output')})
CAPABILITIES.update(CONNECTOR_READS)
CAPABILITIES.update(REGISTERED_MANAGEMENT)
from .unified_contract import canonical
CAPABILITIES.update({canonical(operation):scope for operation,scope in list(CAPABILITIES.items())})

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')


def identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise InventoryError('invalid_argument', 'bounded host/environment/principal identity required')
    return value


class HostRegistry:
    def __init__(self, path, *, now=time.time):
        self.path, self.now = Path(path), now
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600); os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS environments (host TEXT, environment TEXT, record TEXT, PRIMARY KEY(host,environment));
                CREATE TABLE IF NOT EXISTS principals (id TEXT PRIMARY KEY, record TEXT);
                CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, fingerprint TEXT, operation_id TEXT UNIQUE, record TEXT);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def register(self, host, environment, *, kind, authority, destination, command='codex-wake hosts ssh-serve', capabilities=READ_OPERATIONS, ssh_executable='ssh', generation=None, operator=False):
        if not operator: raise InventoryError('unauthorized_target', 'host registration requires local operator authority')
        host, environment, authority = identifier(host), identifier(environment), identifier(authority)
        if kind not in ('windows', 'wsl', 'linux', 'remote'):
            raise InventoryError('unsupported_target', 'unsupported execution environment kind')
        if not isinstance(destination, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:\[\]-]{0,254}', destination):
            raise InventoryError('invalid_argument', 'invalid registered SSH destination')
        if not isinstance(command, str) or not command or len(command) > 2048 or any(ord(c) < 32 for c in command):
            raise InventoryError('invalid_argument', 'invalid operator-configured remote command')
        if not capabilities or not set(capabilities) <= CAPABILITIES.keys():
            raise InventoryError('unsupported_operation', 'only explicitly supported host operations may be registered')
        if not isinstance(ssh_executable, str) or not ssh_executable or any(ord(c) < 32 for c in ssh_executable):
            raise InventoryError('invalid_argument', 'invalid local SSH executable')
        if generation is not None and (not isinstance(generation, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', generation)):
            raise InventoryError('invalid_argument', 'invalid imported authority generation')
        record = dict(target=dict(host=host, environment=environment, authority=authority, generation=generation or secrets.token_urlsafe(18)),
            kind=kind, transport=dict(kind='ssh', destination=destination, command=command, executable=ssh_executable),
            capabilities=sorted(capabilities), observed_at=self.now(), online=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT record FROM environments WHERE host=? AND environment=?', (host, environment)).fetchone()
            if row:
                previous = json.loads(row[0])
                if (generation is not None and previous['target']['generation'] != generation) or any(previous[key] != record[key] for key in ('kind', 'transport', 'capabilities')) or previous['target']['authority'] != authority:
                    raise InventoryError('authority_conflict', 'environment already has a distinct pinned authority')
                return self.public(previous)
            db.execute('INSERT INTO environments VALUES(?,?,?)', (host, environment, json.dumps(record)))
        return self.public(record)

    def public(self, record):
        return dict(target=record['target'], kind=record['kind'], transport=record['transport'], capabilities=record['capabilities'],
            observation=dict(observed_at=record['observed_at'], age_seconds=max(0, self.now() - record['observed_at']),
                freshness='current' if 0 <= self.now() - record['observed_at'] <= 30 else 'stale', online=record['online']),
            grants_operations=False)

    def list(self):
        with self.connect() as db:
            return [self.public(json.loads(row[0])) for row in db.execute('SELECT record FROM environments ORDER BY host,environment')]

    def resolve(self, host, environment, *, expected_target=None, require_online=False):
        identifier(host); identifier(environment)
        with self.connect() as db:
            row = db.execute('SELECT record FROM environments WHERE host=? AND environment=?', (host, environment)).fetchone()
        if not row: raise InventoryError('target_not_found', 'host/environment is not registered')
        public = self.public(json.loads(row[0]))
        if expected_target is not None and public['target'] != expected_target:
            raise InventoryError('stale_target', 'pinned host/environment authority generation changed')
        if require_online:
            if public['observation']['freshness'] != 'current': raise InventoryError('stale_target', 'environment observation expired')
            if not public['observation']['online']: raise InventoryError('offline_target', 'environment is observed offline; no queue or replay')
        return public

    def observe(self, target, *, online, operator=False):
        if not operator: raise InventoryError('unauthorized_target', 'observation refresh requires local operator authority')
        if type(online) is not bool: raise InventoryError('invalid_argument', 'online must be Boolean')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT record FROM environments WHERE host=? AND environment=?', (target.get('host'), target.get('environment'))).fetchone()
            if not row: raise InventoryError('target_not_found', 'environment is not registered')
            record = json.loads(row[0])
            if record['target'] != target: raise InventoryError('stale_target', 'observation target generation changed')
            record.update(online=online, observed_at=self.now())
            db.execute('UPDATE environments SET record=? WHERE host=? AND environment=?', (json.dumps(record), target['host'], target['environment']))
        return self.public(record)

    def map_principal(self, principal_id, *, subject, scopes, targets, expires_at, operator=False):
        from .controller_auth import SCOPES
        if not operator: raise InventoryError('unauthorized_target', 'principal mapping requires local operator authority')
        identifier(principal_id)
        if not isinstance(subject, str) or not subject or not scopes or not set(scopes) <= SCOPES:
            raise InventoryError('invalid_argument', 'invalid mapped principal or capabilities')
        if not isinstance(targets, list) or not targets or any(not isinstance(t, dict) or not t or any(not isinstance(v, str) or not v for v in t.values()) for t in targets):
            raise InventoryError('invalid_argument', 'explicit target grants required')
        if not isinstance(expires_at, (int, float)) or not self.now() < expires_at <= self.now() + 86400:
            raise InventoryError('invalid_argument', 'principal mapping requires finite lifetime at most one day')
        record = dict(subject=subject, scopes=sorted(scopes), targets=targets, expires_at=expires_at,
            grant_id='ssh:' + secrets.token_urlsafe(24), revoked=False)
        with self.connect() as db:
            existing = db.execute('SELECT id FROM principals WHERE id=?', (principal_id,)).fetchone()
            if existing: raise InventoryError('principal_conflict', 'principal already mapped; revoke before explicit replacement')
            db.execute('INSERT INTO principals VALUES(?,?)', (principal_id, json.dumps(record)))
        return dict(principal_id=principal_id, subject=subject, grant_id=record['grant_id'], expires_at=expires_at)

    def ssh_actor(self, principal_id):
        from .controller_auth import Actor, AuthError
        with self.connect() as db:
            row = db.execute('SELECT record FROM principals WHERE id=?', (principal_id,)).fetchone()
        if not row: raise AuthError()
        record = json.loads(row[0])
        if record['revoked'] or record['expires_at'] <= self.now(): raise AuthError()
        return Actor(record['subject'], 'service', 'ssh:' + principal_id, record['grant_id'],
            'ssh://host-local', 'wake:controller', frozenset(record['scopes']), record['targets'], record['expires_at'])

    def revoke_principal(self, principal_id, *, operator=False):
        if not operator: raise InventoryError('unauthorized_target', 'principal revocation requires local operator authority')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT record FROM principals WHERE id=?', (principal_id,)).fetchone()
            if not row: raise InventoryError('target_not_found', 'mapped principal does not exist')
            record = json.loads(row[0]); record['revoked'] = True
            db.execute('UPDATE principals SET record=? WHERE id=?', (json.dumps(record), principal_id))
        return dict(principal_id=principal_id, status='revoked', cancellation='no_owned_active_work')


class SSHReceiver:
    """Forced-command receiver; authenticated principal is fixed outside payload.

    sshd/authorized_keys must pin the principal and receiver command. The caller's
    optional constraints only narrow that mapping; they cannot invent identity.
    """
    def __init__(self, registry, operations, *, principal_id, target):
        self.registry, self.operations = registry, operations
        self.principal_id, self.target = principal_id, target

    def execute(self, request):
        from dataclasses import replace
        from .controller_auth import AuthError
        from .controller_http import ProtectedOperations
        if not isinstance(request, dict) or set(request) != {'target', 'operation', 'arguments', 'constraints'}:
            raise InventoryError('invalid_argument', 'invalid SSH request envelope; identity fields are not accepted')
        if request['target'] != self.target:
            raise InventoryError('stale_target', 'SSH receiver is a different authority/generation')
        registered = self.registry.resolve(self.target['host'], self.target['environment'], expected_target=self.target)
        if self.operations.host != self.target['host'] or self.operations.environment != self.target['environment']:
            raise InventoryError('unauthorized_target', 'receiver execution environment does not match pinned authority')
        if request['operation'] not in registered['capabilities']:
            raise InventoryError('unsupported_operation', 'execution authority does not support this operation')
        constraints = request['constraints']
        if not isinstance(constraints, dict) or set(constraints)-{'scopes','targets','actions','expires_at'} or not {'scopes','targets'}<=set(constraints):
            raise InventoryError('invalid_argument', 'caller attenuation constraints required')
        if not isinstance(constraints['scopes'], list) or not isinstance(constraints['targets'], list) or not constraints['targets']:
            raise InventoryError('invalid_argument', 'invalid caller attenuation')
        if any(not isinstance(t, dict) or not t or any(not isinstance(v, str) for v in t.values()) for t in constraints['targets']):
            raise InventoryError('invalid_argument', 'invalid caller targets')
        if 'actions' in constraints:
            from .unified_connectors import canonical_actions
            requested_actions=canonical_actions(constraints['actions'])
        else:requested_actions=None
        expiry=constraints.get('expires_at',float('inf'))
        if 'expires_at' in constraints and (type(expiry) not in (int,float) or not self.registry.now()<expiry<float('inf')):
            raise AuthError('insufficient_scope')
        receiver = self
        class MappedAuthority:
            def authenticate(self, token):
                actor = receiver.registry.ssh_actor(receiver.principal_id)
                targets = []
                for granted in actor.targets:
                    for requested in constraints['targets']:
                        if not any(k in granted and granted[k] != value for k, value in requested.items()):
                            targets.append(dict(granted, **requested))
                if not targets: raise AuthError('insufficient_scope')
                actions=actor.actions if requested_actions is None else requested_actions if actor.actions is None else actor.actions & requested_actions
                return replace(actor, scopes=actor.scopes & frozenset(constraints['scopes']), targets=targets,actions=actions,expires_at=min(actor.expires_at,expiry),delegated=actor.delegated or 'actions' in constraints or 'expires_at' in constraints)
        return ProtectedOperations(MappedAuthority(), self.operations).execute('fixed-ssh-principal', request['operation'], request['arguments'])


class TransportFailure(ValueError):
    def __init__(self, reason, *, submitted):
        super().__init__(reason)
        self.submitted = submitted


class SSHTransport:
    """Bounded batch SSH, pinned host keys, fixed registered receiver command."""
    def send(self, registered, request):
        import selectors
        import subprocess
        transport = registered['transport']
        argv = [transport['executable'], '-T', '-oBatchMode=yes', '-oConnectTimeout=5',
                '-oStrictHostKeyChecking=yes', '--', transport['destination'], transport['command']]
        payload = json.dumps(request, sort_keys=True).encode()
        if len(payload) > 65536: raise TransportFailure('request_frame_limit', submitted=False)
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError: raise TransportFailure('ssh_start_failed', submitted=False)
        sent, output = 0, bytearray()
        deadline = time.monotonic() + 10
        try:
            with selectors.DefaultSelector() as selector:
                for stream, events in ((process.stdin, selectors.EVENT_WRITE), (process.stdout, selectors.EVENT_READ)):
                    os.set_blocking(stream.fileno(), False); selector.register(stream, events)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise TransportFailure('ssh_deadline', submitted=sent > 0)
                    for key, _ in selector.select(remaining):
                        if key.fileobj is process.stdin:
                            try: written = os.write(process.stdin.fileno(), payload[sent:sent + 4096])
                            except BrokenPipeError: raise TransportFailure('ssh_input_closed', submitted=sent > 0)
                            sent += written
                            if sent == len(payload):
                                selector.unregister(process.stdin); process.stdin.close()
                        else:
                            chunk = os.read(process.stdout.fileno(), 4096)
                            if not chunk:
                                selector.unregister(process.stdout); process.stdout.close()
                            else:
                                output.extend(chunk)
                                if len(output) > 65536: raise TransportFailure('response_frame_limit', submitted=sent > 0)
                try: code = process.wait(timeout=max(.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired: raise TransportFailure('ssh_deadline', submitted=sent > 0)
                try: result = json.loads(output)
                except ValueError: raise TransportFailure('invalid_authority_response', submitted=sent > 0)
                if not isinstance(result, dict): raise TransportFailure('invalid_authority_response', submitted=sent > 0)
                if code != 0 and not (result.get('schema_version') == 1 and result.get('operation') == request['operation'] and result.get('status') == 'failed'):
                    raise TransportFailure('ssh_disconnected', submitted=sent > 0)
                return result
        finally:
            if process.poll() is None: process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream and not stream.closed: stream.close()


class HostOperations:
    def __init__(self, registry, *, transport=None, local_operator=False):
        self.registry, self.transport = registry, transport or SSHTransport()
        self.local_operator = local_operator

    def execute(self, operation, arguments, *, actor=None, authorize=None):
        if not isinstance(arguments, dict): raise InventoryError('invalid_argument', 'object arguments required')
        if operation == 'hosts.list':
            if arguments: raise InventoryError('invalid_argument', 'host list accepts no selectors')
            return {'environments': self.registry.list()}
        if operation == 'hosts.resolve':
            if set(arguments) - {'host', 'environment', 'expected_target'}: raise InventoryError('invalid_argument', 'unsupported host selector')
            return {'environment': self.registry.resolve(arguments.get('host'), arguments.get('environment'), expected_target=arguments.get('expected_target'))}
        if operation != 'hosts.route': raise InventoryError('unsupported_operation', 'unsupported host operation')
        return self.route(arguments, actor=actor, authorize=authorize)

    def route(self, arguments, *, actor, authorize=None):
        import hashlib
        from .controller_auth import Actor, AuthError
        allowed = {'target', 'operation', 'arguments', 'operation_id', 'idempotency_key'}
        if set(arguments) != allowed or not isinstance(arguments.get('target'), dict) or not isinstance(arguments.get('arguments'), dict):
            raise InventoryError('invalid_argument', 'pinned target, typed operation and durable IDs required')
        target, operation = arguments['target'], arguments['operation']
        identifier(arguments['operation_id']); identifier(arguments['idempotency_key'])
        if not set(target) == {'host', 'environment', 'authority', 'generation'}:
            raise InventoryError('invalid_argument', 'full pinned authority target required')
        if operation not in CAPABILITIES:
            raise InventoryError('unsupported_operation', 'operation has no qualified host route; no offline queue or fallback')
        if actor is None and self.local_operator:
            actor = Actor('local-operator', 'owner', 'local-cli', 'local-cli', 'local://operator', 'wake:controller', frozenset(CAPABILITIES.values()),
                [dict(target)], self.registry.now() + 10)
        if not isinstance(actor, Actor) or actor.expires_at <= self.registry.now() or CAPABILITIES[operation] not in actor.scopes:
            raise InventoryError('unauthorized_target', 'authenticated caller lacks routed operation capability')
        # Namespace/account restrictions are carried as attenuation constraints to
        # the receiver. They can narrow, never expand its fixed SSH mapping.
        from .unified_connectors import check_action
        check_action(actor,operation)
        compatible = [scope for scope in actor.targets if set(target) <= set(scope) and not any(k in target and target[k] != value for k, value in scope.items())]
        if not compatible: raise InventoryError('unauthorized_target', 'caller is outside the pinned host/environment target scope')
        registered = self.registry.resolve(target['host'], target['environment'], expected_target=target)
        if operation not in registered['capabilities']: raise InventoryError('unsupported_operation', 'registered authority lacks operation capability')
        request = dict(target=target, operation=operation, arguments=arguments['arguments'], constraints=dict(scopes=sorted(actor.scopes), targets=[{k: v for k, v in scope.items() if k not in ('authority', 'generation')} for scope in compatible]))
        request['constraints']['expires_at']=actor.expires_at
        if actor.actions is not None:request['constraints']['actions']=sorted(actor.actions)
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        key = hashlib.sha256((actor.issuer + '\0' + actor.grant_id + '\0' + arguments['idempotency_key']).encode()).hexdigest()
        receipt = dict(operation_id=arguments['operation_id'], target=target, submission='admitted',
            execution='unknown', delivery='uncertain', acceptance='unknown', effect='management_action' if operation in REGISTERED_MANAGEMENT or operation in {canonical(op) for op in REGISTERED_MANAGEMENT} else 'none_read_only',
            reason='submission_in_progress_or_interrupted')
        with self.registry.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT fingerprint,record FROM deliveries WHERE id=?', (key,)).fetchone()
            if previous:
                if previous[0] != fingerprint: raise InventoryError('idempotency_conflict', 'idempotency key inputs or authority changed')
                return {'route': json.loads(previous[1])}
            self.registry.resolve(target['host'], target['environment'], expected_target=target, require_online=True)
            try: db.execute('INSERT INTO deliveries VALUES(?,?,?,?)', (key, fingerprint, arguments['operation_id'], json.dumps(receipt)))
            except sqlite3.IntegrityError: raise InventoryError('idempotency_conflict', 'operation ID is already bound to another admission')
        try:
            if authorize is not None:
                current = authorize()
                if not isinstance(current, Actor) or current.issuer != actor.issuer or current.grant_id != actor.grant_id or current.scopes != actor.scopes or current.targets != actor.targets or current.actions != actor.actions or current.expires_at <= self.registry.now():
                    raise InventoryError('unauthorized_target', 'caller authorization changed before SSH submission')
            result = self.transport.send(registered, request)
            if result.get('schema_version') != 1 or result.get('operation') != operation or result.get('status') not in ('completed', 'failed'):
                raise TransportFailure('invalid_authority_response', submitted=True)
            receipt.update(execution=result['status'], delivery='received', acceptance='observed', reason=None, result=result)
        except (InventoryError, AuthError) as error:
            receipt.update(execution='not_started', delivery='not_submitted', reason=getattr(error, 'code', 'unauthorized_target'))
        except TransportFailure as error:
            receipt.update(execution='unknown' if error.submitted else 'not_started', delivery='uncertain' if error.submitted else 'not_submitted', reason=str(error))
        with self.registry.connect() as db:
            db.execute('UPDATE deliveries SET record=? WHERE id=?', (json.dumps(receipt), key))
        return {'route': receipt}
