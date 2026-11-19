"""Durable caller-owned operation admission, correlation and result custody.

Effect owners remain authoritative. This journal never retries an admitted effect.
Mailbox and supervised-command adapters retain their own execution/cancellation
contracts; caller wait deadlines and disconnects do not cancel target work.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import stat
from weakref import WeakKeyDictionary

from .controller_auth import Actor, AuthError, _qualified_upper
from .managed_inventory import InventoryError


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def bounded_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ord(c) < 32 for c in value):
        raise InventoryError('invalid_argument', 'explicit bounded operation/correlation/binding identity required')
    return value


def identity(actor):
    return {key: getattr(actor, key) for key in ('issuer', 'resource', 'subject', 'client_id', 'grant_id')}


class _LocalStopCapability:
    """Live-process custody only; never an Actor or a wire representation."""


_LOCAL_STOPS = WeakKeyDictionary()


def _private_local_root(root):
    root = Path(root).absolute()
    if os.getuid() != os.geteuid() or root != root.resolve():
        raise AuthError('insufficient_scope')
    for path in (root, root/'controller-operations', root/'controller-operations'/'operations.sqlite'):
        try:
            info = path.lstat()
        except FileNotFoundError:
            if path == root:
                raise AuthError('insufficient_scope') from None
            continue
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or stat.S_ISLNK(info.st_mode):
            raise AuthError('insufficient_scope')
        if not (stat.S_ISDIR(info.st_mode) if path != root/'controller-operations'/'operations.sqlite' else stat.S_ISREG(info.st_mode)):
            raise AuthError('insufficient_scope')
    return root


def _local_stop_capability(root, arguments):
    """Called only by the immediate local daemon adapter, never from saved work."""
    root = _private_local_root(root)
    if not isinstance(arguments, dict) or arguments.get('confirm') is not True:
        raise InventoryError('confirmation_required', 'explicit confirmation of this scoped interruption is required')
    target, meta = arguments.get('expected_target'), arguments.get('_request')
    if (not isinstance(target, dict) or not {'host','environment','account','home','home_generation','build_sha256','process','socket_generation'} <= target.keys()
            or not isinstance(meta, dict) or set(meta) != {'operation_id','idempotency_key','correlation_id','binding','target'} or meta['target'] != target):
        raise InventoryError('stale_target', 'exact local stop target and original request required')
    for key in ('operation_id','idempotency_key','correlation_id','binding'):
        bounded_id(meta[key])
    capability = _LocalStopCapability()
    _LOCAL_STOPS[capability] = encoded(dict(root=str(root), uid=os.getuid(), arguments=arguments))
    return capability


class ControllerRuntime:
    def __init__(self, root, *, adapter=None, now=None):
        self.root, self.adapter, self.now = Path(root), adapter, now if now is not None else _qualified_upper
        directory = self.root / 'controller-operations'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / 'operations.sqlite'
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600); os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, intent_key TEXT UNIQUE, fingerprint TEXT, record TEXT);
                CREATE TABLE IF NOT EXISTS events (operation_id TEXT, sequence INTEGER,
                event_key TEXT, payload TEXT, PRIMARY KEY(operation_id,event_key));
                CREATE TABLE IF NOT EXISTS revoked_grants (issuer TEXT, resource TEXT, grant_id TEXT,
                revoked_at REAL, PRIMARY KEY(issuer,resource,grant_id));''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def _authorize(self, actor, target, capability, authorize=None):
        if isinstance(actor, Actor):
            with self.connect() as db:
                revoked = db.execute('SELECT 1 FROM revoked_grants WHERE issuer=? AND resource=? AND grant_id=?', (actor.issuer,actor.resource,actor.grant_id)).fetchone()
            if revoked: raise AuthError()
        if not isinstance(actor, Actor) or actor.expires_at <= self.now() or capability not in actor.scopes:
            raise AuthError('insufficient_scope')
        if not isinstance(target, dict) or not {'host', 'environment'} <= target.keys():
            raise InventoryError('invalid_argument', 'pinned host/environment target required')
        if not any({'host', 'environment'} <= scope.keys() and all(target.get(k) == v for k, v in scope.items()) for scope in actor.targets):
            raise AuthError('insufficient_scope')
        if authorize is not None:
            current = authorize()
            if not isinstance(current, Actor) or identity(current) != identity(actor) or current.scopes != actor.scopes or current.targets != actor.targets or current.expires_at <= self.now():
                raise AuthError()
        return actor

    def check_authority(self, actor, target, capability, *, authorize=None):
        """Authorize composed host workflows without admitting a new effect."""
        return self._authorize(actor, target, capability, authorize)

    def owned_operations(self, actor, target, operation, *, authorize, cursor=0, stable_history_store=False):
        """Bounded caller-owned journal projection; never broadens target grants."""
        self._authorize(actor, target, 'observe', authorize)
        if type(cursor) is not int or not 0 <= cursor <= 10000:
            raise InventoryError('invalid_argument', 'bounded journal cursor required')
        with self.connect() as db:
            rows = db.execute('SELECT record FROM operations ORDER BY rowid LIMIT 100 OFFSET ?', (cursor,)).fetchall()
        result = []
        for row in rows:
            record = json.loads(row[0])
            if stable_history_store:
                if operation != 'history.import':
                    raise InventoryError('invalid_argument', 'stable store projection is history-only')
                same_target = all(record['target'].get(key) == target.get(key) for key in
                    ('host', 'environment', 'provider', 'account', 'home', 'home_generation'))
            else:
                same_target = record['target'] == target
            if not same_target or record['operation'] != operation:
                continue
            if identity(actor) not in [record['principal'], *record.get('successors', [])]:
                continue
            if not stable_history_store:
                self._owned(actor, record, authorize)
            result.append(self.projection(record))
        self._authorize(actor, target, 'observe', authorize)
        return result, cursor + len(rows) if len(rows) == 100 else None

    def reconcile_result(self, actor, operation_id, *, expected_operation, authorize, observe, capability='control'):
        """Trusted effect owner's read-only reconciliation of an uncertain result.

        No public generic result-writing operation exists. The owner must observe
        original retained proof, and cannot redispatch through this hook.
        """
        record = self._owned(actor, self._load(operation_id), authorize, capability=capability)
        if record['operation'] != expected_operation:
            raise InventoryError('unsupported_operation', 'original operation belongs to another effect owner')
        if record['phase'] == 'terminal':
            return self.envelope(expected_operation, record)
        value = observe(self.projection(record))
        self._owned(actor, record, authorize, capability=capability)
        if value is not None:
            if len(encoded(value).encode()) > 262144:
                raise InventoryError('capacity', 'reconciled result exceeds retained bound')
            record.update(result=value, phase='terminal', execution='completed', delivery='retained',
                acceptance='owner_observed', reason=None)
            self._save(record)
            self._event(record, 'reconciled', dict(kind='reconciled', operation_id=operation_id))
        return self.envelope(expected_operation, record)

    def _save(self, record, *, update_owner=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT record FROM operations WHERE id=?', (record['operation_id'],)).fetchone()
            current = json.loads(row[0])
            if current.get('_revision', 0) > record.get('_revision', 0):
                if update_owner:
                    successors = current.get('successors', []) + record.get('successors', [])
                    record['successors'] = [item for index,item in enumerate(successors) if item not in successors[:index]]
                else:
                    for key in ('binding', 'successors', 'cancellation', 'revocation'):
                        if key in current: record[key] = current[key]
                if current['phase'] == 'terminal':
                    for key in ('execution', 'delivery', 'acceptance', 'phase', 'reason', 'result', 'answer'):
                        if key in current: record[key] = current[key]
            record['_revision'] = current.get('_revision', 0) + 1
            db.execute('UPDATE operations SET record=? WHERE id=?', (encoded(record), record['operation_id']))

    def _event(self, record, key, value):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM events WHERE operation_id=? AND event_key=?', (record['operation_id'], key)).fetchone(): return
            sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE operation_id=?', (record['operation_id'],)).fetchone()[0]
            db.execute('INSERT INTO events VALUES(?,?,?,?)', (record['operation_id'], sequence, key, encoded(dict(sequence=sequence, **value))))

    def _load(self, operation_id):
        bounded_id(operation_id)
        with self.connect() as db:
            row = db.execute('SELECT record FROM operations WHERE id=?', (operation_id,)).fetchone()
        if not row: raise InventoryError('operation_not_found', 'operation handle is not retained')
        return json.loads(row[0])

    def local_tab_result(self, operation_id, *, expected_operation=None, arguments=None):
        """Read one retained same-UID tab intent without live workspace access.

        Local CLI only: remote APIs retain authenticated operations.result. The
        stored target restores scope, never effect dispatch or fresh authority.
        Optional supplied inputs must still match the immutable original intent.
        """
        from .daemon_commands import local_operator
        for path in (self.path.parent, self.path):
            info=path.lstat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o077 or path.is_symlink():
                raise AuthError('insufficient_scope')
        record=self._load(operation_id)
        if not record['operation'].startswith('tabs.'):
            raise InventoryError('unsupported_operation','Retained operation belongs to another owner.')
        actor=local_operator(record['target'])
        self._owned(actor,record,lambda:actor)
        if expected_operation is not None and record['operation'] != expected_operation:
            raise InventoryError('idempotency_conflict','Request ID already names another operation.')
        if arguments is not None and any(record['payload'].get(k) != v for k,v in arguments.items() if k != '_request'):
            raise InventoryError('idempotency_conflict','Request ID already binds different immutable inputs.')
        return self.envelope(record['operation'],record)

    def _owned(self, actor, record, authorize=None, *, capability='observe'):
        self._authorize(actor, record['target'], capability, authorize)
        if identity(actor) not in [record['principal'], *record.get('successors', [])]: raise AuthError('insufficient_scope')
        return record

    @staticmethod
    def projection(record):
        return {k: v for k, v in record.items() if k not in ('payload', 'principal', 'successors', 'authorization', 'fingerprint', '_revision')}

    def envelope(self, operation, record, **extra):
        return dict(schema_version=1, operation=operation, status='completed',
            result=dict(operation=self.projection(record), **extra))

    def _protective_timestamp(self):
        try:
            return self.now()
        except AuthError as error:
            if error.code != 'qualified_time_unavailable':
                raise
            return None

    def execute_local_stop(self, capability, arguments, *, dispatch):
        """One exact synchronous local stop; no transferable or renewable grant."""
        root = _private_local_root(self.root)
        expected = _LOCAL_STOPS.pop(capability, None) if isinstance(capability, _LocalStopCapability) else None
        if expected != encoded(dict(root=str(root), uid=os.getuid(), arguments=arguments)):
            raise AuthError('insufficient_scope')
        meta = arguments['_request']
        target = arguments['expected_target']
        principal = dict(issuer='local://uid/'+str(os.getuid()), resource='wake:controller',
            subject='uid:'+str(os.getuid()), client_id='local-cli', grant_id='local-cli')
        payload = {key:value for key,value in arguments.items() if key != '_request'}
        intent = dict(operation='daemons.stop', payload=payload, correlation_id=meta['correlation_id'], binding=meta['binding'], target=target)
        raw = encoded(intent)
        if len(raw.encode()) > 262144:
            raise InventoryError('invalid_argument', 'operation intent exceeds bounded capacity')
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        intent_key = hashlib.sha256(encoded(dict(principal=principal, key=meta['idempotency_key'])).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT fingerprint,record FROM operations WHERE intent_key=?', (intent_key,)).fetchone()
            if previous:
                old = json.loads(previous[1])
                if previous[0] != fingerprint or old['principal'] != principal or old['operation_id'] != meta['operation_id']:
                    raise InventoryError('idempotency_conflict', 'intent key already binds different immutable stop inputs')
                return self.envelope('daemons.stop', old)
            if db.execute('SELECT COUNT(*) FROM operations').fetchone()[0] >= 10000:
                raise InventoryError('capacity', 'retained operation capacity reached')
            stamp = self._protective_timestamp()
            record = dict(schema_version=1, operation_id=meta['operation_id'], operation='daemons.stop',
                correlation_id=meta['correlation_id'], binding=meta['binding'], original_binding=meta['binding'], target=target,
                principal=principal, authorization=dict(scopes=['control','observe'], targets=[target]),
                payload=payload, payload_sha256=hashlib.sha256(encoded(payload).encode()).hexdigest(),
                created_at=stamp, submission='admitted', execution='unknown', delivery='uncertain', acceptance='unknown',
                phase='dispatching', reason='dispatch_in_progress_or_interrupted', result=None, cancellation='not_requested')
            if stamp is None:
                record['created_at_status'] = 'not_observed'
            try:
                db.execute('INSERT INTO operations VALUES(?,?,?,?)', (meta['operation_id'], intent_key, fingerprint, encoded(record)))
            except sqlite3.IntegrityError:
                raise InventoryError('idempotency_conflict', 'operation ID already names another immutable intent') from None
        self._event(record, 'admitted', dict(kind='admitted', operation_id=record['operation_id'], correlation_id=record['correlation_id']))
        try:
            _private_local_root(root)
            # The daemon owner still revalidates confirmation, target, lock and selected build.
            value = dispatch('daemons.stop', payload)
            if len(encoded(value).encode()) > 262144:
                raise ValueError('effect result exceeds retained bound')
            record.update(execution='completed', delivery='retained', acceptance='owner_reported', phase='terminal', reason=None, result=value)
            self._event(record, 'completed', dict(kind='terminal', operation_id=record['operation_id']))
        except Exception as error:
            record.update(execution='unknown', delivery='uncertain', reason=getattr(error,'code','effect_uncertain'), phase='uncertain')
        self._save(record)
        return self.envelope('daemons.stop', record)

    def execute(self, actor, operation, arguments, *, authorize, dispatch, required_capability=None):
        if not isinstance(arguments, dict) or not isinstance(arguments.get('_request'), dict):
            raise InventoryError('intent_required', 'explicit _request operation/idempotency/correlation/binding/target metadata required')
        meta = arguments['_request']
        if set(meta) != {'operation_id', 'idempotency_key', 'correlation_id', 'binding', 'target'}:
            raise InventoryError('invalid_argument', 'unsupported request metadata; caller identity is authenticated separately')
        for key in ('operation_id', 'idempotency_key', 'correlation_id', 'binding'): bounded_id(meta[key])
        payload = {k: v for k, v in arguments.items() if k != '_request'}
        target = meta['target']
        if 'expected_target' in payload and payload['expected_target'] != target:
            raise InventoryError('stale_target', 'request target differs from pinned owner target')
        capability = required_capability or ('recovery' if operation.startswith('recovery.') else
            'admin' if operation in ('builds.stage', 'builds.select', 'builds.rollback', 'migration.apply', 'migration.rollback') else 'control')
        self._authorize(actor, target, capability, authorize)
        intent = dict(operation=operation, payload=payload, correlation_id=meta['correlation_id'], binding=meta['binding'], target=target)
        raw = encoded(intent)
        if len(raw.encode()) > 262144: raise InventoryError('invalid_argument', 'operation intent exceeds bounded capacity')
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        intent_key = hashlib.sha256(encoded(dict(principal=identity(actor), key=meta['idempotency_key'])).encode()).hexdigest()
        record = dict(schema_version=1, operation_id=meta['operation_id'], operation=operation,
            correlation_id=meta['correlation_id'], binding=meta['binding'], original_binding=meta['binding'], target=target,
            principal=identity(actor), authorization=dict(scopes=sorted(actor.scopes), targets=actor.targets),
            payload=payload, payload_sha256=hashlib.sha256(encoded(payload).encode()).hexdigest(),
            created_at=self.now(), submission='admitted', execution='unknown', delivery='uncertain', acceptance='unknown',
            phase='dispatching', reason='dispatch_in_progress_or_interrupted', result=None, cancellation='not_requested')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT fingerprint,record FROM operations WHERE intent_key=?', (intent_key,)).fetchone()
            if previous:
                if previous[0] != fingerprint: raise InventoryError('idempotency_conflict', 'intent key already binds different immutable inputs')
                old = json.loads(previous[1]); self._owned(actor, old, authorize, capability=capability)
                return self.envelope(operation, old)
            if db.execute('SELECT COUNT(*) FROM operations').fetchone()[0] >= 10000:
                raise InventoryError('capacity', 'retained operation capacity reached')
            try: db.execute('INSERT INTO operations VALUES(?,?,?,?)', (meta['operation_id'], intent_key, fingerprint, encoded(record)))
            except sqlite3.IntegrityError: raise InventoryError('idempotency_conflict', 'operation ID already names another immutable intent')
        self._event(record, 'admitted', {'kind': 'admitted', 'operation_id': record['operation_id'], 'correlation_id': record['correlation_id']})
        dispatched = False
        try:
            self._authorize(actor, target, capability, authorize)
            dispatched = True
            value = dispatch(operation, payload)
            if len(encoded(value).encode()) > 262144: raise ValueError('effect result exceeds retained bound')
            if isinstance(value, dict) and value.get('_pending') is True:
                record.update(execution='queued', delivery='submitted', acceptance='pending', phase='waiting', reason=None, result=value['handle'])
            else:
                record.update(execution='completed', delivery='retained', acceptance='owner_reported', phase='terminal', reason=None, result=value)
            self._event(record, 'submitted' if record['phase'] == 'waiting' else 'completed', {'kind': record['phase'], 'operation_id': record['operation_id']})
        except Exception as error:
            record.update(execution='unknown' if dispatched else 'not_started', delivery='uncertain' if dispatched else 'not_submitted',
                reason=getattr(error, 'code', 'effect_uncertain'), phase='uncertain' if dispatched else 'terminal')
        self._save(record)
        if record.get('revocation') and record['phase'] != 'terminal':
            self.revoke_grant(record['principal']['grant_id'], issuer=record['principal']['issuer'], resource=record['principal']['resource'])
            record = self._load(record['operation_id'])
        # Grant loss can prevent delivery, never erase effect admission/result custody.
        self._authorize(actor, target, capability, authorize)
        return self.envelope(operation, record)

    def _refresh(self, actor, record, authorize):
        if self.adapter is None or record['phase']=='terminal':return record
        if record['operation'] in ('sessions.prompt','grok.prompt','grok.create','grok.load') and hasattr(self.adapter,'observe_native_owned'):
            self._owned(actor,record,authorize)
            try:
                self.adapter.observe_native_owned(record)
            except (ValueError,OSError) as error:
                record.update(phase='uncertain',execution='unknown',reason=getattr(error,'code','native_owner_unavailable'))
            self._save(record)
            if record['phase']=='terminal' and record.get('answer') is not None:
                self._event(record,'native_terminal',dict(kind='answer',**record['answer']))
            self._owned(actor,record,authorize)
            return record
        if record['operation']!='operations.send':return record
        self._owned(actor, record, authorize)
        if record['result'] is None:
            handle = self.adapter.reconcile(actor, record)
            if handle is None: return record
            record.update(result=handle, phase='waiting', execution='queued', delivery='submitted', acceptance='pending', reason=None)
        for reply in self.adapter.poll(actor, record):
            key = 'reply:' + reply['reply_id']
            final = reply['kind'] == 'result'
            self._event(record, key, dict(kind='answer' if final else 'progress', **{k: v for k, v in reply.items() if k != 'kind'}))
            if final:
                record.update(execution=reply.get('execution', 'completed'), delivery='retained', acceptance='answer_received', phase='terminal',
                    answer=reply, reason=None)
                break
        self._save(record)
        self._owned(actor, record, authorize)
        return record

    def _wait(self, actor, record, authorize, timeout):
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise InventoryError('invalid_argument', 'caller wait timeout must be zero to thirty seconds')
        # Caller waiting is advisory; _owned retains genuine authorization checks.
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if deadline is not None and (deadline - time.monotonic()) <= 0: return record, 'timeout'
            record = self._refresh(actor, self._owned(actor, self._load(record['operation_id']), authorize), authorize)
            remaining = (deadline - time.monotonic()) if deadline is not None else None
            if remaining is not None and remaining <= 0: return record, 'timeout'
            if record['phase'] == 'terminal': return record, 'completed'
            if remaining is None: return record, 'timeout'
            time.sleep(min(.05, remaining))

    def operation(self, actor, operation, arguments, *, authorize, expected_operation=None):
        if not isinstance(arguments, dict): raise InventoryError('invalid_argument', 'object arguments required')
        if operation == 'operations.send':
            if self.adapter is None: raise InventoryError('unsupported_operation', 'host send adapter unavailable')
            allowed = {'_request', 'sender_binding', 'expected_target', 'body', 'delivery', 'queue', 'ttl',
                       'response_requested', 'wait_timeout', 'backend', 'job_profile'}
            if set(arguments) - allowed: raise InventoryError('invalid_argument', 'unsupported send arguments; native identity is host-authenticated')
            response = arguments.get('response_requested', True)
            if type(response) is not bool: raise InventoryError('invalid_argument', 'response_requested must be Boolean')
            meta = arguments.get('_request')
            if not isinstance(meta, dict): raise InventoryError('intent_required', 'explicit _request metadata required')
            self._authorize(actor, meta.get('target'), 'control', authorize)
            payload = {k: v for k, v in arguments.items() if k not in ('_request', 'response_requested', 'wait_timeout')}
            payload.setdefault('backend', 'mailbox')
            if payload['backend'] == 'mailbox':
                payload.setdefault('delivery', 'notify'); payload.setdefault('queue', False); payload.setdefault('ttl', 86400)
                if type(payload['queue']) is not bool or payload['delivery'] not in ('inbox', 'notify') or (payload['delivery'] == 'inbox') != payload['queue']:
                    raise InventoryError('invalid_argument', 'inbox queueing requires explicit queue=true; notifications never imply offline queue permission')
                if not isinstance(payload.get('body'), str) or not 0 < len(payload['body'].encode()) <= 32768:
                    raise InventoryError('invalid_argument', 'message body must contain one to32768 UTF8 bytes')
                if type(payload['ttl']) not in (int, float) or not 0 < payload['ttl'] <= 604800:
                    raise InventoryError('invalid_argument', 'explicit queue TTL must be positive and at most seven days')
            elif payload['backend'] != 'job': raise InventoryError('unsupported_operation', 'unsupported effect owner backend')
            prepared = self.adapter.prepare(actor, payload)
            submitted = self.execute(actor, operation, dict(prepared, _request=meta), authorize=authorize,
                dispatch=lambda _operation, inputs: self.adapter.send(actor, inputs, meta['operation_id'], meta['correlation_id']))
            record = self._load(submitted['result']['operation']['operation_id'])
            if response:
                record, wait_status = self._wait(actor, record, authorize, arguments.get('wait_timeout', 30))
                return self.envelope(operation, record, wait=dict(status=wait_status, ends_work=False))
            return self.envelope(operation, record)
        allowed = {
            'operations.result': {'operation_id'}, 'operations.wait': {'operation_id', 'timeout'},
            'operations.stream': {'operation_id', 'cursor', 'limit', 'timeout'},
            'operations.cancel': {'operation_id'}, 'operations.rebind': {'operation_id', 'successor', 'binding'}}
        if operation not in allowed: raise InventoryError('unsupported_operation', 'unsupported runtime operation')
        if set(arguments) - allowed[operation] or 'operation_id' not in arguments:
            raise InventoryError('invalid_argument', 'unsupported operation arguments')
        capability = 'control' if operation in ('operations.cancel', 'operations.rebind') else 'observe'
        record = self._owned(actor, self._load(arguments['operation_id']), authorize, capability=capability)
        if expected_operation is not None and record['operation']!=expected_operation:
            raise InventoryError('unsupported_operation','original operation belongs to another effect owner')
        if operation == 'operations.cancel':
            if record['phase'] == 'terminal': return self.envelope(operation, record)
            if record['operation'] in ('sessions.prompt','grok.prompt') and self.adapter is not None and hasattr(self.adapter,'cancel_native_owned'):
                record['cancellation']=self.adapter.cancel_native_owned(record)
                if record['cancellation']=='confirmed' and record['phase']!='terminal':
                    record.update(execution='cancelled',phase='terminal',delivery='retained',acceptance='cancelled')
            elif self.adapter is None or record['operation'] != 'operations.send' or record['result'] is None:
                record['cancellation'] = 'uncertain'
            else:
                record['cancellation'] = self.adapter.cancel(actor, record)
                if record['cancellation'] == 'confirmed':
                    record.update(execution='cancelled', phase='terminal', delivery='retained', acceptance='cancelled')
            self._save(record, update_owner=True)
            self._event(record, 'cancel', {'kind': 'cancellation', 'status': record['cancellation']})
            self._owned(actor, record, authorize, capability='control')
            return self.envelope(operation, record)
        if operation == 'operations.rebind':
            successor = arguments.get('successor')
            if not isinstance(successor, dict) or set(successor) != set(record['principal']):
                raise InventoryError('invalid_argument', 'explicit authenticated successor identity reference required')
            if any(successor[k] != record['principal'][k] for k in ('issuer', 'resource', 'subject', 'client_id')):
                raise AuthError('insufficient_scope')
            bounded_id(successor['grant_id']); bounded_id(arguments.get('binding'))
            if successor not in record.get('successors', []):
                record.setdefault('successors', []).append(successor)
                if len(record['successors']) > 8: raise InventoryError('capacity', 'explicit successor bound reached')
            record['binding'] = arguments['binding']
            self._save(record, update_owner=True)
            self._event(record, 'rebind:' + successor['grant_id'], {'kind': 'rebound', 'binding': record['binding']})
            return self.envelope(operation, record)
        if operation == 'operations.wait':
            record, status = self._wait(actor, record, authorize, arguments.get('timeout', 30))
            self._owned(actor, record, authorize)
            return self.envelope(operation, record, wait=dict(status=status, ends_work=False))
        if operation == 'operations.stream':
            cursor, limit, timeout = arguments.get('cursor', 0), arguments.get('limit', 100), arguments.get('timeout', 0)
            if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 100 or type(timeout) not in (int, float) or not 0 <= timeout <= 30:
                raise InventoryError('invalid_argument', 'bounded nonnegative stream cursor/limit/timeout required')
            deadline = time.monotonic() + timeout if timeout else None
            record = self._refresh(actor, record, authorize)
            while True:
                remaining = (deadline - time.monotonic()) if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    events = []
                    break
                with self.connect() as db:
                    rows = db.execute('SELECT payload FROM events WHERE operation_id=? AND sequence>? ORDER BY sequence LIMIT ?', (record['operation_id'], cursor, limit)).fetchall()
                events = [json.loads(row[0]) for row in rows]
                remaining = (deadline - time.monotonic()) if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    events = []
                    break
                if events or record['phase'] == 'terminal' or remaining is None: break
                time.sleep(min(.05, remaining))
                record = self._refresh(actor, self._owned(actor, self._load(record['operation_id']), authorize), authorize)
            self._owned(actor, record, authorize)
            if deadline is not None and (deadline - time.monotonic()) <= 0: events = []
            return self.envelope(operation, record, events=events, next_cursor=events[-1]['sequence'] if events else cursor,
                stream=dict(mode='bounded_correlated_events', token_stream=False))
        record = self._refresh(actor, record, authorize)
        return self.envelope(operation, record)


    def revoke_grant(self, grant_id, *, issuer, resource):
        """Private authority hook; never exposed as a caller-selected operation.

        The authority has already revoked access. Use only original host/native
        cancellation ownership; no replacement OAuth principal or work is minted.
        """
        bounded_id(grant_id)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO revoked_grants VALUES(?,?,?,?)',(issuer,resource,grant_id,self._protective_timestamp()))
            pending=[];remaining=0
            for row in db.execute('SELECT record FROM operations'):
                record=json.loads(row[0])
                if (record['principal']['issuer'],record['principal']['resource'],record['principal']['grant_id'])!=(issuer,resource,grant_id) or record['phase']=='terminal' or record['cancellation'] in ('confirmed','requested'):continue
                if len(pending)<100:pending.append(record)
                else:remaining+=1
        outcomes=[]
        for record in pending:
            if record['cancellation'] in ('confirmed','requested'):
                outcomes.append(dict(operation_id=record['operation_id'],cancellation=record['cancellation']));continue
            try:
                if record['operation'] in ('sessions.prompt','grok.prompt') and self.adapter is not None and hasattr(self.adapter,'cancel_native_owned'):
                    cancellation=self.adapter.cancel_native_owned(record)
                elif self.adapter is None or record['operation']!='operations.send':
                    cancellation='uncertain'
                else:
                    if record['result'] is None:
                        handle=self.adapter.reconcile_owned(record)
                        if handle is not None: record['result']=handle
                    cancellation=self.adapter.cancel_owned(record) if record['result'] is not None else 'uncertain'
                record['cancellation']=cancellation
                record['revocation']=dict(grant_id=grant_id,status='cancellation_'+cancellation)
                if cancellation=='confirmed' and record['phase']!='terminal':record.update(execution='cancelled',phase='terminal',delivery='retained',acceptance='cancelled')
            except (ValueError,OSError,KeyError) as error:
                record['cancellation']='uncertain';record['revocation']=dict(grant_id=grant_id,status='cancellation_uncertain',reason=getattr(error,'code','owner_unavailable'))
            self._save(record,update_owner=True)
            self._event(record,'grant_revoked',{'kind':'grant_revoked','cancellation':record['cancellation']})
            outcomes.append(dict(operation_id=record['operation_id'],cancellation=record['cancellation']))
        return dict(grant_id=grant_id,status='revoked',cancellation='reconciled' if outcomes else 'no_owned_active_work',
            operations=outcomes,remaining=remaining,uncertain_effects=[r['operation_id'] for r in outcomes if r['cancellation']=='uncertain'])
