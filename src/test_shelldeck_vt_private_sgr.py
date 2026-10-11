"""Regressionen fuer private ANSI-SGR-Sequenzen in unterschiedlichen pyte-Versionen.

Der Qt-freie Kompatibilitaetstest laeuft auch ohne pyte. Mit installiertem
pyte wird der echte Stream/HistoryScreen-Pfad fuer vim-aehnliche Sequenzen
getestet, einschliesslich aufgetrennter PTY-Pakete.
"""

import unittest

import shelldeck_vt_screen as vt


class _LegacySgrScreen:
    """Simuliert pyte-Versionen ohne das Keyword ``private``."""

    def __init__(self):
        self.calls = []

    def select_graphic_rendition(self, *attrs):
        self.calls.append(attrs)


class _CompatibleLegacyScreen(vt._PrivateSgrCompatibility, _LegacySgrScreen):
    pass


class PrivateSgrCompatibilityTests(unittest.TestCase):
    def test_private_sgr_ignored_with_legacy_signature(self):
        screen = _CompatibleLegacyScreen()
        screen.select_graphic_rendition(4, 0, private=True)
        self.assertEqual(screen.calls, [])
        screen.select_graphic_rendition(31)
        screen.select_graphic_rendition(0, private=False)
        self.assertEqual(screen.calls, [(31,), (0,)])

    def test_no_global_pyte_monkeypatch(self):
        if vt.is_available():
            self.assertIsNot(vt._CompatibleScreen, vt.pyte.Screen)
            self.assertIsNot(vt._CompatibleHistoryScreen, vt.pyte.HistoryScreen)
            self.assertTrue(issubclass(vt._CompatibleScreen, vt.pyte.Screen))
            self.assertTrue(issubclass(vt._CompatibleHistoryScreen, vt.pyte.HistoryScreen))


@unittest.skipUnless(vt.is_available(), "pyte nicht installiert")
class PrivateSgrIntegrationTests(unittest.TestCase):
    def test_private_sgr_never_crashes_or_changes_colors_in_both_modes(self):
        for history in (False, True):
            with self.subTest(history=history):
                model = vt.VtScreen(rows=4, cols=30, enable_history=history)
                model.feed(b"\x1b[31mROT")
                model.feed(b"\x1b[?4m")
                model.feed(b"\x1b[>4;")
                model.feed(b"?mOK\x1b[0mX")
                cells = model.row_cells(0)
                self.assertEqual("".join(cell["char"] for cell in cells[:6]), "ROTOKX")
                self.assertEqual([cell["fg"] for cell in cells[:5]], ["red"] * 5)
                self.assertEqual(cells[5]["fg"], vt.DEFAULT_FG)

    def test_ordinary_sgr_and_private_modes_keep_working(self):
        model = vt.VtScreen(rows=3, cols=20, enable_history=True)
        model.feed("\x1b[1;32mA\x1b[0m\x1b[?25l")
        self.assertTrue(model.row_cells(0)[0]["bold"])
        self.assertEqual(model.row_cells(0)[0]["fg"], "green")
        self.assertTrue(model.cursor["hidden"])
        model.feed("\x1b[?25h")
        self.assertFalse(model.cursor["hidden"])


if __name__ == "__main__":
    unittest.main()
