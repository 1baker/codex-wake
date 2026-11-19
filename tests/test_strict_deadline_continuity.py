"""Original deadline continuity at the guard configuration/executable seam.

No provider calls, host suspend/reboot, systemd effects, or native Codex work.
The BOOTTIME jump test is deterministic clock injection, not a suspend trial.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from codex_wake.process import boot_id_value
from codex_wake.strict_executor import Guard


class StrictDeadlineContinuityTests(unittest.TestCase):
    def configuration(self, root, *, started_boottime):
        return dict(wake_root=str(root), objective_id='deadline-continuity',
            endpoint='unix://' + str(root/'unused.sock'), codex_home=str(root/'codex-home'),
            argv=[sys.executable, '-c',
                'from pathlib import Path; Path("child-effect").write_text("executed")'],
            cwd=str(root), started_upper=1000, started_boottime=started_boottime,
            boot_id=boot_id_value(), deadline=1010,
            generation='original-generation',status_path=str(root/'status.json'),
            configuration=dict(revision=1,strict_execution=dict(poll_seconds=.05,
                accounting_max_age_seconds=5,stop_grace_seconds=1,checkpoint_grace_seconds=1)))

    def invoke(self, source):
        environment=dict(os.environ)
        environment.pop('INVOCATION_ID',None)
        result=subprocess.run([sys.executable,'-m','codex_wake.strict_executor',str(source)],
            capture_output=True,text=True,timeout=3,env=environment)
        self.assertEqual(result.returncode,5,result.stderr)
        return json.loads((source.parent/'status.json').read_text())

    def test_two_guard_processes_hold_legacy_clock_without_reanchoring_or_child_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            configuration=self.configuration(root,started_boottime=10)
            source=root/'admission.json';source.write_text(json.dumps(configuration))
            original=hashlib.sha256(source.read_bytes()).hexdigest()
            statuses=[self.invoke(source),self.invoke(source)]
            for status in statuses:
                self.assertEqual(status['reason'],'clock_unqualified')
                self.assertEqual(status['state'],'stopped')
                self.assertEqual(status['generation'],'original-generation')
                self.assertIsNone(status['child_pid'])
            self.assertNotEqual(statuses[0]['pid'],statuses[1]['pid'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
            self.assertFalse((root/'child-effect').exists())

    def test_injected_boottime_jump_counts_elapsed_before_child_or_accounting(self):
        # Numeric legacy fixture inputs preserve the explicit injection seam;
        # they do not qualify a host clock or claim a real suspend trial.
        clock=10  # Explicit deterministic legacy fixture coordinate.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            configuration=self.configuration(root,started_boottime=clock)
            first=Guard(configuration)
            self.assertEqual(first.check(boottime=clock+2),'controller_unavailable')
            self.assertEqual(first.check(boottime=clock+100),'deadline_reached')
            reconstructed=Guard(json.loads(json.dumps(configuration)))
            self.assertEqual(reconstructed.check(boottime=clock+100),'deadline_reached')
            self.assertFalse((root/'child-effect').exists())

    def test_changed_boot_identity_fences_executable_before_child_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            configuration=self.configuration(root,started_boottime=10)
            configuration['boot_id']='previous-boot-disposable-fixture'
            source=root/'admission.json';source.write_text(json.dumps(configuration))
            status=self.invoke(source)
            self.assertEqual(status['reason'],'boot_identity_changed')
            self.assertIsNone(status['child_pid'])
            self.assertFalse((root/'child-effect').exists())
