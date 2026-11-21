"""Pinned patch replay and bounded semantic repair with independent review.

This executor consumes host configuration, never caller-supplied commands.
Workers edit an owned Git workspace. Reports live outside the candidate, and a
review is accepted only for the exact candidate and tests that were inspected.
A reviewed source snapshot is input to staging, not runtime qualification.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time

from codex_profiles.upgrades import _atomic, REQUIRED_CAPABILITIES
from .upgrade_storage import owned_storage_bytes


class RepairHeld(ValueError):
    """A repair could not establish the evidence needed to proceed."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _digest(value):
    return _sha(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


NONRETRYABLE_WORKER_REASONS=frozenset(('authentication_needed','coding_capacity_unavailable',
    'configuration_unavailable','native_coding_failed'))


def _explicit_worker_hold(output):
    # Only the configured worker's complete/final structured protocol is metadata;
    # native event prose and intermediate JSON records are not a retry decision.
    candidates=[output.strip()]
    if output.strip():candidates.append(output.strip().splitlines()[-1])
    for candidate in candidates:
        try:value=json.loads(candidate)
        except ValueError:continue
        if (isinstance(value,dict) and set(value)=={'schema_version','status','reason','retryable'}
                and value['schema_version']==1 and value['status']=='held'
                and value['retryable'] is False and value['reason'] in NONRETRYABLE_WORKER_REASONS):
            return value['reason']
    return None


def _inventory(root):
    files={}
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root)
        if '.git' in relative.parts:
            continue
        if path.is_symlink():
            resolved=path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise RepairHeld('candidate contains an escaping or directory symlink')
        if path.is_file():
            files[str(relative)]={'sha256':_sha(path.read_bytes()),'mode':path.stat().st_mode&0o777}
        elif not path.is_dir():
            raise RepairHeld('candidate contains a special file')
    return files


def _identities(files):
    tests={path:value for path,value in files.items() if 'tests' in Path(path).parts or Path(path).name.startswith('test_') or Path(path).stem.endswith('_tests')}
    return _digest(files),_digest(tests)


class UpgradeRepair:
    """Run one sealed release's replay/repair/review; result is a stage recipe.

    ``guard`` verifies the current enabled scope during command polling.
    ``checkpoint`` durably charges the job's cumulative repair_attempts before
    each worker submission. The executor's own journal independently retains the
    same high-water mark and unresolved subprocess intents across reconstruction.
    """
    def __init__(self, workspace, evidence, config, *, now=None, clock=None, guard=None, checkpoint=None):
        self.workspace=Path(workspace).resolve(strict=True)
        self.evidence=Path(evidence).resolve()
        if self.evidence == self.workspace or self.evidence.is_relative_to(self.workspace):
            raise ValueError('repair evidence must be outside candidate source')
        self.cache=Path(config.get('compiler_cache',self.evidence.parent/'cargo-target'))
        if self.cache==self.workspace or self.cache.is_relative_to(self.workspace) or self.workspace.is_relative_to(self.cache):
            raise ValueError('owned compiler cache must be outside candidate source')
        self.config=config
        self.now=now or time.time
        self.clock=clock or self._host_clock
        self.guard=guard
        self.checkpoint=checkpoint or (lambda value: None)
        self.evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.state_path=self.evidence/'repair-state.json'
        self.state={}

    @staticmethod
    def _host_clock():
        return dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),seconds=time.monotonic())

    def _save(self):
        _atomic(self.state_path,self.state)

    def _budget(self):
        if self.guard is not None:
            self.guard()
        if 'start' in self.job.get('clock_anchor', {}):
            if self.guard is None:
                raise RepairHeld('durable_upgrade_guard_required')
            self._check_storage()
            return
        self._legacy_budget()
        self._check_storage()

    def _legacy_budget(self):
        current=self.now()
        try:
            sample=self.clock();anchor=self.state['clock_anchor'];counter=sample['seconds']
            if (not isinstance(sample['boot_id'],str) or not sample['boot_id'] or sample['boot_id']!=anchor['boot_id']
                    or type(counter) not in (int,float) or not math.isfinite(counter)
                    or counter<anchor['monotonic_latest']
                    or type(current) not in (int,float) or not math.isfinite(current)):
                raise ValueError('clock continuity lost')
            regressed=current<anchor['wall_high_water']
            negative_delta=current-anchor['wall_observed']
            anchor.update(monotonic_latest=counter,wall_high_water=max(anchor['wall_high_water'],current),
                wall_observed=current,wall_observation='regressed' if regressed else 'nondecreasing',
                wall_adjustment_count=anchor.get('wall_adjustment_count',0)+int(negative_delta<0),
                last_negative_delta=negative_delta if negative_delta<0 else anchor.get('last_negative_delta',0))
            self.state['last_seen']=anchor['wall_high_water']
        except (KeyError,OSError,TypeError,ValueError):
            raise RepairHeld('clock_uncertain') from None
        if anchor['wall_high_water']>=self.job['deadline'] or counter>=anchor['monotonic_deadline']:
            raise RepairHeld('deadline_exhausted')

    def _check_storage(self):
        limit=self.job['limits'].get('temporary_bytes')
        if limit is not None:
            size=owned_storage_bytes((self.workspace,self.evidence,self.cache))
            if size>limit:
                raise RepairHeld('temporary_storage_exhausted')

    def _host_tools(self):
        tools=self.config.get('host_tools',{})
        if not isinstance(tools,dict):
            raise RepairHeld('host_tools must map command names to absolute paths and SHA256 pins')
        # Subprocesses resolve relative PATH entries from the owned workspace.
        search_path=os.pathsep.join(str(Path(part) if Path(part).is_absolute() else self.workspace/part)
                                    for part in os.environ.get('PATH','').split(os.pathsep))
        for name,pin in tools.items():
            if (not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.+-]+',name)
                    or not isinstance(pin,dict) or set(pin)!={'path','sha256'}
                    or not isinstance(pin['path'],str) or not Path(pin['path']).is_absolute()
                    or not isinstance(pin['sha256'],str) or not re.fullmatch(r'[a-f0-9]{64}',pin['sha256'])):
                raise RepairHeld('invalid host tool pin')
            selected=shutil.which(name,path=search_path)
            if selected is None or Path(selected).absolute()!=Path(pin['path']):
                raise RepairHeld('host_tool_path_mismatch: '+name)
            if _sha(Path(selected).read_bytes())!=pin['sha256']:
                raise RepairHeld('host_tool_hash_mismatch: '+name)

    def _command(self, argv, role, *, packet=None):
        if not isinstance(argv,list) or not argv or any(not isinstance(x,str) or not x for x in argv):
            raise RepairHeld('host command must be an explicit argv array')
        self._budget()
        self._host_tools()
        sequence=len(self.state['commands'])+1
        output=self.evidence/f'{sequence}-{role}.stdout'
        error=self.evidence/f'{sequence}-{role}.stderr'
        response=self.evidence/f'{sequence}-{role}-response.json'
        env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL')}
        with tempfile.TemporaryDirectory(prefix='repair-home-',dir=self.evidence) as home:
            env.update(HOME=home,CODEX_HOME=home+'/.codex',XDG_CONFIG_HOME=home+'/.config',XDG_DATA_HOME=home+'/.local/share',
                CARGO_BUILD_JOBS=str(self.job['limits'].get('compiler_jobs',2)),CARGO_TARGET_DIR=str(self.cache),
                CODEX_REPO_ROOT=str(self.workspace))
            Path(env['CODEX_HOME']).mkdir(mode=0o700)
            if packet is not None:
                packet_path=self.evidence/f'{sequence}-{role}-packet.json'
                _atomic(packet_path,packet)
                env.update(CODEX_UPGRADE_PACKET=str(packet_path),CODEX_UPGRADE_RESPONSE=str(response))
            report=dict(role=role,argv=argv,stdout=str(output),stderr=str(error),status='intent')
            self.state['commands'].append(report)
            self.state['inflight']=dict(role=role,sequence=sequence)
            self._save()
            process=None
            try:
                with output.open('wb') as out,error.open('wb') as err:
                    process=subprocess.Popen(argv,cwd=self.workspace,env=env,stdout=out,stderr=err,start_new_session=True)
                    report['owned_process_group']=process.pid
                    stat=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()
                    report['process_identity']=dict(pid=process.pid,start_ticks=stat[19],boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
                    self.state['inflight']['process_identity']=report['process_identity']
                    self._save()
                    started=time.monotonic()
                    timeout=self.config.get('command_timeout_seconds',600)
                    if type(timeout) is not int or timeout<=0:
                        raise RepairHeld('positive host command timeout required')
                    while process.poll() is None:
                        self._budget()
                        if time.monotonic()-started>=timeout:
                            raise RepairHeld(role+'_timeout')
                        time.sleep(.05)
                    self._budget()
                report.update(status='completed',exit_code=process.returncode,stdout_sha256=_sha(output.read_bytes()),stderr_sha256=_sha(error.read_bytes()))
                self.state['inflight']=None
                self._save()
                return process.returncode,output.read_text(errors='replace')+error.read_text(errors='replace'),response
            finally:
                if process is not None:
                    try:os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    try:process.wait(timeout=1)
                    except subprocess.TimeoutExpired:pass
                    finally:
                        # A completed leader can leave descendants that ignore TERM.
                        # The session/group created for this child remains ours.
                        try:os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                        process.wait()

    def _git(self,*argv):
        code,output,_=self._command(['git',*argv],'git')
        return code,output

    def _unresolved(self):
        code,output=self._git('ls-files','--unmerged')
        if code or output.strip():
            return True
        code,output=self._git('diff','--check','HEAD')
        return 'conflict marker' in output.lower()

    def _validate_config(self, recipe):
        self._host_tools()
        worker=self.config.get('worker',{});reviewer=self.config.get('reviewer',{})
        if type(reviewer.get('require_patch_dispositions',False)) is not bool:
            raise RepairHeld('reviewer require_patch_dispositions must be boolean')
        if not worker.get('identity') or not reviewer.get('identity') or worker['identity']==reviewer['identity']:
            raise RepairHeld('independently configured worker and reviewer identities required')
        if worker.get('argv')==reviewer.get('argv'):
            raise RepairHeld('worker and reviewer must be separately configured commands')
        for commands in ('regenerate','verify'):
            if not isinstance(self.config.get(commands),list):
                raise RepairHeld('explicit host generation and verification command lists required')
        if not self.config['verify']:
            raise RepairHeld('behavioral verification commands required')
        patches=self.config.get('patches')
        if not isinstance(patches,list):
            raise RepairHeld('pinned patch list required')
        pins=lambda items: [(str(Path(p['path']).resolve()),p['sha256']) for p in items]
        if pins(patches)!=pins(recipe.get('patches',[])):
            raise RepairHeld('original_patch_stack_mismatch')
        ids=set()
        for patch in patches:
            if not patch.get('id') or patch['id'] in ids or not patch.get('intent'):
                raise RepairHeld('unique patch identity and behavioral intent required')
            ids.add(patch['id'])
            if _sha(Path(patch['path']).read_bytes())!=patch.get('sha256'):
                raise RepairHeld('patch_pin_mismatch')

    def _packet(self,role):
        files=_inventory(self.workspace)
        candidate,tests=_identities(files)
        packet=dict(schema_version=1,role=role,job_id=self.job['id'],candidate_digest=candidate,tests_digest=tests,
            workspace=str(self.workspace),required_capabilities=self.required,patches=self.config['patches'],
            verification_reports=[dict(report) for report in self.state['commands'] if report['role'] in ('regenerate','verify') and report.get('status')=='completed'],
            patch_provenance=self.state['patch_provenance'],prior_findings=self.state.get('findings',[]),
            contract='Preserve every required capability and acceptance standard. Resolve conflicts by upstream and patch intent. Return schema_version 1, status, identity, candidate_digest, tests_digest, capabilities mapping to evidence, patch_dispositions for EVERY patch ID (disposition applied/rewritten/retired plus nonempty intent evidence), and retirements mapping patch IDs to equivalence evidence. Reviewer additionally returns reviewer identity and status approved or rejected. Never weaken tests to obtain approval.')
        if role=='reviewer' and self.job.get('resume_mode')=='verify_review_only':
            packet.update(require_patch_dispositions=True,interrupted_worker=self.state['verification_readmission']['worker_proof'])
        elif role=='reviewer' and self.config['reviewer'].get('require_patch_dispositions',False):
            packet['require_patch_dispositions']=True
        return packet

    def _read_report(self,path,role):
        try:report=json.loads(path.read_text())
        except (OSError,ValueError) as error:raise RepairHeld(role+'_structured_report_missing') from error
        if not isinstance(report,dict) or report.get('schema_version')!=1:
            raise RepairHeld(role+'_report_schema_unsupported')
        return report

    def _replay(self):
        code,revision=self._git('rev-parse','HEAD')
        if code or not re.fullmatch(r'[a-f0-9]{40,64}',self.config.get('base_revision','')) or revision.strip()!=self.config['base_revision']:
            raise RepairHeld('upstream_source_identity_mismatch')
        self.state['base_revision']=revision.strip()
        self.state['base_files_digest']=_digest(_inventory(self.workspace))
        code,output=self._git('status','--porcelain')
        if code or output.strip():
            raise RepairHeld('initial_workspace_must_be_clean')
        self.state['patch_provenance']=[dict(id=p['id'],sha256=p['sha256'],intent=p['intent'],disposition='pending') for p in self.config['patches']]
        self._save()
        for patch,provenance in zip(self.config['patches'], self.state['patch_provenance']):
            code,_=self._git('apply','--check',str(Path(patch['path']).resolve()))
            if code==0:
                code,output=self._git('apply','--index',str(Path(patch['path']).resolve()))
            else:
                code,output=self._git('apply','--3way','--index',str(Path(patch['path']).resolve()))
            conflicted=code!=0 or 'with conflicts' in output.lower() or self._unresolved()
            provenance['disposition']='needs_repair' if conflicted else 'applied'
            self._save()
            if conflicted:
                return False
        return True

    def _verify(self):
        for role in ('regenerate','verify'):
            for argv in self.config[role]:
                code,_,_=self._command(argv,role)
                if code:
                    return False
        return not self._unresolved()

    def _review(self):
        packet=self._packet('reviewer')
        code,output,path=self._command(self.config['reviewer']['argv'],'reviewer',packet=packet)
        if code:
            raise RepairHeld(_explicit_worker_hold(output) or 'reviewer_failed')
        report=self._read_report(path,'reviewer')
        current=self._packet('reviewer')
        if current['candidate_digest']!=packet['candidate_digest'] or current['tests_digest']!=packet['tests_digest']:
            raise RepairHeld('candidate_changed_during_review')
        if report.get('reviewer')!=self.config['reviewer']['identity'] or any(report.get(k)!=packet[k] for k in ('candidate_digest','tests_digest')):
            raise RepairHeld('review_identity_or_content_mismatch')
        capabilities=report.get('capabilities',{})
        if not isinstance(capabilities,dict) or any(not isinstance(capabilities.get(c),str) or not capabilities[c].strip() for c in self.required):
            raise RepairHeld('required_capability_evidence_missing')
        for patch in ([] if packet.get('require_patch_dispositions') else self.state['patch_provenance']):
            if patch['disposition']=='retired':
                evidence=report.get('retirements',{}).get(patch['id'])
                if not isinstance(evidence,str) or not evidence.strip():
                    raise RepairHeld('retirement_equivalence_unreviewed')
        if packet.get('require_patch_dispositions'):
            self.state['independent_patch_provenance']=self._independent_dispositions(report)
        report['report_sha256']=_sha(path.read_bytes())
        return report

    def _independent_dispositions(self,report):
        declarations=report.get('patch_dispositions')
        if not isinstance(declarations,dict) or set(declarations)!={p['id'] for p in self.config['patches']}:
            raise RepairHeld('independent_review_patch_dispositions_required')
        result=[]
        for patch in self.config['patches']:
            value=declarations[patch['id']]
            if (not isinstance(value,dict) or value.get('disposition') not in ('applied','rewritten','retired')
                    or value.get('intent')!=patch['intent'] or not isinstance(value.get('evidence'),str) or not value['evidence'].strip()
                    or not isinstance(value.get('equivalence'),str)):
                raise RepairHeld('independent_review_patch_intent_unproved')
            retained=dict(id=patch['id'],sha256=patch['sha256'],intent=patch['intent'],
                disposition=value['disposition'],evidence=value['evidence'],basis='independent_review')
            if value['disposition']=='retired':
                equivalence=value.get('equivalence')
                if not isinstance(equivalence,str) or not equivalence.strip() or report.get('retirements',{}).get(patch['id'])!=equivalence:
                    raise RepairHeld('independent_retirement_equivalence_unproved')
                retained['equivalence']=equivalence
            elif value['equivalence'] or report.get('retirements',{}).get(patch['id']):
                raise RepairHeld('independent_patch_disposition_conflicts_with_retirement')
            result.append(retained)
        return result

    def _prepared(self,recipe,review):
        before=_inventory(self.workspace)
        snapshot=self.evidence/'reviewed-source'
        if snapshot.exists():
            raise RepairHeld('reviewed_snapshot_exists_reconcile_required')
        snapshot.mkdir(mode=0o700)
        for name in before:
            source=self.workspace/name;destination=snapshot/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source.resolve(strict=True),destination)
        if _inventory(self.workspace)!=before or _inventory(snapshot)!=before:
            raise RepairHeld('candidate_changed_while_snapshotting')
        if _identities(before)!=(review['candidate_digest'],review['tests_digest']):
            raise RepairHeld('candidate_changed_after_review')
        prepared=json.loads(json.dumps(recipe))
        prepared['source']=dict(prepared.get('source',{}),tree=str(snapshot),files={p:v['sha256'] for p,v in before.items()})
        prepared['patches']=[]
        prepared['repair_provenance']=dict(original_recipe_sha256=_digest(recipe),base_revision=self.state['base_revision'],base_files_digest=self.state['base_files_digest'],candidate_digest=review['candidate_digest'],tests_digest=review['tests_digest'],patches=self.state['patch_provenance'],review=review)
        if self.config['reviewer'].get('require_patch_dispositions',False):
            prepared['repair_provenance'].update(qualification_basis='independent_review_with_patch_dispositions',
                original_patch_provenance=self.state['patch_provenance'],patches=self.state['independent_patch_provenance'])
        if self.job.get('resume_mode')=='verify_review_only':
            provenance=prepared['repair_provenance']
            provenance.update(qualification_basis='independent_review_after_interrupted_worker',worker_completed=False,
                original_patch_provenance=self.state['patch_provenance'],patches=self.state['independent_patch_provenance'],
                interrupted_worker=self.state['verification_readmission']['worker_proof'])
        path=self.evidence/'prepared-recipe.json';_atomic(path,prepared)
        return str(path)

    def _seal(self,job,recipe):
        self.required=sorted(set(REQUIRED_CAPABILITIES.get(recipe.get('channel'), ())) |
            set(job.get('required_capabilities', ())) | set(self.config.get('required_capabilities', ())) |
            ({'tui_health'} if recipe.get('channel') == 'modded' else set()))
        return _digest(dict(job_id=job['id'],recipe=recipe,config=self.config,workspace=str(self.workspace),required=self.required))

    def _dead_owned_intent(self,inflight,role,*,historical=False):
        sequence=inflight.get('sequence')
        label='regeneration' if role=='regenerate' else 'worker'
        if (type(sequence) is not int or not 1<=sequence<=len(self.state['commands'])
                or (not historical and sequence!=len(self.state['commands'])) or inflight.get('role')!=role):
            raise RepairHeld('only_interrupted_'+label+'_can_reconcile')
        command=self.state['commands'][sequence-1]
        identity=command.get('process_identity')
        argv_matches=(command.get('argv') in self.config['regenerate'] if role=='regenerate' else command.get('argv')==self.config['worker']['argv'])
        if (command.get('role')!=role or command.get('status')!='intent'
                or not argv_matches
                or not isinstance(identity,dict) or identity!=inflight.get('process_identity')
                or command.get('owned_process_group')!=identity.get('pid')):
            raise RepairHeld('interrupted_'+label+'_identity_unverified')
        return self._observed_dead_group(command,label)

    def _observed_dead_group(self,command,label):
        identity=command.get('process_identity')
        if not isinstance(identity,dict) or command.get('owned_process_group')!=identity.get('pid'):
            raise RepairHeld('owned_process_identity_unverified')
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if identity.get('boot_id')!=boot or type(identity.get('pid')) is not int or identity['pid']<=1:
            raise RepairHeld('interrupted_'+label+'_boot_unverified')
        leader='absent'
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():continue
            try:fields=(process/'stat').read_text().rsplit(')',1)[1].split()
            except FileNotFoundError:continue
            if int(process.name)==identity['pid']:
                leader='same_zombie' if fields[19]==identity.get('start_ticks') and fields[0]=='Z' else 'different_or_live'
                if fields[19]==identity.get('start_ticks') and fields[0]!='Z':
                    raise RepairHeld('original_'+label+'_still_running')
            if fields[0]!='Z' and (int(fields[2])==identity['pid'] or int(fields[3])==identity['pid']):
                raise RepairHeld('original_'+label+'_group_still_running')
        return dict(status='observed_dead',original_identity=identity,owned_process_group=identity['pid'],
            observed_boot_id=boot,leader_observation=leader,live_group_members=0)

    def _interrupted_worker_proof(self,job,inflight,minimum_mono,*,historical=False):
        if not inflight:raise RepairHeld('known_started_worker_intent_required')
        dead=self._dead_owned_intent(inflight,'worker',historical=historical)
        sequence=inflight['sequence'];command=self.state['commands'][sequence-1]
        if self.state['repair_attempts']<=0:raise RepairHeld('original_coding_attempt_charge_required')
        if (self.evidence/f'{sequence}-worker-response.json').exists():
            raise RepairHeld('worker_response_exists_requires_separate_reconciliation')
        path=self.evidence.parent/'worker-exit-census.json'
        metadata=path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.getuid() or stat.S_IMODE(metadata.st_mode)!=0o600:
            raise RepairHeld('private_owned_worker_exit_census_required')
        if metadata.st_size>1024**2:raise RepairHeld('worker_exit_census_exceeds_bound')
        census=json.loads(path.read_text())
        details=census.get('census',{})
        if (not isinstance(details,dict) or details.get('includes_cross_process_groups') is not True
                or details.get('unreadable_processes')!=[] or type(details.get('proc_entries_scanned')) is not int
                or details['proc_entries_scanned']<=0):
            raise RepairHeld('full_owned_process_census_required')
        observed=census.get('observed_monotonic_seconds')
        current=self.clock()
        if (census.get('schema_version')!=1 or census.get('job_id')!=job['id']
                or census.get('worker_identity')!=command['process_identity']
                or census.get('worker_argv')!=command['argv'] or census.get('boot_id')!=dead['observed_boot_id']
                or current.get('boot_id')!=dead['observed_boot_id']
                or type(observed) not in (int,float) or not math.isfinite(observed)
                or observed<minimum_mono or observed>current['seconds']
                or census.get('owned_processes_remaining')!=[]):
            raise RepairHeld('worker_exit_census_unverified')
        artifacts=census.get('artifacts')
        if not isinstance(artifacts,list) or not artifacts or len(artifacts)>64:
            raise RepairHeld('original_worker_artifact_references_required')
        retained=[]
        for artifact in artifacts:
            if not isinstance(artifact,dict) or artifact.get('kind') not in ('native_events','worker_stdout','worker_stderr','source_diagnostic'):
                raise RepairHeld('unsupported_worker_artifact_reference')
            original=Path(artifact.get('path',''))
            resolved=original.resolve(strict=True)
            if original.is_symlink() or not resolved.is_relative_to(self.evidence.parent) or not resolved.is_file() or _sha(resolved.read_bytes())!=artifact.get('sha256'):
                raise RepairHeld('worker_artifact_identity_changed')
            retained.append(dict(kind=artifact['kind'],path=str(resolved),sha256=artifact['sha256']))
        if not any(a['kind']=='native_events' for a in retained):raise RepairHeld('native_worker_events_required')
        return dict(kind='interrupted_worker_no_completion_report',worker_completed=False,sequence=sequence,
            identity=self.config['worker']['identity'],repair_attempts=self.state['repair_attempts'],
            original_command=command,dead_process=dead,census_path=str(path),census_sha256=_sha(path.read_bytes()),
            artifacts=retained,previous_hold_reason=self.state.get('reason'),
            prior_clock_uncertainty='retained_unclassified' if self.state.get('reason')=='clock_uncertain' else None)

    def _repeat_interrupted_verification(self,job,existing,minimum_mono):
        if self.state.get('inflight') or self.state.get('reason')!='verify_review_only_verification_failed':
            raise RepairHeld('completed_deterministic_verification_failure_required')
        old=existing.get('worker_proof',{})
        inflight=existing.get('interrupted_intent')
        if (existing.get('mode')!='verify_review_only' or existing.get('seal')!=self.state['seal']
                or old.get('kind')!='interrupted_worker_no_completion_report' or not isinstance(inflight,dict)
                or old.get('repair_attempts')!=self.state['repair_attempts']):
            raise RepairHeld('original_interrupted_worker_attestation_required')
        sequence=inflight['sequence'];tail=self.state['commands'][sequence:]
        allowed_git=[['git','ls-files','--unmerged'],['git','diff','--check','HEAD']]
        proofs=[]
        for command in tail:
            role=command.get('role')
            allowed=(command.get('argv') in allowed_git if role=='git' else
                command.get('argv') in self.config[role] if role in ('regenerate','verify') else False)
            if not allowed or command.get('status')!='completed':
                raise RepairHeld('later_worker_reviewer_or_ambiguous_verification_refused')
            proofs.append(self._observed_dead_group(command,role))
        if not tail:raise RepairHeld('completed_verification_tail_required')
        worker=self._interrupted_worker_proof(job,inflight,minimum_mono,historical=True)
        old_refs={(a['kind'],a['path'],a['sha256']) for a in old.get('artifacts',[]) if a['kind'] in ('native_events','worker_stdout','worker_stderr')}
        new_refs={(a['kind'],a['path'],a['sha256']) for a in worker['artifacts']}
        if not old_refs or not old_refs<=new_refs:raise RepairHeld('original_worker_artifact_references_changed')
        old_census=Path(old['census_path'])
        archive=old_census if _sha(old_census.read_bytes())==old['census_sha256'] else self.evidence.parent/'worker-exit-census-original.json'
        if not archive.is_file() or _sha(archive.read_bytes())!=old['census_sha256']:
            raise RepairHeld('prior_worker_exit_attestation_not_retained')
        worker.update(prior_clock_uncertainty=old.get('prior_clock_uncertainty'),
            prior_census=dict(path=str(archive),sha256=old['census_sha256']),completed_tail_proofs=proofs)
        return worker,inflight

    def _worker_proof(self):
        provenance=self.state['patch_provenance']
        if (len(provenance)!=len(self.config['patches']) or {p.get('id') for p in provenance}!={p['id'] for p in self.config['patches']}
                or any(p.get('disposition') not in ('applied','rewritten','retired') for p in provenance)):
            raise RepairHeld('complete_patch_provenance_required')
        if self.state['repair_attempts']==0:
            if any(p['disposition']!='applied' for p in provenance):raise RepairHeld('worker_provenance_missing')
            return dict(kind='deterministic_replay',repair_attempts=0)
        workers=[(i,c) for i,c in enumerate(self.state['commands'],1) if c.get('role')=='worker' and c.get('status')=='completed' and c.get('exit_code')==0]
        if not workers:raise RepairHeld('complete_worker_report_required')
        sequence,command=workers[-1]
        path=self.evidence/f'{sequence}-worker-response.json'
        report=self._read_report(path,'worker')
        if report.get('identity')!=self.config['worker']['identity'] or report.get('status')!='repaired':
            raise RepairHeld('retained_worker_identity_mismatch')
        declarations=report.get('patch_dispositions',{})
        if not isinstance(declarations,dict) or set(declarations)!={p['id'] for p in provenance}:
            raise RepairHeld('retained_worker_patch_proof_incomplete')
        for patch in provenance:
            declaration=declarations[patch['id']]
            if not isinstance(declaration,dict) or any(declaration.get(k)!=patch.get(k) for k in ('disposition','evidence')):
                raise RepairHeld('retained_worker_patch_proof_changed')
            if patch['disposition']=='retired' and report.get('retirements',{}).get(patch['id'])!=patch.get('equivalence'):
                raise RepairHeld('retained_retirement_proof_changed')
        return dict(kind='completed_worker_report',sequence=sequence,identity=report['identity'],
            report_path=str(path),report_sha256=_sha(path.read_bytes()),repair_attempts=self.state['repair_attempts'])

    def reconcile(self,job,recipe,*,mode="verify_only"):
        """Readmit known stopped verification; never run a command or model."""
        if mode not in ('verify_only','verify_review_only'):raise RepairHeld('unsupported_reconciliation_mode')
        self.job=job;seal=self._seal(job,recipe)
        if not self.state_path.is_file():raise RepairHeld('held_repair_evidence_required')
        self.state=json.loads(self.state_path.read_text())
        if self.state.get('seal')!=seal:raise RepairHeld('repair_job_input_changed')
        minimum_mono=self.state.get('clock_anchor',{}).get('monotonic_latest')
        self._validate_config(recipe);self._budget()
        if self.state.get('repair_attempts')!=job.get('repair_attempts'):
            raise RepairHeld('original_attempt_accounting_differs')
        existing=self.state.get('verification_readmission')
        inventory=_inventory(self.workspace);source_digest=_digest(inventory)
        if self.state.get('status')=='verify_ready' and existing:
            if existing.get('mode')!=mode:raise RepairHeld('readmission_mode_changed')
            if self.state.get('inflight'):
                raise RepairHeld('verification_execution_unreconciled')
            if existing['source_digest']!=source_digest:raise RepairHeld('source_changed_after_readmission')
            return existing
        if self.state.get('status')!='held':raise RepairHeld('held_repair_evidence_required')
        inflight=self.state.get('inflight')
        repeating=mode=='verify_review_only' and existing and not inflight
        if mode=='verify_review_only':
            if repeating:worker,inflight=self._repeat_interrupted_verification(job,existing,minimum_mono)
            else:worker=self._interrupted_worker_proof(job,inflight,minimum_mono)
            dead=worker['dead_process']
        else:
            worker=self._worker_proof()
            dead=self._dead_owned_intent(inflight,'regenerate') if inflight else None
        if not inflight and any(c.get('status')=='intent' and not c.get('reconciliation') for c in self.state['commands']):
            raise RepairHeld('unreconciled_command_intent')
        receipt=dict(status='verification_ready',mode=mode,job_id=job['id'],seal=seal,
            repair_attempts=self.state['repair_attempts'],
            source_digest=source_digest,source_inventory_path=str(self.evidence/'verification-readmission-source.json'),worker_proof=worker,
            interrupted_intent=inflight,interrupted_regeneration=dead,previous_reason=self.state.get('reason'))
        if 'start' in job.get('clock_anchor', {}):
            receipt['allowance_anchor'] = job['clock_anchor']['start']
        else:
            receipt['monotonic_deadline'] = self.state['clock_anchor']['monotonic_deadline']
        if repeating:
            self.state.setdefault('verification_readmission_history',[]).append(existing)
        _atomic(self.evidence/'verification-readmission-source.json',inventory)
        if dead:self.state['commands'][inflight['sequence']-1]['reconciliation']=dead
        self.state.update(status='verify_ready',inflight=None,verification_readmission=receipt)
        self._save()
        return receipt

    def run(self,job,recipe):
        self.job=job
        first_wall=self.now()
        first_clock=self.clock()
        seal=self._seal(job,recipe)
        durable_anchor = job.get('clock_anchor', {}).get('start')
        # Keep the local observation for ordering process-census evidence.
        # The owner alone evaluates the persisted StableTime allowance.
        clock_anchor = dict(boot_id=first_clock.get('boot_id'), monotonic_latest=first_clock.get('seconds'))
        if durable_anchor is None:
            clock_anchor.update(monotonic_start=first_clock.get('seconds'),
                monotonic_deadline=first_clock.get('seconds',0)+max(0,job['deadline']-first_wall),
                wall_high_water=first_wall,wall_observed=first_wall,wall_adjustment_count=0,last_negative_delta=0,
                wall_observation='nondecreasing')
        self.state=dict(schema_version=1,seal=seal,repair_attempts=job.get('repair_attempts',0),last_seen=first_wall,
            clock_anchor=clock_anchor,commands=[],patch_provenance=[],inflight=None,status='applying')
        if durable_anchor is not None:
            self.state['allowance_anchor'] = durable_anchor
        verify_only=False
        if self.state_path.exists():
            self.state=json.loads(self.state_path.read_text())
            if self.state.get('seal')!=seal:
                raise RepairHeld('repair_job_input_changed')
            self.state['repair_attempts']=max(self.state['repair_attempts'],job.get('repair_attempts',0))
            try:
                self._budget()
            except (RepairHeld,OSError,ValueError) as error:
                self.state.update(status='held',reason=str(error));self._save()
                return dict(status='held',reason=str(error),repair_attempts=self.state['repair_attempts'],evidence=str(self.state_path))
            if self.state.get('status')=='reviewed':
                result=self.state['result']
                prepared=json.loads(Path(result['prepared_recipe']).read_text())
                if _identities(_inventory(Path(prepared['source']['tree'])))!=(result['candidate_digest'],result['tests_digest']):
                    raise RepairHeld('reviewed_snapshot_changed')
                return result
            if job.get('resume_mode') in ('verify_only','verify_review_only'):
                receipt=self.state.get('verification_readmission',{})
                if (self.state.get('status')!='verify_ready' or receipt.get('status')!='verification_ready'
                        or receipt.get('mode')!=job['resume_mode'] or receipt.get('seal')!=seal or self.state.get('inflight')
                        or receipt.get('source_digest')!=_digest(_inventory(self.workspace))):
                    raise RepairHeld('verification_readmission_required')
                verify_only=True
            else:
                return dict(status='held',reason='interrupted_repair_reconcile_required',repair_attempts=self.state['repair_attempts'],evidence=str(self.state_path))
        elif job.get('resume_mode') in ('verify_only','verify_review_only'):
            raise RepairHeld('verification_readmission_required')
        self._save()
        try:
            self._validate_config(recipe);self._budget()
            applied=not self._unresolved() if verify_only else self._replay()
            limit=job['limits']['repair_attempts']
            while True:
                verified=applied and self._verify()
                if verified:
                    review=self._review()
                    if review.get('status')=='approved':
                        prepared=self._prepared(recipe,review)
                        result=dict(status='reviewed',prepared_recipe=prepared,candidate_digest=review['candidate_digest'],tests_digest=review['tests_digest'],review=review,
                            repair_attempts=self.state['repair_attempts'],patch_provenance=self.state['patch_provenance'],evidence=str(self.state_path))
                        if self.config['reviewer'].get('require_patch_dispositions',False):
                            result.update(qualification_basis='independent_review_with_patch_dispositions',
                                original_patch_provenance=self.state['patch_provenance'],patch_provenance=self.state['independent_patch_provenance'])
                        if self.job.get('resume_mode')=='verify_review_only':
                            result.update(patch_provenance=self.state['independent_patch_provenance'],
                                original_patch_provenance=self.state['patch_provenance'],worker_completed=False,
                                qualification_basis='independent_review_after_interrupted_worker')
                        self.state.update(status='reviewed',result=result);self._save()
                        return result
                    self.state['findings']=review.get('findings',['review rejected'])
                if verify_only:
                    raise RepairHeld(self.job['resume_mode']+('_review_rejected' if verified else '_verification_failed'))
                if limit==0:
                    raise RepairHeld('coding_disabled_'+('review_rejected' if verified else 'verification_failed'))
                if self.state['repair_attempts']>=limit:
                    raise RepairHeld('repair_attempts_exhausted')
                self._budget()
                self.state['repair_attempts']+=1
                self._save()
                self.checkpoint(dict(repair_attempts=self.state['repair_attempts']))
                packet=self._packet('worker')
                code,output,path=self._command(self.config['worker']['argv'],'worker',packet=packet)
                if code:
                    reason=_explicit_worker_hold(output)
                    if reason:raise RepairHeld(reason)
                    self.state['findings']=['worker command failed'];applied=False
                    continue
                report=self._read_report(path,'worker')
                if report.get('identity') != self.config['worker']['identity'] or report.get('status') != 'repaired':
                    raise RepairHeld('worker_identity_or_status_mismatch')
                declarations=report.get('patch_dispositions',{})
                if not isinstance(declarations,dict) or set(declarations)!={p['id'] for p in self.config['patches']}:
                    raise RepairHeld('worker_patch_dispositions_incomplete')
                retirements=report.get('retirements',{})
                if not isinstance(retirements,dict):raise RepairHeld('invalid retirement declarations')
                known={p['id'] for p in self.config['patches']}
                if set(retirements)-known:raise RepairHeld('unknown retired patch')
                for patch in self.state['patch_provenance']:
                    declaration=declarations[patch['id']]
                    if not isinstance(declaration,dict) or declaration.get('disposition') not in ('applied','rewritten','retired') or not isinstance(declaration.get('evidence'),str) or not declaration['evidence'].strip():
                        raise RepairHeld('worker_patch_intent_evidence_missing')
                    patch.update(disposition=declaration['disposition'],evidence=declaration['evidence'])
                    if patch['disposition']=='retired':
                        if not isinstance(retirements.get(patch['id']),str) or not retirements[patch['id']].strip():
                            raise RepairHeld('retirement_equivalence_missing')
                        patch['equivalence']=retirements[patch['id']]
                self._save()
                applied=not self._unresolved()
        except (RepairHeld,OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
            self.state.update(status='held',reason=str(error));self._save()
            return dict(status='held',reason=str(error),repair_attempts=self.state['repair_attempts'],evidence=str(self.state_path))
