"""Runtime delivery values; scheduling and durable attempts stay in the core.

Version 1 is an in-memory interface, not a new persisted wake-record schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol


CapabilityState = Literal["supported", "unsupported", "not_qualified", "unavailable"]


class RuntimeTargetError(ValueError):
    def __init__(self, state: str, reason: str):
        super().__init__(reason)
        self.state = state
        self.reason = reason


@dataclass(frozen=True)
class RuntimeRecipient:
    runtime: str
    session_id: str
    binding: Mapping[str, object] = field(repr=False)
    version: int = 1


@dataclass(frozen=True)
class RuntimeCapability:
    state: CapabilityState
    reason: str


@dataclass(frozen=True)
class RuntimeObservation:
    state: str
    reason: str
    capabilities: Mapping[str, RuntimeCapability]
    resumed: bool = False
    native_status: dict | None = None

    def summary(self, recipient: RuntimeRecipient) -> dict:
        # Do not expose opaque binding data, socket paths or credentials here.
        result = dict(
            version=recipient.version, runtime=recipient.runtime,
            session_id=recipient.session_id, state=self.state, reason=self.reason,
            capabilities={name: dict(state=value.state, reason=value.reason)
                          for name, value in self.capabilities.items()},
        )
        if self.native_status is not None:
            result['native_status'] = self.native_status
        return result


@dataclass(frozen=True)
class RuntimeSubmissionEnvelope:
    """Original durable client identity and absolute expiry; never a new lease."""
    client_user_message_id: str
    expires_at_unix_micros: int

    def __post_init__(self):
        from uuid import UUID
        UUID(self.client_user_message_id)
        if type(self.expires_at_unix_micros) is not int or not 0 < self.expires_at_unix_micros <= 2**63 - 1:
            raise ValueError('invalid original native expiry')


@dataclass(frozen=True)
class RuntimeSubmission:
    state: Literal["accepted", "uncertain", "not_sent"]
    receipt_id: str | None = None
    evidence_kind: str = "none"
    reason: str | None = None
    failure: dict | None = None
    exception_type: str | None = None
    evidence: dict | None = None
    # True only when the adapter proves no submission I/O was attempted.
    pre_io: bool = False


@dataclass(frozen=True)
class RuntimeReconciliation:
    evidence: dict | None = None
    reason: str | None = None


class RuntimeAdapter(Protocol):
    def resolve(self, target: Mapping[str, object]) -> RuntimeRecipient: ...
    def observe(self, recipient: RuntimeRecipient) -> RuntimeObservation: ...
    def submit(self, recipient: RuntimeRecipient, prompt: str) -> RuntimeSubmission: ...
    def reconcile(self, recipient: RuntimeRecipient, prompt: str) -> RuntimeReconciliation: ...
    def submit_bounded(self, recipient: RuntimeRecipient, prompt: str, envelope: RuntimeSubmissionEnvelope) -> RuntimeSubmission: ...
    def reconcile_bounded(self, recipient: RuntimeRecipient, prompt: str, envelope: RuntimeSubmissionEnvelope) -> RuntimeReconciliation: ...


def validate_native_submission(submitted, thread_id, *, allow_background=False):
    """Validate receipt identity consistently on permissioned and legacy routes."""
    from uuid import UUID
    from .records import WakeError
    if not isinstance(submitted, RuntimeSubmission):
        raise WakeError('invalid runtime submission outcome')
    if submitted.state != 'accepted':
        return
    if submitted.evidence_kind == 'native_queue_acceptance':
        UUID(submitted.receipt_id)
        return
    evidence = submitted.evidence
    if (allow_background and submitted.evidence_kind == 'native_turn_acceptance'
            and isinstance(submitted.receipt_id, str) and 0 < len(submitted.receipt_id) <= 256
            and isinstance(evidence, dict) and evidence.get('source') == 'native_turn'
            and evidence.get('thread_id') == thread_id and evidence.get('turn_id') == submitted.receipt_id):
        return
    raise WakeError('runtime evidence does not confirm native acceptance')


def original_submission_expiry(record):
    """Project the original deadline without selecting any current clock."""
    from datetime import UTC, datetime
    from .records import WakeError
    from .network_wakes import precise_deadline
    if record.get('scheduling_intent'):
        from .native_intents import schedule_projection
        expiry = schedule_projection(record).get('expires_at')
        stop = record['scheduling_intent'].get('stop_at')
    else:
        expiry = record.get('target', {}).get('expires_at')
        stop = record.get('stop_at')
    if not expiry:
        raise WakeError('bounded_native_absolute_expiry_unavailable')
    deadline = precise_deadline(expiry)
    if stop:
        deadline = min(deadline, precise_deadline(stop))
    elapsed = deadline - datetime(1970, 1, 1, tzinfo=UTC)
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def submission_envelope(record):
    delivery = record['native_delivery']
    return RuntimeSubmissionEnvelope(delivery['submission_id'], delivery['expires_at_unix_micros'])


def submit_bounded(adapter, recipient, prompt, envelope):
    method = getattr(adapter, 'submit_bounded', None)
    if method is None:
        return RuntimeSubmission('not_sent', reason='bounded_native_backend_not_qualified', pre_io=True)
    return method(recipient, prompt, envelope)


def reconcile_submission(adapter, recipient, prompt, record):
    # Historical attempts lacking the persisted bounded discriminator are read
    # through their original reconciliation contract. Never migrate or resend.
    if 'expires_at_unix_micros' not in record.get('native_delivery', {}):
        return adapter.reconcile(recipient, prompt)
    method = getattr(adapter, 'reconcile_bounded', None)
    if method is None:
        return RuntimeReconciliation(None, 'bounded_native_backend_not_qualified')
    return method(recipient, prompt, submission_envelope(record))


def bounded_nonadmitted_terminal(record):
    """An exact bounded inspection, distinct from a completed native turn."""
    delivery = record.get('native_delivery', {})
    reconciliation = delivery.get('reconciliation', {})
    return (type(delivery.get('expires_at_unix_micros')) is int
            and delivery['expires_at_unix_micros'] > 0
            and reconciliation.get('state') == 'resolved'
            and (record.get('status'), reconciliation.get('reason')) in (
                ('expired', 'bounded_native_expired'), ('cancelled', 'bounded_native_canceled')))
