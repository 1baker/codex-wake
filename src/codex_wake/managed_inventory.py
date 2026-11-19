"""Durable managed-conversation identity; membership never grants operations.

The observer and authority arguments are trusted host seams, not model inputs.
State is confined to one OS user's private Wake root; this does not isolate
hostile code with the same UID.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import uuid4

from .records import WakeError
from . import measurements

VERSION = 1
MAX_BYTES = 4 * 1024 * 1024
MAX_AGE_SECONDS = 30
MODES = ('self_enrollment', 'operator_only', 'operator_selected')
STATES = ('ready', 'unavailable', 'ambiguous', 'stale', 'not_qualified')


class InventoryError(WakeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _text(value, name, *, limit=1024):
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(ord(char) < 32 for char in value)):
        raise InventoryError('invalid_argument', name + ' is invalid')
    return value


def identity_key(runtime, namespace, conversation_id):
    for value, name in [(runtime, 'runtime'), (namespace, 'namespace'),
                        (conversation_id, 'conversation_id')]:
        _text(value, name)
    return json.dumps([runtime, namespace, conversation_id], separators=(',', ':'))


@dataclass(frozen=True)
class Observation:
    runtime: str
    namespace: str
    conversation_id: str
    root: str
    state: str
    observed_at: float
    source: str
    process: dict | None
    attachments: list
    capabilities: dict
    profile: str | None = None
    caller_verified: bool = False
    clock_observation: dict | None = None

    def validated(self, now):
        if self.runtime not in ('codex', 'grok') or self.state not in STATES:
            raise InventoryError('identity_unqualified', 'runtime observation is unqualified')
        identity_key(self.runtime, self.namespace, self.conversation_id)
        if not Path(_text(self.root, 'root')).is_absolute():
            raise InventoryError('identity_unqualified', 'absolute runtime root required')
        expected_source = 'native_metadata' if self.runtime == 'codex' else 'host_bound_runtime'
        if self.source != expected_source:
            raise InventoryError('identity_unqualified', 'runtime evidence provenance is unqualified')
        try:
            fresh = (measurements.fresh(self.clock_observation, MAX_AGE_SECONDS, current=now)
                     if isinstance(now, dict) else self.observed_at <= now <= self.observed_at + MAX_AGE_SECONDS)
        except (measurements.TimeUnavailable, TypeError, ValueError):
            fresh = False
        if (type(self.observed_at) not in (int, float) or not math.isfinite(self.observed_at)
                or not fresh):
            raise InventoryError('observation_stale', 'fresh bounded runtime evidence required')
        if (not isinstance(self.attachments, list) or len(self.attachments) > 32
                or not isinstance(self.capabilities, dict) or len(self.capabilities) > 32):
            raise InventoryError('identity_unqualified', 'invalid runtime observation')
        for pane in self.attachments:
            if (not isinstance(pane, dict) or not pane
                    or set(pane) - {'pane_id', 'window_id', 'session_id', 'window_index',
                                    'pane_index', 'window_name', 'session_name'}):
                raise InventoryError('identity_unqualified', 'only public terminal metadata may be projected')
            for value in pane.values():
                _text(value, 'attachment')
        if self.profile is not None and not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', self.profile):
            raise InventoryError('identity_unqualified', 'profile must be a nonsecret name')
        for key in self.capabilities:
            _text(key, 'capability', limit=128)
        if any(value not in ('supported', 'unsupported', 'not_qualified', 'unavailable')
               for value in self.capabilities.values()):
            raise InventoryError('identity_unqualified', 'invalid runtime capability')
        if self.state == 'ready' or self.process is not None:
            process = self.process
            if (not isinstance(process, dict) or set(process) != {'pid', 'start_ticks', 'boot_id'}
                    or type(process['pid']) is not int or process['pid'] <= 0
                    or type(process['start_ticks']) is not int or process['start_ticks'] <= 0
                    or not isinstance(process['boot_id'], str) or not process['boot_id']
                    or len(process['boot_id']) > 128):
                raise InventoryError('identity_unqualified', 'verified process generation required')
        return self


class ManagedInventory:
    """Serialize policy and identity transitions in one crash-safe private document."""
    def __init__(self, root, *, now=None):
        self.root = Path(root).absolute()
        if self.root != self.root.resolve():
            raise InventoryError('store_unavailable', 'Wake root must not traverse symlinks')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise InventoryError('store_unavailable', 'Wake root must be owned and not writable by others')
        self.directory = self.root / 'managed-inventory'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self._private(self.directory, directory=True)
        self.path = self.directory / 'inventory.json'
        self.lock_path = self.directory / 'inventory.lock'
        self.now = measurements.utc_time if now is None else now
        self.clock = (lambda: measurements.snapshot()) if now is None else (lambda: self.now())

    @staticmethod
    def _private(path, *, directory=False):
        info = path.lstat()
        kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if (not kind or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)):
            raise InventoryError('store_unavailable', 'inventory paths must be owned and private')

    @contextmanager
    def _transaction(self, *, write=True):
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            self._private(self.lock_path)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists() or self.path.is_symlink():
                self._private(self.path)
                fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd) as source:
                    raw = source.read(MAX_BYTES + 1)
                try:
                    if len(raw.encode()) > MAX_BYTES:
                        raise ValueError('oversized inventory')
                    data = json.loads(raw, object_pairs_hook=_unique)
                except (ValueError, TypeError):
                    raise InventoryError('store_unavailable', 'invalid inventory state') from None
                self._validate(data)
            else:
                data = {'version': VERSION, 'policy': {'mode': 'self_enrollment', 'selected': []},
                        'agents': {}}
            yield data
            if write:
                rendered = json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n'
                if len(rendered.encode()) > MAX_BYTES:
                    raise InventoryError('population_limit', 'inventory capacity reached; no history removed')
                fd, temporary = tempfile.mkstemp(prefix='.inventory-', dir=self.directory)
                try:
                    with os.fdopen(fd, 'w') as out:
                        out.write(rendered)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(temporary, self.path)
                    directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _validate(data):
        if (type(data) is not dict or set(data) != {'version', 'policy', 'agents'}
                or type(data['version']) is not int or data['version'] != VERSION):
            raise InventoryError('unsupported_version', 'inventory version is unsupported; state retained')
        if (type(data['policy']) is not dict or set(data['policy']) != {'mode', 'selected'}
                or data['policy']['mode'] not in MODES or type(data['policy']['selected']) is not list
                or type(data['agents']) is not dict or len(data['agents']) > 1000):
            raise InventoryError('store_unavailable', 'invalid inventory policy or population')
        if any(not isinstance(key, str) or len(key) > 4096 for key in data['policy']['selected']):
            raise InventoryError('store_unavailable', 'invalid selected conversation identity')
        for key, agent in data['agents'].items():
            if (type(agent) is not dict
                    or key != identity_key(agent.get('runtime'), agent.get('namespace'), agent.get('conversation_id'))
                    or not re.fullmatch(r'agent_[0-9a-f]{32}', agent.get('managed_agent_id', ''))
                    or agent.get('enrollment') not in ('enrolled', 'suppressed')
                    or agent.get('state') not in STATES or type(agent.get('history')) is not list):
                raise InventoryError('store_unavailable', 'invalid managed-agent record')
            fields = {'managed_agent_id', 'runtime', 'namespace', 'conversation_id', 'enrollment',
                      'root', 'created_at', 'history', 'predecessor', 'task_id', 'allocation_id',
                      'state', 'observed_at', 'evidence_kind', 'process', 'attachments', 'capabilities', 'profile'}
            if set(agent) - {'clock_observation'} != fields:
                raise InventoryError('store_unavailable', 'unknown managed-agent record fields')
            Observation(agent['runtime'], agent['namespace'], agent['conversation_id'],
                        agent['root'], agent['state'], agent['observed_at'], agent['evidence_kind'],
                        agent['process'], agent['attachments'], agent['capabilities'], agent['profile'],
                        clock_observation=agent.get('clock_observation')).validated(agent['observed_at'])

    def inspect(self, managed_agent_id=None):
        with self._transaction(write=False) as data:
            rows = [self._view(agent) for agent in data['agents'].values()]
            if managed_agent_id is not None:
                rows = [row for row in rows if row['managed_agent_id'] == managed_agent_id]
                if not rows:
                    raise InventoryError('agent_not_found', 'managed agent is not present')
                return {'status': 'found', 'agent': rows[0], 'policy': data['policy']}
            return {'status': 'inventory', 'agents': sorted(rows, key=lambda a: a['managed_agent_id']),
                    'policy': data['policy']}

    def _view(self, agent):
        result = json.loads(json.dumps(agent))
        if result['state'] == 'ready':
            try:
                Observation(result['runtime'], result['namespace'], result['conversation_id'],
                    result['root'], result['state'], result['observed_at'], result['evidence_kind'],
                    result['process'], result['attachments'], result['capabilities'], result['profile'],
                    clock_observation=result.get('clock_observation')).validated(self.clock())
            except (InventoryError, measurements.TimeUnavailable):
                result['state'] = 'stale'
        result['binding_current'] = result['state'] == 'ready' and result['enrollment'] == 'enrolled'
        result['grants_operations'] = False
        return result

    def enroll(self, observation, *, operator=False, predecessor=None, task_id=None, allocation_id=None):
        sample = observation.validated(self.clock())
        if sample.state != 'ready':
            raise InventoryError('identity_unavailable', 'new enrollment requires ready verified binding')
        key = identity_key(sample.runtime, sample.namespace, sample.conversation_id)
        with self._transaction() as data:
            agent = data['agents'].get(key)
            if agent is not None and agent['enrollment'] == 'suppressed':
                return {'status': 'suppressed', 'agent': self._view(agent), 'policy': data['policy']}
            mode = data['policy']['mode']
            if not operator and (mode == 'operator_only' or
                    (mode == 'operator_selected' and key not in data['policy']['selected'])):
                raise InventoryError('policy_denied', 'operator enrollment or selection is required')
            parent = None
            if predecessor is not None:
                parent = next((a for a in data['agents'].values()
                               if a['managed_agent_id'] == predecessor), None)
                if parent is None:
                    raise InventoryError('agent_not_found', 'predecessor managed agent is not present')
                if key == identity_key(parent['runtime'], parent['namespace'], parent['conversation_id']):
                    raise InventoryError('invalid_argument', 'successor must be a different conversation')
                for name, value in [('task_id', task_id), ('allocation_id', allocation_id)]:
                    if value is not None and value != parent.get(name):
                        raise InventoryError('identity_changed', 'successor cannot change task or allocation continuity')
                task_id, allocation_id = parent.get('task_id'), parent.get('allocation_id')
            for name, value in [('task_id', task_id), ('allocation_id', allocation_id)]:
                if value is not None:
                    _text(value, name)
            if agent is not None:
                for name, value in [('predecessor', predecessor), ('task_id', task_id), ('allocation_id', allocation_id)]:
                    if value is not None and value != agent.get(name):
                        raise InventoryError('identity_changed', 'managed identity linkage cannot be replaced')
            if agent is None:
                if len(data['agents']) >= 1000:
                    raise InventoryError('population_limit', 'inventory population limit reached')
                agent = dict(managed_agent_id='agent_' + uuid4().hex,
                             runtime=sample.runtime, namespace=sample.namespace,
                             conversation_id=sample.conversation_id, enrollment='enrolled',
                             root=sample.root, created_at=self.now(), history=[], predecessor=predecessor,
                             task_id=task_id, allocation_id=allocation_id)
                data['agents'][key] = agent
            self._apply(agent, sample)
            return {'status': 'enrolled', 'agent': self._view(agent), 'policy': data['policy']}

    def reconcile(self, managed_agent_id, observation):
        sample = observation.validated(self.clock())
        key = identity_key(sample.runtime, sample.namespace, sample.conversation_id)
        with self._transaction() as data:
            agent = data['agents'].get(key)
            if agent is None or agent['managed_agent_id'] != managed_agent_id:
                raise InventoryError('identity_changed', 'observation does not match managed identity')
            if sample.root != agent['root']:
                raise InventoryError('identity_changed', 'managed conversation root changed')
            self._apply(agent, sample)
            return {'status': 'reconciled', 'agent': self._view(agent)}

    def configure(self, mode, selected=()):
        if mode not in MODES or not isinstance(selected, (list, tuple)):
            raise InventoryError('invalid_argument', 'invalid enrollment policy')
        if len(selected) > 1000:
            raise InventoryError('invalid_argument', 'selected population exceeds limit')
        keys = []
        for identity in selected:
            if not isinstance(identity, dict) or set(identity) != {'runtime', 'namespace', 'conversation_id'}:
                raise InventoryError('invalid_argument', 'selection requires exact runtime identities')
            if identity['runtime'] not in ('codex', 'grok'):
                raise InventoryError('invalid_argument', 'selected runtime is unsupported')
            keys.append(identity_key(**identity))
        with self._transaction() as data:
            data['policy'] = {'mode': mode, 'selected': sorted(set(keys))}
            return {'status': 'configured', 'policy': data['policy']}

    def set_enrollment(self, managed_agent_id, *, enabled):
        with self._transaction() as data:
            agent = next((a for a in data['agents'].values()
                          if a['managed_agent_id'] == managed_agent_id), None)
            if agent is None:
                raise InventoryError('agent_not_found', 'managed agent is not present')
            agent['enrollment'] = 'enrolled' if enabled else 'suppressed'
            agent['history'].append({'event': 'operator_reenabled' if enabled else 'operator_unenrolled',
                                     'at': self.now()})
            return {'status': agent['enrollment'], 'agent': self._view(agent)}

    def _apply(self, agent, sample):
        if sample.root != agent['root']:
            raise InventoryError('identity_changed', 'managed conversation root changed')
        agent.update(state=sample.state, observed_at=sample.observed_at, evidence_kind=sample.source,
                     process=sample.process, attachments=sample.attachments,
                     capabilities=sample.capabilities, profile=sample.profile)
        if sample.clock_observation is not None:
            agent['clock_observation'] = json.loads(json.dumps(sample.clock_observation))
        else:
            agent.pop('clock_observation', None)
        agent['history'].append({'event': 'binding_observed', 'at': self.now(),
                                 'state': sample.state, 'process': sample.process,
                                 'attachments': sample.attachments})


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate inventory member')
        result[key] = value
    return result
