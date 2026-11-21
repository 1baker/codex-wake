"""Authenticated StableTime adapter; no guest-clock extrapolation or fallback."""
from datetime import datetime
from decimal import Decimal
import ipaddress
import json
import math
from pathlib import Path
import ssl
import subprocess
import urllib.request
from urllib.parse import urlsplit

from .time_provider import TimeDecision, require_time_decision


def decision_from_response(response, *, counter, frequency):
    if not isinstance(response, dict):
        raise ValueError('invalid_stable_time_response')
    if response.get('status') in ('unavailable', 'unbounded'):
        return TimeDecision('uncertain', reason='stable_time_unavailable')
    version_two = response.get('contract_version') == '2.0'
    policy = response['counter_policy']
    measurement = response['measurement']
    estimate = response['estimate']
    operators = response['operators']
    measured, measured_frequency = int(measurement['counter']), int(measurement['frequency_hz'])
    rate, age, maximum_age = policy['rate_ppm'], response['acquisition_age_ns'], policy['maximum_age_ns']
    if (response.get('contract_version') not in ('1.0', '2.0')
            or response.get('status') not in ('qualified_live', 'qualified_holdover')
            or (version_two and (response.get('bound') != 'finite' or response.get('best_effort') is not None))
            or response.get('authentication') != 'NTS-verified'
            or response.get('time_scale') != 'UTC-step; announced-leaps-unavailable'
            or not response.get('epoch') or response.get('evidence_generation', 0) <= 0
            or len(set(operators)) < 2 or any(not isinstance(x, str) or not x.strip() for x in operators)
            or any(type(x) is not int for x in (rate, age, maximum_age, counter, frequency))
            or not 0 <= rate < 1000000 or not 0 <= age <= maximum_age <= (300000000000 if version_two else 10000000000)
            or frequency <= 0 or frequency != measured_frequency or counter < measured):
        raise ValueError('invalid_stable_time_evidence')
    def stamp(value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('timezone_required')
        # datetime truncates nanoseconds; widen outward below.
        return parsed.timestamp()
    lower, middle, upper = (stamp(estimate[x]) for x in ('earliest_utc', 'utc', 'latest_utc'))
    radius = estimate['maximum_error_ns']
    if (type(radius) is not int or radius < 0 or (not version_two and radius >= 100000000)
            or not lower <= middle <= upper):
        raise ValueError('invalid_stable_time_interval')
    if max(middle-lower, upper-middle) > radius / 1000000000 + .000002:
        raise ValueError('inconsistent_stable_time_interval')
    elapsed = Decimal(counter-measured) * 1000000 / (Decimal(frequency) * (1000000-rate))
    if Decimal(age) / 1000000000 + elapsed > Decimal(maximum_age) / 1000000000:
        raise ValueError('stable_time_handoff_expired')
    # Retaining the old lower endpoint is conservative for not-before checks.
    # Advance upper using the same native counter envelope, never a WSL timer.
    lower = math.nextafter(lower-.000001, -math.inf)
    upper = math.nextafter(upper+float(elapsed)+.000001, math.inf)
    return require_time_decision(TimeDecision('network', tuple('stable-time:'+x for x in operators), lower, upper))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('stable_time_redirect_refused')


def service_time_result(config_path, *, measurement_only=False):
    """Read evidence at the service instant, not at client receipt.

    measurement_only remains accepted for existing inspection callers. All
    Python consumers now use the service measurement; final Native admission
    owns its separate original-expiry check and handoff accounting.
    """
    decision, observation, _ = _service_time_result(config_path, degraded=False)
    return decision, observation


def service_time_inspection(config_path):
    """Read opt-in evidence for inspection without granting deadline authority."""
    return _service_time_result(config_path, degraded=True)


def _service_time_result(config_path, *, degraded):
    observation = None
    fallback = None
    failure = 'stable_time_client_configuration_invalid'
    try:
        config = json.loads(Path(config_path).read_text())
        if not isinstance(config, dict):
            raise ValueError('invalid_stable_time_config')
        origin = config['url']
        parsed = urlsplit(origin)
        host = parsed.hostname
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.path not in ('', '/')
                or not (host == 'localhost' or ipaddress.ip_address(host).is_loopback)):
            raise ValueError('stable_time_origin_refused')
        token = Path(config['token_file']).read_text().strip()
        if len(token) != 64 or any(c not in '0123456789abcdefABCDEF' for c in token):
            raise ValueError('stable_time_credentials_invalid')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=config['ca_file'])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                            urllib.request.HTTPSHandler(context=context))
        route = '/v1/fallback' if degraded else '/v1/time'
        request = urllib.request.Request(origin.rstrip('/') + route,
                                         headers={'Authorization': 'Bearer '+token})
        failure = 'stable_time_client_transport_failed'
        with opener.open(request, timeout=3) as stream:
            body = stream.read(1048577)
        failure = 'stable_time_response_invalid'
        if len(body) > 1048576:
            raise ValueError('stable_time_response_too_large')
        response = json.loads(body)
        if not isinstance(response, dict):
            raise ValueError('invalid_stable_time_response')
        if degraded:
            fallback = response['fallback']
            if fallback is not None and (
                    not isinstance(fallback, dict)
                    or fallback.get('assurance') not in ('single_source', 'windows_only')
                    or not isinstance(fallback.get('utc'), str)):
                raise ValueError('invalid_stable_time_fallback')
            response = response['corroborated']
            if not isinstance(response, dict):
                raise ValueError('invalid_stable_time_response')
        observation = {key: response[key] for key in (
            'contract_version', 'status', 'bound', 'best_effort', 'estimate',
            'qualification', 'reason', 'exclusions', 'acquisition_age_ns',
            'counter_policy', 'epoch', 'evidence_generation', 'measurement',
            'operators', 'authentication', 'time_scale') if key in response}
        if response.get('status') in ('unavailable', 'unbounded'):
            return TimeDecision('uncertain', reason='stable_time_unavailable'), observation, fallback
        measurement = response['measurement']
        if any(not isinstance(measurement.get(key), str) or not measurement[key].isascii()
               or not measurement[key].isdigit() or len(measurement[key]) > 20
               or int(measurement[key]) > 2**64-1 for key in ('counter', 'frequency_hz')):
            raise ValueError('invalid_service_measurement')
        at_measurement = decision_from_response(response,
            counter=int(measurement['counter']), frequency=int(measurement['frequency_hz']))
        return at_measurement, observation, fallback
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, subprocess.SubprocessError):
        # Never include transport errors containing credentials or substitute guest time.
        return TimeDecision('uncertain', reason=failure), observation, None


def service_time_decision(config_path):
    """Finite Python selection bounds at the service decision instant."""
    return service_time_result(config_path)[0]
