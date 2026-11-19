"""Independent acceptance of exact pinned work, distinct from completion prose."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from .a2a_bus import private_path
from .goal_supervision import _save
from .records import WakeError
from . import measurements
from .session_permissions import check_operation
from .task_briefs import TaskBriefStore
from .wake_policy import _read


class AcceptanceError(WakeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class WorkAcceptance:
    def __init__(self, root, *, now=None):
        self.root = Path(root).absolute()
        if self.root != self.root.resolve():
            raise AcceptanceError('acceptance_unavailable', 'canonical Wake root required')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise AcceptanceError('acceptance_unavailable', 'owned Wake root required')
        self.directory = self.root / 'work-acceptance'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        private_path(self.directory, directory=True)
        self.now = measurements.utc_time if now is None else now
        self._fixture_now = now

    @contextmanager
    def _state(self, contract_id, *, write=False):
        if type(contract_id) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', contract_id):
            raise AcceptanceError('invalid_argument', 'invalid contract identity')
        key = hashlib.sha256(contract_id.encode()).hexdigest()
        fd = os.open(self.directory / (key + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            private_path(self.directory / (key + '.lock'))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AcceptanceError('acceptance_busy', 'contract verification is already active') from None
            path = self.directory / (key + '.json')
            state = None
            if path.exists() or path.is_symlink():
                state = _read(path)
                if (type(state) is not dict or set(state) != {'version', 'contract', 'decisions', 'receipts'}
                        or type(state['version']) is not int or state['version'] != 1
                        or type(state['contract']) is not dict or type(state['decisions']) is not dict
                        or type(state['receipts']) is not list):
                    raise AcceptanceError('acceptance_unavailable', 'unknown contract state; retained')
                contract = state['contract']
                if contract.get('id') != contract_id or contract.get('digest') != _digest({k:v for k,v in contract.items() if k != 'digest'}):
                    raise AcceptanceError('acceptance_unavailable', 'contract integrity differs')
            box = [state]
            yield box
            if write and box[0] is not None:
                if len(json.dumps(box[0]).encode()) > 262144:
                    raise AcceptanceError('acceptance_full', 'acceptance history bound reached')
                _save(path, box[0])

    def contract(self, contract_id):
        """Host adapters recover exact task scope before authenticating the operation."""
        with self._state(contract_id) as box:
            if box[0] is None:
                raise AcceptanceError('contract_not_found', 'acceptance contract not found')
            return json.loads(json.dumps(box[0]['contract']))

    def _brief(self, pin, authority):
        store = TaskBriefStore(self.root)
        store.validate_pin(pin, authority=authority)
        brief = store.inspect(pin['task_id'])['revisions'][pin['revision'] - 1]['content']
        authority.require_workspace(brief)
        return brief

    def define(self, contract_id, task_id, assignment_id, checks, *, authority, principal):
        authority.require(task_id, approval=True)
        pin = TaskBriefStore(self.root).assignment_pin(task_id, assignment_id, authority=authority)
        brief = self._brief(pin, authority)
        if type(checks) is not dict or not {'artifacts', 'verifiers', 'decisions'} <= set(checks) or set(checks) - {'artifacts', 'verifiers', 'decisions', 'claim', 'git_commit'} or not checks['artifacts']:
            raise AcceptanceError('invalid_argument', 'artifacts, verifiers and decisions required')
        normalized = json.loads(json.dumps(checks))
        normalized.setdefault('claim', None)
        normalized.setdefault('git_commit', None)
        if normalized['git_commit'] is not None and (type(normalized['git_commit']) is not str or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', normalized['git_commit'])):
            raise AcceptanceError('invalid_argument', 'exact Git commit required')
        if any(type(normalized[key]) is not list or len(normalized[key]) > 16 for key in ('artifacts', 'verifiers', 'decisions')):
            raise AcceptanceError('invalid_argument', 'bounded check lists required')
        for artifact in normalized['artifacts']:
            if (type(artifact) is not dict or set(artifact) != {'name', 'path', 'sha256', 'required'}
                    or type(artifact['name']) is not str or not artifact['name']
                    or type(artifact['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', artifact['sha256'])
                    or type(artifact['required']) is not bool):
                raise AcceptanceError('invalid_argument', 'artifact contract malformed')
            path = Path(artifact['path'])
            if not path.is_absolute() or path != path.resolve() or not path.is_relative_to(Path(brief['workspace'])):
                raise AcceptanceError('authority_denied', 'artifact is outside approved workspace')
        for decision in normalized['decisions']:
            if (type(decision) is not dict or set(decision) != {'name', 'kind', 'required'}
                    or type(decision['name']) is not str or not decision['name']
                    or decision['kind'] not in ('human', 'reviewer') or type(decision['required']) is not bool):
                raise AcceptanceError('invalid_argument', 'named explicit decisions required')
        if len({item['name'] for item in normalized['decisions']}) != len(normalized['decisions']):
            raise AcceptanceError('invalid_argument', 'duplicate decision identity')
        total_timeout = 0
        for verifier in normalized['verifiers']:
            if (type(verifier) is not dict or set(verifier) != {'name', 'argv', 'timeout', 'pass_codes', 'fail_codes'}
                    or type(verifier['name']) is not str or not verifier['name']
                    or type(verifier['argv']) is not list or not 1 <= len(verifier['argv']) <= 32
                    or any(type(arg) is not str or not arg or len(arg) > 4096 or '\0' in arg for arg in verifier['argv'])
                    or type(verifier['timeout']) not in (int, float) or not .01 <= verifier['timeout'] <= 30
                    or any(type(verifier[key]) is not list or not verifier[key]
                           or any(type(code) is not int or not 0 <= code <= 255 for code in verifier[key])
                           for key in ('pass_codes', 'fail_codes'))
                    or set(verifier['pass_codes']) & set(verifier['fail_codes'])):
                raise AcceptanceError('invalid_argument', 'bounded verifier argv and exit classifications required')
            executable = Path(verifier['argv'][0])
            if not executable.is_absolute() or executable != executable.resolve(strict=True) or not executable.is_file():
                raise AcceptanceError('invalid_argument', 'canonical verifier executable required')
            verifier['executable_sha256'] = self._executable_hash(executable)
            total_timeout += verifier['timeout']
        if total_timeout > 30:
            raise AcceptanceError('invalid_argument', 'combined verifier budget exceeds 30 seconds')
        if normalized['verifiers']:
            claim = normalized['claim']
            if (type(claim) is not dict or set(claim) != {'claim_id', 'generation'}
                    or type(claim['claim_id']) is not str or type(claim['generation']) is not int):
                raise AcceptanceError('authority_denied', 'verifier commands require declared mutation custody')
        contract = dict(id=contract_id, revision=1, task_id=task_id, pin=pin, checks=normalized,
                        workspace=brief['workspace'], approved_by=authority.actor_id, approved_at=self.now())
        contract['digest'] = _digest(contract)
        with self._state(contract_id, write=True) as box:
            if box[0] is not None:
                existing = box[0]['contract']
                if existing['pin'] == pin and existing['checks'] == normalized:
                    return existing
                raise AcceptanceError('contract_conflict', 'immutable acceptance contract already exists')
            box[0] = dict(version=1, contract=contract, decisions={}, receipts=[])
        return contract

    def _snapshot(self, contract):
        observations = []
        valid = True
        for artifact in contract['checks']['artifacts']:
            path = Path(artifact['path'])
            status, digest = 'unavailable', None
            try:
                if path != path.resolve(strict=True) or not path.is_relative_to(Path(contract['workspace'])):
                    raise OSError('path changed')
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream:
                    import stat
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                        raise OSError('bounded regular artifact required')
                    data = stream.read(1024 * 1024 + 1)
                digest = hashlib.sha256(data).hexdigest()
                status = 'verified' if digest == artifact['sha256'] else 'changed'
            except OSError:
                pass
            valid = valid and (status == 'verified' or not artifact['required'])
            observations.append(dict(name=artifact['name'], status=status, sha256=digest))
        if contract['checks'].get('git_commit') is not None:
            commit = None
            try:
                environment = {key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
                commit = subprocess.check_output(['git', '-C', contract['workspace'], 'rev-parse', '--verify', 'HEAD^{commit}'],
                    env=environment, stderr=subprocess.DEVNULL, timeout=2, text=True).strip()
            except (OSError, AcceptanceError, subprocess.SubprocessError, measurements.TimeUnavailable):
                pass
            matched = commit == contract['checks']['git_commit']
            valid = valid and matched
            observations.append(dict(name='git_commit', status='verified' if matched else 'changed', sha256=commit))
        return valid, observations

    def _pin_current(self, contract, authority):
        authority.require(contract['task_id'])
        try:
            self._brief(contract['pin'], authority)
            return True
        except WakeError as error:
            if getattr(error, 'code', None) == 'authority_denied':
                raise
            return False
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def evaluate(self, contract_id, *, authority, principal, claimant=None):
        with self._state(contract_id, write=True) as box:
            if box[0] is None:
                raise AcceptanceError('contract_not_found', 'acceptance contract not found')
            contract = box[0]['contract']
            pin_current = self._pin_current(contract, authority)
            permission = check_operation(self.root, 'acceptance.verify', principal,
                task_id=contract['task_id'], operation_id=contract_id, capability='supported', readiness='ready')
            valid, observations = self._snapshot(contract)
            valid = valid and pin_current
            results = []
            status = 'accepted' if valid else 'unknown'
            guard = nullcontext()
            if valid and contract['checks']['verifiers']:
                from .resource_claims import ResourceClaims, Claimant
                if not isinstance(claimant, Claimant):
                    raise AcceptanceError('authority_denied', 'fresh verified resource owner required')
                claim = contract['checks']['claim']
                guard = ResourceClaims(self.root, now=self.now if self._fixture_now is not None else None).guard(claim['claim_id'], claim['generation'], claimant)
            with guard:
                for verifier in contract['checks']['verifiers'] if valid else []:
                    current_valid, current_snapshot = self._snapshot(contract)
                    if (not self._pin_current(contract, authority) or not current_valid
                            or current_snapshot != observations):
                        status = 'unknown'
                        results.append(dict(name=verifier['name'], status='unknown', reason='scope_changed'))
                        break
                    check_operation(self.root, 'acceptance.verify', principal, task_id=contract['task_id'],
                                    operation_id=contract_id, capability='supported', readiness='ready')
                    result = self._run(verifier, contract['workspace'])
                    results.append(result)
                    if result['status'] != 'accepted':
                        status = result['status']
                        break
            for requirement in contract['checks']['decisions'] if valid else []:
                decision = box[0]['decisions'].get(requirement['name'])
                current_snapshot = _digest(dict(pin=contract['pin'], artifacts=observations))
                current = (decision is not None and decision['contract_digest'] == contract['digest']
                           and decision['snapshot'] == current_snapshot and self.now() <= decision['expires_at'])
                if not current:
                    if requirement['required'] and status != 'rejected':
                        status = 'unknown'
                elif decision['outcome'] == 'rejected':
                    status = 'rejected'
                results.append(dict(name=requirement['name'], status=decision['outcome'] if current else 'unknown', kind=requirement['kind']))
            after_valid, after = self._snapshot(contract)
            if not self._pin_current(contract, authority) or not after_valid or after != observations:
                status = 'unknown'
            receipt = dict(contract_id=contract_id, contract_digest=contract['digest'], pin=contract['pin'],
                           status=status, artifacts=observations, checks=results,
                           accepting_authority=principal.subject, permission=permission, observed_at=self.now())
            box[0]['receipts'].append(receipt)
            return receipt

    def decide(self, contract_id, name, outcome, *, authority, principal, expires_at):
        import math
        if outcome not in ('accepted', 'rejected') or type(expires_at) not in (int, float) or not math.isfinite(expires_at) or expires_at < self.now():
            raise AcceptanceError('invalid_argument', 'bounded attributable decision required')
        with self._state(contract_id, write=True) as box:
            if box[0] is None:
                raise AcceptanceError('contract_not_found', 'acceptance contract not found')
            contract = box[0]['contract']
            authority.require(contract['task_id'], approval=True)
            self._brief(contract['pin'], authority)
            requirement = next((item for item in contract['checks']['decisions'] if item['name'] == name), None)
            if requirement is None or (requirement['kind'] == 'human' and principal.role != 'operator'):
                raise AcceptanceError('authority_denied', 'explicit accepting authority is required')
            valid, artifacts = self._snapshot(contract)
            if not valid:
                raise AcceptanceError('evidence_unavailable', 'cannot decide changed or missing work')
            decision = dict(outcome=outcome, actor=principal.subject, contract_digest=contract['digest'],
                            snapshot=_digest(dict(pin=contract['pin'], artifacts=artifacts)),
                            observed_at=self.now(), expires_at=expires_at)
            if name in box[0]['decisions']:
                raise AcceptanceError('decision_conflict', 'explicit decision already recorded')
            box[0]['decisions'][name] = decision
            return decision

    def inspect(self, contract_id, *, authority, principal):
        with self._state(contract_id) as box:
            if box[0] is None:
                raise AcceptanceError('contract_not_found', 'acceptance contract not found')
            contract = box[0]['contract']
            pin_current = self._pin_current(contract, authority)
            valid, observations = self._snapshot(contract)
            valid = valid and pin_current
            receipt = box[0]['receipts'][-1] if box[0]['receipts'] else None
            valid = valid and (receipt is None or observations == receipt['artifacts'])
            for requirement in contract['checks']['decisions']:
                decision = box[0]['decisions'].get(requirement['name'])
                if requirement['required'] and (decision is None or self.now() > decision['expires_at']
                        or decision['snapshot'] != _digest(dict(pin=contract['pin'], artifacts=observations))):
                    valid = False
            return dict(contract=contract, original_receipt=receipt, artifacts=observations,
                        status=receipt['status'] if valid and receipt else 'unknown')


    @staticmethod
    def _executable_hash(path):
        if path.stat().st_size > 64 * 1024 * 1024:
            raise AcceptanceError('invalid_argument', 'verifier executable exceeds bound')
        with path.open('rb') as stream:
            return hashlib.sha256(stream.read(64 * 1024 * 1024 + 1)).hexdigest()

    def _run(self, verifier, cwd):
        process = None
        timed_out = False
        try:
            if self._executable_hash(Path(verifier['argv'][0])) != verifier['executable_sha256']:
                return dict(name=verifier['name'], status='unknown', reason='verifier_changed')
            deadline = measurements.deadline(verifier['timeout'])
            process = subprocess.Popen(verifier['argv'], cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            while True:
                # Keep the leader unreaped until group cleanup: its PGID cannot be reused.
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    break
                if deadline.expired():
                    timed_out = True
                    break
                time.sleep(min(.01, deadline.remaining()))
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            code = process.wait(timeout=2)
            status = ('unknown' if timed_out else 'accepted' if code in verifier['pass_codes']
                      else 'rejected' if code in verifier['fail_codes'] else 'unknown')
            return dict(name=verifier['name'], status=status, exit_code=code,
                        reason='verifier_timeout' if timed_out else 'declared_exit_classification')
        except (OSError, AcceptanceError, subprocess.SubprocessError, measurements.TimeUnavailable):
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
            return dict(name=verifier['name'], status='unknown', reason='verifier_unavailable')
