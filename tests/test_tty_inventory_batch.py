"""Batch native-client discovery preserves unique and ambiguous TTY outcomes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from codex_wake import records

class TtyInventoryBatchTests(unittest.TestCase):
 def test_batch_preserves_birth_identity_and_refuses_ambiguous_tty(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   for pid,tty,command in [(101,'/dev/pts/1','codex'),(202,'/dev/pts/2','codex'),(303,'/dev/pts/2','codex'),(404,'/dev/pts/1','bash')]:
    proc=root/str(pid);(proc/'fd').mkdir(parents=True)
    (proc/'fd/0').symlink_to(tty);(proc/'comm').write_text(command)
    (proc/'stat').write_text(' '.join([str(pid)]*21+[str(pid*10)]))
   real_path=Path
   with patch('codex_wake.records.Path',side_effect=lambda value:root if str(value)=='/proc' else real_path(value)):
    self.assertEqual(records.codex_client_identities_for_ttys(['/dev/pts/1','/dev/pts/2','/dev/pts/3']),{'/dev/pts/1':(101,1010)})
    self.assertEqual(records.codex_client_identity_for_tty('/dev/pts/1'),(101,1010))
    with self.assertRaisesRegex(records.WakeError,'found 2'):records.codex_client_identity_for_tty('/dev/pts/2')
