"""Durable scoped emergency controls; runtime effects enter one shared gate."""
from contextlib import contextmanager
import fcntl
import functools
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import uuid4

from .records import WakeError



def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:raise ValueError('duplicate state or inventory key')
        value[key] = item
    return value


def select_roots(root, *, all_roots=False, registry_dir=None):
    if not all_roots:
        return [Path(root).expanduser().resolve()]
    from .supervisor import default_registry_dir
    directory = Path(registry_dir or default_registry_dir()).expanduser()
    selected = set()
    if not directory.exists():
        return []
    for path in sorted(directory.glob('*.json')):
        try:
            entry = json.loads(path.read_text(),object_pairs_hook=_unique_object)
            raw = entry['wake_root']
            if (entry.get('schema_version') != 1 or not isinstance(raw, str)
                    or not Path(raw).is_absolute()):
                raise ValueError
            selected.add(Path(raw).resolve())
        except (OSError, ValueError, KeyError, TypeError):
            raise WakeError(f'invalid registered wake root: {path.name}') from None
    return sorted(selected)


def _directory(root):
    path = Path(root) / 'emergency-control'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise WakeError('emergency control directory must be private and owned')
    return path


@contextmanager
def _lock(root, name, operation):
    path = _directory(root) / name
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise WakeError('unsafe emergency control lock')
        fcntl.flock(stream, operation)
        yield stream


def _write(root, state):
    directory = _directory(root)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.state-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'state.json')
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_control(root):
    path = Path(root) / 'emergency-control/state.json'
    try:
        info = path.lstat()
    except FileNotFoundError:
        return dict(version=1, paused=False, interrupt_requested=False, revision=0, history=[])
    try:
        parent = path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or stat.S_IMODE(parent.st_mode) & 0o077
                or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 4*1024*1024):
            raise ValueError
        state = json.loads(path.read_text(),object_pairs_hook=_unique_object)
        if (type(state.get('version')) is not int or state.get('version') != 1 or type(state.get('paused')) is not bool
                or type(state.get('interrupt_requested')) is not bool
                or type(state.get('revision')) is not int or state['revision'] < 0
                or not isinstance(state.get('history'), list)):
            raise ValueError
        return state
    except (OSError, ValueError, TypeError, AttributeError):
        return dict(version=1, paused=True, interrupt_requested=False,
                    revision=None, history=[], error='control_state_unavailable')


def paused(root):
    return read_control(root)['paused']


@contextmanager
def delivery_guard(root):
    """Shared effect generation: pause never waits for an uncertain submission."""
    with _lock(root, 'effects.lock', fcntl.LOCK_SH):
        if paused(root):
            raise WakeError('emergency_paused: resume explicitly before new delivery')
        yield


def guard_command(function):
    @functools.wraps(function)
    def guarded(args, root):
        with delivery_guard(root):
            return function(args, root)
    return guarded


def in_flight(root):
    path = Path(root)/'emergency-control/effects.lock'
    if not path.exists() and not path.is_symlink():return False
    try:
        with _lock(root, 'effects.lock', fcntl.LOCK_EX | fcntl.LOCK_NB):
            return False
    except BlockingIOError:
        return True


def change_control(root, action, actor='operator'):
    with _lock(root, 'state.lock', fcntl.LOCK_EX):
        state = read_control(root)
        if state.get('error'):
            raise WakeError('control state corrupt; preserve and repair before resume')
        if action == 'interrupt' and not state['paused']:
            raise WakeError('pause this root before requesting owned-turn interruption')
        wanted = action != 'resume'
        interrupt = action == 'interrupt' or (state['interrupt_requested'] and wanted)
        if state['paused'] != wanted or state['interrupt_requested'] != interrupt:
            state.update(paused=wanted, interrupt_requested=interrupt,
                         revision=state['revision']+1)
            state['history'].append(dict(action=action, actor=actor, operation_id=str(uuid4())))
            _write(root, state)
    return dict(state, in_flight=in_flight(root), enforcement=worker_enforcement(root))


def add_scope_options(parser):
    parser.add_argument('--all-roots', action='store_true', help='snapshot all registered roots, including disabled roots')
    parser.add_argument('--registry-dir', type=Path, help='operator-selected root registry')
    parser.add_argument('--authorized-root', type=Path, action='append', help=__import__('argparse').SUPPRESS)
    parser.add_argument('--caller-wake-subject', help=__import__('argparse').SUPPRESS)


def add_control_parsers(subparsers):
    for name, description in [('pause','persistently block new wake deliveries'),
                              ('resume','explicitly release an emergency pause'),
                              ('pause-status','inspect persistent pause and in-flight delivery'),
                              ('interrupt','request interruption of proven Wake-owned turns; requires pause')]:
        parser = subparsers.add_parser(name, help=description)
        add_scope_options(parser)
        parser.add_argument('--json', dest='as_json', action='store_true')


def _owned_by(record, subject):
    if subject is None:
        return True
    from .records import classify_record
    if classify_record(record) != 'native_intent_v6':
        return False
    context = record.get('wake_policy', {}).get('permission_context', {})
    return (context.get('subject') == subject and context.get('target') == subject
            and record.get('target', {}).get('thread_id') == subject)


def _cancel(root, args):
    from .records import all_records, cancel_record
    if bool(args.wake_id) == bool(args.all):
        raise WakeError('select one wake ID or --all')
    # Root lock excludes delivery, including retained legacy dispatch paths.
    # Nonblocking acquisition reports busy instead of hiding an in-flight effect.
    with _lock(root, 'effects.lock', fcntl.LOCK_EX | fcntl.LOCK_NB):
        candidates = all_records(root) if args.all else [dict(id=args.wake_id)]
        results = [dict(state='held',reason='record_unreadable',path=path) for path in inventory_errors(root)]
        for item in candidates:
            record = item.record if hasattr(item, 'record') else item
            identifier = record['id']
            subject = getattr(args, 'caller_wake_subject', None)
            if args.all and not _owned_by(record, subject):
                continue
            if args.all and record.get('status') not in ('pending','firing'):
                results.append(dict(wake_id=identifier,state='skipped',reason='not_cancellable'))
                continue
            try:
                from .records import find_record
                current = find_record(root,identifier).record
                if not _owned_by(current, subject):
                    raise WakeError('wake outside verified caller scope')
                # An ambiguous external submission may already have been consumed.
                if current.get('app_server_delivery',{}).get('state') == 'uncertain':
                    raise WakeError('submission uncertain; reconcile original effect before cancellation')
                if current.get('native_delivery',{}).get('state') == 'uncertain':
                    from .native_delivery import cancel_native_pending
                    from .records import WakeLifecycleLock
                    with WakeLifecycleLock(root, identifier):
                        state = cancel_native_pending(root, find_record(root, identifier))
                    results.append(dict(wake_id=identifier, state=state))
                    continue
                cancel_record(root,identifier)
                results.append(dict(wake_id=identifier,state='cancelled'))
            except (OSError, ValueError) as exc:
                results.append(dict(wake_id=identifier,state='held',reason=str(exc)))
        return results


def _control_command(args, root):
    from .records import all_records
    roots = select_roots(root, all_roots=args.all_roots, registry_dir=args.registry_dir)
    if args.authorized_root is not None:
        allowed = {p.expanduser().resolve() for p in args.authorized_root}
        if not set(roots) <= allowed:
            raise WakeError('host-authorized root snapshot changed; no operation performed')
    subject = getattr(args, 'caller_wake_subject', None)
    if subject is not None:
        from uuid import UUID
        if str(UUID(subject)) != subject or args.command not in ('list', 'cancel') or args.all_roots:
            raise WakeError('invalid verified-self control scope')
    rows = []
    for selected in roots:
        row = dict(wake_root=str(selected))
        try:
            if args.command == 'list':
                from .native_intents import schedule_projection
                from .records import classify_record
                row['wakes'] = []
                for item in all_records(selected, include_archive=args.archived):
                    record = item.record
                    if not _owned_by(record, subject):
                        continue
                    dates = (schedule_projection(record) if classify_record(record) in ('native_intent_v6', 'runtime_intent_v7') else
                        dict(due_at=record.get('predicate', {}).get('due_at'),
                            expires_at=record.get('target', {}).get('expires_at')))
                    row['wakes'].append(dict(wake_id=record.get('id'), status=record.get('status'),
                        target=record.get('target'), next_attempt_at=record.get('next_attempt_at'), **dates))
                row['paused'] = paused(selected)
                row['inventory_errors'] = inventory_errors(selected,args.archived)
            elif args.command == 'pause-status':
                row.update(read_control(selected), in_flight=in_flight(selected), enforcement=worker_enforcement(selected))
            elif args.command == 'cancel':
                row['results'] = _cancel(selected,args)
            else:
                row.update(change_control(selected,args.command,os.environ.get('CODEX_THREAD_ID','operator')))
                if args.command == 'interrupt':
                    row['inventory_errors'] = inventory_errors(selected)
                    from .emergency_interrupt import interrupt_owned
                    row['results'] = interrupt_owned(selected)
            row['state'] = 'held' if row.get('enforcement') == 'upgrade_required_observed_worker' or row.get('inventory_errors') or any(x.get('state') in ('held','uncertain','unsupported','monitor_required')
                                       for x in row.get('results',[])) else 'ok'
        except (OSError,ValueError) as exc:
            row.update(state='held',error=type(exc).__name__,message=str(exc))
        rows.append(row)
    value = dict(scope='registered_snapshot' if args.all_roots else 'root',roots=rows)
    if args.as_json:
        print(json.dumps(value,sort_keys=True))
    else:
        for row in rows:
            print(json.dumps(row,sort_keys=True))
        if not rows:print('No registered wake roots.')
    return 5 if any(x['state']=='held' for x in rows) else 0


def guard_dispatch(function):
    @functools.wraps(function)
    def guarded(root, found, **kwargs):
        from .injector import DispatchResult
        from .records import find_record
        try:
            from .wake_policy import effect_guard, apply_owner_state
            from .records import WakeLifecycleLock, replace_record
            with delivery_guard(root), effect_guard(root, found.record):
                active = find_record(root,found.record['id'])
                if active.record != found.record or active.record.get('status') != 'firing':
                    return DispatchResult('skipped','wake changed before dispatch admission')
                if active.record.get('schema_version') == 8:
                    with WakeLifecycleLock(root, active.record['id']):
                        record = dict(active.record)
                        reason = apply_owner_state(root, record)
                        if record != active.record:
                            replace_record(root, active, record)
                            active = find_record(root, record['id'])
                        if reason:
                            return DispatchResult('skipped', reason)
                return function(root,active,**kwargs)
        except WakeError as exc:
            return DispatchResult('skipped',str(exc))
    return guarded



def inventory_errors(root, archived=False):
    from .records import ACTIVE_STATUS_DIRS
    errors = []
    for directory in (*ACTIVE_STATUS_DIRS, *(('archive',) if archived else ())):
        for path in sorted((Path(root)/directory).glob('*.json')):
            try:
                value = json.loads(path.read_text(),object_pairs_hook=_unique_object)
                if (not isinstance(value,dict) or not isinstance(value.get('id'),str)
                        or not value['id'] or value.get('status') is None):raise ValueError
            except (OSError,ValueError):
                errors.append(str(path.relative_to(root)))
    return errors


def control_command(args, root):
    try:
        return _control_command(args, root)
    except (OSError,ValueError) as exc:
        value = dict(error=dict(code='scope_unavailable',message=str(exc)),roots=[])
        print(json.dumps(value,sort_keys=True))
        return 2



def worker_enforcement(root):
    # Advisory readback, not proof that every possible reader was inventoried.
    from .monitor import read_monitor_health,health_is_recent
    try:
        health = read_monitor_health(Path(root))
        if not health or not health_is_recent(health):return 'unverified_no_recent_worker'
        if 'emergency_control_v1' not in health.get('reader_capabilities',[]):
            return 'upgrade_required_observed_worker'
        return 'capable_worker_observed_not_exclusive_census'
    except (OSError,ValueError,TypeError):return 'unverified_worker_health'



def transition_pending(root, found, status, **kwargs):
    """Commit a legacy evaluation only if cancellation did not replace its snapshot."""
    from .records import find_record,move_record
    with _lock(root,'effects.lock',fcntl.LOCK_SH):
        try: current = find_record(root,found.record['id'])
        except WakeError:return False
        if current.record != found.record or current.record.get('status') != 'pending':
            return False
        move_record(root,current,status,**kwargs)
        return True
