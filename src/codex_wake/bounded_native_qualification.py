"""Host approval and actual Unix-peer qualification before bounded input RPCs.

The report is host-selected evidence, never authority supplied by an RPC caller.
Every operation rechecks it; an observed capability alone enables no delivery.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import struct
import time

from .native_protocol import native_request
from .process import process_identity
from .records import WakeError
from .runtime_delivery import RuntimeCapability


_CHECKS = ('expiry', 'unknown', 'cancellation', 'restart', 'history_isolation',
           'final_send', 'rollback', 'ownership', 'reconnect')
_CAPABILITIES = 'thread/queue/bounded/capabilities'
_REFUSAL = 'bounded native backend not qualified'


class BoundedNativePreIORefusal(WakeError):
    """The bounded operation was refused before its RPC was sent."""


def _private_bytes(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise WakeError(_REFUSAL)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) not in (0o400, 0o600)
                or info.st_size > 1024 * 1024):
            raise WakeError(_REFUSAL)
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise WakeError(_REFUSAL)
    return data


def _approval():
    policy_path = os.environ.get('CODEX_WAKE_BOUNDED_NATIVE_POLICY')
    if not policy_path:
        raise WakeError(_REFUSAL)
    policy_bytes = _private_bytes(policy_path)
    policy = json.loads(policy_bytes)
    if type(policy.get('schema_version')) is not int or policy['schema_version'] != 1:
        raise WakeError(_REFUSAL)
    report_bytes = _private_bytes(policy['qualification_report'])
    if hashlib.sha256(report_bytes).hexdigest() != policy.get('qualification_sha256'):
        raise WakeError(_REFUSAL)
    report = json.loads(report_bytes)
    admission = report['bounded_native_admission']
    executable = report['package']['files']['bin/codex']
    if (not re.fullmatch('[0-9a-f]{40}', report['native_source_commit'])
            or not re.fullmatch('[0-9a-f]{64}', executable)
            or type(admission.get('contract_version')) is not int
            or admission['contract_version'] != 1 or admission.get('state') != 'qualified'
            or any(admission['checks'].get(name) is not True for name in _CHECKS)):
        raise WakeError(_REFUSAL)
    return policy_path, policy_bytes, report_bytes, executable


def _peer_process(credentials):
    pid, uid, _ = credentials
    if pid <= 0 or uid != os.geteuid():
        raise WakeError(_REFUSAL)
    identity = process_identity(pid)
    if identity is None:
        raise WakeError(_REFUSAL)
    with Path(f'/proc/{pid}/exe').open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if process_identity(pid) != identity:
        raise WakeError(_REFUSAL)
    return credentials, identity, digest


def _validate_capabilities(result):
    if (not isinstance(result, dict) or type(result.get('version')) is not int
            or result['version'] != 1 or result.get('clockSource') != 'stable_time'
            or any(result.get(name) is not True for name in ('clockConfigured',
                'expiryAtAdmission', 'pendingIsolatedFromLegacy'))):
        raise WakeError(_REFUSAL)


class QualifiedBoundedNativeRequest:
    def __init__(self, *, request=native_request):
        self._request = request

    def __call__(self, endpoint, codex, method, params, timeout):
        verified = False
        try:
            if (method not in (_CAPABILITIES, 'thread/queue/bounded/add',
                    'thread/queue/bounded/read', 'thread/queue/bounded/delete')
                    or not isinstance(params.get('threadId'), str) or not params['threadId']
                    or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
                raise WakeError(_REFUSAL)
            approval = _approval()
            # This bounds transport only; Native owns admission expiry.
            stop = time.monotonic() + timeout
            peer = None
            credentials = None

            def verify(ws, initialization):
                nonlocal verified, peer, credentials
                credentials = struct.unpack('3i', ws.socket.getsockopt(socket.SOL_SOCKET,
                    socket.SO_PEERCRED, struct.calcsize('3i')))
                peer = _peer_process(credentials)
                if peer[2] != approval[3]:
                    raise WakeError(_REFUSAL)
                if method != _CAPABILITIES:
                    identifier = 'codex-wake-bounded-qualification'
                    ws.send(json.dumps(dict(id=identifier, method=_CAPABILITIES,
                        params=dict(threadId=params['threadId']))))
                    while True:
                        remaining = (stop - time.monotonic())
                        if remaining <= 0:
                            raise WakeError(_REFUSAL)
                        message = json.loads(ws.recv(timeout=remaining))
                        if message.get('id') == identifier:
                            if 'error' in message:
                                raise WakeError(_REFUSAL)
                            _validate_capabilities(message.get('result'))
                            break
                if _approval() != approval or _peer_process(credentials) != peer:
                    raise WakeError(_REFUSAL)
                if time.monotonic() >= stop:
                    raise WakeError(_REFUSAL)
                verified = method != _CAPABILITIES

            remaining = (stop - time.monotonic())
            if remaining <= 0:
                raise WakeError(_REFUSAL)
            result = self._request(endpoint, codex, method, params, remaining,
                verify_connection=verify)
            if method == _CAPABILITIES:
                _validate_capabilities(result)
                if peer is None or _approval() != approval or _peer_process(credentials) != peer:
                    raise WakeError(_REFUSAL)
            return result
        except Exception as exc:
            if not verified:
                raise BoundedNativePreIORefusal(_REFUSAL) from exc
            # After authorization, a lost reply cannot prove non-submission.
            raise

    def capability(self, recipient):
        try:
            target = recipient.binding
            self(target['endpoint'], target['codex_cmd'], _CAPABILITIES,
                dict(threadId=recipient.session_id), 10)
            return RuntimeCapability('supported', 'bounded_native_backend_qualified')
        except Exception:
            return RuntimeCapability('not_qualified', 'bounded_native_backend_not_qualified')
