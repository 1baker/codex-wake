"""Detached native turn collector and bounded response custody in the operation journal.

Only the admitted dispatcher starts this collector. Reopening output never starts
or repeats a prompt. Socket loss leaves an explicit history gap, never replay.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import time
import threading

from websockets.sync.client import unix_connect
from .controller_runtime import ControllerRuntime, encoded
from .managed_inventory import InventoryError
from .process import process_identity
from . import measurements

MAX_EVENTS=2048
MAX_BYTES=2*1024*1024
MAX_EVENT_BYTES=16384
MAX_SECONDS=3600
MODES=('stream','transcript','final','silent')


def _metadata_time():
    try:return measurements.utc_time()
    except measurements.TimeUnavailable:return None


class TurnEvents:
    def __init__(self,root):
        self.runtime=ControllerRuntime(root)
        with self.runtime.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS native_turn_events
                (operation_id TEXT, sequence INTEGER, payload TEXT, size INTEGER,
                 PRIMARY KEY(operation_id,sequence));
                CREATE TABLE IF NOT EXISTS native_turn_collectors
                (operation_id TEXT PRIMARY KEY, state TEXT);''')

    def state(self,identifier):
        with self.runtime.connect() as db:
            row=db.execute('SELECT state FROM native_turn_collectors WHERE operation_id=?',(identifier,)).fetchone()
        return json.loads(row[0]) if row else dict(status='unavailable',reason='native_event_history_unavailable',sequence=0,truncated=False)

    def publish_scope(self,record,row,connection,turn_id):
        from .native_protocol import _protective_scope
        with self.runtime.connect() as db:
            original=db.execute('SELECT fingerprint,record FROM operations WHERE id=?',(record['operation_id'],)).fetchone()
        current=json.loads(original[1])
        if (current['operation']!='sessions.prompt' or current['target']!=record['target']
                or current['payload_sha256']!=record['payload_sha256']):raise InventoryError('stale_target','original admission changed')
        scope=_protective_scope(connection,row,record,original[0],turn_id)
        with self.runtime.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            saved=db.execute('SELECT state FROM native_turn_collectors WHERE operation_id=?',(record['operation_id'],)).fetchone()
            state=json.loads(saved[0]) if saved else dict(sequence=0,truncated=False)
            prior=state.get('protective_scope')
            if prior:
                if any(prior.get(k)!=scope.get(k) for k in ('operation_id','admission_fingerprint','target_sha256','turn_id')):
                    raise InventoryError('stale_target','qualified protective ownership changed')
                return
            state['protective_scope']=scope
            state['protective_scope_status']='qualified'
            db.execute('INSERT OR REPLACE INTO native_turn_collectors VALUES(?,?)',(record['operation_id'],encoded(state)))

    def update(self,identifier,**values):
        with self.runtime.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM native_turn_collectors WHERE operation_id=?',(identifier,)).fetchone()
            state=json.loads(row[0]) if row else dict(sequence=0,truncated=False,created_at=_metadata_time())
            state.update(values,updated_at=_metadata_time())
            state['metadata_clock_status']='qualified' if state['updated_at'] is not None else 'unavailable'
            db.execute('INSERT OR REPLACE INTO native_turn_collectors VALUES(?,?)',(identifier,encoded(state)))

    def append(self,identifier,kind,params):
        raw=encoded(params);cut=len(raw.encode())>MAX_EVENT_BYTES
        # An oversized event remains explicit and sequenced, never malformed JSON.
        if cut:params=dict(omitted=True,original_bytes=len(raw.encode()),reason='event_size_limit')
        with self.runtime.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM native_turn_collectors WHERE operation_id=?',(identifier,)).fetchone()
            state=json.loads(row[0]);sequence=state['sequence']+1
            value=encoded(dict(sequence=sequence,kind=kind,params=params,truncated=cut,provenance='native_protocol_notification'))
            db.execute('INSERT INTO native_turn_events VALUES(?,?,?,?)',(identifier,sequence,value,len(value.encode())))
            count,total=db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM native_turn_events WHERE operation_id=?',(identifier,)).fetchone()
            while count>MAX_EVENTS or total>MAX_BYTES:
                first=db.execute('SELECT sequence,size FROM native_turn_events WHERE operation_id=? ORDER BY sequence LIMIT 1',(identifier,)).fetchone()
                db.execute('DELETE FROM native_turn_events WHERE operation_id=? AND sequence=?',(identifier,first[0]))
                count-=1;total-=first[1];state['truncated']=True
            state.update(sequence=sequence,updated_at=_metadata_time(),truncated=state['truncated'] or cut)
            state['metadata_clock_status']='qualified' if state['updated_at'] is not None else 'unavailable'
            db.execute('UPDATE native_turn_collectors SET state=? WHERE operation_id=?',(encoded(state),identifier))

    def read(self,identifier,cursor=0,limit=100):
        if type(cursor) is not int or cursor<0 or type(limit) is not int or not 1<=limit<=100:
            raise InventoryError('invalid_argument','nonnegative cursor and limit1..100 required')
        with self.runtime.connect() as db:
            state_row=db.execute('SELECT state FROM native_turn_collectors WHERE operation_id=?',(identifier,)).fetchone()
            state=json.loads(state_row[0]) if state_row else self.state(identifier)
            if cursor>state['sequence']:raise InventoryError('invalid_cursor','cursor is beyond retained native event history')
            first=db.execute('SELECT MIN(sequence) FROM native_turn_events WHERE operation_id=?',(identifier,)).fetchone()[0]
            rows=db.execute('SELECT payload FROM native_turn_events WHERE operation_id=? AND sequence>? ORDER BY sequence LIMIT ?',(identifier,cursor,limit)).fetchall()
        events=[json.loads(row[0]) for row in rows]
        return dict(events=events,next_cursor=events[-1]['sequence'] if events else cursor,latest_cursor=state['sequence'],
            retention=dict(max_events=MAX_EVENTS,max_bytes=MAX_BYTES,max_event_bytes=MAX_EVENT_BYTES,max_collector_seconds=MAX_SECONDS,
                expires_automatically=False,earliest_cursor=(first-1) if first else 0,
                truncated=state.get('truncated',False),cursor_gap=first is not None and cursor<first-1,
                history_complete=state.get('status')=='completed' and not state.get('truncated') and not state.get('unsupported_event_kinds'),
                excluded_item_types=['reasoning','userMessage'],unsupported_event_kinds=state.get('unsupported_event_kinds',[]),
                status=state['status'],reason=state.get('reason')))


def launch(root,identifier):
    deadline=measurements.deadline(10)
    store=TurnEvents(root)
    if deadline.expired():raise InventoryError('collector_deadline','collector launch deadline')
    # Dispatcher is called once by ControllerRuntime. This is never called by a retry/result.
    process=subprocess.Popen([sys.executable,'-m','codex_wake.local_session_events','--root',str(Path(root).resolve()),'--operation',identifier],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        close_fds=True,start_new_session=True)
    threading.Thread(target=process.wait,daemon=True).start()
    while deadline.remaining()>0:
        record=store.runtime._load(identifier)
        if isinstance(record.get('result'),dict) and record['result'].get('turn_id'):
            if deadline.remaining()<=0:break
            return record['result']
        if store.state(identifier)['status'] in ('uncertain','failed'):raise InventoryError('uncertain_effect','collector could not qualify native acknowledgement; retrieve original operation')
        if process.poll() is not None:raise InventoryError('uncertain_effect','collector exited before acknowledgement; retrieve original operation')
        time.sleep(.01)
    raise InventoryError('uncertain_effect','collector acknowledgement deadline; original operation retained')


def collect(root,identifier):
    store=TurnEvents(root);runtime=store.runtime;record=runtime._load(identifier)
    lock_path=runtime.path.parent/(identifier+'.collector.lock')
    with lock_path.open('a') as lock:
        os.chmod(lock_path,0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        if store.state(identifier)['status']!='unavailable':return
        store.update(identifier,status='connecting',pid=os.getpid(),process=process_identity(os.getpid()))
        row=record['payload']['session'];target=row['target'];thread=row['thread_id'];turn_id=None;pending=[];final_items={};final_truncated=False;transmitted=False
        try:
            lifetime=measurements.deadline(MAX_SECONDS)
            preparation=measurements.deadline(10)
            def remaining(deadline):
                value=min(deadline.remaining(),lifetime.remaining())
                if value<=0:raise InventoryError('collector_deadline','collector qualified deadline; work was not cancelled')
                return value
            from .local_sessions import resolve
            resolve(root,'thread:'+thread,target,endpoint=row['endpoint'])
            path=Path(row['endpoint'][7:]);info=path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():raise InventoryError('stale_target','owned existing native socket required')
            with unix_connect(str(path),open_timeout=remaining(preparation),close_timeout=.2,max_size=4*1024*1024,compression=None) as ws:
                remaining(preparation)
                pid,uid,_=struct.unpack('3i',ws.socket.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid!=os.getuid() or pid!=target['process']['pid']:raise InventoryError('stale_target','native peer changed')
                counter=0
                def call(method,params):
                    nonlocal counter
                    deadline=preparation
                    remaining(deadline)
                    counter+=1;request_id=counter
                    ws.send(encoded(dict(id=request_id,method=method,params=params)))
                    remaining(deadline)
                    while True:
                        frame=json.loads(ws.recv(timeout=remaining(deadline)))
                        remaining(deadline)
                        if frame.get('id')==request_id:
                            if 'error' in frame:raise InventoryError('native_rejected','native request rejected: '+method)
                            return frame['result']
                        if len(pending)>=256:raise InventoryError('capacity','native pre-acknowledgement event bound reached')
                        pending.append(frame)
                metadata=call('initialize',dict(clientInfo=dict(name='codex_wake_turn_collector',version='1'),capabilities=dict(experimentalApi=True)))
                if metadata.get('codexHome')!=target['home']:raise InventoryError('stale_target','native account home changed')
                ws.send(encoded(dict(method='initialized')))
                remaining(preparation)
                current=call('thread/read',dict(threadId=thread,includeTurns=False))['thread']
                if current.get('id')!=thread or current.get('status',{}).get('type')!='idle':
                    raise InventoryError('session_busy','target is busy; no implicit queue or steer')
                # Native events are connection-scoped: rejoin ONLY the already
                # loaded idle conversation, with no configuration/history overrides.
                attached=call('thread/resume',dict(threadId=thread,excludeTurns=True))['thread']
                if attached.get('id')!=thread:raise InventoryError('stale_target','native event attachment changed conversation')
                after=call('thread/read',dict(threadId=thread,includeTurns=False))['thread']
                settings=('id','model','modelProvider','reasoningEffort','cwd','environments')
                if any(after.get(key)!=current.get(key) for key in settings):
                    raise InventoryError('stale_target','native event attachment changed session settings')
                store.update(identifier,native_client_id=identifier)
                remaining(preparation)
                transmitted=True
                turn=call('turn/start',dict(threadId=thread,clientUserMessageId=identifier,input=[dict(type='text',text=record['payload']['prompt'])]))['turn']
                turn_id=turn.get('id')
                if not isinstance(turn_id,str) or not turn_id:raise InventoryError('uncertain_effect','native turn acknowledgement missing')
                handle=dict(kind='native_turn',local_control=True,turn_id=turn_id,target=target)
                record.update(result=handle,execution='running',delivery='submitted',acceptance='harness_accepted',phase='waiting',reason=None)
                try:store.publish_scope(record,row,ws,turn_id)
                except (ValueError,OSError,KeyError,TypeError) as error:
                    if not store.state(identifier).get('protective_scope'):
                        store.update(identifier,protective_scope_status='unqualified',protective_scope_error=type(error).__name__)
                remaining(preparation)
                runtime._save(record);store.update(identifier,status='collecting',turn_id=turn_id)
                while True:
                    budget=remaining(lifetime)
                    frame=pending.pop(0) if pending else json.loads(ws.recv(timeout=budget))
                    remaining(lifetime)
                    method=frame.get('method');params=frame.get('params')
                    if not isinstance(method,str) or not isinstance(params,dict):continue
                    # Requests requiring an interaction are never blindly approved.
                    if 'id' in frame:
                        if params.get('threadId')==thread and params.get('turnId')==turn_id:
                            store.update(identifier,interaction_required=True,interaction=dict(id=frame['id'],method=method))
                        continue
                    if params.get('threadId')!=thread:continue
                    event_turn=params.get('turnId') or (params.get('turn') or {}).get('id')
                    if event_turn!=turn_id:continue
                    allowed=('turn/started','turn/completed','item/started','item/completed','item/agentMessage/delta','item/commandExecution/outputDelta','item/mcpToolCall/progress','turn/moderationMetadata','thread/tokenUsage/updated','error')
                    if method not in allowed:
                        if not method.startswith(('codex/event/','item/reasoning/')):
                            omitted=store.state(identifier).get('unsupported_event_kinds',[])
                            if method not in omitted:store.update(identifier,unsupported_event_kinds=(omitted+[method])[:16])
                        continue
                    item=params.get('item',{})
                    if item.get('type') in ('reasoning','userMessage') or item.get('phase')=='analysis':continue
                    clean={key:params[key] for key in ('threadId','turnId','itemId','delta','metadata','tokenUsage') if key in params}
                    if 'turn' in params:clean['turn']={key:params['turn'][key] for key in ('id','status','error') if key in params['turn']}
                    if 'item' in params:clean['item']={key:item[key] for key in ('id','type','phase','text','command','status','exitCode','tool','server','name','arguments','result','changes') if key in item}
                    if method=='error':clean['error']=params.get('error');clean['willRetry']=params.get('willRetry')
                    store.append(identifier,method,clean)
                    if method=='item/completed' and item.get('type')=='agentMessage' and item.get('phase') in (None,'final_answer'):
                        text=item.get('text','')
                        if isinstance(text,str):
                            raw=text.encode();final_items={item.get('id','final'):raw[:32768].decode(errors='replace')};final_truncated=len(raw)>32768
                    if method=='turn/completed':
                        status=params['turn'].get('status');execution={'completed':'completed','failed':'failed','interrupted':'cancelled'}.get(status)
                        if execution is None:raise InventoryError('native_event_schema','unrecognized native terminal status')
                        raw='\n'.join(final_items.values()).encode()
                        record=runtime._load(identifier)
                        record.update(phase='terminal',execution=execution,delivery='retained',acceptance='owner_observed',reason=None,
                            answer=dict(text=raw[:32768].decode(errors='replace'),truncated=final_truncated or len(raw)>32768,source='native_turn_events',turn_id=turn_id))
                        remaining(lifetime)
                        store.update(identifier,status='completed');runtime._save(record);return
        except Exception as error:
            record=runtime._load(identifier)
            reason='stable_time_unavailable' if isinstance(error,measurements.TimeUnavailable) else getattr(error,'code','native_event_connection_lost')
            if record['phase']!='terminal':
                record.update(phase='uncertain' if transmitted else 'terminal',execution='unknown' if transmitted else 'failed',delivery='uncertain' if transmitted else 'not_submitted',reason=reason)
                runtime._save(record)
            # Publish collector failure only after the operation journal retains
            # definitive pre-submit refusal. The dispatcher may return as soon
            # as it sees this status; publishing first races its uncertain save.
            store.update(identifier,status='uncertain' if transmitted else 'failed',reason=reason)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--root',required=True);parser.add_argument('--operation',required=True)
    args=parser.parse_args();collect(args.root,args.operation)
