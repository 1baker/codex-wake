"""Explicit host-owned terminal content and input, separate from harness actions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from .controller_runtime import ControllerRuntime, encoded, identity
from .managed_inventory import InventoryError


KEY_TOKENS = frozenset({'Enter','Escape','Tab','BTab','BSpace','DC','Home','End','Up','Down','Left','Right','PageUp','PageDown'} |
                       {'C-'+chr(c) for c in range(ord('a'),ord('z')+1)} |
                       {'F'+str(n) for n in range(1,13)})


class TerminalControl:
    def __init__(self, root, *, tabs=None, authorize=None):
        if tabs is None:
            from .controller_tabs import controller_tabs_from_root
            tabs = controller_tabs_from_root(root)
        self.root, self.tabs, self.authorize = Path(root), tabs, authorize
        self.runtime = ControllerRuntime(root)
        with self.runtime.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS terminal_observations (id TEXT PRIMARY KEY, record TEXT)')

    def _admit(self, target, action):
        if self.authorize is None:
            raise InventoryError('permission_required', 'explicit terminal content/input authorization required')
        actor = self.authorize(target, action)
        self.runtime.check_authority(actor, target, action, authorize=lambda:self.authorize(target, action))
        return actor

    def _inspect(self, workspace, pane, expected_target, expected_pane, *, strict=True, server_identity=None):
        if workspace not in self.tabs.workspaces:
            raise InventoryError('unsupported_target', 'workspace is not host enrolled')
        rows = self.tabs.execute('tabs.show', dict(workspace=workspace))['resources']
        found = [(r,p) for r in rows for p in r['window']['panes'] if p['pane_id'] == pane]
        if len(found) != 1:
            raise InventoryError('stale_target', 'exact pane is absent or ambiguous')
        row, current = found[0]
        birth = {k:current[k] for k in ('pane_id','pid','process_generation') if k in current}
        if not isinstance(expected_pane,dict) or not {'pane_id','pid','process_generation'} <= expected_pane.keys() or expected_pane.get('process_generation') is None or expected_pane != birth:
            raise InventoryError('stale_target', 'exact pane process generation required')
        target = row['target']
        keys = ('host','environment','workspace','presentation','generation') if strict else ('host','environment','workspace','presentation')
        if not isinstance(expected_target,dict) or any(expected_target.get(k) != target.get(k) for k in keys):
            raise InventoryError('stale_target', 'exact owning host and presentation generation required')
        config = self.tabs.workspaces[workspace]
        snapshot = config['transport'].snapshot(time.monotonic()+5)
        server = {k:snapshot[k] for k in ('server','session_id','socket_identity','bridge_generation') if k in snapshot}
        if not server or server_identity is not None and server != server_identity:
            raise InventoryError('stale_target', 'terminal server generation changed')
        selected = dict(target,pane_id=pane,pane_pid=current['pid'],process_generation=current.get('process_generation'),
                        window_id=row['window']['window_id'],server_identity=server)
        return row,config,selected,birth

    def capture(self, workspace, pane, expected_target, expected_pane, lines=50):
        row,config,target,birth = self._inspect(workspace,pane,expected_target,expected_pane)
        self._admit(target,'content.observe')
        value = self.tabs.execute('tabs.capture',dict(workspace=workspace,pane=pane,expected_target=row['target'],lines=lines))
        self._admit(target,'content.observe')
        text = value['text'].encode()
        return dict(target=target,pane=birth,text=text[-32768:].decode(errors='replace'),
                    truncated=value.get('truncated',False) or len(text)>32768,
                    provenance='rendered_terminal_capture',semantic_execution='unknown',
                    capabilities=dict(raw_terminal_byte_stream=False,rendered_snapshots=True,
                                      input_modes=value.get('input_custody',{}).get('input_modes',[]),
                                      input_permission='terminal.input',key_tokens=sorted(KEY_TOKENS)))

    def _load(self, identifier):
        if not isinstance(identifier,str) or not 0 < len(identifier) <= 128:
            raise InventoryError('invalid_argument','bounded terminal observation identity required')
        with self.runtime.connect() as db:
            row = db.execute('SELECT record FROM terminal_observations WHERE id=?',(identifier,)).fetchone()
        if row is None:
            raise InventoryError('observation_not_found','original terminal observation unavailable')
        return json.loads(row[0])

    def observe(self, workspace, pane, expected_target, expected_pane, *, lines=50,
                idempotency_key=None, max_events=256, max_bytes=1048576):
        if type(max_events) is not int or not 1 <= max_events <= 2048 or type(max_bytes) is not int or not 1024 <= max_bytes <= 2097152:
            raise InventoryError('invalid_argument','bounded terminal retention required')
        key = idempotency_key or uuid4().hex
        if not isinstance(key,str) or not 0 < len(key) <= 128:
            raise InventoryError('invalid_argument','bounded terminal observation key required')
        captured = self.capture(workspace,pane,expected_target,expected_pane,lines)
        actor = self._admit(captured['target'],'content.observe')
        identifier = 'terminal-observation-'+hashlib.sha256(encoded([identity(actor),key]).encode()).hexdigest()[:32]
        intent = dict(workspace=workspace,pane=pane,expected_target=expected_target,expected_pane=expected_pane,lines=lines,max_events=max_events,max_bytes=max_bytes)
        record = dict(observation_id=identifier,intent=intent,target=captured['target'],principal=identity(actor),
                      sequence=0,events=[],snapshot=None,truncated=False,history_gap=True)
        with self.runtime.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT record FROM terminal_observations WHERE id=?',(identifier,)).fetchone()
            if previous:
                record = json.loads(previous[0])
                if record['intent'] != intent:
                    raise InventoryError('idempotency_conflict','key binds another terminal observation')
            else:
                db.execute('INSERT INTO terminal_observations VALUES(?,?)',(identifier,encoded(record)))
        return self.output(identifier)

    def output(self, observation_id, cursor=0, limit=100):
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise InventoryError('invalid_argument','bounded terminal cursor and page limit required')
        record = self._load(observation_id)
        actor = self._admit(record['target'],'content.observe')
        if identity(actor) != record['principal']:
            raise InventoryError('permission_required','observation belongs to another authenticated principal')
        if cursor > record['sequence']:
            raise InventoryError('invalid_cursor','cursor is beyond terminal observation history')
        intent = record['intent']
        row,config,target,birth = self._inspect(intent['workspace'],intent['pane'],intent['expected_target'],intent['expected_pane'],
                                               strict=False,server_identity=record['target']['server_identity'])
        started = time.monotonic_ns()
        captured = self.capture(intent['workspace'],intent['pane'],row['target'],birth,intent['lines'])
        with self.runtime.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = json.loads(db.execute('SELECT record FROM terminal_observations WHERE id=?',(observation_id,)).fetchone()[0])
            if started >= record.get('last_observation',0):
                old = (record['snapshot'] or {}).get('text')
                text = captured['text']
                if old != text:
                    append = old is not None and text.startswith(old)
                    record['sequence'] += 1
                    record['events'].append(dict(sequence=record['sequence'],kind='append' if append else 'replace',
                                                  text=text[len(old):] if append else text,provenance='rendered_terminal_capture',
                                                  observed_at=time.time()))
                    while record['events'] and (len(record['events'])>intent['max_events'] or len(encoded(record['events']).encode())>intent['max_bytes']):
                        record['events'].pop(0);record['truncated']=True
                    if not append:record['history_gap']=True
                record.update(snapshot=captured,last_observation=started)
                db.execute('UPDATE terminal_observations SET record=? WHERE id=?',(encoded(record),observation_id))
        current_actor = self._admit(target,'content.observe')
        if identity(current_actor) != record['principal']:
            raise InventoryError('permission_required','observation principal changed before delivery')
        events = [e for e in record['events'] if e['sequence']>cursor][:limit]
        first = record['events'][0]['sequence']-1 if record['events'] else record['sequence']
        return dict(observation_id=observation_id,target=target,snapshot=record['snapshot'],events=events,
                    next_cursor=events[-1]['sequence'] if events else cursor,latest_cursor=record['sequence'],
                    capabilities=dict(raw_terminal_byte_stream=False,rendered_snapshots=True),
                    retention=dict(max_events=intent['max_events'],max_bytes=intent['max_bytes'],earliest_cursor=first,
                                   cursor_gap=cursor<first,history_gap=record['history_gap'],truncated=record['truncated'],history_complete=False))

    def _write(self, mode, workspace, pane, expected_target, expected_pane, custody, value, idempotency_key):
        if not isinstance(idempotency_key,str) or not 0 < len(idempotency_key) <= 128:
            raise InventoryError('intent_required','explicit bounded terminal input key required')
        if mode=='paste':
            if not isinstance(value,str) or not value or len(value.encode())>16384 or '\x00' in value:
                raise InventoryError('invalid_argument','literal paste must be1..16384UTF8 bytes without NUL')
        else:
            if not isinstance(value,list) or not 1<=len(value)<=32 or any(not isinstance(k,str) or k not in KEY_TOKENS for k in value):
                raise InventoryError('invalid_argument','explicit supported terminal key tokens required')
        row,config,target,birth=self._inspect(workspace,pane,expected_target,expected_pane)
        actor=self._admit(target,'terminal.input')
        def qualify():
            current_row,current_config,current_target,_=self._inspect(workspace,pane,expected_target,expected_pane)
            if current_target!=target:
                raise InventoryError('stale_target','pane changed before terminal input')
            privacy=current_config.get('privacy')
            if privacy is None or privacy(pane)!='safe':
                raise InventoryError('presentation_privacy_unknown','private input, draft or unqualified privacy prevents terminal input')
            broker=current_config.get('broker')
            if broker is None or broker.inspect()!=custody or not custody.get('available') or custody.get('transport')!='terminal':
                raise InventoryError('input_custody_required','exact host-owned terminal broker custody required')
            action=getattr(broker,mode,None)
            if action is None or mode not in custody.get('input_modes',[]):
                raise InventoryError('unsupported_transport','broker has no explicit terminal action; no fallback')
            return action
        qualify()
        identifier='terminal-input-'+hashlib.sha256(encoded([identity(actor),idempotency_key]).encode()).hexdigest()[:32]
        payload=dict(workspace=workspace,pane=pane,expected_target=target,expected_pane=expected_pane,custody=custody,input_mode=mode,value=value)
        payload['_request']=dict(operation_id=identifier,idempotency_key=idempotency_key,correlation_id=identifier,
                                 binding='explicit-terminal-input',target=target)
        def dispatch(operation,arguments):
            self._admit(target,'terminal.input')
            result=qualify()(pane,value,expected_custody=custody)
            return dict(target=target,delivery=result,input_mode=mode,implicit_enter=False,
                        semantic_execution='unknown',fallback=False)
        return self.runtime.execute(actor,'environment.panes.'+mode,payload,
            authorize=lambda:self.authorize(target,'terminal.input'),dispatch=dispatch,required_capability='terminal.input')

    def paste(self, workspace, pane, expected_target, expected_pane, custody, text, idempotency_key):
        return self._write('paste',workspace,pane,expected_target,expected_pane,custody,text,idempotency_key)

    def keys(self, workspace, pane, expected_target, expected_pane, custody, keys, idempotency_key):
        return self._write('keys',workspace,pane,expected_target,expected_pane,custody,keys,idempotency_key)

    def execute(self, operation, arguments):
        verb = operation.removeprefix('environment.panes.')
        if verb not in ('capture','observe','output','paste','keys'):
            raise InventoryError('unsupported_operation','unsupported explicit terminal operation')
        return getattr(self,verb)(**arguments)


def definitions():
    """Same-user definitions; protected routes must inject their authenticated actor."""
    from functools import partial
    def invoke(verb,args,root):
        owner=TerminalControl(root)
        def authorize(target,action):
            if Path(root).stat().st_uid!=os.getuid() or target.get('host')!=owner.tabs.host or target.get('environment')!=owner.tabs.environment:
                raise InventoryError('permission_required','same-user host target ownership required')
            from .daemon_commands import local_operator
            return local_operator(target,('content.observe','terminal.input'))
        owner.authorize=authorize
        return owner.execute('environment.panes.'+verb,args)
    text=dict(type='string',minLength=1,maxLength=4096)
    base=dict(workspace=text,pane=text,expected_target=dict(type='object'),expected_pane=dict(type='object'))
    required=list(base)
    def schema(properties,needed):
        return dict(type='object',properties=properties,required=needed,additionalProperties=False)
    contracts={
        'capture':schema(dict(base,lines=dict(type='integer',minimum=1,maximum=200)),required),
        'observe':schema(dict(base,lines=dict(type='integer',minimum=1,maximum=200),idempotency_key=dict(type='string',minLength=1,maxLength=128),max_events=dict(type='integer',minimum=1,maximum=2048),max_bytes=dict(type='integer',minimum=1024,maximum=2097152)),required),
        'output':schema(dict(observation_id=text,cursor=dict(type='integer',minimum=0),limit=dict(type='integer',minimum=1,maximum=100)),['observation_id']),
        'paste':schema(dict(base,custody=dict(type='object'),text=dict(type='string',minLength=1,maxLength=16384),idempotency_key=dict(type='string',minLength=1,maxLength=128)),required+['custody','text','idempotency_key']),
        'keys':schema(dict(base,custody=dict(type='object'),keys=dict(type='array',minItems=1,maxItems=32,items=dict(type='string',enum=sorted(KEY_TOKENS))),idempotency_key=dict(type='string',minLength=1,maxLength=128)),required+['custody','keys','idempotency_key']),
    }
    return {'environment.panes.'+verb:('wake_environment_panes_'+verb,
        'Explicit terminal content/input with host/pane generations, privacy and separate permissions; rendered snapshots are not native byte streams and delivery is not semantic execution.',
        contract,partial(invoke,verb),verb not in ('paste','keys')) for verb,contract in contracts.items()}


def protected_operations():
    result={}
    for operation,(tool,description,schema,handler,readonly) in definitions().items():
        def invoke(authority,operations,token,operation,args):
            from .unified_connectors import protected_callback
            if operations.tabs is None or operations.inventory is None:
                raise InventoryError('configuration_unavailable','Host terminal owner is unavailable.')
            value=TerminalControl(operations.inventory.root,tabs=operations.tabs,
                authorize=protected_callback(authority,token,operations)).execute(operation,args)
            return dict(schema_version=1,operation=operation,status='completed',result=value)
        result[operation]=(tool,schema,'content.observe' if readonly else 'terminal.input',invoke)
    return result
