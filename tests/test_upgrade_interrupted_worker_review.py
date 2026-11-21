"""Explicit independent review of a stopped worker's unconfirmed source snapshot."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import test_upgrade_repair as fixtures
from codex_wake.upgrade_repair import UpgradeRepair


class InterruptedWorkerReviewTests(unittest.TestCase):
    def interrupted(self,root,prerequisite=None):
        source,config,recipe,job=fixtures.UpgradeRepairTests().fixture(root)
        (source/'feature.txt').write_text('upstream\n')
        subprocess.run(['git','add','.'],cwd=source,check=True)
        subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
        config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
        events=root/'evidence/native-events.jsonl';marker=root/'worker-started'
        (root/'worker.py').write_text("import pathlib,subprocess,time;pathlib.Path('feature.txt').write_text('new\\n');subprocess.run(['git','add','feature.txt'],check=True);pathlib.Path("+repr(str(events))+").write_text('{\\\"type\\\":\\\"thread.started\\\",\\\"scope\\\":\\\"fixture_not_model_acceptance\\\"}\\n');pathlib.Path("+repr(str(marker))+").write_text('ready');time.sleep(120)\n")
        reviewer=Path(config['reviewer']['argv'][1])
        reviewer.write_text(reviewer.read_text().replace("pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(r))", "\nif p.get('require_patch_dispositions'):\n r['patch_dispositions']={x['id']:dict(disposition='rewritten',intent=x['intent'],evidence='Independently inspected fixture feature and tests',equivalence='') for x in p['patches']}\npathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(r))"))
        if prerequisite is not None:
            config['regenerate']=[[sys.executable,'-c',"from pathlib import Path; assert Path("+repr(str(prerequisite))+").exists(), 'host prerequisite missing'"]]
        job['limits']['repair_attempts']=1;job['deadline']=time.time()+60
        def guard():
            if marker.exists():raise ValueError('clock_uncertain')
        charges=[]
        result=UpgradeRepair(source,root/'evidence',config,guard=guard,checkpoint=charges.append).run(job,recipe)
        self.assertEqual(result['status'],'held',result)
        state=json.loads((root/'evidence/repair-state.json').read_text())
        job['repair_attempts']=1
        proof=dict(schema_version=1,job_id=job['id'],worker_identity=state['inflight']['process_identity'],
            worker_argv=config['worker']['argv'],boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            observed_monotonic_seconds=time.monotonic(),owned_processes_remaining=[],
            census=dict(includes_cross_process_groups=True,unreadable_processes=[],proc_entries_scanned=1),
            artifacts=[dict(kind='native_events',path=str(events),sha256=hashlib.sha256(events.read_bytes()).hexdigest())])
        census=root/'worker-exit-census.json';census.write_text(json.dumps(proof));census.chmod(0o600)
        return source,config,recipe,job,charges,state,census

    def test_review_only_salvage_retains_interruption_and_never_creates_a_worker_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job,charges,before,census=self.interrupted(root)
            with self.assertRaises(ValueError):UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe)
            receipt=UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe,mode='verify_review_only')
            self.assertEqual(receipt['mode'],'verify_review_only')
            self.assertEqual(receipt['worker_proof']['kind'],'interrupted_worker_no_completion_report')
            result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(dict(job,resume_mode='verify_review_only'),recipe)
            self.assertEqual(result['status'],'reviewed',result)
            self.assertEqual(result['patch_provenance'][0]['disposition'],'rewritten')
            self.assertFalse(result['worker_completed'])
            self.assertEqual(charges,[{'repair_attempts':1}])
            after=json.loads((root/'evidence/repair-state.json').read_text())
            self.assertEqual(after['clock_anchor']['monotonic_deadline'],before['clock_anchor']['monotonic_deadline'])
            self.assertEqual(len([c for c in after['commands'] if c['role']=='worker']),1)
            self.assertFalse(list((root/'evidence').glob('*-worker-response.json')))
            provenance=json.loads(Path(result['prepared_recipe']).read_text())['repair_provenance']
            self.assertEqual(provenance['qualification_basis'],'independent_review_after_interrupted_worker')
            self.assertFalse(provenance['worker_completed'])
            self.assertEqual(provenance['patches'][0]['disposition'],'rewritten')
            self.assertEqual(provenance['original_patch_provenance'][0]['disposition'],'needs_repair')

    def test_unfinished_worker_without_clean_complete_census_cannot_be_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job,charges,before,census=self.interrupted(root)
            proof=json.loads(census.read_text());proof['owned_processes_remaining']=[{'pid':123}]
            census.write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError,'worker_exit_census_unverified'):
                UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe,mode='verify_review_only')
            self.assertEqual(charges,[{'repair_attempts':1}])

    def test_independent_reviewer_must_disposition_every_patch_without_another_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job,charges,before,census=self.interrupted(root)
            reviewer=Path(config['reviewer']['argv'][1])
            reviewer.write_text(reviewer.read_text().replace("if p.get('require_patch_dispositions'):","if False:"))
            UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe,mode='verify_review_only')
            result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(dict(job,resume_mode='verify_review_only'),recipe)
            self.assertEqual(result['status'],'held')
            self.assertEqual(result['reason'],'independent_review_patch_dispositions_required')
            self.assertEqual(charges,[{'repair_attempts':1}])
            self.assertFalse((root/'evidence/prepared-recipe.json').exists())

    def test_native_reviewer_schema_adds_patch_dispositions_only_for_explicit_mode(self):
        import test_upgrade_codex_worker as adapter_fixture
        from codex_wake.upgrade_codex_worker import run
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config,packet,response,home,workspace=adapter_fixture.CodexUpgradeWorkerTests().fixture(root,'reviewer')
            declaration=json.loads(config.read_text());native=Path(declaration['executable'])
            marker="pathlib.Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(report))"
            additional="if 'patch_dispositions' in props:\n report['patch_dispositions']={key:dict(disposition='rewritten',intent=value['properties']['intent']['const'],evidence='fixture independent inspection',equivalence='') for key,value in props['patch_dispositions']['properties'].items()}\n"
            native.write_text(native.read_text().replace(marker,additional+marker))
            declaration['sha256']=hashlib.sha256(native.read_bytes()).hexdigest();config.write_text(json.dumps(declaration))
            ordinary=run(config,'reviewer',packet,response)
            self.assertNotIn('patch_dispositions',ordinary)
            body=json.loads(packet.read_text());body['require_patch_dispositions']=True;packet.write_text(json.dumps(body))
            independent=run(config,'reviewer',packet,response)
            self.assertEqual(set(independent['patch_dispositions']),{'health'})
            self.assertEqual(independent['patch_dispositions']['health']['intent'],'Preserve main-loop nonce health')

    def test_deterministic_verification_failure_can_readmit_without_another_worker_or_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);prerequisite=root/'host-ready'
            source,config,recipe,job,charges,before,census=self.interrupted(root,prerequisite)
            first=UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe,mode='verify_review_only')
            held=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(dict(job,resume_mode='verify_review_only'),recipe)
            self.assertEqual(held['reason'],'verify_review_only_verification_failed')
            original=census.read_bytes();(root/'worker-exit-census-original.json').write_bytes(original)
            proof=json.loads(original);proof['observed_monotonic_seconds']=time.monotonic();census.write_text(json.dumps(proof))
            prerequisite.write_text('ready')
            second=UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe,mode='verify_review_only')
            self.assertEqual(second['monotonic_deadline'],first['monotonic_deadline'])
            reviewed=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(dict(job,resume_mode='verify_review_only'),recipe)
            self.assertEqual(reviewed['status'],'reviewed',reviewed)
            self.assertEqual(charges,[{'repair_attempts':1}])
            state=json.loads((root/'evidence/repair-state.json').read_text())
            self.assertEqual(sum(c['role']=='worker' for c in state['commands']),1)
            self.assertEqual(sum(c['role']=='reviewer' for c in state['commands']),1)
            self.assertEqual(state['verification_readmission_history'][0],first)
            self.assertEqual(second['worker_proof']['prior_clock_uncertainty'],'retained_unclassified')
