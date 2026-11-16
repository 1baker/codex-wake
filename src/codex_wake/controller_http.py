"""OAuth resource and stateless JSON MCP transport over common controller reads.

The listener is loopback only; TLS ingress is a separate deployment boundary.
No identity headers are trusted. Every request verifies the current grant.
"""
from __future__ import annotations

import html
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from .controller_auth import AuthError, SCOPES
from .managed_inventory import InventoryError
from .tab_views import TabViews

TOOLS = {
    'wake_builds_list': ('builds.list', {'type': 'object', 'properties': {'account': {'type': 'string'}}, 'required': ['account'], 'additionalProperties': False}),
    'wake_controller_list': ('inventory.list', {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'additionalProperties': False}),
    'wake_controller_accounts': ('accounts.list', {'type': 'object', 'properties': {}, 'additionalProperties': False}),
    'wake_controller_account_resolve': ('accounts.resolve', {'type': 'object', 'properties': {'selector': {'type': 'string'}, 'expected_target': {'type': 'object'}}, 'required': ['selector'], 'additionalProperties': False}),
    'wake_controller_configuration': ('configuration.explain', {'type': 'object', 'properties': {'selector': {'type': 'string'}, 'expected_target': {'type': 'object'}}, 'required': ['selector'], 'additionalProperties': False}),
    'wake_controller_resolve': ('inventory.resolve', {'type': 'object', 'properties': {'selector': {'type': 'string'}, 'expected_target': {'type': 'object'}}, 'required': ['selector'], 'additionalProperties': False}),
}


from .grok_provider_auth import tool_specs as grok_auth_specs
for name, spec in grok_auth_specs().items():
    TOOLS[name] = (spec[1], dict(type='object', properties=spec[3], required=spec[4], additionalProperties=False))

from .grok_model_catalog import tool_specs as grok_model_specs
for name, spec in grok_model_specs().items():
    TOOLS[name] = (spec[1], dict(type='object', properties=spec[3], required=spec[4], additionalProperties=False))

from .account_observation import tool_specs as account_observation_specs
for name, spec in account_observation_specs().items():
    TOOLS[name] = (spec[1], {'type': 'object', 'properties': spec[3], 'required': spec[4], 'additionalProperties': False})

# Native-MCP caller identity is not part of the OAuth-MCP argument schema.
from .history_commands import tool_specs as history_specs
for name, spec in history_specs().items():
    properties = {key: value for key, value in spec[3].items() if key != 'caller_thread_id'}
    TOOLS[name] = ('history.' + spec[1], {'type': 'object', 'properties': properties,
        'required': [key for key in spec[4] if key != 'caller_thread_id'], 'additionalProperties': False})
from .migration_commands import tool_specs as migration_specs
for name, spec in migration_specs().items():
    TOOLS[name] = (spec[1], {'type': 'object', 'properties': spec[3],
        'required': spec[4], 'additionalProperties': False})
from .tab_commands import tool_specs as tab_specs
for name, spec in tab_specs().items():
    TOOLS[name] = (spec[1], {'type':'object','properties':spec[3],'required':spec[4],'additionalProperties':False})
TOOLS.update({
    'wake_hosts_list': ('hosts.list', {'type': 'object', 'properties': {}, 'additionalProperties': False}),
    'wake_hosts_resolve': ('hosts.resolve', {'type': 'object', 'properties': {'host': {'type': 'string'}, 'environment': {'type': 'string'}, 'expected_target': {'type': 'object'}}, 'required': ['host', 'environment'], 'additionalProperties': False}),
    'wake_hosts_route': ('hosts.route', {'type': 'object', 'properties': {'target': {'type': 'object'}, 'operation': {'type': 'string'}, 'arguments': {'type': 'object'}, 'operation_id': {'type': 'string'}, 'idempotency_key': {'type': 'string'}}, 'required': ['target', 'operation', 'arguments', 'operation_id', 'idempotency_key'], 'additionalProperties': False}),
})


for verb in ('launch', 'stage', 'select', 'rollback'):
    properties = {'_request': {'type': 'object'}}
    if verb == 'stage':
        properties['recipe'] = {'type': 'string'}
        required = ['recipe', '_request']
    else:
        properties.update(account={'type': 'string'}, channel={'enum': ['stock', 'modded']}, expected_target={'type': 'object'})
        required = ['account', 'channel', 'expected_target', '_request']
        if verb == 'launch': properties['args'] = {'type': 'array', 'items': {'type': 'string'}}
        if verb == 'select':
            properties['identifier'] = {'type': 'string'}
            required.append('identifier')
    TOOLS['wake_builds_' + verb] = ('builds.' + verb, {'type': 'object', 'properties': properties,
        'required': required, 'additionalProperties': False})


for verb in ('send', 'result', 'wait', 'stream', 'cancel', 'rebind'):
    if verb == 'send':
        properties = {'_request': {'type': 'object'}, 'sender_binding': {'type': 'string'},
            'expected_target': {'type': 'object'}, 'backend': {'enum': ['mailbox', 'job']},
            'body': {'type': 'string', 'maxLength': 32768}, 'delivery': {'enum': ['inbox', 'notify']},
            'queue': {'type': 'boolean'}, 'ttl': {'type': 'number'}, 'job_profile': {'type': 'string'},
            'response_requested': {'type': 'boolean'}, 'wait_timeout': {'type': 'number', 'minimum': 0, 'maximum': 30}}
        required = ['_request', 'sender_binding', 'expected_target']
    else:
        properties = {'operation_id': {'type': 'string'}}
        required = ['operation_id']
        if verb in ('wait', 'stream'): properties['timeout'] = {'type': 'number', 'minimum': 0, 'maximum': 30}
        if verb == 'stream': properties.update(cursor={'type': 'integer', 'minimum': 0}, limit={'type': 'integer', 'minimum': 1, 'maximum': 100})
        if verb == 'rebind':
            properties.update(successor={'type': 'object'}, binding={'type': 'string'})
            required += ['successor', 'binding']
    TOOLS['wake_operations_' + verb] = ('operations.' + verb, {'type': 'object', 'properties': properties,
        'required': required, 'additionalProperties': False})


from .flow_commands import tool_specs as flow_specs
for name, spec in flow_specs().items():
    TOOLS[name] = (spec[1], {'type': 'object', 'properties': spec[3],
        'required': spec[4], 'additionalProperties': False})


from .flow_session_commands import tool_specs as flow_session_specs
for name, spec in flow_session_specs().items():
    TOOLS[name] = (spec[1], {'type': 'object', 'properties': spec[3], 'required': spec[4], 'additionalProperties': False})

from .health_commands import INPUT_SCHEMA as health_schema
TOOLS['wake_controller_health'] = ('health.observe', health_schema)
from .notice_commands import tool_specs as notice_specs
for name, spec in notice_specs().items():
    TOOLS[name] = (spec[1], dict(type='object',properties=spec[3],required=spec[4],additionalProperties=False))
from .recovery_commands import tool_specs as recovery_specs
for name, spec in recovery_specs().items():
    TOOLS[name] = (spec[1], dict(type='object',properties=spec[3],required=spec[4],additionalProperties=False))
from .grok_commands import tool_specs as grok_specs
for name, spec in grok_specs().items():
    TOOLS[name] = (spec[1], dict(type='object',properties=spec[3],required=spec[4],additionalProperties=False))


from .account_management import tool_specs as account_management_specs
from .history_commands import import_tool_specs
for name, spec in {**account_management_specs(), **import_tool_specs()}.items():
    TOOLS[name] = (spec[1], dict(type="object", properties=spec[3], required=spec[4], additionalProperties=False))

from .daemon_commands import tool_specs as daemon_specs
for name, spec in daemon_specs().items():
    TOOLS[name] = (spec[1], dict(type='object', properties=spec[3], required=spec[4], additionalProperties=False))


from .command_contract import public_tools, describe as describe_operation
TOOLS.update(public_tools())

def operation_failure(operation, error):
    return {'schema_version': 1, 'operation': operation, 'status': 'failed',
            'error': {'code': error.code, 'message': str(error)}}


def permitted(actor, target):
    return any(all(target.get(key) == value for key, value in scope.items()) for scope in actor.targets)


from .governor_commands import schemas as governor_schemas
TOOLS.update({'wake_governor_' + verb: ('governor.' + verb, schema) for verb, schema in governor_schemas().items()})


from .unified_connectors import protected_operations
PROTECTED_ADAPTERS=protected_operations()
from .unified_wakes import protected_operations as protected_wake_operations
PROTECTED_ADAPTERS.update(protected_wake_operations())
from .unified_terminal import protected_operations as protected_terminal_operations
PROTECTED_ADAPTERS.update(protected_terminal_operations())
from .unified_session_input import protected_operations as protected_input_operations
from .unified_session_presentation import protected_operations as protected_presentation_operations
PROTECTED_ADAPTERS.update(protected_input_operations())
PROTECTED_ADAPTERS.update(protected_presentation_operations())
from .unified_bulk import protected_operations as protected_bulk_operations
PROTECTED_ADAPTERS.update(protected_bulk_operations())
TOOLS.update({tool:(operation,schema) for operation,(tool,schema,required,handler) in PROTECTED_ADAPTERS.items()})
from .unified_contract import api_aliases
api_aliases(TOOLS)


class ProtectedOperations:
    """Shared API/MCP admission. Binding and client registration confer no grant."""
    # operation: (capability, list collection or None, singleton key).
    # Account/config reads require their own capabilities and an exact account
    # identity grant; inventory observe never authorizes reading native config.
    READ_POLICIES = {
        'grok_auth.status': ('account.observe', None, None),
        'grok_auth.revoke': ('account.revoke', None, None),
        'grok_models.list': ('account.observe', None, None),
        'grok_models.resolve': ('account.observe', None, None),
        **{'sessions.' + verb: ('observe' if verb in ('capabilities','wait','checkpoint') else 'control', None, None)
            for verb in ('capabilities','create','prompt','wait','cancel','checkpoint','fork')},
        'health.observe': ('observe', None, None),
        **{'grok.'+verb: ('observe' if verb in ('capabilities','wait','health','checkpoint') else 'control',None,None)
            for verb in ('capabilities','create','load','prompt','wait','cancel','health','checkpoint','fork')},
        **{'recovery.'+verb: ('observe' if verb in ('list','show','check') else 'recovery',None,None)
            for verb in ('list','show','configure','enable','disable','check','tick','apply','reconcile')},
        **{'notices.'+verb: ('observe',None,None)
            for verb in ('list','publish','reconcile')},
        **{'tabs.'+verb: ('observe' if verb in ('list','show') else 'control', 'resources' if verb in ('list','show') else None, None) for verb in ('list','show','preview','apply','undo','capture','input','create','rename','focus','move','park','restore','close')},
        **{'flows.' + verb: ('observe' if verb in ('propose', 'definition', 'inspect') else 'control', None, None)
            for verb in ('propose', 'publish', 'definition', 'start', 'inspect', 'advance', 'reconcile', 'cancel')},
        'migration.preview': ('migration.observe', None, None),
        'migration.apply': ('admin', None, None),
        'migration.rollback': ('admin', None, None),
        'operations.send': ('control', None, None),
        'operations.result': ('observe', None, None),
        'operations.wait': ('observe', None, None),
        'operations.stream': ('observe', None, None),
        'operations.cancel': ('control', None, None),
        'operations.rebind': ('control', None, None),
        'hosts.list': ('observe', 'environments', None),
        'hosts.resolve': ('observe', None, 'environment'),
        'hosts.route': ('observe', None, None),
        **{'daemons.' + verb: ('observe' if verb in ('list', 'status') else 'control', None, None)
           for verb in ('list', 'status', 'start', 'restart', 'update', 'stop')},
        'history.search': ('history.observe', None, None),
        'history.read': ('history.observe', None, None),
        'history.resume': ('history.resume', None, None),
        'builds.launch': ('control', None, None),
        'builds.stage': ('admin', None, None),
        'builds.select': ('admin', None, None),
        'builds.rollback': ('admin', None, None),
        'builds.list': ('account.observe', 'builds', None),
        'inventory.list': ('observe', 'resources', None),
        'inventory.resolve': ('observe', None, 'resource'),
        'accounts.init': ('admin', None, None),
        'accounts.create': ('admin', None, None),
        'history.import': ('control', None, None),
        'stores.register': ('admin', None, None),
        'stores.resolve': ('account.observe', None, None),
        'stores.list': ('account.observe', None, None),
        'configuration.sync.preview': ('configuration.observe', None, None),
        'configuration.sync.apply': ('control', None, None),
        'accounts.readiness': ('account.observe', None, None),
        'accounts.status': ('account.observe', None, None),
        'accounts.list': ('account.observe', 'accounts', None),
        'accounts.resolve': ('account.observe', None, 'account'),
        'configuration.explain': ('configuration.observe', None, 'account'),
    }

    from .bot_family_contract import specs as _family_specs
    READ_POLICIES.update({spec[1]:('observe' if spec[5] else 'control',None,None) for spec in _family_specs().values()})
    from .terminal_session_contract import specs as _session_specs
    READ_POLICIES.update({spec[1]:('observe' if spec[5] else 'control',None,None) for spec in _session_specs().values()})
    READ_POLICIES.update({'tabs.format.'+v:('observe' if v in ('status','inspect') else 'control',None,None) for v in ('status','inspect','enable','pause','resume','rollback','reenable','reset','configure')})
    READ_POLICIES.update({'tabs.monitor.'+v:('observe' if v in ('status','refresh') else 'control',None,None) for v in ('start','status','refresh','stop')})
    READ_POLICIES.update({'tabs.policy.'+v:('observe' if v=='status' else 'control',None,None) for v in ('configure','status','enable','pause','disable','tick')})
    READ_POLICIES.update({'tabs.reattach-'+v:('observe' if v=='status' else 'control',None,None) for v in ('preview','apply','status')})
    READ_POLICIES.update({'tabs.recovery.'+v:('observe' if v in ('preview','status') else 'control',None,None) for v in ('capture','preview','apply','status')})
    READ_POLICIES.update(dict.fromkeys(TabViews.READS,('observe',None,None)))
    READ_POLICIES.update(dict.fromkeys(TabViews.MUTATIONS,('control',None,None)))

    READ_POLICIES.update({'builds.' + verb: ('admin', None, None) for verb in ('prepare','status','build','resume','qualify','cleanup','run')})

    READ_POLICIES.update({'governor.' + verb: ('observe' if verb == 'status' else 'control', None, None) for verb in governor_schemas()})

    READ_POLICIES.update({operation:(required,None,None) for operation,(tool,schema,required,handler) in PROTECTED_ADAPTERS.items()})

    def __init__(self, authority, operations):
        self.authority, self.operations = authority, operations

    def execute(self, token, operation, arguments):
        from .unified_contract import original
        operation = original(operation, self.READ_POLICIES.keys() | {"runtime.input", "runtime.recover", "grants.revoke"})
        actor = self.authority.authenticate(token)
        from .unified_connectors import check_action,check_legacy_content
        check_action(actor,operation)
        check_legacy_content(actor,operation)
        policy = self.READ_POLICIES.get(operation)
        required = policy[0] if policy else {'runtime.input': 'control', 'runtime.recover': 'recovery',
                    'grants.revoke': 'admin'}.get(operation)
        if required is None:
            raise InventoryError('unsupported_operation', 'operation is unsupported')
        if required not in actor.scopes:
            raise AuthError('insufficient_scope')
        from .profile_operations import OPERATIONS as profile_operations
        if operation in PROTECTED_ADAPTERS:
            result=PROTECTED_ADAPTERS[operation][3](self.authority,self.operations,token,operation,arguments)
        elif operation.startswith('governor.'):
            from .governor_commands import protected_execute
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'Host governor owner unavailable.')
            result = protected_execute(self.operations.inventory.root, operation.rsplit('.', 1)[1],
                arguments, actor, authorize=lambda: self.authority.authenticate(token))
        elif operation in profile_operations:
            from .profile_operations import execute
            if self.operations.accounts is None or self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host account owner unavailable')
            result = execute(self.operations.inventory.root, operation, arguments,
                accounts=self.operations.accounts, actor=actor,
                authorize=lambda: self.authority.authenticate(token))
        elif operation in ('grok_auth.status', 'grok_auth.revoke'):
            from .grok_provider_auth import observe
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'Host Grok account owner unavailable.')
            result = observe(self.operations.inventory.root, arguments, actor=actor,
                authorize=lambda: self.authority.authenticate(token), operation=operation)
        elif operation.startswith('grok_models.'):
            from .grok_model_catalog import observe
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'Host Grok account owner unavailable.')
            result = observe(self.operations.inventory.root, operation, arguments, actor=actor,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('grok.'):
            from .controller_grok import ControllerGrok
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host Grok owner unavailable')
            result = ControllerGrok(self.operations.inventory.root).execute(actor,operation,arguments,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('recovery.'):
            from .controller_recovery import ControllerRecovery
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host recovery owner unavailable')
            result = ControllerRecovery(self.operations.inventory.root).execute(actor,operation,arguments,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('notices.'):
            from .controller_notices import ControllerNotices
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host notice owner unavailable')
            result = ControllerNotices(self.operations.inventory.root).execute(actor,operation,arguments,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('sessions.'):
            from .flow_session_commands import execute
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host session owner unavailable')
            result = execute(operation, arguments, self.operations.inventory.root, actor=actor,
                authorize=lambda: self.authority.authenticate(token))
        elif operation == 'health.observe':

            from .health_commands import protected_observe
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host health owner unavailable')
            result = protected_observe(actor, arguments, self.operations.inventory.root,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('flows.'):

            from types import SimpleNamespace
            from .flow_commands import owner, execute
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host flow owner unavailable')
            def dispatch(child_operation, child_arguments, guard):
                # Every child rechecks both the active flow attempt and the current grant.
                def authenticate(unused):
                    guard()
                    return self.authority.authenticate(token)
                child = type(self)(SimpleNamespace(authenticate=authenticate), self.operations)
                return child.execute(token, child_operation, child_arguments)
            flows = owner(self.operations.inventory.root, actor=actor,
                authorize=lambda: self.authority.authenticate(token), dispatch=dispatch)
            result = execute(flows, actor, operation, arguments)
        elif operation=='tabs.reattach-status':
            tabs=self.operations.tabs
            if tabs is None:raise InventoryError('configuration_unavailable','host presentation owner unavailable')
            if not all(permitted(actor,t) for t in tabs.reattach_owner().authorization_targets(arguments.get('plan_id'))):
                raise AuthError('insufficient_scope')
            result=self.operations.execute(operation,arguments)
        elif operation in ('tabs.recovery.preview','tabs.recovery.status'):
            tabs=self.operations.tabs
            if tabs is None:
                raise InventoryError('configuration_unavailable','host presentation owner unavailable')
            result=self.operations.execute(operation,arguments)
            target=result['result']['target'] if operation.endswith('preview') else tabs.recovery_target()
            if not permitted(actor,target):raise AuthError('insufficient_scope')
        elif operation in ('tabs.family.list','tabs.family.show'):
            from .bot_families import BotFamilies
            tabs=self.operations.tabs
            if tabs is None or not permitted(actor,BotFamilies(tabs.root,tabs=tabs).target()):
                raise AuthError('insufficient_scope')
            result=self.operations.execute(operation,arguments)
        elif operation in ('tabs.session.list','tabs.session.show','tabs.relocate.status','tabs.route.list','tabs.route.show','tabs.route.status'):
            from .terminal_sessions import TerminalSessions
            tabs=self.operations.tabs
            if tabs is None or not permitted(actor,TerminalSessions(tabs.root,tabs=tabs).target()):
                raise AuthError('insufficient_scope')
            result=self.operations.execute(operation,arguments)
        elif operation in ('tabs.format.status','tabs.format.inspect'):
            tabs=self.operations.tabs
            if tabs is None:raise InventoryError('configuration_unavailable','host presentation owner unavailable')
            scope=tabs.format_target(scope=arguments.get('scope','workspace'),workspace=arguments.get('workspace'))
            if not permitted(actor,scope):raise AuthError('insufficient_scope')
            result=self.operations.execute(operation,arguments)
        elif operation=='tabs.policy.status':
            tabs=self.operations.tabs
            if tabs is None or not permitted(actor,tabs.policy_target()):
                raise AuthError('insufficient_scope')
            result=self.operations.execute(operation,arguments)
        elif operation in ('tabs.monitor.status','tabs.monitor.refresh'):
            tabs=self.operations.tabs
            if tabs is None or not permitted(actor,tabs.monitor_target()):
                raise AuthError('insufficient_scope')
            result=self.operations.execute(operation,arguments)
            rows=result['result'].get('snapshot')
            if rows and 'resources' in rows:
                rows['resources']=[r for r in rows['resources'] if permitted(actor,r['target'])]
        elif operation in TabViews.READS:
            tabs=self.operations.tabs
            if tabs is None:
                raise InventoryError('configuration_unavailable','host presentation owner unavailable')
            if not permitted(actor,tabs.logical_target()):
                raise AuthError('insufficient_scope')
            result=self.operations.execute(operation,arguments)
            if operation=='tabs.view-evaluate':
                rows=[r for r in result['result']['resources'] if permitted(actor,r['target'])]
                result['result']['resources']=rows
                allowed_ids={TabViews.identity(r)['id'] for r in rows}
                groups=result['result'].get('groups',[])
                for group in groups:group['attachments']=[i for i in group['attachments'] if i in allowed_ids]
                result['result']['groups']=[g for g in groups if g['attachments']]
        elif operation.startswith('tabs.') and operation not in ('tabs.list','tabs.show','tabs.view-list','tabs.view-show','tabs.view-evaluate','tabs.group-list','tabs.group-show'):
            from .controller_tabs import AuthorizedTabs
            from .controller_runtime import ControllerRuntime
            if self.operations.tabs is None or self.operations.inventory is None:
                raise InventoryError('configuration_unavailable','host presentation owner unavailable')
            result = AuthorizedTabs(self.authority,self.operations.tabs,ControllerRuntime(self.operations.inventory.root)).execute(token,operation,arguments)
        elif operation.startswith('operations.'):

            from .operation_commands import execute
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host operation owner is unavailable')
            result = execute(operation, arguments, self.operations.inventory.root, actor=actor,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('migration.'):
            from .controller_migration_authorization import MigrationAuthorization
            from .controller_runtime import ControllerRuntime
            if self.operations.migration is None or self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host migration owner is unavailable')
            result = MigrationAuthorization(self.authority, self.operations.migration,
                runtime=ControllerRuntime(self.operations.inventory.root)).execute(token, operation, arguments)
        elif operation in {'builds.' + verb for verb in ('prepare','status','build','resume','qualify','cleanup','run')}:
            # Build recipe registration is host-owned; release operations never
            # activate packages or mutate account state. Existing admin scope applies.
            if self.operations.builds is None:
                raise InventoryError('configuration_unavailable', 'host build owner unavailable')
            target = dict(host=self.operations.host, environment=self.operations.environment)
            if not permitted(actor, target):
                raise AuthError('insufficient_scope')
            result = self.operations.execute(operation, arguments)
        elif operation.startswith('builds.') and operation != 'builds.list':
            from .controller_build_authorization import BuildAuthorization
            from .controller_runtime import ControllerRuntime
            import hashlib
            from pathlib import Path
            if self.operations.builds is None or self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host build owner is unavailable')
            recipes = {}
            selected_recipe = arguments.get('recipe')
            selected = self.operations.builds.recipes
            entries = [(selected_recipe, selected[selected_recipe])] if operation == 'builds.stage' and isinstance(selected_recipe, str) and selected_recipe in selected else []
            for name, path in entries:
                with Path(path).open('rb') as source:
                    raw = source.read(1048577)
                if len(raw) > 1048576:
                    raise InventoryError('configuration_unavailable', 'host recipe exceeds its bound')
                recipes[name] = dict(host=self.operations.host, environment=self.operations.environment,
                    recipe=name, recipe_sha256=hashlib.sha256(raw).hexdigest())
            result = BuildAuthorization(self.authority, self.operations.builds, recipe_targets=recipes,
                runtime=ControllerRuntime(self.operations.inventory.root)).execute(token, operation, arguments)
        elif operation == 'accounts.status':
            from .account_observation import execute
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host account owner unavailable')
            result = execute(self.operations.inventory.root, arguments, actor=actor,
                authorize=lambda: self.authority.authenticate(token), accounts=self.operations.accounts)
        elif operation in ('accounts.init', 'accounts.create'):
            from .account_management import execute
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host account owner unavailable')
            accounts = self.operations.accounts
            if accounts is None:
                from .controller_accounts import ControllerAccounts
                accounts = ControllerAccounts(self.operations.inventory.root / 'controller-accounts.toml',
                    host=self.operations.host, environment=self.operations.environment)
            result = execute(self.operations.inventory.root, operation, arguments, actor,
                lambda: self.authority.authenticate(token), accounts)
            if result['result']['operation']['execution'] == 'completed':
                self.operations.accounts = accounts
        elif operation == 'history.import':
            from .history_commands import protected_import
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host history owner unavailable')
            result = protected_import(arguments, self.operations.inventory.root, actor=actor,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('daemons.'):
            from .daemon_commands import execute
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host daemon owner unavailable')
            result = execute(self.operations.inventory.root, operation, arguments, actor=actor,
                authorize=lambda: self.authority.authenticate(token))
        elif operation.startswith('history.'):

            from .controller_history_authorization import HistoryAuthorization
            if self.operations.inventory is None:
                raise InventoryError('configuration_unavailable', 'host history owner is unavailable')
            result = HistoryAuthorization(self.authority, self.operations.inventory.root,
                host=self.operations.host, environment=self.operations.environment,
                runtime=self.operations.history_runtime, now=self.operations.history_now).execute(token, operation, arguments)
        elif operation == 'hosts.route':
            result = self.operations.execute(operation, arguments, actor=actor,
                authorize=lambda: self.authority.authenticate(token))
        else:
            if policy is None:
                raise InventoryError('unsupported_operation', 'operation is unsupported')
            result = self.operations.execute(operation, arguments)
            def allowed(row):
                if policy[0] == 'observe':
                    return permitted(actor, row['target'])
                fields = {'host', 'environment', 'provider', 'account', 'home', 'home_generation', 'configuration_revision'}
                return any(fields <= set(scope) and all(row['target'].get(key) == val for key, val in scope.items()) for scope in actor.targets)
            if policy[1]:
                result['result'][policy[1]] = [row for row in result['result'][policy[1]] if allowed(row)]
            elif not allowed(result['result'][policy[2]]):
                raise AuthError('insufficient_scope')
        if operation=='connectors.grants.revoke' and arguments.get('grant_id')==actor.grant_id:
            return result
        current = self.authority.authenticate(token)
        if current.grant_id != actor.grant_id:
            raise AuthError()
        result['actor'] = dict(subject=actor.subject, principal_kind=actor.principal_kind,
            client_id=actor.client_id, grant_id=actor.grant_id, issuer=actor.issuer,
            resource=actor.resource, scopes=sorted(actor.scopes))
        return result


class ControllerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, authority, operations, *, consent_secret=None, owner='owner'):
        if address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise ValueError('controller listener must bind loopback; use authenticated TLS ingress')
        self._slots = threading.BoundedSemaphore(16)
        self.authority = authority
        self._recovery_lock = threading.Lock()
        self.operations = ProtectedOperations(authority, operations)
        self.consent_secret, self.owner = consent_secret, owner
        super().__init__(address, ControllerHandler)

    def service_actions(self):
        self.authority.recover_revocations(limit=1)
        inventory=self.operations.operations.inventory
        if inventory is None:
            return
        from pathlib import Path
        root=inventory.root
        if not (Path(root)/'controller-recovery'/'policies.sqlite').is_file():
            return
        if self._recovery_lock.acquire(blocking=False):
            def run():
                try:
                    from .controller_schedule import maintain
                    maintain(self.authority,root)
                finally:
                    self._recovery_lock.release()
            try:
                threading.Thread(target=run,name='controller-recovery-scheduler',daemon=True).start()
            except BaseException:
                self._recovery_lock.release()
                raise

    def process_request(self, request, address):
        request.settimeout(5)
        if not self._slots.acquire(blocking=False):
            request.close()
            return
        try: super().process_request(request, address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self._slots.release()


class ControllerHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Tokens/codes/consent secrets never enter HTTP request logs.

    def reply(self, status, value, headers=None):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        for key, val in (headers or {}).items(): self.send_header(key, val)
        self.end_headers(); self.wfile.write(body)

    def fail(self, error):
        code = getattr(error, 'code', 'invalid_request')
        status = 401 if code == 'invalid_token' else 403 if code == 'insufficient_scope' else 400
        headers = {}
        if status == 401:
            headers['WWW-Authenticate'] = 'Bearer resource_metadata="' + self.server.authority.issuer + '/.well-known/oauth-protected-resource"'
        self.reply(status, {'error': code}, headers)

    def do_GET(self):
        path = urlsplit(self.path).path
        auth = self.server.authority
        if path == '/mcp':
            bearer = self.headers.get('Authorization', '')
            try:
                if not bearer.startswith('Bearer '): raise AuthError()
                auth.authenticate(bearer[7:])
            except AuthError as error: return self.fail(error)
            return self.reply(405, {'error': 'streaming_not_supported'}, {'Allow': 'POST'})
        if path == '/.well-known/oauth-authorization-server': return self.reply(200, auth.metadata())
        if path == '/.well-known/oauth-protected-resource': return self.reply(200, auth.protected_metadata())
        if path == '/authorize':
            if self.server.consent_secret is None: return self.reply(503, {'error': 'operator_consent_unconfigured'})
            values = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            # Display the complete requested grant; submission requires the private operator secret.
            fields = ''.join('<input type="hidden" name="' + html.escape(k, quote=True) + '" value="' + html.escape(v, quote=True) + '">' for k, v in values.items())
            body = ('<!doctype html><title>Wake consent</title><h1>Authorize Wake client</h1><pre>' + html.escape(json.dumps(values, indent=2)) + '</pre><p>Enter operator consent secret only after reviewing client, scopes and exact targets.</p><form method="post" action="/authorize">' + fields + '<label>Consent secret <input type="password" name="consent_secret" autocomplete="off"></label><button>Approve requested grant</button></form>').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'none'; form-action 'self'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        self.reply(404, {'error': 'not_found'})

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 65536: raise AuthError('invalid_request')
        raw = self.rfile.read(length)
        content_type = self.headers.get('Content-Type', '').split(';')[0]
        if content_type == 'application/x-www-form-urlencoded':
            return {k: v[0] for k, v in parse_qs(raw.decode(), keep_blank_values=True).items()}
        if content_type != 'application/json': raise AuthError('invalid_request')
        value = json.loads(raw)
        if not isinstance(value, dict): raise AuthError('invalid_request')
        return value

    def do_POST(self):
        try:
            if any(key.lower().startswith(('x-wake-', 'x-auth', 'x-forwarded-user', 'x-forwarded-subject', 'x-forwarded-email', 'x-forwarded-groups', 'x-user-', 'x-principal-')) or key.lower() in ('remote-user', 'x-remote-user') for key in self.headers):
                raise AuthError('untrusted_identity_header')
            origin = self.headers.get('Origin')
            if origin and origin != self.server.authority.issuer: raise AuthError('invalid_origin')
            path, auth = urlsplit(self.path).path, self.server.authority
            args = self.body()
            if path == '/register': return self.reply(201, auth.register(args))
            if path == '/token': return self.reply(200, auth.token(args))
            if path == '/revoke':
                auth.revoke_token(args.get('token', ''), args.get('client_id'))
                return self.reply(200, {})
            if path == '/authorize':
                secret = args.pop('consent_secret', '')
                if not self.server.consent_secret or not secrets.compare_digest(secret, self.server.consent_secret): raise AuthError('access_denied')
                if args.get('response_type') != 'code' or args.get('code_challenge_method') != 'S256': raise AuthError('invalid_request')
                code = auth.authorize(subject=self.server.owner, principal_kind='owner', client_id=args.get('client_id'), redirect_uri=args.get('redirect_uri'), resource=args.get('resource'), scopes=args.get('scope', '').split(), targets=json.loads(args.get('targets', '[]')), code_challenge=args.get('code_challenge'))
                location = args['redirect_uri'] + ('&' if '?' in args['redirect_uri'] else '?') + urlencode(dict(code=code, state=args.get('state', '')))
                return self.reply(303, {}, {'Location': location})
            bearer = self.headers.get('Authorization', '')
            if not bearer.startswith('Bearer '): raise AuthError()
            token = bearer[7:]
            auth.authenticate(token)
            if path == '/operations':
                try:
                    value = self.server.operations.execute(token, args.get('operation'), args.get('arguments', {}))
                except InventoryError as error:
                    return self.reply(400, operation_failure(args.get('operation'), error))
                return self.reply(200, value)
            if path == '/mcp': return self.mcp(token, args)
            self.reply(404, {'error': 'not_found'})
        except (AuthError, InventoryError) as error: self.fail(error)
        except (ValueError, TypeError, KeyError, AttributeError): self.fail(AuthError('invalid_request'))

    def mcp(self, token, request):
        identifier = request.get('id')
        if request.get('jsonrpc') != '2.0': raise AuthError('invalid_request')
        method, params = request.get('method'), request.get('params', {})
        if method == 'notifications/initialized':
            self.send_response(202); self.send_header('Content-Length', '0'); self.end_headers(); return
        if method == 'initialize':
            result = dict(protocolVersion='2025-03-26', capabilities={'tools': {'listChanged': False}}, serverInfo={'name': 'codex-wake-controller', 'version': '1'})
        elif method == 'ping': result = {}
        elif method == 'tools/list':
            actor = self.server.authority.authenticate(token)
            result = {'tools': [dict(name=name, description=describe_operation(operation), inputSchema=schema)
                for name, (operation, schema) in TOOLS.items()
                if ProtectedOperations.READ_POLICIES[operation][0] in actor.scopes
                and (operation.startswith('inventory.')
                     or (operation == 'accounts.init' and self.server.operations.operations.inventory is not None)
                     or (operation.startswith('operations.') and self.server.operations.operations.inventory is not None)
                     or (operation.startswith('hosts.') and self.server.operations.operations.hosts is not None)
                     or (operation.startswith('migration.') and self.server.operations.operations.migration is not None)
                     or (operation.startswith('builds.') and self.server.operations.operations.builds is not None)
                     or (not operation.startswith(('hosts.', 'builds.', 'migration.')) and self.server.operations.operations.accounts is not None))]}
        elif method == 'tools/call':
            name = params.get('name')
            if name not in TOOLS:
                return self.reply(200, dict(jsonrpc='2.0', id=identifier, error={'code': -32602, 'message': 'unsupported tool'}))
            try:
                value = self.server.operations.execute(token, TOOLS[name][0], params.get('arguments', {}))
                result = dict(content=[dict(type='text', text=json.dumps(value))], structuredContent=value, isError=False)
            except InventoryError as error:
                value = operation_failure(TOOLS[name][0], error)
                result = dict(content=[dict(type='text', text=json.dumps(value))], structuredContent=value, isError=True)
        else:
            return self.reply(200, dict(jsonrpc='2.0', id=identifier, error={'code': -32601, 'message': 'method not found'}))
        self.reply(200, dict(jsonrpc='2.0', id=identifier, result=result))
