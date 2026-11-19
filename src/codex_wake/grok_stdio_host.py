"""Explicit local transport owner for one native Grok ACP stdio process.

This is a sole pipe owner, not a queue or executor fallback. No public operation
starts it. The operator's foreground command initializes once, then forwards
one active native request at a time. Disconnect never resubmits work. No grants,
resource counters, provider credentials or native goals are created/renewed.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs,urlsplit
from uuid import uuid4

from .controller_health import _image_hash,_process_matches
from .controller_runtime import bounded_id,encoded
from .managed_inventory import InventoryError
from .process import process_identity


def _save(path,value):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.stdio-host-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def _parent_death():
    ctypes.CDLL(None).prctl(1,signal.SIGTERM)
    if os.getppid()==1:os._exit(1)


class StdioOwner:
    def __init__(self,child,*,deadline=10):
        self.child=child;self.lock=threading.RLock();self.write_lock=threading.Lock()
        self.active=None;self.failure=None;self.initialized=threading.Event();self.metadata=None
        self.thread=threading.Thread(target=self._read,daemon=True);self.thread.start()
        self._write(dict(jsonrpc='2.0',id='host_initialize',method='initialize',params=dict(protocolVersion=1,clientCapabilities={},clientInfo=dict(name='codex_wake_stdio_host',version='0.22.0.dev2'))))
        if not self.initialized.wait(deadline) or self.metadata is None:raise InventoryError('native_unavailable','native ACP initialization did not qualify; no runtime published')
        result=self.metadata.get('result',{});meta=result.get('_meta',{})
        if result.get('protocolVersion')!=1 or not isinstance(result.get('agentCapabilities'),dict) or any(not isinstance(meta.get(key),str) or not meta[key] for key in ('agentVersion','agentId','agentInstanceId','currentWorkingDirectory')):
            raise InventoryError('unsupported_operation','native ACP identity/capabilities unavailable; no runtime published')

    def _write(self,value):
        raw=(encoded(value)+'\n').encode()
        if len(raw)>1048576:raise InventoryError('capacity','native stdio frame exceeds bound')
        with self.write_lock:self.child.stdin.write(raw);self.child.stdin.flush()

    @staticmethod
    def _send(client,value):
        try:client.send(encoded(value));return True
        except Exception:return False

    def _read(self):
        try:
            while True:
                raw=self.child.stdout.readline(1048577)
                if not raw:break
                if len(raw)>1048576 or not raw.endswith(b'\n'):raise ValueError('native frame bound')
                value=json.loads(raw)
                if not isinstance(value,dict) or value.get('jsonrpc')!='2.0':raise ValueError('native frame shape')
                if value.get('id')=='host_initialize' and 'method' not in value:
                    self.metadata=value;self.initialized.set();continue
                if 'method' in value and 'id' in value:
                    # Initial client capabilities are empty. This owner cannot
                    # approve native tools, read client files or start terminals.
                    response=dict(result=dict(outcome=dict(outcome='cancelled'))) if value['method']=='session/request_permission' else dict(error=dict(code=-32601,message='Client capability was not negotiated.'))
                    self._write(dict(jsonrpc='2.0',id=value['id'],**response));continue
                with self.lock:
                    active=self.active
                    if active is None:continue
                    if 'method' in value:
                        self._send(active['client'],value)
                    elif value.get('id')==active['native_id']:
                        self._send(active['client'],dict(value,id=active['client_id']))
                        self.active=None
        except Exception:self.failure='native_protocol_unavailable'
        finally:
            self.failure=self.failure or 'native_process_or_pipe_closed';self.initialized.set()
            with self.lock:
                if self.active:self._send(self.active['client'],dict(jsonrpc='2.0',id=self.active['client_id'],error=dict(code=-32099,message='Original native response unavailable.')))
                self.active=None

    def handle(self,client):
        for raw in client:
            if not isinstance(raw,str) or len(raw.encode())>1048576:client.close();return
            try:value=json.loads(raw)
            except ValueError:client.close();return
            if not isinstance(value,dict) or value.get('jsonrpc')!='2.0' or 'id' not in value:client.close();return
            identifier=value['id'];method=value.get('method');params=value.get('params') or {}
            if method=='initialize':
                if params.get('protocolVersion')!=1 or params.get('clientCapabilities',{})!={}:self._send(client,dict(jsonrpc='2.0',id=identifier,error=dict(code=-32602,message='Only cached ACPv1 baseline client capabilities are available.')));continue
                self._send(client,dict(self.metadata,id=identifier));continue
            if method not in ('session/new','session/load','session/prompt','session/list','session/set_model'):
                self._send(client,dict(jsonrpc='2.0',id=identifier,error=dict(code=-32601,message='No qualified stdio-host method.')));continue
            with self.lock:
                if self.failure:self._send(client,dict(jsonrpc='2.0',id=identifier,error=dict(code=-32099,message='Native owner unavailable.')));continue
                if self.active is not None:
                    self._send(client,dict(jsonrpc='2.0',id=identifier,error=dict(code=-32098,message='Native stdio owner is busy; no request queued.',data=dict(source='codex_wake_stdio_host',pre_io=True,reason='busy'))));continue
                native_id='host_'+uuid4().hex
                self.active=dict(client=client,client_id=identifier,native_id=native_id)
                try:self._write(dict(value,id=native_id))
                except Exception:
                    self.failure='native_write_uncertain';self.active=None
                    self._send(client,dict(jsonrpc='2.0',id=identifier,error=dict(code=-32099,message='Native write outcome uncertain.')))


def serve_host(root,*,profile,binary,home,cwd,account,ready_file,block_network=False,bind_port=0,host=None,environment=None):
    """Foreground explicit operator host; returns only after owned shutdown."""
    import socket
    from websockets.sync.server import serve
    bounded_id(profile);bounded_id(account)
    root=Path(root).resolve();root.mkdir(mode=0o700,parents=True,exist_ok=True)
    binary=Path(binary).resolve(strict=True);home=Path(home).resolve(strict=True);cwd=Path(cwd).resolve(strict=True)
    if not binary.is_file() or not os.access(binary,os.X_OK) or not home.is_dir() or not cwd.is_dir() or type(bind_port) is not int or not 0<=bind_port<=65535:raise InventoryError('invalid_argument','explicit native executable/home/cwd/local port required')
    directory=root/'grok-stdio-hosts'/hashlib.sha256(profile.encode()).hexdigest();directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock_fd=os.open(directory/'owner.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:os.close(lock_fd);raise InventoryError('native_owner_busy','this explicit stdio profile already has an owner') from None
    env={key:os.environ[key] for key in ('PATH','LANG','LC_ALL','TERM','SHELL') if key in os.environ}
    env.update(HOME=str(home),GROK_HOME=str(home/'.grok'),XDG_CONFIG_HOME=str(home/'.config'),XDG_STATE_HOME=str(home/'.local/state'),XDG_CACHE_HOME=str(home/'.cache'))
    command=[str(binary),'agent','--no-leader']
    if block_network:
        env.update(HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',ALL_PROXY='http://127.0.0.1:9',NO_PROXY='',GROK_SUBAGENTS='0')
        command+=['--xai-api-base-url','http://127.0.0.1:9','--cli-chat-proxy-base-url','http://127.0.0.1:9','--grok-ws-url','ws://127.0.0.1:9','--grok-ws-origin','http://127.0.0.1:9']
    command+=['stdio','--leader-socket',str(directory/'isolated-leader.sock')]
    native=None;listener=None;stop=threading.Event();old_signals={};log=(directory/'native.stderr').open('ab')
    for sig in (signal.SIGTERM,signal.SIGINT):
        old_signals[sig]=signal.signal(sig,lambda *unused:stop.set())
    try:
        native=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,start_new_session=True,preexec_fn=_parent_death)
        owner=StdioOwner(native)
        observed=process_identity(native.pid)
        if not observed or _image_hash(native.pid)!=hashlib.sha256(binary.read_bytes()).hexdigest():raise InventoryError('stale_target','selected immutable native binary differs from actual child image')
        metadata=owner.metadata['result'];meta=metadata['_meta']
        if meta['currentWorkingDirectory']!=str(cwd):raise InventoryError('stale_target','native ACP workspace differs from explicit host setup')
        secret=secrets.token_urlsafe(32);secret_file=directory/'transport.secret';secret_file.write_text(secret);secret_file.chmod(0o600)
        def process_request(connection,request):
            supplied=parse_qs(urlsplit(request.path).query).get('server-key',[])
            if urlsplit(request.path).path!='/ws' or len(supplied)!=1 or not secrets.compare_digest(supplied[0],secret):return connection.respond(401,'Native transport authentication required.\n')
        listener=serve(owner.handle,'127.0.0.1',bind_port,process_request=process_request,max_size=1048576)
        threading.Thread(target=listener.serve_forever,daemon=True).start()
        bridge=process_identity(os.getpid());assert bridge
        transport=dict(kind='grok_stdio_host',pid=os.getpid(),start_ticks=str(bridge['start_time_ticks']),boot_id=bridge['boot_id'],sha256=_image_hash(os.getpid()),stdin_inode=str(os.fstat(native.stdin.fileno()).st_ino),stdout_inode=str(os.fstat(native.stdout.fileno()).st_ino))
        target=dict(host=host or socket.gethostname(),environment=environment or os.environ.get('WSL_DISTRO_NAME') or os.name,runtime='grok',provider='grok',account=account,home=str(home),
            namespace='grok:'+hashlib.sha256(encoded([str(home),account]).encode()).hexdigest(),build_sha256=_image_hash(native.pid),build_revision=meta['agentVersion'],backend_id=meta['agentId'],channel='acp-websocket',connection_generation=meta['agentInstanceId'],process_pid=str(native.pid),process_start_ticks=str(observed['start_time_ticks']),process_boot_id=observed['boot_id'],configuration_revision=hashlib.sha256(encoded([str(binary),str(home),str(cwd),profile,account]).encode()).hexdigest())
        configuration=dict(target=target,endpoint='ws://127.0.0.1:'+str(listener.socket.getsockname()[1])+'/ws',secret_file=str(secret_file),cwd=str(cwd),agent_version=meta['agentVersion'],timeout=30,transport_owner=transport)
        registry=root/'controller-grok.json'
        with (root/'controller-grok.lock').open('a+') as catalog_lock:
            catalog_lock_path=root/'controller-grok.lock';catalog_lock_path.chmod(0o600);fcntl.flock(catalog_lock,fcntl.LOCK_EX)
            if registry.exists():
                if registry.is_symlink() or registry.stat().st_uid!=os.geteuid() or registry.stat().st_mode&0o077 or registry.stat().st_size>1048576:raise InventoryError('configuration_unavailable','existing private profile catalog unavailable')
                catalog=json.loads(registry.read_text())
                if catalog.get('version')!=1 or not isinstance(catalog.get('profiles'),dict):raise InventoryError('configuration_unavailable','existing Grok profile catalog invalid')
            else:catalog=dict(version=1,profiles={})
            prior=catalog['profiles'].get(profile)
            if prior:
                raw=prior.get('target',{})
                if _process_matches(dict(process=dict(pid=int(raw.get('process_pid','0')),start_ticks=raw.get('process_start_ticks'),boot_id=raw.get('process_boot_id')))):
                    raise InventoryError('native_owner_busy','existing profile still points to a live native owner; no replacement performed')
            if len(catalog['profiles'])>=256 and profile not in catalog['profiles']:raise InventoryError('capacity','Grok profile catalog capacity reached')
            catalog['profiles'][profile]=configuration;_save(registry,catalog)
        receipt=dict(schema_version=1,status='ready',profile=profile,target=target,transport_owner=transport,native_metadata=metadata,registry=str(registry),no_session_created=True,no_grant_issued=True,no_resource_renewal=True)
        _save(ready_file,receipt)
        print(encoded(dict(status='ready',profile=profile,target=target,ready_file=str(Path(ready_file).resolve()))),flush=True)
        while not stop.wait(.1):
            if native.poll() is not None or owner.failure:break
        _save(ready_file,dict(receipt,status='stopped',reason='operator_shutdown' if stop.is_set() else 'native_owner_unavailable'))
    finally:
        if listener is not None:listener.shutdown()
        if native is not None:
            try:os.killpg(native.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:native.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(native.pid,signal.SIGKILL);native.wait(timeout=5)
            for stream in (native.stdin,native.stdout):
                if stream is not None:stream.close()
        log.close();os.close(lock_fd)
        for sig,previous in old_signals.items():signal.signal(sig,previous)


def command(args,root):
    return serve_host(root,profile=args.profile,binary=args.binary,home=args.home,cwd=args.cwd,account=args.account,ready_file=args.ready_file,block_network=args.block_network,bind_port=args.port)


def register_host(commands):
    parser=commands.add_parser('stdio-host',help='explicit foreground owner of one native Grok ACP stdio child')
    for name in ('profile','account'):parser.add_argument('--'+name,required=True)
    for name in ('binary','home','cwd','ready-file'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--block-network',action='store_true',help='qualification only: force provider routes to rejected loopback endpoints')
