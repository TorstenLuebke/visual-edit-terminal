"""Qt-GUI-Regression fuer die neue, nicht steuernde Programmhilfe."""
import os
import unittest
from types import SimpleNamespace

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None
if QApplication is not None:
    from shelldeck_program_help_dialog import ProgramHelpDialog


@unittest.skipUnless(QApplication is not None, 'PySide6 nicht verfuegbar')
class ProgramHelpDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Permanente Referenz auf QApplication verhindert zerstoerte QPaintDevices.
        cls.app = QApplication.instance() or QApplication([])

    def test_search_updates_topics_and_keeps_canonical_help(self):
        from shelldeck_program_assist import GUIDES
        dialog = ProgramHelpDialog(GUIDES['vim'])
        try:
            self.assertGreater(dialog.topic_list.count(), 3)
            dialog.search_edit.setText(':%s')
            self.assertEqual(dialog.topic_list.count(), 1)
            self.assertIn('Ersetzen', dialog.topic_list.item(0).text())
            self.assertIn(':%s/alt/neu/g', dialog.details.toPlainText())
            dialog.search_edit.clear()
            self.assertGreater(dialog.topic_list.count(), 3)
        finally:
            dialog.close()

    def test_programs_keep_their_own_help(self):
        from shelldeck_program_assist import GUIDES
        vim = ProgramHelpDialog(GUIDES['vim'])
        tmux = ProgramHelpDialog(GUIDES['tmux'])
        try:
            vim.search_edit.setText('speichern')
            tmux.search_edit.setText('trennen')
            self.assertIn('Sitzung trennen', tmux.details.toPlainText())
            self.assertNotIn('Sitzung trennen', vim.details.toPlainText())
        finally:
            vim.close()
            tmux.close()

    def test_untrusted_guide_data_is_displayed_as_text_only(self):
        guide = SimpleNamespace(name='custom', label='<img src=x>',
                                help_text='<script>alert(1)</script>')
        dialog = ProgramHelpDialog(guide)
        try:
            self.assertIn('<script>', dialog.details.toPlainText())
            self.assertNotIn('<script>', dialog.details.toHtml())
        finally:
            dialog.close()


if __name__ == '__main__':
    unittest.main()
