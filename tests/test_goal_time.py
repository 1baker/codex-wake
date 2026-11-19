"""Qualified relative allowance time; never substitute guest UTC or rebase."""
import unittest
from unittest.mock import patch


ANCHOR = dict(epoch='00000000-0000-4000-8000-000000000468', counter=1000, frequency=1000, rate_ppm=100)


class GoalTimeTests(unittest.TestCase):
    def test_absolute_utc_allowance_reads_qualified_upper_without_guest_elapsed(self):
        from copy import deepcopy
        from codex_wake.goal_time import upper
        receipt = dict(time_basis='qualified_utc', started_upper=100, time_origin=90,
            deadline=130, started_boottime=999999999, used_tokens=7, stop_latched=True)
        original = deepcopy(receipt)
        with patch('codex_wake.lifecycle_budget.trusted_upper', return_value=125), patch(
                'time.clock_gettime', side_effect=AssertionError('guest clock must not measure allowance')):
            self.assertEqual(upper(receipt), 125)
        self.assertEqual(receipt, original)

    def test_absolute_utc_clock_loss_and_unknown_basis_hold_without_rebasing(self):
        from copy import deepcopy
        from codex_wake.goal_time import upper, GoalTimeUnavailable
        receipt = dict(started_upper=100, time_origin=90, deadline=130,
            used_tokens=7, stop_latched=True, started_boottime=-999999)
        original = deepcopy(receipt)
        with patch('codex_wake.lifecycle_budget.trusted_upper', side_effect=ValueError('unqualified')), patch(
                'codex_wake.native_clock.snapshot') as fallback:
            with self.assertRaises(GoalTimeUnavailable) as refused:
                upper(receipt)
        self.assertEqual(refused.exception.code, 'clock_unqualified')
        fallback.assert_not_called()
        self.assertEqual(receipt, original)
        for changed in (dict(receipt, time_basis='unknown_future_basis'),
                        dict(receipt, deadline=float('inf')),
                        dict(receipt, time_origin=None), dict(receipt, started_upper=True)):
            with self.subTest(changed=changed), patch('codex_wake.lifecycle_budget.trusted_upper') as clock:
                with self.assertRaises(GoalTimeUnavailable):
                    upper(changed)
                clock.assert_not_called()

    def test_trusted_upper_uses_strict_utc_bounds_and_refuses_unavailable_time(self):
        from codex_wake.lifecycle_budget import trusted_upper
        from codex_wake.measurements import TimeUnavailable
        with patch('codex_wake.measurements.utc_bounds', return_value=(111, 112)):
            self.assertEqual(trusted_upper(), 112)
        with patch('codex_wake.measurements.utc_bounds', side_effect=TimeUnavailable('unqualified')):
            with self.assertRaisesRegex(ValueError, 'admissible time unavailable'):
                trusted_upper()

    def test_fresh_allowance_uses_authenticated_counter_without_inventing_utc(self):
        from codex_wake.goal_time import admit, public_time, upper
        clock=dict(utc=None,counter=ANCHOR,reason='authenticated_counter_only')
        with patch('codex_wake.lifecycle_budget.trusted_upper',side_effect=ValueError('admissible time unavailable')), patch('codex_wake.native_clock.snapshot',return_value=clock):
            now, fields=admit(None,allow_counter=True)
        self.assertEqual(now,0)
        self.assertEqual(fields['time_basis'],'authenticated_host_counter')
        self.assertEqual(fields['clock_anchor'],ANCHOR)
        receipt=dict(fields,deadline=10,time_limit_seconds=10,started_upper=0,time_origin=0)
        later=dict(clock,counter=dict(ANCHOR,counter=2000))
        with patch('codex_wake.native_clock.snapshot',return_value=later):
            elapsed=upper(receipt)
        self.assertGreaterEqual(elapsed,1)
        self.assertLess(elapsed,1.002)
        shown=public_time(receipt)
        self.assertIsNone(shown['deadline'])
        self.assertIsNone(shown['deadline_utc'])
        self.assertEqual(shown['elapsed_limit_seconds'],10)

    @patch('codex_wake.measurements.snapshot', return_value=dict(reason='authenticated_counter_only',utc=None,counter=dict(ANCHOR,counter=2000)))
    def test_counter_readiness_and_notice_never_format_elapsed_as_utc(self, _fixture_clock):
        import tempfile
        from pathlib import Path
        from codex_wake.goal_readiness import engagement
        from codex_wake.goal_notices import record_notice
        receipt=dict(thread_id='00000000-0000-4000-8000-000000000468',allocation_id='own',
            generation='receipt',enrollment_revision=1,state='armed',accounting=dict(state='qualified'),
            used_tokens=1,token_limit=10,token_accounting='fresh',deadline=10,
            time_limit_seconds=10,time_origin=0,started_upper=0,
            started_boottime=None,
            checkpoint_token_percent=5,checkpoint_seconds=1,session_scope=True,native_goal_status=None,
            time_basis='authenticated_host_counter',clock_anchor=ANCHOR,
            clock_observation=dict(ANCHOR,counter=2000),clock_elapsed_upper=1.0012,
            poll_ack=dict(enrollment_revision=1,receipt_generation='receipt',
                controller_generation='controller',observed_boottime=None,
                clock_observation=dict(reason='authenticated_counter_only',utc=None,counter=dict(ANCHOR,counter=2000))))
        controller=dict(fresh=True,generation='controller',interval=1)
        self.assertFalse(engagement(receipt,controller)['engaged'])
        controller.update(time_bases=['qualified_utc','authenticated_host_counter'],session_scope_without_goal=True)
        view=engagement(receipt,controller)
        self.assertTrue(view['engaged'])
        self.assertIsNone(view['card']['deadline_utc'])
        self.assertIsNone(view['card']['timezone'])
        self.assertEqual(view['card']['time_basis'],'authenticated_host_counter')
        from copy import deepcopy
        original=deepcopy(receipt)
        qualified=deepcopy(_fixture_clock.return_value)
        for invalid in (None,dict(qualified,counter=dict(ANCHOR,counter=1000)),
                dict(qualified,counter=dict(ANCHOR,epoch='00000000-0000-4000-8000-000000000469',counter=2000)),
                dict(qualified,counter=dict(ANCHOR,counter=50000))):
            with self.subTest(clock=invalid):
                _fixture_clock.return_value=invalid
                self.assertFalse(engagement(receipt,controller)['engaged'])
                self.assertEqual(receipt,original)
        _fixture_clock.return_value=qualified
        legacy=deepcopy(receipt);legacy['poll_ack'].pop('clock_observation')
        legacy['poll_ack']['observed_boottime']=10
        self.assertFalse(engagement(legacy,controller)['engaged'])
        for field,value in (('enrollment_revision',2),('receipt_generation','replacement'),
                ('controller_generation','replacement')):
            mismatch=deepcopy(receipt);mismatch['poll_ack'][field]=value
            self.assertFalse(engagement(mismatch,controller)['engaged'])


        with tempfile.TemporaryDirectory() as directory:
            event=record_notice(Path(directory),receipt,'activation')
            self.assertNotIn('1970',event['text'])
            self.assertIn('authenticated host elapsed',event['text'])
            self.assertIsNone(event['snapshot']['deadline'])

    def test_absolute_readiness_card_requires_current_qualified_utc_without_reanchoring(self):
        from copy import deepcopy
        from codex_wake.goal_readiness import engagement
        from codex_wake.measurements import TimeUnavailable
        stamp=dict(reason='authenticated_utc',utc=dict(status='network',lower=100,upper=101),
            valid_for_ns=300000000000,counter=dict(ANCHOR,counter=2000))
        receipt=dict(thread_id='owned',allocation_id='allocation',generation='receipt',enrollment_revision=1,
            state='armed',accounting=dict(state='qualified'),used_tokens=1,token_limit=10,
            started_upper=100,time_origin=100,deadline=200,checkpoint_token_percent=5,checkpoint_seconds=1,
            poll_ack=dict(enrollment_revision=1,receipt_generation='receipt',controller_generation='controller',
                observed_boottime=None,clock_observation=stamp))
        controller=dict(fresh=True,generation='controller',interval=1)
        original=deepcopy(receipt)
        with patch('codex_wake.measurements.snapshot',return_value=stamp),patch(
                'codex_wake.lifecycle_budget.trusted_upper',return_value=110),patch(
                'time.clock_gettime',side_effect=AssertionError('no guest clock')):
            shown=engagement(receipt,controller)
            self.assertTrue(shown['engaged'])
            self.assertEqual(shown['card']['remaining_seconds'],90)
            self.assertEqual(shown['card']['time_observation'],'qualified_utc')
            with patch('codex_wake.lifecycle_budget.trusted_upper',side_effect=TimeUnavailable('lost')):
                held=engagement(receipt,controller)
                self.assertFalse(held['engaged'])
                self.assertEqual(held['status'],'clock_unqualified')
        self.assertEqual(receipt,original)
        with patch('codex_wake.measurements.snapshot',side_effect=AssertionError('disabled control needs no clock')):
            self.assertEqual(engagement(dict(receipt,governor_enabled=False),controller)['status'],'inactive')
        with patch('codex_wake.measurements.snapshot',side_effect=AssertionError('stop needs no clock')):
            self.assertEqual(engagement(dict(receipt,stop_latched=True),controller)['status'],'continuation_held')

    def test_counter_anchor_cannot_switch_basis_or_survive_continuity_loss(self):
        from codex_wake.goal_time import admit,GoalTimeUnavailable
        original=dict(time_basis='authenticated_host_counter',clock_anchor=dict(ANCHOR),
            clock_observation=dict(ANCHOR),clock_elapsed_upper=0,time_limit_seconds=10)
        with patch('codex_wake.native_clock.snapshot',return_value=dict(
                utc=dict(lower=100,upper=100),counter=dict(ANCHOR,counter=2000),reason='authenticated_utc')):
            _,later=admit(original)
        self.assertEqual(later['clock_anchor'],ANCHOR)
        self.assertEqual(later['time_basis'],'authenticated_host_counter')
        for counter in (None,dict(ANCHOR,epoch='replacement'),dict(ANCHOR,counter=999)):
            with self.subTest(counter=counter),patch('codex_wake.native_clock.snapshot',return_value=dict(
                    utc=None,counter=counter,reason='authenticated_counter_only')):
                with self.assertRaises(GoalTimeUnavailable):admit(original)
        self.assertEqual(original['clock_elapsed_upper'],0)
        self.assertEqual(original['clock_anchor'],ANCHOR)

    def test_inherited_utc_scope_cannot_use_counter_fallback(self):
        from codex_wake.goal_time import admit
        with patch('codex_wake.lifecycle_budget.trusted_upper',side_effect=ValueError('admissible time unavailable')),patch(
                'codex_wake.native_clock.snapshot') as snapshot:
            with self.assertRaisesRegex(ValueError,'admissible time unavailable'):
                admit(dict(time_basis='qualified_utc',deadline=100),allow_counter=True)
            snapshot.assert_not_called()
