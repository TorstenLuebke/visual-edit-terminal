"""Integration: Bash-Exitstatus bleibt fuer den folgenden Benutzerbefehl erhalten."""
import subprocess
import unittest

from shelldeck_qprocess_bash_batch import wrap_batch_command


class BatchExitStatusTests(unittest.TestCase):
    def test_previous_status_in_general_shell_expressions(self):
        commands = [
            "false",
            "printf 'one=%s\\n' $?",
            "false",
            "result=$?; printf 'var=%s\\n' $result",
            "true",
            "printf 'zero=%s\\n' $?",
        ]
        script = "".join(wrap_batch_command(cmd, f"{i:032x}") for i, cmd in enumerate(commands))
        proc = subprocess.run(["bash", "--noprofile", "--norc"], input=script,
                              capture_output=True, text=True, timeout=8)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("one=1", proc.stdout)
        self.assertIn("var=1", proc.stdout)
        self.assertIn("zero=0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
