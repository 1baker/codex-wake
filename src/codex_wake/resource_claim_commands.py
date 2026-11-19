"""CLI/MCP adapter for host-verified cooperative mutation-resource custody."""
from __future__ import annotations

from .cli_output import emit
from pathlib import Path
from . import measurements

from .goal_supervision import verified_native_caller
from .managed_inventory import ManagedInventory
from .resource_claims import Claimant, ResourceClaims, ResourceClaimError


def _claimant(agent_id, root, *, observer, operator, native_context, now):
    agent = ManagedInventory(root, now=now).inspect(agent_id)['agent']
    if not operator and agent['runtime'] == 'codex':
        verified_native_caller(native_context, agent['conversation_id'])
    if (observer is None or agent['enrollment'] != 'enrolled'
            or agent['state'] not in ('ready', 'stale')):
        raise ResourceClaimError('owner_unqualified', 'current enrolled managed binding and runtime observer required')
    sample = observer(dict(runtime=agent['runtime'], conversation_id=agent['conversation_id'])).validated(measurements.snapshot() if now is None else now())
    if (sample.runtime != agent['runtime'] or sample.namespace != agent['namespace']
            or sample.conversation_id != agent['conversation_id'] or sample.root != agent['root']
            or sample.process != agent['process'] or sample.state != 'ready'):
        raise ResourceClaimError('owner_changed', 'fresh runtime binding differs from enrolled managed generation')
    if not operator and sample.runtime == 'grok' and sample.caller_verified is not True:
        raise ResourceClaimError('owner_unqualified', 'Grok requires verified host-bound caller context')
    return Claimant(agent_id, sample.root, sample.process, sample.observed_at,
                    clock_observation=sample.clock_observation)


def execute(action, arguments, root, *, native_context=None, observer=None, operator=False, now=None):
    if type(operator) is not bool or 'operator' in arguments or 'role' in arguments:
        raise ResourceClaimError('authority_denied', 'operator authority is host supplied, never a model argument')
    store = ResourceClaims(root, now=now)
    if action in ('list', 'show'):
        return store.inspect(arguments.get('claim_id') if action == 'show' else None)
    if action not in ('claim', 'check', 'release', 'transfer'):
        raise ResourceClaimError('invalid_argument', 'unknown resource claim operation')
    if action == 'release' and operator:
        return store.release(arguments['claim_id'], arguments['generation'], operator=True, reason=arguments.get('reason'))
    if action == 'transfer' and not operator:
        raise ResourceClaimError('operator_required', 'resource custody transfer requires explicit local operator action')
    owner_id = arguments['target_managed_agent_id'] if action == 'transfer' else arguments['managed_agent_id']
    claimant = _claimant(owner_id, root, observer=observer, operator=operator, native_context=native_context, now=now)
    if action == 'claim':
        if not operator and not Path(arguments['path']).resolve().is_relative_to(Path(claimant.root)):
            raise ResourceClaimError('workspace_denied', 'worker resource claim must remain within its managed workspace')
        return store.claim(arguments['kind'], arguments['path'], claimant)
    if action == 'transfer':
        return store.transfer(arguments['claim_id'], arguments['generation'], claimant,
                              operator=True, reason=arguments.get('reason'))
    if action == 'release':
        return store.release(arguments['claim_id'], arguments['generation'], claimant)
    with store.guard(arguments['claim_id'], arguments['generation'], claimant) as claim:
        return dict(status='admitted', point_in_time_only=True, claim=claim)


def register_parser(subparsers):
    from .resource_claims import KINDS
    parser = subparsers.add_parser('resources', help='declare and inspect cooperative directory mutation custody')
    commands = parser.add_subparsers(dest='resource_command', required=True)
    for action in ('list', 'show', 'claim', 'check', 'release', 'transfer'):
        command = commands.add_parser(action)
        command.add_argument('--json', dest='as_json', action='store_true')
        if action in ('show', 'check', 'release', 'transfer'):
            command.add_argument('--claim-id', required=True)
        if action in ('check', 'release', 'transfer'):
            command.add_argument('--generation', type=int, required=True)
        if action in ('claim', 'check', 'release'):
            command.add_argument('--managed-agent-id', required=action != 'release')
        if action == 'claim':
            command.add_argument('--kind', choices=KINDS, required=True)
            command.add_argument('--path', required=True)
        if action == 'transfer':
            command.add_argument('--target-managed-agent-id', required=True)
        if action in ('release', 'transfer'):
            command.add_argument('--reason')
        if action not in ('list', 'show'):
            command.add_argument('--operator', action='store_true', help='explicit local operator action; never a model argument')
            command.add_argument('--app-server', default='unix://')
            command.add_argument('--tmux-socket')
            command.add_argument('--timeout', type=float, default=10)
            command.add_argument('--runtime-root')
            command.add_argument('--binding-id')
            command.add_argument('--binding-sha256')
            command.add_argument('--bus-root')
            command.add_argument('--capability')
    return parser


def run(args, root, *, native_context=None, observer=None, now=None):
    import json
    from .records import WakeError
    try:
        action = args.resource_command
        operator = getattr(args, 'operator', False) is True
        names = ('managed_agent_id', 'target_managed_agent_id', 'kind', 'path', 'claim_id', 'generation', 'reason')
        arguments = {name: getattr(args, name) for name in names if getattr(args, name, None) is not None}
        if observer is None and action not in ('list', 'show') and not (action == 'release' and operator):
            from .managed_inventory_commands import RuntimeObserver
            if not 0 < args.timeout <= 30:
                raise ResourceClaimError('invalid_argument', 'runtime timeout must be positive and at most 30 seconds')
            runtime = bus = capability = None
            if operator and args.runtime_root:
                from .runtime_a2a import GrokMailboxRuntime
                runtime = GrokMailboxRuntime(args.runtime_root)
            elif not operator and args.bus_root and args.capability:
                from .a2a_bus import BusStore
                from .runtime_a2a import GrokMailboxRuntime
                bus, capability = BusStore(Path(args.bus_root)), Path(args.capability)
                runtime = GrokMailboxRuntime.from_actor(bus, capability)
            reader = RuntimeObserver(endpoint=args.app_server, socket_path=args.tmux_socket,
                timeout=args.timeout, grok_runtime=runtime, bus=bus, capability=capability, operator=operator, now=now)
            def observer(identity):
                return reader(dict(identity, binding_id=args.binding_id, binding_sha256=args.binding_sha256))
        result = execute(action, arguments, root, native_context=native_context,
                         observer=observer, operator=operator, now=now)
        emit(result, args)
        return 0
    except (WakeError, OSError, ValueError, KeyError, TypeError) as error:
        emit(dict(status='held', error=dict(code=getattr(error, 'code', 'resource_unavailable'),
            message=str(error) if isinstance(error, WakeError) else 'Resource custody or runtime evidence is unavailable.')), args)
        return 2
