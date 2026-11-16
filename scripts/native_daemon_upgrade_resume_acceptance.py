"""Opt-in UID1017 cooperative-upgrade qualification; never uses working-account state.

Requires the staged dummy-account launcher and complete immutable native packages.
Run as codex-daemon-test with one unique case name. Provider traffic stays on localhost.
CODEX_QUALIFICATION_TARGET selects the candidate; optional BASELINE and MODE select
legacy/refuse/hang controls. Full receipts and terminal captures remain in dummy state.
"""
import os,json,time,pathlib,subprocess,threading,shlex,hashlib,signal,traceback,sys,socket,struct,tempfile,re
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
assert os.getuid() == 1017, "Run this isolated acceptance harness as codex-daemon-test UID1017"
from codex_wake.native_protocol import native_request
P=pathlib.Path;b=P('/home/codex-daemon-test/daemon-qualification-0165');root=b/('resume-journey-'+sys.argv[1]);root.mkdir(mode=0o700)
ws=root/'workspace';ws.mkdir(mode=0o700);home=root/'accounts/codex-test';home.mkdir(mode=0o700,parents=True)
prefix=P(os.environ.get('CODEX_QUALIFICATION_WAKE_PREFIX',str(b/'wake')));launcher=prefix/'bin/codex-modded';baseline=P(os.environ.get('CODEX_QUALIFICATION_BASELINE',str(b/'candidate-barrier/bin/codex')));target=P(os.environ.get('CODEX_QUALIFICATION_TARGET',str(baseline)));control=home/'app-server-control/app-server-control.sock'
(root/'harness.py').write_bytes(P(__file__).read_bytes());(root/'harness.py').chmod(0o600)
report=dict(state='preparing',script_sha256=hashlib.sha256(P(__file__).read_bytes()).hexdigest(),external_model_calls=0,optional_plugins_enabled=False,uid=os.getuid(),provider='Owned scripted localhost Responses fixture',external_provider_calls=0,mode=os.environ.get('CODEX_QUALIFICATION_MODE','success'));finish=threading.Event();release=threading.Event();active={};calls=[];errors=[];lock=threading.Lock();watcher=None;updater=None;native_pid=None

authority_case=os.environ.get('CODEX_QUALIFICATION_AUTHORITY_CASE','')
report['authority_case']=authority_case
resume_stream_release=threading.Event()
class QualificationPassed(Exception):pass
retention_locks=[]
coordinator=None;coordinator_child=None;failed_executable=None;failed_mode=None;failed_start_log=None;failed_start_log_mode=None
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def durable_fixture_json(path,value):
 with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as stream:
  temporary=P(stream.name);os.fchmod(stream.fileno(),0o600);json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
 os.replace(temporary,path)
 descriptor=os.open(path.parent,os.O_RDONLY)
 try:os.fsync(descriptor)
 finally:os.close(descriptor)
def save():(root/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
def text_values(v):
 if isinstance(v,dict):
  for k,x in v.items():
   if k=='text' and isinstance(x,str):yield x
   else:yield from text_values(x)
 elif isinstance(v,list):
  for x in v:yield from text_values(x)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  tid=self.headers.get('thread-id');body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  with lock:number=len(calls)+1;calls.append(dict(thread=tid,number=number))
  (root/('request-'+str(number)+'.json')).write_text(json.dumps(body))
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  def emit(v):self.wfile.write(('event: '+v['type']+'\ndata: '+json.dumps(v)+'\n\n').encode());self.wfile.flush()
  try:
   assert number<=32,'Provider request cap exceeded'
   emit(dict(type='response.created',response=dict(id='upgrade-owned-'+str(number))))
   item=None;prompt=next((x.split('UPGRADE_REQUEST_JSON=',1)[1] for x in text_values(body.get('input',[])) if 'UPGRADE_REQUEST_JSON=' in x),None)
   recovery=next((x.split('UPGRADE_RECOVERY_JSON=',1)[1] for x in text_values(body.get('input',[])) if 'UPGRADE_RECOVERY_JSON=' in x),None)
   if recovery:
    packet=json.JSONDecoder().raw_decode(recovery)[0];assert packet['thread_id']==tid,packet
    handoff=packet['handoff'];assert handoff['ready'] and handoff['thread_id']==tid and handoff['upgrade_id']==packet['operation_id']
    assert handoff['remaining']==['Resume original unfinished objective'] and handoff['resource_state']['native_token_limit']==report['native_limits'][tid],handoff
    if report['mode']=='accepted-crash' and not report.get('server_crashed'):
     report.setdefault('accepted_streams',{})[tid]=True
     while not resume_stream_release.wait(.1) and not finish.is_set():self.wfile.write(b': accepted work before controlled native crash\n\n');self.wfile.flush()
     # This response belongs to the killed process. It must not change fixture goal state.
     raise BrokenPipeError('Owned accepted-stream crash control')
    if not active[tid].get('resume_paused'):
     current_endpoint='unix://'+str(control.resolve(strict=True))
     g=wait(lambda:(v if (v:=native_request(current_endpoint,str(target),'thread/goal/get',dict(threadId=tid),5)['goal'])['status']=='active' else None),'Resumed existing goal active',5)
     assert g['createdAt']==report['goals_before'][tid]['createdAt'] and g['tokenBudget']==report['native_limits'][tid],g
     checkpoint=json.loads((home/'daemon-upgrades'/packet['operation_id']/'state.json').read_text())['threads'][tid]['goal_after']
     assert all(g[k]>=checkpoint[k] for k in ['tokensUsed','timeUsedSeconds']),dict(resumed=g,checkpoint=checkpoint)
     report.setdefault('resumed',{})[tid]=dict(packet=packet,goal_at_resume=g)
     active[tid]['resume_paused']=True
     item=dict(type='function_call',name='update_goal',call_id='resume-pause-'+str(number),arguments=json.dumps(dict(status='paused')));text=None
    else:text='UPGRADE_WORK_RESUMED'
   elif not body.get('tools'):
    assert 'Generate a concise' in json.dumps(body),'Unexpected auxiliary request';text='Prepare upgrade checkpoint'
   elif prompt:
    request=json.JSONDecoder().raw_decode(prompt)[0];assert request['thread_id']==tid,request
    report.setdefault('injected_requests',{})[tid]=request
    if not active[tid].get('paused'):
     item=dict(type='function_call',name='update_goal',call_id='checkpoint-pause-'+str(number),arguments=json.dumps(dict(status='paused')));active[tid]['paused']=True;text=None
    else:
     if report['mode']=='hang' and tid==report['active_threads'][-1]:
      report['hanging_checkpoint_thread']=tid
      while not finish.wait(.1):self.wfile.write(b': bounded unresponsive checkpoint control\n\n');self.wfile.flush()
      return
     handoff=dict(upgrade_id=request['upgrade_id'],thread_id=tid,ready=True,objective='Preserve isolated active work',authority='Operator-approved isolated upgrade qualification',completed=['Bounded work packet recorded'],remaining=['Resume original unfinished objective'],pending_operations=[],resource_state=dict(native_token_limit=report['native_limits'][tid],scope='unchanged'),resume_instructions='Read this checkpoint and resume original conversation only with the original remaining allowance')
     if authority_case=='metadata':handoff['workspace_state']=dict(branch='isolated-fixture',dirty=True)
     if report['mode']=='deadline' and tid==report['active_threads'][0]:
      case=authority_case or 'deadline_unix_seconds'
      if case=='deadline_at':handoff['resource_state']['deadline_at']='1970-01-01T00:00:00Z'
      elif case=='deadline_unix_seconds':handoff['resource_state']['deadline_unix_seconds']=1
      elif case=='allowed-string':handoff['resource_state']['resume_allowed']='true'
      elif case=='limit-string':handoff['resource_state']['native_token_limit']=str(report['native_limits'][tid])
      elif case=='scope-number':handoff['resource_state']['scope']=1
      elif case=='unknown-policy':handoff['resource_state']['external_policy']=dict(deadline_at=1)

     if report['mode']=='refuse' and tid==report['active_threads'][-1]:handoff.update(ready=False,reason='Isolated negative control: cannot establish a safe checkpoint')
     text=json.dumps(handoff)
     report.setdefault('agent_handoffs',{})[tid]=handoff if text.startswith('{') else dict(refused=True)
   else:
    assert tid in active,tid;active[tid]['stream_started']=True
    while not release.wait(.1) and not finish.is_set():self.wfile.write(b': bounded active work\n\n');self.wfile.flush()
    text='ACTIVE_WORK_PACKET_YIELDED'
   if item:emit(dict(type='response.output_item.done',item=item))
   if text:emit(dict(type='response.output_item.done',item=dict(type='message',role='assistant',id='upgrade-message-'+str(number),content=[dict(type='output_text',text=text)])))
   emit(dict(type='response.completed',response=dict(id='upgrade-owned-'+str(number),usage=dict(input_tokens=20,input_tokens_details=dict(cached_tokens=0),output_tokens=0,total_tokens=20))))
  except (BrokenPipeError,ConnectionResetError):
   if not finish.is_set():report.setdefault('stream_disconnects',[]).append(tid)
  except BaseException as e:errors.append(repr(e));report['provider_errors']=errors

http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.daemon_threads=True;threading.Thread(target=http.serve_forever,daemon=True).start()
config='model="mock-model"\nmodel_provider="local_fixture"\napproval_policy="never"\nsandbox_mode="read-only"\n[features]\nplugins=false\n[model_providers.local_fixture]\nname="Owned upgrade fixture"\nbase_url="http://127.0.0.1:'+str(http.server_address[1])+'/v1"\nwire_api="responses"\nrequires_openai_auth=false\nsupports_websockets=false\nrequest_max_retries=0\nstream_max_retries=0\n[projects.'+json.dumps(str(ws))+']\ntrust_level="trusted"\n'
(home/'config.toml').write_text(config)
settings=home/'app-server-daemon';settings.mkdir(mode=0o700);(settings/'settings.json').write_text(json.dumps(dict(shutdownGraceSeconds=2)))
shared=home.parent/'shared';shared.mkdir(mode=0o700);(shared/'builds.json').write_text(json.dumps(dict(schema_version=1,builds=dict(modded=dict(executable=str(baseline),sha256=digest(baseline),upstream_version='0.165.0',revision='barrier-baseline',source='local-qualified',read_schemas=[5],backend='managed')))))
profiles=root/'profiles.toml';profiles.write_text('[profiles]\nstate_root='+json.dumps(str(home.parent))+'\nselection_mode="launcher"\ndefault_profile="test"\nknown_profiles=["test"]\nshared_links=[]\ncheck_upstream_releases=false\n')
(root/'tmux.conf').write_text('set -g remain-on-exit on\n')
env=dict(os.environ,CODEX_HOME=str(home),CODEX_PROFILES_CONFIG=str(profiles),CODEX_BUILD_UPDATE_CHECK='0',TERM='xterm-256color');tm=['tmux','-f',str(root/'tmux.conf'),'-S',str(root/'tmux.sock')]
def t(*args,check=True):return subprocess.run([*tm,*args],env=env,capture_output=True,text=True,timeout=10,check=check).stdout
def wait(fn,label,seconds=15):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if errors:raise AssertionError(errors)
  v=fn()
  if v:return v
  time.sleep(.05)
 raise AssertionError(label+' unavailable')
def raw_rpc(method,params):
 from websockets.sync.client import unix_connect
 with unix_connect(endpoint[7:],open_timeout=5,close_timeout=1) as client:
  client.send(json.dumps(dict(id=1,method='initialize',params=dict(clientInfo=dict(name='upgrade_qualification',version='0'),capabilities=dict(experimentalApi=True)))))
  while json.loads(client.recv(timeout=5)).get('id')!=1:pass
  client.send(json.dumps(dict(method='initialized')))
  client.send(json.dumps(dict(id=2,method=method,params=params)))
  while True:
   v=json.loads(client.recv(timeout=5))
   if v.get('id')==2:return v
def recovery_replay(address,operation_id,threads):
 from websockets.sync.client import unix_connect
 with unix_connect(address[7:],open_timeout=5,close_timeout=1) as client:
  identifier=0
  def request(method,params):
   nonlocal identifier
   identifier+=1;client.send(json.dumps(dict(id=identifier,method=method,params=params)))
   while True:
    response=json.loads(client.recv(timeout=8))
    if response.get('id')==identifier:return response
  assert 'result' in request('initialize',dict(clientInfo=dict(name='recovery_replay_fixture',version='0'),capabilities=dict(experimentalApi=True)))
  client.send(json.dumps(dict(method='initialized')))
  def acquire():
   response=request('daemon/upgrade/prepare',dict(operationId=operation_id))
   if response.get('error',{}).get('message')=='Another daemon upgrade is already preparing':return None
   assert response.get('result')==dict(operationId=operation_id,ready=True),response
   return True
  wait(acquire,'Prior native recovery coordinator released its connection-owned hold',10)
  results={}
  for tid in threads:
   response=request('daemon/upgrade/recovery',dict(operationId=operation_id,threadId=tid,action='resume'))
   assert 'result' in response,response
   results[tid]=response['result']
  return results
def assert_no_recovery_requests(threads):
 # The scripted protocol emits three provider requests through checkpoint completion.
 # Held work must add none, including requests without a recovery context marker.
 counts={tid:sum(call['thread']==tid for call in calls) for tid in threads}
 assert all(count==3 for count in counts.values()),counts
 report.setdefault('stopped_thread_provider_requests',{}).update(counts)
def pane(name,tid):
 t('new-session','-d','-s',name,'-x','180','-y','55',shlex.join([str(launcher),'--no-alt-screen','resume',tid]));wait(lambda:'mock-model' in t('capture-pane','-p','-t',name,check=False),'Actual '+name+' TUI',20)
 frame=t('capture-pane','-p','-S','-2000','-t',name)
 if 'Resume paused goal?' in frame and 'Leave paused' in frame:t('send-keys','-t',name,'Escape')
def history_visibility(address,executable,label):
 # Query the public history surface, not only already-attached TUI state.
 listed=native_request(address,str(executable),'thread/list',dict(limit=100),8)['data']
 expected=set(report['active_threads']+[report['idle_thread']])
 # The default conversation list intentionally omits message-less idle threads.
 assert set(report['active_threads']) <= {thread['id'] for thread in listed},(label,report['active_threads'],[thread['id'] for thread in listed])
 evidence={}
 for tid in expected:
  thread=native_request(address,str(executable),'thread/read',dict(threadId=tid,includeTurns=True),8)['thread']
  assert thread['id']==tid and thread.get('path') and P(thread['path']).is_file(),thread
  turns={turn['id'] for turn in thread['turns']}
  if tid in active:assert active[tid]['turn_id'] in turns,(label,tid,turns)
  evidence[tid]=dict(path=thread['path'],turn_ids=sorted(turns))
 report.setdefault('public_history_visibility',{})[label]=evidence

try:
 t('new-session','-d','-s','bootstrap','-x','180','-y','55',shlex.join([str(launcher),'--no-alt-screen','-C',str(ws)]))
 wait(lambda:'mock-model' in t('capture-pane','-p','-t','bootstrap',check=False),'Managed bootstrap',60)
 endpoint='unix://'+str(control.resolve(strict=True))
 def rpc(method,params):return native_request(endpoint,str(baseline),method,params,5)
 with socket.socket(socket.AF_UNIX) as s:s.connect(endpoint[7:]);native_pid,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
 assert uid==os.getuid() and digest(P('/proc')/str(native_pid)/'exe')==digest(baseline)
 t('kill-session','-t','bootstrap');report['old_pid']=native_pid;report['baseline_sha256']=digest(baseline);report['target_sha256']=digest(target);report['active_threads']=[]
 for i in range(2):
  if report['mode']=='tui-authority':
   previously_loaded=set(rpc('thread/loaded/list',dict(limit=100))['data'])
   t('new-session','-d','-s','active'+str(i),'-x','180','-y','55',shlex.join([str(launcher),'--no-alt-screen','-C',str(ws)]))
   wait(lambda:'mock-model' in t('capture-pane','-p','-t','active'+str(i),check=False),'Fresh ordinary TUI '+str(i),20)
   def new_ui_thread():
    created=set(rpc('thread/loaded/list',dict(limit=100))['data'])-previously_loaded
    assert len(created)<=1,created
    return next(iter(created)) if created else None
   tid=wait(new_ui_thread,'New TUI conversation identity',15)
  else:tid=rpc('thread/start',dict(cwd=str(ws),historyMode='paginated'))['thread']['id']
  active[tid]={};report['active_threads'].append(tid)
  if report['mode']=='tui-authority':
   report.setdefault('native_limits',{})[tid]=None
   t('send-keys','-t','active'+str(i),'-l','/goal Preserve isolated active work');time.sleep(.4);t('send-keys','-t','active'+str(i),'Enter')
   wait(lambda:active[tid].get('stream_started'),'Ordinary TUI goal starts original work',20)
   def original_turn():
    turns=rpc('thread/turns/list',dict(threadId=tid,limit=20,itemsView='notLoaded'))['data']
    return turns[0]['id'] if turns else None
   active[tid]['turn_id']=wait(original_turn,'Native TUI goal original turn')
   report.setdefault('tui_created_goal_threads',[]).append(tid)
   (root/('goal-created-active'+str(i)+'.txt')).write_text(t('capture-pane','-p','-S','-2000','-t','active'+str(i)))
   continue
  limit=20 if report['mode']=='exhausted' and i==0 else 2000
  report.setdefault('native_limits',{})[tid]=limit
  creation=dict(threadId=tid,objective='Preserve isolated active work',status='paused',tokenBudget=limit,origin='user')
  if not (i==0 and authority_case in ('missing-declaration','tui-legacy')):creation['recoveryAuthority']=dict(version=1,policy='nativeOnly')
  rpc('thread/goal/set',creation)
  turn=rpc('turn/start',dict(threadId=tid,input=[dict(type='text',text='Perform a bounded isolated work packet under the existing goal. During an operator daemon upgrade, checkpoint and pause without changing limits.')]))['turn']['id'];active[tid]['turn_id']=turn
  wait(lambda:active[tid].get('stream_started'),'Active native work stream')
  if authority_case=='metadata' and i==0:
   before=rpc('thread/goal/get',dict(threadId=tid))['goal']
   invalid=[dict(version='1',policy='nativeOnly'),dict(version=True,policy='nativeOnly'),dict(version=2,policy='nativeOnly'),dict(version=1,policy='external'),dict(version=1,policy='nativeOnly',deadline_at=1)]
   for declaration in invalid:
    rejected=raw_rpc('thread/goal/set',dict(threadId=tid,status='active',origin='user',recoveryAuthority=declaration))
    assert 'error' in rejected,rejected
    unchanged=rpc('thread/goal/get',dict(threadId=tid))['goal']
    assert all(unchanged[k]==before[k] for k in ['objective','status','createdAt','tokenBudget','tokensUsed']),unchanged
   rejected=raw_rpc('thread/goal/set',dict(threadId=tid,status='active',origin='automatic',recoveryAuthority=dict(version=1,policy='nativeOnly')))
   assert 'error' in rejected,rejected
   report['invalid_authority_declarations_rejected_before_mutation']=len(invalid)+1
  if i==0 and authority_case in ('tui-legacy','tui-after-external'):
   if authority_case=='tui-after-external':
    rpc('thread/goal/set',dict(threadId=tid,status='active',origin='user',recoveryAuthority=dict(version=1,policy='nativeOnly')))
    rpc('thread/goal/set',dict(threadId=tid,status='paused',origin='automatic'))
   pane('active'+str(i),tid)
   t('send-keys','-t','active'+str(i),'-l','/goal resume');time.sleep(.4);t('send-keys','-t','active'+str(i),'Enter')
   wait(lambda:rpc('thread/goal/get',dict(threadId=tid))['goal']['status']=='active','User TUI control remains available for unknown authority',15)
   report['tui_resumed_unknown_authority']=True
   continue
  if report['mode']!='originalpause' or i!=0:
   params=dict(threadId=tid,status='active',origin='user')
   if not (authority_case=='missing-declaration' and i==0):params['recoveryAuthority']=dict(version=1,policy='nativeOnly')
   rpc('thread/goal/set',params)
  pane('active'+str(i),tid)
 pane('active0mirror',report['active_threads'][0])
 idle=rpc('thread/start',dict(cwd=str(ws),historyMode='paginated'))['thread']['id'];report['idle_thread']=idle
 rpc('thread/notice/append',dict(threadId=idle,eventId='upgrade_fixture_idle',text='Idle isolated session. [External supervision event upgrade_fixture_idle]'));pane('idle',idle)
 report['goals_before']={tid:rpc('thread/goal/get',dict(threadId=tid))['goal'] for tid in active}
 history_visibility(endpoint,baseline,'before_upgrade')
 report['old_selection']=os.readlink(home/'packages/app-server-daemon/current')
 if report['mode']=='retention':
  import fcntl
  journal=home/'daemon-upgrades';journal.mkdir(mode=0o700,exist_ok=True)
  retained=[];pending=[]
  for number in range(340):
   name='upgrade-retained-'+str(number).zfill(4);directory=journal/name;directory.mkdir(mode=0o700)
   value=dict(schema_version=2 if number%2 else 1,recovery_enabled=bool(number%2),phase='recovered',threads={},operation_id=name)
   if number>=300:
    value.update(schema_version=2,recovery_enabled=True,phase='installing');pending.append(name)
    lease=(directory/'coordinator.lock').open('a+');os.chmod(lease.name,0o600);fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);retention_locks.append(lease)
   else:retained.append(name)
   durable_fixture_json(directory/'state.json',value)
  report['inventory_fixture']=dict(retained=retained,pending_empty=pending,kind='Synthetic valid terminal/legacy records and 40 pending empty operations; real active work remains native updater-owned')
 prior_operations=set((home/'daemon-upgrades').glob('upgrade-*/state.json'))
 log=(root/'update.log').open('w');updater=subprocess.Popen([str(target),'app-server','daemon','update','--from-cli','--yes'],env=env,cwd=ws,stdout=log,stderr=log,start_new_session=True)
 deadline=time.monotonic()+150;operation=None
 while updater.poll() is None and time.monotonic()<deadline:
  paths=list(set((home/'daemon-upgrades').glob('upgrade-*/state.json'))-prior_operations)
  if paths:
   operation=max(paths,key=lambda p:p.stat().st_mtime)
   state=json.loads(operation.read_text())
   if state['phase']=='waiting' and not release.is_set():
    if report['mode'] in ('userpause','unknown','response-loss','bad-handoff','wrong-target','wrong-digest','startup-fail','owner-loss') or authority_case.startswith('seal-'):
     import fcntl
     coordinator=(operation.parent/'coordinator.lock').open('a+');os.chmod(coordinator.name,0o600)
     if report['mode']=='owner-loss':
      lock_ready=root/'coordinator-ready'
      owner_code="import fcntl,os,pathlib,sys,time;f=open(sys.argv[1],'a+');os.chmod(sys.argv[1],0o600);fcntl.flock(f,fcntl.LOCK_EX);pathlib.Path(sys.argv[2]).write_text(str(os.getpid()));time.sleep(180)"
      coordinator_child=subprocess.Popen([sys.executable,'-c',owner_code,coordinator.name,str(lock_ready)],env=env,cwd=ws,stdout=(root/'coordinator.log').open('w'),stderr=subprocess.STDOUT)
      wait(lambda:lock_ready.exists(),'Real coordinator child owns lease',5)
      report['coordinator_owner_pid']=coordinator_child.pid
     else:fcntl.flock(coordinator,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if report['mode']=='startup-fail':
     import stat
     # Fail the mandatory new-process log open; old inherited handles and
     # canonical history remain available. Config errors otherwise use defaults.
     failed_start_log=home/'app-server-daemon/daemon.stderr.log';failed_start_log_mode=stat.S_IMODE(failed_start_log.stat().st_mode)
     failed_start_log.chmod(0)
     report['failed_start_injection']=dict(path=str(failed_start_log),original_mode=failed_start_log_mode,kind='Owned daemon stderr log made unwritable before replacement mandatory startup open; package and account configuration bytes unchanged')
    rejected=raw_rpc('thread/start',dict(cwd=str(ws),historyMode='paginated'))
    assert rejected.get('error',{}).get('data',{}).get('reason')=='daemonUpgradePreparing',rejected
    report['new_work_held_during_preparation']=True
    report['notices_visible']={}
    for name in ['active0','active0mirror','active1','idle']:
     screen=wait(lambda:(v if 'Daemon upgrade pending' in (v:=t('capture-pane','-p','-S','-2000','-t',name)) else None),'Visible upgrade prompt '+name,10);(root/(name+'-prompt.txt')).write_text(screen);report['notices_visible'][name]=True
    release.set()
  time.sleep(.05)
 assert updater.poll() is not None,'Updater exceeded qualification deadline'
 report['update_exit_code']=updater.returncode
 assert operation is not None,'Updater completed without a checkpoint preparation receipt'
 state=json.loads(operation.read_text());report['preparation']=state;report['operation_receipt']=str(operation)
 if report['mode'] in ('refuse','hang','legacy'):
  assert updater.returncode!=0 and state['phase']=='blocked',state
  if report['mode']=='legacy':
   assert 'save work and stop an older daemon once' in state['reason'],state
   assert not report.get('injected_requests'),'Unsupported daemon received checkpoint steering'
  assert os.readlink(home/'packages/app-server-daemon/current')==report['old_selection'],'Refusal changed installed selection'
  assert digest(P('/proc')/str(native_pid)/'exe')==digest(baseline),'Refusal stopped/replaced old daemon'
  rpc('thread/loaded/list',dict(limit=100))
  def released():
   from codex_wake.records import WakeError
   try:return rpc('thread/start',dict(cwd=str(ws),historyMode='paginated'))
   except WakeError as error:
    if str(error)=='native lifecycle request rejected: thread/start':return None
    raise
  wait(released,'Cancelled preparation released new-work admission',5)
  report.update(state='passed',refusal_holds_old_daemon=True,cancellation_releases_admission=True)
 else:
  assert updater.returncode==0 or report['mode']=='startup-fail',state
  assert report.get('notices_visible')==dict(active0=True,active0mirror=True,active1=True,idle=True),report.get('notices_visible')
  assert report.get('new_work_held_during_preparation') is True
  files={tid:json.loads(P(v['file']).read_text()) for tid,v in state['threads'].items()}
  assert set(report['active_threads']+[idle])<=set(files),files.keys()
  for tid in active:assert files[tid]['upgrade_id']==state['operation_id'] and files[tid]['thread_id']==tid and files[tid]['ready']
  assert files[idle]['kind']=='idle_snapshot';assert idle not in report.get('agent_handoffs',{}),'Idle session unnecessarily called model'
  report['handoff_files']=files
  if report['mode']=='startup-fail':
   assert updater.returncode!=0 and failed_start_log is not None and state['phase']=='installing',state
   assert not report.get('resumed'),'Work woke while the replacement could not start'
   failed_start_log.chmod(failed_start_log_mode)
   report['failed_start_no_work_before_repair']=True
   repaired=subprocess.run([str(target),'app-server','daemon','start'],env=env,cwd=ws,capture_output=True,text=True,timeout=30)
   (root/'failed-start-repair.log').write_text(repaired.stdout+repaired.stderr);assert repaired.returncode==0,repaired.stderr
   report['upgrader_exited_before_native_startup_recovery']=True
  newendpoint='unix://'+str(control.resolve(strict=True))
  with socket.socket(socket.AF_UNIX) as s:s.connect(newendpoint[7:]);newpid,newuid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
  assert newpid!=native_pid and newuid==os.getuid() and digest(P('/proc')/str(newpid)/'exe')==digest(target)
  report['new_pid']=newpid
  if report['mode']=='retention':
   assert len(retention_locks)==40 and all(json.loads((home/'daemon-upgrades'/name/'state.json').read_text())['phase']=='installing' for name in report['inventory_fixture']['pending_empty'])
   report['cold_pending_operations_at_replacement']=40
   for lease in retention_locks:lease.close()
   retention_locks.clear()
  if report['mode']=='adoption':
   state=wait(lambda:(v if (v:=json.loads(operation.read_text()))['phase']=='installedPaused' else None),'Explicit first-adoption compatibility verdict',15)
   assert state['recovery_enabled'] is False and 'lacks recovery seals' in state['recovery_compatibility'],state
   after={tid:native_request(newendpoint,str(target),'thread/goal/get',dict(threadId=tid),5)['goal'] for tid in active}
   for tid,g in after.items():
    before=report['goals_before'][tid];assert g['status']=='paused' and all(g[k]==before[k] for k in ['objective','createdAt','tokenBudget']) and g['tokensUsed']>=before['tokensUsed'],g
   assert not report.get('resumed'),'Old daemon without seals resumed work'
   manifest=shared/'builds.json';v=json.loads(manifest.read_text());v['builds']['modded'].update(executable=str(target),sha256=digest(target),revision='first-adoption-qualified-fixture');manifest.write_text(json.dumps(v))
   pane('fresh',report['active_threads'][0])
   for name in ['active0','active0mirror','active1','idle']:
    frame=t('capture-pane','-p','-S','-2000','-t',name)
    if 'Resume paused goal?' in frame and 'Leave paused' in frame:t('send-keys','-t',name,'Escape')
   for tid in [*active,idle]:
    native_request(newendpoint,str(target),'thread/notice/append',dict(threadId=tid,eventId='adoption_live_'+tid,text='QUALIFIED_REPLACEMENT_LIVE. [External supervision event adoption_live_'+tid+']'),5)
   for name in ['active0','active0mirror','active1','idle','fresh']:
    shown=wait(lambda:(frame if 'QUALIFIED_REPLACEMENT_LIVE' in (frame:=t('capture-pane','-p','-S','-2000','-t',name)) else None),'New replacement notice in original/fresh '+name,20)
    (root/('adoption-'+name+'-live.txt')).write_text(shown)
   report['replacement_notice_received_in_original_and_fresh_tabs']=True
   for name,tid in [('active0',report['active_threads'][0]),('active0mirror',report['active_threads'][0]),('active1',report['active_threads'][1]),('idle',idle),('fresh',report['active_threads'][0])]:
    frame=t('capture-pane','-p','-S','-2000','-t',name)
    if 'Resume paused goal?' in frame and 'Leave paused' in frame:t('send-keys','-t',name,'Escape')
    t('send-keys','-t',name,'-l','/status');time.sleep(.4);t('send-keys','-t',name,'Enter')
    shown=wait(lambda:(frame if re.search(r'Session:\s*'+re.escape(tid),(frame:=t('capture-pane','-p','-S','-2000','-t',name))) else None),'First-adoption original/fresh tab '+name,20)
    (root/('adoption-'+name+'-status.txt')).write_text(shown)
   report.update(state='passed',first_adoption_installed_paused=True,actual_different_executable=digest(baseline)!=digest(target),goals_after=after,preparation=state,original_tabs_reconnected=True,fresh_launch_qualified=True)
   raise QualificationPassed()
  if report['mode']=='accepted-crash':
   wait(lambda:set(report.get('accepted_streams',{}))==set(active),'Accepted recovery streams before native crash',20)
   accepted_before={tid:json.loads((operation.parent/(tid+'.recovery.json')).read_text()) for tid in active}
   assert all(v['status']=='resumed' for v in accepted_before.values()),accepted_before
   def saved_contexts():
    contexts=[]
    for path in (home/'sessions').rglob('*.jsonl'):
     for line in path.read_text().splitlines():
      try:v=json.loads(line)
      except json.JSONDecodeError:continue
      if v.get('type')=='turn_context':contexts.append(v.get('payload',{}).get('turn_id'))
    return all(v['turn_id'] in contexts for v in accepted_before.values())
   wait(saved_contexts,'Original accepted turn contexts persisted before controlled crash',10)
   os.kill(newpid,signal.SIGKILL);report['server_crashed']=True;resume_stream_release.set()
   restarted=subprocess.run([str(target),'app-server','daemon','start'],env=env,cwd=ws,capture_output=True,text=True,timeout=30)
   (root/'accepted-crash-restart.log').write_text(restarted.stdout+restarted.stderr);assert restarted.returncode==0,restarted.stderr
   newendpoint='unix://'+str(control.resolve(strict=True))
   with socket.socket(socket.AF_UNIX) as sock:sock.connect(newendpoint[7:]);newpid,newuid,_=struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
   assert newpid!=report['new_pid'];report['after_crash_pid']=newpid
   wait(lambda:set(report.get('resumed',{}))==set(active),'Startup continues original accepted work',30)
   accepted_after={tid:json.loads((operation.parent/(tid+'.recovery.json')).read_text()) for tid in active}
   assert all(accepted_before[tid]['turn_id']==v['turn_id'] and accepted_before[tid]['runtime_epoch']!=v['runtime_epoch'] for tid,v in accepted_after.items()),accepted_after
   report.update(fault='Actual replacement daemon SIGKILL after native acceptance, while provider streams remain incomplete',accepted_before_crash=accepted_before,accepted_after_crash=accepted_after,same_turn_identity_after_crash=True)
  if coordinator:
   held_thread=report['active_threads'][0]
   def live(method,params):return native_request(newendpoint,str(target),method,params,8)
   if report['mode']=='owner-loss':
    assert coordinator_child is not None and coordinator_child.poll() is None
    started=time.monotonic()
    while time.monotonic()-started<35:
     assert not report.get('resumed'),'Work admitted while real coordinator lease remained owned'
     time.sleep(.1)
    coordinator_child.kill();coordinator_child.wait(timeout=5)
    report['owner_loss']=dict(held_after_replacement_seconds=time.monotonic()-started,exit_code=coordinator_child.returncode,kind='Actual SIGKILL of separate coordinator owner; no manual wake, recovery request or daemon restart')
   elif authority_case.startswith('seal-'):
    path=operation.parent/(held_thread+'.recovery.json');v=json.loads(path.read_text());assert v['status']=='sealed',v
    if authority_case=='seal-version':v['resource_authority']['version']=2
    elif authority_case=='seal-missing':v.pop('resource_authority',None)
    elif authority_case=='seal-account':v['resource_authority']['account']['account_id']='changed-account'
    elif authority_case=='seal-bool-version':v['resource_authority']['version']=True
    else:raise AssertionError('Unknown authority fixture '+authority_case)
    durable_fixture_json(path,v);report['fault']='Explicit invalid host authority seal fixture '+authority_case
   elif report['mode']=='bad-handoff':
    path=operation.parent/(held_thread+'.json');v=json.loads(path.read_text());v['remaining'].append('Unexpected changed work after seal')
    durable_fixture_json(path,v)
    report['fault']='Actual durable handoff changed after native seal; original authority must not be widened'
   elif report['mode'] in ('wrong-target','wrong-digest'):
    v=json.loads(operation.read_text())
    if report['mode']=='wrong-target':v['target_path']=str(P(report['old_selection'])/'bin/codex')
    else:v['target_digest']='00'*32
    durable_fixture_json(operation,v)
    report['fault']='Explicit altered immutable target '+('path' if report['mode']=='wrong-target' else 'digest')+' binding; actual serving replacement must be rejected'
   elif report['mode']=='userpause':
    live('thread/goal/set',dict(threadId=held_thread,status='paused',origin='user'))
    report['fault']='Independent native paused-to-paused user control after checkpoint'
   elif report['mode']=='unknown':
    path=operation.parent/(held_thread+'.recovery.json');v=json.loads(path.read_text());assert v['status']=='sealed',v
    v.update(status='dispatching',dispatch_epoch='synthetic-interrupted-journal-input')
    durable_fixture_json(path,v)
    report['fault']='Explicit synthetic interrupted-dispatch journal based on actual native seal; no accepted history'
   elif report['mode']=='response-loss':
    code='''import json,sys,time
from websockets.sync.client import unix_connect
with unix_connect(sys.argv[1],open_timeout=5,close_timeout=1) as c:
 def call(i,m,p):
  c.send(json.dumps(dict(id=i,method=m,params=p)))
  while True:
   v=json.loads(c.recv(timeout=8))
   if v.get('id')==i:return v
 call(1,'initialize',dict(clientInfo=dict(name='lost_response_fixture',version='0'),capabilities=dict(experimentalApi=True)))
 c.send(json.dumps(dict(method='initialized')))
 assert 'result' in call(2,'daemon/upgrade/prepare',dict(operationId=sys.argv[2]))
 c.send(json.dumps(dict(id=3,method='daemon/upgrade/recovery',params=dict(operationId=sys.argv[2],threadId=sys.argv[3],action='resume'))))
 # Intentionally never read the recovery response; parent kills this connection after native acceptance.
 time.sleep(40)
'''
    child=subprocess.Popen([sys.executable,'-c',code,newendpoint[7:],state['operation_id'],held_thread],env=env,cwd=ws,stdout=(root/'lost-response-child.log').open('w'),stderr=subprocess.STDOUT)
    try:wait(lambda:held_thread in report.get('resumed',{}),'Native accepted work before response loss',15)
    finally:child.kill();child.wait(timeout=5)
    report['fault']='Actual recovery client killed without reading accepted response'
   import fcntl
   fcntl.flock(coordinator,fcntl.LOCK_UN);coordinator.close();coordinator=None
   if report['mode'] in ('userpause','unknown','bad-handoff','wrong-target','wrong-digest'):
    expected=set() if report['mode'] in ('wrong-target','wrong-digest') else set(active)-{held_thread}
    wait(lambda:set(report.get('resumed',{}))==expected,'Other session resumes independently',30)
    def held():
     v=json.loads(operation.read_text());return v if v['phase']=='recoveryHeld' else None
    settled=wait(held,'Native held recovery verdict',15)
    replay=recovery_replay(newendpoint,state['operation_id'],active)
    assert replay[held_thread]['status']=='held',replay
    assert held_thread not in report.get('resumed',{}),'Cancelled/unknown work resumed'
    g=live('thread/goal/get',dict(threadId=held_thread))['goal'];before=report['goals_before'][held_thread]
    assert g['status']=='paused' and all(g[k]==before[k] for k in ['objective','createdAt','tokenBudget']),g
    reason=replay[held_thread]['reason'].lower()
    expected_reason={'userpause':'goal control changed','unknown':'delivery is unknown','bad-handoff':'handoff changed','wrong-target':'does not match','wrong-digest':'does not match'}[report['mode']]
    assert expected_reason in reason,replay
    if report['mode'] in ('wrong-target','wrong-digest'):assert all(v['status']=='held' for v in replay.values()),replay
    assert_no_recovery_requests(active if report['mode'] in ('wrong-target','wrong-digest') else [held_thread])
    report.update(state='passed',recovery_verdicts=replay,preparation=settled,held_work_never_submitted=True)
    raise QualificationPassed()
  if report['mode'] in ('originalpause','deadline','exhausted'):
   held_thread=report['active_threads'][0];expected=set(active)-{held_thread}
   wait(lambda:set(report.get('resumed',{}))==expected,'Eligible other conversation resumes',30)
   expected_phase='recovered' if report['mode'] in ('originalpause','exhausted') else 'recoveryHeld'
   settled=wait(lambda:(v if (v:=json.loads(operation.read_text()))['phase']==expected_phase else None),'Eligibility recovery verdict',15)
   replay=recovery_replay(newendpoint,state['operation_id'],active)
   assert replay[held_thread]['status']==('skipped' if report['mode'] in ('originalpause','exhausted') else 'held'),replay
   g=native_request(newendpoint,str(target),'thread/goal/get',dict(threadId=held_thread),5)['goal'];before=report['goals_before'][held_thread]
   assert g['status']==('budgetLimited' if report['mode']=='exhausted' else 'paused') and all(g[k]==before[k] for k in ['objective','createdAt','tokenBudget']),g
   if report['mode']=='deadline':assert any(term in replay[held_thread]['reason'].lower() for term in ('deadline','authority','resource','paused')),replay
   if report['mode']=='exhausted':assert g['tokensUsed']>=g['tokenBudget'] and 'exhausted' in replay[held_thread]['reason'].lower(),replay
   assert_no_recovery_requests([held_thread])
   report.update(state='passed',recovery_verdicts=replay,preparation=settled,held_work_never_submitted=True,held_goal=g)
   raise QualificationPassed()
  wait(lambda:set(report.get('resumed',{}))==set(active),'Automatic work resumption after upgrade',30)
  state=wait(lambda:(v if (v:=json.loads(operation.read_text()))['phase']=='recovered' else None),'Durable recovery completion',15)
  report['preparation']=state
  after={tid:wait(lambda:(goal if (goal:=native_request(newendpoint,str(target),'thread/goal/get',dict(threadId=tid),5)['goal'])['status']=='paused' else None),'Bounded resumed packet paused '+tid,10) for tid in active}
  for tid,g in after.items():
   before=report['goals_before'][tid];assert g['status']=='paused' and all(g[k]==before[k] for k in ['threadId','objective','createdAt','tokenBudget']) and g['tokensUsed']>=before['tokensUsed'],g
  def select_launcher_build(executable):
   manifest=shared/'builds.json';v=json.loads(manifest.read_text());row=v['builds']['modded'];row.update(executable=str(executable),sha256=digest(executable),revision='qualified-upgrade-fixture')
   staged=manifest.with_suffix('.next');staged.write_text(json.dumps(v));os.replace(staged,manifest)
   report.setdefault('fixture_build_registrations',[]).append(dict(executable=str(executable),sha256=digest(executable)))
  select_launcher_build(target);pane('fresh',report['active_threads'][0])
  def status_checks(label):
   history_visibility(newendpoint,target if label=='upgrade' else rollback_executable,label)
   result={}
   for name,tid in [('active0',report['active_threads'][0]),('active0mirror',report['active_threads'][0]),('active1',report['active_threads'][1]),('idle',idle),('fresh',report['active_threads'][0])]+([('rollbackfresh',report['active_threads'][0])] if label=='rollback' else []):
    frame=t('capture-pane','-p','-S','-2000','-t',name)
    if 'Resume paused goal?' in frame and 'Leave paused' in frame:t('send-keys','-t',name,'Escape')
    t('send-keys','-t',name,'-l','/status');time.sleep(0.4);t('send-keys','-t',name,'Enter')
    shown=wait(lambda:(v if re.search(r'Session:\s*'+re.escape(tid),(v:=t('capture-pane','-p','-S','-2000','-t',name))) else None),'Actual TUI session identity after '+label+' '+name,15)
    (root/(label+'-'+name+'-status.txt')).write_text(shown);result[name]=tid
   return result
  report['resumed_output_in_original_tabs']={}
  for name in ['active0','active0mirror','active1']:
   shown=wait(lambda:(frame if 'UPGRADE_WORK_RESUMED' in (frame:=t('capture-pane','-p','-S','-2000','-t',name)) else None) , 'Resumed work visible in original '+name,30)
   (root/(name+'-resumed.txt')).write_text(shown);report['resumed_output_in_original_tabs'][name]=True
  report['ui_after_upgrade']=status_checks('upgrade')
  if os.environ.get('CODEX_QUALIFICATION_HEALTH')=='1':
   health={}
   for name,tid in [('active0',report['active_threads'][0]),('active0mirror',report['active_threads'][0]),('active1',report['active_threads'][1]),('fresh',report['active_threads'][0])]:
    pane_pid=int(t('display-message','-p','-t',name,'#{pane_pid}').strip())
    def registered_binding():
     pending=[pane_pid];seen=set()
     while pending:
      pid=pending.pop()
      if pid in seen:continue
      seen.add(pid)
      try:pending.extend(int(v) for v in P(f'/proc/{pid}/task/{pid}/children').read_text().split())
      except FileNotFoundError:continue
      bindings=native_request(newendpoint,str(target),'tui/health/describe',dict(pid=pid),5)['bindings']
      if bindings:return bindings[0]
    binding=wait(registered_binding,'Reconnected native health binding '+name,10)
    challenge=os.urandom(32).hex()
    observed=native_request(newendpoint,str(target),'tui/health/probe',dict(binding=binding,threadId=tid,challenge=challenge,timeoutMs=3000),5)
    assert observed['challenge']==challenge and observed['threadId']==tid and observed['state']=='responsive' and observed['evidence']=='tui_main_loop_ack',observed
    health[name]=observed
   report['health_after_recovery']=health
  report['work_requests_after_upgrade']={tid:sum(c['thread']==tid for c in calls) for tid in active}
  assert all(n==(6 if report['mode']=='accepted-crash' else 5) for n in report['work_requests_after_upgrade'].values()),report['work_requests_after_upgrade']
  if report['mode']=='retention':
   fixture=report['inventory_fixture']
   wait(lambda:all(json.loads((home/'daemon-upgrades'/name/'state.json').read_text())['phase']=='recovered' for name in fixture['pending_empty']),'All cold pending operations progress across bounded passes',30)
   assert all((home/'daemon-upgrades'/name/'state.json').is_file() for name in fixture['retained'])
   report['retained_evidence_preserved']=True
  if report['mode']=='delete-completed':
   deleted=report['active_threads'][0]
   acceptance=json.loads((operation.parent/(deleted+'.recovery.json')).read_text())
   for name in ['active0','active0mirror','fresh']:t('kill-session','-t',name,check=False)
   def delete_finished():
    try:
     report['delete_response']=native_request(newendpoint,str(target),'thread/delete',dict(threadId=deleted),5)
     return True
    except Exception as error:
     report['delete_wait_reason']=str(error);return None
   wait(delete_finished,'Supported deletion after completed work tabs close',15)
   stopped=subprocess.run([str(target),'app-server','daemon','stop'],env=env,cwd=ws,capture_output=True,text=True,timeout=20);assert stopped.returncode==0,stopped.stderr
   started=subprocess.run([str(target),'app-server','daemon','start'],env=env,cwd=ws,capture_output=True,text=True,timeout=30);assert started.returncode==0,started.stderr
   address='unix://'+str(control.resolve(strict=True))
   fresh=native_request(address,str(target),'thread/start',dict(cwd=str(ws),historyMode='paginated'),8)
   listing=native_request(address,str(target),'thread/list',dict(limit=100),8)
   assert deleted not in {row['id'] for row in listing['data']},listing
   assert {tid:sum(c['thread']==tid for c in calls) for tid in active}==report['work_requests_after_upgrade'],'Deletion/restart duplicated work'
   report.update(state='passed',completed_deleted_without_replay=True,deleted_thread=deleted,accepted_before_deletion=acceptance,fresh_thread_after_restart=fresh['thread']['id'],deleted_history_not_resurrected=True)
   raise QualificationPassed()
  replay=recovery_replay(newendpoint,state['operation_id'],active)
  assert all(v['status']=='alreadyResumed' for v in replay.values()),replay
  assert {tid:sum(c['thread']==tid for c in calls) for tid in active}==report['work_requests_after_upgrade'],'Recovery replay duplicated model work'
  report['duplicate_recovery_reconciled']=True
  for tid in active:
   turns=native_request(newendpoint,str(target),'thread/turns/list',dict(threadId=tid,limit=30,itemsView='notLoaded'),5)['data']
   resumed=[turn for turn in turns if turn.get('turnTrigger')=='daemon_upgrade']
   # Native turn metadata may expose trigger through history rather than list; the recovery receipt binds its exact turn ID.
   assert report['resumed'][tid]['packet']['checkpoint_turn_id']==active[tid]['turn_id']
   acceptance=json.loads((operation.parent/(tid+'.recovery.json')).read_text())
   assert acceptance['turn_id']==replay[tid]['turnId'] and acceptance['root_turn_id']==active[tid]['turn_id'],acceptance
   assert any(turn['id']==acceptance['turn_id'] for turn in turns),turns
   report.setdefault('accepted_turns',{})[tid]=acceptance
  file_hashes={tid:digest(P(state['threads'][tid]['file'])) for tid in files}
  rollback_executable=P(os.environ.get('CODEX_QUALIFICATION_ROLLBACK',str(baseline)))
  report['rollback_expected_sha256']=digest(rollback_executable)
  rollback=subprocess.run([str(rollback_executable),'app-server','daemon','update','--from-cli','--yes'],env=env,cwd=ws,capture_output=True,text=True,timeout=40)
  (root/'rollback.log').write_text(rollback.stdout+rollback.stderr);assert rollback.returncode==0,rollback.stderr
  restored='unix://'+str(control.resolve(strict=True))
  with socket.socket(socket.AF_UNIX) as s:s.connect(restored[7:]);rollback_pid,rollback_uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
  assert rollback_pid!=newpid and rollback_uid==os.getuid() and digest(P('/proc')/str(rollback_pid)/'exe')==digest(rollback_executable)
  assert {tid:digest(P(state['threads'][tid]['file'])) for tid in files}==file_hashes,'Rollback changed durable handoffs'
  for tid in active:
   g=native_request(restored,str(rollback_executable),'thread/goal/get',dict(threadId=tid),5)['goal'];assert g['status']=='paused' and all(g[k]==after[tid][k] for k in ['threadId','objective','createdAt','tokenBudget','tokensUsed']),g
  select_launcher_build(rollback_executable);pane('rollbackfresh',report['active_threads'][0])
  report['ui_after_rollback']=status_checks('rollback')
  report.update(state='passed',all_tabs_notified=True,durable_handoffs_before_replacement=True,goals_after=after,counters_and_limits_preserved=True,rollback_preserves_handoffs=True,rollback_pid=rollback_pid)
except QualificationPassed:
 pass
except BaseException as e:
 report.update(state='failed',error=repr(e),traceback=traceback.format_exc())
 for name in ['bootstrap','active0','active0mirror','active1','idle','fresh','rollbackfresh']:
  (root/('failure-'+name+'.txt')).write_text(t('capture-pane','-p','-S','-2000','-t',name,check=False))
finally:
 if failed_start_log is not None:failed_start_log.chmod(failed_start_log_mode)
 if failed_executable is not None:failed_executable.chmod(failed_mode)
 for lease in retention_locks:lease.close()
 if coordinator_child is not None and coordinator_child.poll() is None:coordinator_child.kill();coordinator_child.wait(timeout=5)
 if coordinator:coordinator.close()
 finish.set();release.set();resume_stream_release.set();t('kill-server',check=False)
 if updater and updater.poll() is None:
  os.killpg(updater.pid,signal.SIGTERM)
  try:updater.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(updater.pid,signal.SIGKILL);updater.wait()
 subprocess.run([str(target),'app-server','daemon','stop'],env=env,capture_output=True,timeout=20)
 for proc in P('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:
   if proc.stat().st_uid==os.getuid() and b'pid-update-loop' in (proc/'cmdline').read_bytes() and ('CODEX_HOME='+str(home)).encode() in (proc/'environ').read_bytes().split(bytes([0])):os.kill(int(proc.name),signal.SIGTERM)
  except OSError:pass
 http.shutdown();http.server_close();report['calls']=calls;save()
print(json.dumps({k:report.get(k) for k in ['state','error','update_exit_code','all_tabs_notified','refusal_holds_old_daemon']},indent=2))
raise SystemExit(0 if report['state']=='passed' else 1)
