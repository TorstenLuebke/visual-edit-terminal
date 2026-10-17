"""Prevent control-sequence cleaning from destroying Bash completion frames."""
import ast
from pathlib import Path
import unittest

from shelldeck_qprocess_bash_protocol import BashCompletionDecoder, new_completion_token


class MarkerBeforeCleanTests(unittest.TestCase):
    def test_frame_survives_chunking_when_parsed_before_text_cleaning(self):
        token = new_completion_token()
        decoder = BashCompletionDecoder(token)
        payload = f"/tmp\n\x1eSHELLDECK_DONE_{token}:0\x1f".encode()
        visible, codes = [], []
        for chunk in (payload[:5], payload[5:14], payload[14:-1], payload[-1:]):
            shown, done = decoder.feed(chunk.decode())
            visible.append(shown)
            codes.extend(done)
        self.assertEqual("".join(visible), "/tmp\n")
        self.assertEqual(codes, [0])

    def test_qprocess_decodes_marker_before_render_cleanup(self):
        tree = ast.parse(Path(__file__).with_name('shelldeck_terminal_widget.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'ShellDeckTerminalWidget')
        func = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == 'handle_stdout')
        code = ast.unparse(func)
        self.assertLess(code.index('decoder.feed(decoded)'), code.index('predecoded_text=visible'))


if __name__ == '__main__':
    unittest.main()
