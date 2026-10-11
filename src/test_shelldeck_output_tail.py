"""Regression: Prompt-Abfragen duerfen nicht das volle QTextDocument/FIFO kopieren."""

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest

from shelldeck_output_buffer import TerminalOutputBuffer


SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ShellDeckTerminalWidget")


class FakeDocument:
    def __init__(self, text):
        self.text = text
        self.selected_lengths = []

    def characterCount(self):
        return len(self.text) + 1


class FakeCursor:
    MoveOperation = SimpleNamespace(End=1)
    MoveMode = SimpleNamespace(KeepAnchor=1)

    def __init__(self, doc):
        self.doc = doc
        self.pos = 0
        self.anchor = 0

    def document(self):
        return self.doc

    def position(self):
        return self.pos

    def movePosition(self, op):
        assert op == self.MoveOperation.End
        self.pos = len(self.doc.text)
        self.anchor = self.pos

    def setPosition(self, pos, mode=None):
        if mode != self.MoveMode.KeepAnchor:
            self.anchor = pos
        self.pos = pos

    def selectedText(self):
        result = self.doc.text[min(self.anchor, self.pos):max(self.anchor, self.pos)]
        self.doc.selected_lengths.append(len(result))
        return result.replace("\n", "\u2029")


def methods(*names):
    nodes = [n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names)
    code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), "exec")
    context = {"QTextCursor": FakeCursor, "TERMINAL_STATE_TAIL_CHARS": 6000}
    exec(code, context)
    return {name: context[name] for name in names}


class OutputTailTests(unittest.TestCase):
    def test_fifo_tail_never_modifies_unrendered_output(self):
        queue = TerminalOutputBuffer()
        for i in range(50000):
            queue.append(f"{i}:ausgabe\n", None)
        total = queue.pending_chars
        self.assertEqual(queue.tail(30), "".join(part[0] for part in queue)[-30:])
        self.assertEqual(queue.tail(0), "")
        self.assertEqual(queue.pending_chars, total)
        self.assertEqual(len(queue), 50000)
        queue.take(13, lambda *_: 13)
        self.assertEqual(queue.tail(100), "".join(part[0] for part in queue)[-100:])

    def test_state_uses_bounded_visible_and_pending_tails(self):
        functions = methods("terminal_document_tail", "output_tail_context", "terminal_output_text_for_state_checks")
        doc = FakeDocument(("alte Ausgabe\n" * 50000) + "noch offen ")
        queue = TerminalOutputBuffer()
        queue.append("Passwort: ", None)
        queue.append("und shell@host:/tmp$ ", None)
        tab = SimpleNamespace(output_area=SimpleNamespace(document=lambda: doc,
            toPlainText=lambda: self.fail("Volltext darf nicht gelesen werden")), _output_queue=queue)
        for name, fn in functions.items():
            setattr(tab, name, MethodType(fn, tab))
        tail = tab.terminal_output_text_for_state_checks()
        self.assertTrue(tail.endswith("noch offen Passwort: und shell@host:/tmp$ "))
        self.assertLessEqual(len(tail), 6000)
        self.assertTrue(doc.selected_lengths)
        self.assertLessEqual(max(doc.selected_lengths), 6000)
        self.assertEqual(queue.pending_chars, len("Passwort: und shell@host:/tmp$ "))
        self.assertEqual(tab.output_tail_context(0), "")

    def test_fifo_larger_than_limit_avoids_document_access(self):
        funcs = methods("output_tail_context")
        queue = TerminalOutputBuffer()
        queue.append("V" * 100_000 + "\nuser@host:/tmp$ ", None)
        tab = SimpleNamespace(_output_queue=queue,
                              terminal_document_tail=lambda *a, **k: self.fail("Kein Dokumentzugriff"))
        tab.output_tail_context = MethodType(funcs["output_tail_context"], tab)
        self.assertEqual(tab.output_tail_context(22), queue.tail(22))

    def test_inline_prompt_context_reads_only_before_inline_marker(self):
        funcs = methods("terminal_document_tail", "output_tail_context", "inline_prompt_context_text")
        text = "\n".join(["x" * 300] * 100) + "\nvor prompt" + "EINGABE"
        doc = FakeDocument(text)
        mark = text.index("EINGABE")
        queue = TerminalOutputBuffer()
        queue.append("letzter prompt$ ", None)
        tab = SimpleNamespace(output_area=SimpleNamespace(document=lambda: doc),
                              _output_queue=queue, _inline_prompt_cursor=SimpleNamespace(position=lambda: mark),
                              inline_markers_valid=lambda: True)
        for name, fn in funcs.items():
            setattr(tab, name, MethodType(fn, tab))
        tail = tab.inline_prompt_context_text()
        self.assertTrue(tail.endswith("vor promptletzter prompt$ "))
        self.assertNotIn("EINGABE", tail)
        self.assertLessEqual(len(tail), 6000)


if __name__ == "__main__":
    unittest.main()
