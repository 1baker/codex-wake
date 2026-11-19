"""Codex-specific delivery semantics behind the runtime interface."""
from __future__ import annotations

import os
import re
import subprocess
import time
from types import MappingProxyType
from uuid import UUID

from .records import WakeError
from .runtime_delivery import (
    RuntimeCapability, RuntimeObservation, RuntimeRecipient, RuntimeReconciliation,
    RuntimeSubmission, RuntimeTargetError,
)


def read_codex_thread(target):
    from .shared_app_server import SharedAppServerReader, locate_shared_endpoint
    endpoint = target['endpoint']
    if endpoint == 'unix://':
        endpoint = locate_shared_endpoint(codex_cmd=target['codex_cmd'])
    with SharedAppServerReader(endpoint) as reader:
        return reader.read_thread(target['thread_id'])


def submission_failure(reason, result, error):
    """Project subprocess evidence without retaining arbitrary output or argv."""
    def output_summary(value, *, inspect=False):
        value = value if isinstance(value, (str, bytes)) else ''
        sample = value[:4096]
        if isinstance(sample, bytes):
            sample = sample.decode('utf-8', errors='replace')
        hints = []
        if inspect:
            lowered = sample.lower()
            for phrase, hint in (
                ('thread not found', 'thread_not_found'),
                ('connection refused', 'connection_refused'),
                ('permission denied', 'permission_denied'),
                ('unauthorized', 'unauthorized'),
                ('unexpected argument', 'cli_usage_error'),
                ('timed out', 'timed_out'),
            ):
                if phrase in lowered:
                    hints.append(hint)
        return dict(length=len(value), length_unit='bytes' if isinstance(value, bytes) else 'characters',
                    truncated=len(value) > 4096, hints=hints, raw_output='withheld')
    source = result if result is not None else error
    return dict(version=1, reason=reason, exception_type=type(error).__name__,
                returncode=result.returncode if result is not None else None,
                stdout=output_summary(getattr(source, 'stdout', None)),
                stderr=output_summary(getattr(source, 'stderr', None), inspect=True))

class CodexRuntimeAdapter:
    def __init__(self, *, read_thread, request, run, project_failure, monotonic=None, busy_policy="wait", bounded_adapter=None):
        self._bounded_adapter = bounded_adapter
        self.busy_policy = busy_policy
        self._read_thread = read_thread
        self._request = request
        self._run = run
        self._project_failure = project_failure
        self._clock = monotonic  # Injectable advisory transport clock; no expiry authority.

    def resolve(self, target) -> RuntimeRecipient:
        if target.get("transport") != "native" or target.get("runtime", "codex") != "codex":
            raise RuntimeTargetError("unsupported", "unsupported_runtime_target")
        if not all(isinstance(target.get(key), str) and target[key]
                   for key in ("thread_id", "endpoint", "codex_cmd")):
            raise RuntimeTargetError("unavailable", "incomplete_runtime_target")
        return RuntimeRecipient("codex", target["thread_id"], MappingProxyType(dict(target)))

    def observe(self, recipient: RuntimeRecipient) -> RuntimeObservation:
        target = recipient.binding
        capabilities = {
            "submit": RuntimeCapability("supported", "native_queue_acceptance"),
            "reconcile": RuntimeCapability("supported", "exact_native_evidence"),
            "saved_resume": RuntimeCapability("supported", "explicit_same_thread_policy"),
            "busy_queue": RuntimeCapability("not_qualified", "dequeue_deadline_not_qualified"),
            "interrupt": RuntimeCapability("unsupported", "not_implemented_by_delivery_adapter"),
            "terminal_input": RuntimeCapability("unsupported", "not_this_delivery_method"),
            "receiver_acknowledgment": RuntimeCapability("not_qualified", "queue_is_not_receiver_ack"),
        }
        if self._bounded_adapter is not None:
            try:
                capabilities['busy_queue'] = self._bounded_adapter.capability(recipient)
            except Exception:
                capabilities['busy_queue'] = RuntimeCapability('not_qualified', 'bounded_native_backend_not_qualified')
        if target.get('startup_policy') == 'active_tab':
            from .sessions import observe
            try:
                endpoint = target['endpoint']
                if endpoint == 'unix://':
                    from .shared_app_server import locate_shared_endpoint
                    endpoint = locate_shared_endpoint(codex_cmd=target['codex_cmd'], timeout=5)
                snapshot = observe(endpoint=endpoint, timeout=5)
                matches = [row for row in snapshot['sessions'] if row.get('thread_id') == recipient.session_id]
                active = (snapshot.get('complete') and len(matches) == 1
                          and matches[0].get('binding_status') == 'metadata_matched'
                          and len(matches[0].get('attachments', [])) == 1)
                capabilities['active_tab'] = RuntimeCapability('supported' if active else 'unavailable',
                                                              'exact_metadata_attachment' if active else 'active_attachment_unavailable')
            except Exception:
                capabilities['active_tab'] = RuntimeCapability('unavailable', 'active_attachment_unavailable')
        resumed = False
        try:
            thread = self._read_thread(target)
            if (thread.get("id") == recipient.session_id
                    and thread.get("status", {}).get("type") == "notLoaded"
                    and target.get("resume_policy") == "same_thread"):
                response = self._request(
                    target["endpoint"], target["codex_cmd"], "thread/resume",
                    {"threadId": recipient.session_id}, 10,
                )
                if response.get("thread", {}).get("id") != recipient.session_id:
                    raise WakeError("native resume returned a different thread")
                resumed = True
                thread = self._read_thread(target)
            if thread.get("id") != recipient.session_id:
                return RuntimeObservation("unavailable", "recipient_identity_changed", capabilities, resumed)
            state = thread.get("status", {}).get("type")
            if state == "idle":
                return RuntimeObservation("ready", "recipient_idle", capabilities, resumed)
            if state == "active":
                return RuntimeObservation("busy", "recipient_busy", capabilities, resumed)
            return RuntimeObservation("unavailable", "recipient_not_loaded_or_unknown", capabilities, resumed)
        except Exception:
            return RuntimeObservation("unavailable", "runtime_observation_unavailable", capabilities, resumed)

    def submit_bounded(self, recipient, prompt, envelope):
        # Host qualification must be rechecked on the submission connection.
        if self._bounded_adapter is None:
            return RuntimeSubmission('not_sent', reason='bounded_native_backend_not_qualified', pre_io=True)
        return self._bounded_adapter.submit_bounded(recipient, prompt, envelope)

    def reconcile_bounded(self, recipient, prompt, envelope):
        if self._bounded_adapter is None:
            return RuntimeReconciliation(None, 'bounded_native_backend_not_qualified')
        observed = self._bounded_adapter.reconcile_bounded(recipient, prompt, envelope)
        admission = observed.evidence
        if admission is None or admission.get('source') != 'bounded_native_admission':
            return observed
        exact = self.reconcile(recipient, prompt)
        evidence = exact.evidence
        if (not isinstance(evidence, dict) or evidence.get('source') != 'native_turn'
                or evidence.get('turn_id') != admission['turn_id']
                or evidence.get('client_message_id') != envelope.client_user_message_id):
            return RuntimeReconciliation(None, 'bounded_native_admitted_execution_unconfirmed')
        return exact

    def cancel_bounded(self, recipient, prompt, envelope, queue_id=None):
        if self._bounded_adapter is None:
            return RuntimeReconciliation(None, 'bounded_native_backend_not_qualified')
        return self._bounded_adapter.cancel_bounded(recipient, prompt, envelope, queue_id)

    def submit(self, recipient: RuntimeRecipient, prompt: str) -> RuntimeSubmission:
        if self.busy_policy != "wait":
            return RuntimeSubmission("not_sent", reason="busy_policy_unsupported", pre_io=True)
        target = recipient.binding
        env = dict(os.environ)
        for key in ("CODEX_THREAD_ID", "TMUX", "TMUX_PANE"):
            env.pop(key, None)
        result = None
        reason = "queue_command_exception"
        try:
            remote = ["--remote", target["endpoint"]] if target["endpoint"] != "unix://" else []
            result = self._run(
                [target["codex_cmd"], "queue", *remote, "--thread", recipient.session_id,
                 "--message", prompt],
                env=env, capture_output=True, text=True, timeout=30,
            )
            match = re.fullmatch(
                r"Queued message ([0-9a-f-]{36}) for thread "
                + re.escape(recipient.session_id) + r"\.\s*", result.stdout,
            )
            if result.returncode or match is None:
                reason = "queue_exit_nonzero" if result.returncode else "queue_acceptance_unconfirmed"
                raise WakeError("native queue did not confirm exact acceptance")
            reason = "queue_acceptance_unconfirmed"
            UUID(match[1])
            return RuntimeSubmission(
                "accepted", receipt_id=match[1], evidence_kind="native_queue_acceptance",
            )
        except Exception as exc:
            if isinstance(exc, subprocess.TimeoutExpired):
                reason = "queue_timeout"
            elif isinstance(exc, OSError):
                reason = "queue_os_error"
            return RuntimeSubmission(
                "uncertain", reason=reason, exception_type=type(exc).__name__,
                failure=self._project_failure(reason, result, exc),
            )

    def reconcile(self, recipient: RuntimeRecipient, prompt: str) -> RuntimeReconciliation:
        """Observe only this session and return receipt identities, never bodies."""
        target = recipient.binding
        # One advisory RPC budget, retained across queue/history pagination.
        clock = self._clock if self._clock is not None else time.monotonic
        end = clock() + 10

        def remaining_budget():
            return end - clock()

        def request(method, params):
            remaining = remaining_budget()
            if remaining <= 0:
                raise WakeError("native reconciliation observation timed out")
            response = self._request(target["endpoint"], target["codex_cmd"], method, params, remaining)
            if remaining_budget() <= 0:
                raise WakeError("native reconciliation observation timed out")
            return response

        def exact(items):
            return (isinstance(items, list) and len(items) == 1
                    and items[0].get("type") == "text" and items[0].get("text") == prompt)

        evidence = {}
        cursor = None
        for _ in range(10):
            page = request("thread/queue/list", dict(threadId=recipient.session_id, limit=100, cursor=cursor))
            for queued in page["data"]:
                if exact(queued["input"]):
                    identity = queued.get("clientUserMessageId")
                    if (not isinstance(identity, str) or not identity
                            or not isinstance(queued.get('id'), str) or not queued['id']):
                        raise WakeError("native queue identity unavailable")
                    if identity in evidence and evidence[identity].get("queue_id") != queued["id"]:
                        return RuntimeReconciliation(None, "multiple_native_submissions")
                    evidence[identity] = dict(
                        source="native_queue", queue_id=queued["id"],
                        client_message_id=identity, execution="not_observed",
                    )
            cursor = page.get("nextCursor")
            if not cursor:
                break
        else:
            raise WakeError("native queue observation exceeded its page bound")
        from .native_protocol import NativeCapabilityUnavailable
        thread = request("thread/read", dict(threadId=recipient.session_id, includeTurns=False))["thread"]
        if thread["id"] != recipient.session_id:
            raise WakeError("native evidence returned a different thread")

        def hydrate(summary):
            # Summary pages identify candidates; only complete native items can
            # establish the receipt. Do not hydrate unrelated tool/image output.
            expected = [(item.get('id'), item.get('clientId') or item.get('id'))
                        for item in summary['items']
                        if item.get('type') == 'userMessage' and exact(item.get('content'))]
            items = []
            cursor = None
            cursors = set()
            identifiers = set()
            for _ in range(128):
                params = dict(threadId=recipient.session_id, turnId=summary['id'],
                              limit=100, sortDirection='asc',
                              deferOutput=dict(commandExecution=True, mcpToolCall=True))
                if cursor is not None:
                    params['cursor'] = cursor
                page = request('thread/items/list', params)
                if (not isinstance(page, dict) or not isinstance(page.get('data'), list)
                        or 'nextCursor' not in page):
                    raise WakeError('native item page incomplete')
                for entry in page['data']:
                    item = entry.get('item') if isinstance(entry, dict) else None
                    identifier = item.get('id') if isinstance(item, dict) else None
                    if (not isinstance(entry, dict) or entry.get('turnId') != summary['id'] or not isinstance(identifier, str)
                            or not identifier or identifier in identifiers):
                        raise WakeError('native item identity ambiguous')
                    identifiers.add(identifier)
                    items.append(item)
                cursor = page['nextCursor']
                if cursor is None:
                    actual = [(item.get('id'), item.get('clientId') or item.get('id'))
                              for item in items
                              if item.get('type') == 'userMessage' and exact(item.get('content'))]
                    if actual != expected:
                        raise WakeError('native summary and full message identity differ')
                    return dict(summary, items=items, itemsView='full')
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise WakeError('native item cursor ambiguous')
                cursors.add(cursor)
            raise WakeError('native item observation exceeded its page bound')

        def turns():
            cursor = None
            seen_cursors = set()
            seen_turns = set()

            def checked(turn, *, legacy=False):
                identifier = turn.get('id') if isinstance(turn, dict) else None
                if (not isinstance(identifier, str) or not identifier or identifier in seen_turns
                        or turn.get('itemsView', 'full' if legacy else None) not in ('full', 'summary')
                        or turn.get('status') not in ('completed', 'failed', 'interrupted', 'inProgress')
                        or not isinstance(turn.get('items'), list)):
                    raise WakeError("native history identity or items ambiguous")
                seen_turns.add(identifier)
                return turn

            for index in range(128):
                params = dict(threadId=recipient.session_id, limit=16,
                              sortDirection="desc", itemsView="summary")
                if cursor is not None:
                    params['cursor'] = cursor
                try:
                    page = request("thread/turns/list", params)
                except NativeCapabilityUnavailable:
                    if index:
                        raise
                    # Explicitly older native servers retain the original read
                    # contract. Malformed, incomplete, or failed pages never
                    # authorize fallback or renewal of the observation budget.
                    legacy = request("thread/read", dict(threadId=recipient.session_id, includeTurns=True))["thread"]
                    if legacy.get('id') != recipient.session_id or not isinstance(legacy.get('turns'), list):
                        raise WakeError("native legacy history identity unavailable")
                    for turn in legacy['turns']:
                        turn = checked(turn, legacy=True)
                        if turn.get('itemsView', 'full') != 'full':
                            raise WakeError('native legacy history items incomplete')
                        yield turn
                    return
                if (not isinstance(page, dict) or not isinstance(page.get('data'), list)
                        or 'nextCursor' not in page):
                    raise WakeError("native history page incomplete")
                for turn in page['data']:
                    turn = checked(turn)
                    if turn['itemsView'] == 'summary':
                        if not any(item.get('type') == 'userMessage' and exact(item.get('content'))
                                   for item in turn['items'] if isinstance(item, dict)):
                            continue
                        turn = hydrate(turn)
                    yield turn
                cursor = page['nextCursor']
                if cursor is None:
                    return
                if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                    raise WakeError("native history cursor ambiguous")
                seen_cursors.add(cursor)
            raise WakeError("native history observation exceeded its page bound")

        for turn in turns():
            for item in turn["items"]:
                if item.get("type") == "userMessage" and exact(item.get("content")):
                    identity = item.get("clientId")
                    if identity is None:
                        identity = item.get("id")
                    if (not isinstance(item.get('id'), str) or not item['id']
                            or not isinstance(identity, str) or not identity):
                        raise WakeError("native message identity unavailable")
                    previous = evidence.get(identity, {})
                    if previous.get("source") == "native_turn" and (
                            previous["turn_id"] != turn["id"] or previous["user_message_id"] != item["id"]):
                        return RuntimeReconciliation(None, "multiple_native_submissions")
                    outputs = [entry for entry in turn['items']
                        if entry.get('type') == 'agentMessage' and isinstance(entry.get('text'), str)]
                    evidence[identity] = dict(
                        previous, source="native_turn", turn_id=turn["id"],
                        user_message_id=item["id"], client_message_id=identity,
                        execution="turn_" + turn["status"],
                        output_summary=dict(
                            text_bytes=sum(len(entry['text'].encode()) for entry in outputs),
                            item_count=len(outputs),
                            item_ids=[entry.get('id') for entry in outputs[:16]],
                            locators_truncated=len(outputs) > 16,
                            coverage='Native agentMessage text only; excludes tools, reasoning and token usage.',
                            source=dict(thread_id=recipient.session_id, turn_id=turn['id']),
                            freshness='Observed with this exact native turn reconciliation',
                            ambiguity='Completion establishes execution, not acceptance of the result.'),
                    )
        if remaining_budget() <= 0:
            raise WakeError("native reconciliation observation timed out")
        if len(evidence) != 1:
            return RuntimeReconciliation(
                None, "no_exact_native_evidence" if not evidence else "multiple_native_submissions",
            )
        return RuntimeReconciliation(next(iter(evidence.values())))
