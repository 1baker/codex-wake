"""Future-launch selection through the public registry and launch seams."""
import io
import json
import tempfile
import threading
import time
import unittest
from test_measurements import observation as time_observation
from pathlib import Path

from codex_profiles.build_channels import load_build, run_build
from codex_profiles.upgrades import _atomic
from codex_wake.upgrade_qualification import package_inventory


def stage_fixture(root, identifier, version, read=None, write=1):
    directory=root/'stages'/identifier;package=directory/'package'
    for name in ('bin/codex','bin/codex-code-mode-host','codex-resources/bwrap','codex-path/rg'):
        path=package/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#!/bin/sh\nfor arg in "$@"; do if [ "$arg" = "--hold" ]; then touch "$CODEX_HOME/ready"; while [ ! -f "$CODEX_HOME/release" ]; do sleep 0.01; done; fi; done\nprintf "'+version+'\\n"\n');path.chmod(0o700)
    (package/'codex-package.json').write_text('{}')
    files=package_inventory(package)
    result=dict(schema_version=1,id=identifier,status='staged',channel='modded',files=files,
        checks={key:True for key in ('scoped_reload','durable_notices','caller_accounting','orphan_output')},qualification_reports=[{'scope':'source_fixture'}],
        read_schemas=read or [1],write_schema=write,source_identity=dict(upstream_version=version,revision=identifier,source_files={}),
        build=dict(executable=str(package/'bin/codex'),sha256=files['bin/codex']['sha256'],upstream_version=version,revision=identifier,source='https://github.com/openai/codex/releases/download/fixture/source.tar'))
    _atomic(directory/'receipt.json',result)
    return result


class FutureRegistryTests(unittest.TestCase):
    def test_existing_private_session_remains_pinned_while_future_launch_selects_new_package(self):
        from codex_profiles.upgrades import select_future
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'account';home.mkdir()
            stage_fixture(root,'old','0.165.0');stage_fixture(root,'new','0.166.0')
            select_future(root,home,identifier='old',operation_id='initial')
            previous=load_build(root/'builds.json','modded',home)
            output=io.StringIO();codes=[]
            thread=threading.Thread(target=lambda:codes.append(run_build(previous,home,'test',['--hold'],output=output)))
            thread.start()
            try:
                deadline=time.monotonic()+3
                while not (home/'ready').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue((home/'ready').exists())
                result=select_future(root,home,identifier='new',operation_id='upgrade')
                self.assertEqual(result['status'],'selected')
                self.assertEqual(load_build(root/'builds.json','modded',home).upstream_version,'0.166.0')
                self.assertEqual(previous.upstream_version,'0.165.0')
                self.assertTrue(thread.is_alive())
            finally:
                (home/'release').touch();thread.join(timeout=3)
            self.assertEqual(codes,[0])
            self.assertIn('0.165.0',output.getvalue())

    def test_incompatible_rollback_and_managed_cutover_preserve_selection(self):
        from codex_profiles.upgrades import select_future, UpgradeError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'account';home.mkdir()
            stage_fixture(root,'old','0.165.0');stage_fixture(root,'new','0.166.0',read=[1,2],write=2)
            select_future(root,home,identifier='old',operation_id='initial')
            with self.assertRaises(UpgradeError):select_future(root,home,identifier='new',operation_id='incompatible')
            self.assertEqual(load_build(root/'builds.json','modded',home).revision,'old')
            registry=json.loads((root/'builds.json').read_text())
            registry['tenants'][str(home.resolve())]['builds']['modded']['backend']='managed'
            _atomic(root/'builds.json',registry)
            with self.assertRaisesRegex(UpgradeError,'managed backend'):select_future(root,home,identifier='old',operation_id='managed')
            self.assertEqual(load_build(root/'builds.json','modded',home).backend,'managed')


def promotion_fixture(root):
    """Synthetic signed-by-content inputs test admission; no genuine auth claim."""
    import hashlib
    from codex_wake import upgrade_qualification
    from codex_wake.upgrade_qualification import object_hash, content_hash
    job_id='job166';directory=root/'upgrade-jobs'/job_id;directory.mkdir(parents=True)
    home=root/'account';home.mkdir()
    manifest=root/'catalog'/'builds.json';manifest.parent.mkdir()
    source=directory/'repair'/'reviewed-source';source.mkdir(parents=True)
    (source/'code.rs').write_text('candidate behavior\n');(source/'tests').mkdir();(source/'tests'/'proof.rs').write_text('independent assertion\n')
    files={str(p.relative_to(source)):dict(sha256=content_hash(p),mode=p.stat().st_mode&0o777) for p in source.rglob('*') if p.is_file()}
    tests={p:v for p,v in files.items() if 'tests' in Path(p).parts}
    review=dict(schema_version=1,status='approved',reviewer='reviewer',candidate_digest=object_hash(files),tests_digest=object_hash(tests),capabilities={c:'observed behavior' for c in upgrade_qualification.CAPABILITIES})
    recipe=dict(schema_version=1,id='candidate166',upstream_version='0.166.0',revision='revision',channel='modded',build=[],qualify=[],patches=[],read_schemas=[1],write_schema=1,source={})
    original=directory/'original.json';_atomic(original,recipe)
    prepared=dict(recipe,source=dict(tree=str(source),files={p:v['sha256'] for p,v in files.items()}),repair_provenance=dict(candidate_digest=review['candidate_digest'],tests_digest=review['tests_digest'],review=review))
    prepared_path=directory/'repair'/'prepared-recipe.json';_atomic(prepared_path,prepared)
    stage=stage_fixture(directory/'build-store','candidate166','0.166.0')
    stage['source_identity']['source_files']={p:v['sha256'] for p,v in files.items()}
    _atomic(directory/'build-store'/'stages'/'candidate166'/'receipt.json',stage)
    target={'host':'fixture','namespace':'account'}
    test_program=directory/'qualification-test.py';test_program.write_text('print("fixture test artifact")\n')
    qconfig=dict(schema_version=1,environment=dict(kind='separate_test_user',uid=1234),test_files={str(test_program):content_hash(test_program)})
    qualification=dict(schema_version=1,status='qualified',eligible_for_promotion=True,job_id=job_id,job_key='sealed-key',target=target,
        model_requests=0,external_provider_requests=0,scripted_provider_requests=0,owned_processes_remaining=[],
        candidate_sha256=object_hash(stage),package_files=stage['files'],package_sha256=object_hash(stage['files']),source_identity=stage['source_identity'],
        executor_sha256=content_hash(upgrade_qualification.__file__),test_files=qconfig['test_files'],tests_sha256=object_hash(qconfig['test_files']),configuration_sha256=object_hash(qconfig),
        environment=dict(kind='separate_test_user',uid=1234),checks={c:True for c in upgrade_qualification.CAPABILITIES|upgrade_qualification.JOURNEYS},required_checks=sorted(upgrade_qualification.CAPABILITIES|upgrade_qualification.JOURNEYS),
        receipt_path=str(directory/'qualification'/'receipt.json'))
    qualification['receipt_sha256']=object_hash(qualification);_atomic(Path(qualification['receipt_path']),qualification)
    job=dict(id=job_id,key='sealed-key',target=target,state='promoting',generation=1,deadline=time.time()+100,stage_id='candidate166',version='0.166.0',
        recipe_path=str(original),recipe_sha256=content_hash(original),results=dict(stage=stage,repair=dict(status='reviewed',prepared_recipe=str(prepared_path),candidate_digest=review['candidate_digest'],tests_digest=review['tests_digest'],review=review),qualification=qualification))
    config=dict(schema_version=1,target=target,qualification=qconfig,repair=dict(worker=dict(identity='worker'),reviewer=dict(identity='reviewer')),
        promotion=dict(manifest=str(manifest),account_home=str(home),channel='modded'))
    return job,config,home,manifest


class PromotionTests(unittest.TestCase):
    def test_qualified_reviewed_candidate_selects_through_public_build_loader(self):
        from codex_wake.upgrade_promotion import UpgradePromotion
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job,config,home,manifest=promotion_fixture(root)
            result=UpgradePromotion(root).run(job,config,guard=lambda:None,commit=lambda action:action())
            self.assertEqual(result['status'],'selected',result)
            self.assertEqual(load_build(manifest,'modded',home).upstream_version,'0.166.0')

    def test_stale_review_or_qualification_cannot_select(self):
        from codex_wake.upgrade_promotion import UpgradePromotion
        for corrupt in ('review','qualification','package','test_artifact'):
            with self.subTest(corrupt=corrupt),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);job,config,home,manifest=promotion_fixture(root)
                if corrupt=='review':job['results']['repair']['review']['tests_digest']='0'*64
                elif corrupt=='qualification':job['results']['qualification']['checks']['tui_health']=False
                elif corrupt=='package':Path(job['results']['stage']['build']['executable']).write_text('mutated package')
                else:Path(next(iter(config['qualification']['test_files']))).write_text('mutated acceptance test')
                result=UpgradePromotion(root).run(job,config,guard=lambda:None,commit=lambda action:action())
                self.assertEqual(result['status'],'held',result)
                self.assertFalse(manifest.exists())

    def test_disable_before_commit_does_not_select_and_reconcile_does_not_replay(self):
        from codex_wake.upgrade_promotion import UpgradePromotion, PromotionHeld
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job,config,home,manifest=promotion_fixture(root);enabled=[True]
            def guard():
                if not enabled[0]:raise PromotionHeld('disabled by operator')
            def commit(action):
                enabled[0]=False
                return action()
            owner=UpgradePromotion(root)
            result=owner.run(job,config,guard=guard,commit=commit)
            self.assertEqual(result['status'],'held',result)
            self.assertFalse(manifest.exists())
            enabled[0]=True
            resumed=owner.reconcile(job,config,guard=guard,commit=lambda action:self.fail('must not replay uncertain intent'))
            self.assertEqual(resumed['status'],'held',resumed)
            self.assertFalse(manifest.exists())

    def test_committed_selection_is_reconciled_after_lost_result_even_when_disabled(self):
        from codex_wake.upgrade_promotion import UpgradePromotion, PromotionHeld
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job,config,home,manifest=promotion_fixture(root)
            def commit(action):
                action()
                raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):UpgradePromotion(root).run(job,config,guard=lambda:None,commit=commit)
            self.assertEqual(load_build(manifest,'modded',home).upstream_version,'0.166.0')
            def disabled():raise PromotionHeld('disabled later')
            recovered=UpgradePromotion(root).reconcile(job,config,guard=disabled,commit=lambda action:self.fail('must not replay committed selection'))
            self.assertEqual(recovered['status'],'selected',recovered)
            self.assertTrue(recovered['reconciled'])

class ManagedHomeTests(unittest.TestCase):
    def test_private_registry_does_not_override_existing_managed_home(self):
        from codex_profiles.upgrades import select_future, UpgradeError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'account';home.mkdir()
            stage_fixture(root,'candidate','0.166.0')
            marker=home/'packages'/'app-server-daemon'/'current';marker.parent.mkdir(parents=True);marker.symlink_to('retained-daemon')
            with self.assertRaisesRegex(UpgradeError,'managed'):
                select_future(root,home,identifier='candidate',operation_id='private-fallback')
            self.assertFalse((root/'builds.json').exists())

    def test_compatible_rollback_uses_retained_complete_package_and_refuses_later_incompatible_history(self):
        from codex_profiles.upgrades import select_future, UpgradeError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'account';home.mkdir()
            stage_fixture(root,'old','0.165.0',read=[1,2],write=1)
            stage_fixture(root,'new','0.166.0',read=[1,2],write=2)
            select_future(root,home,identifier='old',operation_id='initial')
            select_future(root,home,identifier='new',operation_id='upgrade')
            rolled=select_future(root,home,channel='modded',rollback=True,operation_id='rollback')
            self.assertEqual(rolled['id'],'old')
            self.assertEqual(load_build(root/'builds.json','modded',home).revision,'old')
            select_future(root,home,identifier='new',operation_id='again')
            (home/'state_3.sqlite').write_bytes(b'synthetic schema marker')
            with self.assertRaises(UpgradeError):select_future(root,home,channel='modded',rollback=True,operation_id='incompatible-rollback')
            self.assertEqual(load_build(root/'builds.json','modded',home).revision,'new')

    def test_second_promotion_preserves_the_actual_older_pinned_writer_schema(self):
        from codex_profiles.upgrades import select_future, UpgradeError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'account';home.mkdir()
            stage_fixture(root,'old','0.164.0',read=[1],write=1)
            stage_fixture(root,'middle','0.165.0',read=[1,3],write=1)
            stage_fixture(root,'latest','0.166.0',read=[1,3],write=3)
            select_future(root,home,identifier='old',operation_id='initial')
            pinned=load_build(root/'builds.json','modded',home)
            errors=[]
            def launch():
                try:run_build(pinned,home,'test',['--hold'],output=io.StringIO())
                except Exception as error:errors.append(error)
            thread=threading.Thread(target=launch);thread.start()
            try:
                deadline=time.monotonic()+3
                while not (home/'ready').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue((home/'ready').exists())
                select_future(root,home,identifier='middle',operation_id='middle')
                with self.assertRaises(UpgradeError):select_future(root,home,identifier='latest',operation_id='latest')
                self.assertEqual(load_build(root/'builds.json','modded',home).revision,'middle')
            finally:
                (home/'release').touch();thread.join(timeout=3)
            self.assertEqual(errors,[])

class PromotionReadbackTests(unittest.TestCase):
    def test_successful_callback_without_registry_commit_is_not_selection_evidence(self):
        from codex_wake.upgrade_promotion import UpgradePromotion
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job,config,home,manifest=promotion_fixture(root)
            result=UpgradePromotion(root).run(job,config,guard=lambda:None,commit=lambda action:dict(status='selected'))
            self.assertEqual(result['status'],'held',result)
            self.assertFalse(manifest.exists())

    def test_reconciliation_observes_actual_build_row_not_only_stale_operation_marker(self):
        from codex_wake.upgrade_promotion import UpgradePromotion
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job,config,home,manifest=promotion_fixture(root)
            owner=UpgradePromotion(root)
            owner.run(job,config,guard=lambda:None,commit=lambda action:action())
            registry=json.loads(manifest.read_text());registry['tenants'][str(home.resolve())]['builds']['modded']['sha256']='0'*64
            _atomic(manifest,registry)
            self.assertEqual(owner.reconcile(job,config)['status'],'held')

    def test_explicit_rollback_uses_current_admission_without_renewing_original_job_budget(self):
        from codex_wake.upgrade_promotion import UpgradePromotion
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job,config,home,manifest=promotion_fixture(root)
            stage_fixture(manifest.parent,'baseline','0.165.0')
            from codex_profiles.upgrades import select_future
            select_future(manifest.parent,home,identifier='baseline',operation_id='initial')
            owner=UpgradePromotion(root)
            promoted=owner.run(job,config,guard=lambda:None,commit=lambda action:action())
            self.assertEqual(promoted['status'],'selected',promoted)
            deadline=job['deadline'];job['deadline']=0
            rolled=owner.rollback(config,operation_id='explicit-rollback',guard=lambda:None,commit=lambda action:action())
            self.assertEqual(rolled['status'],'selected',rolled)
            self.assertEqual(load_build(manifest,'modded',home).revision,'baseline')
            self.assertEqual(job['deadline'],0)
            self.assertGreater(deadline,0)
            duplicate=owner.rollback(config,operation_id='explicit-rollback',guard=lambda:None,commit=lambda action:action())
            self.assertEqual(duplicate['status'],'already_selected',duplicate)
            self.assertEqual(load_build(manifest,'modded',home).revision,'baseline')

class PublicPromotionObservationTests(unittest.TestCase):
    def test_operator_observes_committed_selection_after_lost_result_without_renewal(self):
        """Filesystem failure after selection must be observable through the public owner."""
        import os
        from types import SimpleNamespace
        from unittest.mock import patch
        from codex_wake.upgrade_jobs import UpgradeJobs, policy_digest
        for stopped in ('disabled', 'expired', 'interrupted', 'not_committed', 'guest_clock_ahead'):
            with self.subTest(stopped=stopped), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);job,config,home,manifest=promotion_fixture(root)
                from codex_profiles.upgrades import select_future
                stage_fixture(manifest.parent,'baseline','0.165.0')
                select_future(manifest.parent,home,identifier='baseline',operation_id='initial')
                now=[time.time()]
                config['recipes']={'release':job['recipe_path']}
                config['limits']=dict(repair_attempts=3,total_seconds=100,compiler_jobs=2,temporary_bytes=24*1024**3)
                _atomic(root/'upgrade-bot.json',config)
                guest_offset=job['deadline']-now[0]+1 if stopped=='guest_clock_ahead' else 0
                owner=UpgradeJobs(root,now=lambda:now[0]+guest_offset,clock=lambda:time_observation(int(now[0]*1000)));clock=owner.clock()
                job.update(recipe='release',last_seen=now[0],repair_attempts=1,limits=config['limits'],
                    policy_sha256=policy_digest(config),worker=None,
                    clock_anchor=dict(start=clock,latest=clock))
                _atomic(root/'upgrade-jobs/state.json',dict(schema_version=1,enabled=True,generation=1,jobs={job['id']:job},events=[]))
                actor=SimpleNamespace(subject='operator',scopes=['admin','observe'],targets=[job['target']],expires_at=now[0]+1000)
                args=dict(expected_target=job['target'],job_id=job['id'])
                replace=os.replace
                def lost_result(source,destination):
                    if stopped=='not_committed' and Path(destination)==manifest:
                        raise KeyboardInterrupt('simulated controller loss before registry commit')
                    if Path(destination)==root/'upgrade-jobs/state.json':
                        value=json.loads(Path(source).read_text())
                        if value['jobs'][job['id']]['state']=='succeeded':
                            raise KeyboardInterrupt('simulated controller loss after registry commit')
                    return replace(source,destination)
                with patch('os.replace',side_effect=lost_result):
                    with self.assertRaises(KeyboardInterrupt):owner.execute(actor,'upgrades.advance',args)
                version='0.165.0' if stopped=='not_committed' else '0.166.0'
                self.assertEqual(load_build(manifest,'modded',home).upstream_version,version)
                if stopped=='disabled':owner.execute(actor,'upgrades.disable',dict(expected_target=job['target']))
                elif stopped=='expired':
                    now[0]=job['deadline']+1
                    owner.execute(actor,'upgrades.advance',args)
                before=owner.execute(actor,'upgrades.show',args)['result']['job']
                registry=manifest.read_bytes()
                result=owner.execute(actor,'upgrades.reconcile',dict(args,mode='promotion_observe'))['result']['job']
                observation=result['results']['promotion_observation']
                self.assertEqual(observation['status'],'held' if stopped=='not_committed' else 'selected')
                self.assertEqual(observation['reconciled'],stopped!='not_committed')
                expected_state=before['state'] if stopped in ('disabled','expired') else ('held' if stopped=='not_committed' else 'succeeded')
                self.assertEqual(result['state'],expected_state)
                for key in ('deadline','limits','repair_attempts','generation','policy_sha256','clock_anchor'):
                    self.assertEqual(result[key],before[key],key)
                self.assertEqual(manifest.read_bytes(),registry)
                self.assertEqual(load_build(manifest,'modded',home).upstream_version,version)
