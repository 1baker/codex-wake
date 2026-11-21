"""Owned child defaults must satisfy real Unix socket ownership checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_upgrade_qualification as fixtures

PRIVATE_SOCKET_CHECK="""import os,socket,stat,tempfile,pathlib
with tempfile.TemporaryDirectory(prefix='private-native-') as directory:
 path=pathlib.Path(directory)/'native.sock'
 with socket.socket(socket.AF_UNIX) as connection:
  connection.bind(str(path))
  assert stat.S_IMODE(path.stat().st_mode)==0o700, 'native socket must be owner-private'
 file=pathlib.Path(directory)/'native.state';file.write_text('state')
 assert stat.S_IMODE(file.stat().st_mode)==0o600, 'native state must be owner-private'
"""


class UpgradePrivatePermissionsTests(unittest.TestCase):
    def test_stage_worker_restricts_real_native_socket_and_state_under_inherited_022(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=fixtures.QualificationTests().fixture(directory)
            recipe=root/'recipe.json'
            recipe.write_text(json.dumps(dict(schema_version=1,id='private',channel='stock',upstream_version='0.166.0',revision='fixture',package='.',
                source=dict(official_url='https://github.com/openai/codex/releases/download/fixture/source.tar',tree=str(package),files={name:row['sha256'] for name,row in job['results']['stage']['files'].items()}),
                qualify=[[sys.executable,'-c',PRIVATE_SOCKET_CHECK+"\nimport json;print(json.dumps(dict(schema_version=1,checks={'official_cli':True})))"]],read_schemas=[1],write_schema=1)))
            result=root/'result.json'
            process=subprocess.run([sys.executable,'-m','codex_wake.upgrade_stage_worker',str(root/'stage-store'),str(recipe),str(result)],
                env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')),umask=0o022,capture_output=True,text=True,timeout=20)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertEqual(json.loads(result.read_text())['status'],'staged',result.read_text())

    def test_qualification_native_and_probe_children_restrict_socket_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root,package,job,config=fixtures.QualificationTests().fixture(directory)
            native=package/'bin/codex';body=native.read_text();lines=body.splitlines(keepends=True)
            native.write_text(lines[0]+PRIVATE_SOCKET_CHECK+''.join(lines[1:]))
            digest=hashlib.sha256(native.read_bytes()).hexdigest()
            job['results']['stage']['files']['bin/codex']['sha256']=digest
            job['results']['stage']['build']['sha256']=digest
            probe=root/'probe.py';probe.write_text(PRIVATE_SOCKET_CHECK+probe.read_text())
            config['test_files'][str(probe)]=hashlib.sha256(probe.read_bytes()).hexdigest()
            payload=root/'qualification-input.json';payload.write_text(json.dumps(dict(job=job,config=config)))
            runner="import json,sys;from pathlib import Path;from codex_wake.upgrade_qualification import UpgradeQualification;p=json.loads(Path(sys.argv[1]).read_text());r=UpgradeQualification(sys.argv[2]).run(p['job'],p['config']);print(json.dumps(r))"
            process=subprocess.run([sys.executable,'-c',runner,str(payload),str(root)],env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')),umask=0o022,capture_output=True,text=True,timeout=20)
            self.assertEqual(process.returncode,0,process.stderr)
            result=json.loads(process.stdout)
            self.assertEqual(result['status'],'fixture_verified',result)
