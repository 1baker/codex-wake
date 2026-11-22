"""Bounded process isolation and durable uncertainty for enrolled root polling."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import multiprocessing
import os
import re
import time
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .records import WakeError
from .supervisor import (
    SupervisorConfig, _atomic_write_json, iter_registry_entries, poll_registered_root,
)


@dataclass
class _Worker:
    process: Any
    connection: Any
    task: dict[str, Any] | None = None
    started: float = 0.0


def _worker_main(connection, config: SupervisorConfig, dispatch: bool) -> None:
    # Preserve dispatched native children, but never leave a blocked pool worker
    # behind when its coordinator is killed before it can perform cleanup.
    parent = multiprocessing.parent_process()
    if parent is not None:
        def parent_exit():
            parent.join()
            os._exit(1)
        threading.Thread(target=parent_exit, daemon=True).start()
    try:
        while True:
            try:
                task = connection.recv()
            except EOFError:
                return
            if task is None:
                return
            cpu_start = time.process_time()
            result = poll_registered_root(
                config, task['entry'], mode='loop', dispatch=dispatch,
                signal_reconcile_reason=task['reason'],
            )
            result['poll_cpu_seconds'] = time.process_time() - cpu_start
            connection.send(result)
    finally:
        connection.close()


def _key(root: str) -> str:
    return hashlib.sha256(str(Path(root).expanduser().resolve()).encode()).hexdigest()


def _hold(task: dict[str, Any], reason: str) -> None:
    root = Path(task['wake_root'])
    path = root / 'monitor-reconciliation.json'
    # The first uncertain outcome remains the reconciliation authority.
    from .monitor_ownership import reconciliation_required
    if not reconciliation_required(root):
        _atomic_write_json(path, {**task, 'reason': reason, 'held_at': time.time()})


def reconcile_root(config: SupervisorConfig, root_id: str, *, expected_token: str) -> None:
    """Acknowledge an exact uncertain poll after inspecting its effects."""
    from .monitor_ownership import MonitorOwnership

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", expected_token):
        raise WakeError("invalid reconciliation token")
    entry = next((e for e in iter_registry_entries(config.registry_dir)
                  if e.get('root_id') == root_id), None)
    if entry is None:
        raise WakeError('root is not enrolled')
    root = Path(entry['wake_root']).resolve()
    with MonitorOwnership(root) as owner:
        if not owner.acquired:
            raise WakeError('root still has a live polling owner; reconciliation refused')
        hold = root / 'monitor-reconciliation.json'
        try:
            value = json.loads(hold.read_text())
        except (OSError, ValueError):
            raise WakeError('no readable reconciliation hold; inspect the root manually') from None
        if value.get('token') != expected_token:
            raise WakeError('reconciliation token changed; inspect current uncertain outcome')
        # Retain the admission evidence before removing the guard.
        _atomic_write_json(config.state_dir / 'reconciled' / (expected_token + '.json'),
                           {**value, 'reconciled_at': time.time()})
        pending = config.state_dir / 'inflight' / (_key(str(root)) + '.json')
        if pending.exists():
            data = json.loads(pending.read_text())
            if data.get('token') != expected_token:
                raise WakeError('another in-flight generation exists; reconciliation refused')
            pending.unlink()
        hold.unlink()


def recover_interrupted_root(config: SupervisorConfig, entry: dict[str, Any]) -> Literal['owner_busy'] | None:
    """Transfer a supervisor hold under poll custody, reporting temporary contention."""
    from .monitor_ownership import MonitorOwnership
    from .records import ACTIVE_STATUS_DIRS, classify_record, WakePath

    root = Path(entry['wake_root']).expanduser().resolve()
    marker = root / 'monitor-reconciliation.json'
    if not marker.is_file() or marker.is_symlink():
        return
    with MonitorOwnership(root) as owner:
        if not owner.acquired:
            return 'owner_busy'
        task = json.loads(marker.read_text())
        if not isinstance(task, dict) or task.get('recovery_schema') != 1:
            return
        token = task.get('token')
        if (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', token)
                or task.get('root_id') != entry['root_id'] or task.get('wake_root') != str(root)
                or task.get('reason') not in ('supervisor_stopped_with_inflight_poll',
                    'coordinator_restarted_with_inflight_poll', 'poll_failed_with_possible_effects',
                    'worker_admission_outcome_unknown', 'worker_exited_with_inflight_poll',
                    'poll_timeout_outcome_unknown')):
            return
        pending = config.state_dir / 'inflight' / (_key(str(root)) + '.json')
        if pending.exists():
            admission = json.loads(pending.read_text())
            if not isinstance(admission, dict) or admission.get('token') != token:
                return
        # A lifecycle entry that cannot be safely inspected is not evidence
        # that work stayed pending. In particular, never open a FIFO here.
        if any(path.is_symlink() or not path.is_file()
               for status in ACTIVE_STATUS_DIRS for path in (root / status).glob('*.json')):
            return
        legacy = []
        for path in (root / 'firing').glob('*.json'):
            record = json.loads(path.read_text())
            if not isinstance(record, dict) or record.get('status') != 'firing' or record.get('id') != path.stem:
                return
            classification = classify_record(record)
            if classification == 'hold':
                return
            if classification not in ('native_intent_v6', 'runtime_intent_v7'):
                if any((root / status / path.name).exists() for status in ACTIVE_STATUS_DIRS if status != 'firing'):
                    return
                if record.get('target', {}).get('transport') == 'native':
                    if record.get('native_delivery', {}).get('state') not in ('uncertain', 'accepted'):
                        return
                    continue
                legacy.append(WakePath(path, record))
        # Native dispatch retains its intent before submission and reconciles
        # that intent without replay. Older transports lack that guarantee.
        for item in legacy:
            if not item.record.get('ack_wait_time_held'):
                _atomic_write_json(item.path, dict(item.record, ack_wait_time_held=True))
        _atomic_write_json(config.state_dir / 'reconciled' / (token + '.json'),
                           {**task, 'recovery': 'record_scoped', 'legacy_holds': [w.record['id'] for w in legacy]})
        pending.unlink(missing_ok=True)
        marker.unlink()


class SupervisorScheduler:
    """One coordinator, a bounded reusable pool, and independent root schedules.

    tick() is nonblocking with respect to polling: it starts ready work and returns
    completed results. In-flight journals precede worker admission. Unknown work
    is held across coordinator restart rather than replayed.
    """

    def __init__(self, config: SupervisorConfig, *, dispatch: bool = True):
        self.config = config
        self.dispatch = dispatch
        self.workers: list[_Worker] = []
        self.next_due: dict[str, float] = {}
        self.started_roots: set[str] = set()
        self._lock = None
        self._closed = False
        self._entries: list[dict[str, Any]] = []
        self._refresh_at = 0.0
        self._startup_recovery: set[str] = set()

    def __enter__(self):
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = (self.config.state_dir / 'scheduler.lock').open('a+')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            self._lock = None
            raise WakeError('another supervisor owns this state directory') from None
        try:
            for path in (self.config.state_dir / 'inflight').glob('*.json'):
                task = json.loads(path.read_text())
                _hold(task, 'coordinator_restarted_with_inflight_poll')
                path.unlink()
            for entry in iter_registry_entries(self.config.registry_dir):
                if entry.get('enabled') and entry.get('wake_root'):
                    self._recover_startup_entry(entry)
        except Exception:
            self.close()
            raise
        return self

    def _recover_startup_entry(self, entry: dict[str, Any]) -> None:
        root_id = entry['root_id']
        self._startup_recovery.discard(root_id)
        try:
            if recover_interrupted_root(self.config, entry) == 'owner_busy':
                self._startup_recovery.add(root_id)
        except (OSError, RuntimeError, TypeError, ValueError, WakeError):
            # Unreadable evidence keeps the original marker for this root.
            return

    @property
    def running_count(self) -> int:
        return sum(w.task is not None for w in self.workers)

    @property
    def worker_pids(self) -> list[int]:
        return [w.process.pid for w in self.workers if w.process.is_alive()]

    def _journal(self, task: dict[str, Any]) -> Path:
        return self.config.state_dir / 'inflight' / (_key(task['wake_root']) + '.json')

    def _new_worker(self) -> _Worker:
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=_worker_main,
                                  args=(child, self.config, self.dispatch), daemon=True)
        process.start()
        child.close()
        worker = _Worker(process, parent)
        self.workers.append(worker)
        return worker

    def _retire(self, worker: _Worker) -> None:
        if worker.process.is_alive():
            worker.process.terminate()
        worker.process.join(timeout=1)
        if worker.process.is_alive():
            worker.process.kill()
            worker.process.join(timeout=1)
        worker.connection.close()
        self.workers.remove(worker)

    def _uncertain(self, worker: _Worker, reason: str) -> dict[str, Any]:
        task = worker.task
        assert task is not None
        _hold(task, reason)
        self._journal(task).unlink(missing_ok=True)
        self._retire(worker)
        return {'root_id': task['root_id'], 'wake_root': task['wake_root'],
                'ok': False, 'activity': True, 'error': reason,
                'reconciliation_token': task['token']}

    def tick(self) -> list[dict[str, Any]]:
        if self._lock is None or self._closed:
            raise WakeError('scheduler must be entered before polling')
        now = time.monotonic()
        completed: list[dict[str, Any]] = []
        for worker in list(self.workers):
            if worker.task is None:
                if not worker.process.is_alive():
                    self._retire(worker)
                continue
            task = worker.task
            if worker.connection.poll():
                try:
                    result = worker.connection.recv()
                except (EOFError, OSError):
                    completed.append(self._uncertain(worker, 'worker_exited_with_inflight_poll'))
                    continue
                if not result['ok'] and self.dispatch:
                    _hold(task, 'poll_failed_with_possible_effects')
                    result['reconciliation_token'] = task['token']
                self._journal(task).unlink(missing_ok=True)
                result['poll_wall_seconds'] = now - worker.started
                completed.append(result)
                # Match prior post-pass sleep; never catch up missed intervals.
                self.next_due[task['key']] = now + task['interval']
                worker.task = None
            elif not worker.process.is_alive():
                completed.append(self._uncertain(worker, 'worker_exited_with_inflight_poll'))
            elif now - worker.started >= self.config.poll_timeout:
                completed.append(self._uncertain(worker, 'poll_timeout_outcome_unknown'))
        # Registry reads are bounded independently of the fastest root cadence.
        if now >= self._refresh_at:
            self._entries = iter_registry_entries(self.config.registry_dir)
            self._refresh_at = now + min(self.config.interval, 1.0)
            for entry in self._entries:
                if (entry.get('root_id') in self._startup_recovery
                        and entry.get('enabled') and entry.get('wake_root')):
                    self._recover_startup_entry(entry)
        busy = {w.task['key'] for w in self.workers if w.task}
        due: dict[str, dict[str, Any]] = {}
        for entry in self._entries:
            if not entry.get('enabled') or not entry.get('wake_root'):
                continue
            try:
                root = str(Path(entry['wake_root']).expanduser().resolve())
                key = _key(root)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                # A malformed/changed enrollment cannot abort admission for all
                # other roots. Rate-limit its failure to the configured cadence.
                error_key = 'invalid:' + str(entry.get('_path', entry.get('root_id')))
                if now >= self.next_due.get(error_key, 0):
                    completed.append({'root_id': entry.get('root_id', ''),
                                      'ok': False, 'activity': True,
                                      'error': f'root path unavailable: {exc}'})
                    self.next_due[error_key] = now + self.config.interval
                continue
            if key in busy or key in due or now < self.next_due.get(key, 0):
                continue
            from .monitor_ownership import reconciliation_required
            if reconciliation_required(Path(root)):
                continue
            interval = entry.get('poll_interval', self.config.interval)
            if type(interval) not in (int, float) or not math.isfinite(interval) or interval <= 0:
                completed.append({'root_id': entry['root_id'], 'ok': False,
                                  'activity': True, 'error': 'invalid per-root poll_interval'})
                self.next_due[key] = now + self.config.interval
                continue
            due[key] = {'key': key, 'root_id': entry['root_id'], 'wake_root': root,
                        'entry': entry, 'interval': interval}
        for key, item in sorted(due.items(), key=lambda pair: self.next_due.get(pair[0], 0)):
            worker = next((w for w in self.workers if w.task is None), None)
            if worker is None:
                if len(self.workers) >= self.config.max_workers:
                    break
                worker = self._new_worker()
            task = {**item, 'token': uuid.uuid4().hex, 'coordinator_pid': os.getpid(),
                    'recovery_schema': 1}
            _atomic_write_json(self._journal(task), task)
            worker.task = task
            worker.started = now
            try:
                worker.connection.send({'entry': item['entry'],
                    'reason': 'periodic' if key in self.started_roots else 'startup'})
            except (BrokenPipeError, OSError):
                completed.append(self._uncertain(worker, 'worker_admission_outcome_unknown'))
                continue
            self.started_roots.add(key)
        return completed

    def wait_seconds(self) -> float:
        """Wake promptly for completed children without registry/record busy polling."""
        now = time.monotonic()
        future = [t - now for t in self.next_due.values() if t > now]
        return max(0.001, min([0.05 if self.running_count else 1.0,
                              max(0.001, self._refresh_at - now), *future]))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            deadline = time.monotonic() + 2
            while any(w.task for w in self.workers) and time.monotonic() < deadline:
                for worker in list(self.workers):
                    if worker.task is not None and worker.connection.poll():
                        try:
                            result = worker.connection.recv()
                        except (EOFError, OSError):
                            continue
                        if not result['ok'] and self.dispatch:
                            _hold(worker.task, 'poll_failed_with_possible_effects')
                        self._journal(worker.task).unlink(missing_ok=True)
                        worker.task = None
                if any(w.task for w in self.workers):
                    time.sleep(0.01)
            for worker in list(self.workers):
                if worker.task is not None:
                    _hold(worker.task, 'supervisor_stopped_with_inflight_poll')
                    self._journal(worker.task).unlink(missing_ok=True)
                self._retire(worker)
        finally:
            if self._lock is not None:
                self._lock.close()
                self._lock = None

    def __exit__(self, *_exc):
        self.close()
