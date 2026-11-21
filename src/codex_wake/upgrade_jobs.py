"""Durable opt-in upgrade jobs. Recipes and executors are trusted host inputs.

The store lock fences control changes and promotion. Work runs in owned process
sessions outside the lock; every result is checked against the current generation.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from codex_profiles.upgrades import _atomic
from .managed_inventory import InventoryError
from . import measurements
from .upgrade_storage import owned_storage_bytes

DEFAULT_LIMITS = dict(repair_attempts=3, total_seconds=7200, compiler_jobs=2,
                      temporary_bytes=24 * 1024**3)
TERMINAL = frozenset(('succeeded', 'failed', 'held', 'disabled', 'superseded'))
READS = frozenset(('status', 'list', 'show'))


def occupies_upgrade_slot(job):
    return job['state'] not in TERMINAL or bool(job.get('worker') or job.get('active_phase'))


def policy_digest(config):
    return digest({key:config.get(key) for key in ('target','limits','repair','qualification','promotion')})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def process_identity(pid):
    try:
        value = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'start': value[19], 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, IndexError):
        return None


class UpgradeJobs:
    def __init__(self, root, *, now=None, executor=None, clock=None):
        self.root = Path(root)
        self.store = self.root / 'upgrade-jobs'
        self.now = now or time.time
        self.executor = executor
        self.clock = clock or measurements.snapshot
        self.authorization_time = now or measurements.utc_time

    def config(self):
        path=self.root/'upgrade-bot.json'
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
            raise InventoryError('invalid_configuration','host upgrade configuration ownership or permissions invalid')
        value = json.loads(path.read_text())
        if value.get('schema_version') != 1 or not isinstance(value.get('target'), dict) or not value['target']:
            raise InventoryError('invalid_configuration', 'versioned fixed upgrade target required')
        limits = dict(DEFAULT_LIMITS, **value.get('limits', {}))
        if set(limits) != set(DEFAULT_LIMITS) or any(type(v) is not int or v < (0 if k=='repair_attempts' else 1) for k,v in limits.items()):
            raise InventoryError('invalid_configuration', 'nonnegative repair attempts and positive integer upgrade limits required')
        value['limits'] = limits
        value['recipes'] = dict(value.get('recipes', {}))
        catalog_path = self.store / 'generated-recipes.json'
        discovery = value.get('discovery', {})
        if discovery.get('recipe_template') and catalog_path.exists():
            template_sha = hashlib.sha256(Path(discovery['recipe_template']).read_bytes()).hexdigest()
            if template_sha != discovery.get('recipe_template_sha256'):
                raise InventoryError('stale_template', 'host recipe template pin changed')
            catalog = json.loads(catalog_path.read_text())
            if catalog.get('schema_version') != 1:
                raise InventoryError('unsupported_schema', 'generated recipe catalog schema unsupported')
            for name, row in catalog.get('recipes', {}).items():
                if row.get('template_sha256') != template_sha:
                    continue
                path = Path(row['path'])
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                    raise InventoryError('stale_recipe', 'generated recipe pin changed')
                value['recipes'][name] = str(path)
        return value

    def register_generated_recipe(self, name, path, expected_sha256):
        # Host-internal only: discovery can fill release/source identity, never
        # invent executable recipe instructions downloaded from the network.
        from codex_profiles.upgrades import official_source_url
        with self.locked():
            config = self.config()
            declaration = config.get('discovery', {})
            template_path = Path(declaration['recipe_template'])
            template = json.loads(template_path.read_text())
            template_sha = hashlib.sha256(template_path.read_bytes()).hexdigest()
            if template_sha != declaration.get('recipe_template_sha256'):
                raise InventoryError('stale_template', 'host recipe template pin required')
            path = Path(path).resolve(strict=True)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
                raise InventoryError('stale_recipe', 'generated recipe pin mismatch')
            recipe = json.loads(path.read_text())
            mutable = {'id','upstream_version','revision','source'}
            if {k:v for k,v in template.items() if k not in mutable} != {k:v for k,v in recipe.items() if k not in mutable}:
                raise InventoryError('unauthorized_target', 'generated recipe changed host execution policy')
            source = recipe.get('source', {})
            if not official_source_url(source.get('official_url')) or not isinstance(source.get('sha256'), str) or len(source['sha256']) != 64:
                raise InventoryError('invalid_source', 'pinned official source archive required')
            catalog_path = self.store / 'generated-recipes.json'
            catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else dict(schema_version=1,recipes={})
            previous = catalog['recipes'].get(name)
            row = dict(path=str(path), sha256=expected_sha256, template_sha256=template_sha, upstream_version=recipe.get('upstream_version'))
            if previous and previous != row:
                raise InventoryError('stale_recipe', 'generated recipe name already bound to other bytes')
            catalog['recipes'][name] = row
            _atomic(catalog_path, catalog)
            return row

    @contextmanager
    def locked(self):
        self.store.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.store.is_symlink() or self.store.stat().st_uid != os.getuid() or self.store.stat().st_mode & 0o022:
            raise InventoryError('invalid_configuration','upgrade store ownership or permissions invalid')
        fd=os.open(self.store/'.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def load(self):
        path = self.store / 'state.json'
        if not path.exists():
            return dict(schema_version=1, enabled=False, generation=0, jobs={}, events=[])
        value = json.loads(path.read_text())
        if value.get('schema_version') != 1:
            raise InventoryError('unsupported_schema', 'upgrade state schema unsupported')
        return value

    def save(self, state):
        _atomic(self.store / 'state.json', state)

    def event(self, state, kind, job=None, **details):
        state['events'].append(dict(id=len(state['events']) + 1, kind=kind,
            job_id=job['id'] if job else None, at=self.now(), **details))

    def guard(self, actor, target, arguments, authorize, *, write=False):
        current = authorize() if authorize else actor
        expiry=getattr(current,'expires_at',None)
        if expiry is not None:
            try:
                expired = type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= self.authorization_time()
            except measurements.TimeUnavailable as error:
                raise InventoryError('clock_uncertain', str(error)) from error
            if expired:
                raise InventoryError('unauthorized_target', 'current upgrade grant expired')
        if current.subject != actor.subject or ('admin' if write else 'observe') not in current.scopes:
            raise InventoryError('unauthorized_target', 'current upgrade grant required')
        if arguments.get('expected_target') != target or not any(
                all(target.get(k) == v for k, v in scope.items()) for scope in current.targets):
            raise InventoryError('unauthorized_target', 'exact host-configured upgrade scope required')

    def execute(self, actor, operation, arguments, *, authorize=None):
        verb = operation.removeprefix('upgrades.')
        allowed = dict(status=set(), list=set(), show={'job_id'}, enable=set(), disable=set(),
                       start={'recipe', 'expected_recipe_sha256', 'upstream_version'}, advance={'job_id'}, cancel={'job_id'}, rollback={'job_id','operation_id'}, reconcile={'job_id','mode'}, cache_cleanup=set())
        if not operation.startswith('upgrades.') or verb not in allowed or not isinstance(arguments, dict):
            raise InventoryError('invalid_argument', 'exact upgrade job arguments required')
        optional = {'expected_recipe_sha256', 'upstream_version'} if verb == 'start' else set()
        required = (allowed[verb] - optional) | {'expected_target'}
        if set(arguments) - (allowed[verb] | {'expected_target'}) or required - set(arguments):
            raise InventoryError('invalid_argument', 'exact upgrade job arguments required')
        config = self.config()
        self.compiler_cache(config)
        self.guard(actor, config['target'], arguments, authorize, write=verb not in READS)
        if verb == 'reconcile':
            with self.runner_lease(arguments['job_id']):
                result=self.reconcile(actor,arguments,authorize)
        elif verb == 'rollback':
            with self.runner_lease(arguments['job_id']):
                result=self.rollback(actor,arguments,authorize)
        elif verb == 'advance':
            with self.runner_lease(arguments['job_id']):
                result = self.advance(actor, arguments, authorize)
        else:
            with self.locked():
                state = self.load()
                if state.get('target',config['target'])!=config['target'] or any(j['target']!=config['target'] for j in state['jobs'].values()):
                    raise InventoryError('unauthorized_target','upgrade store is sealed to its original host scope')
                state.setdefault('target',config['target'])
                self.guard(actor, config['target'], arguments, authorize, write=verb not in READS)
                if verb == 'status':
                    result = dict(enabled=state['enabled'], generation=state['generation'],
                        limits=config['limits'], target=config['target'], events=state['events'],
                        notice_delivery=self.notice_summary(), compiler_cache=self.compiler_cache(config))
                elif verb == 'cache_cleanup':
                    if any(occupies_upgrade_slot(job) for job in state['jobs'].values()):
                        raise InventoryError('upgrade_busy','compiler cache owner remains active or uncertain')
                    cache=self.compiler_cache(config)
                    path=Path(cache['path'])
                    if path.exists():shutil.rmtree(path)
                    self.event(state,'compiler_cache_cleaned',bytes=cache['bytes'])
                    result=dict(compiler_cache=self.compiler_cache(config),reclaimed_bytes=cache['bytes'])
                elif verb == 'list':
                    result = dict(jobs=list(state['jobs'].values()))
                elif verb in ('show', 'cancel'):
                    job = self.job(state, arguments['job_id'])
                    if verb == 'cancel' and job['state'] not in TERMINAL:
                        self.stop(job)
                        job.update(state='disabled', reason='cancelled_by_operator')
                        self.event(state, 'cancelled', job)
                    result = dict(job=job)
                elif verb in ('enable', 'disable'):
                    state['enabled'] = verb == 'enable'
                    state['generation'] += 1
                    if verb == 'disable':
                        for job in state['jobs'].values():
                            if job['state'] not in TERMINAL:
                                self.stop(job)
                                job.update(state='disabled', reason='disabled_by_operator')
                    self.event(state, verb)
                    result = dict(enabled=state['enabled'], generation=state['generation'])
                else:
                    if not state['enabled']:
                        raise InventoryError('upgrade_disabled', 'explicit upgrade enable required')
                    name = arguments['recipe']
                    if not isinstance(name, str) or name not in config.get('recipes', {}):
                        raise InventoryError('unauthorized_target', 'host-approved upgrade recipe required')
                    recipe_path = Path(config['recipes'][name]).resolve(strict=True)
                    recipe = json.loads(recipe_path.read_text())
                    if arguments.get('expected_recipe_sha256', hashlib.sha256(recipe_path.read_bytes()).hexdigest()) != hashlib.sha256(recipe_path.read_bytes()).hexdigest() or arguments.get('upstream_version', recipe.get('upstream_version')) != recipe.get('upstream_version'):
                        raise InventoryError('stale_recipe', 'resolved release recipe changed before job admission')
                    key = digest(dict(recipe=recipe, target=config['target']))
                    existing = next((j for j in state['jobs'].values() if j['key'] == key), None)
                    if existing:
                        result = dict(job=existing)
                    else:
                        if any(occupies_upgrade_slot(job) for job in state['jobs'].values()):
                            raise InventoryError('upgrade_busy', 'one upgrade candidate at a time')
                        job = dict(id=uuid.uuid4().hex, key=key, recipe=name,
                            recipe_path=str(recipe_path), recipe_sha256=hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
                            version=recipe.get('upstream_version'), target=config['target'], state='queued',
                            created_at=self.now(), deadline=self.now()+config['limits']['total_seconds'],
                            last_seen=self.now(), repair_attempts=0, limits=config['limits'], generation=state['generation'],
                            stage_id=recipe.get('id'), worker=None, results={}, policy_sha256=policy_digest(config))
                        try:
                            observation = self.clock()
                            measurements.elapsed_bounds(observation, observation)
                        except measurements.TimeUnavailable as error:
                            raise InventoryError('clock_uncertain', str(error)) from error
                        job['clock_anchor'] = dict(start=observation, latest=observation)
                        state['jobs'][job['id']] = job
                        self.event(state, 'queued', job)
                        result = dict(job=job)
                self.save(state)
        if verb == 'advance':
            self.reclaim_terminal_cache(arguments['job_id'])
        if verb not in READS:
            self.notify(actor, authorize)
        return dict(schema_version=1, operation=operation, status='completed', result=result)

    def disable_local(self):
        """Local file owner may always stop this bot; this grants no new work.

        Remote and native-MCP callers still use authenticated scoped controls.
        The local operator owns the private config/store and could already stop
        these same-user processes. Expired service credentials cannot trap ON.
        """
        self.config()  # validates the local host file's ownership and permissions
        with self.locked():
            state=self.load();state['enabled']=False;state['generation']+=1
            for job in state['jobs'].values():
                if job['state'] not in TERMINAL:
                    self.stop(job)
                    job.update(state='disabled',reason='disabled_by_local_operator')
            self.event(state,'disable',reason='local_operator')
            self.save(state)
            result=dict(enabled=False,generation=state['generation'],authority='local_file_owner')
        try:
            from .operation_commands import local_actor
            self.notify(local_actor(self.root),None)
        except (OSError,ValueError,KeyError) as error:
            _atomic(self.store/'notice-drain-status.json',dict(status='failed',reason=getattr(error,'code','notice_authority_unavailable'),at=self.now()))
        return dict(schema_version=1,operation='upgrades.disable',status='completed',result=result)

    @contextmanager
    def runner_lease(self, identifier):
        with self.locked():
            self.job(self.load(),identifier)
        name=hashlib.sha256(identifier.encode()).hexdigest()
        fd=os.open(self.store/('.runner-'+name),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise InventoryError('upgrade_busy','the original upgrade advance remains active') from error
            yield
        finally:os.close(fd)

    def reclaim_terminal_cache(self, identifier):
        with self.locked():
            state=self.load();job=self.job(state,identifier)
            if job['state'] not in TERMINAL or job.get('active_phase') or job.get('worker'):
                return
            # Legacy job-local scratch only; the shared compiler cache survives holds.
            cache=self.store/identifier/'cargo-target'
            if cache.exists() or cache.is_symlink():
                if cache.is_symlink() or not cache.resolve().is_relative_to((self.store/identifier).resolve()):
                    job['cache_reclamation']=dict(status='held',reason='owned_cache_path_changed')
                else:
                    size=owned_storage_bytes((cache,))
                    shutil.rmtree(cache)
                    job['cache_reclamation']=dict(status='reclaimed',bytes=size,at=self.now())
                self.save(state)

    def compiler_cache(self, config):
        path=self.root/'upgrade-compiler-cache'
        if path.is_symlink() or (path.exists() and (not path.is_dir() or path.stat().st_uid!=os.getuid() or path.stat().st_mode & 0o022)):
            raise InventoryError('invalid_configuration','compiler cache ownership or permissions invalid')
        return dict(path=str(path), identity=digest(dict(root=str(self.root.resolve()),target=config['target'])),
            bytes=owned_storage_bytes((path,)), limit_bytes=config['limits']['temporary_bytes'],
            retention='until_explicit_cleanup', invalidation='cargo_fingerprints')

    def notice_summary(self):
        from .upgrade_notices import UpgradeNotices
        value=UpgradeNotices(self.root).summary()
        drain_status=self.store/'notice-drain-status.json'
        if drain_status.exists():value['last_drain']=json.loads(drain_status.read_text())
        return value

    def notify(self, actor, authorize):
        from .upgrade_notices import UpgradeNotices
        try:
            UpgradeNotices(self.root).drain(actor, authorize=authorize or (lambda: actor))
            _atomic(self.store/'notice-drain-status.json',dict(status='completed',at=self.now()))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            # Notice delivery is independently observable, never grounds for
            # changing an already committed upgrade outcome or replaying work.
            _atomic(self.store/'notice-drain-status.json', dict(status='failed',
                reason=getattr(error,'code',type(error).__name__),at=self.now()))

    def job(self, state, identifier):
        if not isinstance(identifier, str) or identifier not in state['jobs']:
            raise InventoryError('unknown_job', 'unknown upgrade job')
        return state['jobs'][identifier]

    def stop(self, job):
        worker = job.get('worker')
        if worker and process_identity(worker['pid']) == worker:
            try:
                os.killpg(worker['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
        job['worker'] = None

    def budget_reason(self, job):
        anchor = job.get('clock_anchor') or {}
        if 'start' not in anchor or 'latest' not in anchor:
            return 'clock_uncertain'
        try:
            observation = self.clock()
            measurements.elapsed_bounds(anchor['latest'], observation)
            _, elapsed = measurements.elapsed_bounds(anchor['start'], observation)
        except measurements.TimeUnavailable as error:
            return str(error)
        anchor['latest'] = observation
        if elapsed >= job['limits']['total_seconds']:
            return 'deadline_exhausted'
        workspace = self.store / job['id']
        size = owned_storage_bytes((workspace, self.root/'upgrade-compiler-cache'))
        if size > job['limits']['temporary_bytes']:
            return 'temporary_storage_exhausted'
        return None

    def advance(self, actor, arguments, authorize):
        with self.locked():
            state = self.load()
            job = self.job(state, arguments['job_id'])
            self.guard(actor, job['target'], arguments, authorize, write=True)
            if job['state'] in TERMINAL:
                return dict(job=job)
            reason = self.budget_reason(job)
            if not state['enabled'] or reason:
                self.stop(job)
                job.update(state='held', reason=reason or 'upgrade_disabled')
                self.event(state, 'held', job, reason=job['reason'])
                self.save(state)
                return dict(job=job)
            if job.get('active_phase') and not job['worker'] and job['active_phase']!='promote':
                job.update(state='held', reason='worker_intent_pending_reconciliation')
                self.event(state, 'held', job, reason=job['reason'])
                self.save(state)
                return dict(job=job)
            if job['worker']:
                if process_identity(job['worker']['pid']) == job['worker']:
                    raise InventoryError('upgrade_busy', 'owned upgrade worker remains active')
                job.update(state='held', reason='worker_lost_reconcile_required')
                self.event(state, 'held', job, reason=job['reason'])
                self.save(state)
                return dict(job=job)
            config = self.config()
            if str(Path(config['recipes'].get(job['recipe'], '')).resolve()) != job['recipe_path'] or hashlib.sha256(Path(job['recipe_path']).read_bytes()).hexdigest() != job['recipe_sha256']:
                raise InventoryError('stale_recipe', 'pinned upgrade recipe changed')
            phase = ('promote' if job['state']=='promoting' or job.get('active_phase')=='promote'
                else 'qualify' if job['state']=='qualifying' else 'stage')
            job['active_phase'] = phase
            job['state'] = {'qualify':'qualifying','promote':'promoting','stage':'building'}[phase]
            self.event(state, job['state'], job)
            self.save(state)
            frozen = json.loads(json.dumps(job))
        self.notify(actor, authorize)
        try:
            committing=[False]
            def guard_locked():
                current_state=self.load();current=self.job(current_state,frozen['id'])
                self.guard(actor,current['target'],arguments,authorize,write=True)
                current_config=self.config()
                reason=self.budget_reason(current)
                self.save(current_state)
                if current_config['target']!=frozen['target'] or policy_digest(current_config)!=frozen.get('policy_sha256'):
                    raise ValueError('upgrade_policy_changed')
                if not current_state['enabled'] or current['state'] in TERMINAL or current_state['generation']!=frozen['generation'] or reason:
                    raise ValueError(reason or 'upgrade_policy_changed')
            def guard():
                if committing[0]:
                    guard_locked()
                else:
                    with self.locked():guard_locked()
            def commit(action):
                with self.locked():
                    committing[0]=True
                    try:
                        guard_locked()
                        current_state=self.load();current=self.job(current_state,frozen['id'])
                        current['selection_intent']=dict(status='prepared',at=self.now(),generation=current_state['generation'])
                        self.save(current_state)
                        outcome=action()
                        current_state=self.load();current=self.job(current_state,frozen['id'])
                        current['selection_intent'].update(status='committed',result=outcome)
                        current['results']['promotion']=outcome
                        current.update(state='succeeded',reason='future_launch_selection_committed',active_phase=None,worker=None)
                        self.event(current_state,'succeeded',current,reason=current['reason'])
                        self.save(current_state)
                        return outcome
                    finally:committing[0]=False
            def checkpoint(delta):
                guard()
                with self.locked():
                    current_state=self.load();current=self.job(current_state,frozen['id'])
                    value=delta['repair_attempts']
                    if type(value) is not int or value<current['repair_attempts'] or value>current['limits']['repair_attempts']:
                        raise ValueError('invalid_repair_budget_checkpoint')
                    current['repair_attempts']=value
                    self.save(current_state)
            if self.executor:
                result=self.executor(frozen)
            elif frozen['active_phase']=='promote':
                from .upgrade_promotion import UpgradePromotion
                result=UpgradePromotion(self.root,now=self.now).run(frozen,config,guard=guard,commit=commit)
            elif frozen['active_phase']=='qualify':
                from .upgrade_qualification import UpgradeQualification
                if not config.get('qualification'):
                    result=dict(status='held',reason='disposable_qualification_not_configured')
                else:
                    result=UpgradeQualification(self.root).run(frozen,config['qualification'],guard=guard)
            else:
                from .upgrade_pipeline import prepare_reviewed_recipe
                guard()
                repair=prepare_reviewed_recipe(self.root,frozen,config,guard=guard,checkpoint=checkpoint)
                if repair is not None:
                    with self.locked():
                        current_state=self.load();current=self.job(current_state,frozen['id'])
                        current['results']['repair']=repair
                        self.save(current_state)
                    if repair.get('status')!='reviewed':
                        result=dict(status='held',reason=repair.get('reason','semantic_repair_held'))
                    else:
                        frozen['prepared_recipe']=repair['prepared_recipe']
                        result=self.run_stage(frozen, guard_locked=guard_locked)
                else:
                    result=self.run_stage(frozen, guard_locked=guard_locked)
            if not isinstance(result, dict):
                raise ValueError('upgrade executor returned no structured outcome')
        except Exception as error:
            result = dict(status='failed', reason=str(error))
        with self.locked():
            state = self.load();job = self.job(state, frozen['id'])
            try:
                self.guard(actor, job['target'], arguments, authorize, write=True)
            except (InventoryError, ValueError, OSError):
                job.update(worker=None, active_phase=None)
                if job['state'] not in TERMINAL:
                    job.update(state='held', reason='upgrade_authority_unavailable')
                    self.event(state, 'held', job, reason=job['reason'])
                self.save(state)
                raise
            if job['state'] in TERMINAL:
                job.update(worker=None,active_phase=None)
                if frozen['active_phase']=='promote':job['results']['promotion_observation']=result
                self.save(state)
                return dict(job=job)
            reason = self.budget_reason(job)
            job['worker'] = None
            job['active_phase'] = None
            job['results'][{'qualify':'qualification','promote':'promotion','stage':'stage'}[frozen['active_phase']]] = result
            if not state['enabled'] or state['generation'] != frozen['generation'] or reason:
                job.update(state='held', reason=reason or 'policy_changed')
            elif result.get('status') == 'selected':
                job.update(state='succeeded',reason='future_launch_selection_reconciled')
            elif result.get('status') == 'qualified':
                job.update(state='promoting', reason='awaiting_qualified_selection')
            elif result.get('status') == 'staged':
                job.update(state='qualifying', reason='awaiting_disposable_qualification')
            else:
                job.update(state='held', reason=result.get('reason', 'stage_failed'))
            self.event(state, job['state'], job, reason=job['reason'])
            self.save(state)
            return dict(job=job)

    def reconcile(self, actor, arguments, authorize):
        mode=arguments['mode']
        if mode not in ('verify_only','verify_review_only','qualification_only','promotion_observe'):
            raise InventoryError('invalid_argument','explicit upgrade reconciliation mode required')
        with self.locked():
            config=self.config();state=self.load();job=self.job(state,arguments['job_id'])
            self.guard(actor,job['target'],arguments,authorize,write=True)
            if mode=='promotion_observe':
                # Observation never replays selection or renews the original work.
                # A later disable/expiry cannot hide an already committed effect.
                if not job.get('selection_intent'):
                    raise InventoryError('reconciliation_required','existing promotion intent required')
                if job.get('worker') or job.get('active_phase') not in (None,'promote'):
                    raise InventoryError('reconciliation_refused','owned worker observation unresolved')
                from .upgrade_promotion import UpgradePromotion
                observed=UpgradePromotion(self.root,now=self.now).reconcile(job,config)
                job['results']['promotion_observation']=observed
                job.setdefault('reconciliations',[]).append(dict(mode=mode,at=self.now(),receipt=observed))
                if job['state'] not in TERMINAL:
                    job.update(state='succeeded' if observed.get('status')=='selected' else 'held',
                        reason='promotion_outcome_observed',active_phase=None)
                self.event(state,'promotion_observed',job,reason=observed.get('reason','committed_selection_observed'))
                self.save(state)
                return dict(job=job)
            evidence=self.store/job['id']/'repair'/'repair-state.json'
            if job['state']!='held' or not config.get('repair') or not evidence.is_file():
                raise InventoryError('reconciliation_required','held repair evidence required')
            reason=self.budget_reason(job)
            if (not state['enabled'] or state['generation']!=job['generation'] or reason
                    or policy_digest(config)!=job['policy_sha256']):
                raise InventoryError('reconciliation_refused',reason or 'original upgrade authority changed')
            if any(other['id'] != job['id'] and occupies_upgrade_slot(other) for other in state['jobs'].values()):
                raise InventoryError('upgrade_busy','another upgrade job remains active')
            if job.get('worker') or job.get('active_phase'):
                raise InventoryError('reconciliation_refused','owned worker observation unresolved')
            path=Path(job['recipe_path'])
            if (str(Path(config['recipes'].get(job['recipe'],'')).resolve())!=str(path)
                    or hashlib.sha256(path.read_bytes()).hexdigest()!=job['recipe_sha256']):
                raise InventoryError('stale_recipe','pinned upgrade recipe changed')
            from .upgrade_pipeline import reconcile_reviewed_recipe
            def guard():
                self.guard(actor,job['target'],arguments,authorize,write=True)
                reason=self.budget_reason(job)
                if reason:raise InventoryError('reconciliation_refused',reason)
            previous_reason=job.get('reason')
            if mode=='qualification_only':
                from .upgrade_qualification import UpgradeQualification
                try:receipt=UpgradeQualification(self.root,now=self.now).reconcile(job,config.get('qualification',{}),guard=guard)
                except (OSError,ValueError,KeyError) as error:raise InventoryError('reconciliation_refused',str(error)) from error
                guard()
                job.setdefault('reconciliations',[]).append(dict(mode=mode,at=self.now(),previous_reason=previous_reason,receipt=receipt,controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
                job.update(state='qualifying',reason='qualification_readmitted',resume_mode=mode)
                self.event(state,'qualification_readmitted',job,reason='same_stage_original_budget',mode=mode)
                self.save(state)
                return dict(job=job)
            receipt=reconcile_reviewed_recipe(self.root,job,config,guard=guard,**({'mode':mode} if mode!='verify_only' else {}))
            if not isinstance(receipt,dict) or receipt.get('status')!='verification_ready' or receipt.get('mode')!=mode:
                raise InventoryError('reconciliation_refused','verification readiness not established')
            guard()
            job.setdefault('reconciliations',[]).append(dict(mode=mode,at=self.now(),
                previous_reason=previous_reason,receipt=receipt,controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
            job.update(state='queued',reason='verification_readmitted',resume_mode=mode)
            self.event(state,'verification_readmitted',job,reason='known_interrupted_worker_verify_review_only' if mode=='verify_review_only' else 'same_job_original_budget',mode=mode)
            self.save(state)
            return dict(job=job)

    def rollback(self, actor, arguments, authorize):
        from .upgrade_promotion import UpgradePromotion
        config=self.config()
        with self.locked():
            original=self.job(self.load(),arguments['job_id'])
            self.guard(actor,original['target'],arguments,authorize,write=True)
        committing=[False]
        def guard_locked():
            current_config=self.config()
            self.guard(actor,original['target'],arguments,authorize,write=True)
            if current_config['target']!=original['target'] or current_config.get('promotion')!=config.get('promotion'):
                raise ValueError('rollback_target_changed')
        def guard():
            if committing[0]:guard_locked()
            else:
                with self.locked():guard_locked()
        def commit(action):
            with self.locked():
                committing[0]=True
                try:
                    guard_locked()
                    value=action()
                    state=self.load();job=self.job(state,original['id'])
                    job.setdefault('rollback_operations',{})[arguments['operation_id']]=value
                    self.event(state,'rollback',job,reason='explicit_future_launch_rollback')
                    self.save(state)
                    return value
                finally:committing[0]=False
        value=UpgradePromotion(self.root,now=self.now).rollback(config,
            operation_id=arguments['operation_id'],guard=guard,commit=commit)
        return dict(rollback=value)

    def run_stage(self, job, *, guard_locked):
        directory = self.store / job['id'];directory.mkdir(mode=0o700, exist_ok=True)
        self.compiler_cache(self.config())
        (self.root/'upgrade-compiler-cache').mkdir(mode=0o700,exist_ok=True)
        recipe_bytes = Path(job.get('prepared_recipe',job['recipe_path'])).read_bytes()
        if not job.get('prepared_recipe') and hashlib.sha256(recipe_bytes).hexdigest() != job['recipe_sha256']:
            raise InventoryError('stale_recipe', 'pinned upgrade recipe changed')
        frozen_recipe = directory / 'recipe.json'
        _atomic(frozen_recipe, json.loads(recipe_bytes))
        # Child inherits no Codex credentials; build recipes are host-owned.
        with tempfile.TemporaryDirectory(prefix='worker-home-', dir=directory) as home:
            env = {k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','PYTHONPATH')}
            env.update(CODEX_UPGRADE_TEMP_ROOT=str(directory), CODEX_UPGRADE_OWNED_GROUP='1', HOME=home, CODEX_HOME=home+'/.codex', XDG_CONFIG_HOME=home+'/.config',
                XDG_DATA_HOME=home+'/.local/share', CARGO_BUILD_JOBS=str(job['limits']['compiler_jobs']), CARGO_TARGET_DIR=str(self.root/'upgrade-compiler-cache'))
            Path(env['CODEX_HOME']).mkdir(mode=0o700)
            output = directory / 'stage-result.json'
            with (directory / 'worker.log').open('ab') as log:
                process = None
                try:
                    with self.locked():
                        guard_locked()
                        process = subprocess.Popen([sys.executable, '-m', 'codex_wake.upgrade_stage_worker',
                            str(directory / 'build-store'), str(frozen_recipe), str(output)],
                            env=env, stdout=log, stderr=log, start_new_session=True)
                        identity = process_identity(process.pid)
                        if identity is None and process.poll() is None:
                            raise InventoryError('upgrade_worker_unverified', 'stage worker identity unavailable')
                        state = self.load()
                        self.job(state, job['id'])['worker'] = identity
                        self.save(state)
                    while process.poll() is None:
                        with self.locked():
                            guard_locked()
                        time.sleep(.1)
                finally:
                    if process is not None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                if output.is_file():return json.loads(output.read_text())
                return dict(status='failed',reason='stage_worker_exit_'+str(process.returncode))
