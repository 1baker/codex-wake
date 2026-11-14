"""One operation registry for same-user CLI, HTTP and local MCP clients."""
from functools import partial

from jsonschema import Draft202012Validator
from .managed_inventory import InventoryError


def definitions():
    from .local_control_commands import operation_schemas,tool_specs,execute
    from .local_health import INPUT_SCHEMA
    from .local_slash_commands import tool_specs as slash_specs
    from .local_control_routing import HARNESS_PROPERTIES,observation,health as routed_health,slash as routed_slash
    result={}
    for tool,(_,verb,description,properties,required,readonly) in tool_specs().items():
        name='local.'+verb
        result[name]=(tool,description,operation_schemas()[name],partial(execute,name),readonly)
    text={'type':'string','minLength':1,'maxLength':4096}
    def schema(properties,required=()):return dict(type='object',properties=properties,required=list(required),additionalProperties=False)
    result['local.list']=('wake_local_list','Discover running owned conversations and presentation bindings.',schema(dict(endpoint=text,**HARNESS_PROPERTIES)),partial(observation,'list'),True)
    result['local.resolve']=('wake_local_resolve','Resolve one owned conversation and pin its generation.',schema(dict(selector=text,endpoint=text,expected_target={'type':'object'},**HARNESS_PROPERTIES),['selector']),partial(observation,'resolve'),True)
    result['local.health']=('wake_local_health','Fresh exact controlling-TUI loop health, never inferred from process liveness.',dict(INPUT_SCHEMA,properties=dict(INPUT_SCHEMA['properties'],**HARNESS_PROPERTIES)),lambda arguments,root:routed_health(arguments,root),True)
    for tool,(_,verb,description,properties,required,readonly) in slash_specs().items():
        def action(verb,arguments,root):return routed_slash(verb,arguments,root)
        result['local.slash.'+verb]=(tool,description,schema(properties,required),partial(action,verb),readonly)
    for verb in ('show','set'):
        def limits(verb,arguments,root):
            from .local_self_limits import execute as self_limits
            arguments=dict(arguments);selector=arguments.pop('selector',None);endpoint=arguments.pop('endpoint','unix://')
            return self_limits(root,verb,arguments,selector=selector,endpoint=endpoint)
        properties=dict(selector=text,endpoint=text)
        required=[]
        if verb=='set':
            properties.update(token_limit={'type':'integer','minimum':1},time_limit_seconds={'type':'integer','minimum':1});required=['token_limit','time_limit_seconds']
        result['local.self_limits.'+verb]=('wake_self_limits_'+verb,'Inspect or tighten voluntary own-session limits with automatic enforcement readiness.',schema(properties,required),partial(limits,verb),verb=='show')
    from .local_session_observation import definitions as observation_definitions
    result.update(observation_definitions())
    from .governor_commands import definitions as governor_definitions
    result.update(governor_definitions())
    from .unified_contract import local_aliases
    return local_aliases(result)


class LocalOperations:
    def __init__(self,root,*,native_endpoint='unix://'):
        self.root=root;self.native_endpoint=native_endpoint;self.definitions=definitions()

    def validated_arguments(self,operation,arguments):
        if operation not in self.definitions:raise InventoryError('unsupported_operation','operation is not in the local controller contract')
        tool,description,schema,handler,readonly=self.definitions[operation]
        if not Draft202012Validator(schema).is_valid(arguments):raise InventoryError('invalid_argument','arguments do not match the operation schema')
        arguments=dict(arguments)
        if 'endpoint' in schema['properties'] and arguments.get('harness','codex')=='codex' and arguments.get('endpoint','unix://')=='unix://':arguments['endpoint']=self.native_endpoint
        return arguments

    def execute(self,operation,arguments):
        arguments=self.validated_arguments(operation,arguments)
        return self.definitions[operation][3](arguments,self.root)

    def tools(self):
        return [dict(name=tool,description=description,inputSchema=schema,annotations={'readOnlyHint':readonly}) for tool,description,schema,handler,readonly in self.definitions.values()]

    def call_tool(self,name,arguments):
        names={value[0]:key for key,value in self.definitions.items()}
        if name not in names:raise InventoryError('unsupported_operation','local MCP tool is unavailable')
        return self.execute(names[name],arguments)


def contract():
    """Pure generated metadata for all local controller transports."""
    operations={}
    for operation,(tool,description,schema,handler,readonly) in definitions().items():
        if operation.startswith('local.governor.'):
            cli=['governor',operation.rsplit('.',1)[1]]
        elif operation.startswith('local.self_limits.'):
            cli=['self-limits',operation.rsplit('.',1)[1]]
        elif operation.startswith('environment.'):cli=operation.split('.')
        else:cli=['control',*operation.removeprefix('local.').split('.')]
        operations[operation]=dict(cli=cli,mcp_tool=tool,description=description,input_schema=schema,readonly=readonly)
    return dict(schema_version=1,operations=operations,
        local_only=['control.server.start','control.server.run','control.server.status','control.server.stop','control.connection','control.remote','control.powershell','control.mcp'],
        admission='Automatic same-user private connection; external OAuth connector grants are separate.',
        output_modes=['stream','transcript','final','silent'],
        transport_notes=dict(api='POST /operations; Accept application/x-ndjson for incremental frames.',mcp='POST /mcp or control mcp stdio bridge; bounded event batches and durable cursors.',native_mcp='Legacy full native tool server additionally binds self-limits to attested native caller context.'))
