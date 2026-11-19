"""Read-only selected-account readiness; registration never proves native operation.

Reuses account resolution and the build-channel owner. No credentials, watcher starts, grants, refreshes, or budget mutations occur.
Existing health probes and service status inspection provide read-only evidence.
"""
from pathlib import Path
import os
import socket
import subprocess

from .controller_auth import Actor, AuthError
from .account_observation import _TARGET_FIELDS, _actor_is_current

from .controller_accounts import ControllerAccounts
from .managed_inventory import InventoryError


def execute(root, arguments, *, accounts=None, actor=None, authorize=None):
    """Inspect selected launcher/registration, retaining explicit runtime gates."""
    if root is None:
        raise InventoryError('host_wake_root_required', 'host Wake root required')
    if (not isinstance(arguments, dict) or set(arguments) - {'selector', 'expected_target', 'manifest', 'launcher'}
            or not isinstance(arguments.get('selector'), str)):
        raise InventoryError('invalid_argument', 'selected account and optional manifest/launcher paths required')
    for key in ('manifest', 'launcher'):
        if key in arguments and (not isinstance(arguments[key], str) or not Path(arguments[key]).is_absolute()):
            raise InventoryError('invalid_argument', 'readiness paths must be absolute')
    accounts = accounts or ControllerAccounts(Path(root)/'controller-accounts.toml',
        host=socket.gethostname(), environment=os.environ.get('WSL_DISTRO_NAME') or os.name)
    selection = {key: arguments[key] for key in ('selector', 'expected_target') if key in arguments}
    account = accounts.execute('accounts.resolve', selection)['account']
    target = account['target']
    def guard():
        if actor is not None:
            if (not isinstance(actor, Actor) or not _actor_is_current(actor) or authorize is None
                    or authorize() != actor or 'account.observe' not in actor.scopes
                    or not any(_TARGET_FIELDS <= scope.keys() and all(target.get(k) == v for k, v in scope.items()) for scope in actor.targets)):
                raise AuthError('insufficient_scope')
    guard()
    checks = {}
    launcher = arguments.get('launcher')
    checks['launcher'] = dict(state='unknown', remedy='Select the installed profile launcher path for inspection.')
    if launcher:
        path = Path(launcher)
        available = path.is_file() and os.access(path, os.X_OK)
        checks['launcher'] = dict(state='present' if available else 'blocked', path=str(path),
            remedy='Qualify this launcher with the selected native profile; presence does not prove its routing.' if available
            else 'Repair or install only the selected profile launcher; preserve stock and peer launchers.')
    checks['build'] = dict(state='missing', remedy='Supply the existing build-channel manifest for the selected profile.')
    if arguments.get('manifest'):
        from codex_profiles.build_channels import load_build, BuildError, _pinned_executable
        try:
            build = load_build(Path(arguments['manifest']), 'modded', Path(account['home']))
            with _pinned_executable(build):
                pass
            checks['build'] = dict(state='registered_bytes_verified', executable=str(build.executable),
                sha256=build.sha256, backend=build.backend,
                remedy='Qualify native initialization and selected home/backend identity in isolation.')
        except (BuildError, OSError):
            checks['build'] = dict(state='blocked', remedy='Repair the selected tenant build registration and digest using the existing build-channel owner; re-inspect before launch.')
    for name, remedy in (
        ('backend', 'Observe native initialization and selected home/backend identity using isolated native qualification.'),
        ('watcher', 'Inspect the existing selected limit-watcher owner; explicitly authorize any selected watcher start.'),
        ('limits', 'Exercise voluntary limits through the existing self-limit owner on the selected real profile; retain cumulative usage.'),
        ('refresh', 'Qualify scoped refresh through the existing refresh owner on the selected real profile; preserve stock, peers and budgets.')):
        checks[name] = dict(state='not_qualified', remedy=remedy)
    # Daemon observation and client event-loop health are distinct evidence.
    checks['backend'] = dict(state='unknown', remedy='Supply the host-owned selected build manifest, then inspect daemons status.')
    if arguments.get('manifest'):
        from .controller_builds import ControllerBuilds
        from .controller_daemons import ControllerDaemons
        try:
            guard()
            daemon = ControllerDaemons(ControllerBuilds(arguments['manifest'], accounts)).execute(
                'daemons.status', dict(account=arguments['selector'], channel='modded'))['daemon']
            checks['backend'] = dict(state=daemon['state'], observation=daemon,
                remedy='Inspect the selected daemons status; any start or scoped restart requires separate authorization and the exact observed target.')
        except (InventoryError, BuildError, OSError, ValueError) as error:
            checks['backend'] = dict(state='unavailable', reason=getattr(error, 'code', 'build_held'),
                remedy='Repair the selected build registration or private daemon endpoint using existing build/daemon owners; inspect again before any authorized start.')
    from .controller_health import ControllerHealth
    health = ControllerHealth(root)
    try:
        bindings = [row for row in health.bindings()
                    if row['target'].get('home') == account['home']]
        if len(bindings) == 1:
            guard()
            observed = health.execute('health.observe', {'expected_target': bindings[0]['target']})
            checks['client'] = dict(state=observed['observation']['status'], observation=observed,
                remedy='Use the existing health.observe and exact selected runtime recovery capabilities; no peer restart is implied.')
        else:
            checks['client'] = dict(state='unknown', reason='missing_or_ambiguous_selected_health_binding',
                remedy='Register one exact selected runtime with the existing health binding owner, then inspect again.')
    except (InventoryError, OSError, ValueError):
        checks['client'] = dict(state='unavailable', remedy='Repair the existing private controller-health binding for the selected runtime.')
    from .goal_watcher import watcher_status
    try:
        guard()
        watcher = watcher_status(root)
        checks['watcher'] = dict(state=watcher['reason'], observation=watcher,
            scope='wake_root_process', selected_goal_enforced=False,
            remedy=watcher['next_action'])
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        checks['watcher'] = dict(state='unavailable', remedy='Inspect goal-limits watcher-status for the selected Wake root; do not start a competing watcher.')
    checks['limits']['operation'] = 'goal-limits readiness'
    checks['refresh']['native_dependency'] = 'thread/mcpServer/reload'
    accounts.execute('accounts.resolve', dict(selector=arguments['selector'], expected_target=account['target']))
    guard()
    return dict(schema_version=1, operation='accounts.readiness', status='completed',
        result=dict(account=account, status='incomplete', checks=checks,
                    native_qualified=False, effects='none'))
