"""Conversation-scoped presentation moves through the existing whole-tab owner.

Parking a running client is not headless app-server execution. No native turn,
conversation/history, resource allowance or execution owner is replaced here.
"""
from functools import partial
import hashlib
import os
from pathlib import Path

from .controller_runtime import ControllerRuntime, encoded, identity
from .daemon_commands import local_operator
from .local_sessions import resolve
from .managed_inventory import InventoryError


class SessionPresentation:
    def __init__(self,root,*,tabs=None,authorize=None):
        if tabs is None:
            from .controller_tabs import controller_tabs_from_root
            tabs=controller_tabs_from_root(root)
        self.root,self.tabs,self.authorize=Path(root),tabs,authorize
        self.runtime=ControllerRuntime(root)

    def _guard(self,target):
        if self.authorize is not None:actor=self.authorize(target,'control')
        else:
            if self.root.stat().st_uid!=os.getuid() or target.get('host')!=self.tabs.host or target.get('environment')!=self.tabs.environment:
                raise InventoryError('foreign_target','same-user owning presentation host required')
            actor=local_operator(target)
        self.runtime.check_authority(actor,target,'control',authorize=(lambda:self.authorize(target,'control')) if self.authorize else None)
        return actor

    def _qualify(self,row,args):
        config=self.tabs.workspaces.get(args['workspace'],{})
        socket=getattr(config.get('transport'),'socket',None)
        native=resolve(self.root,'thread:'+row['thread_id'],row['target'],endpoint=row['endpoint'],socket_path=socket)
        views=self.tabs.execute('tabs.show',dict(workspace=args['workspace']))['resources']
        selected=[r for r in views if r['window']['window_id']==args['window']]
        if len(selected)!=1:
            raise InventoryError('stale_target','exact conversation tab is absent')
        selected=selected[0]
        if args['expected_presentation'] not in (selected['target'],selected['lifecycle_target']):
            raise InventoryError('stale_target','presentation generation changed')
        panes=selected['window']['panes']
        if len(panes)!=1:
            raise InventoryError('multi_conversation_tab','single-pane conversation attachment required; unrelated panes are never moved')
        pane=panes[0]
        if pane.get('process_generation') is None:
            raise InventoryError('attachment_unqualified','exact pane process generation unavailable')
        transport=self.tabs.workspaces[args['workspace']]['transport']
        socket=getattr(transport,'socket',None)
        bindings=[p for p in native.get('attachments',[]) if p.get('pane_id')==pane['pane_id'] and p.get('window_id',args['window'])==args['window'] and socket is not None and p.get('socket')==socket and p.get('evidence')=='metadata_matched']
        if len(bindings)!=1:
            raise InventoryError('attachment_unqualified','exact native conversation-to-terminal binding unavailable')
        for target in (args['expected_presentation'],args['expected_destination']):
            # Preserve account/conversation scope when authorizing a physical move.
            self._guard(dict(target,**{k:row['target'][k] for k in ('account','home','uid','conversation_id') if k in row['target']}))
        return selected

    def execute(self,operation,arguments):
        verb=operation.removeprefix('environment.conversations.presentation.')
        if verb not in ('background','foreground'):
            raise InventoryError('unsupported_operation','unsupported conversation presentation action')
        args=dict(arguments)
        allowed={'selector','expected_target','endpoint','workspace','window','expected_presentation','destination','expected_destination','idempotency_key','route','force','receipt_id'}
        required=allowed-{'endpoint','force','receipt_id'}
        if set(args)-allowed or not required<=args.keys():
            raise InventoryError('invalid_argument','exact conversation and source/destination presentation arguments required')
        expected_route='park_live' if verb=='background' else 'restore_live'
        if args['route']!=expected_route:
            raise InventoryError('unsupported_presentation_route','only explicit parked-live/restore-live route is qualified; headless detach is not silently substituted')
        if verb=='foreground' and (not isinstance(args.get('receipt_id'),str) or not args['receipt_id']):
            raise InventoryError('intent_required','foreground restoration requires its original parking receipt')
        if 'force' in args and type(args['force']) is not bool:
            raise InventoryError('invalid_argument','force must be explicit Boolean')
        if not isinstance(args['idempotency_key'],str) or not 0<len(args['idempotency_key'])<=128:
            raise InventoryError('intent_required','bounded original presentation intent key required')
        socket=getattr(self.tabs.workspaces.get(args['workspace'],{}).get('transport'),'socket',None)
        native=resolve(self.root,args['selector'],args['expected_target'],endpoint=args.get('endpoint','unix://'),socket_path=socket)
        row={k:native[k] for k in ('thread_id','target','endpoint','codex_cmd')}
        actor=self._guard(row['target'])
        identifier='session-presentation-'+hashlib.sha256(encoded([identity(actor),args['idempotency_key']]).encode()).hexdigest()[:32]
        payload=dict(args,session=row)
        meta=dict(operation_id=identifier,idempotency_key=args['idempotency_key'],correlation_id=identifier,
                  binding='conversation-presentation',target=row['target'])
        try:old=self.runtime._load(identifier)
        except InventoryError as error:
            if error.code!='operation_not_found':raise
            old=None
        if old is not None:
            self.runtime._owned(actor,old,lambda:self._guard(row['target']),capability='control')
            if old['operation']!=operation or old['payload']!=payload:
                raise InventoryError('idempotency_conflict','presentation key binds original conversation and placement')
            return self.runtime.envelope(operation,old)
        self._qualify(row,args)
        def dispatch(unused,inputs):
            self._qualify(row,args)
            physical={k:args[k] for k in ('workspace','window','destination','expected_destination','force','receipt_id') if k in args}
            physical['expected_target']=args['expected_presentation']
            result=self.tabs.execute('tabs.park' if verb=='background' else 'tabs.restore',physical)
            applied=result.get('status')=='applied'
            return dict(conversation_id=row['thread_id'],route=('parked_live_tui' if verb=='background' else 'foreground_live_tui') if applied else 'held',
                        requested_route=expected_route,headless=False,applied=applied,placement=result,
                        execution_owner='existing_runtime',turn_interrupted=False,history_deleted=False,
                        accounting_changed=False,scope='presentation_only')
        return self.runtime.execute(actor,operation,dict(payload,_request=meta),authorize=lambda:self._guard(row['target']),dispatch=dispatch)


def definitions():
    text=dict(type='string',minLength=1)
    properties=dict(selector=text,expected_target=dict(type='object'),endpoint=text,workspace=text,window=text,
                    expected_presentation=dict(type='object'),destination=text,expected_destination=dict(type='object'),
                    idempotency_key=text,route=dict(type='string'),force=dict(type='boolean'),receipt_id=text)
    required=[k for k in properties if k not in ('endpoint','force','receipt_id')]
    def invoke(verb,args,root):return SessionPresentation(root).execute('environment.conversations.presentation.'+verb,args)
    return {'environment.conversations.presentation.'+verb:('wake_environment_conversations_presentation_'+verb,
        'Move only an exactly bound single-pane conversation attachment; parked live TUI is not headless execution.',
        dict(type='object',properties=dict(properties,route=dict(type='string',enum=['park_live' if verb=='background' else 'restore_live'])),required=required+(['receipt_id'] if verb=='foreground' else []),additionalProperties=False),partial(invoke,verb),False)
        for verb in ('background','foreground')}


def protected_operations():
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    result={}
    for operation,(tool,description,schema,handler,readonly) in definitions().items():
        schema=deepcopy(schema)
        schema['properties'].pop('endpoint',None)
        def invoke(authority,operations,token,operation,args):
            from .unified_connectors import protected_callback
            if operations.inventory is None or operations.tabs is None:
                raise InventoryError('configuration_unavailable','host conversation/presentation owner unavailable')
            if not Draft202012Validator(result[operation][1]).is_valid(args):
                raise InventoryError('invalid_argument','protected presentation arguments do not match schema')
            owner=SessionPresentation(operations.inventory.root,tabs=operations.tabs,
                                      authorize=protected_callback(authority,token,operations))
            return owner.execute(operation,args)
        result[operation]=(tool,schema,'control',invoke)
    return result
