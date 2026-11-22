"""Conditional, journaled permutations of one qualified tmux workspace.

The observer is a private host seam, never evidence supplied by tool arguments.
No terminal input or native turn is submitted by this module.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid

from .records import WakeError
from .tab_identity import stable_snapshot


class TabError(WakeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class TmuxTransport:
    def __init__(self, socket_path, session_id):
        path = Path(socket_path)
        info = path.lstat()
        if (not path.is_absolute() or path != path.resolve() or not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != os.geteuid() or not re.fullmatch(r'\$[0-9]+', session_id)):
            raise TabError('workspace_unqualified', 'exact user-owned socket and session ID required')
        self.socket, self.session = str(path), session_id
        self.socket_identity = [info.st_dev, info.st_ino]

    def command(self, deadline, *args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TabError('workspace_timeout', 'operation deadline exhausted')
        info = Path(self.socket).lstat()
        if [info.st_dev, info.st_ino] != self.socket_identity:
            raise TabError('workspace_changed', 'tmux socket generation changed')
        result = subprocess.run(['tmux', '-S', self.socket, *args], capture_output=True,
                                text=True, timeout=remaining, check=True)
        if len(result.stdout) > 1048576:
            raise TabError('workspace_unavailable', 'inventory exceeds bounded output')
        return result.stdout

    def snapshot(self, deadline):
        fields = ('session_id', 'window_id', 'window_index', 'window_name', 'window_active',
                  'pane_id', 'pane_pid', 'pane_current_path', 'pane_title', 'pane_tty', 'pane_current_command')
        raw = self.command(deadline, 'list-panes', '-a', '-F', '\t'.join('#{' + x + '}' for x in fields))
        lines = raw.splitlines()
        if len(lines) > 4096:
            raise TabError('workspace_unavailable', 'inventory exceeds 4096 panes')
        all_rows = []
        for line in lines:
            values = line.split('\t')
            if len(values) != len(fields):
                raise TabError('workspace_unavailable', 'ambiguous inventory metadata')
            all_rows.append(dict(zip(fields, values)))
        rows = [r for r in all_rows if r['session_id'] == self.session]
        if not rows:
            raise TabError('workspace_unavailable', 'exact session unavailable')
        appearances_by_window = {}
        for row in all_rows:
            appearances_by_window.setdefault(row['window_id'], set()).add(
                (row['session_id'], int(row['window_index'])))
        windows = {}
        panes_by_window = {}
        for row in rows:
            wid = row['window_id']
            if not re.fullmatch(r'@[0-9]+', wid) or not re.fullmatch(r'%[0-9]+', row['pane_id']):
                raise TabError('workspace_unqualified', 'invalid native IDs')
            appearances = appearances_by_window[wid]
            window = windows.setdefault(wid, dict(window_id=wid, index=int(row['window_index']),
                name=row['window_name'], focused=False, linked=len(appearances) > 1, panes=[]))
            window['focused'] |= row['window_active'] == '1'
            if window['linked']:
                window['linked_sessions'] = sorted({session for session, _ in appearances})
                window['linked_appearances'] = [dict(session_id=session, index=index)
                                                for session, index in sorted(appearances)]
            pane = row['pane_id']
            seen = panes_by_window.setdefault(wid, set())
            if pane in seen:
                continue
            seen.add(pane)
            window['panes'].append(dict(pane_id=pane, pid=int(row['pane_pid']),
                pane_title=row['pane_title'],pane_current_path=row['pane_current_path'],pane_tty=row['pane_tty'],pane_current_command=row['pane_current_command']))
        self.focused = next(w['window_id'] for w in windows.values() if w['focused'])
        return dict(server=self.command(deadline, 'display-message', '-p', '#{pid}').strip(),
                    session_id=self.session, socket_identity=self.socket_identity,
                    windows=sorted(windows.values(), key=lambda w: w['index']))

    def swap(self, first, second, deadline):
        self.command(deadline, 'swap-window', '-d', '-s', first, '-t', second,
                     ';', 'select-window', '-t', self.session + ':' + self.focused)


class TabOrganization:
    def __init__(self, root, *, transport, observer=None, authorize=None, policy_revision=None):
        self.directory = Path(root) / 'tab-organization'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory != self.directory.resolve() or self.directory.stat().st_mode & 0o077:
            raise TabError('workspace_store_unavailable', 'canonical private store required')
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.geteuid():
            raise TabError('workspace_store_unavailable', 'private store required')
        self.transport, self.observer, self.authorize = transport, observer, authorize
        self.policy_revision = policy_revision or (lambda: 0)
        self.criteria = []

    @contextmanager
    def locked(self, deadline):
        path = self.directory / 'lock'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TabError('workspace_timeout', 'workspace lock unavailable')
                    time.sleep(min(.02, max(0, deadline-time.monotonic())))
            yield
        finally:
            os.close(fd)

    def save(self, key, value):
        temporary = self.directory / ('.' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.directory / (key + '.json'))
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def read(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'(plan|receipt)_[0-9a-f]{32}', key):
            raise TabError('workspace_invalid_argument', 'invalid record ID')
        path = self.directory / (key + '.json')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as source:
            value = source.read(1048577)
        if len(value) > 1048576:
            raise TabError('workspace_store_unavailable', 'record too large')
        record = json.loads(value)
        if type(record) is not dict or record.get('version') != 1:
            raise TabError('workspace_store_unavailable', 'unsupported record version')
        return record

    def snapshot(self, pins, deadline):
        result = self.transport.snapshot(deadline)
        result['permission_revision'] = self.policy_revision()
        evidence = self.observer(max(.001, deadline-time.monotonic())) if self.observer else {}
        from .process import process_identity
        for window in result['windows']:
            reasons, repos, states, observed_traits = [], [], [], []
            if window['focused']: reasons.append('focused')
            if window['linked']: reasons.append('linked')
            if window['window_id'] in pins: reasons.append('explicit')
            for pane in window['panes']:
                sample = evidence.get(pane['pane_id'])
                qualified = (isinstance(sample, dict) and sample.get('fresh') is True
                    and sample.get('conversation_id') and sample.get('namespace')
                    and sample.get('state') in ('working', 'ready', 'awaiting-human', 'auth-required', 'disconnected')
                    and isinstance(sample.get('process'), dict))
                if qualified:
                    process = sample['process']
                    # Managed client may be a descendant of pane_pid; the observer
                    # owns that relationship, while current generation is rechecked.
                    current = process_identity(process.get('pid')) if type(process.get('pid')) is int else None
                    qualified = bool(current and set(process) == {'pid', 'start_ticks', 'boot_id'}
                        and process['start_ticks'] == current.get('start_time_ticks')
                        and process['boot_id'] == current.get('boot_id'))
                if not qualified:
                    reasons.append('unqualified')
                    continue
                pane['binding'] = {k: sample[k] for k in ('conversation_id', 'namespace', 'process', 'root', 'state')}
                try:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0: raise TimeoutError()
                    common = subprocess.check_output(['git', '-C', sample['root'], 'rev-parse',
                        '--path-format=absolute', '--git-common-dir'], text=True, stderr=subprocess.DEVNULL,
                        timeout=remaining).strip()
                    common = Path(common).resolve(strict=True)
                    info = common.stat()
                    repo = dict(path=str(common), device=info.st_dev, inode=info.st_ino)
                    repos.append(repo)
                except (OSError, ValueError, subprocess.SubprocessError, TimeoutError):
                    if not self.criteria or 'repository' in self.criteria:
                        reasons.append('unqualified')
                states.append(sample['state'])
                observed_traits.append(sample.get('traits',{}))
            if len({digest(r) for r in repos}) > 1: reasons.append('mixed')
            if self.criteria:
                window['traits']={}
                for field in self.criteria:
                    values=[t.get(field,{}) for t in observed_traits]
                    qualified=bool(values) and all(v.get('status')=='observed' for v in values)
                    distinct={str(v.get('value','unknown')) for v in values}
                    window['traits'][field]=next(iter(distinct)) if qualified and len(distinct)==1 else 'unknown'
                    if window['traits'][field] in ('unknown','mixed'):
                        reasons.append('unqualified_traits')
            window['pins'] = sorted(set(reasons))
            window['repository'] = repos[0] if repos and len({digest(r) for r in repos}) == 1 else None
            window['activity'] = min(({'working': 0, 'awaiting-human': 1, 'auth-required': 2,
                                      'ready': 3, 'disconnected': 4}[s] for s in states), default=5)
        if time.monotonic() > deadline:
            raise TabError('workspace_timeout', 'observation exceeded deadline')
        return result

    def preview(self, *, mode='activity', pins=(), criteria=(), deadline):
        if mode not in ('activity','repository','traits') or not isinstance(pins, (list, tuple)) or any(
                not isinstance(p, str) or not re.fullmatch(r'@[0-9]+', p) for p in pins):
            raise TabError('workspace_invalid_argument', 'invalid ordering mode or pins')
        from .tab_views import FIELDS
        if not isinstance(criteria,(list,tuple)) or any(v not in FIELDS for v in criteria) or (mode=='traits' and not criteria):
            raise TabError('workspace_invalid_argument','Trait ordering requires supported criteria.')
        self.criteria=list(criteria) if mode=='traits' else []
        with self.locked(deadline):
            before = self.snapshot(pins, deadline)
            if set(pins) - {w['window_id'] for w in before['windows']}:
                raise TabError('workspace_invalid_argument', 'pin is outside exact workspace')
            movable = [w for w in before['windows'] if not w['pins']]
            def key(w):
                if mode=='traits':return tuple(w['traits'][v] for v in self.criteria)+(w['index'],)
                repo = w['repository']['path']
                return (w['activity'], repo, w['index']) if mode == 'activity' else (repo, w['activity'], w['index'])
            ordered = iter(sorted(movable, key=key))
            target = []
            for window in before['windows']:
                selected = window if window['pins'] else next(ordered)
                target.append(dict(window_id=selected['window_id'], index=window['index'], name=selected['name']))
            plan = dict(version=1, plan_id='plan_' + uuid.uuid4().hex, before=before,
                        fingerprint=digest(before), pins=list(pins), mode=mode, criteria=self.criteria, target=target)
            self.save(plan['plan_id'], plan)
            return dict(status='preview', plan=plan)

    def apply(self, plan_id, *, deadline):
        with self.locked(deadline):
            plan = self.read(plan_id)
            self.criteria=plan.get('criteria',[])
            if plan.get('receipt_id'):
                return dict(status='replayed', receipt=self.read(plan['receipt_id']))
            return self.permute(plan, plan['target'], deadline, undo=False)

    def undo(self, receipt_id, *, deadline):
        with self.locked(deadline):
            original = self.read(receipt_id)
            if original.get('undo_receipt_id'):
                return dict(status='replayed', receipt=self.read(original['undo_receipt_id']))
            if original['status'] != 'applied':
                raise TabError('workspace_undo_held', 'only fully observed applied layout may be undone')
            plan = self.read(original['plan_id'])
            self.criteria=plan.get('criteria',[])
            inverse = dict(plan, before=original['after'], fingerprint=digest(original['after']), undo_parent=receipt_id)
            target = [{k: w[k] for k in ('window_id', 'index', 'name')} for w in plan['before']['windows']]
            result = self.permute(inverse, target, deadline, undo=True)
            original['undo_receipt_id'] = result['receipt']['receipt_id']
            self.save(receipt_id, original)
            return result

    def permute(self, plan, target, deadline, *, undo):
        if self.authorize is None:
            raise TabError('workspace_permission_unavailable', 'host effect authorization required')
        action = 'workspace.undo' if undo else 'workspace.order'
        self.authorize(action)
        current = self.snapshot(plan['pins'], deadline)
        if (digest(plan['before']) != plan['fingerprint'] or
                digest(stable_snapshot(current)) != digest(stable_snapshot(plan['before']))):
            raise TabError('workspace_stale_plan', 'layout, binding, activity or focus changed; preview again')
        receipt = dict(version=1, receipt_id='receipt_' + uuid.uuid4().hex,
            plan_id=plan['plan_id'], status='pending', action=action, swaps=[], before=current, after=None)
        self.save(receipt['receipt_id'], receipt)
        if undo:
            original_receipt = self.read(plan['undo_parent'])
            original_receipt['undo_receipt_id'] = receipt['receipt_id']
            self.save(plan['undo_parent'], original_receipt)
        if not undo:
            original = self.read(plan['plan_id'])
            original['receipt_id'] = receipt['receipt_id']
            self.save(plan['plan_id'], original)
        try:
            for position, wanted in enumerate(target):
                windows = current['windows']
                if windows[position]['window_id'] == wanted['window_id']: continue
                self.authorize(action)
                observed = self.snapshot(plan['pins'], deadline)
                if digest(stable_snapshot(observed)) != digest(stable_snapshot(current)):
                    raise TabError('workspace_changed', 'workspace changed between swaps')
                other = next(i for i, w in enumerate(windows) if w['window_id'] == wanted['window_id'])
                first, second = windows[position], windows[other]
                receipt['swaps'].append(dict(first=first['window_id'], second=second['window_id'], state='pending'))
                self.save(receipt['receipt_id'], receipt)
                self.transport.swap(first['window_id'], second['window_id'], deadline)
                expected = json.loads(json.dumps(current))
                expected['windows'][position], expected['windows'][other] = expected['windows'][other], expected['windows'][position]
                expected['windows'][position]['index'], expected['windows'][other]['index'] = first['index'], second['index']
                current = self.snapshot(plan['pins'], deadline)
                if digest(stable_snapshot(current)) != digest(stable_snapshot(expected)):
                    raise TabError('workspace_changed', 'swap postcondition unavailable or changed')
                receipt['swaps'][-1]['state'] = 'observed'
                receipt['after'] = current
                self.save(receipt['receipt_id'], receipt)
            receipt['status'] = 'undone' if undo else 'applied'
            receipt['after'] = current
        except Exception as error:
            receipt['status'] = 'uncertain' if receipt['swaps'] and receipt['swaps'][-1]['state'] == 'pending' else 'partial'
            receipt['reason'] = getattr(error, 'code', type(error).__name__)
        self.save(receipt['receipt_id'], receipt)
        return dict(status=receipt['status'], receipt=receipt)
