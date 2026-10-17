import ast
import unittest
from shelldeck_qprocess_bash_batch import normalized_batch_mode, batch_for_session


class BatchSelectionTests(unittest.TestCase):
    def test_preference(self):
        self.assertEqual(normalized_batch_mode('batch'), 'batch')
        self.assertEqual(normalized_batch_mode('unknown'), 'classic')
        self.assertFalse(batch_for_session('classic', {'SHELLDECK_QPROCESS_BASH_BATCH': '1'}))
        self.assertTrue(batch_for_session('batch', {}))
        self.assertTrue(batch_for_session(None, {'SHELLDECK_QPROCESS_BASH_BATCH': '1'}))

    def test_gui_has_guarded_restart_and_persistence(self):
        from pathlib import Path
        src = (Path(__file__).parent / 'main.py').read_text()
        ast.parse(src)
        self.assertIn('"qprocess_bash_mode": self.qprocess_bash_mode', src)
        self.assertIn('force_restart=True', src)
        self.assertIn('self.qprocess_bash_mode = previous', src)

if __name__ == '__main__':
    unittest.main()
