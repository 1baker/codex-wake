import unittest
from codex_wake.stable_time import decision_from_response


class StableTimeTests(unittest.TestCase):
    def test_inspection_uses_service_measurement_without_a_counter_helper(self):
        import contextlib, io, json, tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, patch
        from codex_wake import cli

        response = dict(contract_version='2.0', status='qualified_live', bound='finite',
            epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6', evidence_generation=1,
            authentication='NTS-verified', operators=['cloudflare', 'netnod'],
            time_scale='UTC-step; announced-leaps-unavailable', acquisition_age_ns=0,
            counter_policy=dict(rate_ppm=5000, maximum_age_ns=300000000000),
            measurement=dict(counter='10000000', frequency_hz='10000000'),
            estimate=dict(earliest_utc='2026-10-10T00:00:00Z',
                utc='2026-10-10T00:00:00.050000000Z', latest_utc='2026-10-10T00:00:00.100000000Z',
                maximum_error_ns=50000000))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'token').write_text('a'*64)
            config = root/'client.json'
            config.write_text(json.dumps(dict(url='https://localhost:47770',
                token_file=str(root/'token'), ca_file=str(root/'ca'))))
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            output = io.StringIO()
            with patch.dict('os.environ', {'CODEX_WAKE_STABLE_TIME_CONFIG': str(config)}), \
                    patch('codex_wake.stable_time.ssl.SSLContext'), \
                    patch('codex_wake.stable_time.urllib.request.build_opener', return_value=opener), \
                    patch('codex_wake.host_counter.read_counter', side_effect=AssertionError('auxiliary helper')) as helper, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['time', 'inspect']), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report['decision']['status'], 'network')
            self.assertEqual(report['decision']['reason'], '')
            self.assertEqual(report['measurement_decision']['status'], 'network')
            self.assertEqual(report['basis'], 'service_measurement')
            self.assertFalse(report['receipt_time_bound'])
            self.assertFalse(report['production_ready'])
            self.assertEqual(report['observation']['measurement'], response['measurement'])
            self.assertLessEqual(report['measurement_decision']['lower'], 1791590400.0)
            self.assertLess(report['measurement_decision']['upper'], 1791590400.10001)
            helper.assert_not_called()
            # Python selection uses the service decision instant too; an
            # auxiliary helper cannot invalidate that authenticated observation.
            from codex_wake.stable_time import service_time_result
            with patch('codex_wake.stable_time.ssl.SSLContext'), \
                    patch('codex_wake.stable_time.urllib.request.build_opener', return_value=opener), \
                    patch('codex_wake.host_counter.read_counter', side_effect=OSError('private helper detail')):
                decision, observed = service_time_result(config)
            self.assertEqual(decision.status, 'network')
            self.assertEqual(decision.reason, '')
            self.assertEqual(observed['bound'], 'finite')
            response['measurement']['counter'] = True
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            with patch('codex_wake.stable_time.ssl.SSLContext'), \
                    patch('codex_wake.stable_time.urllib.request.build_opener', return_value=opener):
                invalid, _ = service_time_result(config, measurement_only=True)
            self.assertEqual(invalid.status, 'uncertain')
            self.assertEqual(invalid.reason, 'stable_time_response_invalid')

    def test_native_counter_handoff_widens_upper_bound_without_guest_time(self):
        response = dict(contract_version='1.0', status='qualified_live', epoch='a',
                        evidence_generation=1, authentication='NTS-verified',
                        operators=['cloudflare', 'netnod'],
                        time_scale='UTC-step; announced-leaps-unavailable',
                        acquisition_age_ns=0,
                        counter_policy=dict(rate_ppm=5000, maximum_age_ns=10000000000),
                        measurement=dict(counter='10000000', frequency_hz='10000000'),
                        estimate=dict(earliest_utc='2026-10-10T00:00:00.000000000Z',
                                      utc='2026-10-10T00:00:00.050000000Z',
                                      latest_utc='2026-10-10T00:00:00.100000000Z',
                                      maximum_error_ns=50000000))
        decision = decision_from_response(response, counter=11000000, frequency=10000000)
        self.assertEqual(decision.status, 'network')
        self.assertLessEqual(decision.lower, 1791590400.0)
        self.assertGreaterEqual(decision.upper, 1791590400.200502513)
        self.assertLess(decision.upper, 1791590400.201)
        self.assertEqual(decision.sources, ('stable-time:cloudflare', 'stable-time:netnod'))
        for counter, frequency in [(9999999,10000000),(11000000,1000),(120000000,10000000)]:
            with self.subTest(counter=counter,frequency=frequency), self.assertRaises(ValueError):
                decision_from_response(response,counter=counter,frequency=frequency)

    def test_wide_authenticated_v2_holdover_remains_usable_for_scheduling(self):
        response = dict(contract_version='2.0', status='qualified_holdover', bound='finite', epoch='a',
                        evidence_generation=1, authentication='NTS-verified', operators=['cloudflare','netnod'],
                        time_scale='UTC-step; announced-leaps-unavailable', acquisition_age_ns=80000000000,
                        counter_policy=dict(rate_ppm=5000, maximum_age_ns=300000000000),
                        measurement=dict(counter='10000000', frequency_hz='10000000'),
                        estimate=dict(earliest_utc='2026-10-11T00:00:00Z', utc='2026-10-11T00:00:03Z',
                                      latest_utc='2026-10-11T00:00:06Z', maximum_error_ns=3000000000))
        decision = decision_from_response(response, counter=11000000, frequency=10000000)
        self.assertEqual(decision.status, 'network')
        self.assertLessEqual(decision.lower, 1791676800.0)
        self.assertGreaterEqual(decision.upper, 1791676806.100502513)
        self.assertGreater(decision.upper-decision.lower, 6)

    def test_configured_service_failure_does_not_fall_back_to_ntp(self):
        from unittest.mock import patch
        from codex_wake.time_inspection import network_time_decision
        with patch.dict('os.environ', {'CODEX_WAKE_STABLE_TIME_CONFIG': '/missing/private/client.json'}), \
                patch('codex_wake.time_inspection.inspect_time', side_effect=AssertionError('NTP fallback')):
            self.assertEqual(network_time_decision().status, 'uncertain')

    def test_unavailable_service_or_missing_configuration_cannot_supply_trusted_time(self):
        from codex_wake.stable_time import service_time_decision, service_time_result
        self.assertEqual(decision_from_response({'status': 'unavailable'}, counter=1, frequency=1).status, 'uncertain')
        self.assertEqual(service_time_decision('/missing/private/client.json').status, 'uncertain')
        self.assertEqual(service_time_result('/missing/private/client.json', measurement_only=True)[0].reason,
                         'stable_time_client_configuration_invalid')

    def test_inspect_reports_configured_service_without_provider_polling(self):
        import contextlib, io, json
        from unittest.mock import patch
        from codex_wake import cli
        from codex_wake.time_provider import TimeDecision
        output = io.StringIO()
        with patch.dict('os.environ', {'CODEX_WAKE_STABLE_TIME_CONFIG': '/private/client.json'}), \
                patch('codex_wake.stable_time.service_time_result', return_value=(TimeDecision('uncertain', reason='stable_time_unavailable'), {'bound':'unbounded','best_effort':{'utc':'2026-10-11T00:00:00Z','basis':'host_wall_clock_unverified'}})), \
                patch('codex_wake.time_inspection.inspect_time', side_effect=AssertionError('provider request')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['time', 'inspect']), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['provider'], 'stable-time')
        self.assertEqual(report['observation']['bound'], 'unbounded')
        self.assertEqual(report['observation']['best_effort']['basis'], 'host_wall_clock_unverified')

    def test_malformed_http_json_holds_instead_of_crashing_caller(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, patch
        from codex_wake.stable_time import service_time_decision, service_time_result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'token').write_text('a'*64)
            (root/'client.json').write_text(json.dumps(dict(url='https://localhost:47770', token_file=str(root/'token'), ca_file=str(root/'ca'))))
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = b'[]'
            with patch('codex_wake.stable_time.ssl.SSLContext'), patch('codex_wake.stable_time.urllib.request.build_opener', return_value=opener):
                self.assertEqual(service_time_decision(root/'client.json').status, 'uncertain')
                self.assertEqual(service_time_result(root/'client.json', measurement_only=True)[0].reason,
                                 'stable_time_response_invalid')
                opener.open.side_effect = OSError('private transport detail must not be printed')
                self.assertEqual(service_time_result(root/'client.json', measurement_only=True)[0].reason,
                                 'stable_time_client_transport_failed')
