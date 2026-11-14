"""Flow command/schema adapter; definitions never supply executable host code."""
from pathlib import Path
import json

from .cli_output import emit
import os
import socket

from .controller_flows import ControllerFlows
from .managed_inventory import InventoryError


def owner(root, *, actor, authorize, dispatch):
    if root is None:
        raise InventoryError('host_wake_root_required', 'host Wake root required')
    def invoke(operation, arguments, *, authorize, request=None):
        from .controller_http import TOOLS
        from .unified_contract import original
        operation = original(operation, {verb for verb,schema in TOOLS.values()})
        schemas = [schema for name, (verb, schema) in TOOLS.items() if verb == operation]
        if not schemas or operation.startswith('flows.'):
            raise InventoryError('unsupported_flow_operation', 'flow child must be a registered non-flow operation')
        arguments = dict(arguments)
        if '_request' in schemas[0].get('properties', {}):
            arguments['_request'] = request
        return dispatch(operation, arguments, authorize)
    return ControllerFlows(Path(root), host=socket.gethostname(),
        environment=os.environ.get('WSL_DISTRO_NAME') or os.name,
        invoke=invoke, authorize=authorize)


def execute(flows, actor, operation, arguments):
    allowed = {
        'flows.propose': {'definition'}, 'flows.publish': {'definition'},
        'flows.definition': {'flow_id', 'version'},
        'flows.start': {'flow_id', 'version', 'inputs', 'intent', 'binding'},
        'flows.inspect': {'run_id'}, 'flows.advance': {'run_id'},
        'flows.reconcile': {'run_id'}, 'flows.cancel': {'run_id'}}
    if operation not in allowed or not isinstance(arguments, dict) or set(arguments) != allowed[operation]:
        raise InventoryError('invalid_argument', 'exact structured flow arguments required')
    verb = operation.split('.')[1]
    if verb in ('propose', 'publish'):
        result = getattr(flows, verb)(actor, arguments['definition'])
    elif verb == 'definition':
        result = flows.definition(actor, arguments['flow_id'], arguments['version'])
    elif verb == 'start':
        result = flows.start(actor, arguments['flow_id'], arguments['version'],
            **{key: arguments[key] for key in ('inputs', 'intent', 'binding')})
    else:
        result = getattr(flows, verb)(actor, arguments['run_id'])
    return dict(schema_version=1, operation=operation, status='completed', result=result)


def tool_specs():
    text = {'type': 'string', 'minLength': 1, 'maxLength': 200}
    specs = {}
    for verb in ('propose', 'publish', 'definition', 'start', 'inspect', 'advance', 'reconcile', 'cancel'):
        if verb in ('propose', 'publish'):
            properties = {'definition': {'type': 'object'}}
        elif verb in ('definition', 'start'):
            properties = {'flow_id': text, 'version': {'type': 'integer', 'minimum': 1}}
            if verb == 'start':
                properties.update(inputs={'type': 'object'}, intent=text, binding=text)
        else:
            properties = {'run_id': text}
        specs['wake_flows_' + verb] = ('controller-flows', 'flows.' + verb,
            'Use pinned structured flow state under the current caller grant; no new allowance or automatic effect replay.',
            properties, list(properties), verb in ('propose', 'definition', 'inspect'))
    return specs


def register_parser(subparsers):
    parser = subparsers.add_parser('flows', help='publish and run pinned durable structured flows')
    verbs = parser.add_subparsers(dest='flow_verb', required=True)
    for name, spec in tool_specs().items():
        item = verbs.add_parser(spec[1].split('.')[1])
        item.add_argument('--json', dest='as_json', action='store_true')
        item.add_argument('--arguments', type=json.loads, required=True)
    return parser


def protected_execute(operation, arguments, root, *, authority=None, protected_type=None):
    from types import SimpleNamespace
    from .operation_commands import local_actor
    from .controller_http import ProtectedOperations
    from .controller_operations import ControllerOperations
    from .managed_inventory import ManagedInventory
    authority = authority or SimpleNamespace(authenticate=lambda unused: local_actor(root))
    operations = ControllerOperations(ManagedInventory(root), host=socket.gethostname(),
        environment=os.environ.get('WSL_DISTRO_NAME') or os.name)
    return (protected_type or ProtectedOperations)(authority, operations).execute('host-local-grant', operation, arguments)


def command(args, root):
    result = protected_execute('flows.' + args.flow_verb, args.arguments, root)
    emit(result, args)
    return 0 if result['status'] == 'completed' else 2


def mcp_call(runner, operation, arguments, native_context):
    from types import SimpleNamespace
    from .controller_auth import Actor
    from .controller_http import ProtectedOperations
    from .controller_mailbox import ControllerMailbox
    from .goal_supervision import verified_native_caller
    caller = arguments.get('caller_thread_id')
    def authenticated(unused):
        verified_native_caller(native_context, caller)
        config = ControllerMailbox(runner.wake_root).config()
        value = config.get('flow_callers', {}).get(caller)
        if not isinstance(value, dict):
            raise InventoryError('unauthorized_target', 'native flow caller requires its own host-approved grant')
        return Actor(value['subject'], 'service', value['client_id'], value['grant_id'],
            value['issuer'], value['resource'], frozenset(value['scopes']), value['targets'], value['expires_at'])
    class NativeOperations(ProtectedOperations):
        def execute(self, token, operation, arguments):
            if operation == 'operations.send':
                config = ControllerMailbox(runner.wake_root).config()
                if arguments.get('backend', 'mailbox') == 'job':
                    mapping = config.get('job_bindings', {}).get(arguments.get('sender_binding'), {})
                    claimed = mapping.get('native_thread_id', mapping.get('native_subject'))
                else:
                    mapping = config.get('bindings', {}).get(arguments.get('sender_binding'), {})
                    claimed = mapping.get('identity', {}).get('thread_id')
                if claimed != caller:
                    raise InventoryError('native_caller_unverified', 'flow child sender differs from invoking native session')
                verified_native_caller(native_context, claimed)
            return super().execute(token, operation, arguments)
    return protected_execute(operation, {key: value for key, value in arguments.items() if key != 'caller_thread_id'},
        runner.wake_root, authority=SimpleNamespace(authenticate=authenticated), protected_type=NativeOperations)
