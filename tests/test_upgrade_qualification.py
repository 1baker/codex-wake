"""Qualification observes an exact package and actual subprocess boundaries."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from codex_wake.upgrade_qualification import UpgradeQualification


class QualificationTests(unittest.TestCase):
    def fixture(self, directory):
        root=Path(directory);package=root/'upgrade-jobs/job/build-store/stages/candidate/package'
        native='''#!/usr/bin/env python3
import json,os,sys
for line in sys.stdin:
 v=json.loads(line)
 if 'id' not in v:continue
 result={} if v['method']=='initialize' else {'account':{'type':'chatgpt','email':os.environ['CODEX_HOME'].split('/')[-1]+'@fixture.invalid'}}
 print(json.dumps({'id':v['id'],'result':result}),flush=True)
'''
        for name in ('bin/codex','bin/codex-code-mode-host','codex-resources/bwrap','codex-path/rg'):
            p=package/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(native);p.chmod(0o700)
        (package/'codex-package.json').write_text('{}')
        files={str(p.relative_to(package)):dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),mode=p.stat().st_mode&0o777) for p in package.rglob('*') if p.is_file()}
        job=dict(id='job',key='key',target={'namespace':'fixture'},deadline=time.time()+20,
                 results={'stage':dict(status='staged',channel='modded',files=files,
                    source_identity={'upstream_version':'0.166','revision':'fixture'},
                    build={'executable':str(package/'bin/codex'),'sha256':files['bin/codex']['sha256']})})
        probe=root/'probe.py'
        probe.write_text("import json\nprint(json.dumps({'schema_version':1,'status':'passed','model_requests':0,'checks':{x:True for x in ['scoped_reload','durable_notices','caller_accounting','orphan_output','tui_health','history_visibility','failed_start_recovery','compatible_rollback']},'owned_processes_remaining':[]}))\n")
        import sys
        config=dict(schema_version=1,environment={'kind':'source_fixture'},
            accounts=[dict(alias='a',home=str(root/'accounts/a')),dict(alias='b',home=str(root/'accounts/b'))],
            state_root=str(root/'accounts'),test_files={str(probe):hashlib.sha256(probe.read_bytes()).hexdigest()},
            probes=[dict(id='capabilities',argv=[sys.executable,str(probe)])])
        for account in config['accounts']:Path(account['home']).mkdir(parents=True)
        return root,package,job,config

    def test_exact_package_and_real_metadata_subprocesses_have_fixture_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            receipt=UpgradeQualification(root).run(job,config)
            self.assertEqual(receipt['status'],'fixture_verified',receipt)
            self.assertFalse(receipt['eligible_for_promotion'])
            self.assertEqual(receipt['metadata']['sequence'],['a','b','a'])
            self.assertEqual(receipt['model_requests'],0)
            self.assertEqual(receipt['package_files'],job['results']['stage']['files'])
            self.assertTrue(receipt['receipt_sha256'])

    def test_durable_qualification_uses_owner_guard_across_guest_clock_jump(self):
        from test_measurements import observation

        with tempfile.TemporaryDirectory() as directory:
            root, _, job, config = self.fixture(directory)
            sample = observation(1000)
            job.update(clock_anchor=dict(start=sample, latest=sample), deadline=0)
            qualification = UpgradeQualification(root)
            guarded = qualification.run(job, config, guard=lambda: None)
            self.assertEqual(guarded['status'], 'fixture_verified', guarded)
            unguarded = qualification.run(job, config)
            self.assertEqual(unguarded['status'], 'held')
            self.assertIn('durable upgrade guard required', unguarded['reason'])

    def test_missing_source_provenance_never_qualifies(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            job['results']['stage']['source_identity']={}
            result=UpgradeQualification(root).run(job,config)
            self.assertEqual(result['status'],'held',result)
            self.assertIn('source identity',result['reason'])

    def test_manifest_recovery_claim_cannot_be_omitted_from_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            manifest=package/'codex-package.json'
            manifest.write_text('{"capabilities":{"upgrade_recovery":true}}')
            job['results']['stage']['files']['codex-package.json']['sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
            receipt=UpgradeQualification(root).run(job,config)
            self.assertEqual(receipt['status'],'held',receipt)
            self.assertIn('required capability',receipt['reason'])

    def test_changed_package_auth_needed_and_model_request_are_distinct_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            binary=package/'bin/codex';binary.write_text(binary.read_text()+'# changed\n')
            changed=UpgradeQualification(root).run(job,config)
            self.assertEqual(changed['status'],'held')
            self.assertIn('digest mismatch',changed['reason'])
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            binary=package/'bin/codex';binary.write_text(binary.read_text().replace("{'type':'chatgpt','email':os.environ['CODEX_HOME'].split('/')[-1]+'@fixture.invalid'}",'None'))
            job['results']['stage']['files']['bin/codex']['sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
            job['results']['stage']['build']['sha256']=job['results']['stage']['files']['bin/codex']['sha256']
            auth=UpgradeQualification(root).run(job,config)
            self.assertEqual(auth['status'],'authentication_needed',auth)
            self.assertFalse(auth['eligible_for_promotion'])
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            probe=root/'probe.py';probe.write_text(probe.read_text().replace("'model_requests':0","'model_requests':1"))
            config['test_files'][str(probe)]=hashlib.sha256(probe.read_bytes()).hexdigest()
            forbidden=UpgradeQualification(root).run(job,config)
            self.assertEqual(forbidden['status'],'held',forbidden)
            self.assertIn('model-request boundary',forbidden['reason'])
            self.assertEqual(forbidden['model_requests'],1)

    def test_disable_guard_stops_native_processes_and_test_digest_drift_holds(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            calls=[]
            def guard():
                calls.append(1)
                if len(calls)>3:raise ValueError('disabled during qualification')
            cancelled=UpgradeQualification(root).run(job,config,guard=guard)
            self.assertEqual(cancelled['status'],'held',cancelled)
            self.assertIn('disabled during qualification',cancelled['reason'])
            self.assertFalse(cancelled['eligible_for_promotion'])
            probe=root/'probe.py';probe.write_text(probe.read_text()+'# drift\n')
            drifted=UpgradeQualification(root).run(job,config)
            self.assertEqual(drifted['status'],'held',drifted)
            self.assertIn('test digest mismatch',drifted['reason'])

    def test_official_commit_archive_supported_and_foreign_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            stage=job['results']['stage']
            stage['source']='https://github.com/openai/codex/archive/'+'a'*40+'.tar.gz'
            accepted=UpgradeQualification(root).run(job,config)
            self.assertEqual(accepted['status'],'fixture_verified',accepted)
            stage['source']='https://github.com/untrusted/codex/archive/'+'a'*40+'.tar.gz'
            rejected=UpgradeQualification(root).run(job,config)
            self.assertEqual(rejected['status'],'held',rejected)
            self.assertIn('official upstream',rejected['reason'])

    def test_scripted_fixture_requests_need_explicit_zero_external_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            probe=root/'probe.py'
            probe.write_text(probe.read_text().replace("'model_requests':0","'model_requests':0,'scripted_provider_requests':1"))
            config['test_files'][str(probe)]=hashlib.sha256(probe.read_bytes()).hexdigest()
            missing=UpgradeQualification(root).run(job,config)
            self.assertEqual(missing['status'],'held',missing)
            probe.write_text(probe.read_text().replace("'scripted_provider_requests':1","'scripted_provider_requests':1,'external_provider_requests':0"))
            config['test_files'][str(probe)]=hashlib.sha256(probe.read_bytes()).hexdigest()
            explicit=UpgradeQualification(root).run(job,config)
            self.assertEqual(explicit['status'],'fixture_verified',explicit)
            self.assertEqual(explicit['scripted_provider_requests'],1)
            self.assertEqual(explicit['external_provider_requests'],0)

    def test_account_metadata_must_match_explicit_designated_identity_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=self.fixture(directory)
            config['accounts'][0]['identity_sha256']='0'*64
            receipt=UpgradeQualification(root).run(job,config)
            self.assertEqual(receipt['status'],'authentication_needed',receipt)
            self.assertFalse(receipt['eligible_for_promotion'])
