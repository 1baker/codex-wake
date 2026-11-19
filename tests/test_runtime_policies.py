"""Public adapter policy boundary: no unsafe busy-mode effects."""
import unittest
from codex_wake.runtime_delivery import RuntimeRecipient
from codex_wake.grok_runtime import GrokRuntimeAdapter

class BusyPolicyTests(unittest.TestCase):
    def test_unqualified_queue_and_interrupt_refuse_before_host_io(self):
        class Host:
            def snapshot(self, binding):
                raise AssertionError('unsupported policy must refuse before host I/O')
        for policy in ('queue', 'interrupt', 'unknown'):
            with self.subTest(policy=policy):
                result = GrokRuntimeAdapter(Host(), busy_policy=policy).submit(
                    RuntimeRecipient('grok', 'exact', {}), 'Synthetic')
                self.assertEqual(result.state, 'not_sent')
                self.assertEqual(result.reason, 'busy_policy_unsupported')

class TerminalFallbackTests(unittest.TestCase):
    def test_only_approved_pre_io_native_unavailability_may_switch(self):
        from codex_wake.runtime_delivery import RuntimeSubmission
        from codex_wake.runtime_policies import terminal_fallback
        class Terminal:
            calls = 0
            def submit(self, recipient, prompt):
                self.calls += 1
                return RuntimeSubmission('accepted', evidence_kind='terminal_observation')
        binding = dict(allow_terminal_input=True, allow_terminal_fallback=True)
        recipient = RuntimeRecipient('grok', 'exact', binding)
        for prior in (RuntimeSubmission('uncertain', reason='native_unavailable'),
                      RuntimeSubmission('not_sent', reason='native_unavailable'),
                      RuntimeSubmission('not_sent', reason='deadline', pre_io=True),
                      RuntimeSubmission('accepted', evidence_kind='native_queue_acceptance')):
            terminal = Terminal()
            result = terminal_fallback(recipient, 'Synthetic', prior, terminal)
            self.assertIs(result, prior)
            self.assertEqual(terminal.calls, 0)
        prior = RuntimeSubmission('not_sent', reason='native_unavailable', pre_io=True)
        terminal = Terminal()
        self.assertEqual(terminal_fallback(recipient, 'Synthetic', prior, terminal).evidence_kind,
                         'terminal_observation')
        self.assertEqual(terminal.calls, 1)
        for profile in ({}, dict(allow_terminal_input=True), dict(allow_terminal_fallback=True)):
            terminal = Terminal()
            self.assertIs(terminal_fallback(RuntimeRecipient('grok', 'exact', profile),
                                           'Synthetic', prior, terminal), prior)
            self.assertEqual(terminal.calls, 0)

class PreferredGrokRouteTests(unittest.TestCase):
    def test_native_preferred_requires_host_profile_and_keeps_weak_evidence(self):
        from test_grok_runtime import FRAME, SESSION
        class Host:
            def __init__(self):
                self.frame = FRAME
                self.inputs = []
            def snapshot(self, binding):
                return dict(binding, frame=self.frame)
            def refresh_identity(self, binding):
                pass
            def paste(self, binding, prompt, *, deadline=None):
                self.inputs.append(prompt)
                self.frame = FRAME.replace('minimal · /help', prompt+'\nminimal · /help')
        prompt = 'WAKE_RUNTIME_SUBMISSION_ID=01234567-89ab-cdef-0123-456789abcdef\nSynthetic'
        for approved in (False, True):
            with self.subTest(approved=approved):
                host = Host()
                binding = dict(start_ticks=42, boot_id='boot', pid=123, session_id=SESSION,
                               executable_sha256='a'*64, allow_terminal_input=True,
                               allow_terminal_fallback=approved)
                adapter = GrokRuntimeAdapter(host, preferred_method='native_preferred')
                result = adapter.submit(RuntimeRecipient('grok', SESSION, binding), prompt)
                self.assertEqual(len(host.inputs), 1 if approved else 0)
                self.assertEqual(result.state, 'accepted' if approved else 'not_sent')
                if approved:
                    self.assertEqual(result.evidence_kind, 'terminal_observation')
                    self.assertEqual(result.evidence['execution'], 'not_observed')

class CodexBusyPolicyTests(unittest.TestCase):
    def test_unqualified_policies_do_not_invoke_native_control(self):
        from codex_wake.codex_runtime import CodexRuntimeAdapter
        def forbidden(*args, **kwargs):
            raise AssertionError('policy refusal must precede native control')
        for policy in ('queue', 'interrupt'):
            adapter = CodexRuntimeAdapter(read_thread=forbidden, request=forbidden,
                                         run=forbidden, project_failure=forbidden,
                                         busy_policy=policy)
            result = adapter.submit(RuntimeRecipient('codex', 'exact', {}), 'Synthetic')
            self.assertEqual(result.state, 'not_sent')
            self.assertTrue(result.pre_io)

class GrokPolicyCLITests(unittest.TestCase):
    def test_cli_refuses_unsupported_busy_policies_before_host_lookup_or_retention(self):
        import contextlib, io, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from codex_wake.cli import run
        from codex_wake.records import all_records, WakeError
        for policy in ('queue', 'interrupt'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with patch('codex_wake.runtime_wakes.binding_digest',
                           side_effect=AssertionError('must refuse before host lookup')), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaisesRegex(WakeError, 'busy_policy_unsupported'):
                        run(['--wake-root', str(root), 'grok', 'after',
                        '--busy-policy', policy, '--idempotency-key', 'same',
                        'grok_'+'a'*32, '1m', '--', 'Synthetic'])
                self.assertEqual(all_records(root), [])

class DurableFallbackTests(unittest.TestCase):
    def test_approved_profile_is_retained_and_uncertain_terminal_is_never_replayed(self):
        import contextlib, io, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from codex_wake.cli import run
        from codex_wake.daemon import poll_once
        from codex_wake.records import all_records
        from codex_wake.time_provider import TimeDecision
        from test_grok_runtime import FRAME, SESSION
        class Host:
            inputs = 0
            def load_binding(self, *args):
                return dict(start_ticks=42, boot_id='boot', pid=123, session_id=SESSION,
                            executable_sha256='a'*64, allow_terminal_input=True,
                            allow_terminal_fallback=True)
            def snapshot(self, binding):
                return dict(binding, frame=FRAME)
            def refresh_identity(self, binding):
                pass
            def paste(self, binding, prompt, *, deadline=None):
                self.inputs += 1
                raise OSError('response lost after possible input')
        host = Host()
        clock = dict(utc=dict(status='network',sources=['one','two'],
                              lower=1800000000,upper=1800000000.1), counter=None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('codex_wake.runtime_wakes.GrokTerminalHost',return_value=host), patch(
                    'codex_wake.runtime_wakes.binding_digest',return_value='b'*64), patch(
                    'codex_wake.native_clock.snapshot',return_value=clock), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(['--wake-root',str(root),'grok','after','--ttl','2m',
                    '--idempotency-key','fallback','grok_'+'a'*32,'1s','--','Synthetic']),0)
                original = all_records(root)[0].record
                self.assertEqual(original['target']['method'],'native_preferred')
                due = lambda:TimeDecision('network',('one','two'),1800000002,1800000002.1)
                poll_once(root,time_provider=due)
                first = all_records(root)[0].record
                poll_once(root,time_provider=due)
                final = all_records(root)[0].record
            self.assertEqual(host.inputs,1)
            self.assertEqual(final['runtime_delivery']['state'],'uncertain')
            self.assertEqual(final['runtime_delivery']['submission_id'],first['runtime_delivery']['submission_id'])
            self.assertEqual(final['scheduling_intent'],original['scheduling_intent'])
            self.assertEqual(final['attempts'],1)

class FallbackProtectionTests(unittest.TestCase):
    def test_profile_never_bypasses_composer_version_or_process_checks(self):
        from test_grok_runtime import FRAME, SESSION
        cases = ((FRAME.replace('❯\n','❯ user draft\n'),42),
                 (FRAME+'Permission required\n',42),
                 (FRAME+'user@host $\n',42),
                 (FRAME.replace('1.0.40','1.0.41'),42),
                 (FRAME.replace(SESSION,'replaced-session'),42),
                 (FRAME,43))
        for frame, generation in cases:
            with self.subTest(frame=frame,generation=generation):
                class Host:
                    def snapshot(self,binding):
                        return dict(binding, frame=frame,start_ticks=generation)
                    def refresh_identity(self,binding):
                        raise AssertionError('protected UI must not receive control input')
                    def paste(self,*args,**kwargs):
                        raise AssertionError('protected UI must not receive payload')
                binding = dict(pid=123,start_ticks=42,boot_id='boot',session_id=SESSION,
                    executable_sha256='a'*64,allow_terminal_input=True,allow_terminal_fallback=True)
                outcome = GrokRuntimeAdapter(Host(),preferred_method='native_preferred').submit(
                    RuntimeRecipient('grok',SESSION,binding),'Synthetic')
                self.assertEqual(outcome.state,'not_sent')

class IntegratedPolicySelectionTests(unittest.TestCase):
    def test_native_cli_and_grok_mcp_refuse_unqualified_policy_before_effects(self):
        import tempfile
        from pathlib import Path
        from codex_wake.cli import run
        from codex_wake.records import WakeError
        from codex_wake.mcp_server import CommandRunner
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake'
            for policy in ('queue','interrupt'):
                if policy == 'interrupt':
                    with self.assertRaisesRegex(WakeError,'busy_policy_unsupported'):
                        run(['--wake-root',str(root),'native','after','--busy-policy',policy,
                             '--codex-path','/not-an-executable','exact-thread','1m','--','Synthetic'])
                runner=CommandRunner(wake_root=root)
                value,failed=runner.call('wake_grok_after',dict(binding_id='grok_'+'a'*32,
                    trigger='1m',prompt='Synthetic',idempotency_key='original',busy_policy=policy))
                self.assertTrue(failed)
                self.assertEqual(value['error']['code'],'busy_policy_unsupported')
            self.assertFalse(root.exists())


def setUpModule():
    from itertools import count
    from unittest.mock import patch
    from test_measurements import observation
    global _qualified_clock_patch
    counters=count(1000,100)
    _qualified_clock_patch=patch('codex_wake.measurements.snapshot', side_effect=lambda:observation(next(counters),rate=0))
    _qualified_clock_patch.start()


def tearDownModule():
    _qualified_clock_patch.stop()
