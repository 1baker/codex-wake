"""Canonical resource names; existing owners retain execution and authority."""
from copy import deepcopy
import argparse

FAMILIES=('environment','wakes','programs','accounts','harnesses','operations','connectors')
PREFIXES=(('tabs.session.','environment.sessions.'),('tabs.','environment.tabs.'),
 ('local.governor.','programs.governor.'),('local.self_limits.','programs.limits.'),
 ('local.','environment.conversations.'),('inventory.','environment.resources.'),
 ('agent_sessions.','environment.discovery.'),('agents.','environment.agents.'),('history.','environment.conversations.history.'),
 ('sessions.','programs.sessions.'),('flows.','programs.flows.'),
 ('conditions.','programs.conditions.'),('functions.','programs.functions.'),
 ('configuration.','accounts.configuration.'),('stores.','accounts.stores.'),('accounts.','accounts.profiles.'),
 ('builds.','harnesses.builds.'),('daemons.','harnesses.runtimes.'),
 ('hosts.','connectors.hosts.'),('grants.','connectors.grants.'),
 ('native.','wakes.intents.'),('schedules.','wakes.schedules.'),
 ('grok.','harnesses.grok.'),('health.','environment.health.'),
 ('notices.','operations.notices.'),('recovery.','harnesses.recovery.'),
 ('migration.','accounts.migration.'),('governor.','programs.governor.'),
 ('runtime.','harnesses.runtime_controls.'))
# Whole legacy parser owners are reused, including their validation and root rules.
CLI_ALIASES={('environment','sessions'):('tabs','sessions'),
 ('environment','tabs'):('tabs',),('environment','agents'):('agents',),
 ('environment','discovery'):('sessions',),
 ('environment','conversations','history'):('history',),
 ('environment','conversations'):('control',),
 ('programs','flows'):('flows',),('programs','sessions'):('flow-sessions',),
 ('accounts','profiles'):('accounts',),('accounts','stores'):('stores',),
 ('accounts','configuration'):('configuration',),
 ('harnesses','builds'):('builds',),('harnesses','runtimes'):('daemons',),
 ('connectors','hosts'):('hosts',),('wakes','intents'):('native',),
 ('wakes','schedules'):('schedules',)}

FLOW_NAMES={'propose':'definitions.propose','publish':'definitions.publish','definition':'definitions.show',
            'start':'runs.start','inspect':'runs.show','advance':'runs.advance','reconcile':'runs.reconcile','cancel':'runs.cancel'}
for _verb,_path in FLOW_NAMES.items():
    CLI_ALIASES[tuple(['programs',*_path.split('.')])]=('flows',_verb)

def canonical(operation):
    if operation.startswith(('accounts.profiles.','accounts.configuration.','accounts.stores.')):return operation
    if operation.startswith('flows.') and operation[6:] in FLOW_NAMES:return 'programs.'+FLOW_NAMES[operation[6:]]
    for before,after in PREFIXES:
        if operation.startswith(before):return after+operation[len(before):]
    return operation

def original(operation,available):
    if operation in available:return operation
    matches=[key for key in available if canonical(key)==operation]
    if len(matches)>1:raise ValueError('conflicting canonical operation: '+operation)
    return matches[0] if matches else operation

def tool_name(operation):return 'wake_'+operation.replace('.','_')

def api_aliases(tools):
    for name,(operation,schema) in list(tools.items()):
        alias=tool_name(canonical(operation))
        entry=(operation,schema)
        if alias in tools and tools[alias]!=entry:raise ValueError('conflicting MCP alias: '+alias)
        tools.setdefault(alias,entry)
    return tools

def local_aliases(definitions):
    from .unified_environment import definitions as environment_definitions
    definitions.update(environment_definitions())
    from .unified_wakes import definitions as wake_definitions
    definitions.update(wake_definitions())
    from .unified_terminal import definitions as terminal_definitions
    definitions.update(terminal_definitions())
    from .unified_session_input import definitions as input_definitions
    definitions.update(input_definitions())
    from .unified_session_presentation import definitions as presentation_definitions
    definitions.update(presentation_definitions())
    from .unified_connectors import definitions as connector_definitions
    definitions.update(connector_definitions())
    from .unified_bulk import definitions as bulk_definitions
    definitions.update(bulk_definitions())
    for operation,(tool,description,schema,handler,readonly) in list(definitions.items()):
        alias=canonical(operation)
        if alias==operation:continue
        if alias in definitions:raise ValueError('conflicting local alias: '+alias)
        definitions[alias]=(tool_name(alias),description,schema,handler,readonly)
    return definitions

def native_operation(group,verb):
    if group=='local':return 'local.'+verb
    if group.startswith('controller-'):
        if '.' in verb:return verb
        prefixes={'controller-hosts':'hosts','controller-builds':'builds',
                  'controller-operations':'operations','controller-history':'history'}
        return prefixes.get(group,group.removeprefix('controller-'))+'.'+verb
    return {'controller':'inventory','sessions':'agent_sessions',
            'harness-native':'native','harness-schedules':'schedules','self-limits':'local.self_limits'}.get(group,group)+'.'+verb

def native_aliases(specs):
    for name,spec in list(specs.items()):
        operation=native_operation(spec[0],spec[1]);alias=tool_name(canonical(operation))
        if canonical(operation)==operation and not spec[0].startswith('controller-'):continue
        if alias in specs and (specs[alias][:2],specs[alias][3:])!=(spec[:2],spec[3:]):raise ValueError('conflicting native alias: '+alias)
        specs.setdefault(alias,spec)
    return specs

def metadata():
    from .local_control_service import definitions
    from .controller_http import TOOLS, ProtectedOperations
    operations={}
    for operation,(tool,description,schema,handler,readonly) in definitions().items():
        if operation!=canonical(operation):continue
        operations.setdefault(operation,{})['local']={'schema':schema,'mcp':tool,'readonly':readonly,'admission':'authenticated_controller_transport_required' if operation.startswith(('connectors.grants.','programs.bulk.')) else 'same_user_private_connection','available':not operation.startswith(('connectors.grants.','programs.bulk.'))}
    for tool,(operation,schema) in TOOLS.items():
        operations.setdefault(canonical(operation),{})['protected']={'schema':schema,'mcp':tool_name(canonical(operation)),'required_scope':ProtectedOperations.READ_POLICIES.get(operation,({'runtime.input':'control','runtime.recover':'recovery','grants.revoke':'admin'}.get(operation),))[0],'admission':'fresh_authenticated_actor_and_exact_target','supported_registration':True}
    from .unified_connectors import delegated_content_scope
    for operation,transports in operations.items():
        if 'protected' in transports:
            policy=transports['protected']
            extra=delegated_content_scope(original(operation,ProtectedOperations.READ_POLICIES))
            policy['delegated_required_scopes']=sorted(set(filter(None,(policy['required_scope'],extra))))
    return dict(schema_version=1,families=list(FAMILIES),operations=operations,
                admission='Transport-owned identity and permission checks remain authoritative.',
                compatibility='Legacy entry points retain their original owners and receipts.',
                capability_notes='Registration is not current target readiness. Harness-specific capability and exact target observation remain required; unsupported actions never fall back.')

def _subs(parser):
    return next((a for a in parser._actions if isinstance(a,argparse._SubParsersAction)),None)

def _parser(parser,path):
    for part in path:
        action=_subs(parser)
        if action is None or part not in action.choices:return None
        parser=action.choices[part]
    return parser

def apply_cli(parser):
    parser._unified_direct_paths = set()
    sources={path:deepcopy(_parser(parser,source)) for path,source in CLI_ALIASES.items() if _parser(parser,source)}
    for path,source in sorted(sources.items(),key=lambda item:len(item[0])):
        parent=parser
        for part in path[:-1]:
            action=_subs(parent) or parent.add_subparsers(dest='_unified_'+part,required=True)
            parent=action.choices.get(part) or action.add_parser(part)
        action=_subs(parent) or parent.add_subparsers(dest='_unified_action',required=True)
        if path[-1] not in action.choices:action.add_parser(path[-1],parents=[source],add_help=False)
    environment=_parser(parser,('environment',));action=_subs(environment)
    for verb in ('snapshot','children'):
        item=action.add_parser(verb)
        item.set_defaults(_unified_operation='environment.'+verb)
        if verb=='children':item.add_argument('resource_id')
    action.add_parser('capabilities',help='discover canonical operation contracts and transport capabilities')
    from .local_control_service import definitions
    entries=dict(definitions())
    from .controller_http import TOOLS
    for tool,(legacy,schema) in TOOLS.items():
        operation=canonical(legacy)
        if operation not in entries:
            entries[operation]=(tool,'Authenticated canonical controller operation.',schema,None,False)
    for operation,(tool,description,schema,handler,readonly) in entries.items():
        if operation.split('.')[0] not in FAMILIES or _parser(parser,operation.split('.')) is not None:continue
        parent=parser
        parts=operation.split('.')
        for part in parts[:-1]:
            children=_subs(parent) or parent.add_subparsers(dest='_unified_'+part,required=True)
            parent=children.choices.get(part) or children.add_parser(part)
        children=_subs(parent) or parent.add_subparsers(dest='_unified_action',required=True)
        item=children.add_parser(parts[-1],help=description)
        parser._unified_direct_paths.add(tuple(parts))
        item.set_defaults(_unified_operation=operation,_unified_fields=list(schema['properties']))
        item.add_argument('--arguments',type=__import__('json').loads,default={})
        if handler is None or operation.startswith(('connectors.grants.','programs.bulk.')):
            item.set_defaults(_unified_route='protected')
            item.add_argument('--controller-endpoint',required=True)
            item.add_argument('--controller-token-file',type=__import__('pathlib').Path,required=True)
            item.add_argument('--controller-transport',choices=('api','mcp'),default='api')
        for field,prop in schema['properties'].items():
            if field=='arguments':continue
            options=dict(default=argparse.SUPPRESS,dest=field)
            kind=prop.get('type')
            if kind in ('object','array'):options['type']=__import__('json').loads
            elif kind=='integer':options['type']=int
            elif kind=='number':options['type']=float
            elif kind=='boolean':options['action']=argparse.BooleanOptionalAction
            if 'enum' in prop:options['choices']=prop['enum']
            item.add_argument('--'+field.replace('_','-'),**options)
    def update_usage(node,prog):
        node.prog=prog
        children=_subs(node)
        if children is not None:
            children._prog_prefix=prog
            for name,child in children.choices.items():update_usage(child,prog+' '+name)
    for path in CLI_ALIASES:
        node=_parser(parser,path)
        if node is not None:update_usage(node,parser.prog+' '+' '.join(path))
    return parser

def expand_cli(argv,parser=None):
    import sys
    args=list(sys.argv[1:] if argv is None else argv);offset=0
    # Preserve global options; do not rewrite text in option values or prompts.
    while offset<len(args) and args[offset].startswith('-'):
        if args[offset]=='--wake-root':offset+=2
        elif args[offset].startswith('--wake-root='):offset+=1
        else:break
    rest=args[offset:]
    if rest==['environment','capabilities']:return args,True
    for path in getattr(parser, '_unified_direct_paths', ()):
        if rest[:len(path)]==list(path):return args,False
    for path,legacy in sorted(CLI_ALIASES.items(),key=lambda item:-len(item[0])):
        if rest[:len(path)]==list(path):return args[:offset]+list(legacy)+rest[len(path):],False
    return args,False
