"""Explicit native input policies with durable original-effect custody."""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import os
from websockets.exceptions import WebSocketException

from .managed_inventory import InventoryError
from .controller_runtime import ControllerRuntime, encoded, identity
from .daemon_commands import local_operator
from .local_sessions import resolve
from .local_session_operations import LocalSessionControl

POLICIES=('reject','queue','steer','interrupt_then_submit')
_TERMINAL={'completed':'completed','failed':'failed','interrupted':'cancelled'}


class SessionInputs:
    def __init__(self,root,*,request=None,authorize=None):
        self.root=Path(root)
        self.native=LocalSessionControl(root)
        self.request=request or self.native._request
        self.authorize=authorize
        self.runtime=ControllerRuntime(root)
        with self.runtime.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS native_input_effects (operation_id TEXT PRIMARY KEY, kind TEXT)')

    def _mark(self,identifier,kind):
        with self.runtime.connect() as db:
            db.execute('INSERT OR IGNORE INTO native_input_effects VALUES(?,?)',(identifier,kind))
            actual=db.execute('SELECT kind FROM native_input_effects WHERE operation_id=?',(identifier,)).fetchone()[0]
            if actual!=kind:raise InventoryError('effect_conflict','Original input effect kind changed.')

    def _effect(self,identifier):
        with self.runtime.connect() as db:
            row=db.execute('SELECT kind FROM native_input_effects WHERE operation_id=?',(identifier,)).fetchone()
        return row[0] if row else None

    def guard(self,row,action='control'):
        target=row['target']
        if target.get('uid')!=os.getuid() or Path(target['home']).stat().st_uid!=os.getuid():
            raise InventoryError('foreign_target','Native account is not owned by this user.')
        actor=self.authorize(target,action) if self.authorize is not None else local_operator(target,('control','observe','content.observe'))
        self.runtime.check_authority(actor,target,action,authorize=(lambda:self.authorize(target,action)) if self.authorize else None)
        return actor

    def thread(self,row):
        resolve(self.root,'thread:'+row['thread_id'],row['target'],endpoint=row['endpoint'])
        value=self.request(row,'thread/read',dict(threadId=row['thread_id'],includeTurns=True))['thread']
        if value.get('id')!=row['thread_id']:
            raise InventoryError('stale_target','Native thread identity changed.')
        return value

    @staticmethod
    def active(thread):
        return [t for t in thread.get('turns',[]) if t.get('status')=='inProgress']

    @staticmethod
    def terminal(thread,turn_id):
        return any(t.get('id')==turn_id and t.get('status') in _TERMINAL for t in thread.get('turns',[]))

    @staticmethod
    def _request_meta(identifier,key,target):
        return dict(operation_id=identifier,idempotency_key=key,correlation_id=identifier,
                    binding='explicit-session-input',target=target)

    def _start(self,row,prompt,client_id):
        self.guard(row)
        self._mark(client_id,'start')
        response=self.request(row,'turn/start',dict(threadId=row['thread_id'],clientUserMessageId=client_id,input=[dict(type='text',text=prompt)]))
        turn=response.get('turn',{})
        if not isinstance(turn.get('id'),str) or not turn['id'] or response.get('threadId',row['thread_id'])!=row['thread_id']:
            raise InventoryError('effect_unverified','Exact native turn acknowledgment required.')
        return dict(_pending=True,handle=dict(kind='native_turn',turn_id=turn['id'],client_message_id=client_id,
                                             composer='preserved',route='native_app_server',execution='not_observed'))

    def submit(self,selector,prompt,policy,idempotency_key,*,endpoint='unix://',expected_target=None):
        if policy not in POLICIES or not isinstance(prompt,str) or not 0<len(prompt.encode())<=32768 or not isinstance(idempotency_key,str) or not 0<len(idempotency_key)<=128:
            raise InventoryError('invalid_argument','Explicit bounded input policy, prompt and intent key required.')
        selected=resolve(self.root,selector,expected_target,endpoint=endpoint)
        row={k:selected[k] for k in ('thread_id','target','endpoint','codex_cmd')}
        actor=self.guard(row)
        identifier='session-input-'+hashlib.sha256(encoded([identity(actor),idempotency_key]).encode()).hexdigest()[:32]
        try:old=self.runtime._load(identifier)
        except InventoryError as error:
            if error.code!='operation_not_found':raise
            old=None
        if old is not None:
            if old['payload']['prompt']!=prompt or old['payload']['policy']!=policy or old['payload']['session']!=row:
                raise InventoryError('idempotency_conflict','Input key binds the original exact request.')
            self.runtime._owned(actor,old,lambda:self.guard(row),capability='control')
            return self.runtime.envelope('environment.conversations.input.submit',old)
        thread=self.thread(row)
        active=self.active(thread)
        state=thread.get('status',{}).get('type')
        if state not in ('idle','active'):
            raise InventoryError('session_unavailable','Native session is not qualified idle or active.')
        if policy=='reject' and state!='idle':
            raise InventoryError('session_busy','Native session is busy; reject policy sends no input.')
        if policy=='steer' and len(active)!=1:
            raise InventoryError('turn_unavailable','Steer requires one exact already-active turn; no prompt fallback.')
        if policy=='interrupt_then_submit' and state=='active' and len(active)!=1:
            raise InventoryError('turn_unavailable','Exact active native turn required.')
        payload=dict(session=row,prompt=prompt,policy=policy,active_turn_id=active[0]['id'] if len(active)==1 else None,
                     client_message_id=identifier)
        payload['_request']=self._request_meta(identifier,idempotency_key,row['target'])
        def dispatch(operation,args):
            self.guard(row)
            fresh=self.thread(row)
            fresh_state=fresh.get('status',{}).get('type')
            if fresh_state not in ('idle','active'):
                raise InventoryError('session_unavailable','Native input state became unqualified.')
            if policy=='queue':
                self._mark(identifier,'queue')
                response=self.request(row,'thread/queue/add',dict(threadId=row['thread_id'],clientUserMessageId=identifier,input=[dict(type='text',text=prompt)]))['queuedSubmission']
                items=response.get('input')
                if (response.get('clientUserMessageId')!=identifier or not isinstance(items,list) or len(items)!=1
                    or not isinstance(items[0],dict) or items[0].get('type')!='text' or items[0].get('text')!=prompt
                    or items[0].get('text_elements',[])!=[] or not isinstance(response.get('id'),str) or not 0<len(response['id'])<=256):
                    raise InventoryError('effect_unverified','Exact native queue acknowledgment required.')
                return dict(_pending=True,handle=dict(kind='native_queue',queue_id=response['id'],client_message_id=identifier,
                                                      composer='preserved',route='native_queue',execution='not_observed'))
            if policy=='reject':
                if fresh_state!='idle':raise InventoryError('session_busy','Reject policy refuses newly busy work.')
                return self._start(row,prompt,identifier)
            turns=self.active(fresh)
            if policy=='interrupt_then_submit' and fresh_state=='idle':
                if payload['active_turn_id'] and not self.terminal(fresh,payload['active_turn_id']):
                    raise InventoryError('stale_target','Original turn outcome is unqualified.')
                return self._start(row,prompt,identifier)
            if len(turns)!=1 or turns[0]['id']!=payload['active_turn_id']:
                raise InventoryError('stale_target','Active turn changed before input admission.')
            turn=turns[0]['id']
            if policy=='steer':
                self._mark(identifier,'steer')
                response=self.request(row,'turn/steer',dict(threadId=row['thread_id'],expectedTurnId=turn,input=[dict(type='text',text=prompt)]))
                if not isinstance(response,dict) or response.get('turnId',turn)!=turn:
                    raise InventoryError('effect_unverified','Steer acknowledgment belongs to another turn.')
                return dict(_pending=True,handle=dict(kind='native_steer',turn_id=turn,acceptance='native_steer_acknowledged',
                                                      composer='preserved',route='native_steer',execution='not_observed'))
            self.guard(row)
            self._mark(identifier,'interrupt')
            self.request(row,'turn/interrupt',dict(threadId=row['thread_id'],turnId=turn))
            return dict(_pending=True,handle=dict(kind='interrupt_then_submit',interrupted_turn_id=turn,
                                                  submission='waiting_for_confirmed_idle',composer='preserved',route='native_interrupt'))
        return self.runtime.execute(actor,'sessions.input',payload,authorize=lambda:self.guard(row),dispatch=dispatch)

    @contextmanager
    def _result_lock(self,identifier):
        directory=self.root/'controller-inputs'
        directory.mkdir(mode=0o700,exist_ok=True)
        path=directory/(hashlib.sha256(identifier.encode()).hexdigest()+'.lock')
        with os.fdopen(os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600),'a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True

    @staticmethod
    def _matched(thread,client_id,prompt):
        matches=[]
        for turn in thread.get('turns',[]):
            users=[i for i in turn.get('items',[]) if i.get('type')=='userMessage' and i.get('clientId')==client_id]
            if len(users)==1:
                content=users[0].get('content')
                if isinstance(content,list) and len(content)==1 and isinstance(content[0],dict) and content[0].get('type')=='text' and content[0].get('text')==prompt:matches.append(turn)
        return matches

    def _finish(self,record,turn):
        status=turn.get('status')
        if status in _TERMINAL:
            texts=[i['text'] for i in turn.get('items',[]) if i.get('type')=='agentMessage' and i.get('phase') in (None,'final_answer') and isinstance(i.get('text'),str)]
            text=(texts[-1] if texts else '').encode()
            record.update(phase='terminal',execution=_TERMINAL[status],delivery='retained',acceptance='owner_observed',reason=None,
                          answer=dict(text=text[:32768].decode(errors='replace'),truncated=len(text)>32768,source='native_turn',turn_id=turn['id']))
        elif status=='inProgress':record.update(phase='waiting',execution='running',delivery='submitted',acceptance='owner_observed',reason=None)

    def result(self,identifier):
        record=self.runtime._load(identifier)
        if record.get('operation')!='sessions.input':
            raise InventoryError('unsupported_operation','Original handle is not an input request.')
        row=record['payload']['session']
        actor=self.guard(row,'content.observe')
        self.runtime._owned(actor,record,lambda:self.guard(row,'content.observe'),capability='content.observe')
        if record['phase']=='terminal':return self.runtime.envelope('environment.conversations.input.result',record)
        with self._result_lock(identifier) as acquired:
            if not acquired:return self.runtime.envelope('environment.conversations.input.result',record)
            record=self.runtime._load(identifier)
            try:thread=self.thread(row)
            except (OSError,ValueError,WebSocketException) as error:
                if getattr(error,'code',None) in ('stale_target','foreign_target'):raise
                record.update(phase='uncertain',execution='unknown',reason='input_observation_unavailable')
                self.runtime._save(record)
                self.runtime._owned(self.guard(row,'content.observe'),record,lambda:self.guard(row,'content.observe'),capability='content.observe')
                return self.runtime.envelope('environment.conversations.input.result',record)
            handle=record.get('result') or {}
            policy=record['payload']['policy']
            original=record['payload']['active_turn_id']
            if policy=='interrupt_then_submit' and self._effect(identifier)=='interrupt' and handle.get('kind') not in ('native_turn','after_interrupt'):
                if thread.get('status',{}).get('type')=='idle' and (original is None or self.terminal(thread,original)):
                    self.guard(row)
                    child_id=identifier+'.after-interrupt'
                    payload=dict(session=row,prompt=record['payload']['prompt'],expected_target=row['target'])
                    payload['_request']=self._request_meta(child_id,child_id,row['target'])
                    def dispatch(operation,args):
                        fresh=self.thread(row)
                        if fresh.get('status',{}).get('type')!='idle' or original and not self.terminal(fresh,original):
                            raise InventoryError('stale_target','Original interruption is not confirmed idle.')
                        return self._start(row,args['prompt'],child_id)
                    child=self.runtime.execute(self.guard(row),'sessions.input.after_interrupt',payload,
                        authorize=lambda:self.guard(row),dispatch=dispatch)['result']['operation']
                    handle=dict(kind='after_interrupt',operation_id=child_id,client_message_id=child_id)
                    record['result']=handle
                    if child.get('result'):
                        handle.update(child['result'])
                        handle['operation_id']=child_id
                    if child['phase']=='uncertain':record.update(phase='uncertain',execution='unknown',reason=child.get('reason'))
            turn_id=handle.get('turn_id')
            if turn_id is None and policy!='steer':
                client_id=handle.get('client_message_id') or identifier
                matches=self._matched(thread,client_id,record['payload']['prompt'])
                if len(matches)==1:
                    turn_id=matches[0]['id']
                    record['result']=dict(handle,turn_id=turn_id,evidence='exact_client_message_id_and_input')
                elif len(matches)>1:
                    record.update(phase='uncertain',execution='unknown',reason='ambiguous_native_input_identity')
            # A lost steer acknowledgment cannot be inferred from a turn ending.
            if policy!='steer' or handle.get('acceptance')=='native_steer_acknowledged':
                turns=[t for t in thread.get('turns',[]) if t.get('id')==turn_id] if turn_id else []
                if len(turns)==1:
                    self._finish(record,turns[0])
                    if handle.get('operation_id')==identifier+'.after-interrupt':
                        child=self.runtime._load(handle['operation_id'])
                        self.runtime._owned(actor,child,lambda:self.guard(row,'content.observe'),capability='content.observe')
                        self._finish(child,turns[0])
                        self.runtime._save(child)
            self.runtime._save(record)
        self.runtime._owned(self.guard(row,'content.observe'),record,lambda:self.guard(row,'content.observe'),capability='content.observe')
        return self.runtime.envelope('environment.conversations.input.result',record)


def definitions():
    text={'type':'string','minLength':1}
    props=dict(selector=text,prompt=text,policy={'enum':list(POLICIES)},idempotency_key=text,endpoint=text,expected_target={'type':'object'})
    def submit(args,root):
        return SessionInputs(root).submit(args['selector'],args['prompt'],args['policy'],args['idempotency_key'],**{k:args[k] for k in ('endpoint','expected_target') if k in args})
    def result(args,root):return SessionInputs(root).result(args['operation_id'])
    return {'environment.conversations.input.submit':('wake_environment_conversations_input_submit','Submit one explicitly selected native busy-input policy; no fallback.',dict(type='object',properties=props,required=['selector','prompt','policy','idempotency_key'],additionalProperties=False),submit,False),
        'environment.conversations.input.result':('wake_environment_conversations_input_result','Observe original native input execution without replay.',dict(type='object',properties={'operation_id':text},required=['operation_id'],additionalProperties=False),result,True)}


def protected_operations():
    """Protected connector adapters retain actual caller identity and target scope."""
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    result={}
    for operation,(tool,description,schema,handler,readonly) in definitions().items():
        schema=deepcopy(schema)
        schema['properties'].pop('endpoint',None)
        if operation.endswith('.submit') and 'expected_target' not in schema['required']:
            schema['required'].append('expected_target')
        def invoke(authority,operations,token,operation,args):
            from .unified_connectors import protected_callback
            if operations.inventory is None:raise InventoryError('configuration_unavailable','host session owner unavailable')
            if not Draft202012Validator(result[operation][1]).is_valid(args):
                raise InventoryError('invalid_argument','protected input arguments do not match schema')
            owner=SessionInputs(operations.inventory.root,authorize=protected_callback(authority,token,operations))
            return owner.submit(**args) if operation.endswith('.submit') else owner.result(args['operation_id'])
        result[operation]=(tool,schema,'control' if operation.endswith('.submit') else 'content.observe',invoke)
    from .local_slash_commands import tool_specs
    for tool,(group,verb,description,properties,required,readonly) in tool_specs().items():
        operation='local.slash.'+verb
        properties=deepcopy(properties)
        for field in ('endpoint','harness','profile','mode','cursor'):
            properties.pop(field,None)
        required=list(required)
        if verb in ('list','run') and 'expected_target' not in required:required.append('expected_target')
        schema=dict(type='object',properties=properties,required=required,additionalProperties=False)
        def slash(authority,operations,token,operation,args):
            from .unified_connectors import protected_callback
            from .local_slash_commands import LocalSlashCommands
            if operations.inventory is None:raise InventoryError('configuration_unavailable','host slash owner unavailable')
            if not Draft202012Validator(result[operation][1]).is_valid(args):
                raise InventoryError('invalid_argument','protected slash arguments do not match schema')
            owner=LocalSlashCommands(operations.inventory.root,authorize=protected_callback(authority,token,operations))
            args=dict(args)
            verb=operation.rsplit('.',1)[1]
            if verb=='list':return owner.catalog(**args)
            if verb=='run':
                args['key']=args.pop('idempotency_key')
                args.setdefault('arguments','')
                return owner.run(**args)
            if verb=='result':return owner.result(args['operation_id'])
            if verb=='cancel':return owner.cancel(args['interaction_id'])
            return owner.respond(args['interaction_id'],args['value'],args['idempotency_key'])
        scope='observe' if verb=='list' else 'content.observe' if verb=='result' else 'control'
        result[operation]=(tool,schema,scope,slash)
    return result
