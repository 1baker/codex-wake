"""Durable bounded local commands; command profiles are data, never permissions."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from . import measurements
from .a2a_bus import private_path
from .process_signals import observe_process_exit
from .records import WakeError
from .session_permissions import Principal, PermissionStore, check_operation
from .task_briefs import BriefAuthority, TaskBriefStore

MAX_STATE = 262144
MAX_JOBS = 256
TERMINAL = {'completed', 'cancelled', 'timed_out', 'failed'}


class BackgroundJobError(WakeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _error(code, message):
    raise BackgroundJobError(code, message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _read(path):
    private_path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_STATE + 1)
    if len(data) > MAX_STATE:
        _error('job_store_invalid', 'job state exceeds its bound')
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        _error('job_store_invalid', 'job state is malformed')
    if type(value) is not dict or type(value.get('version')) is not int or value['version'] != 1:
        _error('job_store_invalid', 'unknown or malformed job state version')
    return value


def _save(path, value):
    body = _json(value).encode()
    if len(body) > MAX_STATE:
        _error('job_store_invalid', 'job state exceeds its bound')
    fd, name = tempfile.mkstemp(prefix='.job-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as stream:
        private_path(path)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _identity(pid):
    value = observe_process_exit(pid)
    return value.identity() if value.valid() and value.state == 'alive' else None


def _alive(identity):
    if type(identity) is not dict:
        return False
    try:
        return _identity(identity['pid']) == identity
    except (KeyError, OSError, ValueError):
        return False


def _principal(value):
    if type(value) is not Principal:
        _error('job_identity_unverified', 'host-verified principal required')
    return value


class BackgroundJobs:
    """Public owner of command profiles, one-launch journals and completion receipts."""
    def __init__(self, root):
        self.root = Path(root).absolute()
        if self.root != self.root.resolve():
            _error('job_store_invalid', 'Wake root must be canonical')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_path(self.root, directory=True)
        self.directory = self.root / 'background-jobs'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        private_path(self.directory, directory=True)

    def approve_command(self, profile_id, argv, cwd, *, principal, task_pin, owner,
                        max_seconds=300, max_log_bytes=1048576, claim=None, mutation=False):
        """Operator configures exact command data; execution still needs job.launch."""
        if _principal(principal).role != 'operator':
            _error('job_operator_required', 'only the operator can configure command profiles')
        if type(profile_id) is not str or re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', profile_id) is None:
            _error('job_invalid_argument', 'invalid command profile identifier')
        if (type(argv) is not list or not 1 <= len(argv) <= 128
                or any(type(x) is not str or not x or '\0' in x for x in argv)
                or sum(len(x.encode()) for x in argv) > 32768):
            _error('job_invalid_argument', 'bounded argv list required')
        executable = Path(argv[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            _error('job_invalid_argument', 'absolute executable required')
        cwd = Path(cwd)
        if not cwd.is_absolute() or cwd != cwd.resolve() or not cwd.is_dir():
            _error('job_invalid_argument', 'existing canonical command directory required')
        if (type(max_seconds) not in (int, float) or not 0 < max_seconds <= 3600
                or type(max_log_bytes) is not int or not 1 <= max_log_bytes <= 10485760
                or type(owner) is not str or not owner or len(owner) > 256):
            _error('job_invalid_argument', 'invalid owner or wall/log bounds')
        pin = TaskBriefStore(self.root).validate_pin(task_pin)
        authority = BriefAuthority(principal.subject, 'operator')
        brief = TaskBriefStore(self.root).inspect(pin['task_id'], authority=authority)['revisions'][pin['revision'] - 1]
        if not cwd.is_relative_to(Path(brief['content']['workspace'])):
            _error('job_workspace_denied', 'command directory exceeds approved task workspace')
        if type(mutation) is not bool or (mutation and claim is None):
            _error('job_claim_required', 'declared mutation commands require a genuine resource claim')
        if claim is not None:
            from .resource_claims import Claimant, ResourceClaims
            if (type(claim) is not tuple or len(claim) != 3 or type(claim[2]) is not Claimant):
                _error('job_claim_unverified', 'host-verified claim token and claimant required')
            claim_id, generation, claimant = claim
            with ResourceClaims(self.root).guard(claim_id, generation, claimant) as record:
                if not cwd.is_relative_to(Path(record['resource']['path'])):
                    _error('job_workspace_denied', 'command directory exceeds claimed resource')
            claim = dict(claim_id=claim_id, generation=generation,
                owner=dict(managed_agent_id=claimant.managed_agent_id, root=claimant.root,
                           process=claimant.process))
        command = dict(argv=list(argv), cwd=str(cwd), task_pin=pin, owner=owner,
                       max_seconds=max_seconds, max_log_bytes=max_log_bytes, claim=claim, mutation=mutation)
        with _lock(self.directory / 'catalog.lock'):
            path = self.directory / 'commands.json'
            catalog = _read(path) if path.exists() else dict(version=1, profiles={})
            old = catalog['profiles'].get(profile_id)
            if old and old['command'] == command:
                return old
            value = dict(version=1, profile_id=profile_id, revision=(old['revision'] + 1 if old else 1),
                         command=command, sha256=_digest(command), issuer=principal.subject)
            catalog['profiles'][profile_id] = value
            _save(path, catalog)
            return value

    def profile(self, profile_id):
        with _lock(self.directory / 'catalog.lock'):
            value = _read(self.directory / 'commands.json')['profiles'].get(profile_id)
            if not value or value['sha256'] != _digest(value['command']):
                _error('job_profile_unavailable', 'command profile missing or invalid')
            return value

    def _job_dir(self, job_id):
        if type(job_id) is not str or re.fullmatch(r'job_[0-9a-f]{32}', job_id) is None:
            _error('job_invalid_argument', 'invalid job identity')
        path = self.directory / job_id
        private_path(path, directory=True)
        return path

    def _state(self, job_id):
        value = _read(self._job_dir(job_id) / 'state.json')
        if value.get('job_id') != job_id or value.get('intent_sha256') != _digest(value.get('intent')):
            _error('job_store_invalid', 'job intent integrity differs')
        return value

    def _authorize(self, state, principal, action):
        _principal(principal)
        command = state['intent']['profile']['command']
        task_id = command['task_pin']['task_id']
        if principal.subject != command['owner'] and principal.role != 'operator':
            _error('job_owner_denied', 'job belongs to another exact owner')
        if principal.role != 'operator' and task_id not in principal.tasks:
            _error('job_task_denied', 'verified caller lacks the exact task')
        TaskBriefStore(self.root).validate_pin(command['task_pin'])
        if not PermissionStore(self.root).active():
            _error('job_permission_policy_required', 'background jobs require the common permission policy')
        return check_operation(self.root, action, principal, target=command['owner'],
                               task_id=task_id, operation_id=state['job_id'])

    def launch(self, profile_id, *, principal, idempotency_key, claimant=None):
        _principal(principal)
        if type(idempotency_key) is not str or not 1 <= len(idempotency_key) <= 256:
            _error('job_invalid_argument', 'bounded idempotency key required')
        profile = self.profile(profile_id)
        intent = dict(profile=profile, owner=profile['command']['owner'],
                      idempotency_key=idempotency_key)
        with _lock(self.directory / 'catalog.lock'):
            for path in self.directory.glob('job_*/state.json'):
                existing = self._state(path.parent.name)
                if (existing['intent']['owner'] == intent['owner'] and
                        existing['intent']['idempotency_key'] == idempotency_key):
                    if existing['intent'] != intent:
                        _error('job_idempotency_conflict', 'key already names a different original job intent')
                    self._authorize(existing, principal, 'job.launch')
                    return self.inspect(existing['job_id'])
            if len(list(self.directory.glob('job_*'))) >= MAX_JOBS:
                _error('job_limit_exceeded', 'retained job count reached its bound')
            job_id = 'job_' + uuid.uuid4().hex
            state = dict(version=1, job_id=job_id, generation=1, intent=intent,
                         intent_sha256=_digest(intent), status='starting', process=None,
                         supervisor=None, reservation=_identity(os.getpid()), created_at=measurements.utc_time(),
                         principal=dict(subject=principal.subject, role=principal.role, tasks=list(principal.tasks)))
            self._authorize(state, principal, 'job.launch')
            with _claim_guard(self, profile['command'], claimant):
                if claimant is not None:
                    state['claimant'] = dict(managed_agent_id=claimant.managed_agent_id,
                        root=claimant.root, process=claimant.process, observed_at=claimant.observed_at,
                        clock_observation=claimant.clock_observation)
            deadline = measurements.deadline(3)
            directory = self.directory / job_id
            directory.mkdir(mode=0o700)
            _save(directory / 'state.json', state)
            env = dict(os.environ)
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
            try:
                supervisor = subprocess.Popen([sys.executable, '-m', 'codex_wake.background_jobs',
                    '--supervise', str(self.root), job_id], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                    close_fds=True, env=env)
                threading.Thread(target=supervisor.wait, daemon=True).start()
            except OSError:
                state.update(status='unknown', reason='supervisor_launch_uncertain')
                _save(directory / 'state.json', state)
                return self.inspect(job_id)
        # A bounded launch handshake; neither caller nor controller owns execution.
        try:
            while not deadline.expired():
                value = self.inspect(job_id)
                if value['status'] != 'starting':
                    return value
                if supervisor.poll() is not None:
                    break
                time.sleep(.01)
        except measurements.TimeUnavailable:
            # The durable job already owns this attempt. Return its original
            # handle; unavailable timing never authorizes another launch.
            return self.inspect(job_id)
        return self.inspect(job_id)

    def inspect(self, job_id):
        state = self._state(job_id)
        directory = self._job_dir(job_id)
        result_path = directory / 'result.json'
        if result_path.exists():
            result = _read(result_path)
            if any(result.get(key) != state.get(key) for key in ('job_id', 'generation', 'intent_sha256', 'process')):
                _error('job_result_invalid', 'terminal receipt differs from original job generation')
            if result.get('status') not in TERMINAL:
                _error('job_result_invalid', 'terminal receipt has an invalid outcome')
            state.update(status=result['status'], result=result)
        elif state['status'] not in {'unknown'}:
            identity = state.get('supervisor') or state.get('reservation')
            if not _alive(identity):
                state.update(status='unknown', reason='supervisor_or_boot_generation_unavailable')
        state.update(result_path=str(result_path), stdout_path=str(directory / 'stdout.log'),
                     stderr_path=str(directory / 'stderr.log'))
        return state

    def cancel(self, job_id, *, principal, expected_generation):
        directory = self._job_dir(job_id)
        with _lock(directory / 'state.lock'):
            state = self._state(job_id)
            self._authorize(state, principal, 'job.cancel')
            if type(expected_generation) is not int or expected_generation != state['generation']:
                _error('job_stale_generation', 'exact original job generation required')
            current = self.inspect(job_id)
            if current['status'] in TERMINAL or current['status'] == 'unknown':
                return current
            path = directory / 'cancel.json'
            if not path.exists():
                try:
                    requested_at, clock_status = measurements.utc_time(), 'qualified'
                except measurements.TimeUnavailable:
                    # A verified stop-only request needs no invented UTC and
                    # must not be blocked by failure of timestamp authority.
                    requested_at, clock_status = None, 'unavailable'
                _save(path, dict(version=1, job_id=job_id, generation=expected_generation,
                    actor=principal.subject, requested_at=requested_at, clock_status=clock_status,
                    principal=dict(subject=principal.subject, role=principal.role, tasks=list(principal.tasks))))
        return self.inspect(job_id)

    def authorize_inspection(self, state, principal):
        _principal(principal)
        if principal.role != 'operator' and principal.subject != state['intent']['owner']:
            _error('job_owner_denied', 'job belongs to another exact owner')
        return check_operation(self.root, 'session.inspect', principal, target=principal.subject)

    def await_result(self, job_id, *, principal, register_wake):
        state = self.inspect(job_id)
        self.authorize_inspection(state, principal)
        if not callable(register_wake):
            _error('job_await_unavailable', 'existing wake registration adapter required')
        wake = register_wake(Path(state['result_path']), 'job-result:' + job_id, state)
        return dict(job=state, wake=wake)


def _verify_claimant(claimant):
    from .resource_claims import Claimant
    if type(claimant) is not Claimant:
        _error('job_claim_unverified', 'fresh host-verified claimant required for claimed command')
    claimant.validated(measurements.snapshot())
    sample = observe_process_exit(claimant.process['pid'])
    expected = dict(boot_id=claimant.process['boot_id'], pid=claimant.process['pid'],
                    start_time_ticks=claimant.process['start_ticks'], owner_uid=os.geteuid())
    if sample.state != 'alive' or sample.identity() != expected:
        _error('job_claim_process_changed', 'claimant exact process generation is no longer live')


@contextmanager
def _claim_guard(store, command, claimant):
    claim = command.get('claim')
    if claim is None:
        if claimant is not None:
            _error('job_claim_unexpected', 'unclaimed command cannot accept a new custody claim')
        yield
        return
    _verify_claimant(claimant)
    owner = dict(managed_agent_id=claimant.managed_agent_id, root=claimant.root, process=claimant.process)
    # Legacy profile timestamps are never execution freshness evidence.
    expected = claim.get('owner') or {key: value for key, value in claim.get('claimant', {}).items()
                                      if key != 'observed_at'}
    if owner != expected:
        _error('job_claim_owner_changed', 'fresh claimant differs from the approved managed owner')
    from .resource_claims import ResourceClaims
    with ResourceClaims(store.root).guard(claim['claim_id'], claim['generation'], claimant):
        yield


def _supervise(root, job_id):
    store = BackgroundJobs(root)
    directory = store._job_dir(job_id)
    with _lock(directory / 'supervisor.lock'):
        state = store._state(job_id)
        # A supervisor invocation is not permission to replay an attempted job.
        if state['status'] != 'starting' or state.get('supervisor') is not None:
            return
        state['supervisor'] = _identity(os.getpid())
        _save(directory / 'state.json', state)
        command = state['intent']['profile']['command']
        principal = Principal(state['principal']['subject'], state['principal']['role'], tuple(state['principal']['tasks']))
        selector = selectors.DefaultSelector()
        outputs = []
        child = None
        released = False
        try:
            claimant = None
            if command.get('claim') is not None:
                from .resource_claims import Claimant
                claimant = Claimant(**state['claimant'])
            with _claim_guard(store, command, claimant):
                store._authorize(state, principal, 'job.launch')
                gate_read, gate_write = os.pipe()
                stdout_read, stdout_write = os.pipe()
                stderr_read, stderr_write = os.pipe()
                child = os.fork()
                if child == 0:
                    try:
                        os.close(gate_write)
                        os.close(stdout_read)
                        os.close(stderr_read)
                        os.setsid()
                        os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
                        os.dup2(stdout_write, 1)
                        os.dup2(stderr_write, 2)
                        os.close(stdout_write)
                        os.close(stderr_write)
                        # All other supervisor state/lock fds have CLOEXEC.
                        if os.read(gate_read, 1) != b'R':
                            os._exit(125)
                        os.close(gate_read)
                        os.chdir(command['cwd'])
                        os.execv(command['argv'][0], command['argv'])
                    except BaseException:
                        os._exit(126)
                os.close(gate_read)
                os.close(stdout_write)
                os.close(stderr_write)
                # setsid happens before release; wait until child is group leader.
                ready_deadline = measurements.deadline(1)
                while os.getpgid(child) != child and not ready_deadline.expired():
                    time.sleep(.001)
                state['process'] = _identity(child)
                if state['process'] is None or os.getpgid(child) != child:
                    _error('job_launch_uncertain', 'child process identity unavailable')
                state.update(status='running', started_at=measurements.utc_time(),
                             clock_deadline=dict(basis='stable_time_host_counter_v1',
                                 anchor=measurements.snapshot(), seconds=command['max_seconds']))
                _save(directory / 'state.json', state)
                store._authorize(state, principal, 'job.launch')
                if (directory / 'cancel.json').exists():
                    request = _read(directory / 'cancel.json')
                    actor = request['principal']
                    if request['job_id'] != job_id or request['generation'] != state['generation']:
                        _error('job_stale_generation', 'cancellation generation differs')
                    try:
                        store._authorize(state, Principal(actor['subject'], actor['role'], tuple(actor['tasks'])), 'job.cancel')
                    except WakeError as error:
                        _save(directory / 'cancel-refused.json', dict(version=1, job_id=job_id,
                            reason=getattr(error, 'code', 'permission_denied'), request=request))
                    else:
                        os.close(gate_write)
                        os.waitpid(child, 0)
                        child = None
                        os.close(stdout_read)
                        os.close(stderr_read)
                        for name in ('stdout.log', 'stderr.log'):
                            fd = os.open(directory / name, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
                            os.close(fd)
                        _save(directory / 'result.json', dict(version=1, job_id=job_id,
                            generation=state['generation'], intent_sha256=state['intent_sha256'],
                            process=state['process'], status='cancelled', returncode=None,
                            stored_log_bytes=0, log_truncated=False, completed_at=measurements.utc_time(),
                            cancellation=request, command_not_released=True))
                        return
                if claimant is not None:
                    _verify_claimant(claimant)
                # Persist the possible-effect boundary before releasing exec.
                state['release_attempted'] = True
                _save(directory / 'state.json', state)
                os.write(gate_write, b'R')
                released = True
                os.close(gate_write)
            for fd, name in ((stdout_read, 'stdout.log'), (stderr_read, 'stderr.log')):
                os.set_blocking(fd, False)
                stream = (directory / name).open('wb')
                os.chmod(directory / name, 0o600)
                outputs.append(stream)
                selector.register(fd, selectors.EVENT_READ, stream)
            stored = 0
            truncated = False
            deadline = state['clock_deadline']
            outcome = 'completed'
            stop_at = None
            leader_exit = None
            cancel_checked = False
            cancellation = None
            while True:
                elapsed = measurements.elapsed_bounds(deadline['anchor'], measurements.snapshot())[1]
                if not cancel_checked and (directory / 'cancel.json').exists():
                    cancel_checked = True
                    request = _read(directory / 'cancel.json')
                    try:
                        if request['job_id'] != job_id or request['generation'] != state['generation']:
                            _error('job_stale_generation', 'cancellation generation differs')
                        actor = request['principal']
                        store._authorize(state, Principal(actor['subject'], actor['role'], tuple(actor['tasks'])), 'job.cancel')
                        cancellation = request
                    except WakeError as error:
                        _save(directory / 'cancel-refused.json', dict(version=1, job_id=job_id,
                            reason=getattr(error, 'code', 'permission_denied'), request=request))
                if stop_at is None and (cancellation is not None or elapsed >= deadline['seconds']):
                    outcome = 'cancelled' if cancellation is not None else 'timed_out'
                    os.killpg(child, signal.SIGTERM)
                    stop_at = measurements.deadline(.2)
                leader_exit = os.waitid(os.P_PID, child, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if leader_exit is not None or (stop_at is not None and stop_at.expired()):
                    # Leader is still unreaped: its numeric PGID cannot be recycled.
                    os.killpg(child, signal.SIGKILL)
                    break
                for key, _ in selector.select(.02):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fd)
                        os.close(key.fd)
                        continue
                    keep = min(len(data), max(0, command['max_log_bytes'] - stored))
                    key.data.write(data[:keep])
                    stored += keep
                    truncated |= keep != len(data)
            _, status = os.waitpid(child, 0)
            child = None
            returncode = os.waitstatus_to_exitcode(status)
            # Bound drain even if an unsupported escaped process retains a pipe.
            drain_until = measurements.deadline(.3)
            while selector.get_map() and not drain_until.expired():
                for key, _ in selector.select(.02):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fd)
                        os.close(key.fd)
                        continue
                    keep = min(len(data), max(0, command['max_log_bytes'] - stored))
                    key.data.write(data[:keep])
                    stored += keep
                    truncated |= keep != len(data)
            for stream in outputs:
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
            result = dict(version=1, job_id=job_id, generation=state['generation'],
                intent_sha256=state['intent_sha256'], process=state['process'], status=outcome,
                returncode=returncode, stored_log_bytes=stored, log_truncated=truncated, completed_at=measurements.utc_time())
            if outcome == 'cancelled':
                result['cancellation'] = cancellation
            _save(directory / 'result.json', result)
        except BaseException:
            if child is not None:
                try:
                    if not released:
                        os.close(gate_write)
                    if released:
                        os.killpg(child, signal.SIGKILL)
                    else:
                        os.kill(child, signal.SIGKILL)
                    os.waitpid(child, 0)
                except OSError:
                    pass
            state.update(status='unknown', reason='supervisor_effect_uncertain' if released else 'launch_not_released')
            _save(directory / 'state.json', state)
        finally:
            for key in list(selector.get_map().values()):
                os.close(key.fd)
            selector.close()
            for stream in outputs:
                if not stream.closed:
                    stream.close()


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--supervise':
        _supervise(Path(sys.argv[2]), sys.argv[3])
