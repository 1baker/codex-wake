"""Program-callable Wake operations using the existing durable intent owners."""
from functools import partial
from pathlib import Path
import os
from .managed_inventory import InventoryError
from .recurring_schedules import ScheduleStore

class WakeControls:
    def __init__(self,root,*,principal,codex_path='codex',endpoint='unix://',authorize=None):
        self.root=Path(root);self.principal=principal;self.codex_path=codex_path;self.endpoint=endpoint;self.authorize=authorize
    def execute(self,operation,args):
        if self.authorize is not None:self.authorize(operation,args)
        if self.principal is None:raise InventoryError('permission_identity_unverified','Wake owner requires a verified principal.')
        store=ScheduleStore(self.root);verb=operation.rsplit('.',1)[-1]
        delegated=(lambda thread:self.authorize(operation,dict(thread_id=thread))) if self.authorize is not None else None
        if operation.startswith('wakes.intents.'):
            if verb not in ('after','at','file'):raise InventoryError('unsupported_operation','Unsupported intent operation.')
            request=dict(thread_id=args['thread_id'],prompt=args['prompt'],session_mode=args['session_mode'],delivery_window_seconds=args['delivery_window_seconds'])
            from .native_intents import retain
            native=store.native_args(request,2000000000,args['idempotency_key'],self.codex_path,self.endpoint)
            native.native_command=verb;native.trigger=args['trigger'];native._permission_principal=self.principal
            return retain(native,self.root)
        if operation not in definitions():raise InventoryError('unsupported_operation','Unsupported Wake operation.')
        if verb == 'bind_restoration':
            return store.bind_restoration(args['schedule_id'], profiles=args['profiles'],
                managed_agent_id=args['managed_agent_id'], profile=args['profile'],
                principal=self.principal, authorize=delegated)
        if verb=='register':return store.register(args['request'],codex_path=self.codex_path,endpoint=self.endpoint,principal=self.principal,authorize=delegated)
        if verb=='revise':return store.revise(args['schedule_id'],args['request'],args['expected_revision'],principal=self.principal,codex_path=self.codex_path,endpoint=self.endpoint,authorize=delegated)
        if verb=='cancel':return store.cancel(args['schedule_id'],args['expected_revision'],principal=self.principal,authorize=delegated)
        if verb=='show':
            value=store.read(args['schedule_id']);store.authorize(value,self.principal,delegated);return store.receipt(value)
        values=[]
        for value in store.records():
            try:store.authorize(value,self.principal,delegated)
            except ValueError:continue
            values.append(store.receipt(value))
        return values

def local_invoke(operation,args,root):
    from .session_permissions import Principal
    root=Path(root)
    if root.exists() and root.stat().st_uid!=os.getuid():raise InventoryError('foreign_target','Wake root belongs to another user.')
    return WakeControls(root,principal=Principal('local-operator','operator')).execute(operation,args)

def definitions():
    text={'type':'string','minLength':1};result={}
    for verb in ('register','list','show','revise','cancel','bind_restoration'):
        props={};required=[]
        if verb in ('register','revise'):props['request']={'type':'object'};required.append('request')
        if verb in ('show','revise','cancel','bind_restoration'):props['schedule_id']=text;required.append('schedule_id')
        if verb in ('revise','cancel'):props['expected_revision']={'type':'integer','minimum':1};required.append('expected_revision')
        if verb == 'bind_restoration':
            props.update(profiles=text, managed_agent_id=text, profile=text)
            required.extend(('profiles', 'managed_agent_id', 'profile'))
        operation='wakes.schedules.'+verb
        result[operation]=('wake_'+operation.replace('.','_'),'Control exact durable schedules without changing their timing or permission rules.',dict(type='object',properties=props,required=required,additionalProperties=False),partial(local_invoke,operation),verb in ('list','show'))
    for verb in ('after','at','file'):
        operation='wakes.intents.'+verb
        props=dict(thread_id=text,prompt=text,trigger=text,idempotency_key=text,session_mode={'enum':['session_only','reopen_live','background']},delivery_window_seconds={'type':'integer','minimum':1})
        result[operation]=('wake_'+operation.replace('.','_'),'Retain one explicit-mode native intent; retained readiness is not execution.',dict(type='object',properties=props,required=list(props),additionalProperties=False),partial(local_invoke,operation),False)
    return result


def protected_execute(authority,operations,token,operation,args):
    from .unified_connectors import protected_callback
    from .session_permissions import Principal
    from .controller_auth import AuthError
    actor=authority.authenticate(token)
    if operations.inventory is None:raise InventoryError('configuration_unavailable','Host Wake root is unavailable.')
    root=operations.inventory.root
    guard=protected_callback(authority,token,operations)
    scope='content.observe' if operation.endswith(('.list','.show')) else 'control'
    def authorize(verb,values):
        authority.authenticate(token)
        thread=values.get('thread_id') or values.get('request',{}).get('thread_id')
        if thread is None and 'schedule_id' in values:thread=ScheduleStore(root).read(values['schedule_id'])['request']['thread_id']
        if thread is not None:guard(dict(host=operations.host,environment=operations.environment,conversation_id=thread),scope)
        elif verb!='wakes.schedules.list':raise AuthError('insufficient_scope')
    role = 'controller'
    if operation == 'wakes.schedules.bind_restoration':
        if actor.principal_kind != 'owner' or 'admin' not in actor.scopes:
            raise AuthError('operator_required')
        role = 'operator'
    owner=WakeControls(root,principal=Principal(actor.subject,role),authorize=authorize)
    value=owner.execute(operation,args)
    authority.authenticate(token)
    if 'content.observe' not in actor.scopes and isinstance(value,dict):
        restoration=value.get('restoration')
        value={key:value[key] for key in ('id','revision','state','status','armed','next_due_at','session_mode','scheduling_status','monitor','persistence','delivery') if key in value}
        if restoration:
            value['restoration'] = {key: restoration[key] for key in ('status', 'reason') if key in restoration}
        value['content_redacted']=True
    return dict(schema_version=1,operation=operation,status='completed',result=value)

def protected_operations():
    return {operation:(tool,schema,'content.observe' if readonly else 'control',protected_execute)
            for operation,(tool,description,schema,handler,readonly) in definitions().items()}
