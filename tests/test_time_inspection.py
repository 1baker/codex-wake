import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

from codex_wake import cli


class InspectionTests(unittest.TestCase):
    def test_missing_stable_time_configuration_cannot_acquire_alternate_time(self):
        from codex_wake.time_inspection import network_time_decision
        with patch.dict(os.environ, {'CODEX_WAKE_STABLE_TIME_CONFIG': ''}), \
                patch('codex_wake.time_inspection.windows_collect',
                    side_effect=AssertionError('alternate time acquisition')) as collect:
            decision = network_time_decision()
            self.assertEqual(decision.status, 'uncertain')
            self.assertEqual(decision.reason, 'stable_time_configuration_required')
            collect.assert_not_called()

    def test_offline_command_shows_all_candidates_and_no_trusted_time(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'CODEX_WAKE_STABLE_TIME_CONFIG': ''}), contextlib.redirect_stdout(output):
            code = cli.main(['time', 'inspect', '--offline'])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report['decision']['status'], 'uncertain')
        self.assertEqual([s['operator'] for s in report['sources']], ['cloudflare','nist','netnod','ptb','alastyr'])
        self.assertEqual(report['sources'][2]['reason'], 'time_scale_unqualified')
        self.assertEqual(report['sources'][3]['reason'], 'time_scale_unqualified')
        self.assertFalse(report['production_ready'])

    def test_offline_installed_service_reports_uncertainty_without_acquisition(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'CODEX_WAKE_STABLE_TIME_CONFIG': '/unused/stable-time.json'}), \
                patch('codex_wake.stable_time.service_time_result', side_effect=AssertionError('offline acquisition')), \
                contextlib.redirect_stdout(output):
            code = cli.main(['time', 'inspect', '--offline'])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report['provider'], 'stable-time')
        self.assertEqual(report['purpose'], 'installed-service-consumer')
        self.assertEqual(report['decision']['status'], 'uncertain')
        self.assertEqual(report['decision']['reason'], 'acquisition_not_requested')
        self.assertIsNone(report['observation'])

    def test_two_network_replies_are_normalized_to_one_host_counter_instant(self):
        from codex_wake.time_inspection import inspect_time
        report = inspect_time(collector=lambda sources, request: envelope(request))
        self.assertEqual(report['decision']['status'],'network')
        self.assertEqual(report['decision']['sources'],('time.cloudflare.com','time.nist.gov'))
        self.assertGreater(report['decision']['lower'],1800000000)
        self.assertLess(report['decision']['upper'],1800000000.3)
        self.assertEqual(report['sources'][0]['reason'],'accepted')

    def test_faults_exclude_observation_without_discarding_other_diagnostics(self):
        import base64
        from codex_wake.time_inspection import inspect_time
        changes = [
            ('malformed_reply', lambda d: d['replies'][0].update(packet=base64.b64encode(b'short').decode())),
            ('origin_mismatch', lambda d: d['replies'][0].update(token=base64.b64encode(b'87654321').decode())),
            ('excessive_delay', lambda d: d['replies'][0].update(sent=0,received=1000)),
            ('stale_observation', lambda d: d['replies'][0].update(sent=0,received=20)),
            ('dns_timeout', lambda d: d['replies'][0].update(error='dns_timeout')),
            ('missing_or_duplicate_reply', lambda d: d['replies'].append(d['replies'][0])),
        ]
        for reason, mutate in changes:
            def collect(sources, request):
                data=envelope(request)
                if reason == 'excessive_delay':
                    data.update(start=1000,end=2000)
                    data['replies'][1].update(sent=1980,received=2000)
                if reason == 'stale_observation':
                    data.update(start=121000,end=121001)
                    data['replies'][1].update(sent=120980,received=121000)
                mutate(data)
                return data
            with self.subTest(reason=reason):
                report=inspect_time(collector=collect)
                self.assertEqual(report['decision']['status'],'uncertain')
                self.assertEqual(report['sources'][0]['reason'],reason)
                self.assertEqual(report['sources'][1]['reason'],'accepted')

    def test_boot_request_and_counter_failures_reject_whole_round(self):
        from codex_wake.time_inspection import inspect_time
        cases=[dict(host_boot_end='new'),dict(request_id='replayed'),dict(guest_boot='foreign'),
               dict(frequency=0),dict(end=float('nan')),dict(end=30000)]
        for changes in cases:
            def collect(sources,request):
                data=envelope(request);data.update(changes);return data
            with self.subTest(changes=changes):
                self.assertEqual(inspect_time(collector=collect)['decision']['status'],'uncertain')

    def test_transport_unavailable_still_returns_all_sources(self):
        from codex_wake.time_inspection import inspect_time
        def unavailable(sources,request):
            raise OSError('interop_unavailable')
        report=inspect_time(collector=unavailable)
        self.assertEqual(report['decision']['status'],'uncertain')
        self.assertEqual(len(report['sources']),5)
        self.assertEqual(report['sources'][0]['reason'],'interop_unavailable')

    def test_healthy_windows_fallback_and_health_exclusion(self):
        from codex_wake.time_inspection import inspect_time
        def collect(sources,request):
            data=envelope(request)
            data['replies']=[]
            data['windows']=dict(utc=1800000000.1,sampled=200,service_running=True,source='time.cloudflare.com',
                                 leap=0,stratum=2,root_dispersion=0.01,phase_offset=0.005,sync_age=10)
            return data
        report=inspect_time(collector=collect)
        self.assertEqual(report['decision']['status'],'windows')
        self.assertEqual(report['windows']['reason'],'accepted')
        for changes in [dict(service_running=False),dict(sync_age=301),dict(root_dispersion=2),dict(leap=3),dict(phase_offset=float('nan')),dict(source='time.google.com')]:
            def unhealthy(sources,request):
                data=collect(sources,request); data['windows'].update(changes);return data
            with self.subTest(changes=changes):
                self.assertEqual(inspect_time(collector=unhealthy)['decision']['status'],'uncertain')

    def test_windows_cannot_override_network_or_conflicting_survivor(self):
        from codex_wake.time_inspection import inspect_time
        def collect(sources,request):
            data=envelope(request)
            data['windows']=dict(utc=1800000100,sampled=200,service_running=True,source='time.cloudflare.com',
                                 leap=0,stratum=2,root_dispersion=0.01,phase_offset=0,sync_age=0)
            return data
        self.assertEqual(inspect_time(collector=collect)['decision']['status'],'network')
        def survivor(sources,request):
            data=collect(sources,request); data['replies']=data['replies'][:1];return data
        self.assertEqual(inspect_time(collector=survivor)['decision']['reason'],'windows_conflicts_with_network')


    def test_third_reviewed_operator_preserves_consensus_after_any_single_loss(self):
        from codex_wake.time_inspection import inspect_time
        hosts = ('time.cloudflare.com', 'time.nist.gov', 'ntp.alastyr.com')
        for lost in hosts:
            def collect(sources, request):
                data = envelope(request)
                data['replies'].append(dict(data['replies'][0], host='ntp.alastyr.com'))
                data['replies'] = [r for r in data['replies'] if r['host'] != lost]
                return data
            with self.subTest(lost=lost):
                report = inspect_time(collector=collect)
                self.assertEqual(report['decision']['status'], 'network')
                self.assertEqual(set(report['decision']['sources']), set(hosts)-{lost})


def envelope(request):
    import base64
    import struct
    packet = bytearray(48)
    packet[0], packet[1], packet[3] = 0x24, 1, 236  # NTP4 server, precision 2^-20
    packet[24:32]=b'12345678'
    struct.pack_into('!II',packet,32,1800000000+2208988800,0)
    struct.pack_into('!II',packet,40,1800000000+2208988800,0)
    return dict(request_id=request['request_id'], guest_boot=request['guest_boot'], host_boot='host',host_boot_end='host',
                frequency=1000,start=100,end=200,generation='collection',
                replies=[dict(host=host,token=base64.b64encode(b'12345678').decode(),packet=base64.b64encode(packet).decode(),
                              sent=100,received=120,peer='192.0.2.1') for host in ['time.cloudflare.com','time.nist.gov']])
