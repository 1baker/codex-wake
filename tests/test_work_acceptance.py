"""Independent work acceptance at the task/contract seam, never worker prose."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from codex_wake.session_permissions import PermissionStore, Principal
from codex_wake.task_briefs import BriefAuthority, TaskBriefStore
from codex_wake.work_acceptance import WorkAcceptance


class WorkAcceptanceTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from codex_wake import measurements
        self._ticks = 0
        def clock():
            self._ticks += 10000
            return dict(reason='authenticated_utc', utc=dict(status='network', lower=100, upper=100),
                valid_for_ns=300000000000, counter=dict(
                epoch='c357309d-c209-4467-b757-e1488e6b1aaa', counter=self._ticks,
                frequency=1000000, rate_ppm=0))
        clock_patch = patch.object(measurements, 'snapshot', side_effect=clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'wake'
        self.workspace = Path(self.tmp.name) / 'workspace'
        self.workspace.mkdir()
        self.artifact = self.workspace / 'result.txt'
        self.artifact.write_text('verified result')
        self.authority = BriefAuthority('operator:test', 'operator')
        self.principal = Principal('operator:test', 'operator')
        brief = dict(objective='Deliver result', phase='implementation', non_goals=['No release'],
                     acceptance=['Exact result passes'], context=[], workspace=str(self.workspace),
                     allocation_ref='existing', permission_ref='existing')
        store = TaskBriefStore(self.root)
        revision = store.propose('task', brief, authority=self.authority)
        store.approve('task', revision['revision'], authority=self.authority)
        store.admit('task', 'assignment', authority=self.authority)
        PermissionStore(self.root).configure({'version': 1, 'global': {'actions': {'acceptance.verify': 'allow'}}},
                                             self.principal, expected_revision=0)
        self.checks = dict(artifacts=[dict(name='result', path=str(self.artifact),
                            sha256=hashlib.sha256(b'verified result').hexdigest(), required=True)], verifiers=[], decisions=[])
        self.owner = WorkAcceptance(self.root, now=lambda: 100.0)

    def test_frozen_exact_artifact_is_accepted_and_changed_evidence_is_unknown(self):
        self.owner.define('contract', 'task', 'assignment', self.checks, authority=self.authority, principal=self.principal)
        value = self.owner.evaluate('contract', authority=self.authority, principal=self.principal)
        self.assertEqual(value['status'], 'accepted')
        self.assertEqual(value['pin']['revision'], 1)
        self.artifact.write_text('changed after acceptance')
        self.assertEqual(self.owner.inspect('contract', authority=self.authority, principal=self.principal)['status'], 'unknown')
        self.assertEqual(self.owner.evaluate('contract', authority=self.authority, principal=self.principal)['status'], 'unknown')

    def test_required_verifier_failure_rejects_work_and_infrastructure_error_is_unknown(self):
        import os
        import sys
        from codex_wake.process import process_identity
        from codex_wake.resource_claims import Claimant, ResourceClaims
        current = process_identity(os.getpid())
        claimant = Claimant('agent_' + '1' * 32, str(self.workspace),
            dict(pid=os.getpid(), start_ticks=current['start_time_ticks'], boot_id=current['boot_id']), self.owner.now())
        claim = ResourceClaims(self.root, now=self.owner.now).claim('worktree', self.workspace, claimant)
        for name, code, expected in [('failed', 1, 'rejected'), ('broken', 2, 'unknown'), ('passed', 0, 'accepted')]:
            with self.subTest(code=code):
                checks = dict(self.checks, verifiers=[dict(name='tests', argv=[str(Path(sys.executable).resolve()), '-c', f'raise SystemExit({code})'],
                    timeout=2, pass_codes=[0], fail_codes=[1])], claim=dict(claim_id=claim['claim_id'], generation=1))
                self.owner.define(name, 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
                receipt = self.owner.evaluate(name, authority=self.authority, principal=self.principal, claimant=claimant)
                self.assertEqual(receipt['status'], expected)

    def test_clock_discontinuity_refuses_verifier_effect_until_observation_is_current(self):
        import os
        import sys
        from codex_wake.process import process_identity
        from codex_wake.resource_claims import Claimant, ResourceClaims, ResourceClaimError
        current = process_identity(os.getpid())
        claimant = Claimant('agent_' + '1' * 32, str(self.workspace),
            dict(pid=os.getpid(), start_ticks=current['start_time_ticks'], boot_id=current['boot_id']), 100.0)
        claim = ResourceClaims(self.root, now=self.owner.now).claim('worktree', self.workspace, claimant)
        marker = self.workspace / 'clock-effect'
        checks = dict(self.checks, verifiers=[dict(name='effect', argv=[str(Path(sys.executable).resolve()), '-c',
            f"from pathlib import Path; Path({str(marker)!r}).write_text('once')"],
            timeout=2, pass_codes=[0], fail_codes=[1])], claim=dict(claim_id=claim['claim_id'], generation=1))
        self.owner.define('clock', 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
        for now in (99.0, 131.0):
            with self.subTest(now=now):
                self.owner.now = lambda: now
                with self.assertRaises(ResourceClaimError) as denied:
                    self.owner.evaluate('clock', authority=self.authority, principal=self.principal, claimant=claimant)
                self.assertEqual(denied.exception.code, 'owner_unqualified')
                self.assertFalse(marker.exists())
        self.owner.now = lambda: 100.0
        result = self.owner.evaluate('clock', authority=self.authority, principal=self.principal, claimant=claimant)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(marker.read_text(), 'once')

    def test_explicit_human_decision_is_bound_to_contract_snapshot_and_authority(self):
        from codex_wake.records import WakeError
        checks = dict(self.checks, decisions=[dict(name='review', kind='human', required=True)])
        self.owner.define('reviewed', 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
        self.assertEqual(self.owner.evaluate('reviewed', authority=self.authority, principal=self.principal)['status'], 'unknown')
        worker = BriefAuthority('worker', 'worker', ('task',))
        with self.assertRaises(WakeError):
            self.owner.decide('reviewed', 'review', 'accepted', authority=worker, principal=Principal('worker', tasks=('task',)), expires_at=10**12)
        self.owner.decide('reviewed', 'review', 'accepted', authority=self.authority, principal=self.principal, expires_at=10**12)
        self.assertEqual(self.owner.evaluate('reviewed', authority=self.authority, principal=self.principal)['status'], 'accepted')
        self.artifact.write_text('new work cannot inherit a past decision')
        self.assertEqual(self.owner.evaluate('reviewed', authority=self.authority, principal=self.principal)['status'], 'unknown')

    def test_git_identity_and_expired_judgment_invalidate_prior_acceptance(self):
        import subprocess
        import time
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.workspace), *args], stderr=subprocess.DEVNULL, text=True).strip()
        git('init', '-q')
        git('add', 'result.txt')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        head = git('rev-parse', 'HEAD')
        checks = dict(self.checks, git_commit=head, decisions=[dict(name='review', kind='human', required=True)])
        self.owner.define('git-work', 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
        expires = time.time() + 60
        self.owner.decide('git-work', 'review', 'accepted', authority=self.authority, principal=self.principal, expires_at=expires)
        self.assertEqual(self.owner.evaluate('git-work', authority=self.authority, principal=self.principal)['status'], 'accepted')
        self.owner.now = lambda: expires + 1
        self.assertEqual(self.owner.inspect('git-work', authority=self.authority, principal=self.principal)['status'], 'unknown')
        self.owner.now = time.time
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'new commit')
        self.assertEqual(self.owner.inspect('git-work', authority=self.authority, principal=self.principal)['status'], 'unknown')

    def test_public_cli_uses_real_operator_capability_and_worker_cannot_define(self):
        import contextlib
        import io
        import json
        from codex_wake.a2a_bus import BusStore
        from codex_wake.work_acceptance_commands import register_parser, run
        import argparse
        bus, capability = BusStore.configure(Path(self.tmp.name) / 'bus')
        parser = argparse.ArgumentParser()
        register_parser(parser.add_subparsers(dest='command', required=True))
        path = Path(self.tmp.name) / 'checks.json'
        path.write_text(json.dumps(self.checks))
        common = ['--contract-id', 'cli', '--bus-root', str(bus.root), '--operator-capability', str(capability)]
        def call(verb, *extra):
            args = parser.parse_args(['acceptance', verb, *common, *extra, '--json'])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = run(args, self.root)
            return code, json.loads(output.getvalue())
        code, value = call('define', '--task-id', 'task', '--assignment-id', 'assignment', '--checks-file', str(path))
        self.assertEqual(code, 0, value)
        code, value = call('evaluate')
        self.assertEqual(code, 0, value)
        self.assertEqual(value['status'], 'accepted')
        code, value = call('inspect')
        self.assertEqual(code, 0, value)
        self.assertEqual(value['status'], 'accepted')

    def test_missing_artifact_pin_and_timeout_never_accept_or_run_after_revocation(self):
        import os
        import sys
        from codex_wake.records import WakeError
        from codex_wake.process import process_identity
        from codex_wake.resource_claims import Claimant, ResourceClaims
        worker = BriefAuthority('worker', 'worker', ('task',))
        with self.assertRaises(WakeError):
            self.owner.define('worker', 'task', 'assignment', self.checks, authority=worker, principal=Principal('worker', tasks=('task',)))
        self.owner.define('missing', 'task', 'assignment', self.checks, authority=self.authority, principal=self.principal)
        self.artifact.unlink()
        self.assertEqual(self.owner.evaluate('missing', authority=self.authority, principal=self.principal)['status'], 'unknown')
        self.artifact.write_text('verified result')
        native = process_identity(os.getpid())
        claimant = Claimant('agent_' + '1' * 32, str(self.workspace),
            dict(pid=os.getpid(), start_ticks=native['start_time_ticks'], boot_id=native['boot_id']), self.owner.now())
        claim = ResourceClaims(self.root, now=self.owner.now).claim('worktree', self.workspace, claimant)
        checks = dict(self.checks, verifiers=[dict(name='bounded', argv=[str(Path(sys.executable).resolve()), '-c', 'import time; time.sleep(5)'],
            timeout=.05, pass_codes=[0], fail_codes=[1])], claim=dict(claim_id=claim['claim_id'], generation=1))
        self.owner.define('timeout', 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
        self.assertEqual(self.owner.evaluate('timeout', authority=self.authority, principal=self.principal, claimant=claimant)['status'], 'unknown')
        PermissionStore(self.root).configure({'version': 1, 'global': {'actions': {'acceptance.verify': 'deny'}}}, self.principal, expected_revision=1)
        with self.assertRaises(WakeError):
            self.owner.evaluate('missing', authority=self.authority, principal=self.principal)
        # A previously approved contract cannot manufacture an unavailable task pin.
        PermissionStore(self.root).configure({'version': 1, 'global': {'actions': {'acceptance.verify': 'allow'}}}, self.principal, expected_revision=2)
        for path in (self.root / 'task-briefs').glob('*.json'):
            path.unlink()
        self.assertEqual(self.owner.evaluate('missing', authority=self.authority, principal=self.principal)['status'], 'unknown')

    def test_verifier_scope_changes_stop_later_effects_and_invalidate_publication(self):
        from dataclasses import replace
        import os
        import sys
        from codex_wake.process import process_identity
        from codex_wake.resource_claims import Claimant, ResourceClaims
        native = process_identity(os.getpid())
        claimant = Claimant('agent_' + '1' * 32, str(self.workspace),
            dict(pid=os.getpid(), start_ticks=native['start_time_ticks'], boot_id=native['boot_id']), self.owner.now())
        claim = ResourceClaims(self.root, now=self.owner.now).claim('worktree', self.workspace, claimant)
        marker = self.workspace / 'must-not-run'
        for mode in ('artifact', 'pin'):
            with self.subTest(mode=mode):
                self.artifact.write_text('verified result')
                marker.unlink(missing_ok=True)
                target = self.artifact if mode == 'artifact' else self.root / 'task-briefs'
                code = (f"from pathlib import Path; p=Path({str(target)!r}); "
                        + ("p.write_text('changed')" if mode == 'artifact' else "p.rename(p.with_name('lost-briefs'))"))
                def verifier(name, source):
                    return dict(name=name, argv=[str(Path(sys.executable).resolve()), '-c', source],
                                timeout=2, pass_codes=[0], fail_codes=[1])
                checks = dict(self.checks, verifiers=[verifier('change', code),
                    verifier('later', f"from pathlib import Path; Path({str(marker)!r}).touch()")],
                    claim=dict(claim_id=claim['claim_id'], generation=1))
                self.owner.define(mode, 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
                claimant = replace(claimant, observed_at=self.owner.now())
                result = self.owner.evaluate(mode, authority=self.authority, principal=self.principal, claimant=claimant)
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(marker.exists(), 'stale scope must stop the next verifier effect')
                self.artifact.write_text('verified result')
        # Pin loss in the final verifier must also invalidate its own publication.
        import shutil
        shutil.rmtree(self.root / 'task-briefs', ignore_errors=True)
        (self.root / 'lost-briefs').rename(self.root / 'task-briefs')
        checks['verifiers'] = checks['verifiers'][:1]
        self.owner.define('final-pin', 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
        claimant = replace(claimant, observed_at=self.owner.now())
        result = self.owner.evaluate('final-pin', authority=self.authority, principal=self.principal, claimant=claimant)
        self.assertEqual(result['status'], 'unknown')

    def test_missing_frozen_executable_retains_unknown_receipt(self):
        import os
        from codex_wake.process import process_identity
        from codex_wake.resource_claims import Claimant, ResourceClaims
        executable = self.workspace / 'approved-verifier'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o700)
        native = process_identity(os.getpid())
        claimant = Claimant('agent_' + '1' * 32, str(self.workspace),
            dict(pid=os.getpid(), start_ticks=native['start_time_ticks'], boot_id=native['boot_id']), self.owner.now())
        claim = ResourceClaims(self.root, now=self.owner.now).claim('worktree', self.workspace, claimant)
        checks = dict(self.checks, verifiers=[dict(name='approved', argv=[str(executable)], timeout=2,
            pass_codes=[0], fail_codes=[1])], claim=dict(claim_id=claim['claim_id'], generation=1))
        self.owner.define('executable', 'task', 'assignment', checks, authority=self.authority, principal=self.principal)
        self.assertEqual(self.owner.evaluate('executable', authority=self.authority,
            principal=self.principal, claimant=claimant)['status'], 'accepted')
        executable.unlink()
        result = self.owner.evaluate('executable', authority=self.authority, principal=self.principal, claimant=claimant)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['checks'][0]['reason'], 'verifier_unavailable')
        inspected = self.owner.inspect('executable', authority=self.authority, principal=self.principal)
        self.assertEqual(inspected['status'], 'unknown')
        self.assertEqual(inspected['original_receipt'], result)

    def test_executable_cli_and_native_mcp_share_approved_contract(self):
        import contextlib
        import io
        import json
        from codex_wake.a2a_bus import BusStore
        from codex_wake.cli import run
        from codex_wake.mcp_server import CommandRunner
        bus, capability = BusStore.configure(Path(self.tmp.name) / 'caller-bus')
        path = Path(self.tmp.name) / 'hub-checks.json'
        path.write_text(json.dumps(self.checks))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run(['--wake-root', str(self.root), 'acceptance', 'define', '--contract-id', 'hub',
                '--task-id', 'task', '--assignment-id', 'assignment', '--checks-file', str(path),
                '--bus-root', str(bus.root), '--operator-capability', str(capability), '--json'])
        self.assertEqual(code, 0, output.getvalue())
        thread = '00000000-0000-7000-8000-000000000335'
        delegation = Path(self.tmp.name) / 'delegation.json'
        delegation.write_text(json.dumps(dict(version=1, controllers={thread: ['task']})))
        delegation.chmod(0o600)
        meta = dict(threadId=thread, sessionId=thread, callId='acceptance',
            **{'x-codex-turn-metadata': dict(thread_id=thread, session_id=thread, turn_id='turn')})
        runner = CommandRunner(wake_root=self.root, harness_policy=delegation)
        value, failed = runner.call('wake_acceptance_evaluate', dict(caller_thread_id=thread, contract_id='hub'), native_context=meta)
        self.assertFalse(failed, value)
        self.assertEqual(value['status'], 'accepted')
        denied, failed = runner.call('wake_acceptance_evaluate', dict(caller_thread_id=thread, contract_id='hub'))
        self.assertTrue(failed, denied)
