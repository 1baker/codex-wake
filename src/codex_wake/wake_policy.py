"""Frozen wake lifetime/startup policy; delivery and clock evidence stay in core."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile

from .records import WakeError, WakeLifecycleLock

SCHEMA_VERSION = 8
LIFETIMES = ('conversation', 'task', 'persistent')
OWNER_END = ('retire', 'hold', 'retain')
STARTUP = ('active_tab', 'background_saved', 'create_load_run')
DEFAULTS = dict(lifetime='persistent', owner_end='retire', startup='create_load_run')


def _read(path):
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > 4 * 1024 * 1024):
            raise WakeError('wake_policy_private_state_required')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise WakeError('wake_policy_duplicate_key')
                result[key] = value
            return result
        return json.loads(path.read_text(), object_pairs_hook=unique)
    except FileNotFoundError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise WakeError('wake_policy_state_unavailable') from exc


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.wake-policy-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def configuration(root):
    path = Path(root) / 'wake-policy.json'
    try:
        value = _read(path)
    except FileNotFoundError:
        value = dict(version=1, **DEFAULTS)
    if (type(value) is not dict or set(value) != {'version', *DEFAULTS}
            or type(value['version']) is not int or value['version'] != 1
            or value['lifetime'] not in LIFETIMES or value['owner_end'] not in OWNER_END
            or value['startup'] not in STARTUP):
        raise WakeError('invalid_wake_policy_configuration')
    return value


def configure(root, **options):
    with WakeLifecycleLock(root, 'wake-policy'):
        value = configuration(root)
        value.update({key: val for key, val in options.items() if val is not None})
        if (set(value) != {'version', *DEFAULTS} or value['lifetime'] not in LIFETIMES
                or value['owner_end'] not in OWNER_END or value['startup'] not in STARTUP):
            raise WakeError('invalid_wake_policy_configuration')
        _write(Path(root) / 'wake-policy.json', value)
        return value


def valid(policy):
    if (type(policy) is not dict or set(policy) != ({'version', 'lifetime', 'owner', 'owner_end', 'startup', 'configuration_revision'} | ({'routes','permission_context'} if policy.get('version')==2 else set()) | ({'session_mode'} if 'session_mode' in policy else set()))
            or type(policy['version']) is not int or policy['version'] not in (1,2)
            or policy['lifetime'] not in LIFETIMES or policy['owner_end'] not in OWNER_END
            or policy['startup'] not in STARTUP or not isinstance(policy['configuration_revision'], str)
            or re.fullmatch(r'[0-9a-f]{64}', policy['configuration_revision']) is None):
        return False
    if 'session_mode' in policy and policy['session_mode'] not in ('session_only', 'reopen_live', 'background'):
        return False
    if policy['version']==2:
        from .permission_wake import valid_routes,valid_context
        if not valid_routes(policy['routes']) or not valid_context(policy['permission_context']):return False
    owner = policy['owner']
    return ((policy['lifetime'] == 'persistent' and owner is None)
            or (policy['lifetime'] != 'persistent' and type(owner) is dict
                and set(owner) == {'kind', 'id'} and owner['kind'] == policy['lifetime']
                and isinstance(owner['id'], str) and 0 < len(owner['id']) <= 256
                and all(ord(c) >= 32 for c in owner['id'])))


def request_policy(root, args, conversation):
    """Retry without explicit overrides retains the original admitted policy."""
    if not getattr(args, 'wake_policy_enabled', False):
        return None
    explicit = {key: getattr(args, argument, None) for key, argument in
                [('lifetime', 'wake_lifetime'), ('owner_end', 'owner_end'), ('startup', 'recipient_startup')]}
    explicit_owner = getattr(args, 'owner_id', None)
    key = getattr(args, 'idempotency_key', None)
    if key:
        from .records import all_records
        for item in all_records(root, include_archive=True):
            old = item.record
            if old.get('scheduling_intent', {}).get('idempotency_key') != key:
                continue
            policy = old.get('wake_policy')
            if old.get('schema_version') != 8:
                if any(v is not None for v in explicit.values()) or explicit_owner:
                    raise WakeError('idempotency_conflict: legacy wake has no explicit policy')
                return None
            if not valid(policy):
                raise WakeError('original_wake_policy_invalid')
            if any(v is not None and policy[k] != v for k, v in explicit.items()):
                raise WakeError('idempotency_conflict: wake policy differs')
            if explicit_owner is not None and (policy['owner'] or {}).get('id') != explicit_owner:
                raise WakeError('idempotency_conflict: wake owner differs')
            from .permission_wake import validate_retry
            validate_retry(root,args,policy,conversation)
            return dict(policy)
    config = configuration(root)
    selected = {k: explicit[k] if explicit[k] is not None else config[k] for k in DEFAULTS}
    owner = None
    if selected['lifetime'] != 'persistent':
        identifier = explicit_owner or (conversation if selected['lifetime'] == 'conversation' else None)
        if not identifier:
            raise WakeError('wake_owner_id_required')
        owner = dict(kind=selected['lifetime'], id=identifier)
    elif explicit_owner:
        raise WakeError('persistent_wake_cannot_have_owner')
    value = dict(version=1, owner=owner, configuration_revision=hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()).hexdigest(), **selected)
    from .permission_wake import decorate_policy
    value=decorate_policy(root,args,conversation,value)
    mode = getattr(args, "session_mode", None)
    if mode is not None:
        value["session_mode"] = mode
    if not valid(value):
        raise WakeError('invalid_wake_policy')
    return value


def decorate(record, policy, base_version):
    if policy is not None:
        record.update(schema_version=8, intent_schema_version=base_version, wake_policy=policy)
    return record


def core_record(record, expected_version):
    if record.get('schema_version') != 8:
        # Policy-shaped data must not be silently ignored by a legacy reader.
        if 'wake_policy' in record or 'intent_schema_version' in record:
            raise WakeError('wake_policy_schema_required')
        return record
    if (type(record.get('schema_version')) is not int or type(record.get('intent_schema_version')) is not int
            or record['intent_schema_version'] != expected_version or not valid(record.get('wake_policy'))):
        raise WakeError('invalid_policy_wake')
    if record['wake_policy']['version']==2:
        from .permission_wake import valid_progress
        if not valid_progress(record):raise WakeError('invalid_wake_route_progress')
    intent = record['scheduling_intent']
    if expected_version == 6:
        canonical = dict(root=intent['canonical_root'], cwd=record['cwd'], target=record['target'],
                         schedule=intent['schedule'], ttl_seconds=intent['ttl_seconds'], prompt=record['prompt'],
                         tolerance_seconds=intent['tolerance_seconds'], stop_at=intent['stop_at'],
                         wake_policy=record['wake_policy'])
    else:
        canonical = dict(target=record['target'], prompt=record['prompt'],
                         canonical_root=intent['canonical_root'], schedule=intent['schedule'],
                         ttl_seconds=intent['ttl_seconds'], tolerance_seconds=intent['tolerance_seconds'],
                         stop_at=intent['stop_at'], idempotency_key=intent['idempotency_key'],
                         wake_policy=record['wake_policy'])
    if hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest() != intent['fingerprint']:
        raise WakeError('wake_policy_intent_integrity_changed')
    return {**{k: v for k, v in record.items() if k not in ('wake_policy', 'intent_schema_version')}, 'schema_version': expected_version}


def _owner_key(owner):
    return hashlib.sha256(json.dumps(owner, sort_keys=True).encode()).hexdigest()


def _owners(root, *, initialize=False):
    path = Path(root) / 'wake-owners.json'
    try:
        state = _read(path)
    except FileNotFoundError:
        if not initialize:
            raise WakeError('wake_owner_state_unavailable') from None
        from .records import all_records
        if any(item.record.get('schema_version') == 8
               and item.record.get('wake_policy', {}).get('owner') is not None
               for item in all_records(root, include_archive=True)):
            raise WakeError('wake_owner_state_missing_recovery_required') from None
        state = dict(version=1, owners={})
        _write(path, state)
    if type(state) is not dict or set(state) != {'version', 'owners'} or state['version'] != 1 or type(state['owners']) is not dict:
        raise WakeError('invalid_wake_owner_state')
    return state


def register_owner(root, policy):
    if policy and policy['owner'] is not None:
        _owners(root, initialize=True)


def apply_owner_state(root, record):
    """Called with the wake lock; does not invent terminal owner evidence."""
    policy = record.get('wake_policy')
    if record.get('schema_version') != 8 or not valid(policy) or policy['owner'] is None:
        return None
    terminal = _owners(root)['owners'].get(_owner_key(policy['owner']))
    if terminal is None or policy['owner_end'] == 'retain':
        return None
    if (type(terminal) is not dict or terminal.get('owner') != policy['owner']
            or terminal.get('state') != 'completed' or not terminal.get('event_id') or not terminal.get('actor')):
        raise WakeError('invalid_wake_owner_completion')
    record['owner_completion'] = terminal
    uncertain = any(record.get(k, {}).get('state') == 'uncertain' for k in ('native_delivery', 'runtime_delivery'))
    if uncertain:
        return None  # Reconcile the original effect; never resubmit it.
    if record['status'] not in ('pending', 'firing'):
        return None
    if policy['owner_end'] == 'retire':
        record['status'] = 'cancelled'
        reason = 'owner_completed_retired'
    else:
        record['status'] = 'pending'
        reason = 'owner_completed_review_required'
    record['policy_outcome'] = dict(state='retired' if policy['owner_end'] == 'retire' else 'held', reason=reason)
    return reason


def complete_owner(root, owner, event_id, *, actor):
    if (type(owner) is not dict or set(owner) != {'kind', 'id'} or owner['kind'] not in ('conversation', 'task')
            or not isinstance(owner['id'], str) or not 0 < len(owner['id']) <= 256
            or not isinstance(event_id, str) or not 0 < len(event_id) <= 200 or not actor):
        raise WakeError('invalid_owner_completion')
    from .records import all_records, classify_record, find_record, replace_record
    with WakeLifecycleLock(root, 'wake-policy'):
        state = _owners(root, initialize=True)
        key = _owner_key(owner)
        terminal = dict(owner=owner, event_id=event_id, state='completed', actor=actor)
        previous = state['owners'].get(key)
        if previous is not None and previous != terminal:
            raise WakeError('owner_completion_conflict')
        if previous is None and len(state['owners']) >= 4096:
            raise WakeError('wake_owner_event_limit_reached')
        state['owners'][key] = terminal
        _write(Path(root) / 'wake-owners.json', state)
        outcomes = []
        for item in all_records(root):
            if item.record.get('schema_version') != 8 or item.record.get('wake_policy', {}).get('owner') != owner:
                continue
            with WakeLifecycleLock(root, item.record['id']):
                current = find_record(root, item.record['id'])
                if classify_record(current.record) == 'hold':
                    continue
                record = dict(current.record)
                reason = apply_owner_state(root, record)
                replace_record(root, current, record)
                outcomes.append(dict(id=record['id'], status=record['status'], reason=reason))
        return dict(state='completed', owner=owner, event_id=event_id, deduplicated=previous is not None, wakes=outcomes)


def reconcile_owner_completion(root, owner, event_id):
    """Consume an existing operator event; actor identity is not terminal proof.

    Automatic task acceptance and runtime terminal-event adapters are separate
    capabilities. Until qualified, MCP can reconcile the exact explicit operator
    completion but cannot manufacture one from an active caller's claim.
    """
    try:
        terminal = _owners(root)['owners'].get(_owner_key(owner))
    except WakeError:
        raise WakeError('owner_completion_evidence_required') from None
    if (type(terminal) is not dict or set(terminal) != {'owner', 'event_id', 'state', 'actor'}
            or terminal['owner'] != owner or terminal['event_id'] != event_id
            or terminal['state'] != 'completed' or not isinstance(terminal['actor'], str)
            or not terminal['actor'].startswith('operator:')):
        raise WakeError('owner_completion_evidence_required')
    return complete_owner(root, owner, event_id, actor=terminal['actor'])


@contextmanager
def registration_guard(root, args):
    if getattr(args, 'wake_policy_enabled', False):
        with WakeLifecycleLock(root, 'wake-policy'):
            yield
    else:
        yield


def startup_reason(record, observation):
    policy = record.get('wake_policy')
    if record.get('schema_version') != 8:
        return None
    if not valid(policy):
        return 'invalid_wake_policy'
    if policy['startup'] == 'active_tab':
        capability = observation.capabilities.get('active_tab')
        if capability is None or capability.state != 'supported':
            return 'active_tab_not_verified'
    if policy['startup'] == 'create_load_run':
        from .runtime_policies import native_delivery_ready
        target = record.get('target', {})
        ready = (native_delivery_ready(target, observation) if target.get('transport') == 'native'
                 else observation.state == 'ready')
        if not ready:
            return 'recipient_startup_unavailable_or_unsupported'
    return None


def add_options(parser):
    parser.set_defaults(wake_policy_enabled=True)
    parser.add_argument('--wake-lifetime', choices=LIFETIMES)
    parser.add_argument('--owner-id')
    parser.add_argument('--owner-end', choices=OWNER_END)
    parser.add_argument('--recipient-startup', choices=STARTUP)
    parser.add_argument('--wake-route',dest='wake_routes',action='append',choices=('background','existing_tab','new_tab','fresh_task'))
    parser.add_argument('--bus-root',type=Path)
    parser.add_argument('--operator-capability',type=Path)
    parser.add_argument('--actor-capability',type=Path)
    parser.add_argument('--actor-runtime',choices=('codex','grok'),default='codex')
    parser.add_argument('--app-server',default='unix://')


def register_parser(subparsers):
    group = subparsers.add_parser('wake-policy', help='configure wake lifetime and recipient startup')
    commands = group.add_subparsers(dest='policy_command', required=True)
    commands.add_parser('show')
    config = commands.add_parser('configure')
    config.add_argument('--lifetime', choices=LIFETIMES)
    config.add_argument('--owner-end', choices=OWNER_END)
    config.add_argument('--startup', choices=STARTUP)
    config.add_argument('--operator', action='store_true', required=True)
    complete = commands.add_parser('owner-complete')
    complete.add_argument('--owner-kind', choices=('conversation', 'task'), required=True)
    complete.add_argument('--owner-id', required=True)
    complete.add_argument('--event-id', required=True)
    complete.add_argument('--operator', action='store_true', required=True)


def command(args, root):
    # Direct local CLI is the operator surface. These flags are never forwarded
    # from model arguments by MCP, which derives authority separately.
    if args.policy_command == 'show':
        value = configuration(root)
    elif args.policy_command == 'configure' and args.operator:
        value = configure(root, lifetime=args.lifetime, owner_end=args.owner_end, startup=args.startup)
    elif args.policy_command == 'owner-complete' and args.operator:
        value = complete_owner(root, dict(kind=args.owner_kind, id=args.owner_id), args.event_id, actor='operator:'+str(os.geteuid()))
    else:
        raise WakeError('operator_authority_required')
    print(json.dumps(value, sort_keys=True))
    return 0


def guard_registration(function=None, *, native=False):
    from functools import wraps
    if function is None:
        return lambda selected: guard_registration(selected, native=native)
    @wraps(function)
    def guarded(args, root):
        from .runtime_policies import require_native_policy, require_wait_policy
        validator = require_native_policy if native else require_wait_policy
        validator(getattr(args, "busy_policy", "wait"))
        with registration_guard(root, args):
            return function(args, root)
    return guarded


@contextmanager
def effect_guard(root, record):
    if record.get('schema_version') == 8:
        with WakeLifecycleLock(root, 'wake-policy'):
            yield
    else:
        yield
