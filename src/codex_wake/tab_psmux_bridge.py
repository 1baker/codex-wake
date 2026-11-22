"""Finite Windows psmux bridge for a WSL-owned Wake controller.

The host fixes the executable, namespace, session and server birth in its bridge
command. Requests contain finite presentation actions and new-launch directories. This
module is stdlib-only so the same installed artifact runs under native Windows
Python without creating a second Wake execution owner.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4


# Immutable standalone vocabulary: the validator and reader/writer must expose
# exactly the same finite options without importing Linux controller owners.
FORMATTING_WINDOW_OPTIONS=('window-status-format','window-status-current-format',
                           'window-status-style','window-status-current-style')
FORMATTING_SESSION_OPTIONS=('status-interval','@wake-format-clock')


class BridgeError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def process_birth(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise BridgeError('attachment_unavailable', 'native presentation process is unavailable')
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times]):
            raise BridgeError('attachment_unavailable', 'native process generation is unavailable')
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def process_image(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        value = ctypes.create_unicode_buffer(size.value)
        return value.value if kernel.QueryFullProcessImageNameW(handle, 0, value, ctypes.byref(size)) else None
    finally:
        kernel.CloseHandle(handle)


def pane_processes(roots):
    """One bounded native snapshot, returning only selected pane descendants.

    No command-line/private environment reads and no PowerShell/WMI process loop.
    Image identity can classify a harness; it cannot attest its conversation,
    turn activity, stock/modded registration or exact TUI-loop health.
    """
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ('Process32FirstW', 'Process32NextW'):
        getattr(kernel, name).argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        getattr(kernel, name).restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return {}, False
    deadline = time.monotonic() + .5
    children, parents, count, complete = {}, {}, 0, True
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while found:
            count += 1
            if count > 4096 or time.monotonic() >= deadline:
                complete = False
                break
            pid, parent = int(entry.th32ProcessID), int(entry.th32ParentProcessID)
            children.setdefault(parent, []).append(pid)
            parents[pid] = parent
            found = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    result = {}
    for root in roots:
        pending, seen, rows = [root], set(), []
        while pending:
            pid = pending.pop(0)
            if pid in seen:
                continue
            if len(seen) >= 256 or time.monotonic() >= deadline:
                complete = False
                break
            seen.add(pid)
            try:
                birth = process_birth(pid)
                image = process_image(pid)
                if process_birth(pid) != birth:
                    complete = False
                    continue
                rows.append(dict(pid=pid, parent_pid=parents.get(pid), creation_filetime=birth,
                                 executable=image, platform='windows'))
            except BridgeError:
                complete = False
            pending.extend(children.get(pid, []))
        result[root] = rows
    return result, complete


def current_sid():
    """Current native Windows owner, without a child process or token output."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise BridgeError('unauthorized_target', 'native manifest owner cannot be verified')
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 0 < size.value <= 65536:
            raise BridgeError('unauthorized_target', 'native owner token exceeds bound')
        value = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, value, size, ctypes.byref(size)):
            raise BridgeError('unauthorized_target', 'native owner token is unavailable')
        return _sid_string(ctypes.cast(value, ctypes.POINTER(ctypes.c_void_p))[0])
    finally:
        kernel.CloseHandle(token)


def _sid_string(sid):
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    output = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(output)):
        raise BridgeError('unauthorized_target', 'native manifest SID is invalid')
    try:
        return output.value
    finally:
        kernel.LocalFree(ctypes.cast(output, ctypes.c_void_p))


def check_private_manifest(path):
    """Current-owner private DACL, with bounded direct Win32 ACL inspection.

    Same owner/SYSTEM/Administrators exception as the portable caller contract;
    no PowerShell startup/census can outlive a bridge timeout.
    """
    class ACL(ctypes.Structure):
        _fields_ = [('revision', ctypes.c_ubyte), ('unused', ctypes.c_ubyte),
                    ('size', wintypes.WORD), ('count', wintypes.WORD), ('unused2', wintypes.WORD)]
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    if advapi.GetNamedSecurityInfoW(str(path), 1, 5, ctypes.byref(owner), None,
            ctypes.byref(dacl), None, ctypes.byref(descriptor)):
        raise BridgeError('unauthorized_target', 'native manifest security descriptor is unavailable')
    try:
        current = current_sid()
        if not dacl.value or _sid_string(owner.value) != current:
            raise BridgeError('unauthorized_target', 'native manifest must have current owner and a private DACL')
        count = ctypes.cast(dacl, ctypes.POINTER(ACL)).contents.count
        if count > 256:
            raise BridgeError('unauthorized_target', 'native manifest ACL exceeds bound')
        allowed = {current, 'S-1-5-18', 'S-1-5-32-544'}
        sensitive = 0xD00F0007
        for index in range(count):
            ace = ctypes.c_void_p()
            if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
                raise BridgeError('unauthorized_target', 'native manifest ACE is unavailable')
            kind = ctypes.c_ubyte.from_address(ace.value).value
            if kind in (1, 6, 10, 12):
                continue  # deny ACEs cannot grant another principal access
            if kind != 0:
                raise BridgeError('unauthorized_target', 'native manifest ACL contains unsupported grant semantics')
            mask = wintypes.DWORD.from_address(ace.value + 4).value
            if mask & sensitive and _sid_string(ace.value + 8) not in allowed:
                raise BridgeError('unauthorized_target', 'native manifest grants another principal sensitive access')
    finally:
        kernel.LocalFree(descriptor)


class PsmuxHost:
    ACTIONS = {'snapshot', 'discover', 'capture', 'visible_screen', 'paste', 'keys', 'swap', 'lifecycle', 'attach_saved', 'formatting', 'formatting_batch', 'session_rename'}

    def __init__(self, *, namespace, session, server_pid=None, server_birth=None, attach_directory=None):
        if os.name != 'nt':
            raise BridgeError('unsupported_target', 'this presentation bridge requires native Windows Python')
        if not isinstance(namespace, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', namespace):
            raise BridgeError('invalid_argument', 'host must configure a bounded exact namespace')
        self.namespace = namespace
        self.session = self._text(session, 'session')
        self.binary = Path(os.environ['LOCALAPPDATA']) / 'Microsoft/WinGet/Links/psmux.exe'
        self.server_pid, self.server_birth = server_pid, server_birth
        self.attach_directory = Path(attach_directory).resolve() if attach_directory else None
        self.identity = self.describe()
        if self.attach_directory is not None:
            self.identity['attach_directory'] = str(self.attach_directory)
        if server_pid is not None and (self.identity['pid'] != server_pid or self.identity['creation_filetime'] != server_birth):
            raise BridgeError('stale_target', 'psmux server generation changed')
        self.generation = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _text(value, field):
        if not isinstance(value, str) or not value or len(value.encode()) > 256 or any(ord(c) < 32 for c in value):
            raise BridgeError('invalid_argument', field + ' must be bounded single-line text')
        return value

    def command(self, *argv, timeout=4, input_text=None):
        try:
            reply = subprocess.run([str(self.binary), '-L', self.namespace, *argv],
                text=True, encoding='utf-8', input=input_text, capture_output=True, timeout=timeout, check=True)
        except (OSError, subprocess.SubprocessError):
            raise BridgeError('attachment_unavailable', 'native psmux command failed; reconcile effects before retry') from None
        if len(reply.stdout.encode()) > 1048576:
            raise BridgeError('capacity', 'native presentation exceeds bounded output')
        return reply.stdout

    def describe(self):
        pid = int(self.command('display-message', '-p', '-t', self.session + ':', '#{pid}').strip())
        return dict(platform='windows', namespace=self.namespace, pid=pid,
                    session=self.session, creation_filetime=process_birth(pid),
                    executable_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest())

    def _current(self):
        if process_birth(self.identity['pid']) != self.identity['creation_filetime']:
            raise BridgeError('stale_target', 'native psmux process generation changed')
        pid = int(self.command('display-message', '-p', '-t', self.session + ':', '#{pid}').strip())
        if pid != self.identity['pid']:
            raise BridgeError('stale_target', 'native psmux server was replaced')

    def _rows(self):
        fields = ('session_id', 'session_name', 'window_id', 'window_index', 'window_name',
                  'window_active', 'pane_id', 'pane_index', 'pane_pid', 'pane_current_path')
        output = self.command('list-panes', '-a', '-F', '\t'.join('#{' + field + '}' for field in fields))
        lines = output.splitlines()
        if len(lines) > 4096:
            raise BridgeError('capacity', 'native pane inventory exceeds bound')
        rows = []
        for line in lines:
            values = line.split('\t')
            if len(values) != len(fields):
                raise BridgeError('attachment_unavailable', 'ambiguous native presentation metadata')
            row = dict(zip(fields, values))
            if not re.fullmatch(r'@[0-9]+', row['window_id']) or not re.fullmatch(r'%[0-9]+', row['pane_id']):
                raise BridgeError('attachment_unavailable', 'invalid native presentation identities')
            rows.append(row)
        return rows

    def _snapshot(self, rows, session=None):
        session = session or self.session
        selected = [row for row in rows if session in (row['session_id'], row['session_name'])]
        identities = {row['session_id'] for row in selected}
        if len(identities) != 1:
            raise BridgeError('attachment_unavailable', 'exact psmux session is unavailable or ambiguous')
        native_processes, complete = pane_processes({int(row['pane_pid']) for row in selected})
        indices_by_window = {}
        for row in selected:
            indices_by_window.setdefault(row['window_id'], set()).add(int(row['window_index']))
        windows = {}
        panes_by_window = {}
        for row in selected:
            native_window = row['window_id']
            indices = indices_by_window[native_window]
            window = windows.setdefault(native_window, dict(window_id=native_window, index=int(row['window_index']),
                name=row['window_name'], focused=False, linked=len(indices) > 1, panes=[]))
            window['focused'] |= row['window_active'] == '1'
            if window['linked']:
                window['linked_sessions'] = [row['session_id']]
                window['linked_appearances'] = [dict(session_id=row['session_id'], index=index)
                                                for index in sorted(indices)]
            pane = row['pane_id']
            seen = panes_by_window.setdefault(native_window, set())
            if pane in seen:
                continue
            seen.add(pane)
            pid = int(row['pane_pid'])
            window['panes'].append(dict(pane_id=row['pane_id'], pane_index=int(row['pane_index']), pid=pid, platform='windows',
                windows_creation_filetime=process_birth(pid), windows_executable=process_image(pid), cwd=row['pane_current_path'],
                windows_processes=native_processes.get(pid, []), windows_processes_complete=complete))
        if self.attach_directory is not None:
            for window in windows.values():
                receipt_path = self._window_receipt(window['window_id'])
                if not receipt_path.exists():
                    continue
                try:
                    check_private_manifest(receipt_path)
                    if receipt_path.is_symlink() or receipt_path.stat().st_size > 4096:
                        continue
                    receipt = json.loads(receipt_path.read_text())
                    pane = window['panes'][0] if len(window['panes']) == 1 else None
                    if (pane and receipt.get('bridge_generation') == self.generation
                            and receipt.get('window_id') == window['window_id']
                            and receipt.get('pane_id') == pane['pane_id']
                            and receipt.get('windows_pid') == pane['pid']
                            and receipt.get('windows_creation_filetime') == pane['windows_creation_filetime']):
                        window['attach_intent'] = receipt['intent']
                except (BridgeError, OSError, ValueError, KeyError):
                    pass  # Unknown relay evidence must not become a false binding.
        return dict(server=str(self.identity['pid']), session_id=next(iter(identities)), session_name=selected[0]['session_name'],
                    socket_identity=[self.identity['pid'], self.identity['creation_filetime']],
                    windows=sorted(windows.values(), key=lambda w: w['index']),
                    server_identity=self.identity, windows_server=self.identity)

    def _window_receipt(self, window):
        scope = hashlib.sha256(json.dumps([self.identity['pid'], self.identity['creation_filetime'], self.session]).encode()).hexdigest()[:16]
        return self.attach_directory / ('window_' + scope + '_' + window[1:] + '.json')

    def execute(self, request):
        if not isinstance(request, dict) or set(request) != {'action', 'arguments'}:
            raise BridgeError('invalid_argument', 'finite action and arguments required')
        action, args = request['action'], request['arguments']
        if action not in self.ACTIONS or not isinstance(args, dict):
            raise BridgeError('unsupported_operation', 'unsupported finite presentation operation')
        self._current()
        rows = self._rows()
        if action == 'discover':
            if args:
                raise BridgeError('invalid_argument', 'discovery accepts no arguments')
            sessions = {row['session_id']: row['session_name'] for row in rows}
            result = dict(sessions=[dict(session_id=k, name=v) for k, v in sorted(sessions.items())],
                          server_identity=self.identity, capabilities=sorted(self.ACTIONS))
        else:
            snapshot = self._snapshot(rows)
            windows = {w['window_id']: w for w in snapshot['windows']}
            panes = {p['pane_id'] for w in windows.values() for p in w['panes']}
            if action == 'snapshot':
                if args:
                    raise BridgeError('invalid_argument', 'snapshot accepts no arguments')
                result = snapshot
            elif action in ('capture', 'visible_screen'):
                allowed = {'pane', 'lines'} if action == 'capture' else {'pane'}
                if set(args) != allowed or args.get('pane') not in panes:
                    raise BridgeError('stale_target', 'exact current pane is required')
                command = ['capture-pane', '-p', '-t', args['pane']]
                if action == 'capture':
                    lines = args['lines']
                    if type(lines) is not int or not 1 <= lines <= 200:
                        raise BridgeError('invalid_argument', 'capture supports 1 through 200 lines')
                    command += ['-S', '-' + str(lines)]
                result = self.command(*command)[-32768:]
            elif action in ('paste', 'keys'):
                field = 'text' if action == 'paste' else 'keys'
                pane = args.get('pane')
                if set(args) != {'pane', field} or not isinstance(pane, str) or pane not in panes:
                    raise BridgeError('stale_target', 'exact current pane is required')
                value = args[field]
                if action == 'paste':
                    if (not isinstance(value, str) or not value or len(value.encode()) > 16384
                            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)):
                        raise BridgeError('invalid_argument', 'bounded literal text without control characters required')
                    buffer = 'wake-paste-' + uuid4().hex
                    try:
                        self.command('load-buffer', '-b', buffer, '-', input_text=value)
                        self._current()
                        self.command('paste-buffer', '-r', '-d', '-b', buffer, '-t', pane)
                    finally:
                        try:
                            self.command('delete-buffer', '-b', buffer)
                        except BridgeError:
                            pass
                else:
                    if (not isinstance(value, list) or not 1 <= len(value) <= 32 or any(
                            not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,31}', key)
                            for key in value)):
                        raise BridgeError('invalid_argument', 'bounded named terminal keys required')
                    self.command('send-keys', '-t', pane, '--', *value)
                result = {'delivery': 'sent', 'semantic_execution': 'unknown'}
            elif action == 'swap':
                if set(args) != {'first', 'second'} or args.get('first') not in windows or args.get('second') not in windows:
                    raise BridgeError('stale_target', 'exact current windows required')
                focused = next(w['window_id'] for w in windows.values() if w['focused'])
                self.command('swap-window', '-d', '-s', self.session + ':' + args['first'], '-t', self.session + ':' + args['second'])
                self.command('select-window', '-t', self.session + ':' + focused)
                result = {}
            elif action == 'formatting':
                result = self._formatting(args, snapshot)
            elif action == 'formatting_batch':
                requests=args.get('requests')
                if set(args)!={'requests'} or not isinstance(requests,list) or not 1<=len(requests)<=256:
                    raise BridgeError('invalid_argument','Formatting batch requires 1 through 256 typed requests')
                for item in requests:self._formatting_validate(item,snapshot)
                result=[]
                for item in requests:
                    try:result.append(self._formatting(item,snapshot))
                    except BridgeError as error:result.append(dict(error=dict(code=error.code,message=str(error))))
            elif action == 'session_rename':
                if set(args)!={'name'}:raise BridgeError('invalid_argument','Exact new session name required')
                name=self._text(args['name'],'name')
                if any(c in name for c in ':.'):raise BridgeError('invalid_argument','Exact session name required')
                self.command('rename-session','-t',self.session,name)
                self.session=name
                result=dict(name=name)
            elif action == 'attach_saved':
                result = self._attach_saved(args, snapshot)
            else:
                result = self._lifecycle(args, snapshot, rows)
        if not (action == 'lifecycle' and args.get('action') == 'close'
                and result.get('workspace_state') == 'removed'):
            self._current()
        return dict(generation=self.generation, result=result)

    def _formatting_validate(self,args,snapshot):
        if not isinstance(args,dict):raise BridgeError('invalid_argument','Typed formatting request required')
        action=args.get('action')
        allowed={'read':{'action','window'},'write':{'action','window','values'},
                 'read-session':{'action'},'write-session':{'action','values'},'refresh':{'action'}}
        if action not in allowed or set(args)!=allowed[action]:
            raise BridgeError('invalid_argument','Unsupported finite formatting arguments')
        session=action.endswith('-session')
        if action!='refresh' and not session and args.get('window') not in {w['window_id'] for w in snapshot['windows']}:
            raise BridgeError('stale_target','Exact current window required')
        options=FORMATTING_SESSION_OPTIONS if session else FORMATTING_WINDOW_OPTIONS
        if action.startswith('write'):
            values=args['values']
            if (not isinstance(values,dict) or set(values)-set(options)
                    or any(v is not None and (not isinstance(v,str) or len(v)>8192 or
                               any(ord(c)<32 and c not in '\t' for c in v)) for v in values.values())):
                raise BridgeError('invalid_argument','Only bounded managed formatting option values are accepted')
            if 'status-interval' in values and values['status-interval'] is not None:
                interval=values['status-interval']
                if not interval.isdecimal() or not 0<=int(interval)<=3600:
                    raise BridgeError('invalid_argument','Status interval must be 0 through 3600 seconds')

    def _formatting(self, args, snapshot):
        """Finite read/write/unset/readback protocol for managed display options.

        psmux single-option reads return inherited values even without -A.
        Full local-window listings identify which built-ins are actually set.
        Session options live in this pinned session server's own option store.
        """
        self._formatting_validate(args,snapshot)
        action=args['action']
        if action=='refresh':
            self.command('refresh-client','-S')
            return dict(status='refreshed')
        session=action.endswith('-session')
        options=FORMATTING_SESSION_OPTIONS if session else FORMATTING_WINDOW_OPTIONS
        if session:
            flags=[];target=self.session
        else:
            windows={w['window_id']:w for w in snapshot['windows']}
            window=args.get('window')
            if not isinstance(window,str) or window not in windows:
                raise BridgeError('stale_target','Exact current window required')
            flags=['-w'];target=self.session+':'+window
        if action.startswith('write'):
            values=args['values']
            for name,value in values.items():
                if value is None:self.command('set-option',*flags,'-u','-t',target,name)
                else:self.command('set-option',*flags,'-t',target,name,value)
        if not session:
            return self._window_format_options(target)
        raw=self.command('show-options',*flags,'-t',target)
        explicit={line.split(' ',1)[0] for line in raw.splitlines() if line and not line[0].isspace()}
        result={}
        for name in options:
            # Absent user options must not be queried: psmux may reject them.
            effective=self.command('show-options',*flags,'-v','-t',target,name).removesuffix('\n') if name in explicit or not name.startswith('@') else ''
            result[name]=dict(explicit=name in explicit,value=effective if name in explicit else None,effective=effective)
        return result

    def _window_format_options(self, target):
        # Queue only fixed read requests. Framing preserves native whitespace
        # and multiline option values without parsing them as option records.
        separator = 'wake-format-' + uuid4().hex
        argv = ['show-options', '-w', '-t', target]
        for name in FORMATTING_WINDOW_OPTIONS:
            for scope in ((), ('-g',)):
                argv.extend((';', 'display-message', '-p', '-t', target, separator,
                             ';', 'show-options', *scope, '-w', '-v', '-t', target, name))
        parts = self.command(*argv).split(separator + '\n')
        if len(parts) != 1 + len(FORMATTING_WINDOW_OPTIONS) * 2:
            raise BridgeError('formatting_mismatch', 'Native window option readback was incomplete')
        explicit = {line.split(' ', 1)[0] for line in parts[0].splitlines()
                    if line and not line[0].isspace()}
        result = {}
        for index, name in enumerate(FORMATTING_WINDOW_OPTIONS):
            effective, parent = (part.removesuffix('\n') for part in parts[1+2*index:3+2*index])
            result[name] = dict(explicit=name in explicit, value=effective if name in explicit else None,
                                effective=effective, parent=parent)
        return result

    def _attach_saved(self, args, snapshot):
        if self.attach_directory is None:
            raise BridgeError('unsupported_target', 'host has not configured exact saved-conversation attachment')
        if (set(args) != {'intent', 'manifest_sha256'} or not isinstance(args['intent'], str)
                or not re.fullmatch(r'[0-9a-f]{32}', args['intent'])
                or not isinstance(args['manifest_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', args['manifest_sha256'])):
            raise BridgeError('invalid_argument', 'opaque host launch intent and exact manifest digest required')
        path = self.attach_directory / (args['intent'] + '.json')
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise BridgeError('unauthorized_target', 'bounded regular host launch manifest required')
        check_private_manifest(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != args['manifest_sha256']:
            raise BridgeError('stale_target', 'host launch manifest changed')
        manifest = json.loads(raw)
        fields = {'version','intent','identity','profile','marker','wsl_manifest','window_name','execution_user','windows_destination'}
        if (set(manifest) != fields or manifest['version'] != 1 or manifest['intent'] != args['intent']
                or manifest['windows_destination'] != self.generation):
            raise BridgeError('stale_target', 'host launch intent/destination mismatch')
        profile = manifest['profile']
        if any(k in profile for k in ('argv','shell','command','environment')):
            raise BridgeError('unauthorized_target', 'launch profiles cannot supply arbitrary commands')
        for value in ('wake_python','wsl_distribution','codex_home','codex_path','app_server'):
            self._text(profile.get(value), value)
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+', profile['wsl_distribution'])
                or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,63}', manifest['execution_user'])
                or not profile['wake_python'].startswith('/') or not manifest['wsl_manifest'].startswith('/')):
            raise BridgeError('unauthorized_target', 'host must select an exact WSL owner/profile')
        name = self._text(manifest['window_name'], 'window name')
        if any(w['name'] == name for w in snapshot['windows']):
            raise BridgeError('uncertain_effect', 'intent attachment already exists; reconcile without creating another')
        wsl = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/wsl.exe'
        window = self.command('new-window','-d','-P','-F','#{window_id}',
            '-t',self.session+':','-n',name,'--',str(wsl),'--distribution',profile['wsl_distribution'],
            '--user',manifest['execution_user'],'--exec',profile['wake_python'],'-m','codex_wake.tab_reattach',
            '--launch-child',manifest['wsl_manifest'],'--manifest-sha',args['manifest_sha256'],timeout=10).strip()
        after = self._snapshot(self._rows())
        created = next((w for w in after['windows'] if w['window_id'] == window), None)
        if created is None or len(created['panes']) != 1:
            raise BridgeError('effect_uncertain', 'saved-conversation window creation is not verified')
        pane = created['panes'][0]
        result = dict(window_id=window,pane_id=pane['pane_id'],windows_pid=pane['pid'],
                      windows_creation_filetime=pane['windows_creation_filetime'],bridge_generation=self.generation)
        self._window_receipt(window).write_text(json.dumps(dict(intent=args['intent'], **result)))
        return result

    @staticmethod
    def _relative_placement(args, windows, moving):
        position = args.get('position')
        anchor = args.get('anchor')
        if position is None and anchor is None:
            return None
        if position not in ('first', 'last', 'before', 'after'):
            raise BridgeError('invalid_argument', 'valid relative placement is required')
        remaining = sorted((window for window in windows.values() if window['window_id'] != moving),
                           key=lambda window: window['index'])
        if position in ('before', 'after'):
            if anchor == moving and moving is not None:
                raise BridgeError('invalid_argument', 'a tab cannot anchor its own move')
            if not isinstance(anchor, str) or anchor not in windows:
                raise BridgeError('stale_target', 'exact current anchor tab is required')
            target = windows[anchor]
        else:
            if anchor is not None:
                raise BridgeError('invalid_argument', 'first and last do not take an anchor')
            if not remaining:
                return None
            target = remaining[0] if position == 'first' else remaining[-1]
        after = position in ('last', 'after')
        if moving is not None:
            expected = remaining.copy()
            expected.insert(remaining.index(target) + int(after), windows[moving])
            if expected == sorted(windows.values(), key=lambda window: window['index']):
                return None
        return ('-a' if after else '-b', target['window_id'])

    def _lifecycle(self, args, snapshot, rows):
        allowed = {
            'create': {'name', 'cwd', 'position', 'anchor'}, 'rename': {'window', 'name'}, 'focus': {'window'}, 'close': {'window'},
            'move': {'window', 'destination_session', 'index', 'position', 'anchor'}, 'park': {'window', 'destination_session', 'index'},
            'restore': {'window', 'destination_session', 'index'},
        }
        action = args.get('action')
        if action not in allowed or set(args) - allowed[action] - {'action'}:
            raise BridgeError('unsupported_operation', 'unsupported finite lifecycle operation')
        windows = {w['window_id']: w for w in snapshot['windows']}
        wid = args.get('window')
        if action != 'create' and wid not in windows:
            raise BridgeError('stale_target', 'exact current source window is required')
        relative = None
        destination = snapshot['session_id']
        if action in ('create', 'rename'):
            name = self._text(args.get('name'), 'name')
            if any(w['name'] == name and w['window_id'] != wid for w in windows.values()):
                raise BridgeError('name_conflict', 'destination already has that tab name')
        if action == 'create':
            relative = self._relative_placement(args, windows, None)
            flags = [relative[0], '-t', self.session + ':' + str(relative[1])] if relative else ['-t', destination + ':']
            command = ['new-window', '-d', '-P', '-F', '#{window_id}', *flags, '-n', name]
            wid = self.command(*command, *_launch_arguments(args)).strip()
        elif action == 'move' and 'position' in args and 'destination_session' not in args:
            relative = self._relative_placement(args, windows, wid)
            if relative:
                self.command('move-window', '-d', relative[0], '-s', self.session + ':' + wid,
                             '-t', self.session + ':' + str(relative[1]))
        elif action == 'rename':
            self.command('rename-window', '-t', self.session + ':' + wid, name)
        elif action == 'focus':
            self.command('select-window', '-t', self.session + ':' + wid)
        elif action == 'close':
            self.command('kill-window', '-t', self.session + ':' + wid)
        else:
            destination = args.get('destination_session')
            target = self._snapshot(rows, destination)
            if target['session_id'] == snapshot['session_id']:
                raise BridgeError('invalid_argument', 'destination must differ from source')
            # Native psmux sessions have separate servers and repeat @/% IDs.
            # join-pane would be a different operation and must not be substituted.
            raise BridgeError('unsupported_target', 'psmux whole-window cross-session movement is unsupported; source preserved')
        after_rows = self._rows()
        present = any(row['session_id'] == destination for row in after_rows)
        after = self._snapshot(after_rows, destination) if present else None
        if action == 'close':
            if any(row['session_id'] == snapshot['session_id'] and row['window_id'] == wid for row in after_rows):
                raise BridgeError('effect_uncertain', 'closed tab remains visible')
        elif after is None or not any(w['window_id'] == wid for w in after['windows']):
            raise BridgeError('effect_uncertain', 'destination attachment was not observed')
        if relative:
            previous_order = [row['window_id'] for row in sorted(windows.values(), key=lambda row: row['index'])]
            expected = [window for window in previous_order if window != wid]
            expected.insert(expected.index(relative[1]) + int(relative[0] == '-a'), wid)
            actual = sorted(after['windows'], key=lambda row: row['index'])
            def pane_births(window):
                return [(pane['pane_id'], pane.get('pid'), pane.get('windows_creation_filetime'))
                        for pane in window['panes']]
            if ([row['window_id'] for row in actual] != expected
                    or {row['window_id'] for row in actual if row['focused']}
                       != {row['window_id'] for row in windows.values() if row['focused']}
                    or any(pane_births(row) != pane_births(windows[row['window_id']])
                           for row in actual if row['window_id'] in windows)):
                raise BridgeError('effect_uncertain', 'native placement, pane identity, or focus did not match readback')
        return dict(window_id=wid, workspace_state='present' if present else 'removed', snapshot=after)


def _launch_arguments(args):
    """Validate new-launch fields on Windows; never interpret a shell script."""
    result=[]
    cwd=args.get('cwd',os.environ['USERPROFILE'])
    if not isinstance(cwd,str) or not 0<len(cwd)<=4096 or any(ord(c)<32 for c in cwd) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise BridgeError('invalid_argument','native working directory must exist and be absolute')
    result+=['-c',cwd]
    return result+['--','cmd.exe','/d','/k']


def session_management(namespace, session, request):
    """Finite bootstrap actions for a host-selected namespace, without a live pin."""
    if os.name != 'nt' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',namespace):
        raise BridgeError('unsupported_target','Native Windows and exact host namespace required')
    PsmuxHost._text(session,'session')
    if any(c in session for c in ':.'):
        raise BridgeError('invalid_argument','Exact session name required')
    if not isinstance(request,dict) or set(request)!={'action','arguments'}:
        raise BridgeError('invalid_argument','Finite session request required')
    action,args=request['action'],request['arguments']
    if action not in ('session_probe','session_create') or not isinstance(args,dict) or set(args)-{'cwd'} or (action=='session_probe' and args):
        raise BridgeError('unsupported_operation','Unsupported finite session action')
    binary=Path(os.environ['LOCALAPPDATA'])/'Microsoft/WinGet/Links/psmux.exe'
    probe=subprocess.run([str(binary),'-L',namespace,'has-session','-t',session],capture_output=True,text=True,timeout=4)
    if probe.returncode not in (0,1):
        raise BridgeError('attachment_unavailable','Native session presence is unknown')
    if action=='session_probe':return dict(result=dict(present=probe.returncode==0))
    if probe.returncode==0:raise BridgeError('name_conflict','Native session already exists; reconcile before creating')
    launch=_launch_arguments(args)
    reply=subprocess.run([str(binary),'-L',namespace,'new-session','-d','-s',session,*launch],capture_output=True,text=True,timeout=8)
    if reply.returncode:raise BridgeError('uncertain_effect','Native session creation failed; reconcile before retry')
    host=PsmuxHost(namespace=namespace,session=session)
    return dict(result=dict(identity=host.identity,generation=host.generation))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--server-pid', type=int)
    parser.add_argument('--server-birth', type=int)
    parser.add_argument('--describe', action='store_true')
    parser.add_argument('--session-management', action='store_true')
    parser.add_argument('--attach-directory')
    args = parser.parse_args(argv)
    host = None
    try:
        if args.session_management:
            raw=sys.stdin.buffer.read(65537)
            if len(raw)>65536:raise BridgeError('capacity','Finite bridge input exceeds bound')
            print(json.dumps(session_management(args.namespace,args.session,json.loads(raw))))
            return 0
        host = PsmuxHost(namespace=args.namespace, session=args.session,
                         server_pid=args.server_pid, server_birth=args.server_birth, attach_directory=args.attach_directory)
        if args.describe:
            value = dict(generation=host.generation, identity=host.identity,
                         capabilities=sorted(host.ACTIONS))
        else:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise BridgeError('capacity', 'finite bridge input exceeds bound')
            value = host.execute(json.loads(raw))
        print(json.dumps(value))
        return 0
    except (BridgeError, ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps(dict(generation=host.generation if host else None,
            error=dict(code=getattr(error, 'code', 'attachment_unavailable'), message=str(error)))))
        return 0 if host else 2


if __name__ == '__main__':
    raise SystemExit(main())
