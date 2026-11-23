"""Durable human attention; responses are data, never execution or new grants."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid

from .a2a_bus import private_path
from .records import WakeError
from .session_permissions import PermissionStore, Principal, check_operation

MAX_BYTES = 4 * 1024 * 1024
CONTEXT_FIELDS = frozenset(('owner', 'operation_id', 'attempt', 'task_id',
    'allocation_id', 'runtime', 'conversation_id', 'account', 'target', 'action',
    'effect_scope', 'policy_root', 'policy_revision', 'operation_state'))
STATUSES = frozenset(('open', 'responded', 'consumed', 'closed', 'unknown'))


class AttentionError(WakeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _fail(code, message):
    raise AttentionError(code, message)


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _copy(value):
    return json.loads(_encoded(value))


def fingerprint(value):
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate state field')
        result[key] = value
    return result


def _context(value, *, task_optional=False):
    if type(value) is not dict or set(value) != CONTEXT_FIELDS:
        _fail('context_invalid', 'exact operation context required')
    for key in CONTEXT_FIELDS - {'attempt', 'policy_revision'}:
        if key == 'task_id' and task_optional and value[key] is None:
            continue
        if type(value[key]) is not str or not value[key] or len(value[key]) > 2048:
            _fail('context_invalid', 'operation context fields must be bounded nonempty strings')
    for key in ('attempt', 'policy_revision'):
        if type(value[key]) is not int or value[key] < 1:
            _fail('context_invalid', 'positive attempt and policy revision required')
    return _copy(value)


class AttentionQueue:
    """One private queue. context_validator is a trusted feature-owner hook.

    The hook receives a retained request and returns freshly observed exact
    context. Never connect it directly to caller-supplied JSON or fingerprints.
    It runs while the queue lock is held and must not re-enter this queue.
    """
    def __init__(self, root, *, now=time.time, context_validator=None):
        self.root = Path(root).absolute()
        if self.root != self.root.resolve():
            _fail('store_unavailable', 'canonical Wake root required')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            _fail('store_unavailable', 'owned Wake root not writable by others required')
        self.directory = self.root / 'attention'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        private_path(self.directory, directory=True)
        self.path = self.directory / 'queue.json'
        self.marker = self.directory / 'initialized'
        self.lock_path = self.directory / 'queue.lock'
        self.now, self.context_validator = now, context_validator

    @contextmanager
    def _transaction(self, *, write=False):
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a+') as lock:
            private_path(self.lock_path)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _fail('attention_busy', 'another attention transition holds the queue')
            exists = self.path.exists() or self.path.is_symlink()
            if exists:
                private_path(self.path)
                try:
                    with self.path.open() as source:
                        raw = source.read(MAX_BYTES + 1)
                    state = json.loads(raw, object_pairs_hook=_unique)
                    if len(raw.encode()) > MAX_BYTES:
                        raise ValueError('oversized state')
                    self._validate(state)
                except (ValueError, TypeError, KeyError, AttentionError):
                    _fail('store_unavailable', 'unknown or malformed queue retained without changes')
            else:
                if self.marker.exists() or self.marker.is_symlink():
                    _fail('store_unavailable', 'initialized queue is missing; explicit recovery required')
                state = dict(version=1, requests=[])
            if self.marker.exists() or self.marker.is_symlink():
                private_path(self.marker)
            else:
                fd = os.open(self.marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            if not exists:
                self._publish(state)
            yield state
            if write:
                self._validate(state)
                self._publish(state)

    def _publish(self, state):
        body = _encoded(state)
        if len(body.encode()) > MAX_BYTES:
            _fail('store_full', 'attention capacity reached; history retained')
        fd, temporary = tempfile.mkstemp(prefix='.queue-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as out:
                out.write(body)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
            descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _validate(state):
        if (type(state) is not dict or set(state) != {'version', 'requests'}
                or type(state['version']) is not int or state['version'] != 1
                or type(state['requests']) is not list):
            raise ValueError('unknown queue schema')
        ids, keys = set(), set()
        for row in state['requests']:
            fields = {'request_id', 'revision', 'status', 'created_at', 'request',
                'fingerprint', 'response', 'history'}
            if type(row) is not dict or set(row) != fields:
                raise ValueError('unknown request schema')
            request = row['request']
            AttentionQueue._request_shape(request)
            if (row['request_id'] in ids or request['key'] in keys
                    or type(row['request_id']) is not str or not row['request_id'].startswith('attention_')
                    or row['fingerprint'] != fingerprint(request)
                    or row['status'] not in STATUSES or type(row['revision']) is not int
                    or type(row['history']) is not list or row['revision'] != len(row['history'])
                    or not row['history']):
                raise ValueError('invalid request authority')
            if row['status'] in ('responded', 'consumed') and type(row['response']) is not dict:
                raise ValueError('missing response')
            if type(row['created_at']) not in (int, float) or not math.isfinite(row['created_at']):
                raise ValueError('invalid creation time')
            events = row['history']
            for index, event in enumerate(events):
                if type(event) is not dict or event.get('event') not in ('requested', 'responded', 'consumed', 'closed', 'unknown'):
                    raise ValueError('invalid history event')
                expected = {'event', 'actor', 'at'}
                if event['event'] in ('responded', 'consumed'):
                    expected.add('response_id')
                if event['event'] in ('closed', 'unknown'):
                    expected.add('reason')
                if (set(event) != expected or type(event['actor']) is not str or not event['actor']
                        or type(event['at']) not in (int, float) or not math.isfinite(event['at'])
                        or (index == 0 and event['event'] != 'requested')
                        or (index > 0 and event['event'] == 'requested')):
                    raise ValueError('invalid transition history')
            if events[-1]['event'] != {'open':'requested', 'responded':'responded', 'consumed':'consumed',
                    'closed':'responded' if request['kind']=='notice' and events[-1]['event']=='responded' else 'closed', 'unknown':'unknown'}[row['status']]:
                raise ValueError('state and history disagree')
            response = row['response']
            if response is not None:
                if (type(response) is not dict or set(response) != {'response_id', 'choice', 'actor', 'at',
                        'request_revision', 'fingerprint', 'approval'}
                        or response['choice'] not in request['options'] or type(response['actor']) is not str
                        or not response['actor'] or type(response['at']) not in (int, float)
                        or not math.isfinite(response['at']) or response['fingerprint'] != row['fingerprint']
                        or type(response['request_revision']) is not int or response['request_revision'] != 1
                        or type(response['response_id']) is not str or not response['response_id'].startswith('response_')):
                    raise ValueError('invalid response authority')
                matches = [event for event in events if event['event'] == 'responded']
                if (len(matches) != 1 or matches[0]['response_id'] != response['response_id']
                        or matches[0]['actor'] != response['actor'] or matches[0]['at'] != response['at']):
                    raise ValueError('response attribution differs from history')
                approval = response['approval']
                if approval is not None and (type(approval) is not dict or set(approval) != {'approval_id', 'policy_revision'}
                        or type(approval['approval_id']) is not str or not approval['approval_id']
                        or type(approval['policy_revision']) is not int or approval['policy_revision'] < 1):
                    raise ValueError('invalid approval reference')
                if request['permission_decision'] and response['choice'] == 'accept' and approval is None:
                    raise ValueError('missing common approval reference')
            elif any(event['event'] in ('responded', 'consumed') for event in events):
                raise ValueError('missing historical response')
            ids.add(row['request_id'])
            keys.add(request['key'])

    @staticmethod
    def _request_shape(request):
        required = {'key', 'kind', 'question', 'options', 'evidence', 'priority',
            'expires_at', 'context', 'permission_decision'}
        if type(request) is not dict or set(request) != required:
            _fail('request_invalid', 'unsupported request fields')
        for key in ('key', 'question'):
            if type(request[key]) is not str or not request[key] or len(request[key]) > 4096:
                _fail('request_invalid', 'bounded key and question required')
        if request['kind'] not in ('notice', 'decision') or request['priority'] not in ('low', 'normal', 'high', 'urgent'):
            _fail('request_invalid', 'unsupported kind or priority')
        if (type(request['expires_at']) not in (float, int) or not math.isfinite(request['expires_at'])
                or type(request['permission_decision']) is not bool):
            _fail('request_invalid', 'finite expiry and permission classification required')
        for key in ('options', 'evidence'):
            if (type(request[key]) is not list or not 1 <= len(request[key]) <= 32
                    or any(type(v) is not str or not v or len(v) > 4096 for v in request[key])
                    or len(set(request[key])) != len(request[key])):
                _fail('request_invalid', 'bounded distinct options and evidence references required')
        if request['kind'] == 'notice' and (request['options'] != ['acknowledge'] or request['permission_decision']):
            _fail('request_invalid', 'notices may only be acknowledged and grant nothing')
        if request['kind'] == 'decision' and request['options'] != ['accept', 'decline']:
            _fail('request_invalid', 'decision options are accept and decline')
        _context(request['context'], task_optional=request['kind'] == 'notice')

    @staticmethod
    def _owner(principal, row):
        if not isinstance(principal, Principal):
            _fail('identity_unverified', 'verified principal required')
        if principal.role != 'operator' and principal.subject != row['request']['context']['owner']:
            _fail('attention_owner_required', 'request belongs to another owner')

    def _permission(self, action, principal, row):
        context = row['request']['context']
        check_operation(self.root, action, principal, task_id=context['task_id'],
            operation_id=context['operation_id'])

    def _current_policy(self, row):
        if self.now() >= row['request']['expires_at']:
            _fail('attention_expired', 'original attention expiry reached')
        store = PermissionStore(self.root)
        context = row['request']['context']
        if store.active():
            if str(store.root) != context['policy_root'] or store._read()['revision'] != context['policy_revision']:
                _fail('attention_policy_changed', 'current policy differs from retained request')

    def _live(self, row):
        self._current_policy(row)
        if self.context_validator is None:
            _fail('context_unavailable', 'trusted feature-owner context validator required')
        live = _context(self.context_validator(_copy(row)))
        if live != row['request']['context']:
            _fail('attention_stale', 'current operation context differs from retained request')
        if live['operation_state'] != 'blocked':
            _fail('operation_unknown', 'only positively blocked unsubmitted operations may proceed')

    @staticmethod
    def _find(state, identifier):
        for row in state['requests']:
            if row['request_id'] == identifier:
                return row
        _fail('attention_not_found', 'attention request not found')

    def _event(self, row, event, principal, **details):
        row['history'].append(dict(event=event, actor=principal.subject, at=self.now(), **details))
        row['revision'] = len(row['history'])

    def request(self, principal, request):
        self._request_shape(request)
        row = dict(request_id='attention_' + uuid.uuid4().hex, revision=0, status='open',
            created_at=self.now(), request=_copy(request), fingerprint=fingerprint(request), response=None, history=[])
        self._owner(principal, row)
        with self._transaction(write=True) as state:
            for old in state['requests']:
                if old['request']['key'] == request['key']:
                    self._owner(principal, old)
                    if old['fingerprint'] != row['fingerprint']:
                        _fail('attention_key_conflict', 'idempotency key already names another request')
                    return _copy(old)
            self._permission('attention.request', principal, row)
            self._current_policy(row)
            if request['kind'] == 'decision' and self.context_validator is not None:
                self._live(row)
            self._event(row, 'requested', principal)
            state['requests'].append(row)
            return _copy(row)

    def inspect(self, principal, request_id=None, *, include_closed=False):
        with self._transaction() as state:
            if request_id is not None:
                row = self._find(state, request_id)
                self._owner(principal, row)
                return _copy(row)
            if not isinstance(principal, Principal):
                _fail('identity_unverified', 'verified principal required')
            return dict(status='attention', requests=[_copy(row) for row in state['requests']
                if (principal.role == 'operator' or row['request']['context']['owner'] == principal.subject)
                and (include_closed or row['status'] in ('open', 'responded', 'unknown'))])

    @staticmethod
    def _expected(row, revision, digest):
        if type(revision) is not int or revision != row['revision'] or digest != row['fingerprint']:
            _fail('attention_revision_conflict', 'inspect current revision and fingerprint first')

    def _approval(self, row, approval_id):
        context = row['request']['context']
        principal = Principal(context['owner'], tasks=(context['task_id'],))
        result = PermissionStore(self.root, now=self.now).evaluate(context['action'], principal,
            target=context['target'], relationship='shared' if context['action'] == 'refresh.shared' else None,
            task_id=context['task_id'], operation_id=context['operation_id'])
        if not approval_id or result['permission'] != 'allow' or result['approval_id'] != approval_id:
            _fail('attention_approval_required', 'existing matching common permission approval required')
        return dict(approval_id=approval_id, policy_revision=result['revision'])

    def respond(self, principal, request_id, choice, *, expected_revision, expected_fingerprint, approval_id=None):
        if not isinstance(principal, Principal) or principal.role != 'operator':
            _fail('attention_operator_required', 'response requires verified local operator')
        with self._transaction(write=True) as state:
            row = self._find(state, request_id)
            self._expected(row, expected_revision, expected_fingerprint)
            if row['status'] != 'open' or choice not in row['request']['options']:
                _fail('attention_not_open', 'request is closed or response is unsupported')
            self._permission('attention.respond', principal, row)
            self._current_policy(row)
            if row['request']['kind'] == 'decision' and self.context_validator is not None:
                self._live(row)
            approval = None
            if row['request']['permission_decision'] and choice == 'accept':
                approval = self._approval(row, approval_id)
            row['response'] = dict(response_id='response_' + uuid.uuid4().hex, choice=choice,
                actor=principal.subject, at=self.now(), request_revision=row['revision'],
                fingerprint=row['fingerprint'], approval=approval)
            row['status'] = 'closed' if row['request']['kind'] == 'notice' else 'responded'
            self._event(row, 'responded', principal, response_id=row['response']['response_id'])
            row['response']['at'] = row['history'][-1]['at']
            return _copy(row)

    def consume(self, principal, request_id, *, expected_revision, expected_fingerprint):
        with self._transaction(write=True) as state:
            row = self._find(state, request_id)
            self._owner(principal, row)
            self._expected(row, expected_revision, expected_fingerprint)
            if row['status'] != 'responded' or row['request']['kind'] != 'decision':
                _fail('attention_not_consumable', 'response already consumed or unavailable')
            self._permission('attention.consume', principal, row)
            self._live(row)
            response = row['response']
            if row['request']['permission_decision'] and response['choice'] == 'accept':
                self._approval(row, response['approval']['approval_id'])
            row['status'] = 'consumed'
            self._event(row, 'consumed', principal, response_id=response['response_id'])
            return dict(status='consumed', request_id=request_id, revision=row['revision'],
                fingerprint=row['fingerprint'], choice=response['choice'], response_id=response['response_id'],
                context=_copy(row['request']['context']), executes_operation=False, grants_permission=False)

    def close(self, principal, request_id, *, expected_revision, expected_fingerprint, disposition, reason):
        if disposition not in ('closed', 'unknown') or type(reason) is not str or not reason or len(reason) > 4096:
            _fail('request_invalid', 'explicit closed/unknown disposition and bounded reason required')
        with self._transaction(write=True) as state:
            row = self._find(state, request_id)
            self._owner(principal, row)
            self._expected(row, expected_revision, expected_fingerprint)
            if row['status'] in ('closed', 'consumed'):
                _fail('attention_closed', 'terminal history cannot be reopened')
            self._permission('attention.consume', principal, row)
            row['status'] = disposition
            self._event(row, disposition, principal, reason=reason)
            return _copy(row)
