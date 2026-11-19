"""Protective SSH frame waits do not require a reliable clock; private pipes only."""
import os
import unittest
from unittest.mock import patch

from codex_wake import measurements
from codex_wake.host_commands import bounded_stdin
from codex_wake.managed_inventory import InventoryError


class HostInputTests(unittest.TestCase):
    def test_available_frame_is_read_when_reliable_time_is_unavailable(self):
        reader, writer = os.pipe()
        os.write(writer, b'{"operation":"hosts.list"}')
        os.close(writer)
        with os.fdopen(reader, 'r') as stream, patch('sys.stdin', stream), patch(
                'codex_wake.measurements.snapshot', side_effect=measurements.TimeUnavailable('client unavailable')):
            self.assertEqual(bounded_stdin(), {'operation': 'hosts.list'})

    def test_frame_cannot_outlive_its_original_protective_wait(self):
        reader, writer = os.pipe()
        os.write(writer, b'{"operation":"hosts.list"}')
        os.close(writer)
        finished = False
        read = os.read
        def receive(fd, count):
            nonlocal finished
            chunk = read(fd, count)
            if not chunk:
                finished = True
            return chunk
        with os.fdopen(reader, 'r') as stream, patch('sys.stdin', stream), patch(
                'time.monotonic', side_effect=lambda: 7 if finished else 1), patch('os.read', side_effect=receive):
            with self.assertRaises(InventoryError):
                bounded_stdin()
