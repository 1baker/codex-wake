"""Qualified UTC or authenticated host elapsed bounds for goal supervision.

Only a fresh voluntary session may select counter-relative time. A persisted
anchor is never replaced, and these bounds never become UTC timestamps.
"""
from __future__ import annotations

import math

from .native_intents import eligibility, valid_counter, valid_utc

COUNTER = 'authenticated_host_counter'
FIELDS = ('time_basis', 'clock_anchor', 'clock_observation', 'clock_elapsed_upper')


class GoalTimeUnavailable(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code.replace('_', ' '))


def relative(receipt):
    return receipt.get('time_basis') == COUNTER


def _elapsed(receipt, clock):
    anchor = receipt.get('clock_anchor')
    observed = clock.get('counter')
    prior = receipt.get('clock_observation', anchor)
    if (not valid_counter(anchor) or not valid_counter(observed)
            or clock.get('reason') not in ('authenticated_counter_only', 'authenticated_utc')):
        raise GoalTimeUnavailable('authenticated_elapsed_unavailable')
    if (observed['epoch'] != anchor['epoch'] or observed['frequency'] != anchor['frequency']
            or observed['counter'] < anchor['counter']
            or not valid_counter(prior) or observed['counter'] < prior['counter']):
        raise GoalTimeUnavailable('counter_continuity_lost')
    # Reuse the scheduling owner's conservative same-epoch/rate-bound math.
    result = eligibility(dict(scheduling_intent=dict(
        schedule=dict(kind='after', delay_seconds=0), counter_anchor=anchor,
        utc_anchor=None, ttl_seconds=receipt.get('time_limit_seconds', 1),
        tolerance_seconds=300)), dict(clock, utc=None))
    if result.get('mode') != 'host_counter':
        raise GoalTimeUnavailable(result.get('reason', 'authenticated_elapsed_unavailable'))
    value = max(receipt.get('clock_elapsed_upper', 0), result['upper'])
    receipt.update(clock_observation=dict(observed), clock_elapsed_upper=value)
    return value


def admit(previous, *, allow_counter=False):
    """Qualify admission before effects; old UTC scopes can never switch basis."""
    if previous and relative(previous):
        retained = dict(previous)
        return upper(retained), {key: retained[key] for key in FIELDS}
    if previous or not allow_counter:
        from .lifecycle_budget import trusted_upper
        return trusted_upper(), {}
    from .native_clock import snapshot
    clock = snapshot()  # One bounded acquisition; counter-only is not UTC.
    if valid_utc(clock.get('utc')):
        return clock['utc']['upper'], {}
    if clock.get('reason') not in ('authenticated_counter_only', 'authenticated_utc') or not valid_counter(clock.get('counter')):
        raise GoalTimeUnavailable('admissible_time_unavailable')
    anchor = dict(clock['counter'])
    return 0, dict(time_basis=COUNTER, clock_anchor=anchor,
        clock_observation=dict(anchor), clock_elapsed_upper=0)


def upper(receipt):
    if relative(receipt):
        from .native_clock import snapshot
        return _elapsed(receipt, snapshot())
    # Legacy absolute-UTC receipts retain their original deadline and origin.
    # Their guest BOOTTIME fields remain historical data, never a QPC anchor.
    if (receipt.get('time_basis') not in (None, 'qualified_utc')
            or any(type(receipt.get(key)) not in (int, float)
                   or not math.isfinite(receipt[key])
                   for key in ('started_upper', 'time_origin', 'deadline'))):
        raise GoalTimeUnavailable('clock_unqualified')
    from .lifecycle_budget import trusted_upper
    try:
        current = trusted_upper()
        if type(current) not in (int, float) or not math.isfinite(current):
            raise ValueError('qualified UTC upper required')
        return current
    except (OSError, ValueError, KeyError, TypeError):
        raise GoalTimeUnavailable('clock_unqualified') from None


def public_time(receipt):
    """Explicit public clock domain; relative coordinates are never UTC."""
    if not relative(receipt):
        return {}
    return dict(deadline=None, deadline_utc=None, started_upper=None,
        time_origin=None, elapsed_limit_seconds=receipt['deadline'],
        elapsed_upper_seconds=receipt.get('clock_elapsed_upper', 0),
        time_basis=COUNTER)


def merge_allocation(receipt, allocation):
    """A shared allocation keeps its original clock domain and highest charge."""
    if not relative(receipt) and not relative(allocation):
        return
    if (not relative(receipt) or not relative(allocation)
            or receipt.get('clock_anchor') != allocation.get('clock_anchor')):
        raise GoalTimeUnavailable('allocation_time_basis_changed')
    selected = max((receipt, allocation), key=lambda row: row['clock_observation']['counter'])
    fields = {key: selected[key] for key in FIELDS}
    fields['clock_elapsed_upper'] = max(receipt['clock_elapsed_upper'], allocation['clock_elapsed_upper'])
    receipt.update(fields)
    allocation.update(fields)


def controller_compatible(receipt, controller):
    if relative(receipt) and COUNTER not in controller.get('time_bases', []):
        return False
    if (receipt.get('session_scope') and receipt.get('native_goal_status') is None
            and controller.get('session_scope_without_goal') is not True):
        return False
    return True


def singleton_held(directory):
    """An opaque/stale live singleton is a gate, never permission to compete."""
    import fcntl
    import os
    path = directory / 'watch.lock'
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
        return False
