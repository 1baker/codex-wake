"""Read-only exact-turn observations with bounded, resumable snapshot custody.

Native thread/read is deliberately used instead of thread/resume: it observes
already-running human/other-client work without attaching a mutating subscriber.
Snapshot changes are not advertised as the original native notification stream.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4
from websockets.exceptions import WebSocketException

from .controller_runtime import ControllerRuntime, encoded
from .local_sessions import resolve
from .local_session_operations import LocalSessionControl
from .managed_inventory import InventoryError
from .native_protocol import native_request

_TERMINAL = {'completed': 'completed', 'failed': 'failed', 'interrupted': 'cancelled'}
_CAPABILITIES = dict(read_only=True, live_notification_stream=False,
                     snapshot_events=True, original_notification_replay=False)


class SessionObservations:
    """Public same-user observer; delegated adapters must supply current authorization."""
    def __init__(self, root, *, authorize=None):
        self.root = root
        self.runtime = ControllerRuntime(root)
        self.authorize = authorize
        with self.runtime.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS session_observations (id TEXT PRIMARY KEY, record TEXT)')

    def _owned(self, record):
        target = record['session']['target']
        home = Path(target['home'])
        if target.get('uid') != os.getuid() or home.stat().st_uid != os.getuid():
            raise InventoryError('foreign_target', 'observation belongs to another local user')
        if self.authorize is not None:
            # Rechecked on every poll/page; a remembered grant is never authority.
            self.authorize(target, 'content')
        resolve(self.root, 'thread:' + record['session']['thread_id'], target,
                endpoint=record['session']['endpoint'])

    def _load(self, identifier):
        if not isinstance(identifier, str) or len(identifier) > 128:
            raise InventoryError('invalid_argument', 'bounded observation identity required')
        with self.runtime.connect() as db:
            row = db.execute('SELECT record FROM session_observations WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise InventoryError('observation_not_found', 'original observation is unavailable')
        return json.loads(row[0])


    def observe(self, selector, turn_id, *, endpoint='unix://', expected_target=None,
                idempotency_key=None, max_events=256, max_bytes=1048576):
        if not isinstance(turn_id, str) or not 0 < len(turn_id) <= 256:
            raise InventoryError('invalid_argument', 'exact existing turn identity required')
        key = idempotency_key or uuid4().hex
        if not isinstance(key, str) or not 0 < len(key) <= 128:
            raise InventoryError('invalid_argument', 'bounded observation key required')
        if type(max_events) is not int or not 1 <= max_events <= 2048 or type(max_bytes) is not int or not 1024 <= max_bytes <= 2097152:
            raise InventoryError('invalid_argument', 'bounded observation retention required')
        identifier = 'observation-' + hashlib.sha256(key.encode()).hexdigest()[:32]
        try:
            record = self._load(identifier)
        except InventoryError as error:
            if error.code != 'observation_not_found':
                raise
            record = None
        if record is not None:
            self._owned(record)
            session = record['session']
            if turn_id != record['turn_id'] or (max_events, max_bytes) != (record['max_events'], record['max_bytes']):
                raise InventoryError('idempotency_conflict', 'observation key already binds another intent')
            if expected_target is not None and expected_target != session['target']:
                raise InventoryError('stale_target', 'retry cannot replace original observation target')
            if endpoint not in ('unix://', session['endpoint']):
                raise InventoryError('idempotency_conflict', 'retry cannot replace original observation endpoint')
            selected = resolve(self.root, selector, session['target'], endpoint=session['endpoint'])
            if selected['thread_id'] != session['thread_id']:
                raise InventoryError('idempotency_conflict', 'retry cannot replace original conversation')
        else:
            selected = resolve(self.root, selector, expected_target, endpoint=endpoint)
            session = {k: selected[k] for k in ('thread_id', 'target', 'endpoint', 'codex_cmd')}
            record = dict(observation_id=identifier, turn_id=turn_id, session=session,
                          max_events=max_events, max_bytes=max_bytes, sequence=0, events=[],
                          status='observing', terminal=False, execution='unknown', snapshot=None,
                          history_gap=True, truncated=False, created_at=time.time())
            self._owned(record)
            # Read-only admission is durable before the first remote observation.
            with self.runtime.connect() as db:
                db.execute('INSERT OR IGNORE INTO session_observations VALUES(?,?)',
                           (identifier, encoded(record)))
            record = self._load(identifier)
            if record['session'] != session or record['turn_id'] != turn_id:
                raise InventoryError('idempotency_conflict', 'concurrent observation admission conflicts')
        observed = self.output(identifier)['result']
        return dict(schema_version=1, operation='local.observe', status='completed',
                    result=dict(observation_id=identifier, turn_id=turn_id,
                                target=record['session']['target'], capabilities=_CAPABILITIES,
                                status=observed['status'], reason=observed['reason'],
                                terminal=observed['terminal'], execution=observed['execution']))

    @staticmethod
    def _snapshot(turn):
        # Keep newest answer content first within the shared output budget, then
        # restore native item order. Tool status is retained, not secret-bearing
        # tool arguments/results or hidden reasoning.
        items = []
        text_remaining = 32768
        truncated = False
        source = turn.get('items', [])
        for item in reversed(source):
            if not isinstance(item, dict) or item.get('type') in ('reasoning', 'userMessage') or item.get('phase') == 'analysis':
                continue
            if len(items) >= 256:
                truncated = True
                break
            clean = {}
            for key in ('id', 'type', 'phase', 'status', 'exitCode', 'tool', 'server', 'name'):
                value = item.get(key)
                if key not in item or not isinstance(value, (str, int, float, bool, type(None))):
                    continue
                if isinstance(value, str) and len(value.encode()) > 256:
                    value = value.encode()[:256].decode(errors='replace')
                    truncated = True
                clean[key] = value
            if item.get('type') == 'agentMessage' and isinstance(item.get('text'), str):
                text = item['text'].encode()
                retained = text[:text_remaining]
                text_remaining -= len(retained)
                cut = len(retained) < len(text)
                clean.update(text=retained.decode(errors='replace'), truncated=cut)
                truncated = truncated or cut
            if len(encoded([*items, clean]).encode()) > 65536:
                truncated = True
                break
            items.append(clean)
        return dict(id=turn['id'], status=turn.get('status'), items=list(reversed(items)), truncated=truncated)

    def _append(self, record, kind, params):
        record['sequence'] += 1
        record['events'].append(dict(sequence=record['sequence'], kind=kind, params=params,
                                     observed_at=time.time(), provenance='native_thread_snapshot'))
        while record['events'] and (len(record['events']) > record['max_events'] or len(encoded(record['events']).encode()) > record['max_bytes']):
            record['events'].pop(0)
            record.update(truncated=True, history_gap=True)

    def output(self, identifier, *, cursor=0, limit=100):
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise InventoryError('invalid_argument', 'nonnegative cursor and limit1..100 required')
        record = self._load(identifier)
        self._owned(record)
        if cursor > record['sequence']:
            raise InventoryError('invalid_cursor', 'cursor is beyond observation history')
        # Remote I/O never holds the shared operation journal write lock. A late
        # read cannot overwrite cancellation, terminal evidence or a newer read.
        started = time.monotonic_ns()
        snapshot = None
        failure = None
        if record['status'] != 'cancelled' and not record['terminal']:
            session = record['session']
            control = LocalSessionControl(self.root, request=native_request)
            try:
                value = control._request(session, 'thread/read', dict(threadId=session['thread_id'], includeTurns=True))['thread']
                if value.get('id') != session['thread_id']:
                    raise InventoryError('stale_target', 'native read belongs to another conversation')
                turns = [t for t in value.get('turns', []) if t.get('id') == record['turn_id']]
                if len(turns) != 1:
                    raise InventoryError('native_turn_unavailable', 'exact observed turn is not available')
                snapshot = self._snapshot(turns[0])
            except InventoryError as error:
                if error.code in ('stale_target', 'foreign_target'):
                    raise
                failure = error.code
            except (OSError, ValueError, KeyError, WebSocketException) as error:
                failure = getattr(error, 'code', 'native_observation_unavailable')
        self._owned(record)
        with self.runtime.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = json.loads(db.execute('SELECT record FROM session_observations WHERE id=?', (identifier,)).fetchone()[0])
            if record['status'] != 'cancelled' and not record['terminal'] and started >= record.get('last_read_started', 0):
                record['last_read_started'] = started
                if snapshot is not None:
                    if snapshot != record['snapshot']:
                        self._append(record, 'turn/snapshot', snapshot)
                        if snapshot['status'] in _TERMINAL:
                            self._append(record, 'turn/completed', dict(turnId=record['turn_id'], status=snapshot['status']))
                    record.update(snapshot=snapshot, status='observing', reason=None,
                                  terminal=snapshot['status'] in _TERMINAL,
                                  execution=_TERMINAL.get(snapshot['status'], 'running' if snapshot['status'] == 'inProgress' else 'unknown'))
                    if record['execution'] == 'unknown':
                        record.update(status='unavailable', reason='native_turn_status_unknown')
                    if record['terminal']:
                        answers = [i for i in snapshot['items'] if i.get('type') == 'agentMessage' and i.get('phase') in (None, 'final_answer') and 'text' in i]
                        answer = answers[-1] if answers else {}
                        record.update(status='completed', answer=dict(text=answer.get('text', ''), truncated=answer.get('truncated', False), source='native_thread_snapshot', turn_id=record['turn_id']))
                elif failure is not None:
                    record.update(status='unavailable', execution='unknown', reason=failure, history_gap=True)
                db.execute('UPDATE session_observations SET record=? WHERE id=?', (encoded(record), identifier))
        self._owned(record)
        events = [e for e in record['events'] if e['sequence'] > cursor][:limit]
        earliest = record['events'][0]['sequence'] - 1 if record['events'] else record['sequence']
        return dict(schema_version=1, operation='local.observation.output', status='completed', result=dict(
            observation_id=identifier, turn_id=record['turn_id'], target=record['session']['target'],
            status=record['status'], reason=record.get('reason'), terminal=record['terminal'],
            execution=record['execution'], snapshot=record['snapshot'], answer=record.get('answer'),
            events=events, next_cursor=events[-1]['sequence'] if events else cursor,
            latest_cursor=record['sequence'], capabilities=_CAPABILITIES,
            retention=dict(max_events=record['max_events'], max_bytes=record['max_bytes'],
                           earliest_cursor=earliest, cursor_gap=cursor < earliest,
                           history_gap=record['history_gap'], truncated=record['truncated'],
                           history_complete=False, source='native_thread_snapshots')))

    def cancel(self, identifier):
        record = self._load(identifier)
        self._owned(record)
        with self.runtime.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = json.loads(db.execute('SELECT record FROM session_observations WHERE id=?', (identifier,)).fetchone()[0])
            record.update(status='cancelled', reason='observer_cancelled')
            db.execute('UPDATE session_observations SET record=? WHERE id=?', (encoded(record), identifier))
        return dict(schema_version=1, operation='local.observation.cancel', status='completed',
                    result=dict(observation_id=identifier, observer_cancelled=True,
                                turn_cancelled=False))


def definitions():
    """Native observation entries for the existing local transport registry."""
    from functools import partial
    text = dict(type='string', minLength=1, maxLength=4096)
    def schema(properties, required):
        return dict(type='object', properties=properties, required=required, additionalProperties=False)
    def execute(verb, arguments, root):
        owner = SessionObservations(root)
        if verb == 'observe':
            return owner.observe(**arguments)
        arguments = dict(arguments)
        identifier = arguments.pop('observation_id')
        return owner.cancel(identifier) if verb == 'cancel' else owner.output(identifier, **arguments)
    observe = schema(dict(selector=text, turn_id=dict(type='string', minLength=1, maxLength=256),
                          endpoint=text, expected_target=dict(type='object'),
                          idempotency_key=dict(type='string', minLength=1, maxLength=128),
                          max_events=dict(type='integer', minimum=1, maximum=2048),
                          max_bytes=dict(type='integer', minimum=1024, maximum=2097152)), ['selector', 'turn_id'])
    output = schema(dict(observation_id=text, cursor=dict(type='integer', minimum=0),
                         limit=dict(type='integer', minimum=1, maximum=100)), ['observation_id'])
    return {
        'local.observe': ('wake_local_observe', 'Observe an exact already-existing turn without resuming or submitting work.', observe, partial(execute, 'observe'), True),
        'local.observation.output': ('wake_local_observation_output', 'Read bounded snapshot-derived events and exact terminal results; native notification history may have gaps.', output, partial(execute, 'output'), True),
        'local.observation.result': ('wake_local_observation_result', 'Reconcile the exact existing observed turn without replaying input.', output, partial(execute, 'result'), True),
        'local.observation.cancel': ('wake_local_observation_cancel', 'Stop observing; never interrupts the observed turn.', schema(dict(observation_id=text), ['observation_id']), partial(execute, 'cancel'), False),
    }
