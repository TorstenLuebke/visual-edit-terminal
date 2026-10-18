import unittest
from shelldeck_engine_cases_252 import engine_cases, replay_case


class _Collector:
    def __init__(self):
        self.data = bytearray()

    def feed(self, data):
        self.data.extend(data)


class EngineCases252Tests(unittest.TestCase):
    def test_unique_named_immutable_cases(self):
        cases = engine_cases()
        self.assertEqual(len({c.name for c in cases}), len(cases))
        self.assertTrue(all(isinstance(c.data, bytes) and c.data for c in cases))
        self.assertIn("long_output", {c.name for c in cases})

    def test_replay_preserves_all_bytes_in_all_chunk_sizes(self):
        for case in engine_cases():
            for size in (1, 2, 7, 4096, len(case.data) + 1):
                with self.subTest(case=case.name, size=size):
                    receiver = _Collector()
                    replay_case(receiver, case, size)
                    self.assertEqual(bytes(receiver.data), case.data)

    def test_sha256_stable(self):
        self.assertEqual({c.name: c.sha256 for c in engine_cases()},
                         {c.name: c.sha256 for c in engine_cases()})

    def test_invalid_chunk_size(self):
        with self.assertRaises(ValueError):
            replay_case(_Collector(), engine_cases()[0], 0)
