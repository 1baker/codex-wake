"""Durable cooperative directory custody; no operating-system access grant."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

from .a2a_bus import private_path
from .records import WakeError
from . import measurements

MAX_BYTES = 4 * 1024 * 1024
KINDS = ('worktree', 'build_prefix', 'install_prefix')


class ResourceClaimError(WakeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _copy(value):
    return json.loads(json.dumps(value))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate authority field')
        result[key] = value
    return result


@dataclass(frozen=True)
class Claimant:
    """Host-verified managed identity and freshly observed process binding."""
    managed_agent_id: str
    root: str
    process: dict
    observed_at: float
    clock_observation: dict | None = None

    def validated(self, now):
        if (not isinstance(self.managed_agent_id, str)
                or re.fullmatch(r'agent_[0-9a-f]{32}', self.managed_agent_id) is None
                or type(self.root) is not str or not Path(self.root).is_absolute()
                or type(self.process) is not dict or set(self.process) != {'pid', 'start_ticks', 'boot_id'}
                or type(self.process['pid']) is not int or self.process['pid'] <= 0
                or type(self.process['start_ticks']) is not int or self.process['start_ticks'] < 0
                or type(self.process['boot_id']) is not str or not self.process['boot_id']
                or type(self.observed_at) not in (int, float) or not math.isfinite(self.observed_at)):
            raise ResourceClaimError('owner_unqualified', 'fresh exact managed process binding required')
        try:
            qualified = (measurements.fresh(self.clock_observation, 30, current=now)
                         if isinstance(now, dict) else self.observed_at <= now <= self.observed_at + 30)
        except (measurements.TimeUnavailable, TypeError, ValueError):
            qualified = False
        if not qualified:
            raise ResourceClaimError('owner_unqualified', 'fresh exact managed process binding required')
        return dict(managed_agent_id=self.managed_agent_id, root=self.root, process=_copy(self.process))


def _resource(kind, path):
    if kind not in KINDS:
        raise ResourceClaimError('invalid_argument', 'unsupported mutation resource kind')
    path = Path(path)
    if not path.is_absolute() or path != path.resolve(strict=True) or not path.is_dir():
        raise ResourceClaimError('resource_unqualified', 'existing canonical directory required')
    info = path.stat()
    return dict(kind=kind, path=str(path), device=info.st_dev, inode=info.st_ino)


class ResourceClaims:
    """One private serialized owner of claims and their retained transition history."""
    def __init__(self, root, *, now=None):
        self.root = Path(root).absolute()
        if self.root != self.root.resolve():
            raise ResourceClaimError('store_unavailable', 'Wake root must not traverse symlinks')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ResourceClaimError('store_unavailable', 'Wake root must be owned and not writable by others')
        self.directory = self.root / 'resource-claims'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        private_path(self.directory, directory=True)
        self.path = self.directory / 'claims.json'
        self.lock_path = self.directory / 'claims.lock'
        self.initialized = self.directory / 'initialized'
        self.now = measurements.utc_time if now is None else now
        self.clock = (lambda: measurements.snapshot()) if now is None else (lambda: self.now())

    @contextmanager
    def _transaction(self, *, write=False):
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+') as stream:
            private_path(self.lock_path)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ResourceClaimError('resource_busy', 'another admitted operation holds resource custody') from None
            initializing = False
            if self.path.exists() or self.path.is_symlink():
                private_path(self.path)
                with self.path.open() as source:
                    raw = source.read(MAX_BYTES + 1)
                try:
                    state = json.loads(raw, object_pairs_hook=_unique)
                    if (len(raw.encode()) > MAX_BYTES or type(state) is not dict
                            or set(state) != {'version', 'claims'} or type(state['version']) is not int
                            or state['version'] != 1 or type(state['claims']) is not list):
                        raise ValueError('unknown state')
                    self._validate(state)
                except (ValueError, TypeError):
                    raise ResourceClaimError('store_unavailable', 'unsupported or malformed claim state; retained') from None
            else:
                if self.initialized.exists() or self.initialized.is_symlink():
                    raise ResourceClaimError('store_unavailable', 'initialized claim authority is missing; explicit recovery required')
                state = dict(version=1, claims=[])
                initializing = True
            if not self.initialized.exists():
                marker = os.open(self.initialized, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(marker)
            private_path(self.initialized)
            if initializing:
                self._publish(state)
            yield state
            if write:
                self._publish(state)

    def _publish(self, state):
        body = json.dumps(state, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(body.encode()) > MAX_BYTES:
            raise ResourceClaimError('store_full', 'claim history capacity reached; no history removed')
        fd, temporary = tempfile.mkstemp(prefix='.claims-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as out:
                out.write(body)
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
    def _validate(state):
        ids = set()
        for claim in state['claims']:
            if (type(claim) is not dict
                    or set(claim) != {'claim_id', 'generation', 'status', 'resource', 'owner', 'history'}
                    or type(claim['claim_id']) is not str
                    or re.fullmatch(r'claim_[0-9a-f]{32}', claim['claim_id']) is None
                    or claim['claim_id'] in ids or type(claim['generation']) is not int
                    or claim['generation'] < 1 or claim['status'] not in ('active', 'released')
                    or type(claim['resource']) is not dict
                    or set(claim['resource']) != {'kind', 'path', 'device', 'inode'}
                    or claim['resource']['kind'] not in KINDS
                    or type(claim['resource']['path']) is not str
                    or not Path(claim['resource']['path']).is_absolute()
                    or type(claim['resource']['device']) is not int or type(claim['resource']['inode']) is not int
                    or type(claim['owner']) is not dict
                    or set(claim['owner']) != {'managed_agent_id', 'root', 'process'}
                    or type(claim['history']) is not list or not claim['history']):
                raise ValueError('unsupported claim shape')
            ids.add(claim['claim_id'])
            Claimant(**claim['owner'], observed_at=0).validated(0)
            for event in claim['history']:
                fields = {'claimed': {'event', 'actor', 'at'},
                          'released': {'event', 'actor', 'at', 'reason', 'generation'},
                          'transferred': {'event', 'actor', 'at', 'reason', 'previous_owner', 'owner', 'generation'}}
                if type(event) is not dict or event.get('event') not in fields or set(event) != fields[event['event']]:
                    raise ValueError('unsupported transition shape')

    def inspect(self, claim_id=None):
        with self._transaction() as state:
            if claim_id is None:
                return dict(status='claims', claims=_copy(state['claims']))
            return _copy(self._find(state, claim_id))

    @staticmethod
    def _find(state, claim_id):
        for claim in state['claims']:
            if claim['claim_id'] == claim_id:
                return claim
        raise ResourceClaimError('claim_not_found', 'resource claim not found')

    def claim(self, kind, path, claimant):
        owner = claimant.validated(self.clock())
        resource = _resource(kind, path)
        with self._transaction(write=True) as state:
            for existing in state['claims']:
                if existing['status'] != 'active':
                    continue
                left, right = Path(existing['resource']['path']), Path(resource['path'])
                if left.is_relative_to(right) or right.is_relative_to(left):
                    if existing['resource'] == resource and existing['owner'] == owner:
                        return _copy(existing)
                    raise ResourceClaimError('resource_conflict', 'declared resource overlaps existing exclusive custody')
            claim = dict(claim_id='claim_' + uuid.uuid4().hex, generation=1, status='active',
                         resource=resource, owner=owner, history=[dict(event='claimed', actor=owner['managed_agent_id'], at=self.now())])
            state['claims'].append(claim)
            return _copy(claim)

    @contextmanager
    def guard(self, claim_id, generation, claimant):
        """Hold custody serialization through one cooperative mutation effect."""
        with self._transaction() as state:
            claim = self._find(state, claim_id)
            self._current(claim, generation, claimant)
            yield _copy(claim)

    def _current(self, claim, generation, claimant):
        if type(generation) is not int or generation != claim['generation'] or claim['status'] != 'active':
            raise ResourceClaimError('stale_generation', 'active exact claim generation required')
        if claim['owner'] != claimant.validated(self.clock()):
            raise ResourceClaimError('owner_changed', 'claim owner or process generation differs')
        if _resource(claim['resource']['kind'], claim['resource']['path']) != claim['resource']:
            raise ResourceClaimError('resource_changed', 'claimed directory identity changed')

    @staticmethod
    def _operator(operator, reason):
        if operator is not True or type(reason) is not str or not reason.strip() or len(reason) > 1024:
            raise ResourceClaimError('operator_required', 'explicit operator action and bounded reason required')

    def transfer(self, claim_id, generation, claimant, *, operator=False, reason=None):
        self._operator(operator, reason)
        owner = claimant.validated(self.clock())
        with self._transaction(write=True) as state:
            claim = self._find(state, claim_id)
            if type(generation) is not int or claim['generation'] != generation or claim['status'] != 'active':
                raise ResourceClaimError('stale_generation', 'active exact claim generation required')
            if _resource(claim['resource']['kind'], claim['resource']['path']) != claim['resource']:
                raise ResourceClaimError('resource_changed', 'release replaced directory before claiming its new identity')
            previous = claim['owner']
            claim.update(owner=owner, generation=generation + 1)
            claim['history'].append(dict(event='transferred', actor='operator:local', at=self.now(),
                                         reason=reason, previous_owner=previous, owner=owner, generation=generation + 1))
            return _copy(claim)

    def release(self, claim_id, generation, claimant=None, *, operator=False, reason=None):
        if operator:
            self._operator(operator, reason)
        with self._transaction(write=True) as state:
            claim = self._find(state, claim_id)
            if operator:
                if type(generation) is not int or claim['generation'] != generation or claim['status'] != 'active':
                    raise ResourceClaimError('stale_generation', 'active exact claim generation required')
                actor = 'operator:local'
            else:
                if type(claimant) is not Claimant:
                    raise ResourceClaimError('owner_unqualified', 'verified owner required')
                self._current(claim, generation, claimant)
                actor = claimant.managed_agent_id
            claim.update(status='released', generation=generation + 1)
            claim['history'].append(dict(event='released', actor=actor, at=self.now(), reason=reason,
                                         generation=generation + 1))
            return _copy(claim)
