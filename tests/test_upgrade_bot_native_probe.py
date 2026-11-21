"""Acceptance probes must reject older-package and failed journey evidence."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('upgrade_native_probe',Path(__file__).parents[1]/'scripts/upgrade_bot_native_probe.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class NativeAcceptanceProbeTests(unittest.TestCase):
    def test_older_package_receipt_cannot_qualify_new_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';scripts=source/'scripts';scripts.mkdir(parents=True)
            package=root/'package';(package/'bin').mkdir(parents=True);(package/'bin/codex').write_bytes(b'new exact candidate')
            prefix=root/'prefix';(prefix/'bin').mkdir(parents=True);(prefix/'bin/python').symlink_to(sys.executable)
            program=scripts/'upgrade_native_capability_probe.py'
            program.write_text("import json,sys;from pathlib import Path;p=Path(sys.argv[sys.argv.index('--artifacts')+1]);p.mkdir(parents=True);(p/'receipt.json').write_text(json.dumps(dict(status='passed',native_sha256='older-package',model_requests=0,external_provider_requests=0,checks={'durable_notices':True},scripted_provider_requests=1)))\n")
            args=['probe','--source',str(source),'--prefix',str(prefix),'--models',str(root/'models.json'),'--artifacts',str(root/'artifacts'),'--baseline',str(root/'baseline'),'--history-probe',str(root/'history.py')]
            out=io.StringIO()
            with patch.dict(os.environ,{'CODEX_UPGRADE_PACKAGE':str(package)}),patch.object(sys,'argv',args),contextlib.redirect_stdout(out):
                code=module.main()
            report=json.loads(out.getvalue())
            self.assertEqual(code,1)
            self.assertEqual(report['status'],'failed')
            self.assertEqual(report['checks'],{})
            self.assertEqual(report['scripted_provider_requests'],0)
            self.assertTrue((Path(report['artifacts'])/'receipt.json').is_file())
