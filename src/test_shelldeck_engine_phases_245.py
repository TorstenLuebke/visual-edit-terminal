"""Fast Qt-independent phase benchmark contracts, including disabled memory tracing."""
import unittest
from shelldeck_engine_bench_241 import run_phases
from test_shelldeck_engine_arch_242 import StubEngine


class EnginePhaseBenchmarkTests(unittest.TestCase):
    def test_phase_contract_and_total_data(self):
        data = b"hello\r\n" * 100
        report = run_phases(StubEngine, data, rows=4, columns=20,
                            repeat=2, chunk_size=7)
        self.assertEqual(report["bytes"], len(data))
        self.assertEqual(report["state"]["transcript_chars"], len(data))
        self.assertEqual(set(report["phase_median_seconds"]),
                         {"feed", "snapshot", "transcript", "resize"})
        self.assertIsNone(report["peak_traced_bytes"])

    def test_memory_tracing_is_explicit(self):
        report = run_phases(StubEngine, b"x", repeat=1, trace_memory=True)
        self.assertTrue(report["memory_tracing"])
        self.assertIsInstance(report["peak_traced_bytes"], int)

    def test_reject_invalid_geometry(self):
        with self.assertRaises(ValueError):
            run_phases(StubEngine, b"x", columns=1)

    def test_benchmark_does_not_mutate_input(self):
        payload = b"abc\r\n" * 20
        run_phases(StubEngine, payload)
        self.assertEqual(payload, b"abc\r\n" * 20)


if __name__ == "__main__":
    unittest.main()
