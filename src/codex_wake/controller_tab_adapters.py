"""Host presentation adapters and exclusive use of an existing stdio owner."""
import threading
import uuid

from .managed_inventory import InventoryError
from .tab_organization import TmuxTransport


class UnavailableAttachmentTransport:
    """Retain configured ownership when its terminal has disappeared.

    No runtime capability or input custody is inferred from configuration.
    Metadata-only global controls remain usable while reads report unavailable.
    """
    def snapshot(self, deadline):
        raise InventoryError('attachment_unavailable','Configured terminal socket is absent; restart or refresh the workspace.')


class TmuxAttachmentTransport(TmuxTransport):
    def formatting(self, action, arguments, deadline):
        from .tab_format_transport import tmux_formatting
        return tmux_formatting(self,action,arguments,deadline)

    def formatting_batch(self, requests, deadline):
        from .tab_format_transport import tmux_formatting_batch
        # Preserve host-specific adapter overrides, including fault-injection and
        # ownership adapters which deliberately replace the finite single seam.
        if getattr(self.formatting,'__func__',None) is not TmuxAttachmentTransport.formatting:
            return [self.formatting(request['action'],{k:v for k,v in request.items() if k!='action'},deadline)
                    for request in requests]
        return tmux_formatting_batch(self,requests,deadline)

    def formatting_read_session_windows(self, windows, deadline):
        if getattr(self.formatting,'__func__',None) is not TmuxAttachmentTransport.formatting:
            return (self.formatting('read-session',{},deadline),
                    self.formatting_batch([dict(action='read',window=w) for w in windows],deadline))
        from .tab_format_transport import tmux_formatting_read_session_windows
        return tmux_formatting_read_session_windows(self,windows,deadline)

    def capture(self, pane, lines, deadline):
        return self.command(deadline, 'capture-pane', '-p', '-t', pane, '-S', '-' + str(lines))

    def visible_screen(self, pane, deadline):
        return self.command(deadline, 'capture-pane', '-p', '-t', pane)

    def paste_literal(self, pane, text, deadline):
        import subprocess
        import time
        # The body travels over stdin, never through a shell or process argv.
        # Check the pinned socket both before loading and before presentation.
        self.command(deadline,'display-message','-p','#{pid}')
        name='wake-paste-'+uuid.uuid4().hex
        try:
            subprocess.run(['tmux','-S',self.socket,'load-buffer','-b',name,'-'],
                           input=text,text=True,capture_output=True,check=True,
                           timeout=max(.001,deadline-time.monotonic()))
            self.command(deadline,'paste-buffer','-p','-r','-d','-b',name,'-t',pane)
        finally:
            try:self.command(deadline,'delete-buffer','-b',name)
            except (OSError,ValueError,subprocess.SubprocessError):pass

    def send_key_tokens(self, pane, keys, deadline):
        self.command(deadline,'send-keys','-t',pane,'--',*keys)


class PsmuxAttachmentTransport:
    """Finite host broker protocol, also used for Windows qualification fixtures.

    The host bridge owns psmux process/Windows identity. A protocol fixture is
    not Windows runtime qualification. No shell/path/argv comes from a caller.
    """
    def __init__(self, bridge, *, generation):
        self.bridge, self.generation = bridge, generation

    def request(self, action, arguments, deadline):
        reply = self.bridge(action, arguments, deadline)
        if not isinstance(reply, dict) or reply.get('generation') != self.generation:
            raise InventoryError('stale_target', 'psmux bridge generation changed')
        if 'error' in reply:
            error = reply['error']
            raise InventoryError(error.get('code', 'attachment_unavailable'),
                                 error.get('message', 'native presentation request failed'))
        if 'result' not in reply:
            raise InventoryError('attachment_unavailable', 'bridge returned no typed result')
        return reply['result']

    def snapshot(self, deadline):
        return dict(self.request('snapshot', {}, deadline), bridge_generation=self.generation)

    def swap(self, first, second, deadline):
        return self.request('swap', dict(first=first, second=second), deadline)

    def capture(self, pane, lines, deadline):
        return self.request('capture', dict(pane=pane, lines=lines), deadline)


    @property
    def pinned_server_id(self):
        return self.generation

    def same_server(self, other):
        return isinstance(other, PsmuxAttachmentTransport) and self.pinned_server_id == other.pinned_server_id

    def visible_screen(self, pane, deadline):
        return self.request('visible_screen', dict(pane=pane), deadline)

    def paste_literal(self, pane, text, deadline):
        return self.request('paste', dict(pane=pane, text=text), deadline)

    def send_key_tokens(self, pane, keys, deadline):
        return self.request('keys', dict(pane=pane, keys=keys), deadline)

    def attach_saved(self, intent, manifest_sha256, deadline):
        return self.request('attach_saved', dict(intent=intent, manifest_sha256=manifest_sha256), deadline)

    def formatting(self, action, arguments, deadline):
        allowed={'read':{'window'},'write':{'window','values'},'read-session':set(),'write-session':{'values'},'refresh':set()}
        if action not in allowed or not isinstance(arguments,dict) or set(arguments)!=allowed[action]:
            raise InventoryError('invalid_argument','Unsupported finite formatting arguments.')
        return self.request('formatting',dict(action=action,**arguments),deadline)

    def formatting_batch(self, requests, deadline):
        if not isinstance(requests,list) or not 1<=len(requests)<=256:
            raise InventoryError('invalid_argument','Formatting batch requires 1 through 256 typed requests.')
        import json
        frame=json.dumps(dict(action='formatting_batch',arguments=dict(requests=requests))).encode()
        if len(frame)>65536:
            raise InventoryError('capacity','Formatting batch exceeds the finite 65536-byte native frame; reduce the batch size.')
        return self.request('formatting_batch',dict(requests=requests),deadline)

    def lifecycle(self, action, arguments, deadline):
        allowed = {
            'create': {'name', 'cwd', 'position', 'anchor'}, 'rename': {'window', 'name'},
            'focus': {'window'}, 'close': {'window'},
            'move': {'window', 'destination_session', 'index', 'position', 'anchor'},
            'park': {'window', 'destination_session', 'index'},
            'restore': {'window', 'destination_session', 'index'},
        }
        if action not in allowed or not isinstance(arguments, dict) or set(arguments) - allowed[action]:
            raise InventoryError('unsupported_operation', 'unsupported finite psmux lifecycle operation')
        return self.request('lifecycle', dict(action=action, **arguments), deadline)


class OwnedStdioBroker:
    """Serialize the already-owned app-server client; never open another stdin.

    Host installs this object at the connection owner and shares this broker,
    rather than creating a competing reader/writer on the process pipes.
    """
    def __init__(self, client, *, bindings, owner_id):
        self.client, self.bindings = client, dict(bindings)
        self.custody = dict(available=True, transport='structured', owner_id=owner_id,
                            generation=uuid.uuid4().hex)
        self.lock = threading.Lock()
        self.closed = False

    def inspect(self):
        return dict(self.custody, available=not self.closed)

    def send(self, pane, text, *, expected_custody):
        with self.lock:
            if self.closed or expected_custody != self.inspect() or pane not in self.bindings:
                raise InventoryError('input_custody_required', 'structured connection ownership changed')
            # Existing owner translates typed input into structured turn/start.
            # An exception remains uncertain under ControllerRuntime; no fallback.
            return self.client.start_turn(self.bindings[pane], text)

    def relinquish(self):
        with self.lock:
            self.closed = True


class OwnedTerminalBroker:
    """Explicit literal-line fallback, installed only after host input custody.

    Caller must still pass privacy admission, exact pane generation and control
    grant. Never selected as recovery for failed structured submission.
    """
    def __init__(self, transport, *, panes, owner_id):
        self.transport, self.panes = transport, frozenset(panes)
        self.custody = dict(available=True,transport='terminal',owner_id=owner_id,generation=uuid.uuid4().hex,
                            input_modes=[mode for mode,method in [('paste','paste_literal'),('keys','send_key_tokens')] if callable(getattr(transport,method,None))])
        self.lock = threading.Lock()

    def inspect(self):
        return dict(self.custody)

    def send(self, pane, text, *, expected_custody):
        import time
        with self.lock:
            if expected_custody != self.custody or pane not in self.panes:
                raise InventoryError('input_custody_required', 'terminal custody changed')
            deadline = time.monotonic() + 5
            self.transport.command(deadline,'send-keys','-t',pane,'-l','--',text)
            self.transport.command(deadline,'send-keys','-t',pane,'Enter')
            return dict(status='submitted',acceptance='unverified',transport='terminal')

    def paste(self, pane, text, *, expected_custody):
        return self._explicit(pane,'paste_literal',text,expected_custody)

    def keys(self, pane, keys, *, expected_custody):
        return self._explicit(pane,'send_key_tokens',keys,expected_custody)

    def _explicit(self, pane, method, value, expected_custody):
        import time
        with self.lock:
            if expected_custody != self.inspect() or pane not in self.panes:
                raise InventoryError('input_custody_required','terminal custody changed')
            action=getattr(self.transport,method,None)
            if action is None:
                raise InventoryError('unsupported_transport','explicit terminal action is not qualified by this broker')
            action(pane,value,time.monotonic()+5)
            return dict(delivery='sent',acceptance='terminal_adapter',semantic_execution='unknown')


class ConfiguredBridge:
    """Host-fixed finite subprocess protocol; no command selection in requests."""
    def __init__(self, command):
        if not isinstance(command,list) or not command or any(not isinstance(x,str) for x in command):
            raise ValueError('host bridge command must be argv')
        self.command = command

    def __call__(self, action, arguments, deadline):
        import json
        import subprocess
        import time
        result = subprocess.run(self.command,input=json.dumps(dict(action=action,arguments=arguments)),
            text=True,capture_output=True,check=True,timeout=max(.001,min(15 if action=='attach_saved' else 5,deadline-time.monotonic())))
        if len(result.stdout)>1048576: raise ValueError('bridge reply exceeds bounded capacity')
        return json.loads(result.stdout)


class UnixInputBroker:
    """Proxy the existing host stdin custodian, never attach to its pipes."""
    def __init__(self, path):
        from pathlib import Path
        import os
        import stat
        self.path = Path(path)
        info = self.path.lstat()
        if (not self.path.is_absolute() or self.path != self.path.resolve() or
            not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError('input broker requires private user-owned socket')
        self.identity = (info.st_dev,info.st_ino)

    def request(self, action, arguments):
        import json
        import socket
        info = self.path.lstat()
        if (info.st_dev,info.st_ino) != self.identity:
            raise InventoryError('input_custody_required','broker socket generation changed')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as stream:
            stream.settimeout(5)
            stream.connect(str(self.path))
            stream.sendall(json.dumps(dict(action=action,arguments=arguments)).encode()+b'\n')
            data = b''
            while b'\n' not in data:
                chunk = stream.recv(65536)
                if not chunk: raise InventoryError('input_custody_required','broker disconnected')
                data += chunk
                if len(data)>262144: raise ValueError('broker reply exceeds bound')
            result = json.loads(data.split(b'\n',1)[0])
            if not isinstance(result,dict): raise ValueError('invalid broker response')
            return result

    def inspect(self):
        return self.request('inspect',{})

    def send(self,pane,text,*,expected_custody):
        return self.request('send',dict(pane=pane,input=text,expected_custody=expected_custody))

    def paste(self,pane,text,*,expected_custody):
        return self.request('paste',dict(pane=pane,text=text,expected_custody=expected_custody))

    def keys(self,pane,keys,*,expected_custody):
        return self.request('keys',dict(pane=pane,keys=keys,expected_custody=expected_custody))
