"""Public input admission fences a changed active turn before steering."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from codex_wake.unified_session_input import SessionInputs


class ConnectorBusyPolicyTests(unittest.TestCase):
    def test_changed_active_turn_refuses_steer_without_prompt_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            target=dict(host='h',environment='e',uid=os.getuid(),home=directory,conversation_id='thread')
            row=dict(thread_id='thread',target=target,endpoint='unix:///owned',codex_cmd=['codex'])
            reads=0
            calls=[]
            def native(row,method,arguments):
                nonlocal reads
                calls.append(method)
                self.assertEqual(method,'thread/read','changed turn must send no native input')
                reads+=1
                return dict(thread=dict(id='thread',status=dict(type='active'),turns=[dict(id='original' if reads==1 else 'replacement',status='inProgress',items=[])]))
            with patch('codex_wake.unified_session_input.resolve',return_value=row):
                result=SessionInputs(Path(directory),request=native).submit('thread:thread','New detail','steer','one')['result']['operation']
            self.assertEqual(result['execution'],'unknown')
            self.assertEqual(result['reason'],'stale_target')
            self.assertEqual(calls,['thread/read','thread/read'])
