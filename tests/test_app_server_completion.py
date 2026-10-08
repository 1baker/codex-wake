from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_wake.app_server import StdioAppServerClient, dispatch_app_server_record, require_unowned_stdio
from codex_wake.records import WakeError, WakePath, build_record, find_record, write_record


class CompletionTests(unittest.TestCase):
    def test_request_really_times_out_and_closes_child(self):
        client = StdioAppServerClient(command=[sys.executable, "-u", "-c", "import time; time.sleep(5)"], timeout_seconds=0.05)
        start = time.monotonic()
        try:
            with self.assertRaises(WakeError): client.initialize()
        finally: client.close()
        self.assertLess(time.monotonic() - start, 1)
        self.assertIsNotNone(client.process.poll())

    def test_matching_completion_before_rpc_response_is_retained(self):
        script = """import json,sys
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({'method':'turn/completed','params':{'threadId':'t','turn':{'id':'other','status':'completed'}}}),flush=True)
 print(json.dumps({'method':'turn/completed','params':{'threadId':'t','turn':{'id':'wanted','status':'completed'}}}),flush=True)
 print(json.dumps({'id':r['id'],'result':{'ok':True}}),flush=True)
"""
        client = StdioAppServerClient(command=[sys.executable, "-u", "-c", script], timeout_seconds=1)
        try:
            client.initialize()
            result = client.wait_for_turn("t", "wanted", timeout_seconds=1)
            self.assertEqual(result["status"], "completed")
        finally: client.close()

    def test_read_only_writer_lock_probe_refuses_live_writer_without_unlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); locks = home / "thread-writer-locks"; locks.mkdir()
            path = locks / "test_thread.lock"; path.touch()
            with path.open("r") as held:
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(WakeError): require_unowned_stdio("test_thread", codex_home=home)
            self.assertTrue(path.exists())
            require_unowned_stdio("test_thread", codex_home=home)
            require_unowned_stdio("absent", codex_home=home)
            self.assertFalse((locks / "absent.lock").exists())

    def dispatch(self, root, client):
        r = build_record(predicate={"type":"not_before","due_at":"2026-10-05T04:00:00Z"},
            prompt="saved unique task", cwd=root,
            target={"transport":"app-server","endpoint":"stdio://","thread_id":"t","inline_payload":True})
        r["id"] = "wake_lifetime"; r["status"] = "firing"
        write_record(root,r)
        with patch("codex_wake.app_server.require_unowned_stdio"), patch("codex_wake.app_server.StdioAppServerClient", return_value=client):
            result = dispatch_app_server_record(root, find_record(root, r["id"]))
        return result, find_record(root, r["id"]).record

    def test_owned_client_waits_before_close_and_passes_actual_payload(self):
        class Client:
            def __init__(self): self.calls=[]
            def initialize(self): return {}
            def resume_thread(self,*args,**kwargs): return {"thread":{"id":"t","status":{"type":"idle"}}}
            def start_turn(self,thread,prompt,**kwargs):
                self.calls.append("start"); self.prompt=prompt
                return {"turn":{"id":"turn"}}
            def wait_for_turn(self,*args,**kwargs): self.calls.append("complete"); return {"id":"turn","status":"completed"}
            def close(self): self.calls.append("close")
        with tempfile.TemporaryDirectory() as tmp:
            client=Client(); result,r=self.dispatch(Path(tmp),client)
            self.assertEqual(client.calls,["start","complete","close"])
            self.assertIn("saved unique task",client.prompt)
            self.assertEqual(result.status,"submitted")
            self.assertEqual(r["delivery"]["state"],"completed")

    def test_eof_or_timeout_after_start_is_uncertain_not_retryable(self):
        class Client:
            def initialize(self): return {}
            def resume_thread(self,*args,**kwargs): return {"thread":{"id":"t","status":{"type":"idle"}}}
            def start_turn(self,*args,**kwargs): return {"turn":{"id":"turn"}}
            def wait_for_turn(self,*args,**kwargs): raise WakeError("completion timeout")
            def close(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            result,r=self.dispatch(Path(tmp),Client())
            self.assertEqual(result.status,"failed")
            self.assertEqual(r["delivery"]["state"],"uncertain")
            self.assertEqual(r["dispatch_result"]["turn_id"],"turn")

    def test_recovered_sending_never_creates_a_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            r=build_record(predicate={"type":"not_before"},prompt="task",cwd=root,
                target={"transport":"app-server","endpoint":"stdio://","thread_id":"t"})
            r["id"]="wake_recover"; r["status"]="firing"; r["delivery"]={"state":"sending"}; write_record(root,r)
            with patch("codex_wake.app_server.StdioAppServerClient") as create:
                result=dispatch_app_server_record(root,find_record(root,r["id"]))
                create.assert_not_called()
            self.assertEqual(result.status,"failed")
            self.assertEqual(find_record(root,r["id"]).record["delivery"]["state"],"uncertain")


if __name__ == "__main__": unittest.main()
