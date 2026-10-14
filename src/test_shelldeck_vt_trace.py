"""Regression checks for opt-in and bounded VT raw capture."""
import unittest
from shelldeck_vt_trace import VtRawTrace


class VtRawTraceTests(unittest.TestCase):
    def test_trace_is_off_until_explicit_start(self):
        trace = VtRawTrace(limit=100)
        trace.append(b"secret")
        self.assertEqual(trace.stop(), b"")
        trace.start()
        trace.append(b"\x1b[?1049h\x1b[2J")
        self.assertEqual(trace.stop(), b"\x1b[?1049h\x1b[2J")
        trace.append(b"after stop")
        self.assertEqual(trace.stop(), b"\x1b[?1049h\x1b[2J")

    def test_capture_preserves_pty_chunks_and_stops_at_limit(self):
        trace = VtRawTrace(limit=5)
        trace.start()
        trace.append(b"\x1b[")
        trace.append(b"?1049h")
        self.assertEqual(trace.stop(), b"\x1b[?10")
        self.assertTrue(trace.truncated)
        self.assertEqual(trace.size, 5)
        trace.start()
        self.assertFalse(trace.truncated)
        self.assertEqual(trace.size, 0)

    def test_ignore_nonbyte_inputs(self):
        trace = VtRawTrace()
        trace.start()
        trace.append("text")
        self.assertEqual(trace.stop(), b"")


if __name__ == '__main__':
    unittest.main()
