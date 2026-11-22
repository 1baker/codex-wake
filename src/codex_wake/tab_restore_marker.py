"""Live tmux decoration and provenance for a Wake-restored window."""
import json
import re

PROVENANCE = '@codex_wake_restoration'
PENDING = '@codex_wake_restoration_pending'
SUFFIX = '#{?' + PENDING + ', ↻,}'
_FOCUS_HOOK = 'after-select-window'
_CLEAR_ON_FOCUS = "if-shell -F '#{?"+PENDING+",1,0}' 'set-option -wuq "+PENDING+"'"


def mark_restored(terminal, runtime, placement):
    """Stamp the exact live placement in the terminal server that created it."""
    pane = placement['pane_id']
    window = terminal(runtime, 'display-message', '-p', '-t', pane, '#{window_id}')
    if window != placement['window_id']:
        return
    # tmux resolves hooks from the closest scope with an existing array.
    # Append at that scope so its existing handlers continue to run.
    for scope in (('-w', '-t', pane), ('-t', pane), ('-g',)):
        hooks = terminal(runtime, 'show-hooks', *scope)
        selections = [line for line in hooks.splitlines() if line.startswith(_FOCUS_HOOK + '[')]
        if selections or scope == ('-g',):
            if not any(PENDING in line for line in selections):
                terminal(runtime, 'set-hook', '-a', *scope, _FOCUS_HOOK, _CLEAR_ON_FOCUS)
            break
    terminal(runtime, 'set-option', '-w', '-t', pane, PROVENANCE,
             json.dumps(placement, separators=(',', ':')), ';',
             'set-option', '-w', '-t', pane, PENDING, '1')


def read_launched_placement(terminal, runtime, launched):
    """Resolve actual location from a legacy launch without a saved index."""
    ids = launched.split('\t')
    if len(ids) != 2 or not re.fullmatch(r'%[0-9]+', ids[1]):
        return None
    raw = terminal(runtime, 'display-message', '-p', '-t', ids[1],
                   '#{window_id}\t#{session_id}\t#{session_name}\t#{window_index}\t#{window_name}')
    fields = raw.split('\t')
    if (len(fields) != 5 or fields[0] != ids[0] or not re.fullmatch(r'@[0-9]+', fields[0])
            or not re.fullmatch(r'\$[0-9]+', fields[1]) or not fields[3].isdigit()):
        return None
    window, session, name, index, title = fields
    return dict(session=name, session_id=session, window_id=window, pane_id=ids[1],
                index=int(index), title=title, placeholder=None)


def describe_restoration(raw, pending, window_id):
    """Project only metadata belonging to this exact native window."""
    if not raw or len(raw) > 4096:
        return None
    try:
        placement = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(placement, dict) or placement.get('window_id') != window_id:
        return None
    return dict(label='Restored by Wake', pending_focus=pending == '1', placement=placement)
