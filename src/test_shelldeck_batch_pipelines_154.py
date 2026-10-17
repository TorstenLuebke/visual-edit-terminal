"""Linux-Bash pipeline behavior in the persistent QProcess command wrapper."""
import subprocess
import unittest
from shelldeck_qprocess_bash_batch import wrap_batch_command
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder


class BatchPipelineTests(unittest.TestCase):
    def test_pipefail_status_and_following_command(self):
        commands = ('set -o pipefail', 'false | true', 'echo "pipeline-rc=$?"',
                    'set +o pipefail', 'false | true', 'echo after')
        tokens = [f'{i:032x}' for i in range(len(commands))]
        script = ''.join(wrap_batch_command(cmd, tok)
                         for cmd, tok in zip(commands, tokens))
        result = subprocess.run(['bash', '--noprofile', '--norc'], input=script,
                                text=True, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = [0, 1, 0, 0, 0, 0]
        for token, code in zip(tokens, expected):
            parser = BashCompletionDecoder(token)
            _, actual = parser.feed(result.stdout)
            self.assertEqual(actual, [code])
        self.assertIn('pipeline-rc=1', result.stdout)
        self.assertIn('after', result.stdout)

    def test_stdin_reader_inside_pipeline_cannot_consume_transport(self):
        commands = ('cat | wc -c', 'echo SURVIVES')
        script = ''.join(wrap_batch_command(c, f'{i:032x}')
                         for i, c in enumerate(commands))
        result = subprocess.run(['bash', '--noprofile', '--norc'], input=script,
                                text=True, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SURVIVES', result.stdout)
        self.assertEqual(result.stdout.count('SHELLDECK_DONE_'), 2)


if __name__ == '__main__':
    unittest.main()
