import unittest
from unittest.mock import patch
from copy import deepcopy

from codex_wake.native_clock import from_response


def response():
    return {
        'contract_version': '1.0', 'epoch': 'c357309d-c209-4467-b757-e1488e6b1aaa',
        'counter_policy': {'rate_ppm': 5000, 'maximum_age_ns': 10000000000},
        'measurement': {'counter': '10000000', 'frequency_hz': '10000000'},
        'status': 'qualified_live', 'authentication': 'NTS-verified',
        'time_scale': 'UTC-step; announced-leaps-unavailable', 'operators': ['a', 'b'],
        'acquisition_age_ns': 0, 'evidence_generation': 1, 'reason': None,
        'estimate': {'earliest_utc': '2027-01-15T12:00:00.001Z',
                     'utc': '2027-01-15T12:00:00.100Z',
                     'latest_utc': '2027-01-15T12:00:00.199Z',
                     'maximum_error_ns': 99000000, 'maximum_error_ms': 99.0},
    }


class NativeClockTests(unittest.TestCase):
    def test_default_snapshot_retains_service_instant_without_counter_helper(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from codex_wake.native_clock import snapshot
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'token').write_text('a' * 64)
            config = root / 'client.json'
            config.write_text(json.dumps(dict(url='https://localhost:47770',
                token_file=str(root / 'token'), ca_file=str(root / 'ca'))))
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(response()).encode()
            with patch('codex_wake.native_clock.configuration', return_value=str(config)), \
                    patch('codex_wake.native_clock.ssl.SSLContext'), \
                    patch('codex_wake.native_clock.urllib.request.build_opener', return_value=opener), \
                    patch('codex_wake.host_counter.read_counter', side_effect=OSError('auxiliary client failed')) as helper:
                value = snapshot()
                opener.open.side_effect = OSError('private transport detail')
                failed = snapshot()
            self.assertEqual(value['reason'], 'authenticated_utc')
            self.assertEqual(value['basis'], 'service_measurement')
            self.assertEqual(value['counter']['counter'], 10000000)
            self.assertLess(value['utc']['upper'], 1800014400.200)
            helper.assert_not_called()
            self.assertEqual(failed['reason'], 'stable_time_client_transport_failed')
            self.assertIsNone(failed['counter'])

    def test_missing_stable_time_configuration_holds_without_network_fallback(self):
        from codex_wake.native_clock import snapshot
        with patch('codex_wake.native_clock.configuration', return_value=None), \
                patch('codex_wake.time_inspection.network_time_decision',
                    side_effect=AssertionError('non-Stable-Time fallback attempted')) as fallback:
            value = snapshot()
            self.assertIsNone(value['utc'])
            self.assertIsNone(value['counter'])
            self.assertEqual(value['reason'], 'stable_time_configuration_required')
            fallback.assert_not_called()

    def test_authenticated_utc_retains_conservative_remaining_validity(self):
        result = from_response(response(), counter=10000010, frequency=10000000)
        # Eleven counter ticks at the slowest allowed rate consume1106ns,
        # rounded up, plus1ns safety margin from the original ten-second lease.
        self.assertEqual(result['valid_for_ns'], 9999998893)

    def test_wake_tolerance_does_not_relax_service_utc_qualification(self):
        valid = response()
        self.assertIsNotNone(from_response(valid, counter=10000010, frequency=10000000)['utc'])
        just_below = deepcopy(valid)
        just_below['estimate'].update(earliest_utc='2027-01-15T12:00:00.000000001Z',
                                     latest_utc='2027-01-15T12:00:00.199999999Z',
                                     maximum_error_ns=99999999, maximum_error_ms=99.999999)
        self.assertIsNotNone(from_response(just_below, counter=10000010, frequency=10000000)['utc'])
        for radius, milliseconds, earliest, latest in [
            (100000000, 100.0, '2027-01-15T12:00:00Z', '2027-01-15T12:00:00.200Z'),
            (100000001, 100.000001, '2027-01-15T11:59:59.999999999Z', '2027-01-15T12:00:00.200000001Z'),
        ]:
            invalid = deepcopy(valid)
            invalid['estimate'].update(earliest_utc=earliest, latest_utc=latest,
                                       maximum_error_ns=radius, maximum_error_ms=milliseconds)
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                from_response(invalid, counter=10000010, frequency=10000000)

    def test_v2_finite_bounds_support_hours_away_tolerance_without_best_effort(self):
        value = response()
        value.update(contract_version='2.0', bound='finite', best_effort=None,
                     status='qualified_holdover', acquisition_age_ns=80000000000,
                     counter_policy={'rate_ppm': 5000, 'maximum_age_ns': 300000000000})
        value['estimate'].update(earliest_utc='2027-01-15T12:00:00Z',
                                 utc='2027-01-15T12:00:03Z', latest_utc='2027-01-15T12:00:06Z',
                                 maximum_error_ns=3000000000, maximum_error_ms=3000.0)
        observed = from_response(value, counter=10000010, frequency=10000000)
        self.assertLessEqual(observed['utc']['lower'], 1800014400)
        self.assertGreaterEqual(observed['utc']['upper'], 1800014406)
        for replacement in [dict(value, bound='unbounded'), dict(value, best_effort={'utc': '2027-01-15T12:00:03Z'})]:
            with self.assertRaises(ValueError):
                from_response(replacement, counter=10000010, frequency=10000000)

    def test_authenticated_unavailable_response_can_only_supply_elapsed_evidence(self):
        value = response()
        value.update(status='unavailable', authentication='NTS-required', estimate=None,
                     acquisition_age_ns=None, operators=[], reason='uncertainty_exceeded')
        result = from_response(value, counter=10000010, frequency=10000000)
        self.assertIsNone(result['utc'])
        self.assertEqual(result['counter']['epoch'], value['epoch'])
        self.assertEqual(result['reason'], 'authenticated_counter_only')
        for invalid, count, frequency in [
            (dict(value, counter_policy=None), 10000010, 10000000),
            (value, 9999999, 10000000), (value, 10000010, 1000),
            (value, 200000000, 10000000),
        ]:
            with self.subTest(counter=count, frequency=frequency):
                with self.assertRaises((ValueError, TypeError)):
                    from_response(invalid, counter=count, frequency=frequency)

    def test_holdover_and_stale_provenance_remain_bounded(self):
        value = response()
        value['status'] = 'qualified_holdover'
        self.assertIsNotNone(from_response(value, counter=10000010, frequency=10000000)['utc'])
        for field, replacement in [('operators', ['a', 'a']), ('authentication', 'unverified'),
                                   ('acquisition_age_ns', 10000000000), ('evidence_generation', 0)]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    from_response(dict(value, **{field: replacement}), counter=10000010, frequency=10000000)

    def test_malformed_counter_and_unavailable_estimate_are_never_admitted(self):
        for field, value in [('counter', True), ('frequency_hz', 10000000), ('counter', '1e7')]:
            with self.subTest(field=field, value=value):
                invalid = response()
                invalid['measurement'][field] = value
                with self.assertRaises(ValueError):
                    from_response(invalid, counter=10000010, frequency=10000000)
        invalid = response()
        invalid.update(status='unavailable', authentication='NTS-required')
        with self.assertRaises(ValueError):
            from_response(invalid, counter=10000010, frequency=10000000)
