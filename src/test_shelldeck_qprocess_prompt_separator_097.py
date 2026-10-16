"""Regression tests for the QProcess Bash prompt separator (Patch 097)."""

import ast
from pathlib import Path
import unittest


class QProcessBashPromptSeparatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (Path(__file__).parent / 'shelldeck_terminal_widget.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        methods = [node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef)
                   and node.name == 'separate_qprocess_bash_prompt_before_command']
        assert len(methods) == 1
        cls.method_source = ast.get_source_segment(source, methods[0])
        # Run the exact method against fake Qt process types without requiring a GUI.
        namespace = {'QProcess': type('QProcess', (), {})}
        exec('class Subject:\n' + ''.join('    ' + line + '\n'
             for line in cls.method_source.splitlines()), namespace)
        cls.Subject = namespace['Subject']
        cls.Process = namespace['QProcess']

    def make_case(self, prompt, *, backend='qprocess', shell='bash', vt=False):
        s = self.Subject()
        s.process = self.Process() if backend == 'qprocess' else object()
        s.shell_type = shell
        s.real_terminal_active = vt
        s.queued = []
        s.terminal_output_text_for_state_checks = lambda: prompt
        s.output_ends_with_shell_prompt = lambda text: text.endswith('$')
        s.queue_terminal_output = s.queued.append
        return s

    def test_unterminated_prompt_is_separated(self):
        s = self.make_case('(.venv) host:/project$')
        self.assertTrue(s.separate_qprocess_bash_prompt_before_command())
        self.assertEqual(s.queued, ['\n'])

    def test_existing_linebreak_is_preserved(self):
        s = self.make_case('(.venv) host:/project$\n')
        self.assertFalse(s.separate_qprocess_bash_prompt_before_command())
        self.assertEqual(s.queued, [])

    def test_arbitrary_output_is_never_edited(self):
        s = self.make_case('regular command output')
        self.assertFalse(s.separate_qprocess_bash_prompt_before_command())
        self.assertEqual(s.queued, [])

    def test_other_engines_and_shells_untouched(self):
        for backend, shell, vt in [('pty', 'bash', False),
                                   ('qprocess', 'zsh', False),
                                   ('qprocess', 'bash', True)]:
            s = self.make_case('host:/project$', backend=backend, shell=shell, vt=vt)
            self.assertFalse(s.separate_qprocess_bash_prompt_before_command())
            self.assertEqual(s.queued, [])


if __name__ == '__main__':
    unittest.main()
