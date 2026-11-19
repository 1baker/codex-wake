"""Stopped executor final accounting through the operator-only CLI."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.cli import run
from codex_wake.lifecycle_configuration import effective_configuration
from codex_wake.objective_ledger import ObjectiveLedger
from codex_wake.strict_runtime import location


def qualified_clock(upper=1893456001):
    return dict(reason='authenticated_utc', utc=dict(status='network',lower=upper-.1,upper=upper),
        valid_for_ns=300000000000,counter=dict(epoch='c357309d-c209-4467-b757-e1488e6b1aaa',
        counter=1000,frequency=1000,rate_ppm=0))


class StrictFinalUsageTests(unittest.TestCase):
    def fixture(self, directory):
        root=Path(directory)/'wake';root.mkdir(mode=0o700)
        source=Path(directory)/'instructions.md';source.write_text('Review bounded local evidence.')
        profiles=Path(directory)/'profiles.json'
        limits=dict(memory_max_bytes=134217728,memory_swap_max_bytes=0,cpu_quota_percent=20,
            tasks_max=32,stop_grace_seconds=1,checkpoint_grace_seconds=1,poll_seconds=.2,accounting_max_age_seconds=5)
        policy=dict(objective_id='objective',objective='Finish bounded work',approval='operator',
            started_at='2030-01-01T00:00:00Z')
        registry=dict(profiles={'worker':dict(cwd=directory,strict_execution=limits)},
            lifecycle_defaults=dict(handoff_writer=dict(name='writer',path=str(source)),
                preflight_reviewer=dict(name='reviewer',path=str(source)),session_token_limit=100,
                session_time_limit_seconds=60,objective_token_limit=500,objective_time_limit_seconds=300,max_correction_cycles=2),
            continuations={'source':policy})
        profiles.write_text(json.dumps(registry))
        cfg=effective_configuration(registry,'source','worker')
        cfg={k:v for k,v in cfg.items() if k not in ('source_thread_id','profile')}
        ledger=ObjectiveLedger(root,'objective');ledger.configure(cfg,'operator',now=1893456000)
        ledger.reserve('spawn:owned',100,60,now=1893456000);ledger.record('spawn:owned',20,now=1893456000)
        directory=location(root,'objective');directory.mkdir(parents=True,mode=0o700)
        home=directory/'home';home.mkdir(mode=0o700);(home/'sessions').mkdir(mode=0o700)
        binding=dict(objective_id='objective',generation='original',configuration_revision=cfg['revision'],
            state='stopped',identity=dict(unit='codex-wake-objective-test.service',invocation_id='exact',
                control_group='/owned/group',main_pid=123))
        def private(path,value):
            path.write_text(json.dumps(value));path.chmod(0o600)
        private(directory/'binding.json',binding)
        endpoint='unix://'+str(directory/'app-server.sock')
        private(directory/'guard-original.json',dict(wake_root=str(root.resolve()),objective_id='objective',
            generation='original',configuration=cfg,codex_home=str(home),endpoint=endpoint))
        lifecycle=root/'lifecycle';lifecycle.mkdir(mode=0o700)
        private(lifecycle/'spawn.json',dict(thread_id='owned-thread',budget_actor='spawn:owned',
            intent=dict(operation='spawn',configuration=cfg,continuation=policy,
                launch=dict(app_server=endpoint,codex_home=str(home)))))
        log=home/'sessions/owned.jsonl'
        rows=[dict(type='session_meta',payload=dict(id='owned-thread')),
            dict(type='event_msg',payload=dict(type='task_started',turn_id='turn-1')),
            dict(type='event_msg',payload=dict(type='token_count',info=dict(total_token_usage=dict(
                total_tokens=27,input_tokens=25,cached_input_tokens=15,output_tokens=2)))),
            dict(type='event_msg',payload=dict(type='task_complete',turn_id='turn-1'))]
        log.write_text(''.join(json.dumps(row)+'\n' for row in rows));log.chmod(0o600)
        return root,profiles,ledger,log,rows

    def command(self,root,profiles,*extra):
        output=StringIO()
        with (redirect_stdout(output), patch('codex_wake.strict_runtime.SystemdExecution.inspect',
                return_value=dict(populated=False,members=[],state='inactive')),
                patch('codex_wake.measurements.snapshot',return_value=qualified_clock())):
            code=run(['--wake-root',str(root),'sessions','execution','--profiles',str(profiles),
                '--profile','worker','--thread-id','source','--json',*extra])
        return code,json.loads(output.getvalue())

    def test_public_operator_reconcile_settles_only_proven_terminal_cumulative_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root,profiles,ledger,_,_=self.fixture(directory)
            code,result=self.command(root,profiles,'--reconcile')
            self.assertEqual(code,0,result)
            view=ledger.inspect(now=1893456001)
            self.assertEqual(view['tokens_used'],27)
            self.assertTrue(view['actors']['spawn:owned']['settled'])
            self.assertTrue(view['actors']['spawn:owned']['known'])

    def test_native_sessions_permissions_inside_private_home_do_not_block_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            root,profiles,ledger,log,_=self.fixture(directory)
            log.parent.chmod(0o775)  # Actual Codex creates this beneath its private 0700 home.
            code,result=self.command(root,profiles,'--reconcile')
            self.assertEqual(code,0,result)
            self.assertEqual(ledger.inspect(now=1893456001)['tokens_used'],27)

    def test_missing_terminal_or_later_inprogress_keeps_sampled_floor_unknown(self):
        for variant in ('missing_terminal','later_inprogress','counter_after_terminal','decreased'):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as directory:
                root,profiles,ledger,log,rows=self.fixture(directory)
                if variant=='missing_terminal':rows.pop()
                elif variant=='later_inprogress':rows.append(dict(type='event_msg',payload=dict(type='task_started',turn_id='turn-2')))
                elif variant=='counter_after_terminal':rows.append(rows[2])
                else:rows[2]['payload']['info']['total_token_usage']['total_tokens']=10
                log.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                code,result=self.command(root,profiles,'--reconcile')
                self.assertEqual(code,5,result)
                actor=ledger.inspect(now=1893456001)['actors']['spawn:owned']
                self.assertFalse(actor['known'])
                self.assertFalse(actor['settled'])
                self.assertEqual(actor['used'],20 if variant=='decreased' else 27)
                self.assertEqual(actor['reservation'],100)

    def test_nonblocking_fence_reports_lock_busy_without_claiming_final(self):
        import fcntl
        from codex_wake.strict_executor import _NonblockingLedger
        from codex_wake.strict_final_usage import fence_final_usage
        with tempfile.TemporaryDirectory() as directory:
            root,_,ledger,_,_=self.fixture(directory)
            with ledger.lock_path.open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                result=fence_final_usage(_NonblockingLedger(root,'objective'),['spawn:owned'],now=1893456001)
                self.assertEqual(result['reason'],'ledger_lock_busy')
                self.assertEqual(result['state'],'accounting_unknown')

    def test_public_authorization_preserves_usage_and_allows_only_fresh_new_reservation(self):
        import sys
        from codex_wake.strict_runtime import ensure_execution
        with tempfile.TemporaryDirectory() as directory:
            root,profiles,ledger,_,_=self.fixture(directory)
            self.assertEqual(self.command(root,profiles,'--reconcile')[0],0)
            registry=json.loads(profiles.read_text());registry['lifecycle_defaults']['objective_token_limit']=600
            cfg=effective_configuration(registry,'source','worker')
            registry['continuations']['source']['budget_authorization']=dict(action='extend',
                approval='operator explicit renewal',revision=cfg['revision'])
            profiles.write_text(json.dumps(registry))
            with (patch('codex_wake.strict_runtime.SystemdExecution.inspect',return_value=dict(populated=False,members=[],state='inactive')),
                    patch('codex_wake.measurements.snapshot',return_value=qualified_clock()),redirect_stdout(StringIO())):
                self.assertEqual(run(['--wake-root',str(root),'sessions','configuration','--profiles',str(profiles),
                    '--profile','worker','--thread-id','source','--apply-budget-authorization','--json']),0)
            cfg={k:v for k,v in cfg.items() if k not in ('source_thread_id','profile')}
            self.assertEqual(ledger.inspect(now=1893456001)['tokens_used'],27)
            self.assertTrue(ledger.reserve('spawn:new',100,60,now=1893456001)['admitted'])
            layout=location(root,'objective')
            receipt=dict(state='prepared',fingerprint='new',thread_id=None,budget_actor='spawn:new',
                intent=dict(configuration=cfg,continuation=registry['continuations']['source'],
                    launch=dict(codex_home=str(layout/'home'),app_server='unix://'+str(layout/'app-server.sock'),
                        codex_path=sys.executable,cwd=directory,timeout=1)))
            from codex_wake import measurements
            original_deadline=cfg['objective_deadline']
            with patch('codex_wake.measurements.snapshot',side_effect=measurements.TimeUnavailable('lost')),patch(
                    'codex_wake.strict_runtime.SystemdExecution.inspect',return_value=dict(populated=False,members=[],state='inactive')),patch(
                    'codex_wake.strict_runtime.SystemdExecution.launch') as withheld:
                with self.assertRaises(ValueError):
                    ensure_execution(root,receipt)
                withheld.assert_not_called()
            captured={}
            def launch(unit,argv,**kwargs):
                captured.update(json.loads(Path(argv[-1]).read_text()))
                return dict(unit=unit,invocation_id='new',control_group='/new',main_pid=456)
            with (patch('codex_wake.strict_runtime.SystemdExecution.inspect',return_value=dict(populated=False,members=[],state='inactive')),
                    patch('codex_wake.strict_runtime.SystemdExecution.launch',side_effect=launch),
                    patch('codex_wake.strict_runtime.Path.is_socket',return_value=True),
                    patch('codex_wake.native_protocol.native_request',return_value={}),
                    patch('codex_wake.measurements.snapshot',return_value=qualified_clock())):
                ensure_execution(root,receipt)
            self.assertEqual(captured['clock_anchor'],qualified_clock())
            self.assertEqual(captured['started_upper'],qualified_clock()['utc']['upper'])
            self.assertIsNone(captured['started_boottime'])
            self.assertEqual(captured['configuration']['objective_deadline'],original_deadline)
            self.assertEqual(captured['historical_actors'],{'spawn:owned':27})
            self.assertEqual(ledger.inspect(now=1893456001)['tokens_used'],27)
            from codex_wake.strict_runtime import guard_execution
            from codex_wake.records import WakeError
            binding=json.loads((layout/'binding.json').read_text())
            config_path=layout/('guard-'+binding['generation']+'.json')
            legacy=json.loads(config_path.read_text());legacy.pop('clock_anchor')
            config_path.write_text(json.dumps(legacy))
            original=config_path.read_bytes()
            with patch('codex_wake.strict_runtime.read_execution',return_value=binding),patch(
                    'codex_wake.measurements.snapshot') as replacement_clock:
                self.assertFalse(guard_execution(root,receipt))
                self.assertEqual(receipt['reason'],'strict_execution_clock_unqualified')
                with self.assertRaises(WakeError):
                    ensure_execution(root,receipt)
                replacement_clock.assert_not_called()
            self.assertEqual(config_path.read_bytes(),original)


    def test_renewal_rejects_unsettled_or_unknown_prior_actor_even_after_operator_extension(self):
        import sys
        from codex_wake.strict_runtime import ensure_execution
        from codex_wake.records import WakeError
        for known in (True,False):
            with self.subTest(known=known),tempfile.TemporaryDirectory() as directory:
                root,profiles,ledger,_,_=self.fixture(directory)
                if not known:ledger.record('spawn:owned',None,now=1893456000)
                registry=json.loads(profiles.read_text());registry['lifecycle_defaults']['objective_token_limit']=600
                cfg=effective_configuration(registry,'source','worker')
                registry['continuations']['source']['budget_authorization']=dict(action='extend',
                    approval='operator explicit renewal',revision=cfg['revision'])
                profiles.write_text(json.dumps(registry))
                with (patch('codex_wake.strict_runtime.SystemdExecution.inspect',return_value=dict(populated=False,members=[],state='inactive')),
                        patch('codex_wake.measurements.snapshot',return_value=qualified_clock()),redirect_stdout(StringIO())):
                    self.assertEqual(run(['--wake-root',str(root),'sessions','configuration','--profiles',str(profiles),
                        '--profile','worker','--thread-id','source','--apply-budget-authorization','--json']),0)
                cfg={k:v for k,v in cfg.items() if k not in ('source_thread_id','profile')}
                # Unknown accounting may deny a new reservation; the prior actor
                # gate must refuse regardless, without inventing a repair.
                ledger.reserve('spawn:new',100,60,now=1893456001)
                layout=location(root,'objective')
                receipt=dict(state='prepared',fingerprint='new',thread_id=None,budget_actor='spawn:new',
                    intent=dict(configuration=cfg,continuation=registry['continuations']['source'],
                        launch=dict(codex_home=str(layout/'home'),app_server='unix://'+str(layout/'app-server.sock'),
                            codex_path=sys.executable,cwd=directory,timeout=1)))
                with (patch('codex_wake.strict_runtime.SystemdExecution.inspect',return_value=dict(populated=False,members=[],state='inactive')),
                        patch('codex_wake.strict_runtime.SystemdExecution.launch') as launch,
                        patch('codex_wake.measurements.snapshot',return_value=qualified_clock())):
                    with self.assertRaisesRegex(WakeError,'every prior actor settled and known'):
                        ensure_execution(root,receipt)
                    launch.assert_not_called()
                self.assertEqual(ledger.inspect(now=1893456001)['tokens_used'],20)

    def test_live_host_or_changed_invocation_refuses_offline_ledger_effects(self):
        from codex_wake.strict_runtime import reconcile_execution
        for response in (dict(populated=True,members=[123],state='active'),RuntimeError('invocation changed')):
            with self.subTest(response=response),tempfile.TemporaryDirectory() as directory:
                root,_,ledger,_,_=self.fixture(directory)
                with (patch('codex_wake.strict_runtime.SystemdExecution.inspect',side_effect=response if isinstance(response,Exception) else None,
                            return_value=response if isinstance(response,dict) else None),
                        patch('codex_wake.measurements.snapshot',return_value=qualified_clock())):
                    if isinstance(response,Exception):
                        with self.assertRaisesRegex(RuntimeError,'invocation changed'):reconcile_execution(root,'objective')
                    else:
                        result=reconcile_execution(root,'objective')
                        self.assertEqual(result['final_usage']['state'],'accounting_unknown')
                actor=ledger.inspect(now=1893456001)['actors']['spawn:owned']
                self.assertEqual(actor['used'],20)
                self.assertTrue(actor['known'])
                self.assertFalse(actor['settled'])

    def test_malformed_native_usage_is_explicit_unknown_without_losing_sampled_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            root,profiles,ledger,log,rows=self.fixture(directory)
            rows[2]['payload']['info']['total_token_usage']='invalid'
            log.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            code,result=self.command(root,profiles,'--reconcile')
            self.assertEqual(code,5,result)
            actor=ledger.inspect(now=1893456001)['actors']['spawn:owned']
            self.assertFalse(actor['known'])
            self.assertEqual(actor['used'],20)

    def test_proven_change_invalidates_previously_settled_usage_and_preserves_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            root,profiles,ledger,log,rows=self.fixture(directory)
            self.assertEqual(self.command(root,profiles,'--reconcile')[0],0)
            rows[2]['payload']['info']['total_token_usage']['total_tokens']=40
            log.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            code,result=self.command(root,profiles,'--reconcile')
            self.assertEqual(code,5,result)
            actor=ledger.inspect(now=1893456001)['actors']['spawn:owned']
            self.assertFalse(actor['known'])
            self.assertFalse(actor['settled'])
            self.assertEqual(actor['used'],27)

    def test_preflight_stopped_or_unknown_final_is_read_only_before_reservation(self):
        from codex_wake.strict_runtime import preflight_execution
        from codex_wake.records import WakeError
        for new_revision in (False,True):
            with self.subTest(new_revision=new_revision),tempfile.TemporaryDirectory() as directory:
                root,_,ledger,_,_=self.fixture(directory)
                layout=location(root,'objective');path=layout/'binding.json'
                binding=json.loads(path.read_text())
                config=json.loads((layout/'guard-original.json').read_text())['configuration']
                if new_revision:
                    binding['final_usage']={'state':'accounting_unknown'}
                    path.write_text(json.dumps(binding))
                    config['revision']='new-unadmitted-revision'
                before=ledger.path.read_bytes()
                receipt=dict(state='prepared',thread_id=None,fingerprint='new',intent=dict(
                    configuration=config,continuation={'objective_id':'objective'}))
                with (patch('codex_wake.strict_runtime.SystemdExecution.inspect',return_value=dict(populated=False,members=[],state='inactive')),
                        patch('codex_wake.strict_runtime.SystemdExecution.launch') as launch,
                        patch('codex_wake.measurements.snapshot',return_value=qualified_clock())):
                    with self.assertRaisesRegex(WakeError,'final-usage reconciliation' if new_revision else 'is fenced'):
                        preflight_execution(root,receipt)
                    launch.assert_not_called()
                self.assertEqual(ledger.path.read_bytes(),before)
                self.assertEqual(set(ledger.inspect(now=1893456001)['actors']),{'spawn:owned'})
