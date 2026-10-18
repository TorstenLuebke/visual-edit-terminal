"""Contract and bench regression tests; no GUI or native library required."""
import unittest

from shelldeck_engine_contract_240 import CursorSnapshot, ScreenSnapshot, TerminalEngineContract
from shelldeck_engine_bench_241 import built_in_cases, run_case, load_adapter


class StubEngine:
    def __init__(self, rows, columns):
        self.rows, self.columns = rows, columns
        self.data = bytearray()

    def feed(self, data: bytes) -> None:
        self.data.extend(data)

    def resize(self, rows, columns) -> None:
        self.rows, self.columns = rows, columns

    def snapshot(self):
        return ScreenSnapshot(self.rows, self.columns, tuple("" for _ in range(self.rows)), CursorSnapshot(0, 0))

    def transcript(self) -> str:
        return self.data.decode("utf-8", "replace")


class EngineArchitectureTests(unittest.TestCase):
    def test_snapshot_rejects_invalid_geometry(self):
        with self.assertRaises(ValueError):
            ScreenSnapshot(1, 2, (), CursorSnapshot(0, 0))
        with self.assertRaises(ValueError):
            ScreenSnapshot(1, 2, ("ok",), CursorSnapshot(0, 2))

    def test_stub_conforms_to_protocol(self):
        self.assertIsInstance(StubEngine(2, 4), TerminalEngineContract)

    def test_benchmark_does_not_drop_bytes(self):
        report = run_case(StubEngine, b"abc\n" * 12, rows=2, columns=4, repeat=2, chunk_size=3)
        self.assertEqual(report["bytes"], 48)
        self.assertEqual(report["state"]["transcript_chars"], 48)

    def test_suite_includes_large_output(self):
        self.assertIn("49999", built_in_cases()["long_output"].decode())

    def test_bad_adapter_rejected(self):
        with self.assertRaises(ValueError):
            load_adapter("unknown")


if __name__ == "__main__":
    unittest.main()
