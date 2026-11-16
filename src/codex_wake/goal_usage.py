"""Fresh-token sampled usage from native 0.163 response identities.

No native RPC or display counters. Unsupported/incomplete history is unknown.
"""
from datetime import datetime
from pathlib import Path
import json
import hashlib
import time
import os
import sqlite3
import stat

MAX_FILES = 4096
MAX_METADATA_BYTES = 4 * 1024 * 1024
# Evidence retention and total input scanning have distinct bounds. Tool output
# volume is not accounting evidence, but still consumes the scan/time budget.
MAX_HISTORY_BYTES = 32 * 1024 * 1024
MAX_SCAN_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES = 32 * 1024 * 1024
ACCOUNTING_EVENTS = frozenset(('thread_goal_updated', 'task_started', 'task_complete',
    'turn_aborted', 'collab_agent_spawn_begin', 'collab_agent_spawn_end', 'raw_response_completed'))
MAX_SCAN_SECONDS = 2.0



def _epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


MAX_INDEX_ROWS = 65536
MAX_INDEX_BYTES = 64 * 1024 * 1024


def _continuation_record(home, identity):
    """Native handoff journals locate successors; rollout metadata still proves membership."""
    if not isinstance(identity, str) or not identity or Path(identity).name != identity or identity in ('.', '..'):
        raise ValueError('usage_continuation_identity_invalid')
    try:
        directory = os.open(home/'provider_continuations', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('usage_continuation_directory_invalid')
        try:
            fd = os.open(identity+'.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('usage_continuation_record_invalid')
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('usage_continuation_record_limit')
        record = json.loads(raw)
        if (not isinstance(record, dict) or record.get('version') != 1
                or record.get('source') != identity or record.get('state') not in ('staged', 'preparing', 'ready')
                or not isinstance(record.get('successor'), str) or not record['successor']
                or not isinstance(record.get('session_id'), str) or not record['session_id']
                or record['state'] == 'ready' and any(not isinstance(record.get(key), str) or len(record[key]) != 64
                       or any(c not in '0123456789abcdefABCDEF' for c in record[key])
                       for key in ('authority_revision', 'context_revision'))):
            raise ValueError('usage_continuation_not_ready_or_invalid')
        return record, len(raw)
    finally:
        os.close(directory)


def _indexed_inventory(home, thread_id, check_time):
    """Use native metadata only as a locator; canonical rollout metadata wins."""
    index = home / 'state_5.sqlite'
    if not index.exists():
        return None
    index = index.resolve(strict=True)
    allowed = {home.resolve(), (home / 'sessions').resolve().parent}
    if (not index.is_file() or index.parent not in allowed
            or index.stat().st_uid != os.geteuid()):
        raise ValueError('usage_index_not_regular')
    connection = None
    try:
        connection = sqlite3.connect(index.absolute().as_uri() + '?mode=ro',
                                     uri=True, timeout=.2)
        connection.execute('PRAGMA query_only=ON')
        # mode=ro intentionally retains normal WAL visibility; not immutable=1.
        connection.set_progress_handler(lambda: _index_timed_out(check_time), 1000)
        columns = {r[1] for r in connection.execute('PRAGMA table_info(threads)')}
        if not {'id', 'rollout_path', 'source'}.issubset(columns):
            return None
        rows = {}; parents = {}; children = {}; size = 0
        for count, row in enumerate(connection.execute(
                'SELECT id, rollout_path, source FROM threads LIMIT ?',
                (MAX_INDEX_ROWS + 1,)), 1):
            check_time()
            if count > MAX_INDEX_ROWS:
                raise ValueError('usage_index_row_limit')
            identity, rollout, source = row
            if not all(isinstance(v, str) for v in row):
                raise ValueError('usage_index_metadata_invalid')
            size += sum(len(v.encode()) for v in row)
            if size > MAX_INDEX_BYTES:
                raise ValueError('usage_index_byte_limit')
            decoded = json.loads(source) if source.startswith(('{', '[', '"')) else source
            parent = None
            if isinstance(decoded, dict):
                subagent = decoded.get('subagent', {})
                spawn = subagent.get('thread_spawn', {}) if isinstance(subagent, dict) else {}
                if not isinstance(spawn, dict):
                    raise ValueError('usage_index_parent_invalid')
                parent = spawn.get('parent_thread_id')
            if identity in rows:
                raise ValueError('usage_index_duplicate_identity')
            rows[identity] = (Path(rollout), decoded)
            if parent:
                parents[identity] = parent
                children.setdefault(parent, set()).add(identity)
        edge_columns = {r[1] for r in connection.execute('PRAGMA table_info(thread_spawn_edges)')}
        if edge_columns:
            if not {'parent_thread_id', 'child_thread_id'}.issubset(edge_columns):
                return None
            for count, (parent, child) in enumerate(connection.execute(
                    'SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges LIMIT ?',
                    (MAX_INDEX_ROWS + 1,)), 1):
                check_time()
                if count > MAX_INDEX_ROWS:
                    raise ValueError('usage_index_edge_limit')
                if child in parents and parents[child] != parent:
                    raise ValueError('usage_index_parent_conflict')
                parents[child] = parent
                children.setdefault(parent, set()).add(child)
        owned = {thread_id}; pending = [thread_id]
        continuations = {}; continuation_bytes = 0
        while pending:
            check_time()
            parent = pending.pop()
            continuation = _continuation_record(home, parent)
            if continuation is not None:
                record, consumed = continuation
                continuation_bytes += consumed
                if continuation_bytes > MAX_METADATA_BYTES:
                    raise ValueError('usage_inventory_byte_limit')
                child = record['successor']
                if record['state'] == 'ready' or child in rows:
                    if child == parent or child in parents and parents[child] != parent:
                        raise ValueError('usage_index_parent_conflict')
                    parents[child] = parent
                    children.setdefault(parent, set()).add(child)
                    continuations[parent] = record
                # A staged/preparing successor not yet materialized cannot admit
                # inference. Keep observing the current source without interrupting it.
            for child in children.get(parent, ()):
                if child not in owned:
                    owned.add(child); pending.append(child)
                    if len(owned) > MAX_FILES:
                        raise ValueError('usage_index_descendant_limit')
        sessions_root = (home / 'sessions').resolve(strict=True)
        inventory = {}
        canonical_metadata_bytes = continuation_bytes
        for identity in owned:
            check_time()
            if identity not in rows:
                raise ValueError('usage_index_root_or_child_missing')
            path, source = rows[identity]
            if not path.is_absolute() or path.is_symlink() or not path.is_file():
                raise ValueError('usage_index_rollout_unavailable')
            path = path.resolve(strict=True)
            path.relative_to(sessions_root)
            with path.open('rb') as stream:
                first = stream.readline(65537)
            canonical_metadata_bytes += len(first)
            if canonical_metadata_bytes > MAX_METADATA_BYTES:
                raise ValueError('usage_inventory_byte_limit')
            if len(first) > 65536:
                raise ValueError('metadata_line_limit')
            row = json.loads(first); meta = row['payload']
            if row.get('type') != 'session_meta' or meta.get('id') != identity:
                raise ValueError('usage_index_identity_mismatch')
            if meta.get('source') != source:
                raise ValueError('usage_index_source_mismatch')
            native_parent = meta.get('parent_thread_id')
            if isinstance(source, dict):
                subagent = source.get('subagent', {})
                spawn = subagent.get('thread_spawn', {}) if isinstance(subagent, dict) else {}
                source_parent = spawn.get('parent_thread_id')
                if native_parent and source_parent and native_parent != source_parent:
                    raise ValueError('usage_index_parent_mismatch')
                native_parent = native_parent or source_parent
            if identity != thread_id and native_parent != parents.get(identity):
                raise ValueError('usage_index_parent_mismatch')
            inventory[identity] = [(meta, path)]
        for parent, record in continuations.items():
            source = inventory[parent][0][0]
            successor = inventory[record['successor']][0][0]
            if (source.get('session_id') != record['session_id']
                    or successor.get('session_id') != record['session_id']
                    or successor.get('parent_thread_id') != parent
                    or successor.get('forked_from_id') != parent):
                raise ValueError('usage_continuation_identity_mismatch')
        return inventory
    except sqlite3.Error as exc:
        raise ValueError('usage_index_unavailable_or_corrupt') from exc
    finally:
        if connection is not None:
            connection.close()


def _index_timed_out(check_time):
    try:
        check_time()
        return 0
    except ValueError:
        return 1


def observe_usage(codex_home, thread_id, goal_created_at, *, reset_anchor=None, token_accounting="fresh", session_scope=False):
    """Observe original-goal response spending, or an explicitly authorized anchor."""
    try:
        if token_accounting not in ("fresh", "cache_inclusive"):
            raise ValueError("unsupported_token_accounting")
        deadline = time.monotonic() + MAX_SCAN_SECONDS
        inventory = {}
        metadata_bytes = 0
        metadata_errors = False
        def check_time():
            if time.monotonic() > deadline:
                raise ValueError('usage_scan_time_limit')
        indexed = _indexed_inventory(Path(codex_home), thread_id, check_time)
        if indexed is not None:
            inventory = indexed
        else:
            def rollout_paths():
                for directory_count, (directory, _, names) in enumerate(
                        os.walk(Path(codex_home) / 'sessions', followlinks=False), 1):
                    check_time()
                    if directory_count > MAX_FILES:
                        raise ValueError('usage_inventory_directory_limit')
                    for name in names:
                        if name.endswith('.jsonl'):
                            yield Path(directory) / name
            for count, path in enumerate(rollout_paths(), 1):
                check_time()
                if count > MAX_FILES:
                    raise ValueError('usage_inventory_file_limit')
                try:
                    if path.is_symlink() or not path.is_file():
                        raise ValueError('non_regular_rollout')
                    with path.open('rb') as stream:
                        first = stream.readline(65537)
                    metadata_bytes += len(first)
                    if metadata_bytes > MAX_METADATA_BYTES:
                        raise ValueError('usage_inventory_byte_limit')
                    if len(first) > 65536:
                        raise ValueError('metadata_line_limit')
                    row = json.loads(first)
                    if row.get('type') != 'session_meta':
                        raise ValueError('missing_session_metadata')
                    meta = row['payload']
                    inventory.setdefault(meta['id'], []).append((meta, path))
                except (ValueError, KeyError, TypeError, OSError):
                    if metadata_bytes > MAX_METADATA_BYTES:
                        raise ValueError('usage_inventory_byte_limit')
                    metadata_errors = True
        if thread_id not in inventory:
            raise ValueError('root_rollout_missing_or_metadata_invalid' if metadata_errors
                             else 'root_rollout_missing')
        owned = {thread_id}
        changed = True
        while changed:
            check_time()
            changed = False
            for identity, candidates in inventory.items():
                for meta, _ in candidates:
                    parent = meta.get('parent_thread_id')
                    source = meta.get('source', {})
                    if isinstance(source, dict):
                        subagent = source.get('subagent', {})
                        spawn = subagent.get('thread_spawn', {}) if isinstance(subagent, dict) else {}
                        if isinstance(spawn, dict):
                            parent = parent or spawn.get('parent_thread_id')
                    if parent in owned and identity not in owned:
                        owned.add(identity); changed = True
        sessions = {}
        history_bytes = 0
        scanned_bytes = 0
        for identity in owned:
            check_time()
            candidates = inventory[identity]
            if len(candidates) != 1:
                raise ValueError('ambiguous_rollout_identity')
            meta, path = candidates[0]
            rows = []
            with path.open('rb') as stream:
                while True:
                    check_time()
                    line = stream.readline(min(MAX_LINE_BYTES, MAX_SCAN_BYTES - scanned_bytes) + 1)
                    if not line:
                        break
                    scanned_bytes += len(line)
                    if scanned_bytes > MAX_SCAN_BYTES:
                        raise ValueError('usage_scan_byte_limit')
                    if len(line) > MAX_LINE_BYTES:
                        raise ValueError('usage_line_byte_limit')
                    value = json.loads(line)
                    kind = value.get('type')
                    relevant = (kind in ('session_meta', 'token_usage_record') or
                        kind == 'event_msg' and value.get('payload', {}).get('type') in ACCOUNTING_EVENTS)
                    if relevant:
                        history_bytes += len(line)
                        if history_bytes > MAX_HISTORY_BYTES:
                            raise ValueError('usage_history_byte_limit')
                        rows.append(value)
            if not rows or rows[0].get('payload') != meta:
                raise ValueError('rollout_metadata_changed')
            sessions[identity] = (meta, rows[1:])
        rows = sessions[thread_id][1]
        boundaries = [i for i, r in enumerate(rows)
            if r.get('type') == 'event_msg'
            and r['payload'].get('type') == 'thread_goal_updated'
            and r['payload'].get('goal', {}).get('createdAt') == goal_created_at]
        if session_scope:
            # A session boundary is its original history, including work before
            # voluntary enrollment or a native goal created during an active turn.
            boundary = -1
            stamp = sessions[thread_id][0].get('timestamp')
            if not stamp and rows:
                stamp = rows[0]['timestamp']
            if not stamp:
                raise ValueError('session_start_missing')
            creation = dict(timestamp=stamp)
        else:
            if not boundaries:
                raise ValueError('goal_start_missing')
            boundary = boundaries[0]
            creation = rows[boundary]
            if (creation['payload'].get('threadId') != thread_id
                    or creation['payload']['goal'].get('threadId') != thread_id):
                raise ValueError('goal_identity_mismatch')
            if int(_epoch(creation['timestamp'])) != goal_created_at:
                raise ValueError('goal_start_not_original')
        active = set()
        for r in rows[:max(0, boundary)]:
            if r.get('type') != 'event_msg':
                continue
            p = r['payload']
            if p.get('type') == 'task_started':
                active.add(p['turn_id'])
            elif p.get('type') in ('task_complete', 'turn_aborted'):
                active.discard(p['turn_id'])
        if active:
            raise ValueError('goal_start_during_active_turn')
        turns = {r['payload']['turn_id'] for r in rows[boundary+1:]
            if r.get('type') == 'event_msg' and r['payload'].get('type') == 'task_started'}
        # A descendant can start later turns after an operational refresh or
        # goal continuation. Its initial inherited root_turn_id is not permanent.
        for identity, (_, history) in sessions.items():
            if identity != thread_id:
                turns.update(r['payload']['turn_id'] for r in history
                    if r.get('type') == 'event_msg' and r['payload'].get('type') == 'task_started'
                    and _epoch(r['timestamp']) >= _epoch(creation['timestamp']))
        for identity, (meta, _) in sessions.items():
            parent = meta.get('parent_thread_id')
            source = meta.get('source', {})
            if isinstance(source, dict):
                subagent = source.get('subagent', {})
                spawn = subagent.get('thread_spawn', {}) if isinstance(subagent, dict) else {}
                if not isinstance(spawn, dict):
                    raise ValueError('malformed_parent_identity')
                source_parent = spawn.get('parent_thread_id')
                if parent and source_parent and parent != source_parent:
                    raise ValueError('conflicting_parent_identity')
        records = {}
        charged = set()
        for identity in owned:
            meta, history = sessions[identity]
            provider = meta.get('model_provider', '')
            if (isinstance(provider, str) and (provider == 'grok' or provider.startswith('grok__'))
                    and any(r.get('type') == 'event_msg'
                            and r['payload'].get('turn_id') in turns
                            and ((r['payload'].get('type') == 'turn_aborted'
                                  and r['payload'].get('reason') == 'interrupted')
                                 or (r['payload'].get('type') == 'task_complete'
                                     and isinstance(r['payload'].get('error'), dict)
                                     and r['payload']['error'].get('codex_error_info')
                                         != 'session_budget_exceeded'))
                            for r in history)):
                # Local Stop or a failed request is not provider-side completion/usage evidence.
                # Earlier observed charges remain retained; do not qualify an
                # uncertain later request as zero or as only those prior charges.
                raise ValueError('provider_completion_unconfirmed')
            if meta.get('history_base') or (identity == thread_id and meta.get('forked_from_id')):
                raise ValueError('referenced_or_root_fork_history_unqualified')
            if meta.get('session_id') != sessions[thread_id][0].get('session_id'):
                raise ValueError('descendant_session_identity_mismatch')
            for r in history:
                p = r['payload']
                if r.get('type') == 'event_msg' and p.get('type') == 'collab_agent_spawn_end':
                    child = p.get('new_thread_id')
                    if child and child not in owned:
                        raise ValueError('descendant_rollout_missing')
                if r.get('type') != 'token_usage_record':
                    continue
                key = (p['thread_id'], p['response_id'])
                total = p['usage']['total_tokens']
                usage = p['usage']
                components = [usage.get(key) for key in
                    ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens')]
                if any(type(v) is not int or v < 0 for v in components):
                    raise ValueError('malformed_usage')
                inputs, cached, outputs, total = components
                if cached > inputs or total != inputs + outputs:
                    raise ValueError('inconsistent_usage_components')
                if p['thread_id'] not in owned:
                    raise ValueError('inherited_record_owner_missing')
                if key in records and records[key] != p:
                    raise ValueError('conflicting_response_identity')
                records[key] = p
                if p['root_turn_id'] in turns:
                    charged.add(key)
        prior_turns = {r['payload']['root_turn_id'] for r in rows[:max(0, boundary)]
                       if r.get('type') == 'token_usage_record'}
        for identity in owned:
            _, history = sessions[identity]
            pending_spawns = set()
            for r in history:
                p = r['payload']
                if r.get('type') == 'token_usage_record':
                    if p['root_turn_id'] not in turns | prior_turns:
                        raise ValueError('response_goal_attribution_unknown')
                if r.get('type') != 'event_msg':
                    continue
                if p.get('type') == 'collab_agent_spawn_begin':
                    pending_spawns.add(p['call_id'])
                if p.get('type') == 'collab_agent_spawn_end':
                    pending_spawns.discard(p.get('call_id'))
                if p.get('type') == 'raw_response_completed':
                    key = (identity, p['response_id'])
                    if key not in records or p.get('token_usage') is None:
                        raise ValueError('response_usage_missing')
                    if records[key]['usage'] != p['token_usage']:
                        raise ValueError('response_usage_mismatch')
            if pending_spawns:
                raise ValueError('descendant_spawn_incomplete')
        if turns and not charged and not session_scope:
            raise ValueError('first_usage_unavailable')
        check_time()
        anchor = dict(version=1, thread_id=thread_id, goal_created_at=goal_created_at,
            boundary=creation['timestamp'], response_ids=[list(k) for k in sorted(records)],
            response_hashes={json.dumps(k): hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()
                             for k, v in records.items()})
        check_time()
        excluded = set()
        if reset_anchor is not None:
            if any(reset_anchor.get(k) != anchor[k] for k in
                   ('version', 'thread_id', 'goal_created_at', 'boundary')):
                raise ValueError('reset_anchor_identity_mismatch')
            excluded = {tuple(k) for k in reset_anchor['response_ids']}
            if not excluded.issubset(records):
                raise ValueError('reset_anchor_history_missing')
            if any(reset_anchor['response_hashes'].get(json.dumps(k)) !=
                   anchor['response_hashes'][json.dumps(k)] for k in excluded):
                raise ValueError('reset_anchor_history_changed')
        check_time()
        root_meta=sessions[thread_id][0]
        parent_thread_id=root_meta.get('parent_thread_id')
        source=root_meta.get('source',{})
        if isinstance(source,dict):
            subagent=source.get('subagent',{})
            spawn=subagent.get('thread_spawn',{}) if isinstance(subagent,dict) else {}
            if isinstance(spawn,dict):parent_thread_id=parent_thread_id or spawn.get('parent_thread_id')
        selected = [records[k]['usage'] for k in charged - excluded]
        inclusive = sum(v['total_tokens'] for v in selected)
        cached = sum(v['cached_input_tokens'] for v in selected)
        return dict(state='qualified', thread_ids=sorted(owned), parent_thread_id=parent_thread_id, used_tokens=inclusive - cached if token_accounting == 'fresh' else inclusive,
            fresh_tokens=inclusive - cached, cached_input_tokens=cached,
            cache_inclusive_tokens=inclusive, token_accounting=token_accounting,
            charges={json.dumps(k):dict(
                tokens=records[k]['usage']['total_tokens']-(records[k]['usage']['cached_input_tokens'] if token_accounting=='fresh' else 0),
                response_hash=anchor['response_hashes'][json.dumps(k)]) for k in charged-excluded},
            anchor=anchor, reason=None, sampled=True)
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        return dict(state='unknown', used_tokens=None, anchor=None,
                    reason=str(exc), sampled=True)


def observe_session_usage(codex_home, thread_id, *, token_accounting="fresh"):
    """Read lifetime response charges from original session history, without a goal."""
    return observe_usage(codex_home, thread_id, None,
        token_accounting=token_accounting, session_scope=True)
