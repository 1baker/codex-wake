"""Private, idle-expiring bridge to fresh Windows QPC reads (never UTC)."""
import base64
import ctypes
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import stat
import subprocess
import sys
import uuid

SCRIPT = '''while ($null -ne ($id = [Console]::ReadLine())) {
 [Console]::WriteLine("{0},{1},{2}",$id,[Diagnostics.Stopwatch]::GetTimestamp(),[Diagnostics.Stopwatch]::Frequency)
}'''
_CHILDREN = []
COMMAND = ['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
           '-NoProfile', '-NonInteractive', '-EncodedCommand',
           base64.b64encode(SCRIPT.encode('utf-16le')).decode()]


def _directory(directory):
    root = Path(directory) if directory else Path.home()/'.local/state/codex-wake/host-counter'
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('counter_directory_not_private')
    return root


class _TransportFuse:
    """Linux kernel blocking-I/O fuse, never time or elapsed evidence.

    This bootstrap cannot acquire Stable Time through itself. The relative
    timer only aborts owned transport work; actual QPC handoff validation owns
    authority. No clock value is read and the timer is never reset on progress.
    """
    def __init__(self, seconds):
        if sys.platform != 'linux' or ctypes.sizeof(ctypes.c_long) != 8:
            raise ValueError('counter_transport_fuse_unavailable')
        class Timespec(ctypes.Structure):
            _fields_=[('seconds',ctypes.c_long),('nanoseconds',ctypes.c_long)]
        class Itimerspec(ctypes.Structure):
            _fields_=[('interval',Timespec),('value',Timespec)]
        self.fd = -1
        try:
            libc=ctypes.CDLL(None,use_errno=True)
            create=libc.timerfd_create
            create.argtypes=[ctypes.c_int,ctypes.c_int];create.restype=ctypes.c_int
            arm=libc.timerfd_settime
            arm.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.POINTER(Itimerspec),ctypes.c_void_p]
            arm.restype=ctypes.c_int
            # CLOCK_MONOTONIC selects an OS blocking primitive, not a measurement.
            self.fd=create(1,os.O_CLOEXEC|os.O_NONBLOCK)
            if self.fd<0:
                raise OSError(ctypes.get_errno(),'timerfd_create failed')
            value=Itimerspec(Timespec(0,0),Timespec(seconds,0))
            if arm(self.fd,0,ctypes.byref(value),None):
                raise OSError(ctypes.get_errno(),'timerfd_settime failed')
        except (OSError,AttributeError,TypeError):
            if self.fd>=0:os.close(self.fd)
            raise ValueError('counter_transport_fuse_unavailable') from None

    def __enter__(self):
        return self

    def __exit__(self,*args):
        os.close(self.fd)

    def wait(self,streams=(),*,writers=(),pause=None):
        ready=select.select([self.fd,*streams],writers,[],pause)[0]
        if self.fd in ready:
            raise TimeoutError('counter_read_timeout')
        return ready


def _line(stream, fuse):
    data = bytearray()
    while len(data) < 256:
        fuse.wait([stream])
        chunk = os.read(stream.fileno(), 1)
        if not chunk:
            raise ValueError('counter_eof')
        if chunk == b'\n':
            return bytes(data).decode('ascii').strip()
        data.extend(chunk)
    raise ValueError('counter_response_too_large')


def _write(stream,data,fuse):
    pending=memoryview(data)
    while pending:
        fuse.wait(writers=[stream])
        try:
            written=os.write(stream.fileno(),pending)
        except BlockingIOError:
            continue
        if written<=0:raise ValueError('counter_eof')
        pending=pending[written:]


def _values(counter, frequency):
    if not all(type(x) is int for x in (counter, frequency)) or counter < 0 or frequency <= 0:
        raise ValueError('invalid_host_counter')
    return counter, frequency


def counter_socket(directory=None):
    """The private endpoint used by this user's maintained QPC bridge."""
    return _directory(directory)/'counter.sock'


def read_counter(directory=None, *, start=True):
    """Read a newly sampled counter through the current user's private bridge."""
    with _TransportFuse(5) as fuse:
        address = counter_socket(directory)
        root = address.parent
        launched = False
        request_id = uuid.uuid4().hex
        while True:
            try:
                fuse.wait(pause=0)
                info = address.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ValueError('counter_socket_not_private')
                with socket.socket(socket.AF_UNIX) as client:
                    client.setblocking(False)
                    try:
                        client.connect(str(address))
                    except BlockingIOError:
                        fuse.wait(writers=[client])
                        error=client.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
                        if error:raise OSError(error,'counter connection failed')
                        client.getpeername()  # A writable unconnected socket is not admission.
                    _write(client,(request_id+'\n').encode(),fuse)
                    data = _line(client, fuse)
                    fuse.wait(pause=0)
                    response = json.loads(data)
                    if not isinstance(response, dict) or response.get('id') != request_id or response.get('status') != 'ok':
                        raise ValueError('counter_response_rejected')
                    return _values(response['counter'], response['frequency'])
            except (FileNotFoundError, ConnectionRefusedError) as exc:
                # A private bridge publishes its socket before listen(). Waiting for
                # that existing owner does not start a bridge or replay a request:
                # connect() refused before any bytes reached the producer.
                if not start and isinstance(exc, ConnectionRefusedError):
                    fuse.wait(pause=.02)
                    continue
                if not start:
                    raise ValueError('counter_bridge_unavailable') from None
                if not launched:
                    # Child imports this exact source/release; never substitute another CLI.
                    for pid in _CHILDREN[:]:
                        try:
                            if os.waitpid(pid, os.WNOHANG)[0]:
                                _CHILDREN.remove(pid)
                        except ChildProcessError:
                            _CHILDREN.remove(pid)
                    actions = [(os.POSIX_SPAWN_OPEN, fd, '/dev/null',
                                os.O_RDONLY if fd == 0 else os.O_WRONLY, 0o600) for fd in range(3)]
                    _CHILDREN.append(os.posix_spawn(sys.executable,
                        [sys.executable, str(Path(__file__).resolve()), '--serve', str(root)],
                        os.environ, file_actions=actions, setpgroup=0))
                    launched = True
                fuse.wait(pause=.02)


def serve_counter(directory, *, command=None, idle_seconds=60):
    """Own one serialized native producer; terminate on malformed or late output."""
    # Refuse unsupported fuse construction before creating state or a producer.
    with _TransportFuse(1):
        root = _directory(directory)
    lock_path = root/'bridge.lock'
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        info = os.fstat(lock.fileno())
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('counter_lock_not_private')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        address = root/'counter.sock'
        if address.exists() or address.is_symlink():
            info = address.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError('counter_socket_not_owned')
            address.unlink()
        producer = None
        try:
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(address))
                address.chmod(0o600)
                server.listen(16)
                # Windows interop cannot traverse another WSL user's private cwd.
                producer = subprocess.Popen(command or COMMAND, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0, cwd='/tmp')
                os.set_blocking(producer.stdin.fileno(),False)
                server.settimeout(idle_seconds)
                while True:
                    try:
                        client, _ = server.accept()
                    except socket.timeout:
                        return
                    with client:
                        try:
                            client.setblocking(False)
                            with _TransportFuse(1) as request_fuse:
                                request_id = _line(client, request_fuse)
                            if len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
                                continue
                            with _TransportFuse(4) as producer_fuse:
                                _write(producer.stdin,(request_id+'\n').encode(),producer_fuse)
                                parts = _line(producer.stdout, producer_fuse).split(',')
                            if len(parts) != 3 or parts[0] != request_id or not all(x.isascii() and x.isdigit() for x in parts[1:]):
                                raise ValueError('counter_producer_mismatch')
                            counter, frequency = _values(*map(int, parts[1:]))
                            with _TransportFuse(1) as response_fuse:
                                _write(client,(json.dumps(dict(id=request_id, status='ok', counter=counter,
                                                               frequency=frequency))+'\n').encode(),response_fuse)
                        except (OSError, ValueError, TimeoutError):
                            # No stale output reuse, fallback or automatic replay of this read.
                            return
        finally:
            if producer:
                producer.stdin.close()
                try:
                    producer.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    producer.kill()
                    producer.wait()
                producer.stdout.close()
            address.unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--serve':
        raise SystemExit(2)
    serve_counter(Path(sys.argv[2]))
