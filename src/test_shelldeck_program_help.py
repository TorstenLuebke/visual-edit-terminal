"""UI-unabhaengige Regression fuer die umfangreiche Programmhilfe."""
import unittest
from types import SimpleNamespace

from shelldeck_program_assist import GUIDES
from shelldeck_program_help import (
    HelpEntry, HelpSection, PROGRAM_HELP, filter_help_sections, help_sections_for,
)


class ProgramHelpContentTests(unittest.TestCase):
    def test_every_integrated_guide_has_structured_help(self):
        self.assertTrue(set(PROGRAM_HELP).issubset(GUIDES),
                        "Alle integrierten Guides benoetigen eigene Themen")
        for name in PROGRAM_HELP:
            with self.subTest(program=name):
                sections = help_sections_for(GUIDES[name])
                self.assertGreaterEqual(len(sections), 2)
                self.assertTrue(all(s.title and s.entries for s in sections))
                self.assertTrue(all(e.description for s in sections for e in s.entries))

    def test_search_is_case_accent_and_word_order_independent(self):
        sections = help_sections_for(GUIDES['vim'])
        matched = filter_help_sections(sections, 'SPEICHERN')
        self.assertTrue(any('Speichern' in s.title for s in matched))
        matched = filter_help_sections(sections, 'ruckgaengig')
        self.assertTrue(any('Bearbeiten' in s.title for s in matched))
        matched = filter_help_sections(sections, 'vim splIT')
        self.assertEqual(matched, ())  # mehrere Worte muessen im Treffer stehen
        self.assertEqual(filter_help_sections(sections, ''), sections)
        self.assertEqual(filter_help_sections(sections, 'einwortdasnirgendwoauftritt'), ())

    def test_filter_does_not_mutate_catalog(self):
        sections = help_sections_for(GUIDES['tmux'])
        before = repr(sections)
        self.assertTrue(filter_help_sections(sections, 'trennen'))
        self.assertEqual(repr(sections), before)

    def test_user_guides_fall_back_to_safe_plain_text(self):
        fake = SimpleNamespace(name='custom', help_text='<script>not html</script>\nTaste: q')
        sections = help_sections_for(fake)
        self.assertEqual(len(sections), 1)
        self.assertIn('<script>', sections[0].entries[0].description)
        self.assertEqual(len(sections[0].entries), 2)
        self.assertEqual(help_sections_for(None), ())

    def test_detach_is_not_documented_as_session_exit(self):
        for name in ('tmux', 'screen'):
            sections = help_sections_for(GUIDES[name])
            texts = '\n'.join(e.description for s in sections for e in s.entries)
            self.assertIn('Sitzung trennen', texts)
            self.assertIn('Sitzung endgueltig beenden', texts)


if __name__ == '__main__':
    unittest.main()

# Neu hinzugefuegte Programme nutzen optional ebenfalls Kapitel statt Fliesstext.
class UserGuideHelpSectionsTests(unittest.TestCase):
    def test_custom_multisection_help_is_data_only(self):
        import json
        import tempfile
        from pathlib import Path
        from shelldeck_program_assist import load_user_guides
        payload = {"programs": [{
            "name": "myviewer", "label": "Viewer", "help_text": "Alte Hilfe",
            "keys": ["q"], "help_sections": [
                {"title": "Suche", "entries": [
                    {"keys": "/", "description": "Suche beginnen", "detail": "Beispiel: /name"}]},
                {"title": "Beenden", "entries": [
                    {"keys": "q", "description": "Beenden"}]}],
        }]}
        with tempfile.TemporaryDirectory() as folder:
            file_path = Path(folder) / "program_guides.json"
            file_path.write_text(json.dumps(payload), encoding="utf-8")
            guides, aliases, errors = load_user_guides(file_path)
        self.assertEqual(errors, [])
        sections = help_sections_for(guides['myviewer'])
        self.assertEqual([section.title for section in sections], ['Suche', 'Beenden'])
        self.assertEqual(sections[0].entries[0].detail, 'Beispiel: /name')
        self.assertEqual(aliases['myviewer'], 'myviewer')

    def test_invalid_multisection_help_is_rejected(self):
        import json
        import tempfile
        from pathlib import Path
        from shelldeck_program_assist import load_user_guides
        payload = {"programs": [{"name": "badviewer", "label": "Bad",
            "help_text": "test", "keys": ["q"],
            "help_sections": [{"title": "X", "entries": [
                {"keys": "q", "description": "", "detail": ""}]}]}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'program_guides.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            guides, _, errors = load_user_guides(path)
        self.assertEqual(guides, {})
        self.assertEqual(len(errors), 1)
