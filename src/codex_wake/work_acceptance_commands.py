"""Verified callers for independent acceptance; no model-supplied authority."""
from __future__ import annotations

from .cli_output import emit
import json
from pathlib import Path

from .permission_commands import verified_cli_principal
from .session_permissions import Principal
from .task_briefs import BriefAuthority
from .work_acceptance import WorkAcceptance, AcceptanceError
from .records import WakeError


def execute(action, arguments, root, *, principal, authority, claimant=None):
    if (not isinstance(principal, Principal) or not isinstance(authority, BriefAuthority)
            or any(key in arguments for key in ('role', 'operator', 'authority', 'principal', 'claimant'))):
        raise AcceptanceError('authority_denied', 'verified host authority is required')
    owner = WorkAcceptance(root)
    if action == 'define':
        return owner.define(arguments['contract_id'], arguments['task_id'], arguments['assignment_id'],
            arguments['checks'], authority=authority, principal=principal)
    if action == 'evaluate':
        return owner.evaluate(arguments['contract_id'], authority=authority, principal=principal, claimant=claimant)
    if action == 'inspect':
        return owner.inspect(arguments['contract_id'], authority=authority, principal=principal)
    if action == 'decide':
        return owner.decide(arguments['contract_id'], arguments['name'], arguments['outcome'],
            authority=authority, principal=principal, expires_at=arguments['expires_at'])
    raise AcceptanceError('invalid_argument', 'unknown acceptance operation')


def register_parser(subparsers):
    commands = subparsers.add_parser('acceptance', help='verify exact work independently of worker completion prose').add_subparsers(dest='acceptance_command', required=True)
    for verb in ('define', 'evaluate', 'inspect', 'decide'):
        command = commands.add_parser(verb)
        command.add_argument('--contract-id', required=True)
        command.add_argument('--bus-root', type=Path, required=True)
        command.add_argument('--operator-capability', type=Path)
        command.add_argument('--actor-capability', type=Path)
        command.add_argument('--app-server', default='unix://')
        command.add_argument('--tmux-socket')
        command.add_argument('--managed-agent-id')
        command.add_argument('--json', dest='as_json', action='store_true')
        if verb == 'define':
            command.add_argument('--task-id', required=True)
            command.add_argument('--assignment-id', required=True)
            command.add_argument('--checks-file', type=Path, required=True)
        if verb == 'decide':
            command.add_argument('--name', required=True)
            command.add_argument('--outcome', choices=('accepted', 'rejected'), required=True)
            command.add_argument('--expires-at', type=float, required=True)


def qualified_claimant(root, agent_id, principal, *, observer=None):
    from . import measurements
    from .managed_inventory import ManagedInventory
    from .managed_inventory_commands import RuntimeObserver
    from .resource_claims import Claimant
    agent = ManagedInventory(root).inspect(agent_id)['agent']
    if (agent['enrollment'] != 'enrolled' or agent['state'] not in ('ready', 'stale')
            or (principal.role != 'operator' and agent['conversation_id'] != principal.subject)):
        raise AcceptanceError('authority_denied', 'verified current owner is required')
    sample = (observer or RuntimeObserver())(dict(runtime=agent['runtime'], conversation_id=agent['conversation_id'])).validated(measurements.snapshot())
    if (sample.state != 'ready' or any(getattr(sample, field) != agent[field]
            for field in ('runtime', 'namespace', 'conversation_id', 'root', 'process'))):
        raise AcceptanceError('authority_denied', 'exact fresh owner binding differs')
    return Claimant(agent_id, sample.root, sample.process, sample.observed_at,
                    clock_observation=sample.clock_observation)


def run(args, root):
    try:
        principal = verified_cli_principal(args)
        owner = WorkAcceptance(root)
        arguments = dict(contract_id=args.contract_id)
        if args.acceptance_command == 'define':
            with args.checks_file.open('rb') as stream:
                raw = stream.read(262145)
            if len(raw) > 262144:
                raise AcceptanceError('invalid_argument', 'checks exceed bounded contract size')
            from .resource_claims import _unique
            checks = json.loads(raw, object_pairs_hook=_unique)
            arguments.update(task_id=args.task_id, assignment_id=args.assignment_id, checks=checks)
            task_id, assignment_id = args.task_id, args.assignment_id
        else:
            contract = owner.contract(args.contract_id)
            task_id, assignment_id = contract['task_id'], contract['pin']['assignment_id']
        if principal.role == 'operator':
            authority = BriefAuthority('operator:' + principal.subject, 'operator')
        else:
            from .permission_enforcement import verified_tasks
            tasks = verified_tasks(root, principal.subject, task_id, assignment_id,
                                   actor_id=getattr(args, 'permission_actor_id', None))
            principal = Principal(principal.subject, tasks=tasks)
            authority = BriefAuthority('native:' + principal.subject, 'worker', tasks)
        if args.acceptance_command == 'decide':
            arguments.update(name=args.name, outcome=args.outcome, expires_at=args.expires_at)
        claimant = None
        if args.acceptance_command == 'evaluate' and owner.contract(args.contract_id)['checks']['verifiers']:
            if not args.managed_agent_id:
                raise AcceptanceError('authority_denied', 'verifier execution requires its managed resource owner')
            from .managed_inventory_commands import RuntimeObserver
            claimant = qualified_claimant(root, args.managed_agent_id, principal,
                observer=RuntimeObserver(endpoint=args.app_server, socket_path=args.tmux_socket))
        value = execute(args.acceptance_command, arguments, root, principal=principal, authority=authority, claimant=claimant)
        emit(value, args)
        return 0
    except (WakeError, ValueError, KeyError, TypeError, OSError) as error:
        emit(dict(status='held', error=dict(code=getattr(error, 'code', 'acceptance_unavailable'),
            message=str(error) if isinstance(error, WakeError) else 'Acceptance request or evidence unavailable.')), args)
        return 2
