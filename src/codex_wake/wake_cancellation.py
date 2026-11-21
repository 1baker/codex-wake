"""Retain exact cancellation intent while delivery owns the effect gate.

Only the authorized CLI enqueues requests. A monitor reconciles them before
its next poll, never while holding a wake lifecycle lock or replaying delivery.
"""
import fcntl
import hashlib
import json
import os
import stat

from .records import WakeError, all_records, cancel_record, find_record
from .wake_control import _directory, _lock, _owned_by, _unique_object, _write


def _identity(record):
    fields = ('id', 'schema_version', 'created_at', 'cwd', 'prompt', 'target',
              'predicate', 'wake_policy')
    value = {key: record.get(key) for key in fields}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _name(identifier):
    return 'cancel-request-' + hashlib.sha256(identifier.encode()).hexdigest() + '.json'


def _read(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 65536):
        raise WakeError('unsafe cancellation request')
    value = json.loads(path.read_text(), object_pairs_hook=_unique_object)
    if (not isinstance(value, dict) or value.get('version') != 1
            or not isinstance(value.get('wake_id'), str)
            or path.name != _name(value['wake_id'])
            or value.get('state') not in ('pending', 'settled')
            or not isinstance(value.get('identity_sha256'), str)
            or value.get('subject') is not None and not isinstance(value['subject'], str)):
        raise WakeError('invalid cancellation request')
    return value


def has_pending(root):
    """A corrupt request also refuses admission rather than permitting delivery."""
    return any(_read(path)['state'] == 'pending'
               for path in _directory(root).glob('cancel-request-*.json'))


def cancellation_pending(root, identifier):
    """Stop only the addressed wake; unrelated delivery and readback remain usable."""
    path = _directory(root) / _name(identifier)
    return (path.exists() or path.is_symlink()) and _read(path)['state'] == 'pending'


def cancellation_status(root, identifier):
    """Public, code-free intent readback; it never performs reconciliation."""
    path = _directory(root) / _name(identifier)
    if not path.exists() and not path.is_symlink():
        return None
    value = _read(path)
    return value.get('result', dict(wake_id=identifier, state='pending', reason='delivery_in_flight'))


def _store(root, value):
    _write(root, value, name=_name(value['wake_id']))


def _apply(root, value):
    identifier = value['wake_id']
    current = find_record(root, identifier).record
    if not _owned_by(current, value['subject']) or _identity(current) != value['identity_sha256']:
        return dict(wake_id=identifier, state='held', reason='cancellation_identity_changed'), True
    if current.get('status') == 'cancelled':
        return dict(wake_id=identifier, state='cancelled'), True
    if current.get('native_delivery', {}).get('state') == 'uncertain':
        from .native_delivery import cancel_native_pending
        from .records import WakeLifecycleLock
        with WakeLifecycleLock(root, identifier):
            state = cancel_native_pending(root, find_record(root, identifier))
        return dict(wake_id=identifier, state=state), True
    if current.get('app_server_delivery', {}).get('state') == 'uncertain':
        return dict(wake_id=identifier, state='held',
                    reason='submission uncertain; reconcile original effect before cancellation'), False
    if current.get('status') not in ('pending', 'firing'):
        return dict(wake_id=identifier, state='skipped', reason='delivery_already_terminal'), True
    cancel_record(root, identifier)
    return dict(wake_id=identifier, state='cancelled'), True


def reconcile_cancellations(root):
    """Try the exclusive gate once; pending requests survive busy/restart/unknown."""
    if not has_pending(root):
        return False
    try:
        with _lock(root, 'effects.lock', fcntl.LOCK_EX | fcntl.LOCK_NB):
            with _lock(root, 'cancel-requests.lock', fcntl.LOCK_EX):
                for path in sorted(_directory(root).glob('cancel-request-*.json')):
                    value = _read(path)
                    if value['state'] != 'pending':
                        continue
                    try:
                        result, settled = _apply(root, value)
                    except (OSError, ValueError) as exc:
                        result, settled = dict(wake_id=value['wake_id'], state='held', reason=str(exc)), False
                    updated = dict(value, result=result, state='settled' if settled else 'pending')
                    if updated != value:
                        _store(root, updated)
        return True
    except BlockingIOError:
        return False


def request_cancellation(root, args):
    """Accept only a frozen, authorized set; queueing is not cancellation proof."""
    if bool(args.wake_id) == bool(args.all):
        raise WakeError('select one wake ID or --all')
    subject = getattr(args, 'caller_wake_subject', None)
    candidates = [item.record for item in all_records(root)] if args.all else [find_record(root, args.wake_id).record]
    results, queued = [], []
    with _lock(root, 'cancel-requests.lock', fcntl.LOCK_EX):
        for current in candidates:
            identifier = current['id']
            if not _owned_by(current, subject):
                if not args.all:
                    raise WakeError('wake outside verified caller scope')
                continue
            if current.get('status') == 'cancelled' and not args.all:
                results.append(dict(wake_id=identifier, state='cancelled'))
                continue
            if current.get('status') not in ('pending', 'firing'):
                results.append(dict(wake_id=identifier, state='skipped' if args.all else 'held', reason='not_cancellable'))
                continue
            path = _directory(root) / _name(identifier)
            if path.exists() or path.is_symlink():
                value = _read(path)
                if value['identity_sha256'] != _identity(current) or value['subject'] != subject:
                    raise WakeError('cancellation request scope changed')
            else:
                _store(root, dict(version=1, wake_id=identifier, subject=subject,
                                  identity_sha256=_identity(current), state='pending'))
            queued.append(identifier)
    reconcile_cancellations(root)
    for identifier in queued:
        value = _read(_directory(root) / _name(identifier))
        results.append(value.get('result', dict(wake_id=identifier, state='pending', reason='delivery_in_flight')))
    return results
