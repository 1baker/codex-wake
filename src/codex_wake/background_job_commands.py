"""CLI/MCP adapter for exact operator-configured background command profiles."""
from __future__ import annotations

from .cli_output import emit
import json
from pathlib import Path
from . import measurements

from .background_jobs import BackgroundJobs, BackgroundJobError
from .permission_commands import verified_cli_principal
from .records import WakeError
from .task_briefs import TaskBriefStore


def register_parser(subparsers):
    parser = subparsers.add_parser('jobs', help='launch and await bounded approved local commands')
    commands = parser.add_subparsers(dest='job_command', required=True)
    for action in ('configure', 'profile', 'launch', 'show', 'cancel', 'await'):
        command = commands.add_parser(action)
        command.add_argument('--json', dest='as_json', action='store_true')
        command.add_argument('--bus-root', type=Path)
        command.add_argument('--operator-capability', type=Path)
        command.add_argument('--actor-capability', type=Path)
        command.add_argument('--actor-runtime', choices=('codex', 'grok'), default='codex')
        command.add_argument('--app-server', default='unix://')
        if action in ('configure', 'launch'):
            command.add_argument('--tmux-socket')
            command.add_argument('--timeout', type=float, default=10)
            command.add_argument('--runtime-root')
            command.add_argument('--binding-id')
            command.add_argument('--binding-sha256')
        if action in ('configure', 'profile', 'launch'):
            command.add_argument('--profile', required=True)
        if action == 'configure':
            command.add_argument('--argv-json', required=True, help='operator-approved exact argv JSON list')
            command.add_argument('--cwd', type=Path, required=True)
            command.add_argument('--task-id', required=True)
            command.add_argument('--assignment-id', required=True)
            command.add_argument('--owner', required=True)
            command.add_argument('--max-seconds', type=float, default=300)
            command.add_argument('--max-log-bytes', type=int, default=1048576)
            command.add_argument('--mutation', action='store_true')
            command.add_argument('--claim-id')
            command.add_argument('--claim-generation', type=int)
            command.add_argument('--managed-agent-id')
        if action == 'launch':
            command.add_argument('--idempotency-key', required=True)
        if action in ('show', 'cancel', 'await'):
            command.add_argument('--job-id', required=True)
        if action == 'cancel':
            command.add_argument('--generation', type=int, required=True)
    return parser


def _fresh_claimant(args, root, caller, managed_agent_id, *, observer, now):
    """Recover process binding from existing host runtime evidence, never CLI JSON."""
    from .managed_inventory import ManagedInventory
    from .managed_inventory_commands import RuntimeObserver
    from .resource_claims import Claimant
    agent = ManagedInventory(root).inspect(managed_agent_id)['agent']
    if (agent['enrollment'] != 'enrolled' or agent['state'] not in ('ready', 'stale')
            or (caller.role != 'operator' and agent['conversation_id'] != caller.subject)):
        raise BackgroundJobError('job_claim_owner_unavailable', 'current enrolled exact caller binding required')
    if observer is None:
        timeout = getattr(args, 'timeout', 10)
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise BackgroundJobError('job_invalid_argument', 'runtime timeout must be within 30 seconds')
        runtime = bus = capability = None
        if agent['runtime'] == 'grok':
            from .runtime_a2a import GrokMailboxRuntime
            from .a2a_bus import BusStore
            if caller.role == 'operator' and getattr(args, 'runtime_root', None):
                runtime = GrokMailboxRuntime(args.runtime_root)
            elif getattr(args, 'bus_root', None) and getattr(args, 'actor_capability', None):
                bus, capability = BusStore(Path(args.bus_root)), Path(args.actor_capability)
                runtime = GrokMailboxRuntime.from_actor(bus, capability)
        observer = RuntimeObserver(endpoint=getattr(args, 'app_server', 'unix://'),
            socket_path=getattr(args, 'tmux_socket', None), timeout=timeout, grok_runtime=runtime,
            bus=bus, capability=capability, operator=caller.role == 'operator', now=now)
    sample = observer(dict(runtime=agent['runtime'], conversation_id=agent['conversation_id'],
        binding_id=getattr(args, 'binding_id', None), binding_sha256=getattr(args, 'binding_sha256', None))).validated(measurements.snapshot() if now is None else now())
    if (sample.runtime != agent['runtime'] or sample.namespace != agent['namespace']
            or sample.conversation_id != agent['conversation_id'] or sample.root != agent['root']
            or sample.process != agent['process'] or sample.state != 'ready'
            or (sample.runtime == 'grok' and caller.role != 'operator' and sample.caller_verified is not True)):
        raise BackgroundJobError('job_claim_owner_changed', 'fresh runtime differs from the enrolled managed generation')
    return Claimant(managed_agent_id, sample.root, sample.process, sample.observed_at,
                    clock_observation=sample.clock_observation)


def execute(args, root, *, principal=None, register_wake=None, observer=None, now=None):
    """The injected Principal and wake adapter are trusted host inputs only."""
    from .session_permissions import Principal
    caller = principal if principal is not None else verified_cli_principal(args)
    if type(caller) is not Principal:
        raise BackgroundJobError('job_identity_unverified', 'verified host caller required')
    # Task scopes are recovered by the host rather than accepted as CLI claims.
    store = BackgroundJobs(root)
    action = args.job_command
    if action == 'configure':
        if caller.role != 'operator':
            raise BackgroundJobError('job_operator_required', 'operator capability required to configure profiles')
        claim = None
        claim_args = (getattr(args, 'claim_id', None), getattr(args, 'claim_generation', None),
                      getattr(args, 'managed_agent_id', None))
        if any(value is not None for value in claim_args):
            if any(value is None for value in claim_args):
                raise BackgroundJobError('job_claim_unverified', 'claim ID, generation and managed agent are all required')
            claimant = _fresh_claimant(args, root, caller, claim_args[2], observer=observer, now=now)
            claim = (claim_args[0], claim_args[1], claimant)
        return store.approve_command(args.profile, json.loads(args.argv_json), args.cwd,
            principal=caller, task_pin=TaskBriefStore(root).assignment_pin(args.task_id, args.assignment_id),
            owner=args.owner, max_seconds=args.max_seconds, max_log_bytes=args.max_log_bytes,
            mutation=getattr(args, 'mutation', False), claim=claim)
    if action == 'profile':
        profile = store.profile(args.profile)
        command = profile['command']
        if caller.role != 'operator' and caller.subject != command['owner']:
            raise BackgroundJobError('job_owner_denied', 'profile belongs to another exact owner')
        return profile
    if principal is None and caller.role != 'operator' and action in ('launch', 'cancel', 'await'):
        from .permission_enforcement import verified_tasks
        command = (store.profile(args.profile)['command'] if action == 'launch'
                   else store.inspect(args.job_id)['intent']['profile']['command'])
        pin = command['task_pin']
        caller = Principal(caller.subject, tasks=verified_tasks(root, caller.subject, pin['task_id'],
            pin['assignment_id'], actor_id=getattr(args, 'permission_actor_id', None)))
    if action == 'launch':
        command = store.profile(args.profile)['command']
        claim = command.get('claim')
        claimant = None
        if claim is not None:
            owner = claim.get('owner') or claim['claimant']
            claimant = _fresh_claimant(args, root, caller, owner['managed_agent_id'], observer=observer, now=now)
        return store.launch(args.profile, principal=caller, idempotency_key=args.idempotency_key, claimant=claimant)
    if action == 'show':
        value = store.inspect(args.job_id)
        store.authorize_inspection(value, caller)
        return value
    if action == 'cancel':
        return store.cancel(args.job_id, principal=caller, expected_generation=args.generation)
    if action == 'await':
        return store.await_result(args.job_id, principal=caller, register_wake=register_wake)
    raise BackgroundJobError('job_invalid_argument', 'unknown background job operation')


def jobs_command(args, root, *, principal=None, register_wake=None, observer=None):
    try:
        value = execute(args, root, principal=principal, register_wake=register_wake, observer=observer)
        emit(dict(schema_version=1, success=True, job=value), args)
        return 0
    except (WakeError, OSError, ValueError, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, WakeError) else 'Job state or caller evidence unavailable.'
        emit(dict(schema_version=1, success=False,
            error=dict(code=getattr(error, 'code', 'job_unavailable'), message=message)), args)
        return 5
