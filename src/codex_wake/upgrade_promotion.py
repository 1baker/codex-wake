"""Qualified future-launch promotion over the existing immutable build registry.

Preparation may copy verified bytes, never select them. The caller's commit
callback owns the outer job/control lock and fences the registry transaction.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from codex_profiles import upgrades
from . import upgrade_qualification
from .upgrade_qualification import CAPABILITIES, JOURNEYS, content_hash, object_hash, package_inventory


class PromotionHeld(ValueError):
    pass


class UpgradePromotion:
    def __init__(self, root, *, now=None):
        self.root=Path(root).resolve()
        self.now=now or time.time

    def paths(self,job,config):
        identifier=job.get('id')
        if not isinstance(identifier,str) or re.fullmatch('[A-Za-z0-9_.-]{1,80}',identifier) is None or identifier in ('.','..'):
            raise PromotionHeld('invalid promotion job identity')
        declaration=config.get('promotion',{})
        if not isinstance(declaration,dict):raise PromotionHeld('host promotion configuration required')
        if not isinstance(declaration.get('manifest'),str) or not Path(declaration['manifest']).is_absolute() or not isinstance(declaration.get('account_home'),str) or not Path(declaration['account_home']).is_absolute():
            raise PromotionHeld('absolute host manifest and account paths required')
        manifest=Path(declaration['manifest'])
        home=Path(declaration['account_home'])
        channel=declaration.get('channel')
        if not manifest.is_absolute() or manifest.name!='builds.json' or not home.is_dir() or home.is_symlink() or channel not in ('stock','modded'):
            raise PromotionHeld('fixed build manifest, existing account home and channel required')
        if job.get('target')!=config.get('target') or not isinstance(job.get('key'),str) or not job['key']:
            raise PromotionHeld('sealed job and host target differ')
        directory=self.root/'upgrade-jobs'/identifier/'promotion'
        return directory,manifest,home,channel

    def check(self,job,guard):
        guard()
        if 'start' in job.get('clock_anchor', {}):
            return
        deadline=job.get('deadline')
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or self.now()>=deadline:
            raise PromotionHeld('promotion deadline exhausted')

    def evidence(self,job,config):
        stage=job.get('results',{}).get('stage',{})
        if stage.get('status')!='staged' or stage.get('id')!=job.get('stage_id'):
            raise PromotionHeld('sealed staged candidate required')
        package=Path(stage.get('build',{}).get('executable','')).resolve(strict=True).parent.parent
        owned=self.root/'upgrade-jobs'/job['id']/'build-store'/'stages'/job['stage_id']/'package'
        if package!=owned.resolve(strict=True):raise PromotionHeld('candidate package outside sealed owned stage')
        files=package_inventory(package)
        if files!=stage.get('files') or files['bin/codex']['sha256']!=stage['build'].get('sha256'):
            raise PromotionHeld('candidate package changed after staging')
        original=Path(job['recipe_path']).resolve(strict=True)
        if content_hash(original)!=job['recipe_sha256']:
            raise PromotionHeld('original sealed recipe changed')
        q=job.get('results',{}).get('qualification',{})
        body={k:v for k,v in q.items() if k!='receipt_sha256'}
        if q.get('receipt_sha256')!=object_hash(body):raise PromotionHeld('qualification receipt content hash mismatch')
        if q.get('status')!='qualified' or q.get('eligible_for_promotion') is not True or q.get('environment',{}).get('kind') not in ('disposable_wsl','separate_test_user'):
            raise PromotionHeld('genuine disposable installed qualification required')
        if (q.get('job_id'),q.get('job_key'),q.get('target'))!=(job['id'],job['key'],job['target']):
            raise PromotionHeld('qualification belongs to a different job or target')
        receipt_path=Path(q.get('receipt_path','')).resolve(strict=True)
        expected=self.root/'upgrade-jobs'/job['id']/'qualification'/'receipt.json'
        if receipt_path!=expected.resolve(strict=True) or json.loads(receipt_path.read_text())!=q:
            raise PromotionHeld('sealed qualification artifact missing or changed')
        if (q.get('candidate_sha256')!=object_hash(stage) or q.get('package_sha256')!=object_hash(files)
                or q.get('package_files')!=files or q.get('source_identity')!=stage.get('source_identity')):
            raise PromotionHeld('qualification candidate identity mismatch')
        if q.get('executor_sha256')!=content_hash(upgrade_qualification.__file__):
            raise PromotionHeld('qualification executor changed')
        qualification_config=config.get('qualification',{})
        if q.get('configuration_sha256')!=object_hash(qualification_config):
            raise PromotionHeld('qualification configuration changed')
        tests=upgrade_qualification.UpgradeQualification(self.root).test_files(qualification_config)
        if q.get('test_files')!=tests or q.get('tests_sha256')!=object_hash(tests):
            raise PromotionHeld('qualification test artifacts changed')
        if type(q.get('model_requests')) is not int or q['model_requests']!=0 or (type(q.get('external_provider_requests')) is not int or q['external_provider_requests']!=0) or q.get('owned_processes_remaining')!=[]:
            raise PromotionHeld('qualification effect boundary or teardown unproven')
        required=set(JOURNEYS)|set(CAPABILITIES if stage.get('channel')=='modded' else ('official_cli',))
        required.update(q.get('required_checks',[]));required.update(job.get('required_capabilities',[]));required.update(stage.get('checks',{}))
        if any(q.get('checks',{}).get(check) is not True for check in required):
            raise PromotionHeld('required capability or installed journey unqualified')
        repair=job.get('results',{}).get('repair',{})
        review=repair.get('review',{})
        identities=config.get('repair',{})
        reviewer=identities.get('reviewer',{}).get('identity')
        worker=identities.get('worker',{}).get('identity')
        if (repair.get('status')!='reviewed' or review.get('status')!='approved' or not reviewer or not worker
                or reviewer==worker or review.get('reviewer')!=reviewer):
            raise PromotionHeld('independent candidate review required')
        if review.get('schema_version')!=1 or any(not isinstance(review.get('capabilities',{}).get(name),str) or not review['capabilities'][name].strip() for name in required & CAPABILITIES):
            raise PromotionHeld('independent review capability evidence missing')
        if identities.get('worker',{}).get('argv') is not None and identities.get('worker',{}).get('argv')==identities.get('reviewer',{}).get('argv'):
            raise PromotionHeld('worker and reviewer commands are not independent')
        for patch in repair.get('patch_provenance',[]):
            if patch.get('disposition')=='retired' and not review.get('retirements',{}).get(patch.get('id')):
                raise PromotionHeld('retired patch equivalence is not independently reviewed')
        prepared_path=Path(repair.get('prepared_recipe','')).resolve(strict=True)
        owned_job=self.root/'upgrade-jobs'/job['id']
        if not prepared_path.is_relative_to(owned_job):raise PromotionHeld('reviewed recipe outside owned job')
        prepared=json.loads(prepared_path.read_text())
        provenance=prepared.get('repair_provenance',{})
        if provenance.get('review')!=review:
            raise PromotionHeld('prepared recipe and sealed review differ')
        source=Path(prepared.get('source',{}).get('tree','')).resolve(strict=True)
        if not source.is_relative_to(owned_job):raise PromotionHeld('reviewed source outside owned job')
        observed={}
        for path in sorted(source.rglob('*')):
            if path.is_symlink():raise PromotionHeld('reviewed snapshot contains a mutable link')
            if path.is_file():observed[str(path.relative_to(source))]=dict(sha256=content_hash(path),mode=path.stat().st_mode&0o777)
        test_source={name:value for name,value in observed.items() if 'tests' in Path(name).parts or Path(name).name.startswith('test_') or Path(name).stem.endswith('_tests')}
        candidate_digest=object_hash(observed);tests_digest=object_hash(test_source)
        for sealed in (repair,review,provenance):
            if sealed.get('candidate_digest')!=candidate_digest or sealed.get('tests_digest')!=tests_digest:
                raise PromotionHeld('candidate source or tests changed after independent review')
        expected_files={name:value['sha256'] for name,value in observed.items()}
        if prepared.get('source',{}).get('files')!=expected_files or stage.get('source_identity',{}).get('source_files')!=expected_files:
            raise PromotionHeld('staged source differs from independently reviewed snapshot')
        original_recipe=json.loads(original.read_text())
        mutable={'source','patches','repair_provenance'}
        if {k:v for k,v in original_recipe.items() if k not in mutable}!={k:v for k,v in prepared.items() if k not in mutable}:
            raise PromotionHeld('prepared recipe changed sealed execution policy')
        return stage,package,dict(qualification_sha256=q['receipt_sha256'],candidate_sha256=object_hash(stage),
            package_sha256=object_hash(files),review_sha256=object_hash(review),candidate_digest=candidate_digest,tests_digest=tests_digest)

    def catalog(self,job,manifest,stage,package,evidence,guard):
        identifier='upgrade-'+job['id']
        root=manifest.parent
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        destination=root/'stages'/identifier
        provenance=dict(job_id=job['id'],job_key=job['key'],target=job['target'],**evidence)
        if destination.exists():
            receipt=upgrades._qualified(root,identifier)
            if receipt.get('promotion_source')!=provenance:
                raise PromotionHeld('global catalog identity already bound to another candidate')
            return identifier
        temporary=root/('promotion-'+uuid.uuid4().hex)
        temporary.mkdir(mode=0o700)
        try:
            output=temporary/'package';output.mkdir(mode=0o700)
            for path in sorted(package.rglob('*')):
                guard()
                relative=path.relative_to(package);target=output/relative
                if path.is_dir():target.mkdir(parents=True,exist_ok=True)
                elif path.is_file() and not path.is_symlink():
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
                else:raise PromotionHeld('candidate special files unsupported')
            if package_inventory(output)!=stage['files'] or package_inventory(package)!=stage['files']:
                raise PromotionHeld('candidate changed while preparing global catalog')
            receipt=json.loads(json.dumps(stage))
            receipt['id']=identifier
            receipt['build']['executable']=str(destination/'package'/'bin/codex')
            receipt['promotion_source']=provenance
            upgrades._atomic(temporary/'receipt.json',receipt)
            guard()
            # Never call an outer-lock guard while holding the registry lock.
            with upgrades._locked(root):
                if destination.exists():
                    existing=upgrades._qualified(root,identifier)
                    if existing.get('promotion_source')!=provenance:raise PromotionHeld('concurrent catalog candidate differs')
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    os.rename(temporary,destination)
            return identifier
        finally:
            if temporary.exists():shutil.rmtree(temporary)

    def run(self,job,config,*,guard,commit):
        directory=None
        try:
            directory,manifest,home,channel=self.paths(job,config)
            if (directory/'intent.json').exists():return self.reconcile(job,config,guard=guard,commit=commit)
            self.check(job,guard)
            stage,package,evidence=self.evidence(job,config)
            if stage.get('channel')!=channel:raise PromotionHeld('host promotion channel differs from candidate')
            identifier=self.catalog(job,manifest,stage,package,evidence,lambda:self.check(job,guard))
            before=content_hash(manifest) if manifest.exists() else 'absent'
            intent=dict(schema_version=1,job_id=job['id'],job_key=job['key'],target=job['target'],
                status='prepared',id=identifier,operation_id='promote-'+job['id'],manifest=str(manifest),
                account_home=str(home.resolve()),channel=channel,registry_before_sha256=before,**evidence)
            upgrades._atomic(directory/'intent.json',intent)
            def select():
                # commit's outer job lock must remain held until this returns.
                self.check(job,guard)
                self.evidence(job,config)
                return upgrades.select_future(manifest.parent,home,identifier=identifier,channel=channel,
                    operation_id=intent['operation_id'],expected_registry_sha256=before,guard=lambda:self.check(job,guard))
            result=commit(select)
            receipt=self.reconcile(job,config)
            if receipt.get('status')=='selected':receipt['registry_result']=result
            upgrades._atomic(directory/'receipt.json',receipt)
            return receipt
        except (OSError,ValueError,KeyError,TypeError) as error:
            receipt=dict(schema_version=1,job_id=job.get('id'),status='held',reason=str(error))
            if directory:upgrades._atomic(directory/'receipt.json',receipt)
            return receipt

    def rollback(self,config,*,operation_id,guard,commit):
        """Explicit admin rollback; independent of an expired upgrade budget.

        Caller fences current target/actor/operation identity under its job lock.
        Disabling automatic upgrades does not disable this explicit recovery path.
        """
        try:
            _,manifest,home,channel=self.paths(dict(id='rollback',key=operation_id,target=config.get('target')),config)
            before=content_hash(manifest) if manifest.exists() else 'absent'
            def select():
                guard()
                return upgrades.select_future(manifest.parent,home,channel=channel,rollback=True,
                    operation_id=operation_id,expected_registry_sha256=before,guard=guard)
            result=commit(select)
            from codex_profiles.build_channels import load_build
            observed=load_build(manifest,channel,home)
            if not isinstance(result,dict) or result.get('status') not in ('selected','already_selected') or observed.sha256!=result.get('build_sha256'):
                raise PromotionHeld('rollback registry readback differs from committed candidate')
            return dict(schema_version=1,status=result['status'],operation='future_rollback',result=result)
        except (OSError,ValueError,KeyError,TypeError) as error:
            return dict(schema_version=1,status='held',operation='future_rollback',reason=str(error))

    def reconcile(self,job,config,*,guard=None,commit=None):
        """Observe an interrupted selection's actual durable outcome; never replay."""
        try:
            directory,manifest,home,channel=self.paths(job,config)
            intent=json.loads((directory/'intent.json').read_text())
            if (intent.get('job_id'),intent.get('job_key'),intent.get('target'))!=(job['id'],job['key'],job['target']):
                raise PromotionHeld('promotion intent belongs to another job or scope')
            if (intent.get('manifest'),intent.get('account_home'),intent.get('channel'))!=(str(manifest),str(home.resolve()),channel):
                raise PromotionHeld('promotion configuration changed after intent')
            active=json.loads(manifest.read_text()) if manifest.exists() else {}
            selected=active.get('tenants',{}).get(str(home.resolve()),{})
            if selected.get('future_operations',{}).get(channel)!=intent['operation_id'] or selected.get('stages',{}).get(channel)!=intent['id']:
                raise PromotionHeld('selection intent has no matching committed registry outcome; no replay')
            stage=upgrades._qualified(manifest.parent,intent['id'])
            if stage.get('promotion_source',{}).get('job_key')!=job['key'] or stage['promotion_source'].get('candidate_sha256')!=intent['candidate_sha256']:
                raise PromotionHeld('committed catalog package identity changed')
            from codex_profiles.build_channels import load_build
            observed=load_build(manifest,channel,home)
            if observed.sha256!=stage['build']['sha256'] or observed.executable!=Path(stage['build']['executable']).resolve() or observed.backend!='private':
                raise PromotionHeld('actual selected build row differs from committed candidate')
            result=dict(intent,status='selected',reconciled=True,registry_result=dict(status='already_selected',id=intent['id'],channel=channel))
            upgrades._atomic(directory/'receipt.json',result)
            return result
        except (OSError,ValueError,KeyError,TypeError) as error:
            return dict(schema_version=1,job_id=job.get('id'),status='held',reason=str(error),reconciled=False)
