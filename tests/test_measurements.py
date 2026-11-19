"""Stable Time evidence governs elapsed and freshness decisions."""
import unittest
from unittest.mock import patch

from codex_wake import measurements


def observation(counter, *, epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6', rate=5000):
    return dict(reason='authenticated_utc', valid_for_ns=1000000000,
        utc=dict(status='network', lower=1700000000, upper=1700000001),
        counter=dict(epoch=epoch, counter=counter, frequency=1000, rate_ppm=rate))


class MeasurementsTests(unittest.TestCase):
    def test_client_failure_is_not_reported_as_a_service_outage(self):
        with patch('codex_wake.native_clock.configuration', return_value='/configured'), patch(
                'codex_wake.native_clock.snapshot', return_value=dict(utc=None, counter=None,
                    reason='stable_time_client_transport_failed')):
            with self.assertRaisesRegex(measurements.TimeUnavailable, 'stable_time_client_transport_failed'):
                measurements.snapshot()

    def test_deadline_rejects_rollback_after_an_already_qualified_observation(self):
        with patch('codex_wake.measurements.snapshot',side_effect=[
                observation(1000),observation(2000),observation(1500)]):
            retained=measurements.deadline(10)
            self.assertLess(retained.remaining(),10)
            with self.assertRaises(measurements.TimeUnavailable):
                retained.remaining()

    def test_restrict_only_tightens_duration_against_original_anchor(self):
        with patch('codex_wake.measurements.snapshot',side_effect=[
                observation(1000,rate=0),observation(2000,rate=0),observation(2500,rate=0)]):
            retained=measurements.deadline(10)
            self.assertIs(retained.restrict(2),retained)
            remaining=retained.remaining()
            self.assertGreater(remaining,.99)
            self.assertLess(remaining,1)
            retained.restrict(20)
            remaining=retained.remaining()
            self.assertGreater(remaining,.49)
            self.assertLess(remaining,.5)

    def test_expired_utc_handoff_cannot_produce_a_timestamp(self):
        with patch('codex_wake.native_clock.configuration', return_value='/host-approved/config'), \
                patch('codex_wake.native_clock.snapshot', return_value=dict(observation(1000), valid_for_ns=0)):
            with self.assertRaises(measurements.TimeUnavailable):
                measurements.utc_time()

    def test_missing_or_unqualified_authority_never_uses_network_or_guest_fallback(self):
        with patch('codex_wake.native_clock.configuration', return_value=None), \
                patch('codex_wake.native_clock.snapshot') as reader:
            with self.assertRaises(measurements.TimeUnavailable):
                measurements.snapshot()
            reader.assert_not_called()
        for reason in ('bounded_utc', 'clock_unavailable', 'unqualified'):
            with self.subTest(reason=reason), \
                    patch('codex_wake.native_clock.configuration', return_value='/host-approved/config'), \
                    patch('codex_wake.native_clock.snapshot', return_value=dict(observation(1000), reason=reason)):
                with self.assertRaises(measurements.TimeUnavailable):
                    measurements.snapshot()

    def test_counter_only_supports_elapsed_but_never_becomes_a_utc_timestamp(self):
        anchor = dict(observation(1000), reason='authenticated_counter_only', utc=None)
        current = dict(observation(2000), reason='authenticated_counter_only', utc=None)
        self.assertTrue(measurements.fresh(anchor, 2, current=current))
        with patch('codex_wake.native_clock.configuration', return_value='/host-approved/config'), \
                patch('codex_wake.native_clock.snapshot', return_value=current):
            with self.assertRaises(measurements.TimeUnavailable):
                measurements.utc_time()

    def test_counter_rollback_or_frequency_change_cannot_extend_a_deadline(self):
        for current in (observation(999), dict(observation(2000), counter=dict(
                observation(2000)['counter'], frequency=2000))):
            with self.subTest(current=current), self.assertRaises(measurements.TimeUnavailable):
                measurements.elapsed_bounds(observation(1000), current)

    def test_deadline_retains_original_counter_anchor_and_refuses_epoch_change(self):
        with patch('codex_wake.native_clock.configuration', return_value='/host-approved/config'), \
                patch('codex_wake.native_clock.snapshot', side_effect=[observation(1000), observation(2000),
                    observation(3100), observation(3200, epoch='4c93a3d4-445d-4403-8a40-77fa9162dee6')]):
            timer = measurements.deadline(2)
            self.assertGreater(timer.remaining(), 0.9)
            self.assertTrue(timer.expired())
            with self.assertRaises(measurements.TimeUnavailable):
                timer.remaining()

    def test_configured_authority_is_used_without_guest_clock_reads(self):
        value = observation(1000)
        with patch('codex_wake.native_clock.configuration', return_value='/host-approved/config'), \
                patch('codex_wake.native_clock.snapshot', return_value=value), \
                patch('time.time', side_effect=AssertionError('guest wall clock read')), \
                patch('time.monotonic', side_effect=AssertionError('guest elapsed clock read')):
            self.assertEqual(measurements.snapshot(), value)

    def test_counter_bounds_preserve_freshness_despite_unrelated_utc_order(self):
        anchor = observation(1000)
        current = observation(2000)
        current['utc'] = dict(status='network', lower=1699999990, upper=1699999991)
        lower, upper = measurements.elapsed_bounds(anchor, current)
        self.assertLess(lower, 1)
        self.assertGreater(upper, 1)
        self.assertTrue(measurements.fresh(anchor, 2, current=current))
        self.assertFalse(measurements.fresh(anchor, 1, current=current))
