"""Bounded native lifecycle and explicit delivery-recovery protocol access."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import time

from . import __version__
from .records import WakeError


class NativeCapabilityUnavailable(WakeError):
    """The server explicitly rejected an unknown protocol method."""


class NativeHealthDeadline(WakeError):
    """An exact native foreground challenge expired in the daemon."""


def native_request(endpoint, codex, method, params, timeout, *, verify_connection=None, observe_result=None):
    from .shared_app_server import locate_shared_endpoint
    from websockets.sync.client import unix_connect
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
        raise WakeError('invalid native request timeout')
    # This bounds local transport resource use only. Native expiry and permission
    # decisions retain their own authoritative envelopes at their owners.
    stop = time.monotonic() + timeout
    def remaining_budget():
        return stop - time.monotonic()
    if endpoint == 'unix://':
        endpoint = locate_shared_endpoint(codex_cmd=codex, timeout=timeout)
    if not endpoint.startswith('unix://') or not Path(endpoint[7:]).is_absolute():
        raise WakeError('session lifecycle requires an existing local Unix endpoint')
    if Path(endpoint[7:]).is_symlink():
        from .strict_runtime import resolve_executor_endpoint
        endpoint=resolve_executor_endpoint(endpoint)
    try:
        info = Path(endpoint[7:]).lstat()
    except OSError:
        raise WakeError('native lifecycle endpoint is unavailable') from None
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise WakeError('native lifecycle endpoint must be an owned Unix socket')
    remaining = remaining_budget()
    if remaining <= 0:
        raise WakeError('native lifecycle endpoint observation timed out')
    # Long-lived threads can exceed the WebSocket library's 1 MiB default.
    # Retain a finite response cap and the existing absolute request deadline.
    with unix_connect(endpoint[7:], open_timeout=remaining, close_timeout=1,
                      compression=None, max_size=32 * 1024 * 1024) as ws:
        def request(identifier, name, body):
            ws.send(json.dumps({'id': identifier, 'method': name, 'params': body}))
            while True:
                remaining = remaining_budget()
                if remaining <= 0:
                    raise WakeError('native lifecycle request timed out; inspect state before retry')
                result = json.loads(ws.recv(timeout=remaining))
                if result.get('id') != identifier:
                    continue
                if 'error' in result:
                    if isinstance(result['error'],dict) and result['error'].get('code')==-32601:
                        raise NativeCapabilityUnavailable('native lifecycle method unavailable: '+name)
                    if name == 'tui/health/probe' and isinstance(result['error'], dict) and result['error'].get('code') == -32001 and result['error'].get('message') == 'foreground loop deadline expired':
                        raise NativeHealthDeadline('native foreground loop deadline expired')
                    raise WakeError('native lifecycle request rejected: ' + name)
                return result['result']
        initialization = request(1, 'initialize', {'clientInfo': {'name': 'codex_wake_lifecycle', 'version': __version__},
                                  'capabilities': {'experimentalApi': True}})
        ws.send(json.dumps({'method': 'initialized'}))
        if verify_connection is not None:
            verify_connection(ws, initialization)
        result=request(2, method, params)
        if observe_result is not None:observe_result(ws,result)
        return result


def _protective_target(connection,row):
    """Validate original kernel/image pins; no discovery or clock-derived authority."""
    import socket
    import struct
    from .process import process_identity
    from .controller_health import _image_hash
    if not isinstance(row.get('thread_id'),str) or not row['thread_id']:
        raise WakeError('protective_thread_unpinned')
    target=row['target'];path=Path(row['endpoint'][7:])
    if not row['endpoint'].startswith('unix:///') or path!=path.resolve():
        raise WakeError('protective_endpoint_unpinned')
    info=path.lstat();home=Path(target['home']);h=home.lstat()
    pid,uid,_=struct.unpack('3i',connection.socket.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    birth=process_identity(pid);expected=target['process']
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.geteuid() or uid!=os.geteuid()
            or target['uid']!=uid or pid!=expected['pid'] or not birth
            or str(birth['start_time_ticks'])!=str(expected['start_ticks']) or birth['boot_id']!=expected['boot_id']
            or f'{info.st_dev}:{info.st_ino}'!=target['socket_generation']
            or home!=home.resolve() or h.st_uid!=uid or not stat.S_ISDIR(h.st_mode)
            or f'{h.st_dev}:{h.st_ino}'!=target['home_generation']
            or str(Path('/proc',str(pid),'exe').resolve(strict=True))!=target['executable']
            or _image_hash(pid)!=target['build_sha256'] or target['conversation_id']!=row['thread_id']):
        raise WakeError('protective_target_changed')


def _protective_scope(connection,row,record,fingerprint,turn_id):
    from . import measurements
    import hashlib
    if not isinstance(turn_id,str) or not turn_id:
        raise WakeError('protective_turn_unacknowledged')
    _protective_target(connection,row)
    clock=measurements.snapshot()
    digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return dict(version=1,operation_id=record['operation_id'],admission_fingerprint=fingerprint,
        payload_sha256=record['payload_sha256'],target_sha256=digest(record['target']),
        endpoint=row['endpoint'],thread_id=row['thread_id'],turn_id=turn_id,
        native_client_id=record['operation_id'],clock_observation=clock)


def _protective_interrupt(row,scope):
    """One exact interrupt under a single kernel I/O fuse; never time authority."""
    import socket
    import select
    import threading
    from types import SimpleNamespace
    from .host_counter import _TransportFuse
    from websockets.sync.client import unix_connect
    if (type(scope.get('version')) is not int or scope['version']!=1 or not isinstance(scope.get('turn_id'),str) or not scope['turn_id']
            or scope.get('thread_id')!=row['thread_id'] or scope.get('endpoint')!=row['endpoint']):
        raise WakeError('protective_scope_invalid')
    from .measurements import elapsed_bounds
    elapsed_bounds(scope['clock_observation'],scope['clock_observation'])
    with _TransportFuse(3) as fuse:
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        stopped_r,stopped_w=os.pipe();expired=threading.Event()
        def abort():
            ready=select.select([fuse.fd,stopped_r],[],[])[0]
            if fuse.fd in ready:
                expired.set()
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
        watcher=threading.Thread(target=abort,daemon=True);watcher.start()
        try:
            # The retained fuse covers connect, handshake and every full frame.
            import errno
            sock.setblocking(False)
            status=sock.connect_ex(row['endpoint'][7:])
            if status not in (0,errno.EINPROGRESS):raise OSError(status,'protective connect refused')
            if status:
                fuse.wait(writers=[sock])
                failure=sock.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
                if failure:raise OSError(failure,'protective connect failed')
            sock.setblocking(True)
            _protective_target(SimpleNamespace(socket=sock),row)
            with unix_connect(sock=sock,open_timeout=None,close_timeout=0,compression=None,max_size=4*1024*1024) as ws:
                def exchange(identifier,method,params):
                    if expired.is_set():raise TimeoutError('protective_transport_fuse')
                    ws.send(json.dumps(dict(id=identifier,method=method,params=params)))
                    for _ in range(256):
                        reply=json.loads(ws.recv(timeout=None))
                        if expired.is_set():raise TimeoutError('protective_transport_fuse')
                        if reply.get('id')!=identifier:continue
                        if 'error' in reply:raise WakeError('protective_interrupt_rejected')
                        return reply['result']
                    raise WakeError('protective_response_capacity')
                metadata=exchange(1,'initialize',dict(clientInfo=dict(name='codex_wake_protective',version=__version__),capabilities=dict(experimentalApi=True)))
                if metadata.get('codexHome')!=row['target']['home']:raise WakeError('protective_target_changed')
                _protective_target(ws,row)
                ws.send(json.dumps(dict(method='initialized')))
                exchange(2,'turn/interrupt',dict(threadId=scope['thread_id'],turnId=scope['turn_id']))
                return 'requested'
        finally:
            os.write(stopped_w,b'1');watcher.join();sock.close();os.close(stopped_r);os.close(stopped_w)
