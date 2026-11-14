"""Frozen bulk programs lowered into the existing durable flow executor.

The flow owner only admits generated metadata. Every real action retains its
original authenticated protected owner and domain idempotency key.
"""
from copy import deepcopy
import hashlib
import re
from jsonschema import Draft202012Validator

from .controller_auth import AuthError
from .controller_flows import ControllerFlows
from .controller_runtime import ControllerRuntime,identity,encoded
from .managed_inventory import InventoryError
from .unified_connectors import check_action,permits


def _digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()


def _member_prefix(index):return 'm'+str(index).zfill(3)


def _inputs(value,inputs):
    if isinstance(value,dict) and set(value)=={'ref'}:
        path=value['ref']
        if not isinstance(path,str) or not path.startswith('inputs.'):
            raise InventoryError('invalid_bulk_input','bulk action inputs may reference only frozen inputs')
        current=inputs
        for key in path.split('.')[1:]:
            if not isinstance(current,dict) or key not in current:raise InventoryError('invalid_bulk_input','input reference is unavailable')
            current=current[key]
        return deepcopy(current)
    if isinstance(value,dict):return {key:_inputs(item,inputs) for key,item in value.items()}
    if isinstance(value,list):return [_inputs(item,inputs) for item in value]
    return value


def _owner_result(value):
    record=value.get('result',{}).get('operation',{}) if isinstance(value,dict) else {}
    if record.get('operation','').startswith('bulk.receipt.'):
        return record.get('result') or {}
    return value


def _failed(value):
    value=_owner_result(value)
    child=value.get('result',{}).get('operation',{})
    return value.get('status')=='failed' or child.get('phase')=='terminal' and child.get('execution') in ('failed','cancelled','not_started')


class _BulkFlow(ControllerFlows):
    """Only generated owned flow metadata is exempt from a separate flow-ID grant."""
    def __init__(self,*args,bulk_id,metadata_guard,**kwargs):
        self.bulk_id,self.metadata_guard=bulk_id,metadata_guard
        super().__init__(*args,**kwargs)

    def check(self,actor,flow_id,capability):
        if flow_id!=self.bulk_id or not flow_id.startswith('bulk_'):raise AuthError('insufficient_scope')
        return self.metadata_guard(capability)


class BulkControls:
    def __init__(self,authority,operations,token):
        if operations.inventory is None:raise InventoryError('configuration_unavailable','host bulk root unavailable')
        self.authority,self.operations,self.token=authority,operations,token
        self.root=operations.inventory.root
        self.principal=identity(authority.authenticate(token))
        self.action='programs.bulk.status'

    def _actor(self,scope):
        actor=check_action(self.authority.authenticate(self.token),self.action)
        if identity(actor)!=self.principal or scope not in actor.scopes:raise AuthError('insufficient_scope')
        return actor

    def _member(self,member):
        from .controller_http import ProtectedOperations
        actor=self._actor('control');check_action(actor,member['operation'])
        required=ProtectedOperations.READ_POLICIES[member['operation']][0]
        if required not in actor.scopes or not permits(actor,member['target']):raise AuthError('insufficient_scope')
        if member['target'].get('host')!=self.operations.host or member['target'].get('environment')!=self.operations.environment:
            raise InventoryError('wrong_environment','Bulk execution belongs to the owning host; route explicitly to that host.')
        return actor

    def _prepare(self,members,policies,inputs,intent):
        from .controller_http import TOOLS,ProtectedOperations
        from .unified_contract import original
        from .controller_flow_retry import policy
        if not isinstance(members,list) or not 1<=len(members)<=16:raise InventoryError('invalid_membership','explicit frozen membership1..16 required')
        if not isinstance(inputs,dict) or '_bulk' in inputs or len(encoded(inputs).encode())>65536:raise InventoryError('invalid_bulk_input','bounded object inputs required')
        if not isinstance(policies,dict) or set(policies)!={'failure','join','uncertain','retry'} or policies['failure'] not in ('stop','continue') or policies['join'] not in ('all_success','all_complete') or policies['uncertain']!='hold':
            raise InventoryError('invalid_bulk_policy','explicit failure/join/uncertain/retry policy required')
        retry=policies['retry']
        if not isinstance(retry,dict) or set(retry)!={'max_attempts','when'} or type(retry['max_attempts']) is not int or not 1<=retry['max_attempts']<=3 or not isinstance(retry['when'],list) or retry['max_attempts']==1 and retry['when']:
            raise InventoryError('invalid_retry','explicit finite retry policy required; never uses1attempt with no retry codes')
        result=[];ids=set();available={operation for operation,schema in TOOLS.values()}
        for index,source in enumerate(members):
            if not isinstance(source,dict) or set(source)-{'id','target','operation','arguments','completion','wait_operation','condition'} or not {'id','target','operation','arguments','completion'}<=source.keys():raise InventoryError('invalid_membership','typed explicit member required')
            if not isinstance(source['id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',source['id']) or source['id'] in ids:raise InventoryError('invalid_membership','unique bounded member IDs required')
            ids.add(source['id']);member=deepcopy(source);operation=original(member['operation'],available)
            if operation not in ProtectedOperations.READ_POLICIES or operation.startswith(('flows.','programs.bulk.','connectors.grants.')):raise InventoryError('unsupported_bulk_action','registered non-program child action required')
            declaration=next(schema for verb,schema in TOOLS.values() if verb==operation)
            target=member['target'];args=_inputs(member['arguments'],inputs)
            if not isinstance(target,dict) or not {'host','environment'}<=target.keys() or not isinstance(args,dict):raise InventoryError('invalid_membership','resolved host-qualified target and object arguments required')
            if '_request' in args:raise InventoryError('invalid_bulk_input','bulk owns original operation metadata')
            key='bulk-'+_digest([self.principal,intent,member['id']])
            supplied=None
            if 'idempotency_key' in declaration['properties']:
                supplied=args.get('idempotency_key');args['idempotency_key']=key
            if operation=='wakes.schedules.register':
                if set(target)!={'host','environment','conversation_id'} or not isinstance(args.get('request'),dict) or args['request'].get('thread_id')!=target['conversation_id']:raise InventoryError('stale_target','schedule member must pin its exact conversation target')
                supplied=args['request'].get('idempotency_key');args['request']['idempotency_key']=key
            elif operation.startswith('wakes.'):
                thread=args.get('thread_id') or args.get('request',{}).get('thread_id')
                if thread is None and 'schedule_id' in args:
                    from .recurring_schedules import ScheduleStore
                    thread=ScheduleStore(self.root).read(args['schedule_id'])['request']['thread_id']
                if set(target)!={'host','environment','conversation_id'} or target['conversation_id']!=thread:raise InventoryError('stale_target','wake member target differs from original conversation')
            elif 'expected_target' in declaration['properties']:
                expected=args.setdefault('expected_target',deepcopy(target))
                covered=dict(expected)
                pane=args.get('expected_pane')
                if isinstance(pane,dict):covered.update(pane_id=pane.get('pane_id'),pane_pid=pane.get('pid'),process_generation=pane.get('process_generation'))
                if any(covered.get(field)!=value for field,value in target.items()):raise InventoryError('stale_target','member target differs from the actual action target')
            elif set(target)!={'host','environment'}:
                raise InventoryError('unsupported_bulk_target','action has no qualified exact resource-target adapter')
            validation=dict(args)
            if '_request' in declaration['properties']:validation['_request']={}
            if not Draft202012Validator(declaration).is_valid(validation):raise InventoryError('invalid_argument','member arguments do not match public action schema')
            completion=member['completion']
            if completion not in ('admission','terminal'):raise InventoryError('invalid_bulk_policy','explicit admission or terminal completion required')
            if completion=='terminal' and member.get('wait_operation') not in ('operations.wait','sessions.wait','environment.conversations.input.result'):
                raise InventoryError('unsupported_bulk_wait','terminal completion requires a qualified original-handle wait owner')
            if completion=='admission' and 'wait_operation' in member:raise InventoryError('invalid_bulk_policy','admission completion does not select a wait owner')
            if retry['max_attempts']>1:policy(dict(operation=operation,retry=retry))
            member.update(index=index,operation=operation,arguments=args,domain_key=key,supplied_key=supplied,request_owner='_request' in declaration['properties'])
            self._member(member);result.append(member)
        return result

    def _flow(self,metadata):
        from .controller_http import ProtectedOperations
        protected=ProtectedOperations(self.authority,self.operations)
        members=metadata['members']
        def invoke(operation,args,*,authorize,request=None):
            authorize()
            identifier=(request or {}).get('operation_id') or args.get('operation_id','')
            match=re.search(r'\.m([0-9]+)_(call|wait)(?:\.try[0-9]+)?$',identifier)
            if not match:raise InventoryError('invalid_bulk_custody','child belongs to another run')
            member=members[int(match[1])];actor=self._member(member)
            if operation=='operations.result' and request is None and match[2]=='wait':
                # Wait nodes observe an existing owner handle, not a new effect.
                # Recover that handle from the durable completed call step.
                unused,state=self._load(identifier.rsplit('.m',1)[0])
                if state.get('child_operation_id')!=identifier:
                    raise InventoryError('invalid_bulk_custody','wait does not own this active attempt')
                prefix=_member_prefix(member['index'])
                original=_owner_result(state['steps'].get(prefix+'_call',{})).get('result',{}).get('operation',{})
                original_id=original.get('operation_id')
                if not isinstance(original_id,str):
                    raise InventoryError('invalid_bulk_custody','original wait handle is unavailable')
                value=protected.execute(self.token,member['wait_operation'],dict(operation_id=original_id))
                if value.get('result',{}).get('operation',{}).get('operation_id')!=original_id:
                    raise InventoryError('stale_target','wait owner returned a different operation')
            elif operation=='operations.result' and request is None:
                journal=ControllerRuntime(self.root)
                if member['operation']=='wakes.schedules.register' and not member['request_owner']:
                    def original_registration(record):
                        observed=protected.execute(self.token,'wakes.schedules.list',{})['result']
                        matches=[row for row in observed if row.get('request')==member['arguments']['request']]
                        return dict(schema_version=1,operation=member['operation'],status='completed',result=matches[0]) if len(matches)==1 else None
                    value=journal.reconcile_result(actor,args['operation_id'],expected_operation='bulk.receipt.'+member['operation'],
                        authorize=lambda:self._member(member),observe=original_registration,capability='control')
                else:value=journal.operation(actor,operation,args,authorize=lambda:self._member(member))
                owner_value=_owner_result(value)
                original_child=owner_value.get('result',{}).get('operation',{})
                wait_owner={'environment.conversations.input.submit':'environment.conversations.input.result',
                    'local.prompt':'local.result'}.get(member['operation'])
                if not member['request_owner'] and wait_owner and original_child.get('phase') in ('uncertain','executing','dispatching') and isinstance(original_child.get('operation_id'),str):
                    fresh=protected.execute(self.token,wait_owner,dict(operation_id=original_child['operation_id']))
                    if fresh.get('result',{}).get('operation',{}).get('operation_id')!=original_child['operation_id']:
                        raise InventoryError('stale_target','original owner returned a different operation')
                    value=dict(value,result=dict(value['result'],operation=dict(value['result']['operation'],result=fresh)))
            elif match[2]=='wait':
                check_action(actor,operation)
                args=dict(args)
                from .controller_http import TOOLS
                schema=next(schema for verb,schema in TOOLS.values() if verb==operation)
                if 'timeout' not in schema['properties']:args.pop('timeout',None)
                value=protected.execute(self.token,operation,args)
            elif member['request_owner']:
                if operation!=member['operation'] or args!=member['arguments']:raise InventoryError('invalid_bulk_custody','compiled action differs from frozen member')
                args=dict(args,_request=dict(request,target=member['target']))
                value=protected.execute(self.token,member['operation'],args)
            else:
                if operation!=member['operation'] or args!=member['arguments']:raise InventoryError('invalid_bulk_custody','compiled action differs from frozen member')
                # Reuse the established receipt journal, never a second executor.
                journal=ControllerRuntime(self.root)
                value=journal.execute(actor,'bulk.receipt.'+member['operation'],dict(arguments=args,_request=dict(request,target=member['target'])),
                    authorize=lambda:self._member(member),required_capability=ProtectedOperations.READ_POLICIES[member['operation']][0],
                    dispatch=lambda unused,payload:protected.execute(self.token,member['operation'],payload['arguments']))
            actual=_owner_result(value)
            nested=actual.get('result',{}).get('operation',{})
            if actual.get('status')=='held' or nested.get('phase') in ('uncertain','executing','dispatching'):
                value=dict(value,result=dict(value['result'],operation=dict(value['result']['operation'],phase='uncertain',reason=nested.get('reason') or 'child_effect_uncertain')))
            from .controller_flow_retry import READ_OPERATIONS
            record=value.get('result',{}).get('operation',{})
            reason=record.get('reason')
            if match[2]=='call' and member['operation'] in READ_OPERATIONS and record.get('phase')=='uncertain' and reason in metadata['policies']['retry']['when']:
                raise InventoryError(reason,'Explicit safe observational retry may advance under its original bound.')
            if _failed(value):value=dict(value,status='failed',error=_owner_result(value).get('error',{}))
            return value
        return _BulkFlow(self.root,host=self.operations.host,environment=self.operations.environment,
            invoke=invoke,authorize=lambda:self._actor('control'),bulk_id=metadata['flow_id'],
            metadata_guard=lambda capability:self._actor('content.observe' if self.action=='programs.bulk.result' else 'observe' if self.action=='programs.bulk.status' else 'control'))

    def start(self,*,members,policies,inputs,limits,intent,binding):
        self.action='programs.bulk.start';self._actor('control')
        from .controller_runtime import bounded_id
        bounded_id(intent);bounded_id(binding)
        frozen=self._prepare(members,policies,inputs,intent)
        flow_id='bulk_'+_digest([self.principal,intent])[:40]
        metadata=dict(schema_version=1,flow_id=flow_id,members=frozen,policies=deepcopy(policies),limits=deepcopy(limits),intent=intent,binding=binding,inputs=deepcopy(inputs))
        definition=self._definition(metadata)
        flow=self._flow(metadata);actor=self._actor('control')
        try:flow.publish(actor,definition)
        except InventoryError as error:
            if error.code=='immutable_flow_version':raise InventoryError('idempotency_conflict','bulk intent already pins another membership or policy') from None
            raise
        state=flow.start(actor,flow_id,1,inputs=dict(_bulk=metadata,**inputs),intent=intent,binding=binding)
        return self._projection(state,content=False)

    @staticmethod
    def _definition(metadata):
        nodes=[]
        for index,member in enumerate(metadata['members']):
            prefix=_member_prefix(index);after=_member_prefix(index+1)+'_guard' if index+1<len(metadata['members']) else 'done'
            nodes.append(dict(id=prefix+'_guard',type='branch',condition=member.get('condition',True),then=prefix+'_call',**{'else':after}))
            call=dict(id=prefix+'_call',type='call',operation=member['operation'],arguments=member['arguments'],failure=metadata['policies']['failure'],next=prefix+'_wait' if member['completion']=='terminal' else after)
            if metadata['policies']['retry']['max_attempts']>1:call['retry']=metadata['policies']['retry']
            nodes.append(call)
            if member['completion']=='terminal':
                path='steps.'+prefix+'_call.result.operation.'+('' if member['request_owner'] else 'result.result.operation.')+'operation_id'
                nodes.append(dict(id=prefix+'_wait',type='wait',operation=member['wait_operation'],operation_id={'ref':path},timeout=0,failure=metadata['policies']['failure'],next=after))
        nodes.append(dict(id='done',type='end',value=dict(completed=True)))
        return dict(id=metadata['flow_id'],version=1,entry='m000_guard',nodes=nodes,limits=metadata['limits'])

    def _load(self,run_id):
        probe=ControllerFlows(self.root,host=self.operations.host,environment=self.operations.environment,invoke=None,authorize=None)
        state=probe._load(run_id)
        metadata=state.get('inputs',{}).get('_bulk')
        if state.get('owner')!=self.principal or not isinstance(metadata,dict) or metadata.get('flow_id')!=state['flow_id'] or state['flow_id']!='bulk_'+_digest([self.principal,metadata.get('intent')])[:40]:raise AuthError('insufficient_scope')
        from .controller_flows import FlowDefinition
        try:expected=FlowDefinition.compile(self._definition(metadata))
        except (KeyError,TypeError,ValueError):raise AuthError('insufficient_scope') from None
        if expected.digest!=state['definition_sha256']:raise AuthError('insufficient_scope')
        actor=self._actor('content.observe' if self.action=='programs.bulk.result' else 'observe' if self.action=='programs.bulk.status' else 'control')
        for member in metadata['members']:
            if not permits(actor,member['target']):raise AuthError('insufficient_scope')
        return self._flow(metadata),state

    def _projection(self,state,*,content):
        metadata=state['inputs']['_bulk'];items=[]
        for member in metadata['members']:
            prefix=_member_prefix(member['index']);value=state['steps'].get(prefix+'_call')
            guard=state['steps'].get(prefix+'_guard',{})
            outcome='skipped' if guard.get('status')=='known' and guard.get('value') is False else 'not_started'
            result=None;receipt=None;error=None
            if value:
                receipt=value.get('result',{}).get('operation',{}).get('operation_id');owner=_owner_result(value);child=owner.get('result',{}).get('operation',{})
                outcome='failed' if _failed(value) else 'uncertain' if child.get('phase') in ('uncertain','executing','dispatching') else 'admitted' if child.get('phase')=='waiting' else 'completed'
                result=owner.get('result');error=owner.get('error',{}).get('code') or child.get('reason')
                waited=state['steps'].get(prefix+'_wait')
                if waited:
                    native=waited.get('result',{}).get('operation',{});outcome='failed' if _failed(waited) else 'completed' if native.get('phase')=='terminal' and native.get('execution')=='completed' else 'failed' if native.get('phase')=='terminal' else 'uncertain' if native.get('phase') in ('uncertain','executing','dispatching') else 'admitted'
                    result=waited.get('result')
                if state.get('executing_node')==prefix+'_wait' and state['phase'] in ('executing','uncertain','held'):
                    outcome='uncertain'
            elif state.get('executing_node') in (prefix+'_call',prefix+'_wait'):
                outcome='uncertain' if state['phase'] in ('executing','uncertain','held') else 'admitted'
                receipt=state.get('child_operation_id')
            item=dict(id=member['id'],target=member['target'],operation=member['operation'],completion=member['completion'],state=outcome,receipt_id=receipt,domain_key=member['domain_key'],error=error)
            if content:item['result']=result
            items.append(item)
        phase=state['phase']
        if phase=='completed' and metadata['policies']['join']=='all_success' and any(item['state']=='failed' for item in items):phase='failed'
        return dict(run_id=state['run_id'],phase=phase,reason=state.get('reason'),definition_sha256=state['definition_sha256'],policies=metadata['policies'],members=items,content_redacted=not content,
            condition_usage=state['condition_usage'],condition_registry_revision=state['condition_registry_revision'])

    def _read(self,run_id,verb):
        self.action='programs.bulk.'+verb;flow,state=self._load(run_id)
        if verb in ('advance','reconcile','cancel'):state=getattr(flow,verb)(self._actor('control'),run_id)
        elif verb=='result':state=flow.inspect(self._actor('content.observe'),run_id)
        else:state=flow.inspect(self._actor('observe'),run_id)
        return self._projection(state,content=verb=='result')

    def status(self,run_id):return self._read(run_id,'status')
    def result(self,run_id):return self._read(run_id,'result')
    def advance(self,run_id):return self._read(run_id,'advance')
    def reconcile(self,run_id):return self._read(run_id,'reconcile')
    def cancel(self,run_id):return self._read(run_id,'cancel')


def protected_operations():
    def invoke(authority,operations,token,operation,args):
        owner=BulkControls(authority,operations,token);verb=operation.rsplit('.',1)[-1]
        if not Draft202012Validator(result[operation][1]).is_valid(args):raise InventoryError('invalid_argument','bulk arguments do not match schema')
        value=owner.start(**args) if verb=='start' else getattr(owner,verb)(args['run_id'])
        return dict(schema_version=1,operation=operation,status='completed',result=value)
    result={}
    for verb in ('start','status','result','advance','reconcile','cancel'):
        member=dict(type='object',properties=dict(id=dict(type='string',pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),target={'type':'object'},operation={'type':'string'},arguments={'type':'object'},completion={'enum':['admission','terminal']},wait_operation={'enum':['operations.wait','sessions.wait','environment.conversations.input.result']},condition={'type':['boolean','object']}),required=['id','target','operation','arguments','completion'],additionalProperties=False)
        retry=dict(type='object',properties=dict(max_attempts=dict(type='integer',minimum=1,maximum=3),when=dict(type='array',items={'enum':['timeout','unavailable','source_unavailable','native_unavailable']},maxItems=4)),required=['max_attempts','when'],additionalProperties=False)
        policies=dict(type='object',properties=dict(failure={'enum':['stop','continue']},join={'enum':['all_success','all_complete']},uncertain={'const':'hold'},retry=retry),required=['failure','join','uncertain','retry'],additionalProperties=False)
        text=dict(type='string',minLength=1,maxLength=200)
        properties=dict(members={'type':'array','items':member,'minItems':1,'maxItems':16},policies=policies,inputs={'type':'object'},limits={'type':'object'},intent=text,binding=text) if verb=='start' else dict(run_id=text)
        operation='programs.bulk.'+verb;schema=dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
        result[operation]=('wake_'+operation.replace('.','_'),schema,'content.observe' if verb=='result' else 'observe' if verb=='status' else 'control',invoke)
    return result


def definitions():
    def protected_only(args,root):raise InventoryError('authenticated_transport_required','Bulk actions require the existing authenticated controller identity.')
    return {operation:(tool,'Run frozen members through the existing durable program executor.',schema,protected_only,operation.endswith(('.status','.result')))
        for operation,(tool,schema,required,handler) in protected_operations().items()}
