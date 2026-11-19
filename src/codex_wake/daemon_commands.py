"""Public CLI, API and MCP adapters for explicit account daemon lifecycle."""
import json

from .cli_output import emit
import os
import hashlib
from pathlib import Path

from .controller_auth import Actor, AuthError, _qualified_upper
from .controller_daemons import ControllerDaemons
from .managed_inventory import InventoryError


def owner_from_root(root):
    from .build_commands import owner_from_root as builds
    return ControllerDaemons(builds(root))


def local_operator(target, capabilities=('control', 'observe')):
    from . import measurements
    try:
        lower, _ = measurements.utc_bounds()
    except measurements.TimeUnavailable:
        raise AuthError('qualified_time_unavailable') from None
    return Actor('uid:' + str(os.getuid()), 'owner', 'local-cli', 'local-cli',
                 'local://uid/' + str(os.getuid()), 'wake:controller', frozenset(capabilities), [target], lower + 120)


def execute(root, operation, arguments, *, actor=None, authorize=None, owner=None):
    from .controller_runtime import ControllerRuntime, _local_stop_capability
    owner = owner or owner_from_root(root)
    if operation in ('daemons.list', 'daemons.status'):
        def guard():
            if actor is not None and (not isinstance(actor, Actor) or actor.expires_at <= _qualified_upper()
                    or authorize is None or authorize() != actor or 'observe' not in actor.scopes):
                raise AuthError('insufficient_scope')
        guard()
        result = owner.execute(operation, arguments)
        if actor is not None:
            if 'observe' not in actor.scopes:
                raise AuthError('insufficient_scope')
            rows = result.get('daemons', [result.get('daemon')])
            def permitted(row):
                return any({'host', 'environment', 'account', 'home', 'home_generation'} <= scope.keys()
                           and all(row['target'].get(k) == v for k, v in scope.items()) for scope in actor.targets)
            if operation == 'daemons.list':
                result['daemons'] = [row for row in rows if permitted(row)]
            elif not permitted(rows[0]):
                raise AuthError('insufficient_scope')
        guard()
        return dict(schema_version=1, operation=operation, status='completed', result=result)
    target = arguments.get('expected_target')
    if not isinstance(target, dict) or not {'home', 'home_generation', 'build_sha256', 'process', 'socket_generation'} <= target.keys():
        raise InventoryError('stale_target', 'previously observed exact daemon target required')
    local_stop = actor is None and operation == 'daemons.stop'
    stop_capability = _local_stop_capability(root, arguments) if local_stop else None
    if actor is None and not local_stop:
        actor = local_operator(target)
        authorize = lambda: actor
    elif actor is not None and not any(set(target) <= set(scope) and scope == target for scope in actor.targets):
        raise AuthError('insufficient_scope')
    runtime = ControllerRuntime(root)
    request = arguments.get('_request', {})
    if not local_stop:
        runtime.check_authority(actor, target, 'control', authorize=authorize)
        try:
            runtime.operation(actor, 'operations.result', {'operation_id': request.get('operation_id')}, authorize=authorize)
        except InventoryError as error:
            if error.code != 'operation_not_found':
                raise
            current = owner.execute('daemons.status', {k: v for k, v in arguments.items() if k in ('account', 'channel')})
            if current['daemon']['target'] != target:
                raise InventoryError('stale_target', 'daemon account/build/process target changed')
    directory = Path(root) / 'controller-daemon-errors'
    diagnostic = directory / (hashlib.sha256(str(request.get('operation_id')).encode()).hexdigest() + '.json')
    def dispatch(op, payload):
        try:
            return owner.execute(op, payload)
        except (ValueError, OSError) as error:
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink() or directory.stat().st_mode & 0o077:
                raise InventoryError('configuration_unavailable', 'private daemon diagnostic directory required') from error
            fd = os.open(diagnostic, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(dict(code=getattr(error, 'code', 'daemon_held'), message=str(error)[:4000]), stream)
            raise
    value = (runtime.execute_local_stop(stop_capability, arguments, dispatch=dispatch) if local_stop
             else runtime.execute(actor, operation, arguments, authorize=authorize, dispatch=dispatch))
    if diagnostic.is_file() and not diagnostic.is_symlink() and not diagnostic.stat().st_mode & 0o077:
        value['result']['diagnostic'] = json.loads(diagnostic.read_text())
    return value


def protected_execute(operation, arguments, root):
    from .operation_commands import local_actor
    return execute(root, operation, arguments, actor=local_actor(root), authorize=lambda: local_actor(root))


def register_parser(subparsers):
    p = subparsers.add_parser('daemons', help='manage exact account-scoped native daemon instances')
    verbs = p.add_subparsers(dest='daemon_verb', required=True)
    for verb in ('list', 'status', 'start', 'restart', 'update', 'stop'):
        item = verbs.add_parser(verb)
        if verb != 'list':
            item.add_argument('account')
        item.add_argument('--channel', choices=('stock', 'modded'), default='modded')
        item.add_argument('--json', action='store_true', dest='as_json')
        if verb not in ('list', 'status'):
            item.add_argument('--expected-target', type=json.loads)
            item.add_argument('--idempotency-key')
            item.add_argument('--yes', action='store_true', dest='confirm')


def command(args, root):
    operation = 'daemons.' + args.daemon_verb
    arguments = {'channel': args.channel}
    if hasattr(args, 'account'):
        arguments['account'] = args.account
    try:
        if args.daemon_verb not in ('list', 'status'):
            from .cli_targets import require_terminal, show_intent, confirm_intent, intent_key
            target = args.expected_target
            key = args.idempotency_key
            missing = [flag for flag, value in (('--expected-target', target), ('--idempotency-key', key)) if value is None]
            require_terminal(missing)
            confirmed = args.confirm
            if missing:
                if target is None:
                    target = execute(root, 'daemons.status', arguments)['result']['daemon']['target']
                key = key if key is not None else intent_key()
                show_intent(operation, target, key)
                if args.daemon_verb in ('restart', 'update', 'stop'):
                    confirmed = confirm_intent('This may interrupt clients on only the selected account daemon.', confirmed)
            arguments.update(expected_target=target, confirm=confirmed)
            arguments['_request'] = dict(operation_id='daemon-' + hashlib.sha256(key.encode()).hexdigest(), idempotency_key=key,
                correlation_id=key, binding='local-cli', target=target)
        value = execute(root, operation, arguments)
    except (ValueError, OSError) as error:
        value = dict(schema_version=1, operation=operation, status='failed',
                     error=dict(code=getattr(error, 'code', 'daemon_held'), message=str(error)))
    emit(value, args)
    record = value.get('result', {}).get('operation', {})
    return 0 if value['status'] == 'completed' and record.get('phase', 'terminal') == 'terminal' else 2


def tool_specs():
    result = {}
    for verb in ('list', 'status', 'start', 'restart', 'update', 'stop'):
        properties = dict(channel={'type': 'string', 'enum': ['stock', 'modded']})
        required = []
        if verb != 'list':
            properties['account'] = {'type': 'string'}
            required.append('account')
        read = verb in ('list', 'status')
        if not read:
            properties.update(expected_target={'type': 'object'}, confirm={'type': 'boolean'}, _request={'type': 'object'})
            required += ['expected_target', '_request']
        result['wake_daemons_' + verb] = ('controller-daemons', 'daemons.' + verb,
            'Observe or explicitly manage one pinned account daemon; no provider turn, credential copy or allowance renewal.',
            properties, required, read)
    return result
