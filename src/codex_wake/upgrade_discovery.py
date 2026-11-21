"""Persistent opt-in stable-release discovery over durable upgrade jobs.

Release metadata selects only existing host-approved, version-pinned recipes.
It never supplies executable build instructions. Poll cursors are independent of
job budgets: rediscovery of a failed release returns its original job unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from codex_profiles.upgrades import _atomic, check
from .managed_inventory import InventoryError
from . import measurements
from .upgrade_jobs import TERMINAL, UpgradeJobs

OFFICIAL_API = 'https://api.github.com/repos/openai/codex/releases/latest'
VERSION = re.compile(r'\d+\.\d+\.\d+')


def version_key(value):
    if not isinstance(value, str) or VERSION.fullmatch(value) is None:
        raise InventoryError('release_unavailable', 'stable numeric upstream version required')
    return tuple(int(part) for part in value.split('.'))


class UpgradeDiscovery:
    def __init__(self, root, *, now=None, fetch=None, jobs=None, source_resolver=None):
        self.root = Path(root)
        self.store = self.root / 'upgrade-discovery'
        self.now = now or measurements.utc_time
        self.fetch = fetch or (lambda: check(self.root, ttl=0))
        self.jobs = jobs or UpgradeJobs(root, now=now)
        self.source_resolver = source_resolver

    @contextmanager
    def locked(self):
        self.store.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.store / '.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def load(self):
        path = self.store / 'state.json'
        if not path.exists():
            return dict(schema_version=1, status='idle', last_poll=None, next_due=0,
                latest_version=None, release_url=None, lag={}, skipped=[], releases={}, job_id=None)
        state = json.loads(path.read_text())
        if state.get('schema_version') != 1:
            raise InventoryError('unsupported_schema', 'upgrade discovery state unsupported')
        return state

    def status(self):
        with self.locked():
            return self.load()

    def save(self, state):
        _atomic(self.store / 'state.json', state)
        return state

    def configuration(self):
        config = self.jobs.config()
        options = config.get('discovery', {})
        interval = options.get('interval_seconds', 21600)
        if type(interval) is not int or not 60 <= interval <= 86400:
            raise InventoryError('invalid_configuration', 'discovery interval must be 60 to 86400 seconds')
        return config, interval

    def validate_release(self, release):
        if not isinstance(release, dict) or release.get('schema_version') != 1 or release.get('status') != 'available':
            raise InventoryError('release_unavailable', 'official stable release metadata unavailable')
        version = release.get('latest_version')
        version_key(version)
        expected = 'https://github.com/openai/codex/releases/tag/rust-v' + version
        if release.get('origin') != OFFICIAL_API or release.get('release_url') != expected:
            raise InventoryError('release_unavailable', 'official Codex release provenance mismatch')
        if release.get('draft') or release.get('prerelease'):
            raise InventoryError('release_unavailable', 'draft or prerelease is not eligible')
        return version

    def recipe_for(self, config, version):
        matches = []
        prefix = 'https://github.com/openai/codex/releases/download/rust-v' + version + '/'
        for name, location in config.get('recipes', {}).items():
            path = Path(location).resolve(strict=True)
            recipe = json.loads(path.read_text())
            if recipe.get('upstream_version') != version:
                continue
            source = recipe.get('source', {})
            url = source.get('official_url', '')
            parsed = urlsplit(url)
            archived = re.fullmatch(r'https://github.com/openai/codex/archive/[0-9a-f]{40}\.tar\.gz',url) is not None
            if (not archived and not url.startswith(prefix)) or parsed.query or parsed.fragment or (not archived and not parsed.path.removeprefix(urlsplit(prefix).path)):
                raise InventoryError('release_recipe_unavailable', 'release recipe provenance does not match discovered version')
            archive_pin = source.get('sha256')
            files = source.get('files')
            if source.get('tree'):
                if not isinstance(files, dict) or not files or any(not isinstance(v,str) or re.fullmatch('[0-9a-f]{64}',v) is None for v in files.values()):
                    raise InventoryError('release_recipe_unavailable', 'version-pinned source inventory required')
            elif not isinstance(archive_pin, str) or re.fullmatch('[0-9a-f]{64}', archive_pin) is None:
                raise InventoryError('release_recipe_unavailable', 'version-pinned source archive digest required')
            matches.append((name, hashlib.sha256(path.read_bytes()).hexdigest()))
        if not matches and config.get('discovery',{}).get('recipe_template'):
            name, path, pin = self.generate_recipe(config, version)
            self.jobs.register_generated_recipe(name, path, pin)
            return name, pin
        if len(matches) != 1:
            raise InventoryError('release_recipe_unavailable', 'exactly one host-approved recipe for release required')
        return matches[0]

    def generate_recipe(self, config, version):
        """Resolve public source while retaining every trusted template command."""
        from .upgrade_source import OfficialSourceResolver
        options = config.get('discovery',{})
        template = dict(path=options.get('recipe_template'),sha256=options.get('recipe_template_sha256'))
        if not isinstance(template['path'],str) or not isinstance(template['sha256'],str):
            raise InventoryError('invalid_configuration', 'pinned host recipe template required')
        path = Path(template['path']).resolve(strict=True)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != template['sha256']:
            raise InventoryError('invalid_configuration', 'host recipe template changed')
        recipe = json.loads(raw)
        if recipe.get('schema_version') != 1:
            raise InventoryError('invalid_configuration', 'host recipe template schema unsupported')
        options = config.get('discovery', {})
        resolver = self.source_resolver or OfficialSourceResolver(self.store,
            maximum_bytes=options.get('source_maximum_bytes',512*1024**2),
            timeout_seconds=options.get('source_timeout_seconds',120)).resolve
        resolved = resolver(version)
        commit = resolved.get('commit')
        if not isinstance(commit,str) or re.fullmatch('[0-9a-f]{40}',commit) is None:
            raise InventoryError('source_unavailable', 'resolved official commit required')
        source = resolved.get('source',{})
        if source.get('official_url') != 'https://github.com/openai/codex/archive/'+commit+'.tar.gz' or not isinstance(source.get('sha256'),str) or re.fullmatch('[0-9a-f]{64}',source['sha256']) is None:
            raise InventoryError('source_unavailable', 'resolved official source provenance invalid')
        archive = Path(source.get('archive_file','')).resolve(strict=True)
        # The source resolver already streamed and hashed its bounded archive;
        # stage rechecks bytes before unpacking. This recipe pins that result.
        if not archive.is_file() or source.get('strip_components') != 1:
            raise InventoryError('source_unavailable', 'resolved official archive unavailable')
        name = 'auto-'+version+'-'+commit[:12]
        recipe.update(id=name,upstream_version=version,revision='upstream-'+commit,source=source)
        directory = self.store/'recipes';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        destination = directory/(name+'.json')
        payload = (json.dumps(recipe,indent=2)+'\n').encode()
        pin = hashlib.sha256(payload).hexdigest()
        if destination.exists():
            if destination.read_bytes() != payload:
                raise InventoryError('release_recipe_unavailable','generated recipe identity already has different content')
        else:
            # Atomic state publication; job start rechecks pin under its lock.
            _atomic(destination,recipe)
            pin = hashlib.sha256(destination.read_bytes()).hexdigest()
        return name,destination,pin

    def poll(self, actor, *, authorize=None):
        config, interval = self.configuration()
        args = dict(expected_target=config['target'])
        self.jobs.guard(actor, config['target'], args, authorize, write=True)
        with self.locked():
            state = self.load()
            snapshot = self.jobs.execute(actor, 'upgrades.status', args, authorize=authorize)['result']
            if not snapshot['enabled']:
                state.update(status='disabled', reason='upgrade_disabled')
                return self.save(state)
            try:
                now = self.now()
            except measurements.TimeUnavailable as error:
                state.update(status='held', reason=str(error))
                return self.save(state)
            if not isinstance(now, (int,float)) or not math.isfinite(now):
                raise InventoryError('clock_uncertain', 'finite discovery clock required')
            if state['last_poll'] is not None and now < state['last_poll']:
                state.update(status='held', reason='clock_uncertain')
                return self.save(state)
            if now < state['next_due']:
                return state
            state.update(last_poll=now, next_due=now+interval, reason=None)
            try:
                metadata = self.fetch()
                version = self.validate_release(metadata)
                previous = state['latest_version']
                if previous and version_key(version) < version_key(previous):
                    raise InventoryError('release_unavailable', 'upstream metadata moved backwards')
                state.update(latest_version=version, release_url=metadata['release_url'],
                    origin=metadata['origin'], lag=metadata.get('lag', {}),
                    lag_status='observed' if metadata.get('lag') else 'selected_version_unverified')
                state['releases'].setdefault(version, dict(first_seen=now, status='observed'))
                jobs = self.jobs.execute(actor, 'upgrades.list', args, authorize=authorize)['result']['jobs']
                active = [j for j in jobs if j['state'] not in TERMINAL]
                if active:
                    state.update(status='waiting', reason='current_candidate_active', job_id=active[0]['id'])
                    state['releases'][version].update(status='pending')
                    return self.save(state)
                # Never request a fresh job for the same discovered release,
                # even if its host recipe changed after a failed attempt.
                known = [j for j in jobs if j.get('version') == version]
                if known:
                    job = max(known, key=lambda j:j['created_at'])
                    state.update(status='settled', reason=job.get('reason'), job_id=job['id'])
                    state['releases'][version].update(status=job['state'], job_id=job['id'])
                    return self.save(state)
                name, pin = self.recipe_for(config, version)
                for old, observed in state['releases'].items():
                    if old != version and observed['status'] in ('observed','pending'):
                        observed.update(status='superseded', superseded_by=version)
                        if old not in state['skipped']:state['skipped'].append(old)
                started = self.jobs.execute(actor, 'upgrades.start', dict(args,recipe=name,expected_recipe_sha256=pin,upstream_version=version), authorize=authorize)['result']['job']
                state['releases'][version].update(status='dispatched', job_id=started['id'], recipe_sha256=pin)
                state.update(status='dispatched', job_id=started['id'])
            except (InventoryError, OSError, ValueError, KeyError) as error:
                state.update(status='held', reason=getattr(error,'code','release_unavailable'), detail=str(error))
            return self.save(state)

    def tick(self, actor, *, authorize=None):
        """Poll when due and drive at most one currently accepted job stage."""
        discovery = self.poll(actor, authorize=authorize)
        config, _ = self.configuration()
        args = dict(expected_target=config['target'])
        current = self.jobs.execute(actor, 'upgrades.status', args, authorize=authorize)['result']
        if not current['enabled']:
            return dict(discovery=discovery, job=None)
        jobs = self.jobs.execute(actor, 'upgrades.list', args, authorize=authorize)['result']['jobs']
        active = [job for job in jobs if job['state'] not in TERMINAL]
        if not active:
            return dict(discovery=discovery, job=None)
        # A concurrent owner may still hold this worker. The public job owner
        # decides whether to advance, reconcile, or report busy; never resubmit.
        try:
            result = self.jobs.execute(actor, 'upgrades.advance', dict(args,job_id=active[0]['id']), authorize=authorize)
            return dict(discovery=discovery, job=result['result']['job'])
        except InventoryError as error:
            return dict(discovery=discovery, job=active[0], drive=dict(status='held',reason=error.code))


def main(argv=None):
    """Installed systemd/cron entrypoint; installation never enables the bot."""
    import argparse
    import json
    from .operation_commands import local_actor
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--once',action='store_true',help='one bounded poll/advance pass for a service timer')
    options = parser.parse_args(argv)
    owner = UpgradeDiscovery(options.root)
    def authorize():
        return local_actor(options.root)
    while True:
        try:
            result = owner.tick(authorize(),authorize=authorize)
        except (InventoryError,OSError,ValueError,KeyError) as error:
            print(json.dumps(dict(status='held',reason=getattr(error,'code','discovery_unavailable'),detail=str(error))),flush=True)
            return 2
        print(json.dumps(result,sort_keys=True),flush=True)
        if options.once:return 0
        # Timer loop has bounded idle waits; work deadlines are owned by jobs.
        time.sleep(5)


if __name__ == '__main__':
    raise SystemExit(main())
