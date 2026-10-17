"""Document and detect the Bash nounset limitation without claiming recovery."""
import subprocess
import unittest
from shelldeck_qprocess_bash_batch import wrap_batch_command
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder


class BatchNounsetTests(unittest.TestCase):
    def test_unbound_variable_terminates_bash_before_completion_frame(self):
        commands = ('set -u', 'echo "$SHELLDECK_VARIABLE_NOT_DEFINED"',
                    'echo SHOULD_NOT_RUN')
        tokens = [f'{i:032x}' for i in range(len(commands))]
        script = ''.join(wrap_batch_command(cmd, token)
                         for cmd, token in zip(commands, tokens))
        result = subprocess.run(['bash', '--noprofile', '--norc'], input=script,
                                text=True, capture_output=True, timeout=8)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHELLDECK_VARIABLE_NOT_DEFINED', result.stderr)
        self.assertNotIn('SHOULD_NOT_RUN', result.stdout)
        _, first_codes = BashCompletionDecoder(tokens[0]).feed(result.stdout)
        _, second_codes = BashCompletionDecoder(tokens[1]).feed(result.stdout)
        self.assertEqual(first_codes, [0])
        self.assertEqual(second_codes, [])


if __name__ == '__main__':
    unittest.main()
