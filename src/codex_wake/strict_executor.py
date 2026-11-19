"""Independent, RPC-free guard for one dedicated native executor.

The guard is the systemd unit's main process. Exiting fences the assignment and
lets KillMode=control-group stop every descendant, including blocked tools.
"""
from __future__ import annotations

import fcntl
import json
import math
from itertools import islice
import os
import stat
import tempfile
from pathlib import Path
import time

from . import measurements
from .objective_ledger import ObjectiveLedger
from .records import parse_timestamp
from .lifecycle_budget import objective_identity
from .process import boot_id_value, process_exists, process_identity

MAX_ACCOUNTING_BYTES = 32 * 1024 * 1024


class _NonblockingLedger(ObjectiveLedger):
    # Keep the ledger's persistence protocol; only lock acquisition differs.
    _lock_flags = fcntl.LOCK_EX | fcntl.LOCK_NB


def admission_clock(configuration):
    """Validate the immutable clock evidence recorded at executor admission."""
    anchor=configuration.get('clock_anchor')
    if (configuration.get('clock_basis')!='stable_time_host_counter_v1'
            or not isinstance(anchor,dict) or anchor.get('reason')!='authenticated_utc'
            or not isinstance(anchor.get('utc'),dict)
            or anchor['utc'].get('status')!='network'
            or type(anchor.get('valid_for_ns')) is not int
            or not 0<anchor['valid_for_ns']<=300000000000
            or any(type(anchor['utc'].get(key)) not in (int,float)
                   or not math.isfinite(anchor['utc'][key]) for key in ('lower','upper'))
            or anchor['utc']['lower']>anchor['utc']['upper']
            or any(type(configuration.get(key)) not in (int,float)
                   or not math.isfinite(configuration[key]) for key in ('started_upper','deadline','remaining_seconds'))
            or anchor['utc']['upper']!=configuration['started_upper']
            or not 0<=configuration['remaining_seconds']<=configuration['deadline']-configuration['started_upper']):
        raise measurements.TimeUnavailable('strict_clock_anchor_unqualified')
    measurements.elapsed_bounds(anchor,anchor)
    return anchor


class Guard:
    """Check one immutable admission against suspend-aware elapsed time."""

    def __init__(self, configuration):
        self.config = configuration
        strict = configuration['configuration']['strict_execution']
        self.limits = strict.get('limits', strict)
        self.seen_usage = set()
        self.usage_observations = {}
        self.last_verified_accounting_elapsed = 0
        self.last_accounting_error = None
        self.actor_admissions = None
        self.accounting_view = None
        self.accounting_verified = False
        self.native_observed_elapsed = {}
        self.invalidated_actors = set()
        self.clock_observation = None
        self.elapsed_upper = None
        self.fixture_boottime = None
        self.clock_qualified = False

    def accounting_readback(self, *, boottime=None):
        # Rendering/cleanup must never reacquire a failed clock and prevent stop.
        elapsed = self.elapsed_upper if self.clock_qualified else None
        fixture = self.fixture_boottime is not None
        if boottime is not None:
            elapsed = boottime - self.config['started_boottime']
            fixture = True
        epoch = self.config.get('started_boottime') if fixture else None
        view = self.accounting_view or {}
        actors = {}
        for actor_id, actor in view.get('actors', {}).items():
            observation = self.usage_observations.get(actor_id)
            fingerprint, lease = observation if observation else ((None, None), None)
            first, latest = self.native_observed_elapsed.get(actor_id, (None, None))
            actors[actor_id] = dict(known=actor['known'], settled=actor['settled'],
                historical=actor_id in self.config.get('historical_actors', {}),
                native_total_tokens=fingerprint[0], native_published_epoch=fingerprint[1],
                first_observed_boottime=None if epoch is None or first is None else epoch + first,
                last_observed_boottime=None if epoch is None or latest is None else epoch + latest,
                lease_started_boottime=None if epoch is None or lease is None else epoch + lease,
                first_observed_elapsed_upper_seconds=first,
                last_observed_elapsed_upper_seconds=latest,
                lease_started_elapsed_upper_seconds=lease,
                lease_age_seconds=None if lease is None or elapsed is None else elapsed - lease)
        return dict(tokens_used=view.get('tokens_used'), accounting_known=view.get('accounting_known'),
            actors=actors, metric='native_cumulative_total_tokens_including_cached_input',
            last_verified_boottime=(epoch + self.last_verified_accounting_elapsed
                if epoch is not None and self.accounting_verified else None),
            last_verified_elapsed_upper_seconds=(self.last_verified_accounting_elapsed
                if self.accounting_verified else None),
            clock_basis='explicit_boottime_fixture' if fixture else self.config.get('clock_basis'),
            clock_status='qualified' if self.clock_qualified else 'unavailable',
            clock_observation=self.clock_observation,
            observation_lease_seconds=self.limits['accounting_max_age_seconds'],
            detection_interval_seconds=self.limits['poll_seconds'],
            publication_delay_seconds=None, publication_delay_status='unmeasured_independent_clock',
            maximum_token_overshoot=None, enforcement='sampled_stop')

    def final_accounting_fence(self):
        """A forced stop does not turn the last sampled floor into final usage."""
        from .strict_final_usage import fence_final_usage
        if boot_id_value() != self.config['boot_id']:
            return dict(state='accounting_unknown',reason='boot_identity_changed')
        if self.config.get('clock_basis') != 'stable_time_host_counter_v1' or not self.config.get('clock_anchor'):
            return dict(state='accounting_unknown',reason='clock_unqualified')
        try:
            upper=measurements.utc_bounds()[1]
            ledger=_NonblockingLedger(self.config['wake_root'],self.config['objective_id'])
            view=ledger.inspect(now=upper)
            if self.accounting_view is None:
                if view['revision']!=self.config['configuration']['revision']:
                    return dict(state='accounting_unknown',reason='configuration_changed')
                actor_ids=list(view['actors'])
            else:
                actor_ids=list(self.accounting_view['actors'])
            for actor_id in self.invalidated_actors:
                ledger.record(actor_id,None,settled=False,now=upper)
            result=fence_final_usage(ledger,actor_ids,now=upper)
            self.accounting_view=ledger.inspect(now=upper)
            return result
        except measurements.TimeUnavailable:
            return dict(state='accounting_unknown',reason='clock_unqualified')
        except BlockingIOError:
            return dict(state='accounting_unknown',reason='ledger_lock_busy')
        except (OSError,ValueError,KeyError,TypeError):
            return dict(state='accounting_unknown',reason='ledger_unavailable')

    def check(self, *, boottime=None):
        self.clock_qualified = False
        if boot_id_value() != self.config['boot_id']:
            return 'boot_identity_changed'
        try:
            if boottime is not None:
                # This is an explicit host-injected deterministic fixture seam.
                if type(boottime) not in (int, float) or not math.isfinite(boottime):
                    return 'elapsed_time_invalid'
                elapsed = boottime - self.config['started_boottime']
                if elapsed < 0:
                    return 'elapsed_time_invalid'
                upper = self.config['started_upper'] + elapsed
                self.fixture_boottime = boottime
                self.clock_observation = None
            else:
                anchor = admission_clock(self.config)
                current = measurements.snapshot()
                elapsed = measurements.elapsed_bounds(anchor, current)[1]
                if self.clock_observation is not None:
                    measurements.elapsed_bounds(self.clock_observation, current)
                self.clock_observation = current
                self.fixture_boottime = None
                self.elapsed_upper = max(self.elapsed_upper or 0, elapsed)
                elapsed = self.elapsed_upper
                remaining = min(self.config['remaining_seconds'],
                    self.config['deadline'] - self.config['started_upper'])
                graces = self.limits['stop_grace_seconds'] + self.limits['checkpoint_grace_seconds']
                if elapsed >= remaining - graces:
                    self.clock_qualified = True
                    return 'deadline_reached'
                # Counter-qualified elapsed is not itself a fresh UTC estimate.
                if current.get('reason') != 'authenticated_utc' or current.get('utc') is None:
                    return 'clock_unqualified'
                upper = current['utc']['upper']
            self.elapsed_upper = elapsed
            self.clock_qualified = True
            if upper >= self.config['deadline'] - self.limits['stop_grace_seconds'] - self.limits['checkpoint_grace_seconds']:
                return 'deadline_reached'
        except (measurements.TimeUnavailable, KeyError, TypeError, ValueError):
            return 'clock_unqualified'
        try:
            controller = json.loads((Path(self.config['wake_root']) / 'lifecycle/supervision.json').read_text())
            pid = controller['pid']
            if (controller.get('active') is not True or not process_exists(pid)
                    or process_identity(pid) != controller['identity']
                    or Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z'
                    or controller.get('boot_id') != self.config['boot_id']):
                return 'controller_unavailable'
            if boottime is not None:
                if (type(controller.get('observed_boottime')) not in (int, float)
                        or not 0 <= boottime - controller['observed_boottime'] <= self.limits['accounting_max_age_seconds']):
                    return 'controller_unavailable'
            elif not measurements.fresh(controller.get('clock_observation'),
                    self.limits['accounting_max_age_seconds'], current=current):
                return 'controller_unavailable'
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return 'controller_unavailable'
        return self.accounting(upper, elapsed)

    def accounting(self, upper, elapsed):
        """Charge only native rollouts bound to this exact host-owned objective."""
        try:
            ledger = _NonblockingLedger(self.config['wake_root'], self.config['objective_id'])
            view = ledger.inspect(now=upper)
            if view['revision'] != self.config['configuration']['revision']:
                return 'configuration_changed'
            self.accounting_view = view
            self.last_accounting_error = None
            historical = self.config.get('historical_actors', {})
            authorized_revisions = {item['configuration']['revision'] for item in view['authorization_history']}
            # Existing actors inherit the service admission epoch. Actors enrolled
            # later receive a bounded first-observation lease when their ledger
            # admission becomes visible, even before a native thread is bound.
            if self.actor_admissions is None:
                self.actor_admissions = {actor_id: 0 for actor_id in view['actors']}
            for actor_id in view['actors']:
                self.actor_admissions.setdefault(actor_id, elapsed)
            owned = {}
            for path in (Path(self.config['wake_root']) / 'lifecycle').glob('*.json'):
                if path.name == 'supervision.json' or path.name.startswith('owner-'):
                    continue
                receipt = json.loads(path.read_text())
                intent = receipt.get('intent', {})
                operation = intent.get('operation')
                if operation not in {'spawn', 'handoff'} or not receipt.get('thread_id'):
                    continue
                launch = intent.get('launch', {})
                configuration = receipt.get('configuration') if operation == 'handoff' else intent.get('configuration')
                actor = receipt.get('budget_actor')
                revision = (configuration or {}).get('revision')
                approved_history = actor in historical and revision in authorized_revisions
                if ((revision != self.config['configuration']['revision'] and not approved_history)
                        or objective_identity(intent.get('continuation', {})) != self.config['objective_id']
                        or launch.get('app_server') != self.config['endpoint']
                        or Path(launch.get('codex_home', '')).resolve() != Path(self.config['codex_home']).resolve()):
                    continue
                if not actor:
                    continue  # An intent is not a ledger admission.
                bindings = [(receipt['thread_id'], actor)]
                if operation == 'handoff':
                    bindings = []
                    if receipt.get('successor_thread_id'):
                        bindings.append((receipt['successor_thread_id'], actor))
                    source = receipt.get('source_goal')
                    if source and source.get('threadId') == receipt['thread_id']:
                        key = 'goal:' + source['threadId'] + ':' + str(source['createdAt'])
                        source_actor = view['goal_aliases'].get(key, {}).get('actor_id', key)
                        bindings.append((source['threadId'], source_actor))
                for thread, bound_actor in bindings:
                    if bound_actor not in view['actors']:
                        return 'actor_binding_unknown'
                    if thread in owned and owned[thread] != bound_actor:
                        return 'actor_binding_changed'
                    owned[thread] = bound_actor
            snapshots = {}
            home = Path(self.config['codex_home']) / 'sessions'
            paths = list(islice(home.rglob('*.jsonl'), 513)) if home.exists() else []
            if len(paths) > 512:
                return 'accounting_capacity_exceeded'
            total = 0
            for path in paths:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    return 'accounting_capacity_exceeded'
                total += info.st_size
                if total > MAX_ACCOUNTING_BYTES:
                    return 'accounting_capacity_exceeded'
            remaining = MAX_ACCOUNTING_BYTES
            for path in paths:
                path.resolve().relative_to(home.resolve())
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        return 'accounting_capacity_exceeded'
                    data = stream.read(remaining + 1)
                if len(data) > remaining:
                    return 'accounting_capacity_exceeded'
                remaining -= len(data)
                complete = (data[:data.rfind(b'\n') + 1] if not data.endswith(b'\n') else data).decode('utf-8')
                rows = [json.loads(line) for line in complete.splitlines()]
                identities = {row.get('payload', {}).get('id') for row in rows if row.get('type') == 'session_meta'}
                if not rows and elapsed < self.limits['accounting_max_age_seconds']:
                    continue
                if len(identities) != 1:
                    return 'rollout_identity_unknown'
                thread = next(iter(identities))
                if thread not in owned:
                    if elapsed >= self.limits['accounting_max_age_seconds']:
                        return 'unattributed_native_work'
                    continue
                actor = owned[thread]
                if actor in snapshots:
                    return 'rollout_binding_ambiguous'
                usage, observed = None, None
                for row in rows:
                    payload = row.get('payload', {})
                    if row.get('type') == 'event_msg' and payload.get('type') == 'token_count':
                        info = payload.get('info')
                        if info is None or (isinstance(info,dict) and not info.get('total_token_usage')):
                            continue  # Native startup/rate events carry no usage observation.
                        if not isinstance(info,dict):return 'accounting_invalid'
                        value = (info.get('total_token_usage') or {}).get('total_tokens')
                        if type(value) is not int or value < 0 or (usage is not None and value < usage):
                            return 'accounting_invalid'
                        stamp = parse_timestamp(row['timestamp']).timestamp()
                        if observed is not None and stamp < observed:
                            return 'accounting_invalid'
                        usage, observed = value, stamp
                snapshots[actor] = usage, observed
            pending_initial=set()
            for actor_id in view['actors']:
                actor = view['actors'][actor_id]
                usage, observed = snapshots.get(actor_id, (None, None))
                if actor_id in historical:
                    if not actor['settled'] or not actor['known'] or actor['used'] != historical[actor_id]:
                        self.invalidated_actors.add(actor_id)
                        return 'historical_actor_accounting_changed'
                    if usage is not None and usage != historical[actor_id]:
                        self.invalidated_actors.add(actor_id)
                        return 'settled_actor_usage_changed'
                    continue
                if actor['used'] >= actor['reservation']:
                    return 'session_tokens_exhausted'
                if not actor['settled'] and upper >= actor['session_deadline'] - self.limits['stop_grace_seconds'] - self.limits['checkpoint_grace_seconds']:
                    return 'session_deadline_reached'
                if actor['settled']:
                    if usage is not None and usage != actor['used']:
                        self.invalidated_actors.add(actor_id)
                        return 'settled_actor_usage_changed'
                    continue
                if usage is None:
                    if actor_id in self.seen_usage or actor['used'] > 0 or elapsed - self.actor_admissions[actor_id] >= self.limits['accounting_max_age_seconds']:
                        return 'accounting_missing'
                    pending_initial.add(actor_id)
                    continue
                # Native wall time is not an elapsed-time authority. Lease the
                # immutable native observation against this guard's retained elapsed
                # origin; first observation gets only admission's original grace.
                previous = self.usage_observations.get(actor_id)
                fingerprint = (usage, observed)
                if previous is None:
                    seen_elapsed = self.actor_admissions[actor_id]
                else:
                    old_fingerprint, seen_elapsed = previous
                    if observed < old_fingerprint[1]:
                        return 'accounting_invalid'
                    if fingerprint != old_fingerprint:
                        seen_elapsed = elapsed
                self.usage_observations[actor_id] = fingerprint, seen_elapsed
                first, latest = self.native_observed_elapsed.get(actor_id, (elapsed, elapsed))
                if previous is None or previous[0] != fingerprint:
                    latest = elapsed
                self.native_observed_elapsed[actor_id] = first, latest
                if not 0 <= elapsed - seen_elapsed <= self.limits['accounting_max_age_seconds']:
                    return 'accounting_stale'
                self.seen_usage.add(actor_id)
                view = ledger.record(actor_id, usage, settled=actor['settled'], now=upper)
                self.accounting_view = view
                actor = view['actors'][actor_id]
                if not actor['known']:
                    return 'accounting_decreased'
                if usage >= actor['reservation']:
                    return 'session_tokens_exhausted'
                if upper >= actor['session_deadline'] - self.limits['stop_grace_seconds'] - self.limits['checkpoint_grace_seconds']:
                    return 'session_deadline_reached'
            unknown={key for key,actor in view['actors'].items() if not actor['known']}
            if unknown-pending_initial:
                return 'objective_accounting_unknown'
            if view['tokens_used'] >= view['objective_token_limit']:
                return 'objective_tokens_exhausted'
            if not view['actors'] and elapsed >= self.limits['accounting_max_age_seconds']:
                return 'accounting_missing'
            self.last_verified_accounting_elapsed=elapsed
            self.accounting_verified=True
            self.last_accounting_error=None
            return None
        except BlockingIOError:
            self.last_accounting_error='ledger_lock_busy'
            # Admission/accounting updates legitimately hold this lock briefly.
            # Contention is not fresh evidence and cannot extend its lease.
            if elapsed-self.last_verified_accounting_elapsed < self.limits['accounting_max_age_seconds']:
                return None
            return 'accounting_unavailable'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.last_accounting_error=type(exc).__name__
            return 'accounting_unavailable'


def _status(config, state, reason=None, child_pid=None, accounting=None):
    service_identity = None
    invocation = os.environ.get('INVOCATION_ID')
    if invocation:
        for line in Path('/proc/self/cgroup').read_text().splitlines():
            if line.startswith('0::'):
                group = line[3:]
                service_identity = dict(unit=Path(group).name, invocation_id=invocation,
                    control_group=group, main_pid=os.getpid())
                break
    destination = Path(config['status_path'])
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(dict(state=state, reason=reason, generation=config['generation'],
                pid=os.getpid(), identity=process_identity(os.getpid()), child_pid=child_pid,
                endpoint=config['endpoint'], objective_id=config['objective_id'],
                service_identity=service_identity,
                accounting=accounting,
                final_usage=config.get('final_usage'),
                observed_boottime=None,
                clock_basis=(accounting or {}).get('clock_basis',config.get('clock_basis')),
                clock_status=(accounting or {}).get('clock_status','unavailable'),
                clock_observation=(accounting or {}).get('clock_observation'),
                accounting_error=config.get('accounting_error')), stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(config):
    """Run as a service main; a stop fence precedes exit and group termination."""
    import subprocess
    guard = Guard(config)
    child = None
    reason = guard.check()
    try:
        if reason is None:
            environment = dict(os.environ, CODEX_HOME=config['codex_home'])
            for key in ('CODEX_THREAD_ID', 'TMUX', 'TMUX_PANE', 'CODEX_WAKE_A2A_CAPABILITY',
                    'CODEX_WAKE_A2A_BUS_ROOT', 'CODEX_WAKE_SENDER_RECEIPT_AUTHORITY'):
                environment.pop(key, None)
            child = subprocess.Popen(config['argv'], cwd=config['cwd'], env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            config['accounting_error']=guard.last_accounting_error
            _status(config, 'running', child_pid=child.pid, accounting=guard.accounting_readback())
            while reason is None:
                if child.poll() is not None:
                    reason = 'executor_exited'
                    break
                time.sleep(guard.limits['poll_seconds'])
                reason = guard.check()
                if reason is None:
                    config['accounting_error']=guard.last_accounting_error
                    _status(config, 'running', child_pid=child.pid, accounting=guard.accounting_readback())
    except Exception:
        reason = 'guard_observation_failed'
    finally:
        config['accounting_error']=guard.last_accounting_error
        try:
            config['final_usage']=guard.final_accounting_fence()
        except Exception:
            config['final_usage']=dict(state='accounting_unknown',reason='final_accounting_unavailable')
        try:
            accounting=guard.accounting_readback()
        except Exception:
            accounting=dict(clock_status='unavailable',clock_basis=config.get('clock_basis'))
        try:
            _status(config, 'stopping', reason, child_pid=child.pid if child else None, accounting=accounting)
        finally:
            # Timestamp/readback failure cannot keep owned work running.
            if child is not None and child.poll() is None:
                try:
                    child.terminate()
                    grace=measurements.deadline(guard.limits['checkpoint_grace_seconds'])
                    while child.poll() is None and not grace.expired():
                        time.sleep(min(.025,grace.remaining()))
                except (ProcessLookupError,measurements.TimeUnavailable):
                    # Service exit still delegates owned group cleanup to systemd.
                    pass
            _status(config, 'stopped', reason, child_pid=child.pid if child else None, accounting=accounting)
        # Service exit lets systemd enforce its independent control-group stop.
    return 5


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration', type=Path)
    args = parser.parse_args(argv)
    configuration = json.loads(args.configuration.read_text())
    return run(configuration)


if __name__ == '__main__':
    raise SystemExit(main())
