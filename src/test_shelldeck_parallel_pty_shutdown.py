"""Echter Linux-PTY-Regressionstest: eine Sitzungsbeendigung darf
niemals die andere PTY-Sitzung treffen. Kein Qt fuer diesen Test noetig.
"""
import os
import shlex
import sys
import time
import unittest

from test_shelldeck_pty_lifecycle import extract_class


@unittest.skipUnless(sys.platform.startswith("linux"), "Zwei POSIX-PTYs unter Linux")
class ParallelPtyShutdownTests(unittest.TestCase):
    def test_stopping_one_session_keeps_other_interactive(self):
        child_type = extract_class("PosixPtyChild", {"os": os, "shlex": shlex})
        script = ("import sys; "
                  "print('READY', flush=True); "
                  "line = sys.stdin.readline().strip(); "
                  "print('ANSWER=' + line, flush=True)")
        command = shlex.join([sys.executable, "-u", "-c", script])
        left = child_type.spawn(command)
        right = None

        def read_until(child, target, timeout=4.0):
            chunks = []
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data = child.read(4096)
                except EOFError:
                    break
                if data:
                    chunks.append(data)
                    if target in b"".join(chunks):
                        return b"".join(chunks)
                if not child.isalive():
                    continue  # eventuell liegen noch letzte Ausgabebytes vor
            self.fail(f"PTY-Ausgabe {target!r} fehlt: {b''.join(chunks)!r}")

        try:
            right = child_type.spawn(command)
            self.assertIn(b"READY", read_until(left, b"READY"))
            self.assertIn(b"READY", read_until(right, b"READY"))
            self.assertTrue(left.isalive())
            self.assertTrue(right.isalive())

            left.terminate()
            self.assertTrue(left.wait_for_exit(3.0), "linker PTY blieb nach SIGTERM aktiv")
            self.assertFalse(left.isalive())
            left.close()

            # Rechts muss danach weiterhin Eingabe und Ausgabe funktionieren.
            self.assertTrue(right.isalive(), "anderes PTY wurde mit beendet")
            right.write("RECHTS_OK\r")
            self.assertIn(b"ANSWER=RECHTS_OK", read_until(right, b"ANSWER=RECHTS_OK"))
            self.assertTrue(right.wait_for_exit(3.0))
            self.assertEqual(right.exitstatus, 0)
        finally:
            for child in (left, right):
                if child is None:
                    continue
                try:
                    if child.isalive():
                        child.kill()
                        child.wait_for_exit(2.0)
                finally:
                    child.close()


if __name__ == "__main__":
    unittest.main()
