"""Echter Linux-PTY-Funktionstest: SGR-Mausbytes erreichen den Kindprozess.

Kein Qt und keine neuen Laufzeitpakete erforderlich. Unter anderen Systemen
werden diese spezifisch Linux-bezogenen PTY-Tests uebersprungen.
"""
import os
import shlex
import sys
import time
import unittest

from shelldeck_mouse_protocol import encode_sgr_mouse
from test_shelldeck_pty_lifecycle import extract_class


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux-PTY benoetigt")
class MousePtyFunctionalTests(unittest.TestCase):
    def test_raw_mouse_report_arrives_unchanged_at_real_pty(self):
        child_class = extract_class("PosixPtyChild", {"os": os, "shlex": shlex})
        payload = encode_sgr_mouse("press", 5, 11)
        script = (
            "import os,tty; "
            "tty.setraw(0); "
            "os.write(1,b'READY\\\\n'); "
            f"n={len(payload)}; buf=b''; "
            "exec('while len(buf)<n: buf+=os.read(0,n-len(buf))'); "
            "os.write(1,b'RECEIVED='+buf.hex().encode()+b'\\\\n')"
        )
        child = child_class.spawn(shlex.join([sys.executable, "-c", script]))
        try:
            deadline = time.monotonic() + 5
            received = bytearray()
            while time.monotonic() < deadline and b"READY" not in received:
                try:
                    received.extend(child.read(4096))
                except EOFError:
                    break
            self.assertIn(b"READY", received)
            self.assertEqual(os.write(child.fd, payload), len(payload))
            while time.monotonic() < deadline and b"RECEIVED=" not in received:
                try:
                    received.extend(child.read(4096))
                except EOFError:
                    break
            self.assertIn(b"RECEIVED=" + payload.hex().encode(), received)
            self.assertTrue(child.wait_for_exit(1))
            self.assertEqual(child.exitstatus, 0)
        finally:
            if child.isalive():
                child.kill()
                child.wait_for_exit(1)
            child.close()
