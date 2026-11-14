"""Exact-session native slash actions; slash text is never a model prompt.

The qualified Codex adapter maps /rename to thread/name/set and /status to
thread/read. Bare /rename uses a controller-owned text interaction, not a native
TUI popup. Unsupported native menus are advertised explicitly.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import hashlib
import json
from pathlib import Path

from .daemon_commands import local_operator
from .controller_runtime import encoded, identity
from .local_session_operations import LocalSessionControl
from .local_sessions import resolve
from .managed_inventory import InventoryError


CATALOG = (
    dict(command='/status', arguments='none', interactive=False,
         execution='native_rpc', method='thread/read'),
    dict(command='/rename', arguments='thread name verbatim; omit to request input',
         interactive=True, presentation='controller_interaction',
         execution='native_rpc', method='thread/name/set'),
)


def _invocation(command, arguments):
    if command not in {row['command'] for row in CATALOG}:
        raise InventoryError('unsupported_slash_command',
            'Supported native adapter commands are /status and /rename; no text was submitted to a model.')
    if not isinstance(arguments, str) or len(arguments.encode()) > 32768 or '\x00' in arguments:
        raise InventoryError('invalid_argument', 'bounded slash arguments required')
    if command == '/status' and arguments:
        raise InventoryError('invalid_argument', '/status takes no arguments')
    if command == '/rename' and arguments and not arguments.strip():
        raise InventoryError('invalid_argument', 'thread name cannot contain only whitespace')


class LocalSlashCommands(LocalSessionControl):
    """Use the existing owner journal, target pins and same-user authority."""

    def __init__(self, root, *, request=None, authorize=None):
        super().__init__(root, **({'request':request} if request is not None else {}))
        self.authorize_callback=authorize

    def _authorized(self, target, capability):
        if target.get('uid')!=os.getuid() or Path(target['home']).stat().st_uid!=os.getuid():
            raise InventoryError('foreign_target','slash target is not owned by this user')
        actor=(self.authorize_callback(target,capability) if self.authorize_callback is not None
               else local_operator(target,('control','observe','content.observe')))
        self.runtime.check_authority(actor,target,capability,
            authorize=(lambda:self.authorize_callback(target,capability)) if self.authorize_callback else None)
        return actor

    def _actor(self, identifier, capability='content.observe'):
        return self._authorized(self.runtime._load(identifier)['target'],capability)

    def _identifier(self, prefix, key, actor):
        source=key if self.authorize_callback is None else encoded([identity(actor),key])
        return prefix+hashlib.sha256(source.encode()).hexdigest()[:32]

    def catalog(self, selector, *, endpoint='unix://', expected_target=None):
        row = resolve(self.root, selector, expected_target, endpoint=endpoint)
        self._authorized(row['target'],'observe')
        return dict(schema_version=1, target=row['target'], harness='codex',
            catalog_source='qualified_native_adapter', complete_native_catalog=False,
            commands=list(CATALOG), unsupported=[dict(command='/model',
                reason='native_tui_picker_protocol_unavailable', effect_attempted=False)],
            prompt_fallback=False)

    def run(self, selector, command, arguments, key, *, endpoint='unix://', expected_target=None):
        _invocation(command, arguments)  # Refuse before operation admission or native effects.
        if not isinstance(key, str) or not 0 < len(key) <= 128:
            raise InventoryError('invalid_argument', 'bounded idempotency key required')
        row = resolve(self.root, selector, expected_target, endpoint=endpoint)
        row = {name: row[name] for name in ('thread_id', 'target', 'endpoint', 'codex_cmd')}
        actor = self._authorized(row['target'],'control')
        identifier = self._identifier('local-slash-',key,actor)
        request = dict(operation_id=identifier, idempotency_key=key,
            correlation_id=identifier, binding='local-slash', target=row['target'])
        def dispatch(operation, payload):
            current = self._current(payload['session'])
            if payload['command'] == '/rename' and not payload['arguments']:
                return dict(_pending=True, handle=dict(kind='controller_interaction',
                    interaction_id=identifier, command='/rename', state='input_required',
                    presentation='controller_interaction', native_popup=False,
                    input=dict(name='name', type='text', max_utf8_bytes=32768),
                    executed=False, completed=False, model_submission=False))
            return self._perform(current, payload['command'], payload['arguments'])
        value = self.runtime.execute(actor, 'sessions.slash',
            dict(session=row, command=command, arguments=arguments, _request=request),
            authorize=lambda:self._authorized(row['target'],'control'), dispatch=dispatch)
        record = value['result']['operation']
        if record.get('result', {}).get('kind') == 'controller_interaction':
            with self._interaction_lock(record['operation_id']):
                retained = self.runtime._load(record['operation_id'])
                if (retained['phase'] == 'waiting' and
                        retained.get('result', {}).get('state') == 'input_required'):
                    retained.update(execution='not_started', delivery='retained', acceptance='interaction_required')
                    self.runtime._save(retained)
                value = self.runtime.envelope('sessions.slash', retained)
        return value

    def _perform(self, row, command, arguments):
        thread = row['thread_id']
        if command == '/rename':
            self._request(row, 'thread/name/set', dict(threadId=thread, name=arguments))
        native = self._request(row, 'thread/read', dict(threadId=thread, includeTurns=False))['thread']
        if native.get('id') != thread:
            raise InventoryError('stale_target', 'native slash result belongs to another conversation')
        if command == '/rename' and native.get('name') != arguments:
            raise InventoryError('effect_unverified', 'native thread name does not match requested arguments')
        return dict(kind='native_slash_result', command=command, arguments=arguments,
            received=True, executed=True, completed=True, model_submission=False,
            native_method='thread/name/set' if command == '/rename' else 'thread/read',
            observation=dict(thread_id=thread, name=native.get('name'),
                cwd=native.get('cwd'), status=native.get('status'),
                model_provider=native.get('modelProvider')))

    @contextmanager
    def _interaction_lock(self, identifier):
        directory = Path(self.root) / 'controller-slash'
        directory.mkdir(mode=0o700, exist_ok=True)
        from .goal_supervision import _private
        _private(directory, True)
        path = directory / (hashlib.sha256(identifier.encode()).hexdigest() + '.lock')
        with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def result(self, operation_id):
        actor = self._actor(operation_id,'content.observe')
        with self._interaction_lock(operation_id):
            current=self.runtime._load(operation_id)
            guard=lambda:self._authorized(current['target'],'content.observe')
            record = self.runtime._owned(actor,current,guard,capability='content.observe')
            if record['operation'] not in ('sessions.slash', 'sessions.slash.response'):
                raise InventoryError('unsupported_operation', 'original operation is not a slash action')
            if record['phase'] != 'terminal' and (record.get('result') or {}).get('response_operation_id'):
                self._reconcile_response(actor,record,capability='content.observe')
                record=self.runtime._load(operation_id)
            self.runtime._owned(actor,record,guard,capability='content.observe')
            return self.runtime.envelope('operations.result',record)

    def _reconcile_response(self, actor, original, capability='control'):
        handle = original['result']
        response = self.runtime._load(handle['response_operation_id'])
        guard=lambda:self._authorized(original['target'],capability)
        self.runtime._owned(actor,response,guard,capability=capability)
        if response['execution'] == 'completed':
            proof = response['result']
        else:
            row = self._current(original['payload']['session'])
            native = self._request(row, 'thread/read', dict(threadId=row['thread_id'], includeTurns=False))['thread']
            if native.get('id') != row['thread_id'] or native.get('name') != handle['response_value']:
                return
            proof = dict(kind='native_slash_result', command='/rename',
                arguments=handle['response_value'], received=True, executed=True,
                completed=True, model_submission=False, native_method='thread/name/set',
                reconciliation='requested_native_name_observed_without_replay',
                observation=dict(thread_id=row['thread_id'], name=native['name']))
            self.runtime.reconcile_result(actor, response['operation_id'],
                expected_operation='sessions.slash.response', authorize=guard,
                observe=lambda _record: proof,capability=capability)
        proof = dict(proof, interaction_id=original['operation_id'],
            presentation='controller_interaction', native_popup=False,
            response_operation_id=response['operation_id'])
        self.runtime.reconcile_result(actor, original['operation_id'],
            expected_operation='sessions.slash', authorize=guard,
            observe=lambda _record: proof,capability=capability)

    def respond(self, interaction_id, value, idempotency_key):
        _invocation('/rename', value)
        if not value:
            raise InventoryError('invalid_argument', 'explicit nonempty interaction input required')
        actor = self._actor(interaction_id,'control')
        with self._interaction_lock(interaction_id):
            original = self.runtime._load(interaction_id)
            guard=lambda:self._authorized(original['target'],'control')
            self.runtime._owned(actor,original,guard,capability='control')
            if original['operation'] != 'sessions.slash' or original.get('result', {}).get('interaction_id') != interaction_id:
                raise InventoryError('interaction_not_found', 'exact owned slash interaction required')
            if original['phase'] == 'terminal':
                if original.get('execution') == 'completed' and original['result'].get('arguments') == value:
                    response = self.runtime._load(original['result']['response_operation_id'])
                    return self.runtime.envelope('sessions.slash.response', response)
                raise InventoryError('interaction_resolved', 'interaction was already completed or cancelled')
            row = original['payload']['session']
            self._current(row)  # A stale selection fails before response admission/effects.
            if not isinstance(idempotency_key, str) or not 0 < len(idempotency_key) <= 128:
                raise InventoryError('invalid_argument', 'bounded response idempotency key required')
            identifier = self._identifier('local-slash-response-',idempotency_key,actor)
            prior = original['result'].get('response_operation_id')
            if prior is not None and (prior != identifier or original['result'].get('response_value') != value):
                raise InventoryError('interaction_response_conflict', 'interaction already binds a different response; reconcile its original operation')
            original['result'].update(state='response_pending', response_operation_id=identifier, response_value=value, executed=None)
            original.update(execution='unknown', delivery='uncertain', acceptance='response_pending')
            self.runtime._save(original)
            request = dict(operation_id=identifier, idempotency_key=idempotency_key,
                correlation_id=original['correlation_id'], binding='local-slash', target=original['target'])
            response = self.runtime.execute(actor, 'sessions.slash.response',
                dict(session=row, interaction_id=interaction_id, value=value, _request=request),
                authorize=guard,
                dispatch=lambda _operation, payload: self._perform(self._current(payload['session']), '/rename', payload['value']))
            result = response['result']['operation']
            if result['execution'] == 'completed':
                self._reconcile_response(actor, original)
            return response

    def cancel(self, interaction_id):
        actor = self._actor(interaction_id,'control')
        with self._interaction_lock(interaction_id):
            original = self.runtime._load(interaction_id)
            guard=lambda:self._authorized(original['target'],'control')
            self.runtime._owned(actor,original,guard,capability='control')
            if original['operation'] != 'sessions.slash' or original.get('result', {}).get('interaction_id') != interaction_id:
                raise InventoryError('interaction_not_found', 'exact owned slash interaction required')
            if original['phase'] != 'terminal' and original['result'].get('response_operation_id'):
                raise InventoryError('interaction_response_pending', 'a response may have executed; reconcile its native outcome before cancellation')
            if original['phase'] != 'terminal':
                original.update(phase='terminal', execution='cancelled', delivery='retained',
                    acceptance='controller_observed', cancellation='confirmed', reason=None)
                original['result'].update(state='cancelled', executed=False, completed=False)
                self.runtime._save(original)
                self.runtime._event(original, 'interaction_cancelled',
                    dict(kind='interaction_cancelled', operation_id=interaction_id, native_effect=False))
            return self.runtime.envelope('sessions.slash', original)


def _execute(root, verb, arguments):
    """CLI/API/MCP hook; transport identity must already be qualified as local."""
    if not isinstance(arguments, dict):
        raise InventoryError('invalid_argument', 'object slash arguments required')
    owner = LocalSlashCommands(root)
    if verb == 'list':
        allowed = {'selector', 'endpoint', 'expected_target'}
        if set(arguments) - allowed or 'selector' not in arguments:
            raise InventoryError('invalid_argument', 'exact slash discovery arguments required')
        return owner.catalog(**arguments)
    if verb == 'run':
        allowed = {'selector', 'command', 'arguments', 'idempotency_key', 'endpoint', 'expected_target'}
        if set(arguments) - allowed or not {'selector', 'command', 'idempotency_key'} <= set(arguments):
            raise InventoryError('invalid_argument', 'exact slash invocation arguments required')
        inputs = dict(arguments)
        key = inputs.pop('idempotency_key')
        return owner.run(key=key, **dict(inputs, arguments=inputs.get('arguments', '')))
    if verb in ('result', 'cancel'):
        field = 'operation_id' if verb == 'result' else 'interaction_id'
        if set(arguments) != {field}:
            raise InventoryError('invalid_argument', 'exact retained operation handle required')
        return getattr(owner, verb)(arguments[field])
    if verb == 'respond':
        if set(arguments) != {'interaction_id', 'value', 'idempotency_key'}:
            raise InventoryError('invalid_argument', 'exact interaction response required')
        return owner.respond(**arguments)
    raise InventoryError('unsupported_operation', 'unsupported slash operation')


def execute(root, verb, arguments):
    """Return the owner envelope or the shared requested receipt presentation."""
    if not isinstance(arguments, dict):
        raise InventoryError('invalid_argument', 'object slash arguments required')
    arguments = dict(arguments)
    mode = arguments.pop('mode', None)
    cursor = arguments.pop('cursor', 0)
    if mode is not None and mode not in ('stream', 'transcript', 'final', 'silent'):
        raise InventoryError('invalid_argument', 'supported slash output mode required')
    if type(cursor) is not int or not 0 <= cursor <= 1:
        raise InventoryError('invalid_cursor', 'native command receipt cursor must be zero or one')
    formatter = None
    if mode is not None and verb != 'list':
        # Resolve the presentation owner before any native action is admitted.
        from .local_control_commands import receipt_output
        formatter = receipt_output
    value = _execute(root, verb, arguments)
    if formatter is not None:
        return formatter(value, mode=mode, cursor=cursor)
    return value


def register(subparsers):
    parser = subparsers.add_parser('slash', help='execute supported native slash actions')
    verbs = parser.add_subparsers(dest='slash_verb', required=True)
    for verb in ('list', 'run', 'result', 'respond', 'cancel'):
        item = verbs.add_parser(verb)
        if verb != 'list':
            item.add_argument('--mode', choices=('stream', 'transcript', 'final', 'silent'), default='final')
        if verb == 'result':
            item.add_argument('--cursor', type=int, default=0)
        if verb in ('list', 'run'):
            from .local_control_routing import parser_options
            parser_options(item)
            item.add_argument('selector')
        elif verb == 'result':
            item.add_argument('operation_id')
        else:
            item.add_argument('interaction_id')
        if verb == 'respond':
            item.add_argument('value')
            item.add_argument('--idempotency-key', required=True)
        if verb in ('list', 'run'):
            item.add_argument('--endpoint', default='unix://')
            item.add_argument('--expected-target', type=json.loads)
        if verb == 'run':
            item.add_argument('slash_command', metavar='command')
            item.add_argument('--arguments', default='')
            item.add_argument('--idempotency-key', required=True)
    return parser


def tool_specs():
    text = dict(type='string', minLength=1)
    from .local_control_routing import HARNESS_PROPERTIES
    common = dict(selector=text, endpoint=text, expected_target=dict(type='object'),**HARNESS_PROPERTIES)
    result = {
        'wake_control_slash_list': ('local-slash', 'list',
            'Discover qualified same-user native slash mappings and interaction support.',
            common, ['selector'], True),
        'wake_control_slash_run': ('local-slash', 'run',
            'Execute a supported native slash action with durable tracking; never submits command text as a prompt.',
            dict(common, command=text, arguments=dict(type='string'), idempotency_key=text,
                mode=dict(type='string', enum=['stream','transcript','final','silent'])),
            ['selector', 'command', 'idempotency_key'], False),
    }
    for verb in ('result', 'respond', 'cancel'):
        field = 'operation_id' if verb == 'result' else 'interaction_id'
        properties = {field: text, 'mode': dict(type='string', enum=['stream','transcript','final','silent'])}
        required = [field]
        if verb == 'result':
            properties['cursor'] = dict(type='integer', minimum=0, maximum=1)
        if verb == 'respond':
            properties.update(value=text, idempotency_key=text)
            required.extend(['value','idempotency_key'])
        result['wake_control_slash_'+verb] = ('local-slash', verb,
            'Inspect, explicitly answer, or cancel an exact controller-owned native slash interaction.',
            properties, required, verb == 'result')
    return result
