"""Counter bridge seam: fresh correlated reads and bounded owned lifetime."""
import json
import multiprocessing
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_wake.host_counter import read_counter, serve_counter
from codex_wake import measurements


def fake_bridge(directory):
    script = "import os,sys\nif os.stat(os.getcwd()).st_mode & 5 != 5: raise SystemExit(7)\nn=100\nfor line in sys.stdin:\n n+=1\n print(line.strip()+','+str(n)+',10000000',flush=True)\n"
    os.chdir(directory)  # Windows interop cannot use this other user's private cwd.
    serve_counter(Path(directory), command=[sys.executable, '-u', '-c', script], idle_seconds=.5)


class HostCounterTests(unittest.TestCase):
    def test_missing_kernel_fuse_holds_before_creating_bridge_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'uncreated'
            with patch('ctypes.CDLL',side_effect=OSError('timerfd unavailable')):
                with self.assertRaisesRegex(ValueError,'counter_transport_fuse_unavailable'):
                    read_counter(root,start=False)
                with self.assertRaisesRegex(ValueError,'counter_transport_fuse_unavailable'):
                    serve_counter(root,command=['must-not-start'])
            self.assertFalse(root.exists())

    def test_bound_socket_retry_does_not_restart_whole_operation_fuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'counter';root.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(root/'counter.sock'));(root/'counter.sock').chmod(0o600)
                anchor=measurements.snapshot()
                with patch('time.monotonic',side_effect=AssertionError('guest clock forbidden')):
                    with self.assertRaises(TimeoutError):read_counter(root,start=False)
                lower,upper=measurements.elapsed_bounds(anchor,measurements.snapshot())
                self.assertGreater(lower,4)
                self.assertLess(upper,6)

    def test_native_counter_read_never_queries_guest_clock(self):
        from codex_wake.measurements import deadline
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'counter';root.mkdir(mode=0o700)
            process=multiprocessing.Process(target=fake_bridge,args=(str(root),))
            process.start()
            try:
                ready=deadline(3)
                while not (root/'counter.sock').exists():
                    self.assertFalse(ready.expired(),'bridge unavailable')
                    time.sleep(.01)
                with patch('time.monotonic',side_effect=AssertionError('guest clock forbidden')):
                    self.assertEqual(read_counter(root,start=False),(101,10000000))
            finally:
                if process.is_alive():process.terminate()
                process.join(3)

    def test_slow_drip_native_frame_cannot_renew_aggregate_read_fuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'counter';root.mkdir(mode=0o700)
            script="import sys,time\nline=sys.stdin.readline().strip()+',123,10000000\\n'\nfor char in line:\n sys.stdout.write(char);sys.stdout.flush();time.sleep(.2)\n"
            process=multiprocessing.Process(target=serve_counter,args=(root,),kwargs=dict(
                command=[sys.executable,'-u','-c',script],idle_seconds=.5))
            process.start()
            try:
                ready=measurements.deadline(3)
                while not (root/'counter.sock').exists():
                    self.assertFalse(ready.expired(),'bridge unavailable')
                    time.sleep(.01)
                anchor=measurements.snapshot()
                with self.assertRaises((OSError,ValueError)):
                    read_counter(root,start=False)
                self.assertLess(measurements.elapsed_bounds(anchor,measurements.snapshot())[1],6)
                process.join(3)
                self.assertEqual(process.exitcode,0)
                self.assertFalse((root/'counter.sock').exists())
                with self.assertRaises(ValueError):read_counter(root,start=False)
            finally:
                if process.is_alive():process.terminate()
                process.join(3)

    def test_independent_clients_share_fresh_native_reads_and_bridge_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'counter'
            root.mkdir(mode=0o700)
            process = multiprocessing.Process(target=fake_bridge, args=(str(root),))
            process.start()
            try:
                deadline = measurements.deadline(3)
                while not (root/'counter.sock').exists():
                    if deadline.expired():self.fail('bridge unavailable')
                    time.sleep(.01)
                first = read_counter(root, start=False)
                second = read_counter(root, start=False)
                self.assertEqual(first, (101,10000000))
                self.assertEqual(second, (102,10000000))
                self.assertEqual((root/'counter.sock').stat().st_mode & 0o777, 0o600)
                process.join(3)
                self.assertEqual(process.exitcode,0)
                self.assertFalse((root/'counter.sock').exists())
            finally:
                if process.is_alive():process.terminate();process.join()

    def test_untrusted_directory_is_refused_without_starting_a_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'public'
            root.mkdir(mode=0o755)
            root.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'not_private'):
                read_counter(root)
            self.assertFalse((root/'counter.sock').exists())

    def test_mismatched_producer_reply_is_rejected_and_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'counter';root.mkdir(mode=0o700)
            script="import sys\nfor line in sys.stdin: print('wrong,123,10000000',flush=True)\n"
            process=multiprocessing.Process(target=serve_counter,args=(root,),kwargs=dict(command=[sys.executable,'-u','-c',script],idle_seconds=.5))
            process.start()
            try:
                deadline=measurements.deadline(3)
                while not (root/'counter.sock').exists():
                    if deadline.expired():self.fail('bridge unavailable')
                    time.sleep(.01)
                with self.assertRaises(ValueError):read_counter(root,start=False)
                process.join(3)
                self.assertEqual(process.exitcode,0)
                self.assertFalse((root/'counter.sock').exists())
            finally:
                if process.is_alive():process.terminate();process.join()

    def test_stalled_native_read_holds_and_retires_instead_of_reusing_a_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'counter';root.mkdir(mode=0o700)
            script="import sys,time\nsys.stdin.readline()\ntime.sleep(10)\nprint('late,123,10000000',flush=True)\n"
            process=multiprocessing.Process(target=serve_counter,args=(root,),kwargs=dict(command=[sys.executable,'-u','-c',script],idle_seconds=.5))
            process.start()
            try:
                deadline=measurements.deadline(3)
                while not (root/'counter.sock').exists():
                    if deadline.expired():self.fail('bridge unavailable')
                    time.sleep(.01)
                started=measurements.snapshot()
                with self.assertRaises((ValueError,OSError)):read_counter(root,start=False)
                self.assertLess(measurements.elapsed_bounds(started,measurements.snapshot())[1],6)
                process.join(3)
                self.assertEqual(process.exitcode,0)
                with self.assertRaises(ValueError):read_counter(root,start=False)
            finally:
                if process.is_alive():process.terminate();process.join()

    def test_owned_bound_socket_can_become_ready_without_starting_or_replaying_a_bridge(self):
        import threading
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'counter';root.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(root/'counter.sock'));(root/'counter.sock').chmod(0o600)
                started=threading.Event();finished=threading.Event();values=[];errors=[]
                def read():
                    started.set()
                    try:values.append(read_counter(root,start=False))
                    except Exception as exc:errors.append(type(exc).__name__)
                    finally:finished.set()
                client=threading.Thread(target=read)
                client.start()
                try:
                    self.assertTrue(started.wait(1))
                    self.assertFalse(finished.wait(.2),'owned socket is bound but not listening yet')
                    server.listen(1);server.settimeout(2)
                    with server.accept()[0] as connection:
                        request=connection.recv(100).decode().strip()
                        connection.sendall((json.dumps(dict(id=request,status='ok',counter=123,frequency=10000000))+'\n').encode())
                    self.assertTrue(finished.wait(2))
                    self.assertEqual(values,[(123,10000000)])
                    self.assertEqual(errors,[])
                finally:
                    client.join(6)
