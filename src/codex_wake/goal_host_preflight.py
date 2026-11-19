"""Read-only host compatibility before opted-in lifecycle dispatch.

Static observations are cached by source/client/server/config/identity. Accounting,
controller health and operator control are observed afresh, never cached authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import struct

from . import goal_supervision as supervision
from . import measurements
from .records import WakeError


MODES = {'hard_admission', 'sampled_stop', 'manual'}


def _time_metadata():
    """Inspection and existing protective controls survive missing UTC."""
    try:
        return dict(observed_at=measurements.utc_time(),time_status='qualified_utc')
    except measurements.TimeUnavailable:
        return dict(observed_at=None,time_status='not_observed')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _file(path, maximum=2 * 1024 * 1024 * 1024):
    path = Path(path).resolve(strict=True)
    with path.open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not path.is_file() or info.st_size > maximum:
            raise ValueError('identity file exceeds preflight bound')
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('identity file changed during preflight')
    return dict(path=str(path), sha256=digest, size=info.st_size)


def _options(profile, caller):
    options = profile['governance_preflight']
    if (type(options) is not dict or set(options) - {'policy', 'thread_id', 'requested_mode', 'manual_authorization'}
            or not {'policy', 'requested_mode'} <= set(options)
            or type(options['requested_mode']) is not str or options['requested_mode'] not in MODES):
        raise WakeError('invalid host governance preflight configuration')
    thread = options.get('thread_id') or caller
    supervision._name(thread)
    if caller is not None and thread != caller:
        raise WakeError('governance preflight cannot select another caller')
    if 'manual_authorization' in options and (type(options['manual_authorization']) is not str
            or not options['manual_authorization'].strip() or len(options['manual_authorization']) > 4096):
        raise WakeError('manual repair requires its existing authorization locator')
    return options, thread


def _static(root, profile, options, thread):
    from .shared_app_server import SharedAppServerReader
    from .process import process_identity
    from .native_protocol import native_request, NativeCapabilityUnavailable
    grant = supervision._grant(options['policy'], thread, root=root)
    if (grant['app_server'] != profile['app_server'] or grant['codex_path'] != profile['codex_path']
            or profile.get('codex_home', grant['codex_home']) != grant['codex_home']):
        raise ValueError('selected launch host differs from the supervision grant')
    timeout = min(profile['timeout'], grant['rpc_timeout'], 5)
    with SharedAppServerReader(profile['app_server'], timeout=timeout) as reader:
        peer_pid, peer_uid, _ = struct.unpack('3i', reader.connection.socket.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        if peer_uid != os.geteuid():
            raise ValueError('native peer owner differs')
        metadata = reader.server_metadata
        peer = dict(pid=peer_pid, process=process_identity(peer_pid), binary=_file('/proc/' + str(peer_pid) + '/exe'))
        source = {name: _file(Path(__file__).with_name(name), 1024 * 1024)['sha256'] for name in (
            'goal_host_preflight.py', 'goal_supervision.py', 'goal_governance.py', 'goal_notices.py',
            'goal_usage.py', 'native_protocol.py', 'shared_app_server.py', 'agent_lifecycle.py', 'dispatch_packet.py')}
        binding = dict(source=source, client=_file(profile['codex_path']), server=peer,
            metadata=metadata, profile=profile, policy=_file(options['policy'], 1024 * 1024),
            identity=dict(thread_id=thread, workspace=str(Path(profile['cwd']).resolve()), uid=os.geteuid()),
            endpoint=dict(path=str(reader.path), inode=reader.path.stat().st_ino))
        if peer['process'] is None:
            raise ValueError('native peer generation unavailable')
        key = _digest(binding)
        directory = supervision._directory(root) / 'host-preflight'
        directory.mkdir(mode=0o700, exist_ok=True)
        supervision._private(directory, True)
        path = directory / (key + '.json')
        with supervision._lock(directory, key):
            if path.exists():
                supervision._private(path)
                saved = json.loads(path.read_text())
                if saved.get('binding') == binding and saved.get('version') == 1:
                    return dict(saved, cache='reused', receipt_path=str(path))
            notice_read = 'unknown'
            try:
                response = native_request(profile['app_server'], profile['codex_path'], 'thread/notice/read',
                    dict(threadId=thread, eventId='preflight-' + key), timeout)
                notice_read = 'supported' if 'notice' in response else 'unqualified_response'
            except NativeCapabilityUnavailable:
                notice_read = 'unsupported'
            except (OSError, ValueError, WakeError):
                pass
            saved = dict(version=1, receipt_id=key, **_time_metadata(), binding=binding,
                capabilities=dict(hard_admission=False, notice_read=notice_read,
                    request_path='unqualified', client_server_same_binary=binding['client']['sha256'] == peer['binary']['sha256']),
                limitations=['Client executable and connected server executable are identified separately; neither proves model request-path admission.',
                    'No qualified native per-request admission hook or enforceable output ceiling is available.',
                    'A successful notice read does not prove operator rendering, model delivery or control authority.'])
            if notice_read == 'unknown':
                return dict(saved, cache='not_qualified', receipt_path=None)
            supervision._save(path, saved)
            return dict(saved, cache='created', receipt_path=str(path))


def inspect_host(root, profile, caller):
    """Return an explicit mode decision using retained host authority, no effects."""
    options, thread = _options(profile, caller)
    # A retained repair locator cannot substitute for the selected host grant.
    grant = supervision._grant(options['policy'], thread, root=root)
    if (grant['app_server'] != profile['app_server'] or grant['codex_path'] != profile['codex_path']
            or profile.get('codex_home', grant['codex_home']) != grant['codex_home']):
        raise WakeError('selected launch host differs from the supervision grant')
    from .goal_governance import snapshot
    control = snapshot(root, thread)
    result = dict(version=1, thread_id=thread, requested_mode=options['requested_mode'],
        **_time_metadata(), mode='degraded', admitted=False, governance=control,
        static=None, dynamic=None, effect_attempted=False, resources_renewed=False,
        native_admission='unsupported', maximum_token_overshoot=None)
    try:
        result['static'] = _static(root, profile, options, thread)
    except (OSError, ValueError, TypeError, KeyError, WakeError) as error:
        result['static'] = dict(cache='unavailable', reason=type(error).__name__, message=str(error)[:256])
    if control.get('state')=='available' and control.get('enabled') is False and control.get('scope')==grant['allocation_id']:
        result.update(mode='inactive',admitted=True,reason='operator_disabled',message='Governor remains disabled; no request-path gate is imposed and no resource authority is renewed.')
        return result
    if options['requested_mode'] == 'hard_admission':
        if result['static'].get('capabilities', {}).get('notice_read') != 'supported':
            result.update(reason='hard_admission_unsupported', qualification_failure='host_notice_unqualified', message='Hard admission withheld: selected native host/notice qualification is unavailable. Existing authorized manual repair remains available; no downgrade or renewal occurred.')
            return result
        try:
            from .request_admission import qualify_gateway
            qualified=qualify_gateway(root,profile,thread)
            result.update(qualified)
            result['native_admission']='selected_http_gateway_only'
            return result
        except (OSError,ValueError,KeyError,TypeError,WakeError) as error:
            latest=snapshot(root,thread)
            if latest.get('enabled') is False and latest.get('scope')==grant['allocation_id']:
                result.update(mode='inactive',admitted=True,governance=latest,reason='operator_disabled')
                return result
            result['request_path_error']=type(error).__name__
        result.update(reason='hard_admission_unsupported', message='Hard admission is unsupported on this selected request path. No work was dispatched and no downgrade was applied. Use an already authorized manual route or explicitly select sampled stopping; no exact token ceiling is claimed.')
        return result
    try:
        diagnosis = supervision.diagnose(root, options['policy'], thread)
        status = supervision.show(root, options['policy'], thread)
        governor = status.get('governor', {})
        from .goal_notices import NativeNoticeAdapter, read_notice
        notices = {}
        for name in ('activation', 'engagement', 'deactivation'):
            if name not in governor:
                continue
            notice = dict(governor[name])
            try:
                observed = NativeNoticeAdapter(root).reconcile(read_notice(root, notice['event_id']))
                notice['current_model_context'] = observed.get('model_context') is True
            except (OSError, ValueError, KeyError, TypeError, WakeError):
                notice['current_model_context'] = False
            notices[name] = notice
        result['dynamic'] = dict(**_time_metadata(), accounting=diagnosis['accounting'],
            controller=diagnosis['controller'], engagement=status.get('engagement'),
            state=status.get('state'), stop_latched=status.get('stop_latched', False),
            notice_surfaces=notices, controls=governor.get('controls', []))
    except (OSError, ValueError, KeyError, TypeError, WakeError) as error:
        result['dynamic'] = dict(**_time_metadata(), state='unavailable', reason=type(error).__name__, message=str(error)[:256])
    control = snapshot(root, thread)
    result['governance'] = control
    manual = options.get('manual_authorization')
    if (control.get('state') == 'available' and control.get('enabled') is False
            and control.get('scope') == grant['allocation_id']):
        result.update(mode='inactive', admitted=True, reason='operator_disabled',
            message='Governor remains inactive by explicit operator choice. Independent limits remain; no watcher was started, work resumed or resources renewed.')
    elif manual and options['requested_mode'] == 'manual':
        _manual(result, manual)
    else:
        dynamic = result['dynamic']
        surfaces = dynamic.get('notice_surfaces', {})
        model_delivery = any(item.get('current_model_context') is True for item in surfaces.values())
        dynamic['operator_rendering'] = 'unverified_by_read_only_preflight'
        remaining = (dynamic.get('engagement') or {}).get('card') or {}
        if (options['requested_mode'] == 'sampled_stop' and dynamic.get('accounting', {}).get('state') == 'qualified'
                and dynamic.get('controller', {}).get('fresh') is True
                and dynamic.get('engagement', {}).get('engaged') is True
                and remaining.get('remaining_tokens', 0) > 0 and remaining.get('remaining_seconds', 0) > 0
                and dynamic.get('controls') and model_delivery and result['static'].get('capabilities', {}).get('notice_read') == 'supported'):
            result.update(mode='sampled_stop', admitted=True, reason='fresh_sampled_supervision',
                message='Sampled stopping is qualified now; it is not request admission and has no exact token overshoot bound. Notice read/model delivery are observed; operator rendering requires its independent qualification receipt.')
        elif manual:
            _manual(result, manual)
        else:
            result.update(reason='required_supervision_unqualified',
                message='Requested supervision is degraded or unqualified. Retained accounting/control history is unchanged. Previously authorized manual repair remains a supported separate host route; this preflight neither asks again nor manufactures that authority.')
    return result


def _manual(result, authorization):
    result.update(mode='manual', admitted=True, reason='existing_manual_authorization',
        authorization=authorization, message='Previously authorized manual work may proceed without the watcher. No automatic containment is promised; original scope, independent limits and stop conditions remain. No repeated approval, watcher change or budget renewal occurred.')
