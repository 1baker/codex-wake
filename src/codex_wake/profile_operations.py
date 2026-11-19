"""Scoped admission for registered stores and directional configuration sync.

Local operator calls use account_commands directly. MCP and OAuth callers retain
host-approved grants; selectors never grant filesystem inspection authority.
"""
from pathlib import Path

from .controller_auth import AuthError, _qualified_upper
from .managed_inventory import InventoryError

OPERATIONS = {'stores.register', 'stores.resolve', 'stores.list',
              'configuration.sync.preview', 'configuration.sync.apply', 'accounts.readiness'}


def execute(root, operation, arguments, *, accounts, actor, authorize):
    if not isinstance(arguments, dict):
        raise InventoryError('invalid_argument', 'operation arguments must be an object')
    required = ('admin' if operation == 'stores.register' else 'control' if operation.endswith('.apply')
                else 'configuration.observe' if operation.startswith('configuration.sync.') else 'account.observe')

    def guard():
        if actor.expires_at <= _qualified_upper() or authorize() != actor or required not in actor.scopes:
            raise AuthError('insufficient_scope')
    guard()

    def permitted(target, fields):
        return any(fields <= scope.keys() and all(target.get(k) == v for k, v in scope.items())
                   for scope in actor.targets)

    def store_allowed(store):
        target = dict(host=accounts.host, environment=accounts.environment,
                      **{k: store[k] for k in ('store_id', 'home', 'home_generation')})
        if permitted(target, {'host', 'environment', 'store_id', 'home', 'home_generation'}):
            return True
        if store['kind'] == 'profile':
            account = accounts.execute('accounts.resolve', {'selector': store['selector']})['account']
            from .account_observation import _TARGET_FIELDS
            return permitted(account['target'], _TARGET_FIELDS)
        return False

    if operation == 'accounts.readiness':
        return readiness(root, arguments, accounts=accounts, actor=actor, authorize=authorize)
    if operation == 'stores.register':
        from .account_management import registry_target
        target = dict(registry_target(accounts), home=arguments.get('home'))
        if not permitted(target, {'host', 'environment', 'registry', 'registry_revision', 'home'}):
            raise AuthError('insufficient_scope')
        guard()
        result = accounts.execute(operation, arguments)
    elif operation in ('stores.resolve', 'stores.list'):
        result = accounts.execute(operation, arguments)
        if operation == 'stores.list':
            result['stores'] = [store for store in result['stores'] if store_allowed(store)]
        elif not store_allowed(result['store']):
            raise AuthError('insufficient_scope')
    elif operation.startswith('configuration.sync.'):
        selectors = [arguments.get('source')]
        destinations = arguments.get('destinations')
        if not isinstance(destinations, list) or not destinations:
            raise InventoryError('invalid_argument', 'explicit destinations required')
        selectors += destinations
        for selector in selectors:
            store = accounts.execute('stores.resolve', {'selector': selector})['store']
            if not store_allowed(store):
                raise AuthError('insufficient_scope')
        from .configuration_sync import execute as sync
        from .profile_reload import selected_reload
        guard()
        result = sync(accounts, operation, arguments,
                      reload_executor=lambda destination: selected_reload(accounts, destination, categories=arguments.get('categories', []), guard=guard))
    else:
        raise InventoryError('unsupported_operation', 'unsupported profile operation')
    guard()
    return dict(schema_version=1, operation=operation, status='completed', result=result)


def readiness(root, arguments, *, accounts, actor=None, authorize=None):
    """Use the registered manifest on every transport; paths are local-only."""
    import tomllib
    from .account_readiness import execute as observe
    if not isinstance(arguments, dict):
        raise InventoryError('invalid_argument', 'readiness arguments must be an object')
    if actor is not None and set(arguments) & {'manifest', 'launcher'}:
        raise InventoryError('invalid_argument', 'remote readiness paths are host-owned; omit manifest and launcher')
    selected = dict(arguments)
    config = tomllib.loads(accounts.path.read_text())
    manifest = config.get('builds', {}).get('manifest')
    if manifest and 'manifest' not in selected:
        selected['manifest'] = manifest
    return observe(root, selected, accounts=accounts, actor=actor, authorize=authorize)


def protected_execute(operation, arguments, root):
    import os
    import socket
    from .controller_accounts import ControllerAccounts
    from .operation_commands import local_actor
    if root is None:
        raise InventoryError('host_wake_root_required', 'host Wake root required')
    accounts = ControllerAccounts(Path(root) / 'controller-accounts.toml',
        host=socket.gethostname(), environment=os.environ.get('WSL_DISTRO_NAME') or os.name)
    return execute(root, operation, arguments, accounts=accounts, actor=local_actor(root),
                   authorize=lambda: local_actor(root))


def tool_specs():
    from .command_contract import OPERATIONS as contracts
    return {op.tool: ('controller-profiles', op.name, op.summary + ' ' + op.effect,
                     op.schema()['properties'], list(op.required),
                     op.name not in ('stores.register', 'configuration.sync.apply'))
            for op in contracts if op.name in OPERATIONS}
