"""Controller attachment CLI adapter over the host-owned operation service."""
import json

from .cli_output import emit
import subprocess


def register_parser(subparsers):
    parser = subparsers.add_parser('tabs')
    commands = parser.add_subparsers(dest='tab_command', required=True)
    for verb in ('list','show','preview','apply','undo','capture','input'):
        item = commands.add_parser(verb)
        item.add_argument('--json', dest='as_json', action='store_true')
        item.add_argument('--arguments', type=json.loads, default={})
    return parser


def render_monitor(value):
    """Render actual status or retained operation uncertainty without inventing state."""
    from .tab_result import exit_status
    if exit_status(value):return None
    from .tab_observer import render_status
    payload=value if isinstance(value.get('monitor'),dict) else None
    result=value.get('result')
    retained=result.get('operation') if isinstance(result,dict) else None
    retained=retained if isinstance(retained,dict) else {}
    outcome=retained.get('result')
    if isinstance(outcome,dict) and isinstance(outcome.get('monitor'),dict):
        payload=outcome
    if payload is not None:
        if 'snapshot' in payload:
            return render_status(payload)
        monitor=payload['monitor'];settings=monitor.get('settings') or {}
        return ('Tab monitor: '+str(monitor.get('status','unknown'))+'\nTiers: '+
                ', '.join(key+'='+('on' if settings.get(key,True) else 'off')
                          for key in ('activity','health','errors'))+'\n'
                'Inspect current inventory with tabs monitor-status --json.')
    outcome_status=outcome.get('status') if isinstance(outcome,dict) else None
    phase=('uncertain' if retained.get('phase')=='uncertain' else
           outcome_status if outcome_status in ('partial','uncertain','held') else
           value.get('status') if value.get('status') in ('partial','uncertain','held') else
           retained.get('execution') or retained.get('phase') or value.get('status') or 'unknown')
    return ('Tab monitor operation: '+str(phase)+'\n'
            'No monitor status was returned. Inspect current state with tabs monitor-status --json.')


def render_format_status(value,args):
    """Keep routine status bounded; inspect and JSON retain native option detail."""
    if value.get('status') not in ('inspection','stale_target'):return None
    import shlex
    from .cli_output import _text
    policy=value['policy'];record=value.get('record') or {}
    state=('disabled' if not policy['enabled'] else 'paused' if record.get('paused') else
           'enabled' if record.get('enabled') else 'not enabled')
    if value.get('namespace_matches') is False:state='stale namespace'
    global_scope=value.get('scope')=='global'
    if global_scope:state='enabled' if policy['enabled'] else 'disabled'
    lines=['Tab formatting: '+state]
    workspace=value.get('target',{}).get('workspace')
    lines.append('Scope: global' if global_scope else 'Workspace: '+_text(workspace))
    lines+=['Policy: '+('enabled' if policy['enabled'] else 'disabled'),
            'Preset: '+_text(policy.get('preset'))]
    if not global_scope:
        lines.append('Tabs: '+str(len(value.get('windows',[]))))
        paused=sum(bool(window.get('paused')) for window in record.get('windows',{}).values())
        if paused:lines.append('Tabs held after manual changes: '+str(paused))
    command=['codex-wake']
    if getattr(args,'wake_root',None):command+=['--wake-root',str(args.wake_root)]
    command+=['tabs','format','inspect']
    command+=['--scope','global'] if global_scope else ['--workspace',workspace]
    lines.append('Details: '+_text(shlex.join(command)))
    return '\n'.join(lines)


def command(args, owner=None):
    from .managed_inventory import InventoryError
    from .records import WakeError
    from .shortcut_store import default_root
    try:
        args.wake_root = default_root(args.wake_root)
        if args.tab_command=='result':
            from .controller_runtime import ControllerRuntime
            from .tab_result import exit_status
            value=ControllerRuntime(args.wake_root).local_tab_result('tab-cli-'+args.request_id)
            emit(value, args);return exit_status(value)
        if owner is None:
            from .controller_tabs import controller_tabs_from_root
            owner = controller_tabs_from_root(args.wake_root)
        operation = 'tabs.' + args.tab_command.replace('monitor-','monitor.',1).replace('policy-','policy.',1).replace('recovery-','recovery.',1).replace('format-','format.',1).replace('session-','session.',1).replace('relocate-','relocate.',1).replace('route-','route.',1).replace('family-','family.',1)
        from .terminal_session_cli import select_workspace, render
        arguments=dict(args.arguments)
        selector=arguments.pop('session_selector',None)
        server=arguments.pop('session_server',None)
        from .tab_contract import BY_OPERATION
        properties=BY_OPERATION.get(operation,(None,(None,None,None,{})))[1][3]
        if 'selection' in properties:
            from .terminal_selection_cli import expression
            selected=expression(owner,args,arguments.get('selection'))
            if selected is not None:arguments['selection']=selected
        if 'workspace' in properties and arguments.get('scope')!='global' and (selector is not None or ('workspace' not in arguments and not operation.startswith('tabs.family.'))):
            arguments['workspace']=select_workspace(owner,selector,server=server,interactive=not getattr(args,'as_json',False))
        value = owner.execute(operation,arguments) if operation in owner.READS else operator_execute(operation,arguments,args.wake_root,owner=owner,request_id=getattr(args,'request_id',None))
        readable=render(value) if operation.startswith('tabs.session.') and not getattr(args,'as_json',False) else None
        if operation.startswith('tabs.monitor.') and not getattr(args,'as_json',False):
            readable=render_monitor(value)
        if operation=='tabs.format.status' and not getattr(args,'as_json',False):
            readable=render_format_status(value,args)
        if readable is not None:
            print(readable)
        else:
            emit(value, args)
        from .tab_result import exit_status
        return exit_status(value)
    except (WakeError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        emit(dict(status='held', error=dict(
            code=getattr(error,'code','configuration_unavailable'),
            message=str(error) if isinstance(error,WakeError) else
                    'Tab configuration is unavailable or invalid; inspect the selected controller and refresh workspaces.',
            **({'candidates':error.candidates} if hasattr(error,'candidates') else {}))), args)
        return 2


def tool_specs():
    from .tab_contract import tool_specs as portable_specs
    return portable_specs()


def protected_execute(operation,arguments,root):
    from .shortcut_store import default_root
    root=default_root(root)
    from types import SimpleNamespace
    from pathlib import Path
    from .controller_tabs import controller_tabs_from_root
    from .controller_operations import ControllerOperations
    from .controller_http import ProtectedOperations
    from .managed_inventory import ManagedInventory
    from .operation_commands import local_actor
    tabs=controller_tabs_from_root(root)
    operations=ControllerOperations(ManagedInventory(root),host=tabs.host,environment=tabs.environment,tabs=tabs)
    configured=(Path(root)/'controller-messaging.json').is_file()
    from .daemon_commands import local_operator
    target=arguments.get('expected_target',{})
    if not configured and not target and operation=='tabs.format.override-inspect':
        target=tabs.format_target(workspace=arguments.get('workspace'))
    uid_actor=None if configured else local_operator(target,('control','observe'))
    if uid_actor is not None and operation in ('tabs.reattach-apply','tabs.reattach-status'):
        from dataclasses import replace
        uid_actor=replace(uid_actor,targets=[*uid_actor.targets,*tabs.reattach_owner().authorization_targets(arguments.get('plan_id'))])
    if uid_actor is not None and isinstance(arguments.get('expected_destination'),dict):
        from dataclasses import replace
        uid_actor=replace(uid_actor,targets=[*uid_actor.targets,arguments['expected_destination']])
    authority=SimpleNamespace(authenticate=lambda unused:local_actor(root) if configured else uid_actor)
    return ProtectedOperations(authority,operations).execute('host-local-grant',operation,arguments)


def operator_execute(operation, arguments, root, *, owner=None, request_id=None):
    """UID-authorized local tab control, with retained common journal identity."""
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace
    from .daemon_commands import local_operator
    from .controller_tabs import controller_tabs_from_root, AuthorizedTabs
    from .controller_runtime import ControllerRuntime
    from .tab_lifecycle import TabLifecycle
    from .managed_inventory import InventoryError
    if request_id is not None:
        from .controller_runtime import bounded_id
        bounded_id('tab-cli-'+request_id)
        try:
            return ControllerRuntime(root).local_tab_result('tab-cli-'+request_id,
                expected_operation=operation,arguments=arguments)
        except InventoryError as error:
            if error.code!='operation_not_found':raise
    owner = owner or controller_tabs_from_root(root)
    payload = dict(arguments)
    from .tab_views import TabViews
    if operation.startswith('tabs.family.'):
        from .bot_families import BotFamilies
        payload.setdefault('expected_target',BotFamilies(root,tabs=owner).target())
        key=_intent_key(operation,payload,request_id)
        payload.setdefault('_request',dict(operation_id='tab-cli-'+key,idempotency_key='tab-cli-'+key,correlation_id=key,binding='local-cli',target=payload['expected_target']))
        actor=local_operator(payload['expected_target'],('control','observe'))
        return AuthorizedTabs(SimpleNamespace(authenticate=lambda unused:actor),owner,ControllerRuntime(root)).execute('local-cli',operation,payload)
    if operation in TabViews.READS|TabViews.MUTATIONS or operation.startswith(('tabs.monitor.','tabs.policy.')):
        payload.setdefault('expected_target',owner.monitor_target() if operation.startswith('tabs.monitor.') else owner.policy_target() if operation.startswith('tabs.policy.') else owner.logical_target())
        key=_intent_key(operation,payload,request_id)
        payload.setdefault('_request',dict(operation_id='tab-cli-'+key,idempotency_key='tab-cli-'+key,
            correlation_id=key,binding='local-cli',target=payload['expected_target']))
        actor=local_operator(payload['expected_target'],('control','observe'))
        return AuthorizedTabs(SimpleNamespace(authenticate=lambda unused:actor),owner,ControllerRuntime(root)).execute('local-cli',operation,payload)
    if operation in ('tabs.reattach-apply','tabs.reattach-status'):
        plan=owner.reattach_owner().execute('tabs.reattach-status',{'plan_id':payload.get('plan_id')})
        payload.setdefault('expected_target',plan['target'])
        key=_intent_key(operation,payload,request_id)
        payload.setdefault('_request',dict(operation_id='tab-cli-'+key,idempotency_key='tab-cli-'+key,correlation_id=key,binding='local-cli',target=payload['expected_target']))
        actor=local_operator(payload['expected_target'],('control','observe'))
        from dataclasses import replace
        actor=replace(actor,targets=[*actor.targets,*owner.reattach_owner().authorization_targets(payload['plan_id'])])
        return AuthorizedTabs(SimpleNamespace(authenticate=lambda unused:actor),owner,ControllerRuntime(root)).execute('local-cli',operation,payload)
    if operation.startswith('tabs.format.') and payload.get('scope')=='global':
        payload.setdefault('expected_target',owner.format_target(scope='global'))
        key=_intent_key(operation,payload,request_id)
        payload.setdefault('_request',dict(operation_id='tab-cli-'+key,idempotency_key='tab-cli-'+key,
            correlation_id=key,binding='local-cli',target=payload['expected_target']))
        actor=local_operator(payload['expected_target'],('control','observe'))
        return AuthorizedTabs(SimpleNamespace(authenticate=lambda unused:actor),owner,ControllerRuntime(root)).execute('local-cli',operation,payload)
    if operation.startswith(('tabs.session.','tabs.relocate.','tabs.route.')):
        from .terminal_sessions import TerminalSessions
        payload.setdefault('expected_target',TerminalSessions(root,tabs=owner).target())
        key=_intent_key(operation,payload,request_id)
        payload.setdefault('_request',dict(operation_id='tab-cli-'+key,idempotency_key='tab-cli-'+key,correlation_id=key,binding='local-cli',target=payload['expected_target']))
        actor=local_operator(payload['expected_target'],('control','observe'))
        return AuthorizedTabs(SimpleNamespace(authenticate=lambda unused:actor),owner,ControllerRuntime(root)).execute('local-cli',operation,payload)
    workspace = payload.get('workspace')
    if workspace is None and len(owner.workspaces) == 1:
        workspace = next(iter(owner.workspaces))
    elif workspace not in owner.workspaces:
        matches = [k for k,v in owner.workspaces.items() if v.get('label') == workspace]
        if len(matches) == 1:
            workspace = matches[0]
    if workspace not in owner.workspaces:
        raise InventoryError('ambiguous_target','Select one workspace from tabs list using --workspace.')
    payload['workspace'] = workspace
    lifecycle = TabLifecycle(root,workspaces=owner.workspaces,host=owner.host,environment=owner.environment)
    if operation=='tabs.recovery.apply' and 'expected_target' not in payload:
        fields={k:payload[k] for k in ('capture_id','workspace','restore_layout') if k in payload}
        preview=owner.execute('tabs.recovery.preview',fields)
        if preview['status']!='ready':
            raise InventoryError('recovery_held','Recovery preview contains unresolved bindings; inspect before applying.')
        payload['expected_target']=preview['target']
    elif 'expected_target' not in payload:
        payload['expected_target']=(owner.format_target(workspace=workspace)
            if operation.startswith('tabs.format.') else lifecycle.inspect(workspace)['target'])
    if 'destination' in payload:
        dest = payload['destination']
        if dest not in owner.workspaces:
            matches=[k for k,v in owner.workspaces.items() if v.get('label') == dest]
            if len(matches)==1:dest=matches[0]
        payload['destination']=dest
        payload.setdefault('expected_destination',lifecycle.inspect(dest)['target'])
    if '_request' not in payload:
        key = _intent_key(operation,payload,request_id)
        payload['_request']=dict(operation_id='tab-cli-'+key,idempotency_key='tab-cli-'+key,
                                 correlation_id=key,binding='local-cli',target=payload['expected_target'])
    actor=local_operator(payload['expected_target'],('control','observe'))
    if '_request' in arguments and (Path(root)/'controller-messaging.json').is_file():
        from .operation_commands import local_actor
        actor=local_actor(root)
    if actor.issuer.startswith('local://uid/') and isinstance(payload.get('expected_destination'),dict):
        from dataclasses import replace
        actor=replace(actor,targets=[*actor.targets,payload['expected_destination']])
    authority=SimpleNamespace(authenticate=lambda unused:actor)
    return AuthorizedTabs(authority,owner,ControllerRuntime(root)).execute('local-cli',operation,payload)


def _intent_key(operation,payload,request_id=None):
    import hashlib
    from uuid import uuid4
    if request_id is not None:return request_id
    if operation.startswith('tabs.format.') or operation in ('tabs.preview','tabs.policy.tick','tabs.recovery.capture','tabs.reattach-preview'):
        return uuid4().hex
    return hashlib.sha256(json.dumps([operation,payload],sort_keys=True).encode()).hexdigest()
