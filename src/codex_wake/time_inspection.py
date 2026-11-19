"""Inspection-only acquisition; never changes clocks or mailbox state."""
from dataclasses import asdict
import base64
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import uuid
from .time_provider import Observation, TimeDecision, select_time

# Inspection policy: conservative subsecond consensus, bounded two-minute holdover.
TOLERANCE = 1.0
MAX_AGE = 120.0
MAX_RTT = 0.5
MAX_ROOT_ERROR = 0.1
DRIFT = 100 / 1_000_000
POWERSHELL = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'


def windows_collect(sources, request):
    script = Path(__file__).with_name('time_collect.ps1').read_text()
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            input=json.dumps(dict(request, hosts=[s['host'] for s in sources])),
                            text=True, capture_output=True, timeout=25)
    if result.returncode:
        raise ValueError('collector_failed')
    return json.loads(result.stdout.lstrip('\ufeff'))


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('invalid_counter')
    return value


def _observation(reply, data, request):
    frequency, end = _number(data['frequency']), _number(data['end'])
    sent, received = _number(reply['sent']), _number(reply['received'])
    if frequency <= 0 or not 0 <= sent <= received <= end:
        raise ValueError('invalid_counter')
    age, rtt = (end-received)/frequency, (received-sent)/frequency
    if age > MAX_AGE:
        raise ValueError('stale_observation')
    if rtt > MAX_RTT:
        raise ValueError('excessive_delay')
    packet = base64.b64decode(reply['packet'], validate=True)
    token = base64.b64decode(reply['token'], validate=True)
    if len(packet) != 48 or len(token) != 8:
        raise ValueError('malformed_reply')
    if packet[24:32] != token:
        raise ValueError('origin_mismatch')
    if packet[0] >> 6 != 0:
        raise ValueError('leap_or_unsynchronized')
    if (packet[0] >> 3) & 7 not in (3,4) or packet[0] & 7 != 4 or not 1 <= packet[1] <= 15:
        raise ValueError('invalid_server_reply')
    def stamp(offset):
        seconds, fraction = struct.unpack_from('!II', packet, offset)
        return seconds-2208988800+fraction/2**32
    rx, tx = stamp(32), stamp(40)
    # Era zero only, explicitly retired before 2036; reject zero/ancient stamps.
    if not 1577836800 <= rx <= tx < 2085978496 or tx-rx > rtt+0.001:
        raise ValueError('invalid_timestamp')
    root_delay = abs(struct.unpack_from('!i',packet,4)[0]/65536)
    dispersion = struct.unpack_from('!I',packet,8)[0]/65536
    precision = struct.unpack_from('!b',packet,3)[0]
    if not -30 <= precision <= 0:
        raise ValueError('invalid_precision')
    error = root_delay/2+dispersion+2**precision+(age+rtt)*DRIFT+2/frequency
    if root_delay/2+dispersion > MAX_ROOT_ERROR:
        raise ValueError('poor_root_quality')
    return Observation(reply['host'], reply['operator'], tx+age-error, tx+age+rtt+error,
                       age, request['guest_boot']+':'+data['host_boot'], data['generation'],
                       'network','utc-step',True)


SOURCES = (
    dict(operator='cloudflare', host='time.cloudflare.com', scale='utc-step', authentication='plain-ntp-inspection-only'),
    dict(operator='nist', host='time.nist.gov', scale='utc-step', authentication='plain-ntp-inspection-only'),
    dict(operator='netnod', host='ntp.se', scale=None, authentication='not-qualified'),
    dict(operator='ptb', host='ptbtime1.ptb.de', scale=None, authentication='not-qualified'),
    dict(operator='alastyr', host='ntp.alastyr.com', scale='utc-step', authentication='plain-ntp-inspection-only'),
)


def _windows_observation(window, data, request):
    if window.get('service_running') is not True or 'error' in window:
        raise ValueError(window.get('error','windows_unsynchronized'))
    if type(window['leap']) is not int or window['leap'] != 0 or type(window['stratum']) is not int or not 1 <= window['stratum'] <= 15:
        raise ValueError('windows_unsynchronized')
    if window.get('source') not in ('time.cloudflare.com', 'time.nist.gov'):
        raise ValueError('windows_source_unqualified')
    utc, sampled = _number(window['utc']), _number(window['sampled'])
    sync_age = _number(window['sync_age'])
    dispersion, offset = _number(window['root_dispersion']), _number(window['phase_offset'])
    if not 0 <= sync_age <= 300 or not 0 <= dispersion <= 0.1 or abs(offset) > 0.1:
        raise ValueError('windows_health_unbounded')
    age = (data['end']-sampled)/data['frequency']
    if utc <= 0 or age < 0 or age > MAX_AGE:
        raise ValueError('windows_stale')
    error = dispersion+abs(offset)+0.016+(sync_age+age)*DRIFT+2/data['frequency']
    if error > 0.25:
        raise ValueError('windows_health_unbounded')
    return Observation('windows','microsoft-host',utc+age-error,utc+age+error,age,
                       request['guest_boot']+':'+data['host_boot'],data['generation'],'windows','utc-step',True)


def inspect_time(*, offline=False, collector=None):
    sources = [dict(source, reason='time_scale_unqualified' if source['scale'] is None else 'acquisition_not_requested') for source in SOURCES]
    report = dict(schema=1, production_ready=False, purpose='inspection-only',
                  decision=asdict(TimeDecision('uncertain',reason='acquisition_not_requested')), sources=sources)
    if offline:
        return report
    if collector is None:
        report['decision'] = asdict(TimeDecision('uncertain', reason='stable_time_acquisition_required'))
        return report
    request = dict(request_id=str(uuid.uuid4()),guest_boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    try:
        data = collector([s for s in sources if s['scale']],request)
        if data['request_id'] != request['request_id'] or data['guest_boot'] != request['guest_boot']:
            raise ValueError('collector_identity_mismatch')
        if not all(isinstance(data[k],str) and data[k] for k in ('host_boot','host_boot_end','generation')) or data['host_boot'] != data['host_boot_end']:
            raise ValueError('host_boot_changed')
        frequency = _number(data['frequency'])
        duration = _number(data['end'])-_number(data['start'])
        if frequency <= 0 or duration < 0 or duration/frequency > 20:
            raise ValueError('collector_round_too_long')
        if not isinstance(data['replies'],list) or len(data['replies']) > 4:
            raise ValueError('invalid_collector_replies')
        observations = []
        for source in sources:
            if source['scale'] is None:
                continue
            replies = [r for r in data['replies'] if isinstance(r,dict) and r.get('host') == source['host']]
            try:
                if len(replies) != 1:
                    raise ValueError('missing_or_duplicate_reply')
                reply = replies[0]
                if 'error' in reply:
                    raise ValueError(str(reply['error']))
                observation = _observation(dict(reply,operator=source['operator']),data,request)
                if observation.upper-observation.lower > TOLERANCE:
                    raise ValueError('interval_too_wide')
                observations.append(observation)
                source.update(reason='accepted', observation=asdict(observation), peer=reply['peer'])
            except (KeyError,TypeError,ValueError,OverflowError) as error:
                source['reason'] = str(error)
        try:
            window = data.get('windows', {})
            observation = _windows_observation(window,data,request)
            observations.append(observation)
            report['windows'] = dict(reason='accepted',observation=asdict(observation))
        except (KeyError,TypeError,ValueError,OverflowError) as error:
            report['windows'] = dict(reason=str(error))
        decision = select_time(observations, boot=request['guest_boot']+':'+data['host_boot'],
                               round_id=data['generation'],tolerance=TOLERANCE,max_age=MAX_AGE,scale='utc-step')
        report.update(decision=asdict(decision), instant=dict(host_boot=data['host_boot'],qpc=data['end'],frequency=frequency,
                      generation=data['generation'], guest_boot=request['guest_boot']),
                      policy=dict(tolerance=TOLERANCE,max_age=MAX_AGE,max_rtt=MAX_RTT,drift_ppm=100),
                      note='Bounds refer to collector completion, not the later print instant. No deadline effects are authorized.')
    except (OSError,subprocess.SubprocessError,KeyError,TypeError,ValueError,OverflowError) as error:
        report['decision'] = asdict(TimeDecision('uncertain',reason='acquisition_unavailable'))
        for source in sources:
            if source['scale']:
                source['reason'] = str(error)
    return report


def add_time_parser(subparsers):
    parser = subparsers.add_parser('time', help='inspect external time without changing clocks')
    commands = parser.add_subparsers(dest='time_command', required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('--offline', action='store_true', help='show admission policy without network access')


def stable_time_config():
    if 'CODEX_WAKE_STABLE_TIME_CONFIG' in os.environ:
        return os.environ['CODEX_WAKE_STABLE_TIME_CONFIG'] or None
    candidate = Path.home() / '.config' / 'codex-wake' / 'stable-time-client.json'
    return str(candidate) if candidate.exists() else None


def time_command(args):
    config = stable_time_config()
    if config:
        from .stable_time import service_time_result
        decision, observation = (TimeDecision('uncertain', reason='acquisition_not_requested'), None) if args.offline else service_time_result(config, measurement_only=True)
        measurement_decision = decision
        report = dict(schema=1, provider='stable-time', authentication='NTS-required',
                      decision=asdict(decision), measurement_decision=asdict(measurement_decision),
                      observation=observation, purpose='installed-service-consumer',
                      basis='service_measurement', receipt_time_bound=False, production_ready=False,
                      note='Bounds describe the service measurement instant, not receipt or print time. Inspection authorizes no dispatch.')
    else:
        report = inspect_time(offline=True)
        if not args.offline:
            report.update(provider='stable-time',
                decision=asdict(TimeDecision('uncertain', reason='stable_time_configuration_required')))
    print(json.dumps(report, sort_keys=True))
    return 0


def network_time_decision():
    """Trusted adapter seam for explicitly opted-in network-time domains."""
    config = stable_time_config()
    if config:
        from .stable_time import service_time_decision
        return service_time_decision(config)
    return TimeDecision('uncertain', reason='stable_time_configuration_required')
