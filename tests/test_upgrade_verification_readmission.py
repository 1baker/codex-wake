"""Same-job public controller reconciliation, without another coding worker."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace

import test_upgrade_repair as fixtures
from test_measurements import observation
from codex_wake.upgrade_jobs import UpgradeJobs
from codex_wake.upgrade_pipeline import prepare_reviewed_recipe
from codex_wake.upgrade_repair import _inventory


class VerificationReadmissionTests(unittest.TestCase):
    def test_public_controller_requeues_original_job_and_verifies_at_attempt_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,repair,recipe,_=fixtures.UpgradeRepairTests().fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            (root/'worker.py').write_text("""import json,os,pathlib,subprocess
pathlib.Path('feature.txt').write_text('new\\n');subprocess.run(['git','add','feature.txt'],check=True)
pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(dict(schema_version=1,status='repaired',identity='repairer',patch_dispositions={'feature':dict(disposition='rewritten',evidence='Retained feature')},retirements={})))
""")
            marker=root/'generation-started'
            repair['regenerate']=[[__import__('sys').executable,'-c',"import pathlib,time; marker=pathlib.Path("+repr(str(marker))+"); first=not marker.exists(); pathlib.Path('Cargo.lock').write_text('generated lockfile'); marker.write_text('ready'); time.sleep(120 if first else 0)"]]
            repair.pop('base_revision')
            recipe_path=root/'recipe.json';recipe_path.write_text(json.dumps(recipe))
            target={'host':'fixture','environment':'test'}
            config=dict(schema_version=1,target=target,recipes={'release':str(recipe_path)},repair=repair,
                limits=dict(repair_attempts=1,total_seconds=120,compiler_jobs=2,temporary_bytes=1024**2))
            (root/'upgrade-bot.json').write_text(json.dumps(config))
            actor=SimpleNamespace(subject='owner',client_id='client',grant_id='grant',scopes={'observe','admin'},targets=[target])
            failed=[False]
            def clock():
                if marker.exists() and not failed[0]:
                    failed[0]=True
                    raise FileNotFoundError('simulated original budget scan race')
                return observation(1000)
            owner=UpgradeJobs(root,clock=clock)
            def call(verb,**arguments):
                return owner.execute(actor,'upgrades.'+verb,dict(expected_target=target,**arguments),authorize=lambda:actor)['result']
            call('enable');job=call('start',recipe='release')['job']
            jobdir=root/'upgrade-jobs'/job['id'];jobdir.mkdir()
            files={name:row['sha256'] for name,row in _inventory(source).items()}
            shutil.move(str(source),str(jobdir/'upstream-source'))
            (jobdir/'source-preparation.json').write_text(json.dumps(dict(recipe_sha256=job['recipe_sha256'],base_revision=base,source_files=files)))
            held=call('advance',job_id=job['id'])['job']
            self.assertEqual(held['state'],'held',held)
            self.assertEqual(held['repair_attempts'],1)
            before=json.loads((jobdir/'repair/repair-state.json').read_text())
            self.assertEqual(before['inflight']['role'],'regenerate')
            queued=call('reconcile',job_id=job['id'],mode='verify_only')['job']
            self.assertEqual(queued['id'],held['id'])
            self.assertEqual(queued['state'],'queued')
            self.assertEqual(queued['resume_mode'],'verify_only')
            self.assertEqual(queued['repair_attempts'],held['repair_attempts'])
            self.assertEqual(queued['deadline'],held['deadline'])
            self.assertEqual(queued['clock_anchor']['start'],held['clock_anchor']['start'])
            def no_new_charge(unused):raise AssertionError('unexpected coding charge')
            result=prepare_reviewed_recipe(root,queued,owner.config(),guard=lambda:None,checkpoint=no_new_charge)
            self.assertEqual(result['status'],'reviewed',result)
            after=json.loads((jobdir/'repair/repair-state.json').read_text())
            self.assertEqual([c for c in after['commands'] if c['role']=='worker'],[c for c in before['commands'] if c['role']=='worker'])
