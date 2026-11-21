"""Public repair executor acceptance, using real Git/process boundaries."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from codex_wake.upgrade_repair import UpgradeRepair


class UpgradeRepairTests(unittest.TestCase):
    def fixture(self, root):
        source=root/'source';source.mkdir()
        subprocess.run(['git','init','-q',str(source)],check=True)
        subprocess.run(['git','config','user.email','fixture@example.invalid'],cwd=source,check=True)
        subprocess.run(['git','config','user.name','Fixture'],cwd=source,check=True)
        (source/'feature.txt').write_text('old\n')
        subprocess.run(['git','add','.'],cwd=source,check=True)
        subprocess.run(['git','commit','-qm','base'],cwd=source,check=True)
        (source/'feature.txt').write_text('new\n')
        patch=root/'feature.patch';patch.write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=source))
        subprocess.run(['git','checkout','--','.'],cwd=source,check=True)
        reviewer=root/'review.py'
        reviewer.write_text("""import json,os,pathlib
p=json.loads(pathlib.Path(os.environ['CODEX_UPGRADE_PACKET']).read_text())
r=dict(schema_version=1,status='approved',reviewer='independent',candidate_digest=p['candidate_digest'],tests_digest=p['tests_digest'],capabilities={c:'Verified feature and unchanged acceptance contract' for c in p['required_capabilities']},retirements={})
pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(r))
""")
        config=dict(base_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),patches=[dict(path=str(patch),sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),id='feature',intent='feature remains new')],
            worker=dict(identity='repairer',argv=[sys.executable,str(root/'worker.py')]),
            reviewer=dict(identity='independent',argv=[sys.executable,str(reviewer)]),
            verify=[[sys.executable,'-c',"from pathlib import Path; assert Path('feature.txt').read_text() == 'new\\n'"]],regenerate=[])
        recipe=dict(schema_version=1,id='candidate',channel='modded',upstream_version='0.166.0',revision='fixture',source=dict(official_url='https://github.com/openai/codex/releases/download/fixture/source.tar'),patches=config['patches'],build=[],qualify=[])
        job=dict(id='job-one',deadline=time.time()+30,repair_attempts=0,limits=dict(repair_attempts=3,total_seconds=30,temporary_bytes=1024**2),required_capabilities=['scoped_reload'])
        return source,config,recipe,job

    def test_clean_replay_is_reviewed_and_snapshot_is_pinned_for_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'reviewed',result)
            prepared=json.loads(Path(result['prepared_recipe']).read_text())
            snapshot=Path(prepared['source']['tree'])
            self.assertEqual((snapshot/'feature.txt').read_text(),'new\n')
            self.assertEqual(prepared['patches'],[])
            self.assertEqual(prepared['source']['files']['feature.txt'],hashlib.sha256(b'new\n').hexdigest())
            self.assertEqual(result['repair_attempts'],0)
            self.assertEqual(result['review']['reviewer'],'independent')
            self.assertEqual(result['patch_provenance'][0]['disposition'],'applied')

    def test_fresh_strict_review_requires_every_patch_without_a_coding_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            job['limits']['repair_attempts']=0
            config['reviewer']['require_patch_dispositions']=True
            charges=[]
            result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(job,recipe)
            self.assertEqual(result['status'],'held',result)
            self.assertEqual(result['reason'],'independent_review_patch_dispositions_required')
            self.assertEqual(charges,[])
            self.assertEqual(result['repair_attempts'],0)

    def test_fresh_strict_review_publishes_independent_patch_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            job['limits']['repair_attempts']=0
            config['reviewer']['require_patch_dispositions']=True
            reviewer=Path(config['reviewer']['argv'][1])
            reviewer.write_text(reviewer.read_text().replace("pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(r))",
                "r['patch_dispositions']={x['id']:dict(disposition='applied',intent=x['intent'],evidence='Independently checked feature and tests',equivalence='') for x in p['patches']}\npathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(r))"))
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'reviewed',result)
            self.assertEqual(result['repair_attempts'],0)
            self.assertEqual(result['patch_provenance'][0]['basis'],'independent_review')
            prepared=json.loads(Path(result['prepared_recipe']).read_text())
            self.assertEqual(prepared['repair_provenance']['patches'],result['patch_provenance'])
            self.assertEqual(prepared['repair_provenance']['original_patch_provenance'][0]['disposition'],'applied')
            state=json.loads((root/'evidence/repair-state.json').read_text())
            self.assertEqual(sum(x['role']=='worker' for x in state['commands']),0)
            self.assertEqual(sum(x['role']=='reviewer' for x in state['commands']),1)

    def test_zero_coding_job_explains_failure_without_submitting_a_worker(self):
        for failure in ('verification','review'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source,config,recipe,job=self.fixture(root)
                job['limits']['repair_attempts']=0
                if failure=='verification':config['verify']=[[sys.executable,'-c','raise SystemExit(23)']]
                else:
                    reviewer=Path(config['reviewer']['argv'][1])
                    reviewer.write_text(reviewer.read_text().replace("status='approved'","status='rejected'"))
                charges=[]
                result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(job,recipe)
                self.assertEqual(result['status'],'held',result)
                self.assertEqual(result['reason'],'coding_disabled_'+('verification_failed' if failure=='verification' else 'review_rejected'))
                self.assertEqual(charges,[])
                self.assertEqual(result['repair_attempts'],0)
                state=json.loads((root/'evidence/repair-state.json').read_text())
                self.assertFalse(any(x['role']=='worker' for x in state['commands']))

    def test_conflict_worker_repairs_and_spends_persisted_attempt_before_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            worker=root/'worker.py';worker.write_text("""import json,os,pathlib,subprocess
pathlib.Path('feature.txt').write_text('new\\n')
subprocess.run(['git','add','feature.txt'],check=True)
pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(dict(schema_version=1,status='repaired',identity='repairer',patch_dispositions={'feature':dict(disposition='rewritten',evidence='Retained requested feature on changed upstream')},retirements={})))
""")
            charges=[]
            result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(job,recipe)
            self.assertEqual(result['status'],'reviewed',result)
            self.assertEqual(charges,[{'repair_attempts':1}])
            self.assertEqual(result['patch_provenance'][0]['disposition'],'rewritten')
            self.assertIn('tui_health',result['review']['capabilities'])
            self.assertIn('orphan_output',result['review']['capabilities'])
            again=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(again['repair_attempts'],1)

    def test_worker_cannot_omit_later_patches_or_claim_another_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            (root/'worker.py').write_text("""import json,os,pathlib,subprocess
pathlib.Path('feature.txt').write_text('new\\n')
subprocess.run(['git','add','feature.txt'],check=True)
pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(dict(schema_version=1,status='repaired',identity='unknown',patch_dispositions={},retirements={})))
""")
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'held',result)
            self.assertEqual(result['reason'],'worker_identity_or_status_mismatch')

    def test_staged_conflict_markers_cannot_be_reviewed_as_a_clean_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            job['limits']['repair_attempts']=1
            (root/'worker.py').write_text("""import json,os,pathlib,subprocess
pathlib.Path('feature.txt').write_text('new\\n')
pathlib.Path('other.rs').write_text('<<<<<<< ours\\na\\n=======\\nb\\n>>>>>>> theirs\\n')
subprocess.run(['git','add','.'],check=True)
pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(dict(schema_version=1,status='repaired',identity='repairer',patch_dispositions={'feature':dict(disposition='rewritten',evidence='ported')},retirements={})))
""")
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'held',result)
            self.assertEqual(result['reason'],'repair_attempts_exhausted')

    def test_host_repair_config_cannot_omit_original_recipe_patches(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            recipe['patches']=json.loads(json.dumps(recipe['patches']))
            recipe['patches'].append(dict(path=str(root/'omitted.patch'),sha256='a'*64))
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'held',result)
            self.assertEqual(result['reason'],'original_patch_stack_mismatch')

    def test_pinned_host_tool_cannot_fall_back_to_another_path(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            for name in ('sealed','fallback'):
                folder=root/name;folder.mkdir()
                tool=folder/'fixture-cargo';tool.write_text('#!/bin/sh\nexit 0\n');tool.chmod(0o700)
            expected=root/'sealed/fixture-cargo'
            config['host_tools']={'fixture-cargo':dict(path=str(expected),sha256=hashlib.sha256(expected.read_bytes()).hexdigest())}
            config['verify'].append([sys.executable,'-c',"import subprocess;subprocess.run(['fixture-cargo'],check=True)"])
            charges=[]
            with patch.dict(os.environ,PATH=str(root/'fallback')+os.pathsep+os.environ['PATH']):
                result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(job,recipe)
            self.assertEqual(result['status'],'held',result)
            self.assertEqual(result['reason'],'host_tool_path_mismatch: fixture-cargo')
            self.assertEqual(charges,[])
            self.assertEqual((source/'feature.txt').read_text(),'old\n')

    def test_pinned_host_tool_requires_matching_bytes_before_generation(self):
        import os
        from unittest.mock import patch
        for changed in (False,True):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source,config,recipe,job=self.fixture(root)
                tools=root/'tools';tools.mkdir();marker=root/'generated'
                tool=tools/'fixture-cargo'
                tool.write_text('#!'+sys.executable+'\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text("generated")\n')
                tool.chmod(0o700)
                config['host_tools']={'fixture-cargo':dict(path=str(tool),sha256=hashlib.sha256(tool.read_bytes()).hexdigest())}
                config['regenerate']=[[sys.executable,'-c',"import subprocess;subprocess.run(['fixture-cargo'],check=True)"]]
                if changed:tool.write_text(tool.read_text()+'# replaced\n')
                with patch.dict(os.environ,PATH=str(tools)+os.pathsep+os.environ['PATH']):
                    result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
                self.assertEqual(result['status'],'held' if changed else 'reviewed',result)
                self.assertEqual(marker.exists(),not changed)
                if changed:self.assertEqual(result['reason'],'host_tool_hash_mismatch: fixture-cargo')

    def test_reviewer_source_mutation_invalidates_approval_and_generated_files_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            reviewer=Path(config['reviewer']['argv'][1])
            reviewer.write_text(reviewer.read_text()+"\npathlib.Path('generated.rs').write_text('changed after review')\n")
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'held',result)
            self.assertEqual(result['reason'],'candidate_changed_during_review')

    def test_crash_during_attempt_checkpoint_keeps_the_attempt_charged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            def interrupted(unused):raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                UpgradeRepair(source,root/'evidence',config,checkpoint=interrupted).run(job,recipe)
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'held')
            self.assertEqual(result['repair_attempts'],1)
            self.assertEqual(result['reason'],'interrupted_repair_reconcile_required')

    def test_upstream_workspace_pin_must_match_before_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            config['base_revision']='a'*40
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'held',result)
            self.assertEqual(result['reason'],'upstream_source_identity_mismatch')
            self.assertEqual((source/'feature.txt').read_text(),'old\n')

    def test_verifier_build_cache_is_owned_outside_candidate_and_snapshot_with_compiler_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            # A source directory named target is legitimate and must not be
            # excluded merely because Cargo commonly uses that name for output.
            (source/'target').mkdir()
            (source/'target/source.rs').write_text('legitimate source\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','source named target'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            config['verify'].append([sys.executable,'-c',
                "import os; from pathlib import Path; assert os.environ['CARGO_BUILD_JOBS']=='2'; cache=Path(os.environ.get('CARGO_TARGET_DIR','target')); cache.mkdir(exist_ok=True,parents=True); (cache/'compiler.bin').write_bytes(b'compiled-cache')"])
            result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
            self.assertEqual(result['status'],'reviewed',result)
            prepared=json.loads(Path(result['prepared_recipe']).read_text())
            snapshot=Path(prepared['source']['tree'])
            self.assertEqual((snapshot/'target/source.rs').read_text(),'legitimate source\n')
            self.assertFalse((source/'target/compiler.bin').exists())
            self.assertFalse((snapshot/'target/compiler.bin').exists())
            self.assertEqual((root/'cargo-target/compiler.bin').read_bytes(),b'compiled-cache')

    def test_completed_command_reaps_its_term_resistant_descendant_before_returning(self):
        import os
        import signal
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            pidfile=root/'child-pid'
            script=root/'spawn.py'
            script.write_text("""import os,pathlib,subprocess,sys
read_fd,write_fd=os.pipe()
child=subprocess.Popen([sys.executable,'-c',"import os,signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);os.write(int(sys.argv[1]),b'R');time.sleep(120)",str(write_fd)],pass_fds=(write_fd,))
os.close(write_fd)
assert os.read(read_fd,1)==b'R'
os.close(read_fd)
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
""")
            config['verify'].append([sys.executable,str(script),str(pidfile)])
            pid=None
            try:
                result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
                self.assertEqual(result['status'],'reviewed',result)
                pid=int(pidfile.read_text())
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    path=Path(f'/proc/{pid}/stat')
                    if not path.exists():break
                    if path.read_text().rsplit(')',1)[1].split()[0]=='Z':break
                    time.sleep(.01)
                else:self.fail('owned TERM-resistant descendant survived command teardown')
            finally:
                if pid is None and pidfile.exists():pid=int(pidfile.read_text())
                if pid is not None:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass

    def test_same_boot_utc_adjustments_never_renew_fixed_monotonic_deadline(self):
        for rollback in (.2,5.0):
            with self.subTest(rollback=rollback),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source,config,recipe,job=self.fixture(root)
                job['deadline']=130.0
                walls=iter([100.0]);ticks=[500.0]
                def wall():return next(walls,100.0-rollback)
                def clock():
                    ticks[0]+=.01
                    return dict(boot_id='fixture-boot',seconds=ticks[0])
                result=UpgradeRepair(source,root/'evidence',config,now=wall,clock=clock).run(job,recipe)
                self.assertEqual(result['status'],'reviewed',result)
                state=json.loads((root/'evidence/repair-state.json').read_text())
                anchor=state['clock_anchor']
                self.assertAlmostEqual(anchor['monotonic_deadline'],530.01)
                self.assertEqual(anchor['wall_high_water'],100.0)
                self.assertEqual(anchor['wall_observed'],100.0-rollback)
                self.assertEqual(anchor['wall_adjustment_count'],1)
                self.assertEqual(anchor['wall_observation'],'regressed')
                ticks[0]=531.0
                expired=UpgradeRepair(source,root/'evidence',config,now=wall,clock=clock).run(job,recipe)
                self.assertEqual(expired['reason'],'deadline_exhausted')
                after=json.loads((root/'evidence/repair-state.json').read_text())
                self.assertAlmostEqual(after['clock_anchor']['monotonic_deadline'],530.01)

    def test_boot_or_monotonic_uncertainty_is_held_without_extra_attempt(self):
        for mode in ('boot_changed','boot_missing','counter_rollback','counter_nonfinite'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source,config,recipe,job=self.fixture(root)
                job['deadline']=130.0;samples=[0]
                def clock():
                    samples[0]+=1
                    if samples[0]==1:return dict(boot_id='before',seconds=500.0)
                    if mode=='counter_rollback':return dict(boot_id='before',seconds=499.0)
                    if mode=='counter_nonfinite':return dict(boot_id='before',seconds=float('nan'))
                    return dict(boot_id='' if mode=='boot_missing' else 'after',seconds=500.1)
                result=UpgradeRepair(source,root/'evidence',config,now=lambda:100.0,clock=clock).run(job,recipe)
                self.assertEqual(result['status'],'held',result)
                self.assertEqual(result['reason'],'clock_uncertain')
                self.assertEqual(result['repair_attempts'],0)

    def test_explicit_nonretryable_worker_hold_spends_one_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            (root/'worker.py').write_text("import json,sys;print(json.dumps(dict(schema_version=1,status='held',reason='authentication_needed',retryable=False)),file=sys.stderr);sys.exit(2)\n")
            charges=[]
            result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(job,recipe)
            self.assertEqual(result['status'],'held')
            self.assertEqual(result['reason'],'authentication_needed')
            self.assertEqual(charges,[{'repair_attempts':1}])

    def test_unstructured_worker_failure_keeps_bounded_repair_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            (root/'worker.py').write_text("import sys;print('compilation needs another repair',file=sys.stderr);sys.exit(1)\n")
            charges=[]
            result=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(job,recipe)
            self.assertEqual(result['reason'],'repair_attempts_exhausted')
            self.assertEqual([c['repair_attempts'] for c in charges],[1,2,3])

    def test_dead_regeneration_reconciles_to_verification_only_without_new_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            (source/'feature.txt').write_text('upstream\n')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','upstream change'],cwd=source,check=True)
            config['base_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            (root/'worker.py').write_text("""import json,os,pathlib,subprocess
pathlib.Path('feature.txt').write_text('new\\n');subprocess.run(['git','add','feature.txt'],check=True)
pathlib.Path(os.environ['CODEX_UPGRADE_RESPONSE']).write_text(json.dumps(dict(schema_version=1,status='repaired',identity='repairer',patch_dispositions={'feature':dict(disposition='rewritten',evidence='Retained feature')},retirements={})))
""")
            marker=root/'regeneration-started'
            config['regenerate']=[[sys.executable,'-c',"import pathlib,time; marker=pathlib.Path("+repr(str(marker))+"); first=not marker.exists(); pathlib.Path('Cargo.lock').write_text('generated lockfile'); marker.write_text('ready'); time.sleep(120 if first else 0)"]]
            job['limits']['repair_attempts']=1;job['deadline']=time.time()+60
            def guard():
                if marker.exists():raise FileNotFoundError('simulated vanished rustc temp file')
            charges=[]
            first=UpgradeRepair(source,root/'evidence',config,guard=guard,checkpoint=charges.append).run(job,recipe)
            self.assertEqual(first['status'],'held')
            before=json.loads((root/'evidence/repair-state.json').read_text())
            self.assertEqual(before['inflight']['role'],'regenerate')
            owner=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append)
            receipt=owner.reconcile(dict(job,repair_attempts=1),recipe)
            self.assertEqual(receipt['mode'],'verify_only')
            self.assertEqual(owner.reconcile(dict(job,repair_attempts=1),recipe),receipt)
            reviewed=UpgradeRepair(source,root/'evidence',config,checkpoint=charges.append).run(dict(job,repair_attempts=1,resume_mode='verify_only'),recipe)
            self.assertEqual(reviewed['status'],'reviewed',reviewed)
            self.assertEqual(charges,[{'repair_attempts':1}])
            after=json.loads((root/'evidence/repair-state.json').read_text())
            self.assertEqual(after['clock_anchor']['monotonic_deadline'],before['clock_anchor']['monotonic_deadline'])
            self.assertEqual([c for c in after['commands'] if c['role']=='worker'],[c for c in before['commands'] if c['role']=='worker'])
            self.assertEqual((Path(json.loads(Path(reviewed['prepared_recipe']).read_text())['source']['tree'])/'Cargo.lock').read_text(),'generated lockfile')

    def test_uncertain_reviewer_cannot_be_readmitted_as_dead_regeneration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            marker=root/'reviewer-started'
            reviewer=Path(config['reviewer']['argv'][1])
            reviewer.write_text("import pathlib,time;pathlib.Path("+repr(str(marker))+").write_text('ready');time.sleep(120)\n")
            def guard():
                if marker.exists():raise FileNotFoundError('simulated interrupted observer')
            held=UpgradeRepair(source,root/'evidence',config,guard=guard).run(job,recipe)
            self.assertEqual(held['status'],'held')
            owner=UpgradeRepair(source,root/'evidence',config)
            with self.assertRaisesRegex(ValueError,'only_interrupted_regeneration_can_reconcile'):
                owner.reconcile(job,recipe)

    def test_cached_readmission_refuses_new_intent_after_verification_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            counter=root/'regeneration-count'
            config['regenerate']=[[sys.executable,'-c',"import pathlib,time;p=pathlib.Path("+repr(str(counter))+");n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n));time.sleep(120)"]]
            def first_guard():
                if counter.exists():raise FileNotFoundError('first known interrupted regeneration')
            held=UpgradeRepair(source,root/'evidence',config,guard=first_guard).run(job,recipe)
            self.assertEqual(held['status'],'held')
            UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe)
            def crash_guard():
                if counter.exists() and counter.read_text()=='2':raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                UpgradeRepair(source,root/'evidence',config,guard=crash_guard).run(dict(job,resume_mode='verify_only'),recipe)
            with self.assertRaisesRegex(ValueError,'verification_execution_unreconciled'):
                UpgradeRepair(source,root/'evidence',config).reconcile(job,recipe)

    def test_host_generation_and_verification_receive_canonical_owned_repo_root(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,config,recipe,job=self.fixture(root)
            command=[sys.executable,'-c',"import os;from pathlib import Path;root=Path(os.environ['CODEX_REPO_ROOT']);assert root==Path.cwd().resolve();assert (root/'feature.txt').read_text()=='new\\n'"]
            config['regenerate']=[command]
            config['verify'].append(command)
            with patch.dict(os.environ,{'CODEX_REPO_ROOT':'/unrelated/ambient/source'}):
                result=UpgradeRepair(source,root/'evidence',config).run(job,recipe)
                self.assertEqual(os.environ['CODEX_REPO_ROOT'],'/unrelated/ambient/source')
            self.assertEqual(result['status'],'reviewed',result)
            self.assertEqual(result['repair_attempts'],0)
