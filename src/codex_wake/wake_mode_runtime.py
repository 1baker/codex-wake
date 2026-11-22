"""Exact-conversation mode routing and serial admission across a wake root."""
from functools import wraps
from pathlib import Path

from .records import WakeLifecycleLock, replace_record
from .wake_session_modes import SESSION_OBSERVATION_TIMEOUT
from .runtime_delivery import RuntimeCapability, RuntimeObservation, RuntimeSubmission, RuntimeTargetError


def observe_mode_presence(target, *, resumed=False):
    from .sessions import observe
    from .shared_app_server import locate_shared_endpoint
    endpoint = target['endpoint']
    if endpoint == 'unix://':
        endpoint = locate_shared_endpoint(codex_cmd=target['codex_cmd'], timeout=5)
    snapshot = observe(endpoint=endpoint, socket_path=target.get('tmux_socket'), timeout=SESSION_OBSERVATION_TIMEOUT)
    if not snapshot.get('complete'):
        # A missing *pinned* socket plus lost original client can qualify
        # absence, but only with available native inventory and no loaded
        # or ambiguous peer attachment in this declared runtime namespace.
        from .wake_session_modes import session_state
        socket = target.get('tmux_socket')
        sources = snapshot.get('sources', {})
        missing = False
        if isinstance(socket, str) and Path(socket).is_absolute():
            try:
                Path(socket).lstat()
            except FileNotFoundError:
                missing = True
            except OSError:
                pass
        old = dict(target, session_mode='session_only', session_owner=target.get('session_origin') or target.get('session_owner'))
        rows = [row for row in snapshot.get('sessions', []) if row.get('thread_id') == target['thread_id']]
        ambiguous = any(target['thread_id'] in row.get('candidates', []) for row in snapshot.get('sessions', []))
        saved_only = not rows or (len(rows) == 1 and not rows[0].get('attachments')
            and (rows[0].get('runtime_state') == 'not_loaded'
                 or (resumed and rows[0].get('runtime_state') in ('idle', 'active'))))
        if (missing and sources.get('app_server', {}).get('availability') == 'available'
                and sources.get('tmux', {}).get('availability') == 'unavailable'
                and session_state(old) == 'closed' and saved_only and not ambiguous):
            return 'background'
        raise RuntimeTargetError('unavailable', 'recipient_ownership_unknown')
    rows = [row for row in snapshot['sessions'] if row.get('thread_id') == target['thread_id']]
    candidates = [row for row in snapshot['sessions'] if target['thread_id'] in row.get('candidates', [])]
    if candidates or len(rows) > 1:
        raise RuntimeTargetError('unavailable', 'recipient_ownership_unknown')
    if not rows or not rows[0].get('attachments'):
        return 'background'
    row = rows[0]
    if row.get('binding_status') != 'metadata_matched' or len(row['attachments']) != 1:
        raise RuntimeTargetError('unavailable', 'recipient_ownership_unknown')
    attachment = row['attachments'][0]
    if not attachment.get('client_pid') or not attachment.get('client_start_time_ticks'):
        raise RuntimeTargetError('unavailable', 'recipient_ownership_unknown')
    return 'existing_tab'


class ModeRuntimeAdapter:
    """Choose a verified attachment or saved-thread route without creating identity."""

    def __init__(self, root, adapter, *, permission_context=None, expires_at=None, occurrence_id=None, background_owned=False):
        self.root = Path(root)
        self.adapter = adapter
        self.permission_context = permission_context
        self.expires_at = expires_at
        self.occurrence_id = occurrence_id
        self.background_owned = background_owned
        self._selected = {}

    def resolve(self, target):
        return self.adapter.resolve(target)

    def _presence(self, target, *, resumed=False):
        return observe_mode_presence(target, resumed=resumed or self.background_owned)

    @staticmethod
    def _capabilities(observation, route):
        capabilities = dict(observation.capabilities)
        for candidate in ('existing_tab', 'background', 'new_tab'):
            capabilities['wake.' + candidate] = RuntimeCapability(
                'supported' if candidate == route else 'unsupported', 'explicit_session_mode_route')
        capabilities['active_tab'] = RuntimeCapability(
            'supported' if route in ('existing_tab', 'new_tab') else 'unavailable', 'verified_mode_attachment')
        return RuntimeObservation(observation.state, observation.reason, capabilities,
                                  observation.resumed, observation.native_status)

    def observe(self, recipient):
        target = dict(recipient.binding)
        mode = target.get('session_mode')
        if mode is None:
            return self.adapter.observe(recipient)
        try:
            route = self._presence(target)
            requested = target.get('wake_route')
            # Common permission dispatch tries each declared route independently.
            if requested and requested != route and not (mode == 'reopen_live' and requested == 'new_tab' and route == 'background'):
                return self._capabilities(RuntimeObservation('unavailable', 'mode_route_not_selected', {}), route)
            if route == 'background' and mode == 'session_only':
                raise RuntimeTargetError('unavailable', 'active_attachment_unavailable')
            if mode == 'reopen_live' and route == 'background':
                from .wake_live_restore import LiveWakeRestorer
                target.update(_wake_permission_context=self.permission_context,
                              _wake_expires_at=self.expires_at,
                              _wake_occurrence_id=self.occurrence_id)
                restored = LiveWakeRestorer(self.root).prepare(target)
                if restored.get('thread_id') != recipient.session_id:
                    raise RuntimeTargetError('unavailable', 'restoration_recipient_changed')
                target = dict(restored)
                route = 'new_tab'
            elif mode not in ('session_only', 'reopen_live', 'background'):
                raise RuntimeTargetError('unsupported', 'invalid_session_mode')
            # Only a verified absent TUI in background mode may load saved state.
            target['resume_policy'] = 'same_thread' if mode == 'background' and route == 'background' else 'hold'
            target['startup_policy'] = 'background_saved'
            selected = self.adapter.resolve(target)
            if selected.runtime != 'codex' or selected.session_id != recipient.session_id:
                raise RuntimeTargetError('unavailable', 'resolved_recipient_changed')
            observed = self.adapter.observe(selected)
            self._selected[recipient.session_id] = (selected, route, observed.resumed)
            return self._capabilities(observed, route)
        except RuntimeTargetError as exc:
            return RuntimeObservation(exc.state, exc.reason, {})
        except Exception:
            return RuntimeObservation('unavailable', 'recipient_ownership_unknown', {})

    def submit(self, recipient, prompt):
        if recipient.binding.get('session_mode') is None:
            return self.adapter.submit(recipient, prompt)
        if recipient.binding.get('session_mode') == 'session_only':
            from .wake_session_modes import session_state
            state = session_state(recipient.binding)
            if state != 'live':
                return RuntimeSubmission('not_sent', reason='session_closed' if state == 'closed' else 'session_owner_unverified', pre_io=True)
        selected = self._selected.get(recipient.session_id)
        if selected is None:
            return RuntimeSubmission('not_sent', reason='mode_route_not_observed', pre_io=True)
        routed, route, resumed = selected
        try:
            current = self._presence(routed.binding, resumed=resumed)
            if current != ('existing_tab' if route == 'new_tab' else route):
                return RuntimeSubmission('not_sent', reason='recipient_ownership_changed', pre_io=True)
            # No resume on the final check: opening a TUI never starts another turn.
            recheck = self.adapter.resolve(dict(routed.binding, resume_policy='hold'))
            if self.adapter.observe(recheck).state != 'ready':
                return RuntimeSubmission('not_sent', reason='recipient_busy_or_unavailable', pre_io=True)
        except Exception:
            return RuntimeSubmission('not_sent', reason='recipient_ownership_unknown', pre_io=True)
        if route == 'background':
            from .native_protocol import native_request
            try:
                response = native_request(routed.binding['endpoint'], routed.binding['codex_cmd'],
                    'turn/start', {'threadId': recipient.session_id,
                                   'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]}, 30)
                turn = response.get('turn', {})
                turn_id = turn.get('id')
                if (not isinstance(turn_id, str) or not turn_id or len(turn_id) > 256
                        or response.get('threadId', recipient.session_id) != recipient.session_id):
                    raise RuntimeTargetError('unavailable', 'background_turn_acceptance_unverified')
                return RuntimeSubmission('accepted', receipt_id=turn_id,
                    evidence_kind='native_turn_acceptance', evidence=dict(source='native_turn', thread_id=recipient.session_id, turn_id=turn_id))
            except Exception:
                return RuntimeSubmission('uncertain', reason='background_turn_acceptance_unverified')
        return self.adapter.submit(routed, prompt)

    def submit_bounded(self, recipient, prompt, envelope):
        # Bounded pending input must never use the background turn/start route.
        from .runtime_delivery import submit_bounded
        from .runtime_policies import native_delivery_ready
        if recipient.binding.get('session_mode') is None:
            return submit_bounded(self.adapter, recipient, prompt, envelope)
        if recipient.binding.get('session_mode') == 'session_only':
            from .wake_session_modes import session_state
            state = session_state(recipient.binding)
            if state != 'live':
                return RuntimeSubmission('not_sent', reason='session_closed' if state == 'closed' else 'session_owner_unverified', pre_io=True)
        selected = self._selected.get(recipient.session_id)
        if selected is None:
            return RuntimeSubmission('not_sent', reason='mode_route_not_observed', pre_io=True)
        routed, route, resumed = selected
        try:
            if self._presence(routed.binding, resumed=resumed) != ('existing_tab' if route == 'new_tab' else route):
                return RuntimeSubmission('not_sent', reason='recipient_ownership_changed', pre_io=True)
            recheck = self.adapter.resolve(dict(routed.binding, resume_policy='hold'))
            if not native_delivery_ready(routed.binding, self.adapter.observe(recheck)):
                return RuntimeSubmission('not_sent', reason='recipient_busy_or_unavailable', pre_io=True)
        except Exception:
            return RuntimeSubmission('not_sent', reason='recipient_ownership_unknown', pre_io=True)
        return submit_bounded(self.adapter, routed, prompt, envelope)

    def reconcile_bounded(self, recipient, prompt, envelope):
        from .runtime_delivery import RuntimeReconciliation
        method = getattr(self.adapter, 'reconcile_bounded', None)
        return method(recipient, prompt, envelope) if method else RuntimeReconciliation(None, 'bounded_native_backend_not_qualified')

    def reconcile(self, recipient, prompt):
        # Reconciliation never restores a tab, resumes a thread, or submits work.
        return self.adapter.reconcile(recipient, prompt)


def _terminal_evidence(evidence):
    return (isinstance(evidence, dict) and evidence.get('source') == 'native_turn'
        and evidence.get('execution') in ('turn_completed', 'turn_failed', 'turn_interrupted')
        and all(isinstance(evidence.get(key), str) and 0 < len(evidence[key]) <= 4096
                for key in ('turn_id', 'user_message_id', 'client_message_id')))


def _terminal_receipt(root, peer, evidence=None):
    """Retain a verified past fact bound to its original submission, never a grant."""
    import hashlib
    import json
    from .wake_policy import _read, _write
    from .records import WakeError
    delivery = peer['native_delivery']
    binding = dict(wake_id=peer['id'], target=peer['target'],
                   submission_id=delivery.get('submission_id'), prompt_sha256=delivery.get('prompt_sha256'))
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    path = Path(root) / 'terminal-wake-evidence' / (digest + '.json')
    if evidence is not None:
        compact = {key:evidence[key] for key in ('source', 'execution', 'turn_id', 'user_message_id', 'client_message_id')}
        _write(path, dict(version=1, binding_sha256=digest, evidence=compact))
        return compact
    if _terminal_evidence(delivery.get('evidence')):
        return delivery['evidence']
    try:
        value = _read(path)
        if value.get('version') == 1 and value.get('binding_sha256') == digest and _terminal_evidence(value.get('evidence')):
            return value['evidence']
    except (WakeError, OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def _peer_records(root, deadline):
    """Read lazily so local history traversal shares the admission deadline."""
    import json
    import time
    from .records import ACTIVE_STATUS_DIRS
    for status in (*ACTIVE_STATUS_DIRS, 'archive'):
        for path in (Path(root) / status).glob('*.json'):
            if time.monotonic() >= deadline:
                raise RuntimeTargetError('unavailable', 'peer_history_deadline')
            with path.open() as source:
                raw = source.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise RuntimeTargetError('unavailable', 'peer_history_unavailable')
            value = json.loads(raw)
            if isinstance(value, dict):
                yield value


def _peer_read_target(original, current):
    """Use current read transport only for a removed historical CLI, not input."""
    import os
    import stat
    try:
        Path(original['codex_cmd']).stat()
        return original
    except FileNotFoundError:
        pass
    replacement = Path(current['codex_cmd'])
    info = replacement.stat()
    if (not replacement.is_absolute() or not stat.S_ISREG(info.st_mode)
            or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022
            or not os.access(replacement, os.X_OK)):
        raise RuntimeTargetError('unavailable', 'peer_read_transport_unqualified')
    # Endpoint and exact conversation were compared by the caller. No saved
    # target, submission, policy, prompt or terminal binding is rewritten.
    return dict(original, codex_cmd=str(replacement))


def registration_harness_readiness(root, record):
    """Read only: never resume/load a conversation or submit a native turn."""
    import time
    from .native_protocol import native_request
    target = record['target']
    try:
        response = native_request(target['endpoint'], target['codex_cmd'],
            'thread/read', dict(threadId=target['thread_id'], includeTurns=False), 5)
        thread = response.get('thread', {})
        if thread.get('id') != target['thread_id']:
            return dict(state='unavailable', reason='recipient_identity_unverified')
        if thread.get('status', {}).get('type') not in ('idle', 'active', 'notLoaded'):
            return dict(state='unavailable', reason='recipient_state_unverified')
        from .runtime_delivery import bounded_nonadmitted_terminal
        for peer in _peer_records(root, time.monotonic() + 5):
            other = peer.get('target', {})
            if (peer.get('id') != record['id'] and other.get('transport') == 'native'
                    and other.get('thread_id') == target['thread_id']
                    and other.get('endpoint') == target['endpoint']
                    and peer.get('native_delivery', {}).get('state') in ('accepted', 'uncertain')
                    and not bounded_nonadmitted_terminal(peer)
                    and _terminal_receipt(root, peer) is None):
                return dict(state='held', reason='peer_history_reconciliation_required')
        return dict(state='ready', reason='exact_native_read_verified',
                    recipient_state=thread['status']['type'])
    except Exception:
        return dict(state='unavailable', reason='native_harness_read_unavailable')


def _pending_peer(root, record, adapter):
    import time
    from .native_delivery import native_prompt
    target = record['target']
    background_owned = False
    deadline = time.monotonic() + 5
    remote_reads = 0
    try:
        for peer in _peer_records(root, deadline):
            other = peer.get('target', {})
            if peer.get('id') == record['id'] or other.get('thread_id') != target['thread_id']:
                continue
            if other.get('transport') != 'native' or other.get('endpoint') != target['endpoint']:
                continue
            from .runtime_delivery import bounded_nonadmitted_terminal
            if bounded_nonadmitted_terminal(peer):
                continue
            delivery = peer.get('native_delivery', {})
            if delivery.get('state') not in ('accepted', 'uncertain'):
                continue
            evidence = _terminal_receipt(root, peer)
            if evidence is None:
                if remote_reads >= 1 or time.monotonic() >= deadline:
                    return True, background_owned
                remote_reads += 1
                recipient = adapter.resolve(_peer_read_target(other, target))
                from .runtime_delivery import reconcile_submission
                evidence = reconcile_submission(adapter, recipient, native_prompt(root, peer), peer).evidence
                if recipient.runtime != 'codex' or recipient.session_id != target['thread_id'] or not _terminal_evidence(evidence):
                    return True, background_owned
                _terminal_receipt(root, peer, evidence)
            background_owned = (background_owned or delivery.get('route') == 'background'
                or other.get('session_mode') == 'background' and bool(delivery.get('turn_id')))
    except Exception:
        raise RuntimeTargetError('unavailable', 'peer_reconciliation_unavailable') from None
    return False, background_owned


def guard_mode_dispatch(function):
    """Serialize check admission; peer receipt uncertainty fences further work."""
    @wraps(function)
    def guarded(root, found, now, *, clock_provider=None, runtime_adapter=None):
        record = found.record
        target = record.get('target', {})
        if not target.get('session_mode'):
            return function(root, found, now, clock_provider=clock_provider, runtime_adapter=runtime_adapter)
        from .injector import DispatchResult
        from .native_delivery import _codex_adapter
        from .native_intents import schedule_projection
        base = runtime_adapter or _codex_adapter()
        with WakeLifecycleLock(root, 'native-conversation:' + target['endpoint'] + ':' + target['thread_id']):
            from .wake_session_modes import apply_session_mode
            checked = dict(record)
            reason = apply_session_mode(checked)
            if reason:
                replace_record(root, found, checked)
                return DispatchResult('skipped' if checked['status'] == 'cancelled' else 'requeued', reason)
            try:
                pending, background_owned = _pending_peer(root, record, base) if record.get('native_delivery', {}).get('state') != 'uncertain' else (False, False)
            except RuntimeTargetError:
                held = dict(record, status='pending', policy_outcome=dict(state='held', reason='peer_reconciliation_unavailable'))
                replace_record(root, found, held)
                return DispatchResult('requeued', 'peer_reconciliation_unavailable')
            if pending:
                held = dict(record, status='pending', policy_outcome=dict(state='held', reason='conversation_check_in_progress'))
                replace_record(root, found, held)
                return DispatchResult('requeued', 'conversation_check_in_progress')
            adapter = ModeRuntimeAdapter(root, base,
                permission_context=record.get('wake_policy', {}).get('permission_context'),
                expires_at=schedule_projection(record).get('expires_at'), occurrence_id=record['id'],
                background_owned=background_owned)
            return function(root, found, now, clock_provider=clock_provider, runtime_adapter=adapter)
    return guarded
