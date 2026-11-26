"""Public release watcher behavior against real durable upgrade jobs."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from codex_wake.upgrade_discovery import UpgradeDiscovery
from codex_wake.upgrade_jobs import UpgradeJobs


from unittest.mock import patch
from test_measurements import observation


class UpgradeDiscoveryTests(unittest.TestCase):
    def fixture(self, root, clock, version='0.166.0'):
        target={'host':'fixture','namespace':'upgrade-test'}
        actor=SimpleNamespace(subject='owner',scopes={'admin','observe'},targets=[target],expires_at=10000)
        recipes={}
        for release in ('0.166.0','0.167.0','0.168.0'):
            recipe=root/(release+'.json')
            recipe.write_text(json.dumps(dict(id='release-'+release,upstream_version=release,
                source=dict(official_url='https://github.com/openai/codex/releases/download/rust-v'+release+'/source.tar.gz',sha256='a'*64))))
            recipes[release]=str(recipe)
        (root/'upgrade-bot.json').write_text(json.dumps(dict(schema_version=1,target=target,recipes=recipes,discovery=dict(interval_seconds=60))))
        release=[version]
        def fetch():
            return dict(schema_version=1,status='available',origin='https://api.github.com/repos/openai/codex/releases/latest',
                latest_version=release[0],release_url='https://github.com/openai/codex/releases/tag/rust-v'+release[0],lag={})
        jobs=UpgradeJobs(root,now=lambda:clock[0],clock=lambda:observation(int(clock[0]*1000)))
        return UpgradeDiscovery(root,now=lambda:clock[0],fetch=fetch,jobs=jobs),jobs,actor,target,release

    def test_disabled_watcher_records_state_without_dispatch_then_deduplicates_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);clock=[100.0]
            owner,jobs,actor,target,release=self.fixture(root,clock)
            first=owner.poll(actor,authorize=lambda:actor)
            self.assertEqual(first['status'],'disabled')
            self.assertIsNone(first['last_poll'])
            jobs.execute(actor,'upgrades.enable',dict(expected_target=target))
            ready=owner.poll(actor,authorize=lambda:actor)
            self.assertEqual(ready['latest_version'],'0.166.0')
            self.assertEqual(ready['status'],'dispatched')
            job_id=ready['job_id']
            clock[0]+=60
            restarted=UpgradeDiscovery(root,now=lambda:clock[0],fetch=owner.fetch,jobs=jobs)
            same=restarted.poll(actor,authorize=lambda:actor)
            self.assertEqual(same['job_id'],job_id)
            self.assertEqual(len(jobs.execute(actor,'upgrades.list',dict(expected_target=target))['result']['jobs']),1)

    def test_persistent_tick_coalesces_new_releases_and_never_renews_failed_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);clock=[100.0]
            owner,jobs,actor,target,release=self.fixture(root,clock)
            args=dict(expected_target=target)
            jobs.execute(actor,'upgrades.enable',args)
            first=owner.poll(actor,authorize=lambda:actor)
            release[0]='0.167.0';clock[0]+=60
            pending=owner.poll(actor,authorize=lambda:actor)
            self.assertEqual(pending['status'],'waiting')
            release[0]='0.168.0';clock[0]+=60
            jobs.executor=lambda job:dict(status='failed',reason='repair_attempts_exhausted')
            settled=owner.tick(actor,authorize=lambda:actor)
            self.assertEqual(settled['job']['state'],'held')
            clock[0]+=60
            successor=owner.poll(actor,authorize=lambda:actor)
            self.assertEqual(successor['status'],'dispatched')
            self.assertEqual(successor['latest_version'],'0.168.0')
            self.assertEqual(successor['skipped'],['0.167.0'])
            owner.tick(actor,authorize=lambda:actor)
            clock[0]+=60
            after=UpgradeDiscovery(root,now=lambda:clock[0],fetch=owner.fetch,jobs=jobs).tick(actor,authorize=lambda:actor)
            self.assertEqual(after['discovery']['status'],'settled')
            all_jobs=jobs.execute(actor,'upgrades.list',args)['result']['jobs']
            self.assertEqual([j['version'] for j in all_jobs],['0.166.0','0.168.0'])
            self.assertEqual(all_jobs[0]['id'],first['job_id'])
            self.assertEqual(all_jobs[0]['deadline'],7300)

    def test_cache_sweep_holds_active_output_and_reclaims_after_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owner, jobs, actor, target, _ = self.fixture(root, [100.0])
            config_path = root / 'upgrade-bot.json'
            config = json.loads(config_path.read_text())
            config['limits'] = {'temporary_bytes': 100}
            config_path.write_text(json.dumps(config))
            args = {'expected_target': target}
            jobs.execute(actor, 'upgrades.enable', args)
            job_id = owner.poll(actor)['job_id']
            cache = root / 'upgrade-compiler-cache'
            cache.mkdir()
            (cache / 'build.o').write_bytes(b'x' * 60)
            legacy_cache = jobs.store / job_id / 'cargo-target'
            legacy_cache.mkdir(parents=True)
            (legacy_cache / 'build.o').write_bytes(b'old')
            evidence = legacy_cache.parent / 'receipt.json'
            evidence.write_text('{}')
            jobs.reconcile_cache(actor, args)
            self.assertTrue(cache.is_dir())
            self.assertTrue(legacy_cache.is_dir())
            jobs.executor = lambda _: dict(status='failed', reason='compile_rejected')
            result = owner.tick(actor)
            self.assertEqual(result['job']['state'], 'held')
            self.assertEqual(result['cache_maintenance']['compiler_cache_bytes_reclaimed'], 60)
            self.assertFalse(cache.exists())
            self.assertFalse(legacy_cache.exists())
            self.assertTrue(evidence.is_file())
            idle = owner.tick(actor)
            self.assertEqual(idle['cache_maintenance']['compiler_cache_bytes_reclaimed'], 0)

    def test_idle_tick_reconciles_abandoned_shared_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owner, jobs, actor, target, _ = self.fixture(root, [100.0])
            config_path = root / 'upgrade-bot.json'
            config = json.loads(config_path.read_text())
            config['limits'] = {'temporary_bytes': 100}
            config_path.write_text(json.dumps(config))
            cache = root / 'upgrade-compiler-cache'
            cache.mkdir()
            (cache / 'abandoned.o').write_bytes(b'x' * 51)
            self.assertEqual(jobs.execute(actor, 'upgrades.status', {'expected_target': target})
                             ['result']['compiler_cache']['bytes'], 51)
            self.assertTrue(cache.is_dir())
            self.assertIsNone(owner.tick(actor)['job'])
            self.assertFalse(cache.exists())

    def test_template_source_resolution_pins_annotated_official_tag_and_archive(self):
        import hashlib
        import io
        from codex_wake.upgrade_source import OfficialSourceResolver
        class Response(io.BytesIO):
            def __init__(self, data, url):super().__init__(data);self.url=url
            def geturl(self):return self.url
        commit='b'*40;tag_object='a'*40;archive=b'owned official archive fixture'
        seen=[]
        def open_url(request,timeout):
            url=request.full_url;seen.append(url)
            if '/git/ref/' in url:data=json.dumps({'object':{'type':'tag','sha':tag_object}}).encode()
            elif '/git/tags/' in url:data=json.dumps({'object':{'type':'commit','sha':commit}}).encode()
            else:data=archive
            return Response(data,url)
        with tempfile.TemporaryDirectory() as directory:
            resolver=OfficialSourceResolver(Path(directory),open_url=open_url)
            result=resolver.resolve('0.166.0')
            self.assertEqual(result['commit'],commit)
            self.assertEqual(result['source']['official_url'],'https://github.com/openai/codex/archive/'+commit+'.tar.gz')
            self.assertEqual(result['source']['sha256'],hashlib.sha256(archive).hexdigest())
            self.assertEqual(Path(result['source']['archive_file']).read_bytes(),archive)
            self.assertEqual(result['source']['strip_components'],1)
            self.assertEqual(len(seen),3)

    def test_new_release_template_generates_pinned_recipe_without_downloading_commands(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);clock=[100.0]
            target={'host':'fixture','namespace':'upgrade-test'}
            actor=SimpleNamespace(subject='owner',scopes={'admin','observe'},targets=[target],expires_at=10000)
            template=root/'template.json'
            template.write_text(json.dumps(dict(schema_version=1,id='template',channel='modded',upstream_version='placeholder',revision='template',
                build=[['/host/trusted/build','--pinned-policy']],qualify=[['/host/trusted/qualify']],patches=[{'path':'/host/pinned.patch','sha256':'c'*64}],package='package',read_schemas=[1],write_schema=1)))
            archive=root/'official.tar.gz';archive.write_bytes(b'official source fixture')
            source=dict(official_url='https://github.com/openai/codex/archive/'+'b'*40+'.tar.gz',archive_file=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),strip_components=1)
            (root/'upgrade-bot.json').write_text(json.dumps(dict(schema_version=1,target=target,recipes={},discovery=dict(interval_seconds=60,
                recipe_template=str(template),recipe_template_sha256=hashlib.sha256(template.read_bytes()).hexdigest()))))
            metadata=dict(schema_version=1,status='available',origin='https://api.github.com/repos/openai/codex/releases/latest',latest_version='0.166.0',
                release_url='https://github.com/openai/codex/releases/tag/rust-v0.166.0',lag={})
            jobs=UpgradeJobs(root,now=lambda:clock[0],clock=lambda:observation(int(clock[0]*1000)))
            jobs.execute(actor,'upgrades.enable',dict(expected_target=target))
            owner=UpgradeDiscovery(root,now=lambda:clock[0],fetch=lambda:metadata,jobs=jobs,source_resolver=lambda version:dict(commit='b'*40,source=source))
            outcome=owner.poll(actor,authorize=lambda:actor)
            self.assertEqual(outcome['status'],'dispatched',outcome)
            job=jobs.execute(actor,'upgrades.show',dict(expected_target=target,job_id=outcome['job_id']))['result']['job']
            recipe=json.loads(Path(job['recipe_path']).read_text())
            self.assertEqual(recipe['upstream_version'],'0.166.0')
            self.assertEqual(recipe['source'],source)
            self.assertEqual(recipe['build'],[['/host/trusted/build','--pinned-policy']])
            self.assertEqual(recipe['patches'],[{'path':'/host/pinned.patch','sha256':'c'*64}])
            self.assertEqual(job['recipe_sha256'],hashlib.sha256(Path(job['recipe_path']).read_bytes()).hexdigest())

    def test_source_cache_budget_rejects_another_archive_without_removing_existing_evidence(self):
        import io
        from codex_wake.upgrade_source import OfficialSourceResolver
        from codex_wake.managed_inventory import InventoryError
        class Response(io.BytesIO):
            def __init__(self,data,url):super().__init__(data);self.url=url
            def geturl(self):return self.url
        seen=[]
        def open_url(request,timeout):
            seen.append(request.full_url)
            data=json.dumps({'object':{'type':'commit','sha':'b'*40}}).encode() if '/git/ref/' in request.full_url else b'12345'
            return Response(data,request.full_url)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);retained=root/'source-cache'/'previous'/'source.tar.gz';retained.parent.mkdir(parents=True);retained.write_bytes(b'123456')
            resolver=OfficialSourceResolver(root,open_url=open_url,maximum_bytes=8)
            with self.assertRaises(InventoryError):resolver.resolve('0.166.0')
            self.assertEqual(retained.read_bytes(),b'123456')
            self.assertFalse((root/'source-cache'/('b'*40)/'source.tar.gz').exists())

    def test_command_pass_is_idle_until_explicit_enable(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from codex_wake.upgrade_discovery import main
        import time
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target={'host':'fixture','namespace':'upgrade-test'}
            (root/'upgrade-bot.json').write_text(json.dumps(dict(schema_version=1,target=target,recipes={})))
            declaration=dict(subject='owner',client_id='client',grant_id='grant',issuer='issuer',resource='resource',scopes=['observe','admin'],targets=[target],expires_at=time.time()+100)
            messaging=root/'controller-messaging.json';messaging.write_text(json.dumps(dict(version=1,local_caller=declaration)));messaging.chmod(0o600)
            output = StringIO()
            with patch('codex_wake.measurements.utc_time', side_effect=time.time), redirect_stdout(output):
                code = main(['--root', str(root), '--once'])
            self.assertEqual(code, 0, output.getvalue())
            result = json.loads(output.getvalue())
            self.assertEqual(result['discovery']['status'], 'disabled')
            self.assertIsNone(result['job'])

    def test_malformed_official_tag_metadata_is_a_held_source_outcome(self):
        import io
        from codex_wake.upgrade_source import OfficialSourceResolver
        from codex_wake.managed_inventory import InventoryError
        class Response(io.BytesIO):
            def geturl(self):return 'https://api.github.com/repos/openai/codex/git/ref/tags/rust-v0.166.0'
        with tempfile.TemporaryDirectory() as directory:
            resolver=OfficialSourceResolver(Path(directory),open_url=lambda request,timeout:Response(b'[]'))
            with self.assertRaises(InventoryError):resolver.resolve('0.166.0')
