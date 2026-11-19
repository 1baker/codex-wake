"""Approved task scope and durable assignment pins.

Authorities are supplied by a trusted native/host or capability adapter. A model
argument naming a role is never an authority. This module does not issue grants.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .a2a_bus import private_path
from . import measurements
from .records import WakeError


MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_BRIEF_BYTES = 65536
MAX_CONTEXT_BYTES = 1024 * 1024
MAX_REVISIONS = 256
MAX_ASSIGNMENTS = 4096
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}')
_SHA256 = re.compile(r'[0-9a-f]{64}')


class TaskBriefError(WakeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _identifier(value, label='identifier'):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise TaskBriefError('invalid_argument', f'{label} is invalid')
    return value


def _text(value, label, limit=4096):
    if type(value) is not str or not value.strip() or len(value.encode()) > limit or '\x00' in value:
        raise TaskBriefError('invalid_argument', f'{label} must be bounded nonempty text')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _copy(value):
    return json.loads(_json(value))


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _now():
    try:
        return measurements.datetime_now().isoformat()
    except measurements.TimeUnavailable:
        raise TaskBriefError('qualified_time_unavailable', 'qualified Stable Time is required for task metadata') from None


@dataclass(frozen=True)
class BriefAuthority:
    """A trusted adapter's verified actor and delegated exact task scope."""
    actor_id: str
    role: str
    task_ids: tuple[str, ...] = ()
    workspace: str | None = None

    def __post_init__(self):
        _identifier(self.actor_id, 'actor identity')
        if self.role not in {'operator', 'controller', 'worker'}:
            raise TaskBriefError('authority_denied', 'unsupported brief authority')
        if type(self.task_ids) is not tuple or len(self.task_ids) > 256:
            raise TaskBriefError('authority_denied', 'invalid delegated task scope')
        for task_id in self.task_ids:
            _identifier(task_id, 'delegated task')

    def require(self, task_id, *, approval=False):
        if self.role == 'operator':
            return
        if task_id not in self.task_ids or (approval and self.role != 'controller'):
            raise TaskBriefError('authority_denied', 'caller lacks the required exact task authority')

    def require_workspace(self, content):
        if (self.workspace is not None
                and not Path(content['workspace']).resolve().is_relative_to(Path(self.workspace).resolve())):
            raise TaskBriefError('authority_denied', 'brief workspace is outside the caller workspace')


def _brief(content):
    fields = {'objective', 'phase', 'non_goals', 'acceptance', 'context', 'workspace',
              'allocation_ref', 'permission_ref'}
    if type(content) is not dict or not fields <= set(content) or set(content) - fields - {'dispatch'}:
        raise TaskBriefError('invalid_argument', 'brief fields differ from version 1 contract')
    value = _copy(content)
    if len(_json(value).encode()) > MAX_BRIEF_BYTES:
        raise TaskBriefError('invalid_argument', 'brief exceeds bounded context contract')
    for field in ('objective', 'phase', 'allocation_ref', 'permission_ref'):
        _text(value[field], field)
    for field in ('non_goals', 'acceptance'):
        items = value[field]
        if type(items) is not list or not 1 <= len(items) <= 32:
            raise TaskBriefError('invalid_argument', f'{field} must contain 1 to 32 items')
        for item in items:
            _text(item, field)
    workspace = Path(_text(value['workspace'], 'workspace'))
    if not workspace.is_absolute() or workspace != workspace.resolve() or not workspace.is_dir():
        raise TaskBriefError('invalid_argument', 'workspace must be an existing canonical directory')
    if type(value['context']) is not list or len(value['context']) > 16:
        raise TaskBriefError('invalid_argument', 'context must contain at most 16 references')
    for ref in value['context']:
        if type(ref) is not dict or set(ref) != {'path', 'sha256', 'required'}:
            raise TaskBriefError('invalid_argument', 'context reference fields are invalid')
        path = Path(_text(ref['path'], 'context path'))
        if not path.is_absolute() or path != path.resolve() or not path.is_relative_to(workspace):
            raise TaskBriefError('invalid_argument', 'context paths must be canonical within the workspace')
        if type(ref['required']) is not bool or type(ref['sha256']) is not str or not _SHA256.fullmatch(ref['sha256']):
            raise TaskBriefError('invalid_argument', 'context reference requires a digest and required flag')
    if 'dispatch' in value:
        _dispatch(value['dispatch'], value['context'])
    return value


def _dispatch(options, context):
    if type(options) is not dict or set(options) - {'stop_conditions', 'evidence_summaries', 'history'}:
        raise TaskBriefError('invalid_argument', 'dispatch options are invalid')
    stops = options.get('stop_conditions', [])
    if type(stops) is not list or len(stops) > 32:
        raise TaskBriefError('invalid_argument', 'dispatch stop conditions must be bounded')
    for stop in stops:
        _text(stop, 'stop condition')
    summaries = options.get('evidence_summaries', [])
    if type(summaries) is not list or len(summaries) > 16:
        raise TaskBriefError('invalid_argument', 'dispatch summaries must be bounded')
    from .records import parse_timestamp
    sources = {ref['path']: ref for ref in context}
    for summary in summaries:
        if (type(summary) is not dict or set(summary) != {'path', 'summary', 'observed_at', 'coverage', 'ambiguity'}
                or type(summary.get('path')) is not str or summary['path'] not in sources):
            raise TaskBriefError('invalid_argument', 'summary requires a raw context source and evidence caveats')
        for key in ('summary', 'observed_at', 'coverage', 'ambiguity'):
            _text(summary[key], key)
        parse_timestamp(summary['observed_at'])
    if 'history' in options:
        history = options['history']
        if (type(history) is not dict or set(history) != {'mode', 'reason', 'path'}
                or history.get('mode') != 'full_history'
                or type(history.get('path')) is not str
                or not sources.get(history['path'], {}).get('required')):
            raise TaskBriefError('invalid_argument', 'full history requires a reason and a required context source')
        _text(history['reason'], 'task-specific full-history reason')


def _verify_context(content):
    observations = []
    workspace = Path(content['workspace'])
    for ref in content['context']:
        path = Path(ref['path'])
        status = 'verified'
        try:
            if path != path.resolve(strict=True) or not path.is_relative_to(workspace):
                raise OSError('context path changed')
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as stream:
                import stat
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONTEXT_BYTES:
                    raise OSError('context is not a bounded regular file')
                data = stream.read(MAX_CONTEXT_BYTES + 1)
                if len(data) > MAX_CONTEXT_BYTES:
                    raise OSError('context exceeds bound')
            if hashlib.sha256(data).hexdigest() != ref['sha256']:
                status = 'changed'
        except OSError:
            status = 'unavailable'
        if ref['required'] and status != 'verified':
            raise TaskBriefError('context_' + status, 'required brief evidence is ' + status)
        observations.append(dict(path=ref['path'], status=status, required=ref['required'],
                                 sha256=ref['sha256']))
    return observations


class TaskBriefStore:
    """Single transactional owner of immutable revisions and admitted pins."""
    def __init__(self, root):
        root = Path(root).absolute()
        if root != root.resolve():
            raise TaskBriefError('store_invalid', 'wake root cannot traverse symlinks')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_path(root, directory=True)
        self.directory = root / 'task-briefs'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        private_path(self.directory, directory=True)

    @contextmanager
    def _transaction(self, task_id, *, write=False):
        _identifier(task_id, 'task identity')
        key = hashlib.sha256(task_id.encode()).hexdigest()
        lock_path = self.directory / (key + '.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+') as lock:
            private_path(lock_path)
            fcntl.flock(lock, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            path = self.directory / (key + '.json')
            if path.exists() or path.is_symlink():
                private_path(path)
                if path.stat().st_size > MAX_STATE_BYTES:
                    raise TaskBriefError('store_invalid', 'task brief state exceeds size limit')
                with path.open() as stream:
                    state = json.load(stream)
                if (type(state) is not dict or set(state) != {'version', 'task_id', 'revisions', 'approvals', 'admissions'}
                        or type(state.get('version')) is not int or state['version'] != 1
                        or state['task_id'] != task_id or type(state['revisions']) is not list
                        or type(state['approvals']) is not dict or type(state['admissions']) is not dict):
                    raise TaskBriefError('store_invalid', 'unknown or malformed task brief state')
            else:
                state = dict(version=1, task_id=task_id, revisions=[], approvals={}, admissions={})
            yield state
            if write:
                body = _json(state).encode()
                if len(body) > MAX_STATE_BYTES:
                    raise TaskBriefError('store_invalid', 'task brief state exceeds size limit')
                out, temporary = tempfile.mkstemp(prefix=key + '.', dir=self.directory)
                try:
                    with os.fdopen(out, 'wb') as stream:
                        stream.write(body)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                    directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)

    def propose(self, task_id, content, *, authority):
        authority.require(task_id)
        value = _brief(content)
        authority.require_workspace(value)
        with self._transaction(task_id, write=True) as state:
            if len(state['revisions']) >= MAX_REVISIONS:
                raise TaskBriefError('limit_exceeded', 'task brief revision limit reached')
            revision = dict(revision=len(state['revisions']) + 1, content=value,
                            digest=_digest(value), proposer=authority.actor_id, proposed_at=_now())
            state['revisions'].append(revision)
        return dict(task_id=task_id, status='proposed', **_copy(revision))

    def approve(self, task_id, revision, *, authority):
        authority.require(task_id, approval=True)
        with self._transaction(task_id, write=True) as state:
            self._revision(state, revision)
            key = str(revision)
            if key not in state['approvals']:
                state['approvals'][key] = dict(actor_id=authority.actor_id,
                    role=authority.role, approved_at=_now())
            return dict(task_id=task_id, revision=revision, status='approved',
                        approval=_copy(state['approvals'][key]))

    @staticmethod
    def _revision(state, revision):
        if type(revision) is not int or not 1 <= revision <= len(state['revisions']):
            raise TaskBriefError('brief_not_found', 'task brief revision not found')
        result = state['revisions'][revision - 1]
        if result.get('revision') != revision or result.get('digest') != _digest(result.get('content')):
            raise TaskBriefError('store_invalid', 'task brief revision integrity differs')
        return result

    def inspect(self, task_id, *, authority=None):
        if authority is not None:
            authority.require(task_id)
        with self._transaction(task_id) as state:
            if authority is not None:
                for revision in state['revisions']:
                    authority.require_workspace(revision['content'])
            approved = [int(key) for key in state['approvals']]
            return dict(task_id=task_id, approved_revision=max(approved) if approved else None,
                        revisions=_copy(state['revisions']), approvals=_copy(state['approvals']),
                        admissions=_copy(list(state['admissions'].values())))

    def admit(self, task_id, assignment_id, *, authority, revision=None):
        authority.require(task_id)
        _identifier(assignment_id, 'assignment identity')
        with self._transaction(task_id, write=True) as state:
            request = dict(revision=revision, actor_id=authority.actor_id)
            existing = state['admissions'].get(assignment_id)
            if existing:
                if existing['request'] != request:
                    raise TaskBriefError('assignment_conflict', 'assignment already pins a different admission intent')
                original = self._revision(state, existing['pin']['revision'])
                authority.require_workspace(original['content'])
                return _copy(existing)
            approved = [int(key) for key in state['approvals']]
            selected = revision if revision is not None else (max(approved) if approved else None)
            if selected is None or str(selected) not in state['approvals']:
                raise TaskBriefError('brief_unapproved', 'assignment requires an approved task brief')
            brief = self._revision(state, selected)
            authority.require_workspace(brief['content'])
            context_evidence = _verify_context(brief['content'])
            pin = dict(task_id=task_id, revision=selected, digest=brief['digest'],
                       approval=_copy(state['approvals'][str(selected)]))
            if len(state['admissions']) >= MAX_ASSIGNMENTS:
                raise TaskBriefError('limit_exceeded', 'task assignment limit reached')
            admitted = dict(assignment_id=assignment_id, pin=pin, request=request, actor_id=authority.actor_id,
                            admitted_at=_now(), context_evidence=context_evidence)
            state['admissions'][assignment_id] = admitted
            return _copy(admitted)

    def assignment_pin(self, task_id, assignment_id, *, authority=None):
        """Return the exact restart-safe brief link for a checkpoint/assignment."""
        if authority is not None:
            authority.require(task_id)
        _identifier(assignment_id, 'assignment identity')
        with self._transaction(task_id) as state:
            admitted = state['admissions'].get(assignment_id)
            if admitted is None:
                raise TaskBriefError('assignment_not_found', 'assignment has no admitted task brief')
            revision = self._revision(state, admitted['pin']['revision'])
            if authority is not None:
                authority.require_workspace(revision['content'])
            if (admitted['pin']['digest'] != revision['digest']
                    or admitted['pin']['approval'] != state['approvals'].get(str(revision['revision']))):
                raise TaskBriefError('store_invalid', 'assignment pin differs from approved brief')
            return dict(version=1, assignment_id=assignment_id, **_copy(admitted['pin']))

    def validate_pin(self, pin, *, authority=None):
        """Validate a carried checkpoint pin against the original admission."""
        if (type(pin) is not dict or set(pin) != {'version', 'assignment_id', 'task_id', 'revision', 'digest', 'approval'}
                or type(pin.get('version')) is not int or pin['version'] != 1):
            raise TaskBriefError('invalid_pin', 'task brief pin shape/version is invalid')
        expected = self.assignment_pin(pin['task_id'], pin['assignment_id'], authority=authority)
        if pin != expected:
            raise TaskBriefError('invalid_pin', 'task brief pin differs from its admitted assignment')
        return expected
