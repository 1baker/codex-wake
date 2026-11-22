"""Operator CLI for explicit recurring schedules."""
import json
from pathlib import Path
from .records import WakeError
from .recurring_schedules import ScheduleStore


def register_parser(subparsers):
    group = subparsers.add_parser('schedules', help='explicit durable recurring schedules')
    verbs = group.add_subparsers(dest='schedule_command', required=True)
    p = verbs.add_parser('register')
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--codex-path', default='codex')
    p.add_argument('--endpoint', default='unix://')
    p = verbs.add_parser('show'); p.add_argument('schedule_id')
    p = verbs.add_parser('revise'); p.add_argument('schedule_id'); p.add_argument('--request', type=Path, required=True); p.add_argument('--expected-revision',type=int,required=True); p.add_argument('--codex-path',default='codex'); p.add_argument('--endpoint',default='unix://')
    p = verbs.add_parser('cancel'); p.add_argument('schedule_id'); p.add_argument('--expected-revision',type=int,required=True)
    verbs.add_parser('list')
    p = verbs.add_parser('bind-restoration', help='pin an exact saved-conversation restoration profile')
    p.add_argument('schedule_id')
    p.add_argument('--profiles', type=Path, required=True)
    p.add_argument('--managed-agent-id', required=True)
    p.add_argument('--profile', required=True)
    for parser in verbs.choices.values():
        parser.add_argument('--bus-root', type=Path)
        parser.add_argument('--operator-capability', type=Path)
        parser.add_argument('--actor-capability', type=Path)
        parser.add_argument('--actor-runtime', default='codex')
        parser.add_argument('--app-server', default='unix://')


def command(args, root):
    store = ScheduleStore(root)
    principal = getattr(args, '_permission_principal', None)
    from .session_permissions import PermissionStore
    if principal is None and (PermissionStore(root).active() or args.schedule_command == 'bind-restoration'):
        from .permission_commands import verified_cli_principal
        principal = verified_cli_principal(args)
    if args.schedule_command == 'bind-restoration':
        value = store.bind_restoration(args.schedule_id, profiles=args.profiles,
            managed_agent_id=args.managed_agent_id, profile=args.profile, principal=principal)
    elif args.schedule_command == 'revise':
        if args.request.stat().st_size > 65536: raise WakeError('schedule_request_too_large')
        value = store.revise(args.schedule_id, json.loads(args.request.read_text()), args.expected_revision, principal=principal, codex_path=args.codex_path, endpoint=args.endpoint)
    elif args.schedule_command == 'cancel':
        value = store.cancel(args.schedule_id, args.expected_revision, principal=principal)
    elif args.schedule_command == 'register':
        if args.request.stat().st_size > 65536:
            raise WakeError('schedule_request_too_large')
        request = json.loads(args.request.read_text())
        value = store.register(request, codex_path=args.codex_path, endpoint=args.endpoint, principal=principal)
    elif args.schedule_command == 'show':
        value = store.read(args.schedule_id)
        store.authorize(value, principal)
        value = store.receipt(value)
    else:
        values = []
        for item in store.records():
            try:
                store.authorize(item, principal)
                values.append(store.receipt(item))
            except WakeError:
                continue
        value = values
    print(json.dumps(value, sort_keys=True))
    return 0
