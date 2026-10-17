"""QProcess transport integration for the future persistent noninteractive Bash engine.

This exercises actual Qt process pipes, unlike subprocess-only protocol tests.
It deliberately does not enable the new protocol in the production GUI.
"""
import os
import shutil
import sys
import time
import unittest

from shelldeck_qprocess_bash_protocol import (
    BashCompletionDecoder, new_completion_token, wrap_bash_command,
)

try:
    from PySide6.QtCore import QCoreApplication, QProcess
except ImportError:
    QCoreApplication = QProcess = None


@unittest.skipUnless(QProcess is not None and os.name == 'posix' and shutil.which('bash'),
                     'QProcess und POSIX-Bash notwendig')
class QProcessBashTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._owned_app = QCoreApplication.instance() is None
        if cls._owned_app:
            cls.app = QCoreApplication([])
        else:
            cls.app = QCoreApplication.instance()

    @classmethod
    def tearDownClass(cls):
        if cls._owned_app:
            cls.app.quit()
            cls.app = None

    def test_state_and_exit_codes_survive_qprocess_pipe(self):
        token = new_completion_token()
        decoder = BashCompletionDecoder(token)
        proc = QProcess()
        stdout_parts = []
        statuses = []
        stderr_parts = []
        proc.setProgram(shutil.which('bash'))
        proc.setArguments(['--noprofile', '--norc'])
        proc.start()
        self.assertTrue(proc.waitForStarted(3000))
        try:
            commands = [
                ('export SHELLDECK_QT_TEST=kept', 0),
                ('cd /tmp', 0),
                ('printf "%s:%s\\n" "$SHELLDECK_QT_TEST" "$PWD"', 0),
                ('false', 1),
            ]
            for command, code in commands:
                payload = wrap_bash_command(command, token).encode('utf-8')
                self.assertEqual(proc.write(payload), len(payload))
                self.assertTrue(proc.waitForBytesWritten(3000))
                deadline = time.monotonic() + 5
                while len(statuses) < commands.index((command, code)) + 1:
                    remain = int(max(1, (deadline - time.monotonic()) * 1000))
                    self.assertGreater(deadline - time.monotonic(), 0, 'Bash completion timed out')
                    proc.waitForReadyRead(min(remain, 100))
                    chunk = bytes(proc.readAllStandardOutput()).decode('utf-8', 'replace')
                    if chunk:
                        visible, codes = decoder.feed(chunk)
                        stdout_parts.append(visible)
                        statuses.extend(codes)
                    stderr_parts.append(bytes(proc.readAllStandardError()).decode('utf-8', 'replace'))
                self.assertEqual(statuses[-1], code)
            self.assertIn('kept:/tmp', ''.join(stdout_parts))
            self.assertNotIn('Keine Jobsteuerung', ''.join(stderr_parts))
            proc.write(b'exit\n')
            proc.waitForBytesWritten(1000)
            self.assertTrue(proc.waitForFinished(3000))
            self.assertEqual(decoder.finish(), '')
        finally:
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
                proc.waitForFinished(3000)


if __name__ == '__main__':
    unittest.main()
