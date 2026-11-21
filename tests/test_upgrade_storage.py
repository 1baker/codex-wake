"""Owned storage budgets tolerate deletion races, not inaccessible evidence."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.upgrade_storage import owned_storage_bytes


class UpgradeStorageTests(unittest.TestCase):
    def test_vanished_compiler_temp_file_is_skipped_without_double_counting_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'nested').mkdir();(root/'nested/keep').write_bytes(b'abc')
            vanishes=root/'nested/vanishes';vanishes.write_bytes(b'12345')
            original=os.scandir
            class Entry:
                def __init__(self,entry):self.entry=entry;self.path=entry.path
                def stat(self,**kwargs):
                    if self.entry.name=='vanishes':Path(self.path).unlink(missing_ok=True)
                    return self.entry.stat(**kwargs)
            class Scan:
                def __init__(self,path):self.path=path
                def __enter__(self):
                    with original(self.path) as entries:return iter([Entry(e) for e in entries])
                def __exit__(self,*args):pass
            with patch('os.scandir',side_effect=Scan):
                self.assertEqual(owned_storage_bytes([root,root/'nested']),3)
            with patch('os.scandir',side_effect=PermissionError('denied')):
                with self.assertRaises(PermissionError):owned_storage_bytes([root])
