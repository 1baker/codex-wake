"""User-owned tmux/process access and operator-only binding enrollment."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from uuid import uuid4

from . import measurements
from .process import process_identity
from .records import WakeError


def digest(data):
    return hashlib.sha256(data).hexdigest()


class GrokTerminalHost:
    def __init__(self, root, *, deadline=None):
        self.deadline = deadline
        self._phase_deadline = None
        self.root = Path(root)
        self.tmux = shutil.which('tmux')

    def _tmux(self, binding, *args, input=None):
        socket = Path(binding['socket'])
        info = socket.lstat()
        if (not socket.is_absolute() or not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o077
                or not re.fullmatch(r'%[0-9]+', binding['pane'])):
            raise WakeError('untrusted_terminal_endpoint')
        timer = self.deadline if self.deadline is not None else measurements.deadline(3)
        if not callable(getattr(timer, 'remaining', None)):
            raise measurements.TimeUnavailable('retained_deadline_required')
        timeout = min(3, timer.remaining())
        if self._phase_deadline is not None:
            timeout = min(timeout, self._phase_deadline.remaining())
        if timeout <= 0:
            raise WakeError('terminal_observation_deadline_reached')
        from contextlib import nullcontext
        guard = nullcontext()
        if args and args[0] in ('send-keys', 'paste-buffer', 'load-buffer', 'delete-buffer'):
            from .guarded_interactions import automated_input_guard
            guard = automated_input_guard(self.root, binding)
        with guard:
            result = subprocess.run([self.tmux or '/usr/bin/tmux', '-S', str(socket), *args],
                                    input=input, capture_output=True, timeout=timeout)
        if timer.remaining() <= 0 or (self._phase_deadline is not None and self._phase_deadline.remaining() <= 0):
            raise WakeError('terminal_observation_deadline_reached')
        if result.returncode:
            raise WakeError('terminal_operation_unavailable')
        return result.stdout.decode('utf-8', errors='replace')

    def snapshot(self, binding):
        pid = binding['pid']
        proc = Path('/proc') / str(pid)
        if proc.stat().st_uid != os.getuid():
            raise WakeError('process_owner_changed')
        identity = process_identity(pid)
        argv = proc.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0')
        if (not identity or '--session-id' not in argv
                or argv[argv.index('--session-id')+1] != binding['session_id']
                or '--no-alt-screen' not in argv):
            raise WakeError('managed_launch_identity_unavailable')
        executable = proc.joinpath('exe').resolve(strict=True)
        if str(executable) != binding['executable']:
            raise WakeError('runtime_executable_changed')
        pane_pid = self._tmux(binding, 'display-message', '-p', '-t', binding['pane'], '#{pane_pid}').strip()
        if pane_pid != str(pid):
            raise WakeError('pane_process_changed')
        frame = self._tmux(binding, 'capture-pane', '-p', '-J', '-S', '-2000', '-t', binding['pane'])
        if process_identity(pid) != identity:
            raise WakeError('process_changed_during_observation')
        return dict(pid=pid, start_ticks=identity['start_time_ticks'], boot_id=identity['boot_id'],
                    session_id=binding['session_id'], executable_sha256=digest(executable.read_bytes()),
                    frame=frame)

    def load_binding(self, binding_id, expected_sha256=None):
        if not re.fullmatch(r'grok_[0-9a-f]{32}', binding_id):
            raise WakeError('invalid_binding_id')
        path = self.root / 'runtime-bindings' / (binding_id+'.json')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WakeError('untrusted_runtime_binding')
        data = path.read_bytes()
        if expected_sha256 is not None and digest(data) != expected_sha256:
            raise WakeError('runtime_binding_changed')
        binding = json.loads(data)
        if binding.get('version') != 1 or binding.get('allow_terminal_input') is not True:
            raise WakeError('terminal_input_not_authorized')
        return binding

    def enroll(self, *, socket, pane, pid, session_id, executable, allow_terminal_input, allow_terminal_fallback=False):
        if not allow_terminal_input:
            raise WakeError('explicit_terminal_input_approval_required')
        if not session_id or len(session_id) > 200 or any(ord(c)<32 for c in session_id):
            raise WakeError('invalid_session_id')
        binary = Path(executable).resolve(strict=True)
        version=subprocess.run([str(binary),'--version'],capture_output=True,text=True,timeout=3)
        if version.returncode or version.stdout.strip()!='grok 1.0.40 (eb1a2256660d) [stable]':
            raise WakeError('unqualified_grok_executable_version')
        binding = dict(version=1, runtime='grok', socket=str(Path(socket).absolute()), pane=pane,
                       pid=pid, session_id=session_id, executable=str(binary),
                       allow_terminal_input=True, allow_terminal_fallback=bool(allow_terminal_fallback))
        observed = self.snapshot(binding)
        binding.update({key:value for key,value in observed.items() if key != 'frame'})
        from .grok_runtime import GrokRuntimeAdapter
        from .runtime_delivery import RuntimeRecipient
        if GrokRuntimeAdapter(self).observe(RuntimeRecipient('grok', session_id, binding)).state != 'ready':
            raise WakeError('qualified_idle_binding_required')
        binding_id = 'grok_'+uuid4().hex
        directory = self.root/'runtime-bindings'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory/(binding_id+'.json')
        data = (json.dumps(binding, sort_keys=True)+'\n').encode()
        descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return dict(binding_id=binding_id, session_id=session_id, binding_sha256=digest(data),
                    method='native_preferred' if allow_terminal_fallback else 'terminal_observation',
                    receiver_acknowledgment='not_qualified')

    def refresh_identity(self,binding):
        phase=measurements.deadline(5)
        previous_phase=self._phase_deadline
        self._phase_deadline=phase
        try:
            if self.deadline is not None and self.deadline.remaining() <= 0:
                raise WakeError('original_deadline_reached')
            previous=self.snapshot(binding)['frame'].count('  Session ID: ')
            self._tmux(binding,'send-keys','-l','-t',binding['pane'],'/session-info')
            self._tmux(binding,'send-keys','-t',binding['pane'],'Enter')
            while min(phase.remaining(), self.deadline.remaining() if self.deadline is not None else 5)>0:
                observed=self.snapshot(binding)
                if observed['frame'].count('  Session ID: ')>previous:
                    return
                time.sleep(.05)
            raise WakeError('fresh_session_info_unavailable')
        finally:
            self._phase_deadline=previous_phase

    def paste(self, binding, prompt, *, deadline=None):
        # Literal stdin buffer + bracketed paste. No shell, prompt interpolation,
        # pre-clearing input, session-info command or fallback recipient.
        def check_window(seconds):
            if deadline is None or not callable(getattr(deadline, 'remaining', None)):
                raise measurements.TimeUnavailable('retained_deadline_required')
            if deadline.remaining() <= seconds:
                raise WakeError('original_deadline_reached')
        check_window(12)
        buffer = 'wake-'+uuid4().hex
        self._tmux(binding, 'load-buffer', '-b', buffer, '-', input=prompt.encode())
        try:
            check_window(8)
            self._tmux(binding, 'paste-buffer', '-p', '-d', '-b', buffer, '-t', binding['pane'])
            check_window(4)
            self._tmux(binding, 'send-keys', '-t', binding['pane'], 'Enter')
        finally:
            try:
                self._tmux(binding, 'delete-buffer', '-b', buffer)
            except Exception:
                pass
