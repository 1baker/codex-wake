"""Qualified Grok1.0.40 minimal-UI delivery, with pinned managed-launch identity."""
from __future__ import annotations

import hashlib
import re
import time
from types import MappingProxyType

from . import measurements
from .records import WakeError
from .runtime_delivery import (
    RuntimeCapability, RuntimeObservation, RuntimeRecipient, RuntimeSubmission,
    RuntimeReconciliation, RuntimeTargetError,
)

GENERATION_KEYS = ('pid', 'start_ticks', 'boot_id', 'session_id', 'executable_sha256')


class GrokRuntimeAdapter:
    def __init__(self, host, *, deadline=None, busy_policy="wait", preferred_method="terminal_observation"):
        self.host = host
        self.deadline = deadline
        self.host.deadline = deadline
        self.busy_policy = busy_policy
        self.preferred_method = preferred_method

    def resolve(self, target):
        if (target.get('transport') != 'runtime' or target.get('version') != 1
                or target.get('runtime') != 'grok' or target.get('method') not in ('terminal_observation', 'native_preferred')):
            raise RuntimeTargetError('unsupported', 'unsupported_grok_target')
        binding = self.host.load_binding(target['binding_id'], target['binding_sha256'])
        if binding['session_id'] != target['session_id']:
            raise RuntimeTargetError('unavailable', 'binding_session_changed')
        return RuntimeRecipient('grok', binding['session_id'], MappingProxyType(dict(binding, _preferred_method=target['method'])))

    def _snapshot(self, recipient):
        observed = self.host.snapshot(recipient.binding)
        if any(observed.get(key) != recipient.binding.get(key) for key in GENERATION_KEYS):
            raise WakeError('grok_process_generation_changed')
        lines = [line.rstrip() for line in observed['frame'].splitlines() if line.strip()]
        versions = [line.strip() for line in lines if line.strip().startswith('Shell version:')]
        sessions = [line.strip() for line in lines if line.strip().startswith('Session ID:')]
        if (not versions or versions[-1] != 'Shell version: 1.0.40 [stable]'
                or not sessions or sessions[-1] != 'Session ID: ' + recipient.session_id):
            raise WakeError('grok_session_or_version_unavailable')
        return observed, lines

    def observe(self, recipient):
        capabilities = {
            'native_submit': RuntimeCapability('not_qualified', 'no_qualified_exact_open_native_route'),
            'terminal_fallback': RuntimeCapability(
                'supported' if recipient.binding.get('allow_terminal_fallback') is True else 'unsupported',
                'host_profile_pre_io_only' if recipient.binding.get('allow_terminal_fallback') is True else 'host_profile_required'),
            'submit': RuntimeCapability('supported', 'grok_1_0_40_minimal_terminal_observation'),
            'reconcile': RuntimeCapability('supported', 'same_generation_submission_marker'),
            'busy_queue': RuntimeCapability('unsupported', 'dequeue_deadline_unavailable'),
            'interrupt': RuntimeCapability('unsupported', 'not_qualified'),
            'receiver_acknowledgment': RuntimeCapability('not_qualified', 'terminal_is_not_receiver_ack'),
        }
        try:
            _, lines = self._snapshot(recipient)
            capabilities['active_tab'] = RuntimeCapability('supported', 'exact_managed_pane_generation')
            last_identity=max(i for i,line in enumerate(lines) if line.strip().startswith('Session ID:'))
            if any(line.strip()=='No active session' or re.search(r'[⠀-⣿] Starting session',line)
                   for line in lines[last_identity+1:]):
                return RuntimeObservation('unavailable','session_initializing_or_missing',capabilities)
            footer = r'Grok 4\.7 \(high\) · .+ · ctrl\+o transcript'
            if (len(lines) >= 3 and lines[-3] == 'minimal · /help'
                    and lines[-2] == '❯' and re.fullmatch(footer, lines[-1])):
                return RuntimeObservation('ready', 'qualified_empty_composer', capabilities)
            return RuntimeObservation('unavailable', 'busy_draft_or_unknown_composer', capabilities)
        except measurements.TimeUnavailable:
            return RuntimeObservation('unavailable', 'qualified_time_unavailable', capabilities)
        except Exception:
            return RuntimeObservation('unavailable', 'binding_or_ui_unavailable', capabilities)

    def submit(self, recipient, prompt):
        if self.busy_policy != "wait":
            return RuntimeSubmission("not_sent", reason="busy_policy_unsupported", pre_io=True)
        try:
            if self.deadline is None:
                self.deadline = measurements.deadline(30)
            if not callable(getattr(self.deadline, 'remaining', None)):
                raise measurements.TimeUnavailable('retained_deadline_required')
            if self.deadline.remaining() <= 12:
                return RuntimeSubmission('not_sent', reason='original_deadline_reached', pre_io=True)
            self.host.deadline = self.deadline
        except measurements.TimeUnavailable:
            return RuntimeSubmission('not_sent', reason='qualified_time_unavailable', pre_io=True)
        method = recipient.binding.get("_preferred_method", self.preferred_method)
        if method == "native_preferred":
            from .runtime_policies import terminal_fallback
            # Grok 1.0.40 has no qualified exact-open-session native route.
            # This result precedes any native submission I/O; UI inspection
            # cannot be used to make the same assertion after possible input.
            preferred = RuntimeSubmission("not_sent", reason="native_unavailable", pre_io=True)
            terminal = GrokRuntimeAdapter(self.host, deadline=self.deadline,
                                          busy_policy=self.busy_policy)
            terminal_recipient = RuntimeRecipient(recipient.runtime, recipient.session_id,
                MappingProxyType(dict(recipient.binding, _preferred_method="terminal_observation")))
            return terminal_fallback(terminal_recipient, prompt, preferred, terminal)
        if method != "terminal_observation":
            return RuntimeSubmission("not_sent", reason="delivery_method_unsupported", pre_io=True)
        observation = self.observe(recipient)
        if observation.state != 'ready':
            return RuntimeSubmission('not_sent', reason=observation.reason, pre_io=True)
        try:
            self.host.refresh_identity(recipient.binding)
            if self.observe(recipient).state != 'ready':
                return RuntimeSubmission('not_sent', reason='fresh_identity_or_composer_changed', pre_io=True)
        except measurements.TimeUnavailable:
            return RuntimeSubmission('not_sent', reason='qualified_time_unavailable', pre_io=True)
        except Exception:
            return RuntimeSubmission('not_sent', reason='fresh_session_identity_unavailable', pre_io=True)
        try:
            if self.deadline.remaining() <= 12:
                return RuntimeSubmission('not_sent', reason='original_deadline_reached', pre_io=True)
        except measurements.TimeUnavailable:
            return RuntimeSubmission('not_sent', reason='qualified_time_unavailable', pre_io=True)
        try:
            self.host.paste(recipient.binding, prompt, deadline=self.deadline)
            # Enter returns before the TUI necessarily repaints. Observe only
            # this original marker, within both a short bound and its deadline.
            phase = measurements.deadline(1)
            previous_phase = getattr(self.host, "_phase_deadline", None)
            self.host._phase_deadline = phase
            try:
                return self._acceptance(recipient, prompt, phase)
            finally:
                self.host._phase_deadline = previous_phase
        except Exception:
            pass
        return RuntimeSubmission('uncertain', reason='terminal_acceptance_unconfirmed')

    def _acceptance(self, recipient, prompt, phase):
        while True:
            remaining = min(phase.remaining(), self.deadline.remaining())
            if remaining <= 0:
                break
            observed = self.reconcile(recipient, prompt)
            # A receipt read cannot extend either retained budget or survive clock loss.
            if min(phase.remaining(), self.deadline.remaining()) <= 0:
                break
            if observed.evidence:
                return RuntimeSubmission('accepted', evidence_kind='terminal_observation', evidence=observed.evidence)
            remaining = min(phase.remaining(), self.deadline.remaining())
            if remaining <= 0:
                break
            time.sleep(min(.05, remaining))
        return RuntimeSubmission('uncertain', reason='terminal_acceptance_unconfirmed')

    def reconcile(self, recipient, prompt):
        try:
            observed, lines = self._snapshot(recipient)
            marker = prompt.splitlines()[0]
            if (not re.fullmatch(r'WAKE_RUNTIME_SUBMISSION_ID=[0-9a-f-]{36}', marker)
                    or marker not in lines):
                return RuntimeReconciliation(reason='no_exact_terminal_acceptance')
            return RuntimeReconciliation(dict(
                source='terminal_observation', execution='not_observed',
                frame_sha256=hashlib.sha256(observed['frame'].encode()).hexdigest(),
                marker_sha256=hashlib.sha256(marker.encode()).hexdigest(),
            ))
        except Exception:
            return RuntimeReconciliation(reason='terminal_evidence_unavailable')
