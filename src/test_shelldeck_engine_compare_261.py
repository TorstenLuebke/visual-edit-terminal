import unittest
from shelldeck_engine_compare_261 import exercise
from shelldeck_engine_cases_252 import EngineCase
from shelldeck_engine_contract_240 import CursorSnapshot, ScreenSnapshot

class _Engine:
    def __init__(self, rows, columns):
        self.rows, self.columns = rows, columns
        self.data = bytearray()
    def feed(self, data):
        self.data.extend(data)
    def resize(self, rows, columns):
        self.rows, self.columns = rows, columns
    def transcript(self):
        return self.data.decode('utf-8', errors='replace')
    def snapshot(self):
        return ScreenSnapshot(self.rows, self.columns,
                              tuple([''] * self.rows), CursorSnapshot(0, 0))

class Compare261Tests(unittest.TestCase):
    def test_chunk_consistency(self):
        result = exercise(_Engine, (EngineCase('sample', b'\x1b[31mHi\r\n'),))
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['cases'][0]['seconds']), 3)
