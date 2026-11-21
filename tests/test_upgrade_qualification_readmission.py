"""Public same-job qualification readmission; synthetic proofs are not native acceptance."""
import json
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace
import unittest

from codex_profiles.upgrades import _atomic
from codex_wake.upgrade_jobs import UpgradeJobs, policy_digest
from codex_wake.upgrade_qualification import content_hash, object_hash, package_inventory
from test_upgrade_promotion import promotion_fixture
from test_measurements import observation


def reviewed_stage(root):
    job,config,unused_home,unused_manifest=promotion_fixture(root)
    directory=root/'upgrade-jobs'/job['id'];stage=job['results']['stage'];repair=job['results']['repair']
    package=Path(stage['build']['executable']).parent.parent
    shutil.copy2('/bin/true',package/'bin/codex')
    stage['files']=package_inventory(package);stage['build']['sha256']=stage['files']['bin/codex']['sha256']
    review=repair['review'];events=directory/'repair/native-events.jsonl';events.write_text('{"type":"turn.completed"}\n')
    review['adapter_provenance']=dict(role='reviewer',identity='reviewer',events=str(events),events_sha256=content_hash(events),evidence_scope='native_source_maintenance_execution_not_installed_qualification')
    response=directory/'repair/2-reviewer-response.json';_atomic(response,review);review['report_sha256']=content_hash(response)
    original=Path(job['recipe_path']);recipe=json.loads(original.read_text());recipe.update(source=dict(official_url='https://github.com/openai/codex/archive/'+'a'*40+'.tar.gz'),build=[['host-build']],qualify=[['host-probe']],evidence_scope='opaque host campaign label')
    _atomic(original,recipe);job['recipe_sha256']=content_hash(original)
    prepared=Path(repair['prepared_recipe']);value=json.loads(prepared.read_text());value.update(recipe);value['source']=dict(recipe['source'],tree=str(directory/'repair/reviewed-source'),files=stage['source_identity']['source_files']);value['repair_provenance']=dict(candidate_digest=repair['candidate_digest'],tests_digest=repair['tests_digest'],review=review);_atomic(prepared,value)
    stage.update(source=recipe['source']['official_url'],recipe_sha256=content_hash(prepared),evidence_scope=recipe['evidence_scope'],commands=[dict(phase='build',argv=['host-build'],exit=0),dict(phase='qualify',argv=['host-probe'],exit=0)])
    stage['qualification_reports']=[dict(schema_version=1,status='passed',native_sha256=stage['build']['sha256'],model_requests=0,external_provider_requests=0,owned_processes_remaining=[])]
    _atomic(directory/'build-store/stages'/job['stage_id']/'receipt.json',stage)
    config['repair']['worker']['argv']=['host-worker'];config['repair']['reviewer']['argv']=['host-reviewer']
    config['repair']['verify']=[['host-verify']]
    _atomic(directory/'repair/repair-state.json',dict(status='reviewed',result=repair,commands=[dict(role='verify',argv=['host-verify'],status='completed',exit_code=0),dict(role='reviewer',argv=['host-reviewer'],status='completed',exit_code=0)]))
    _atomic(directory/'source-preparation.json',dict(recipe_sha256=job['recipe_sha256']))
    old=dict(schema_version=1,status='held',reason='native source-build provenance required',job_id=job['id'],job_key=job['key'],target=job['target'],configuration_sha256=object_hash(config['qualification']),candidate_sha256=object_hash(stage),package_sha256=object_hash(stage['files']),owned_processes_remaining=[],receipt_path=str(directory/'qualification/receipt.json'))
    old['receipt_sha256']=object_hash(old);_atomic(Path(old['receipt_path']),old);job['results']['qualification']=old
    sample = observation(1000)
    owner = UpgradeJobs(root, clock=lambda: sample)
    job.update(state='held',reason=old['reason'],recipe='release',repair_attempts=2,worker=None,active_phase=None,
        limits=dict(repair_attempts=2,total_seconds=100,compiler_jobs=2,temporary_bytes=1024**2),
        clock_anchor=dict(start=sample,latest=sample))
    config.update(recipes=dict(release=str(original)),limits=job['limits']);job['policy_sha256']=policy_digest(config);_atomic(root/'upgrade-bot.json',config);_atomic(root/'upgrade-jobs/state.json',dict(schema_version=1,enabled=True,generation=1,jobs={job['id']:job},events=[]))
    actor=SimpleNamespace(subject='owner',client_id='client',grant_id='grant',scopes={'observe','admin'},targets=[job['target']])
    return owner,actor,job,config


class QualificationReadmissionTests(unittest.TestCase):
    def test_public_readmission_preserves_original_hold_and_queues_only_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owner,actor,job,config=reviewed_stage(root)
            old=Path(job['results']['qualification']['receipt_path']).read_bytes()
            value=owner.execute(actor,'upgrades.reconcile',dict(expected_target=job['target'],job_id=job['id'],mode='qualification_only'),authorize=lambda:actor)['result']['job']
            self.assertEqual(value['state'],'qualifying')
            for key in ('id','deadline','repair_attempts','limits','policy_sha256','clock_anchor'):
                if key!='clock_anchor':self.assertEqual(value[key],job[key])
            self.assertEqual(value['clock_anchor']['start'],job['clock_anchor']['start'])
            receipt=value['reconciliations'][-1]['receipt']
            self.assertEqual(Path(receipt['previous_qualification_path']).read_bytes(),old)
            self.assertEqual(receipt['provenance']['candidate_digest'],job['results']['repair']['candidate_digest'])
            self.assertEqual(value['results']['stage'],job['results']['stage'])

    def test_public_readmission_refuses_changed_source_tests_review_package_and_policy(self):
        from codex_wake.managed_inventory import InventoryError
        for changed in ('source','tests','review','package','test_program','policy'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);owner,actor,job,config=reviewed_stage(root)
                original_state=(root/'upgrade-jobs/state.json').read_bytes()
                if changed in ('source','tests'):
                    source=root/'upgrade-jobs'/job['id']/'repair/reviewed-source'
                    (source/('code.rs' if changed=='source' else 'tests/proof.rs')).write_text('changed\n')
                elif changed=='review':
                    (root/'upgrade-jobs'/job['id']/'repair/2-reviewer-response.json').write_text('{}')
                elif changed=='package':Path(job['results']['stage']['build']['executable']).write_text('changed')
                elif changed=='test_program':Path(next(iter(config['qualification']['test_files']))).write_text('changed')
                else:
                    config['limits']['repair_attempts']=3;_atomic(root/'upgrade-bot.json',config)
                with self.assertRaises(InventoryError):
                    owner.execute(actor,'upgrades.reconcile',dict(expected_target=job['target'],job_id=job['id'],mode='qualification_only'),authorize=lambda:actor)
                self.assertEqual((root/'upgrade-jobs/state.json').read_bytes(),original_state)

    def test_unknown_scope_with_derived_proof_still_requires_exact_native_version(self):
        from codex_wake.upgrade_qualification import UpgradeQualification,QualificationError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owner,actor,job,config=reviewed_stage(root)
            qualification=UpgradeQualification(root);qualification.owned_groups=[]
            with self.assertRaisesRegex(QualificationError,'native executable version differs'):
                qualification.genuine_provenance(job['results']['stage'],Path(job['results']['stage']['build']['executable']).parent.parent,job,lambda:None)
