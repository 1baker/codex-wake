"""Qualified Stable Time measurements; no guest clock fallback."""
from decimal import Decimal
from copy import deepcopy
import math
from uuid import UUID


class TimeUnavailable(ValueError):
    """Time-dependent work must hold until authority is qualified."""


def snapshot():
    from . import native_clock
    # snapshot's legacy no-config network path is not Stable Time authority.
    try:
        if not native_clock.configuration():
            raise TimeUnavailable('stable_time_configuration_required')
        value = native_clock.snapshot()
        if value.get('reason') in {
                'stable_time_configuration_required', 'stable_time_client_configuration_invalid',
                'stable_time_client_transport_failed', 'stable_time_response_invalid'}:
            raise TimeUnavailable(value['reason'])
        _counter(value)
        if value['reason'] == 'authenticated_utc':
            _utc(value)
        return deepcopy(value)
    except TimeUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise TimeUnavailable('stable_time_unavailable_or_unqualified') from None


def elapsed_bounds(anchor, current):
    before, after = _counter(anchor), _counter(current)
    if (before['epoch'] != after['epoch'] or before['frequency'] != after['frequency']
            or after['counter'] < before['counter']):
        raise TimeUnavailable('stable_time_counter_continuity_lost')
    delta = after['counter'] - before['counter']
    rate = max(before['rate_ppm'], after['rate_ppm'])
    frequency = Decimal(before['frequency'])
    lower = Decimal(max(0, delta - 1)) * 1000000 / (frequency * (1000000 + rate))
    upper = Decimal(delta + 1) * 1000000 / (frequency * (1000000 - rate))
    return max(0, math.nextafter(float(lower), -math.inf)), math.nextafter(float(upper), math.inf)


def fresh(anchor, seconds, *, current=None):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise TimeUnavailable('stable_time_invalid_duration')
    return elapsed_bounds(anchor, snapshot() if current is None else current)[1] <= seconds


def utc_bounds():
    """Bounds at a fresh service measurement, never receipt-time extrapolation."""
    return _utc(snapshot())


def utc_time():
    """Service-measurement upper UTC; decision callers must use both bounds."""
    return utc_bounds()[1]


def datetime_now(tz=None):
    from datetime import UTC, datetime
    value = datetime.fromtimestamp(utc_time(), UTC)
    return value.astimezone(tz) if tz is not None else value


class Deadline:
    def __init__(self, seconds):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise TimeUnavailable('stable_time_invalid_duration')
        self._seconds = seconds
        self._anchor = snapshot()
        self._last_observation = self._anchor
        self._elapsed_upper = 0

    def remaining(self):
        current = snapshot()
        elapsed_bounds(self._last_observation, current)
        elapsed = elapsed_bounds(self._anchor, current)[1]
        self._last_observation = current
        self._elapsed_upper = max(self._elapsed_upper, elapsed)
        return max(0, self._seconds - self._elapsed_upper)

    def restrict(self, seconds):
        """Tighten total duration against this original anchor, never renew it."""
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise TimeUnavailable('stable_time_invalid_duration')
        self._seconds = min(self._seconds, seconds)
        return self

    def expired(self):
        return self.remaining() <= 0


def deadline(seconds):
    return Deadline(seconds)


def _counter(value):
    try:
        counter = value['counter']
        if (value['reason'] not in ('authenticated_utc', 'authenticated_counter_only')
                or str(UUID(counter['epoch'])) != counter['epoch']
                or any(type(counter[key]) is not int or not 0 <= counter[key] < 2**64
                       for key in ('counter', 'frequency', 'rate_ppm'))
                or counter['frequency'] == 0 or counter['rate_ppm'] > 5000):
            raise ValueError('invalid_counter')
        return counter
    except (KeyError, TypeError, ValueError, AttributeError):
        raise TimeUnavailable('stable_time_counter_unqualified') from None


def _utc(value):
    try:
        utc = value['utc']
        if (value['reason'] != 'authenticated_utc' or utc['status'] != 'network'
                or type(value.get('valid_for_ns')) is not int
                or not 0 < value['valid_for_ns'] <= 300000000000
                or any(type(utc[key]) not in (int, float) or not math.isfinite(utc[key])
                       for key in ('lower', 'upper'))
                or utc['lower'] > utc['upper']):
            raise ValueError('invalid_utc')
        return utc['lower'], utc['upper']
    except (KeyError, TypeError, ValueError):
        raise TimeUnavailable('stable_time_utc_unqualified') from None
