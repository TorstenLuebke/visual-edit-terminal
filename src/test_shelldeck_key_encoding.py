"""Tests der Tastatur-/Paste-Codierung (Qt-frei)."""

import unittest

from shelldeck_key_encoding import encode_key, encode_paste, modifier_code


class ArrowTests(unittest.TestCase):
    def test_plain_arrows(self):
        self.assertEqual(encode_key("Up"), b"\x1b[A")
        self.assertEqual(encode_key("Down"), b"\x1b[B")
        self.assertEqual(encode_key("Right"), b"\x1b[C")
        self.assertEqual(encode_key("Left"), b"\x1b[D")

    def test_application_cursor_mode(self):
        self.assertEqual(encode_key("Up", application_cursor=True), b"\x1bOA")
        self.assertEqual(encode_key("Left", application_cursor=True), b"\x1bOD")

    def test_arrow_with_ctrl_uses_csi_modifier(self):
        # Ctrl -> Modifiercode 5, App-Cursor wird dann ignoriert.
        self.assertEqual(encode_key("Right", ctrl=True), b"\x1b[1;5C")
        self.assertEqual(encode_key("Up", ctrl=True, application_cursor=True), b"\x1b[1;5A")

    def test_shift_and_alt_modifiers(self):
        self.assertEqual(encode_key("Left", shift=True), b"\x1b[1;2D")
        self.assertEqual(encode_key("Left", alt=True), b"\x1b[1;3D")
        self.assertEqual(encode_key("Left", ctrl=True, shift=True), b"\x1b[1;6D")


class NavAndFunctionTests(unittest.TestCase):
    def test_tilde_keys(self):
        self.assertEqual(encode_key("Delete"), b"\x1b[3~")
        self.assertEqual(encode_key("PageUp"), b"\x1b[5~")
        self.assertEqual(encode_key("Insert"), b"\x1b[2~")

    def test_tilde_with_modifier(self):
        self.assertEqual(encode_key("Delete", ctrl=True), b"\x1b[3;5~")

    def test_function_keys(self):
        self.assertEqual(encode_key("F1"), b"\x1bOP")
        self.assertEqual(encode_key("F4"), b"\x1bOS")
        self.assertEqual(encode_key("F5"), b"\x1b[15~")
        self.assertEqual(encode_key("F12"), b"\x1b[24~")

    def test_function_key_with_modifier(self):
        self.assertEqual(encode_key("F1", shift=True), b"\x1b[1;2P")
        self.assertEqual(encode_key("F5", ctrl=True), b"\x1b[15;5~")


class SpecialKeyTests(unittest.TestCase):
    def test_enter_backspace_tab_escape(self):
        self.assertEqual(encode_key("Enter"), b"\r")
        self.assertEqual(encode_key("Backspace"), b"\x7f")
        self.assertEqual(encode_key("Backspace", ctrl=True), b"\x08")
        self.assertEqual(encode_key("Tab"), b"\t")
        self.assertEqual(encode_key("Backtab"), b"\x1b[Z")
        self.assertEqual(encode_key("Escape"), b"\x1b")

    def test_alt_prefixes_escape(self):
        self.assertEqual(encode_key("Enter", alt=True), b"\x1b\r")
        self.assertEqual(encode_key("", text="x", alt=True), b"\x1bx")


class TextAndCtrlTests(unittest.TestCase):
    def test_plain_text_utf8(self):
        self.assertEqual(encode_key("", text="a"), b"a")
        self.assertEqual(encode_key("", text="ä"), "ä".encode("utf-8"))

    def test_ctrl_letters(self):
        self.assertEqual(encode_key("", text="a", ctrl=True), b"\x01")
        self.assertEqual(encode_key("", text="C", ctrl=True), b"\x03")  # Ctrl+C

    def test_ctrl_symbols(self):
        self.assertEqual(encode_key("", text=" ", ctrl=True), b"\x00")   # Ctrl+Space
        self.assertEqual(encode_key("", text="[", ctrl=True), b"\x1b")

    def test_empty_when_nothing(self):
        self.assertEqual(encode_key("", text=""), b"")


class PasteTests(unittest.TestCase):
    def test_plain_paste_normalizes_newlines(self):
        self.assertEqual(encode_paste("a\r\nb\nc"), b"a\rb\rc")

    def test_bracketed_paste(self):
        self.assertEqual(encode_paste("ok", bracketed=True),
                         b"\x1b[200~ok\x1b[201~")

    def test_modifier_code(self):
        self.assertEqual(modifier_code(), 1)
        self.assertEqual(modifier_code(ctrl=True), 5)
        self.assertEqual(modifier_code(ctrl=True, shift=True), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
