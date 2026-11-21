"""Command/identity contract tests, using a fixture native CLI, not model quality."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from codex_wake.upgrade_codex_worker import run


class CodexUpgradeWorkerTests(unittest.TestCase):
    def fixture(self,root,role='worker'):
        workspace=root/'workspace';workspace.mkdir()
        (workspace/'feature.rs').write_text('feature\n')
        accounts=root/'test-accounts';accounts.mkdir(mode=0o700)
        home=accounts/role;home.mkdir(mode=0o700)
        native=root/'codex-fixture'
        native.write_text("""#!/usr/bin/python3
import json,os,pathlib,sys
args=sys.argv[1:]
schema=json.loads(pathlib.Path(args[args.index('--output-schema')+1]).read_text())
props=schema['properties']
report={'schema_version':1,'status':'approved' if 'reviewer' in props else 'repaired','candidate_digest':props['candidate_digest'].get('const','0'*64),'tests_digest':props['tests_digest'].get('const','0'*64),'capabilities':{key:'fixture evidence; not real model acceptance' for key in props['capabilities']['properties']},'retirements':{key:'' for key in props['retirements']['properties']}}
if 'reviewer' in props:
 report['reviewer']=props['reviewer']['const']
 report['findings']=[]
 if 'patch_dispositions' in props:
  report['patch_dispositions']={key:dict(disposition='rewritten',intent=value['properties']['intent']['const'],evidence='fixture independent source evidence',equivalence='') for key,value in props['patch_dispositions']['properties'].items()}
else:
 report['identity']=props['identity']['const']
 report['patch_dispositions']={key:dict(disposition='rewritten',evidence='fixture source repair') for key in props['patch_dispositions']['properties']}
pathlib.Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(report))
record=dict(argv=args,env={key:os.environ.get(key) for key in ('CODEX_HOME','HOME','OPENAI_API_KEY','CODEX_THREAD_ID')},prompt=sys.stdin.read())
pathlib.Path(os.environ['CODEX_HOME']).joinpath('fixture-invocation.json').write_text(json.dumps(record))
""")
        native.chmod(0o700)
        config=root/(role+'.json')
        config.write_text(json.dumps(dict(schema_version=1,role=role,identity='test-'+role,test_root=str(accounts),codex_home=str(home),executable=str(native),sha256=hashlib.sha256(native.read_bytes()).hexdigest(),timeout_seconds=5)))
        config.chmod(0o600)
        from codex_wake.upgrade_repair import _inventory,_identities
        candidate,tests=_identities(_inventory(workspace))
        packet=root/'packet.json';packet.write_text(json.dumps(dict(schema_version=1,role=role,job_id='job',workspace=str(workspace),candidate_digest=candidate,tests_digest=tests,required_capabilities=['tui_health'],patches=[dict(id='health',path='/fixture/health.patch',sha256='a'*64,intent='Preserve main-loop nonce health')],patch_provenance=[],prior_findings=[])))
        return config,packet,root/'response.json',home,workspace

    def test_worker_uses_pinned_native_dedicated_account_and_ephemeral_workspace_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config,packet,response,home,workspace=self.fixture(root)
            from unittest.mock import patch
            with patch.dict(os.environ,{'CODEX_HOME':str(root/'ambient-codex'),'OPENAI_API_KEY':'synthetic-key','CODEX_THREAD_ID':'unrelated-thread'}):
                result=run(config,'worker',packet,response)
            self.assertEqual(result['status'],'repaired',result)
            saved=json.loads(response.read_text());self.assertEqual(saved['identity'],'test-worker')
            invocation=json.loads((home/'fixture-invocation.json').read_text())
            args=invocation['argv']
            for option in ('--no-daemon','exec','--ephemeral','--ignore-user-config','--json','--output-schema'):
                self.assertIn(option,args)
            self.assertEqual(args[args.index('--sandbox')+1],'workspace-write')
            self.assertEqual(args[args.index('--cd')+1],str(workspace))
            self.assertEqual(invocation['env']['CODEX_HOME'],str(home))
            self.assertNotEqual(invocation['env']['HOME'],str(home.parent))
            self.assertIsNone(invocation['env']['OPENAI_API_KEY'])
            self.assertIsNone(invocation['env']['CODEX_THREAD_ID'])
            self.assertIn('Preserve main-loop nonce health',invocation['prompt'])

    def test_reviewer_has_an_independent_read_only_context_and_exact_content_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config,packet,response,home,workspace=self.fixture(root,'reviewer')
            result=run(config,'reviewer',packet,response)
            self.assertEqual(result['status'],'approved')
            self.assertEqual(result['reviewer'],'test-reviewer')
            self.assertEqual(result['candidate_digest'],json.loads(packet.read_text())['candidate_digest'])
            invocation=json.loads((home/'fixture-invocation.json').read_text())
            self.assertEqual(invocation['argv'][invocation['argv'].index('--sandbox')+1],'read-only')
            self.assertIn('independent read-only source reviewer',invocation['prompt'])
            self.assertIn('Do not trust worker assertions as proof',invocation['prompt'])
            self.assertTrue(result['adapter_provenance']['ephemeral'])

    def test_full_patch_review_does_not_invent_an_interrupted_worker(self):
        for interrupted in (False,True):
            with self.subTest(interrupted=interrupted), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);config,packet,response,home,workspace=self.fixture(root,'reviewer')
                declaration=json.loads(packet.read_text());declaration['require_patch_dispositions']=True
                if interrupted:declaration['interrupted_worker']={'kind':'interrupted_worker_no_completion_report','worker_completed':False}
                packet.write_text(json.dumps(declaration))
                result=run(config,'reviewer',packet,response)
                self.assertEqual(result['patch_dispositions']['health']['disposition'],'rewritten')
                prompt=json.loads((home/'fixture-invocation.json').read_text())['prompt']
                self.assertIn('Independently disposition EVERY original patch',prompt)
                self.assertEqual('original worker was interrupted' in prompt,interrupted)

    def test_mismatched_executable_or_outside_account_never_reaches_native_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config,packet,response,home,workspace=self.fixture(root)
            declaration=json.loads(config.read_text())
            declaration['sha256']='a'*64;config.write_text(json.dumps(declaration))
            with self.assertRaisesRegex(ValueError,'registered build bytes changed'):
                run(config,'worker',packet,response)
            self.assertFalse((home/'fixture-invocation.json').exists())
            declaration['sha256']=hashlib.sha256(Path(declaration['executable']).read_bytes()).hexdigest()
            outside=root/'outside';outside.mkdir()
            declaration['codex_home']=str(outside);config.write_text(json.dumps(declaration))
            with self.assertRaisesRegex(ValueError,'strictly inside'):
                run(config,'worker',packet,response)
            self.assertFalse((outside/'fixture-invocation.json').exists())
            self.assertFalse(response.exists())

    def test_native_capacity_error_emits_constant_nonretryable_protocol_without_log_content(self):
        import contextlib
        import io
        from unittest.mock import patch
        from codex_wake.upgrade_codex_worker import main
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config,packet,response,home,workspace=self.fixture(root)
            declaration=json.loads(config.read_text());native=Path(declaration['executable'])
            native.write_text(native.read_text()+"\nprint(json.dumps({'type':'error','error':{'code':'usage_limit_reached','message':'private diagnostic'}}));sys.exit(2)\n")
            declaration['sha256']=hashlib.sha256(native.read_bytes()).hexdigest();config.write_text(json.dumps(declaration))
            output=io.StringIO()
            with patch.dict(os.environ,{'CODEX_UPGRADE_PACKET':str(packet),'CODEX_UPGRADE_RESPONSE':str(response)}),contextlib.redirect_stderr(output):
                code=main(['--config',str(config),'--role','worker'])
            self.assertEqual(code,2)
            self.assertEqual(json.loads(output.getvalue()),dict(schema_version=1,status='held',reason='coding_capacity_unavailable',retryable=False))
            self.assertFalse(response.exists())
