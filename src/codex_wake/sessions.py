"""Read-only live session inventory and exact Byobu selector resolution."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from .records import WakeError, _canonical_tmux_title, codex_client_identity_for_tty
from .shared_app_server import SharedAppServerReader, SharedSourceError, locate_shared_endpoint


class SelectionError(Exception):
    def __init__(self, code: int, message: str, selector: str, candidates=None):
        super().__init__(message)
        self.code, self.selector, self.candidates = code, selector, candidates or []


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tmux_inventory(socket_path: str | None, timeout: float, *, shell_metadata: bool = False) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    command = ['tmux'] + (['-S', socket_path] if socket_path else [])
    fields = ['session_id', 'session_name', 'window_id', 'window_index', 'window_name',
              'pane_id', 'pane_index', 'pane_title', 'pane_current_path', 'pane_tty', 'session_group']
    if shell_metadata:
        fields += ['pane_current_command', 'pane_pid']
    result = subprocess.run(command + ['list-panes', '-a', '-F', '\t'.join('#{' + x + '}' for x in fields)],
                            capture_output=True, text=True, timeout=timeout, check=True)
    rows = []
    for line in result.stdout.splitlines():
        if time.monotonic() >= deadline:
            raise SharedSourceError('tmux observation timed out')
        values = line.split('\t')
        if len(values) != len(fields):
            raise SharedSourceError('tmux metadata cannot be parsed unambiguously')
        row = dict(zip(fields, values))
        row['socket'] = socket_path
        row['pane_title'] = _canonical_tmux_title(row['pane_title'])
        try:
            identity = codex_client_identity_for_tty(row['pane_tty'])
        except WakeError:
            identity = None
        row['client_pid'] = identity[0] if identity else None
        row['client_start_time_ticks'] = identity[1] if identity else None
        row['evidence'] = 'process_generation' if identity else 'no_unique_codex_client'
        rows.append(row)
    return merge_grouped_session_aliases(rows)


_PHYSICAL_PANE = ('pane_id', 'window_id', 'pane_tty', 'client_pid', 'client_start_time_ticks')


def merge_grouped_session_aliases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """tmux grouped sessions (byobu and its byobu-NN clones) list the same physical pane once per session, so
    'exactly one attachment' checks saw two and refused (work-tracker #214: helper spawn stuck in
    exact_idle_owned_client_not_ready; close refused). Merge only rows of the SAME non-empty session group that are
    the same physical pane (same pane, window, tty and Codex client process generation): grouped sessions share one
    window list with the same indices, so one row with every (session_id, session_name) as an alias is exact. The
    group's own session (name == session_group) is the primary, so existing session-name comparisons still match.
    Ungrouped sessions that link the same window (tmux link-window) can use different indices, so they are never
    merged (review finding S214-SESSION-INDEX-01); neither are rows that differ in any physical field."""
    merged: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        group = row.get('session_group') or ''
        # An ungrouped row keys on its own session too, so it never merges across sessions.
        key = (group or ('ungrouped', row['session_id']),) + tuple(row.get(field) for field in _PHYSICAL_PANE)
        alias = (row['session_id'], row['session_name'])
        if key not in merged:
            merged[key] = dict(row, session_aliases=[alias])
            continue
        kept = merged[key]
        kept['session_aliases'].append(alias)
        if row['session_name'] == group and kept['session_name'] != group:
            merged[key] = dict(row, session_aliases=kept['session_aliases'])
    return list(merged.values())


def in_session(pane: dict[str, Any], session: str) -> bool:
    """A pane belongs to a session if any of its grouped-session aliases is that session id or name."""
    aliases = pane.get('session_aliases') or [(pane['session_id'], pane['session_name'])]
    return any(session in alias for alias in aliases)


def build_snapshot(threads: list[dict[str, Any]], panes: list[dict[str, Any]], sources: dict[str, Any]) -> dict[str, Any]:
    rows = []
    by_id = {}
    for thread in threads:
        status = thread.get('status')
        raw = status.get('type') if isinstance(status, dict) else status
        state = raw if raw in ('active', 'idle') else 'not_loaded' if raw == 'notLoaded' else 'unknown'
        source = thread.get('source')
        spawn = source.get('subAgent', {}) if isinstance(source, dict) else {}
        spawn = spawn.get('thread_spawn', {}) if isinstance(spawn, dict) else {}
        flags = status.get('activeFlags', []) if isinstance(status, dict) else []
        row = dict(thread_id=thread['id'], name=thread.get('name'), cwd=thread.get('cwd'),
                   source=thread.get('source'), parent_thread_id=thread.get('parentThreadId'),
                   agent_path=thread.get('agentPath') or spawn.get('agent_path'),
                   can_accept_direct_input=thread.get('canAcceptDirectInput'),
                   model_provider=thread.get('modelProvider'), agent_nickname=thread.get('agentNickname'),
                   agent_role=thread.get('agentRole'), runtime_state=state, provider_status=status,
                   active_flags=flags, binding_status='unbound', attachments=[], warnings=[])
        rows.append(row)
        by_id[thread['id']] = row
    for pane in panes:
        candidates = [row for row in rows if row['thread_id'] and row['name'] and row['cwd']
                      and row['name'] == _canonical_tmux_title(pane['pane_title'])
                      and row['cwd'] == pane['pane_current_path']]
        if pane['client_pid'] is not None and len(candidates) == 1:
            row = candidates[0]
            row['attachments'].append(dict(pane, evidence='metadata_matched'))
            row['binding_status'] = 'metadata_matched'
        else:
            rows.append(dict(thread_id=None, name=_canonical_tmux_title(pane['pane_title']),
                             cwd=pane['pane_current_path'], source='tmux', parent_thread_id=None,
                             agent_path=None, runtime_state='unknown', provider_status=None, active_flags=[],
                             binding_status=('ambiguous' if len(candidates) > 1 and pane['client_pid']
                                             else 'candidate' if pane['client_pid'] else 'not_codex'),
                             attachments=[pane], warnings=[],
                             candidates=[x['thread_id'] for x in candidates]))
    return dict(schema_version=1, observed_at=now(), complete=all(
        value['availability'] == 'available' for value in sources.values()), sources=sources, sessions=rows)


def observe(*, endpoint: str = 'unix://', socket_path: str | None = None, timeout: float = 10, shell_metadata: bool = False) -> dict[str, Any]:
    sources = {}
    threads, panes = [], []
    if socket_path is None and os.environ.get('TMUX'):
        socket_path = os.environ['TMUX'].split(',')[0]
    try:
        if endpoint == 'unix://':
            endpoint = locate_shared_endpoint(timeout=timeout)
        with SharedAppServerReader(endpoint, timeout=timeout) as reader:
            threads = reader.loaded_threads()
        sources['app_server'] = dict(endpoint=endpoint, observed_at=now(), availability='available', error_code=None)
    except (SharedSourceError, OSError) as exc:
        sources['app_server'] = dict(endpoint=endpoint, observed_at=now(), availability='unavailable', error_code=type(exc).__name__)
    try:
        panes = (tmux_inventory(socket_path, timeout, shell_metadata=True) if shell_metadata
                 else tmux_inventory(socket_path, timeout))
        sources['tmux'] = dict(endpoint=socket_path, observed_at=now(), availability='available', error_code=None)
    except (OSError, subprocess.SubprocessError, SharedSourceError) as exc:
        sources['tmux'] = dict(endpoint=socket_path, observed_at=now(), availability='unavailable', error_code=type(exc).__name__)
    return build_snapshot(threads, panes, sources)


def resolve(snapshot: dict[str, Any], selector: str, *, session: str | None = None,
            eligible: bool = True, require_attested: bool = False) -> dict[str, Any]:
    if not isinstance(selector, str) or not selector.strip() or len(selector) > 1024 or any(ord(c) < 32 for c in selector) or selector in ('thread:', 'tab:') or (selector.startswith('pane:') and not re.fullmatch(r'pane:%\d+', selector)) or (selector.startswith('window:') and not re.fullmatch(r'window:@\d+', selector)):
        raise SelectionError(2, 'invalid selector syntax', selector)
    if require_attested:
        raise SelectionError(5, 'runtime-issued binding is unsupported', selector)
    exact_thread = selector.startswith('thread:')
    required_available = snapshot['sources'].get('app_server', {}).get('availability') == 'available'
    if not required_available or (not exact_thread and not snapshot['complete']):
        raise SelectionError(5, 'selection requires complete required sources', selector)
    rows = snapshot['sessions']
    if selector.startswith('thread:'):
        matches = [row for row in rows if row['thread_id'] == selector[7:]]
    else:
        attachments = [(row, pane) for row in rows for pane in row['attachments']]
        if not selector.startswith(('pane:', 'window:')):
            sessions = {(p['session_id'], p['session_name']) for _, p in attachments}
            if session is None and os.environ.get('TMUX_PANE'):
                context = {p['session_id'] for _, p in attachments if p['pane_id'] == os.environ['TMUX_PANE']}
                if len(context) == 1:
                    session = next(iter(context))
            if session is None:
                if not sessions:
                    raise SelectionError(3, 'session not found', selector)
                if len(sessions) != 1:
                    raise SelectionError(4, 'qualify the tmux session', selector, sorted(sessions))
                session = next(iter(sessions))[0]
            attachments = [(r, p) for r, p in attachments if in_session(p, session)]
        elif session:
            attachments = [(r, p) for r, p in attachments if in_session(p, session)]
        from .tab_matching import match_tabs
        attachments, resolution = match_tabs(attachments, selector)
        if len(attachments) > 1:
            raise SelectionError(4, 'selector matches multiple panes or windows', selector,
                                 [p['window_index'] + ':' + p['window_name'] + '.' + p['pane_index'] for _, p in attachments])
        matches = [r for r, _ in attachments]
    if not matches:
        raise SelectionError(3, 'session not found', selector)
    if len(matches) > 1:
        raise SelectionError(4, 'session identity is ambiguous', selector)
    row = matches[0]
    if eligible and not row['thread_id']:
        raise SelectionError(4 if row['binding_status'] == 'ambiguous' else 6,
                             'selection has no unique Codex identity', selector, row.get('candidates'))
    return dict(row, selected_attachment=attachments[0][1] if not exact_thread else None,
                resolution=resolution if not exact_thread else dict(
        selector=selector, normalized_selector=selector, match_method='exact', confidence=1.0))


def revalidate_attachment(attachment: dict[str, Any]) -> bool:
    """Recheck an observed client generation without capturing pane contents."""
    try:
        current = tmux_inventory(attachment['socket'], 10)
        candidates = [p for p in current if p['pane_id'] == attachment['pane_id']]
        if len(candidates) != 1:
            return False
        pane = candidates[0]
        return (pane['client_pid'] is not None and all(
            pane[key] == attachment[key] for key in (
                'client_pid', 'client_start_time_ticks', 'pane_current_path', 'pane_title',
            )))
    except (OSError, subprocess.SubprocessError, SharedSourceError):
        return False
