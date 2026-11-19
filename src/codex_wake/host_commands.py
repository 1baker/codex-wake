"""Host registry/SSH CLI adapter; caller identity never comes from SSH payloads."""
from __future__ import annotations

import json

from .cli_output import emit
from pathlib import Path
import sys

import time

from .controller_hosts import HostOperations, HostRegistry, SSHReceiver
from .controller_operations import ControllerOperations
from .managed_inventory import InventoryError, ManagedInventory


def owner(root, *, local_operator=False):
    if root is None: raise InventoryError('host_wake_root_required', 'host Wake root required')
    return HostOperations(HostRegistry(Path(root) / 'controller-hosts' / 'registry.sqlite'), local_operator=local_operator)


def register_parser(subparsers):
    hosts = subparsers.add_parser('hosts', help='registered host/environment authorities and pinned SSH routes')
    commands = hosts.add_subparsers(dest='host_verb', required=True)
    commands.add_parser('list')
    resolve = commands.add_parser('resolve')
    resolve.add_argument('host'); resolve.add_argument('environment')
    resolve.add_argument('--expected-target', type=json.loads)
    register = commands.add_parser('register')
    register.add_argument('host'); register.add_argument('environment')
    register.add_argument('--kind', choices=['windows', 'wsl', 'linux', 'remote'], required=True)
    register.add_argument('--authority', required=True)
    register.add_argument('--destination', required=True)
    register.add_argument('--command', dest='ssh_command', default='codex-wake hosts ssh-serve')
    register.add_argument('--ssh-executable', default='ssh', help='local operator-controlled transport executable; fixture paths must be labeled')
    register.add_argument('--generation', help='exact generation exported by destination registration')
    register.add_argument('--capability', action='append')
    observe = commands.add_parser('observe')
    observe.add_argument('--target', type=json.loads, required=True)
    observe.add_argument('--online', choices=['true', 'false'], required=True)
    mapping = commands.add_parser('map-principal')
    mapping.add_argument('principal_id'); mapping.add_argument('--subject', required=True)
    mapping.add_argument('--scope', action='append', required=True)
    mapping.add_argument('--targets', type=json.loads, required=True)
    mapping.add_argument('--expires-at', type=float, required=True)
    revoke = commands.add_parser('revoke-principal'); revoke.add_argument('principal_id')
    route = commands.add_parser('route')
    route.add_argument('--target', type=json.loads, required=True)
    route.add_argument('--operation', required=True)
    route.add_argument('--arguments', type=json.loads, default={})
    route.add_argument('--operation-id', required=True); route.add_argument('--idempotency-key', required=True)
    for item in commands.choices.values():
        item.add_argument('--json', dest='as_json', action='store_true')
    receiver = commands.add_parser('ssh-serve', help='fixed sshd forced-command receiver, one bounded JSON frame')
    receiver.add_argument('--principal-id', required=True)
    receiver.add_argument('--target', type=json.loads, required=True)


def bounded_stdin():
    import os
    import selectors
    chunks = bytearray()
    # Protective I/O wait only; permission and lease expiry belong to the receiver.
    deadline = time.monotonic() + 5
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin.buffer, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise InventoryError('invalid_argument', 'SSH frame input deadline exceeded')
            if not selector.select(remaining): continue
            if time.monotonic() >= deadline: raise InventoryError('invalid_argument', 'SSH frame input deadline exceeded')
            chunk = os.read(sys.stdin.fileno(), 4096)
            if time.monotonic() >= deadline: raise InventoryError('invalid_argument', 'SSH frame input deadline exceeded')
            if not chunk: break
            chunks.extend(chunk)
            if len(chunks) > 65536: raise InventoryError('invalid_argument', 'SSH frame exceeds 65536 bytes')
    value = json.loads(chunks)
    if not isinstance(value, dict): raise InventoryError('invalid_argument', 'SSH frame must be an object')
    if time.monotonic() >= deadline: raise InventoryError('invalid_argument', 'SSH frame input deadline exceeded')
    return value


def command(args, root=None):
    root = root or args.wake_root
    operation = 'hosts.' + args.host_verb
    try:
        service = owner(root, local_operator=True)
        registry = service.registry
        verb = args.host_verb
        if verb == 'register':
            options = dict(kind=args.kind, authority=args.authority, destination=args.destination, command=args.ssh_command,
                ssh_executable=args.ssh_executable, generation=args.generation, operator=True)
            if args.capability: options['capabilities'] = args.capability
            value = {'environment': registry.register(args.host, args.environment, **options)}
        elif verb == 'observe': value = {'environment': registry.observe(args.target, online=args.online == 'true', operator=True)}
        elif verb == 'map-principal':
            value = registry.map_principal(args.principal_id, subject=args.subject, scopes=args.scope, targets=args.targets, expires_at=args.expires_at, operator=True)
        elif verb == 'revoke-principal': value = registry.revoke_principal(args.principal_id, operator=True)
        elif verb == 'ssh-serve':
            options = {}
            account_config = Path(root) / 'controller-accounts.toml'
            if account_config.is_file():
                from .controller_accounts import ControllerAccounts
                options['accounts'] = ControllerAccounts(account_config, host=args.target['host'], environment=args.target['environment'])
            local = ControllerOperations(ManagedInventory(Path(root)), host=args.target['host'], environment=args.target['environment'], **options)
            receiver = SSHReceiver(registry, local, principal_id=args.principal_id, target=args.target)
            request = bounded_stdin()
            operation = request.get('operation', operation)
            result = receiver.execute(request)
            print(json.dumps(result, sort_keys=True)); return 0
        else:
            arguments = {} if verb == 'list' else ({'host': args.host, 'environment': args.environment} if verb == 'resolve' else
                dict(target=args.target, operation=args.operation, arguments=args.arguments, operation_id=args.operation_id, idempotency_key=args.idempotency_key))
            if verb == 'resolve' and args.expected_target is not None: arguments['expected_target'] = args.expected_target
            value = service.execute(operation, arguments)
        result = dict(schema_version=1, operation=operation, status='completed', result=value)
    except (ValueError, OSError, KeyError) as error:
        result = dict(schema_version=1, operation=operation, status='failed', error=dict(code=getattr(error, 'code', 'invalid_argument'), message=str(error)))
    if args.host_verb == 'ssh-serve':
        print(json.dumps(result, sort_keys=True))
    else:
        emit(result, args)
    return 0 if result['status'] == 'completed' else 2


def main(argv=None):
    """Module entrypoint permits installed acceptance before shared CLI registration."""
    import argparse
    parser = argparse.ArgumentParser(prog='codex-wake hosts')
    parser.add_argument('--wake-root', type=Path, required=True)
    subparsers = parser.add_subparsers(dest='command', required=True)
    register_parser(subparsers)
    return command(parser.parse_args(argv))


if __name__ == '__main__': raise SystemExit(main())
