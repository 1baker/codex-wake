"""Experimental bounded queue wire adapter, with no production qualification.

Only a host-owned qualified runtime may inject this into CodexRuntimeAdapter.
No RPC capability response or caller flag enables it. Pending is queue acceptance,
not observed delivery; admitted is permission to inspect the exact native turn,
not completion. Cancellation inspects the original envelope before deleting its exact row.
"""
from uuid import UUID

from .records import WakeError
from .bounded_native_qualification import BoundedNativePreIORefusal
from .runtime_delivery import RuntimeReconciliation, RuntimeSubmission


class BoundedNativeAdapter:
    def __init__(self, *, request, qualification=None):
        self._request = request
        self._qualification = qualification

    def capability(self, recipient):
        from .runtime_delivery import RuntimeCapability
        if self._qualification is None:
            return RuntimeCapability('not_qualified', 'bounded_native_backend_not_qualified')
        return self._qualification(recipient)

    @staticmethod
    def _input(prompt):
        return [dict(type='text', text=prompt, text_elements=[])]

    def _inspect(self, response, prompt, envelope):
        if not isinstance(response, dict):
            raise WakeError('bounded native inspection unavailable')
        state = response.get('state')
        if state not in ('pending', 'canceled', 'expired', 'admitted', 'notFound', 'ambiguous'):
            raise WakeError('bounded native state unavailable')
        if state in ('notFound', 'ambiguous'):
            return state, None
        queued = response.get('queuedSubmission')
        if (not isinstance(queued, dict)
                or queued.get('clientUserMessageId') != envelope.client_user_message_id
                or type(queued.get('expiresAtUnixMicros')) is not int
                or queued['expiresAtUnixMicros'] != envelope.expires_at_unix_micros
                or queued.get('input') != self._input(prompt)):
            raise WakeError('bounded native original envelope changed')
        UUID(queued.get('id'))
        if state == 'admitted':
            import math
            clock = response.get('clockEvidence')
            authority = clock.get('authority') if isinstance(clock, dict) else None
            counter = authority.get('counter') if isinstance(authority, dict) else None
            if (not isinstance(clock, dict)
                    or any(type(clock.get(key)) not in (int, float) or not math.isfinite(clock[key]) for key in ('lower', 'upper'))
                    or clock['lower'] > clock['upper']
                    or not isinstance(authority, dict)
                    or type(authority.get('contract_version')) is not int
                    or authority['contract_version'] not in (1, 2)
                    or (authority['contract_version'] == 2 and (
                        authority.get('basis') != 'service_measurement'
                        or authority.get('receipt_time_bound') is not False
                        or authority.get('counter_source') != dict(kind='stable_time_service_measurement')))
                    or authority.get('state') != 'qualified'
                    or any(type(authority.get(key)) not in (int, float) or not math.isfinite(authority[key]) for key in ('lower', 'upper'))
                    or authority['lower'] > authority['upper']
                    or any(not math.nextafter(clock[key], -math.inf) <= authority[key] <= math.nextafter(clock[key], math.inf) for key in ('lower', 'upper'))
                    or not isinstance(counter, dict)
                    or any(type(counter.get(key)) is not int or not 0 <= counter[key] < 2**64 for key in ('counter', 'frequency', 'rate_ppm'))
                    or counter['frequency'] == 0 or counter['rate_ppm'] > 5000
                    or not isinstance(response.get('turnId'), str) or not response['turnId']):
                raise WakeError('bounded admission evidence unavailable')
            # Duplicate persisted JSON bounds may differ by one representable f64.
            # Use the larger upper bound and round outward, never into eligibility.
            upper_micros = max(clock['upper'], authority['upper']) * 1_000_000
            if not math.isfinite(upper_micros) or math.ceil(upper_micros) >= envelope.expires_at_unix_micros:
                raise WakeError('bounded admission evidence unavailable')
            UUID(counter.get('epoch'))
        return state, queued

    def _read(self, recipient, prompt, envelope, *, add=False):
        params = dict(threadId=recipient.session_id, clientUserMessageId=envelope.client_user_message_id)
        if add:
            params.update(input=self._input(prompt), expiresAtUnixMicros=envelope.expires_at_unix_micros)
        target = recipient.binding
        response = self._request(target['endpoint'], target['codex_cmd'],
            'thread/queue/bounded/' + ('add' if add else 'read'), params, 10)
        # Native v2 has distinct response DTOs: add returns the retained row;
        # read wraps its stateful observation under inspection.
        inspection = dict(state='pending', queuedSubmission=response.get('queuedSubmission')) if add else response.get('inspection')
        state, queued = self._inspect(inspection, prompt, envelope)
        return state, queued, inspection

    def submit_bounded(self, recipient, prompt, envelope):
        try:
            state, queued, _ = self._read(recipient, prompt, envelope, add=True)
            if state in ('pending', 'admitted'):
                return RuntimeSubmission('accepted', receipt_id=queued['id'], evidence_kind='native_queue_acceptance')
            return RuntimeSubmission('uncertain', reason='bounded_native_' + state)
        except BoundedNativePreIORefusal:
            return RuntimeSubmission('not_sent', reason='bounded_native_backend_not_qualified', pre_io=True)
        except Exception:
            # A timeout or malformed response never authorizes an unbounded retry.
            return RuntimeSubmission('uncertain', reason='bounded_native_acceptance_unconfirmed')

    def reconcile_bounded(self, recipient, prompt, envelope):
        try:
            state, queued, response = self._read(recipient, prompt, envelope)
        except BoundedNativePreIORefusal:
            return RuntimeReconciliation(None, 'bounded_native_backend_not_qualified')
        if state != 'admitted':
            return RuntimeReconciliation(None, 'bounded_native_' + state)
        return RuntimeReconciliation(dict(source='bounded_native_admission',
            turn_id=response['turnId'], queue_id=queued['id'],
            client_message_id=envelope.client_user_message_id, execution='not_observed'))

    def cancel_bounded(self, recipient, prompt, envelope, queue_id=None):
        try:
            state, queued, _ = self._read(recipient, prompt, envelope)
        except BoundedNativePreIORefusal:
            return RuntimeReconciliation(None, 'bounded_native_backend_not_qualified')
        if queue_id is not None and queued is not None and queued['id'] != queue_id:
            raise WakeError('bounded native queue identity changed')
        if state != 'pending':
            return RuntimeReconciliation(None, 'bounded_native_' + state)
        target = recipient.binding
        response = self._request(target['endpoint'], target['codex_cmd'],
            'thread/queue/bounded/delete', dict(threadId=recipient.session_id,
                queuedSubmissionId=queued['id']), 10)
        state, retained = self._inspect(response.get('inspection'), prompt, envelope)
        if retained is not None and retained['id'] != queued['id']:
            raise WakeError('bounded native queue identity changed')
        return RuntimeReconciliation(None, 'bounded_native_' + state)
