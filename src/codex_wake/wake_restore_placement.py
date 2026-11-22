"""Read and recover the saved tmux placement without replacing its old shell."""
from pathlib import Path
import os
import re

from .records import WakeError


def valid_placement(saved):
    return (isinstance(saved, dict) and set(saved) == {'session', 'title', 'index'}
            and type(saved['index']) is int and 0 <= saved['index'] <= 2147483647
            and all(isinstance(saved[key], str) and saved[key] and len(saved[key]) <= 256
                    and all(ord(char) >= 32 for char in saved[key]) for key in ('session', 'title')))


def capture_placement(thread_id, profile):
    from .sessions import observe, revalidate_attachment

    socket = profile.get('tmux_socket')
    if not socket:
        return None
    snapshot = observe(endpoint=profile['app_server'], socket_path=socket, timeout=profile['timeout'])
    matches = [row for row in snapshot['sessions'] if row.get('thread_id') == thread_id]
    if (not snapshot.get('complete') or len(matches) != 1
            or any(thread_id in row.get('candidates', []) for row in snapshot['sessions'])):
        return None
    row = matches[0]
    attachments = row.get('attachments', [])
    if row.get('binding_status') != 'metadata_matched' or len(attachments) != 1:
        return None
    attachment = attachments[0]
    if (attachment.get('socket') != socket or attachment.get('pane_current_path') != profile['cwd']
            or not revalidate_attachment(attachment)):
        return None
    saved = dict(session=attachment['session_name'], title=attachment['window_name'],
                 index=int(attachment['window_index']))
    return saved if valid_placement(saved) else None


_FIELDS = ('session_id', 'window_id', 'window_index', 'window_name', 'pane_id',
           'pane_pid', 'pane_current_path', 'pane_current_command', 'pane_tty', 'pane_in_mode',
           'alternate_on', 'window_linked')


def _panes(terminal, runtime, session):
    rendered = '\t'.join('#{' + field + '}' for field in _FIELDS)
    output = terminal(runtime, 'list-panes', '-s', '-t', session, '-F', rendered)
    rows = []
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) != len(_FIELDS):
            raise WakeError('live_restore_terminal_inventory_unverified')
        row = dict(zip(_FIELDS, fields))
        if any(not re.fullmatch(pattern, row[key]) for key, pattern in (
                ('session_id', r'\$\d+'), ('window_id', r'@\d+'), ('pane_id', r'%\d+'),
                ('window_index', r'\d+'), ('pane_pid', r'[1-9]\d*'))):
            raise WakeError('live_restore_terminal_inventory_unverified')
        rows.append(row)
    if not rows or len({row['session_id'] for row in rows}) != 1:
        raise WakeError('live_restore_terminal_inventory_unverified')
    return rows


def _idle_shell(row):
    if (row['pane_current_command'] not in {'bash', 'dash', 'fish', 'sh', 'zsh'}
            or row['pane_in_mode'] != '0' or row['alternate_on'] != '0'
            or row['window_linked'] != '0'):
        return False
    pid = row['pane_pid']
    proc = Path('/proc') / pid
    try:
        if proc.stat().st_uid != os.geteuid():
            return False
        stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        return (stat[0] in ('S', 'I') and stat[2] == stat[5] == pid
                and (proc / 'fd/0').resolve(strict=True) == Path(row['pane_tty'])
                and not (proc / 'task' / pid / 'children').read_text().strip())
    except (OSError, ValueError, IndexError):
        return False


def _candidate(rows, saved, cwd):
    windows = {}
    for row in rows:
        windows.setdefault(row['window_id'], []).append(row)
    ranked = []
    for panes in windows.values():
        row = panes[0]
        title_match = row['window_name'] == saved['title']
        index_match = int(row['window_index']) == saved['index']
        if (len(panes) == 1 and row['pane_current_path'] == cwd and (title_match or index_match)
                and _idle_shell(row)):
            ranked.append((title_match + index_match, row))
    ranked.sort(key=lambda candidate: candidate[0], reverse=True)
    if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
        return ranked[0][1]
    return None


def _title(rows, desired):
    taken = {row['window_name'] for row in rows}
    if desired not in taken:
        return desired
    index = 1
    while True:
        suffix = '-restored' if index == 1 else f'-restored-{index}'
        title = desired[:256 - len(suffix)] + suffix
        if title not in taken:
            return title
        index += 1


def launch_placed(terminal, runtime, saved, cwd, launch, *, recreated=False):
    from .process import process_identity

    rows = _panes(terminal, runtime, '=' + saved['session'])
    session = rows[0]['session_id']
    candidate = _candidate(rows, saved, cwd)
    generation = process_identity(int(candidate['pane_pid'])) if candidate else None
    name = _title(rows, saved['title'])
    occupied = {int(row['window_index']) for row in rows}
    destination = max(occupied) + 1
    if recreated and saved['index'] not in occupied and candidate is None:
        destination = saved['index']
    target = session + ':' + str(destination)
    result = launch(name, target)
    ids = result.split('\t')
    if len(ids) != 2 or not re.fullmatch(r'@\d+', ids[0]) or not re.fullmatch(r'%\d+', ids[1]):
        raise WakeError('live_restore_launch_identity_unverified')
    window, pane = ids
    current = _panes(terminal, runtime, session)
    reclaimed = None
    if candidate and generation:
        members = [row for row in current if row['window_id'] == candidate['window_id']]
        if members == [candidate] and process_identity(int(candidate['pane_pid'])) == generation and _idle_shell(candidate):
            # Stable tmux window IDs keep a racing index change from moving a
            # third window. Swapping keeps the original window and shell alive.
            checks = {
                'session_id': session,
                'window_id': candidate['window_id'],
                'window_index': candidate['window_index'],
                'window_panes': '1',
                'window_linked': '0',
                'pane_pid': candidate['pane_pid'],
                'pane_current_command': candidate['pane_current_command'],
                'pane_in_mode': '0',
                'alternate_on': '0',
            }
            condition = '1'
            for field, expected in checks.items():
                condition = '#{&&:' + condition + ',#{==:#{' + field + '},' + expected + '}}'
            terminal(runtime, 'if-shell', '-F', '-t', candidate['pane_id'], condition,
                     f"swap-window -d -s {window} -t {candidate['window_id']}")
            current = _panes(terminal, runtime, session)
            shell = [row for row in current if row['pane_id'] == candidate['pane_id']]
            if len(shell) == 1 and shell[0]['window_id'] == candidate['window_id']:
                if int(shell[0]['window_index']) == destination:
                    reclaimed = dict(window_id=shell[0]['window_id'], pane_id=shell[0]['pane_id'],
                                     index=destination)
    restored = [row for row in current if row['window_id'] == window and row['pane_id'] == pane]
    if len(restored) != 1:
        raise WakeError('live_restore_placement_readback_unverified')
    actual = restored[0]
    return dict(session=saved['session'], session_id=session, window_id=window, pane_id=pane,
                index=int(actual['window_index']), title=actual['window_name'], placeholder=reclaimed)
