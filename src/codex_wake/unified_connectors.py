"""Delegated connector controls retain OAuth identity and target attenuation."""
from copy import deepcopy
import re
import hashlib
import json
from jsonschema import Draft202012Validator
from .controller_auth import AuthError
from .managed_inventory import InventoryError


def canonical_actions(actions):
    from .unified_contract import canonical
    if not isinstance(actions,list) or not 1<=len(actions)<=256 or any(not isinstance(a,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,255}',a) for a in actions):
        raise AuthError('invalid_request','explicit bounded operation actions required')
    return frozenset(canonical(action) for action in actions)


def intersect_targets(granted,requested):
    if not isinstance(requested,list) or not requested or len(requested)>256:raise AuthError('invalid_target')
    result=[]
    for wanted in requested:
        if not isinstance(wanted,dict) or not wanted:raise AuthError('invalid_target')
        matches=[dict(parent,**wanted) for parent in granted if not any(key in parent and parent[key]!=value for key,value in wanted.items())]
        if not matches:raise AuthError('insufficient_scope')
        for item in matches:
            if item not in result:result.append(item)
    return result


def check_action(actor,operation):
    from .unified_contract import canonical
    if actor.actions is not None and canonical(operation) not in actor.actions:
        raise AuthError('insufficient_scope')
    return actor


def delegated_content_scope(operation):
    content={'tabs.capture','history.read','operations.result','operations.wait','operations.stream','sessions.wait','grok.wait','grok.prompt',
             'flows.definition','flows.inspect','flows.start','flows.advance','flows.reconcile','flows.cancel'}
    return 'terminal.input' if operation in ('tabs.input','runtime.input') else 'content.observe' if operation in content else None


def check_legacy_content(actor,operation):
    """New attenuated grants cannot use compatibility routes to bypass RW scopes."""
    required=delegated_content_scope(operation)
    if actor.delegated and required is not None and required not in actor.scopes:raise AuthError('insufficient_scope')
    return actor


def permits(actor,target):
    return any(all(target.get(key)==value for key,value in scope.items()) for scope in actor.targets)


def protected_callback(authority,token,operations):
    def authorize(target,action):
        actor=authority.authenticate(token)
        required='content.observe' if action=='content' else action
        if required not in actor.scopes or not permits(actor,target):raise AuthError('insufficient_scope')
        if target.get('host')!=operations.host or target.get('environment')!=operations.environment:
            raise AuthError('insufficient_scope')
        return actor
    return authorize


def _schema(properties,required=()):
    return dict(type='object',properties=properties,required=list(required),additionalProperties=False)


def schemas():
    text=dict(type='string',minLength=1,maxLength=4096)
    return {
        'connectors.grants.create':_schema(dict(mode={'enum':['full','subset']},idempotency_key=dict(type='string',minLength=1,maxLength=128),client_id=text,redirect_uri=text,code_challenge=text,
            scopes=dict(type='array',items=text,minItems=1),targets=dict(type='array',items={'type':'object'},minItems=1),actions=dict(type='array',items=text,minItems=1),expires_in=dict(type='integer',minimum=1,maximum=86400)),['mode','idempotency_key','client_id','redirect_uri','code_challenge']),
        'connectors.grants.list':_schema({}),
        'connectors.grants.show':_schema(dict(grant_id=text),['grant_id']),
        'connectors.grants.revoke':_schema(dict(grant_id=text),['grant_id']),
        'environment.snapshot':_schema({}),
        'environment.children':_schema(dict(resource_id=text),['resource_id']),
    }


class UnifiedConnectors:
    def __init__(self,authority,operations):self.authority,self.operations=authority,operations

    def execute(self,token,operation,arguments):
        actor=check_action(self.authority.authenticate(token),operation)
        schema=schemas().get(operation)
        if schema is None or not Draft202012Validator(schema).is_valid(arguments):raise InventoryError('invalid_argument','arguments do not match connector operation')
        if operation=='connectors.grants.create':
            value=self.issue_once(actor,arguments)
        elif operation=='connectors.grants.list':value=dict(grants=self.authority.grant_metadata(actor))
        elif operation=='connectors.grants.show':value=dict(grant=self.authority.grant_metadata(actor,arguments['grant_id']))
        elif operation=='connectors.grants.revoke':
            self.authority.grant_metadata(actor,arguments['grant_id'])
            value=self.authority.revoke_grant(arguments['grant_id'])
            return dict(schema_version=1,operation=operation,status='completed',result=value)
        else:value=self.environment(actor,operation,arguments)
        check_action(self.authority.authenticate(token),operation)
        return dict(schema_version=1,operation=operation,status='completed',result=value)

    def issue_once(self,actor,arguments):
        if actor.principal_kind!='owner' or 'admin' not in actor.scopes:raise AuthError('operator_required')
        args=dict(arguments);key=args.pop('idempotency_key')
        intent=hashlib.sha256((actor.grant_id+'\0'+key).encode()).hexdigest()
        fingerprint=hashlib.sha256(json.dumps(args,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.authority.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT fingerprint,result FROM delegation_intents WHERE intent=?',(intent,)).fetchone()
            if previous:
                if previous[0]!=fingerprint:raise InventoryError('idempotency_conflict','grant intent already names another delegation')
                if previous[1] is None:raise InventoryError('grant_issuance_uncertain','original issuance requires operator reconciliation; no new grant issued')
                retained=json.loads(previous[1])
                if 'creation_error' in retained:raise AuthError(retained['creation_error'])
                return retained
            db.execute('INSERT INTO delegation_intents VALUES(?,?,NULL)',(intent,fingerprint))
        # Admission is durable before credentials are created. An interrupted
        # issuance remains uncertain rather than silently creating another grant.
        try:value=self.authority.delegate(actor,**args)
        except AuthError as error:
            with self.authority.connect() as db:
                db.execute('UPDATE delegation_intents SET result=? WHERE intent=?',(json.dumps(dict(creation_error=error.code)),intent))
            raise
        with self.authority.connect() as db:
            db.execute('UPDATE delegation_intents SET result=? WHERE intent=?',(json.dumps(value),intent))
        return value

    def environment(self,actor,operation,arguments):
        from .unified_environment import Environment
        if self.operations.tabs is None:raise InventoryError('configuration_unavailable','host presentation owner unavailable')
        view=Environment(self.operations.tabs.root,tabs=self.operations.tabs).snapshot()
        host=dict(host=self.operations.host,environment=self.operations.environment)
        broad=permits(actor,host)
        visible=[]
        def tab(row):
            target=dict(row['target'],resource_id=row['id'],window_id=row['native_id'],tab_id=row['native_id'])
            panes=[pane for pane in row['panes'] if permits(actor,dict(target,pane_id=pane['pane_id']))]
            if permits(actor,target) or panes:return dict(row,panes=panes)
            return None
        for session in view['sessions']:
            target=dict(host,resource_id=session['id'],terminal_session_id=session['id'])
            if session.get('workspace') is not None:target['workspace']=session['workspace']
            tabs=[filtered for row in session['tabs'] if (filtered:=tab(row)) is not None]
            if broad or permits(actor,target) or tabs:visible.append(dict(session,tabs=tabs))
        view['sessions']=visible
        view['unplaced_tabs']=[filtered for row in view['unplaced_tabs'] if (filtered:=tab(row)) is not None]
        view['agents']=[row for row in view['agents'] if broad or permits(actor,dict(host,bot_id=row['bot_id']))]
        view['bindings']=[row for row in view['bindings'] if broad or isinstance(row.get('target'),dict) and permits(actor,row['target'])]
        if not broad:view['unavailable']=[]
        if operation=='environment.snapshot':return view
        selected=arguments['resource_id']
        for session in view['sessions']:
            if session['id']==selected:return dict(kind='tabs',children=session['tabs'])
            for row in session['tabs']:
                if row['id']==selected:return dict(kind='panes',children=row['panes'])
        if any(row['bot_id']==selected for row in view['agents']):
            return dict(kind='agents',children=[row for row in view['agents'] if row.get('parent_bot_id')==selected])
        raise InventoryError('target_not_found','resource is absent from permitted environment')


def protected_operations():
    result={}
    for operation,schema in schemas().items():
        required='admin' if operation in ('connectors.grants.create','connectors.grants.revoke') else 'observe'
        def handler(authority,operations,token,operation,args):
            return UnifiedConnectors(authority,operations).execute(token,operation,args)
        result[operation]=('wake_'+operation.replace('.','_'),schema,required,handler)
    from .local_session_observation import definitions as observations
    for operation,(tool,description,schema,unused_handler,readonly) in observations().items():
        schema=deepcopy(schema)
        if operation=='local.observe':
            schema['properties'].pop('endpoint',None)
            schema['required']=[*schema['required'],'expected_target']
        def observe(authority,operations,token,operation,args):
            from .local_session_observation import SessionObservations
            if operations.inventory is None:raise InventoryError('configuration_unavailable','host observation owner unavailable')
            owner=SessionObservations(operations.inventory.root,authorize=protected_callback(authority,token,operations))
            if operation=='local.observe':return owner.observe(**args)
            args=dict(args);identifier=args.pop('observation_id')
            return owner.cancel(identifier) if operation=='local.observation.cancel' else owner.output(identifier,**args)
        def validated(authority,operations,token,operation,args):
            declaration=result[operation][1]
            if not Draft202012Validator(declaration).is_valid(args):raise InventoryError('invalid_argument','protected observation arguments do not match its schema')
            return observe(authority,operations,token,operation,args)
        result[operation]=(tool,schema,'content.observe',validated)
    return result


def definitions():
    """Discovery shares schemas; grant administration requires OAuth operator identity."""
    def protected_only(arguments,root):
        raise InventoryError('operator_transport_required','Use the authenticated controller route; native arguments cannot select an operator role.')
    return {operation:(tool,'Manage connector identity/grants under authenticated operator authority.',schema,protected_only,operation.endswith(('.list','.show')))
        for operation,(tool,schema,required,handler) in protected_operations().items() if operation.startswith('connectors.')}
