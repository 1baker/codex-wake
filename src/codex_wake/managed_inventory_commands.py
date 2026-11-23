"""CLI/MCP caller seam for managed inventory. Native metadata is host supplied."""
from __future__ import annotations

from .cli_output import emit
from . import measurements

from .goal_supervision import verified_native_caller
from .managed_inventory import ManagedInventory, InventoryError
from .records import WakeError


def execute(action, arguments, root, *, native_context=None, observer=None,
            operator=False, now=None):
    if type(operator) is not bool:
        raise InventoryError('policy_denied', 'operator authority must come from the host')
    inventory = ManagedInventory(root, now=now)
    if action in ('list', 'show'):
        return inventory.inspect(arguments.get('managed_agent_id') if action == 'show' else None)
    if action in ('configure', 'unenroll', 'reenable'):
        if not operator:
            raise InventoryError('policy_denied', 'explicit local operator action required')
        if action == 'configure':
            return inventory.configure(arguments['mode'], arguments.get('selected', []))
        return inventory.set_enrollment(arguments['managed_agent_id'], enabled=action == 'reenable')
    if action not in ('enroll', 'reconcile'):
        raise InventoryError('invalid_argument', 'unknown inventory action')
    if arguments.get('runtime', 'codex') == 'codex' and not operator:
        verified_native_caller(native_context, arguments['conversation_id'])
    if observer is None:
        raise InventoryError('identity_unqualified', 'qualified runtime observer is unavailable')
    try:
        sample = observer(arguments)
    except InventoryError as error:
        # Source loss may invalidate a known exact binding, but cannot create or
        # substitute an identity. Grok failed caller authentication stays denied.
        if (action != 'reconcile' or error.code != 'identity_unavailable'
                or (arguments.get('runtime', 'codex') == 'grok' and not operator)):
            raise
        from .managed_inventory import Observation
        previous = inventory.inspect(arguments['managed_agent_id'])['agent']
        if (previous['runtime'] != arguments.get('runtime', 'codex')
                or previous['conversation_id'] != arguments['conversation_id']):
            raise InventoryError('identity_changed', 'unavailable source does not match managed identity')
        sample = Observation(previous['runtime'], previous['namespace'], previous['conversation_id'],
                             previous['root'], 'unavailable', measurements.utc_time() if now is None else now(), previous['evidence_kind'],
                             None, [], {name: 'unavailable' for name in previous['capabilities']},
                             profile=previous['profile'], clock_observation=measurements.snapshot() if now is None else None)
    if sample.runtime != arguments.get('runtime', 'codex') or sample.conversation_id != arguments['conversation_id']:
        raise InventoryError('identity_changed', 'observed identity differs from requested identity')
    if sample.runtime == 'grok' and not operator and sample.caller_verified is not True:
        raise InventoryError('identity_unqualified', 'Grok caller requires verified host-bound context')
    if action == 'reconcile':
        return inventory.reconcile(arguments['managed_agent_id'], sample)
    return inventory.enroll(sample, operator=operator, predecessor=arguments.get('predecessor'),
                            task_id=arguments.get('task_id'), allocation_id=arguments.get('allocation_id'))


class RuntimeObserver:
    """Read existing runtime evidence without any terminal input or native turn."""
    def __init__(self, *, endpoint='unix://', socket_path=None, timeout=10,
                 grok_runtime=None, bus=None, capability=None, operator=False, now=None, allow_idle_saved=False):
        self.endpoint, self.socket_path, self.timeout = endpoint, socket_path, timeout
        self.grok_runtime, self.bus, self.capability = grok_runtime, bus, capability
        self.operator, self.now = operator, now
        self.allow_idle_saved = allow_idle_saved

    def _time_observation(self):
        if self.now is not None:
            return self.now(), None
        clock = measurements.snapshot()
        if clock.get('utc') is None:
            raise measurements.TimeUnavailable('stable_time_utc_unqualified')
        return clock['utc']['upper'], clock

    def __call__(self, arguments):
        from .sessions import SelectionError
        from .shared_app_server import SharedSourceError
        try:
            runtime = arguments.get('runtime', 'codex')
            if runtime == 'codex':
                return self._codex(arguments['conversation_id'])
            if runtime == 'grok':
                return self._grok(arguments)
            raise InventoryError('identity_unqualified', 'unsupported runtime')
        except InventoryError:
            raise
        except (WakeError, SelectionError, SharedSourceError, OSError, ValueError, KeyError, TypeError):
            raise InventoryError('identity_unavailable', 'qualified runtime identity or process generation is unavailable') from None

    def _codex(self, conversation_id):
        from .a2a_identity import RuntimeIdentity
        from .managed_inventory import Observation
        from .process import process_identity
        from .sessions import observe, resolve
        from .shared_app_server import SharedAppServerReader, locate_shared_endpoint
        endpoint = locate_shared_endpoint(timeout=self.timeout) if self.endpoint == 'unix://' else self.endpoint
        with SharedAppServerReader(endpoint, timeout=self.timeout) as reader:
            thread = reader.read_thread(conversation_id)
            if thread.get('id') != conversation_id:
                raise InventoryError('identity_changed', 'native conversation identity changed')
            identity = RuntimeIdentity.from_metadata(thread, reader.server_metadata)
            snapshot = observe(endpoint=endpoint, socket_path=self.socket_path, timeout=self.timeout)
            saved_only = not any(row.get('thread_id') == conversation_id for row in snapshot['sessions'])
            if saved_only:
                # Loaded membership excludes saved recipients after their last TUI
                # disconnects. Absence is useful only with complete inventory and
                # no possible competing attachment for this exact saved metadata.
                name = thread.get('name')
                if (not snapshot.get('complete') or not isinstance(name, str) or not name
                        or thread.get('status', {}).get('type') != 'notLoaded'
                        or any(conversation_id in row.get('candidates', []) or (
                            row.get('attachments') and row.get('name') == name
                            and row.get('cwd') == identity.cwd) for row in snapshot['sessions'])):
                    raise InventoryError('identity_unavailable', 'saved recipient absence is unverified')
                row = dict(cwd=identity.cwd, attachments=[])
            else:
                row = resolve(snapshot, 'thread:' + conversation_id)
            idle_detached = (
                self.allow_idle_saved and not saved_only and not row['attachments']
                and snapshot.get('complete') and thread.get('status', {}).get('type') == 'idle'
                and not any(conversation_id in candidate.get('candidates', [])
                            for candidate in snapshot['sessions'])
            )
            current = reader.read_thread(conversation_id)
            repeated = RuntimeIdentity.from_metadata(current, reader.server_metadata)
            if (repeated != identity or row['cwd'] != identity.cwd
                    or (saved_only and current.get('status', {}).get('type') != 'notLoaded')):
                raise InventoryError('identity_changed', 'native conversation changed during observation')
        attachments = row['attachments']
        generations = {(pane.get('client_pid'), pane.get('client_start_time_ticks')) for pane in attachments}
        process, state = None, 'unavailable'
        if len(generations) > 1:
            state = 'ambiguous'
        elif len(generations) == 1:
            pid, ticks = next(iter(generations))
            current = process_identity(pid) if type(pid) is int and pid > 0 else None
            if current and current.get('start_time_ticks') == ticks and current.get('boot_id'):
                process = {'pid': pid, 'start_ticks': ticks, 'boot_id': current['boot_id']}
                state = 'ready'
        # Only metadata is projected. Socket paths, title frames and host endpoints
        # are not inventory identity or credentials to copy into its read view.
        projected = [{key: pane[key] for key in ('pane_id', 'window_id', 'session_id',
                     'window_index', 'pane_index', 'window_name', 'session_name') if key in pane}
                     for pane in attachments]
        observed_at, clock = self._time_observation()
        return Observation('codex', identity.namespace, conversation_id, identity.cwd,
                           state, observed_at, 'native_metadata', process, projected,
                           {'inspect': 'supported', 'lifecycle_control': 'not_qualified',
                            'saved_resume': 'supported' if not attachments and (
                                current.get('status', {}).get('type') == 'notLoaded'
                                or (idle_detached and current.get('status', {}).get('type') == 'idle')
                            ) else 'not_qualified'},
                           clock_observation=clock)

    def _grok(self, arguments):
        from .managed_inventory import Observation
        from .a2a_bus import read_capability
        runtime = self.grok_runtime
        if runtime is None:
            raise InventoryError('identity_unqualified', 'host-bound Grok runtime is unavailable')
        caller_verified = False
        if self.operator:
            binding_id, sha = arguments.get('binding_id'), arguments.get('binding_sha256')
        else:
            if self.bus is None or self.capability is None:
                raise InventoryError('identity_unqualified', 'Grok caller capability is unavailable')
            actor = runtime.authenticate(self.bus, self.capability,
                                         claimed_session=arguments['conversation_id'])
            profile = read_capability(self.bus.root / 'runtime-actors' / (actor.actor_id + '.json'))
            binding_id, sha = profile['binding_id'], profile['binding_sha256']
            caller_verified = True
        identity, binding = runtime.resolve(binding_id, sha)
        if identity.thread_id != arguments['conversation_id']:
            raise InventoryError('identity_changed', 'Grok conversation identity changed')
        process = {key: binding[key] for key in ('pid', 'start_ticks', 'boot_id')}
        observed_at, clock = self._time_observation()
        return Observation('grok', identity.namespace, identity.thread_id, identity.cwd,
                           'ready', observed_at, 'host_bound_runtime', process,
                           [{'pane_id': binding['pane']}],
                           {'inspect': 'supported', 'lifecycle_control': 'not_qualified'},
                           caller_verified=caller_verified, clock_observation=clock)


def register_parser(subparsers):
    parser = subparsers.add_parser('agents', help='manage durable conversation inventory and enrollment')
    commands = parser.add_subparsers(dest='agents_command', required=True)
    for action in ('list', 'show', 'enroll', 'reconcile', 'configure', 'unenroll', 'reenable'):
        command = commands.add_parser(action)
        command.add_argument('--json', dest='as_json', action='store_true')
        if action not in ('list', 'show'):
            command.add_argument('--operator', action='store_true',
                                 help='explicit local operator action; never exposed as an agent MCP argument')
        if action in ('show', 'reconcile', 'unenroll', 'reenable'):
            command.add_argument('--managed-agent-id', required=True)
        if action in ('enroll', 'reconcile'):
            command.add_argument('--runtime', choices=('codex', 'grok'), default='codex')
            command.add_argument('--conversation-id', required=True)
            command.add_argument('--app-server', default='unix://')
            command.add_argument('--tmux-socket')
            command.add_argument('--timeout', type=float, default=10)
            command.add_argument('--runtime-root', help='operator-only existing Grok runtime root')
            command.add_argument('--binding-id', help='operator-selected existing Grok binding')
            command.add_argument('--binding-sha256')
            command.add_argument('--bus-root', help='existing Grok host-bound caller bus')
            command.add_argument('--capability', help='existing issued Grok caller capability')
        if action == 'enroll':
            for option in ('predecessor', 'task-id', 'allocation-id'):
                command.add_argument('--' + option)
        if action == 'configure':
            from .managed_inventory import MODES
            command.add_argument('--mode', choices=MODES, required=True)
            command.add_argument('--selected-json', default='[]',
                                 help='exact runtime/namespace/conversation selections')
    from .agent_observation_commands import register_parser as register_observation
    register_observation(commands)
    from .operator_overview_commands import register_parser as register_overview
    register_overview(commands)
    from .agent_resume_commands import register_parser as register_resume
    register_resume(commands)
    return parser


def run(args, root, *, native_context=None, observer=None, now=None):
    import json
    from pathlib import Path
    try:
        action = args.agents_command
        if action in ('overview', 'focus'):
            from .operator_overview_commands import run as overview_command
            return overview_command(args, root)
        if action == 'resume':
            from .agent_resume_commands import run as resume_command
            return resume_command(args, root)
        if action in ('observe', 'wait'):
            from .agent_observation_commands import run as observe_command
            return observe_command(args, root)
        operator = getattr(args, 'operator', False) is True
        names = ('managed_agent_id', 'runtime', 'conversation_id', 'predecessor',
                 'task_id', 'allocation_id', 'binding_id', 'binding_sha256', 'mode')
        arguments = {name: getattr(args, name) for name in names
                     if getattr(args, name, None) is not None}
        if action == 'configure':
            arguments['selected'] = json.loads(args.selected_json)
        if observer is None and action in ('enroll', 'reconcile'):
            if not 0 < args.timeout <= 30:
                raise InventoryError('invalid_argument', 'timeout must be positive and at most 30 seconds')
            runtime = bus = capability = None
            if args.runtime == 'grok':
                from .runtime_a2a import GrokMailboxRuntime
                if operator and args.runtime_root:
                    runtime = GrokMailboxRuntime(args.runtime_root)
                elif not operator and args.bus_root and args.capability:
                    from .a2a_bus import BusStore
                    bus, capability = BusStore(Path(args.bus_root)), Path(args.capability)
                    runtime = GrokMailboxRuntime.from_actor(bus, capability)
            observer = RuntimeObserver(endpoint=args.app_server, socket_path=args.tmux_socket,
                                       timeout=args.timeout, grok_runtime=runtime, bus=bus,
                                       capability=capability, operator=operator, now=now)
        value = execute(action, arguments, root, native_context=native_context,
                        observer=observer, operator=operator, now=now)
        emit(value, args)
        return 0
    except (ValueError, KeyError, TypeError, OSError, WakeError) as error:
        value = {'status': 'held', 'error': {'code': getattr(error, 'code', 'inventory_unavailable'),
                 'message': str(error) if isinstance(error, (ValueError, InventoryError))
                 else 'Inventory or qualified runtime evidence is unavailable.'}}
        emit(value, args)
        return 2
