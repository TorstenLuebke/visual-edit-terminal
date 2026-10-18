"""Rust transport integrity tests. Cargo integration is optional and offline."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from shelldeck_rust_transport_247 import fnv1a64, verify_rust_probe

ROOT = Path(__file__).resolve().parent.parent / "experimental" / "rust_transport"


class RustTransportTests(unittest.TestCase):
    def test_hash_known_vector(self):
        self.assertEqual(fnv1a64(b""), "cbf29ce484222325")
        self.assertEqual(fnv1a64(b"hello"), "a430d84680aabd0b")

    def test_requires_raw_bytes(self):
        with self.assertRaises(TypeError):
            verify_rust_probe("missing", "text")

    def test_requires_built_binary(self):
        with self.assertRaises(FileNotFoundError):
            verify_rust_probe("/path/that/does/not/exist", b"data")

    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain not installed")
    def test_offline_rust_build_and_integrity(self):
        # Isolated build output: never touch the user's target/ directory.
        with tempfile.TemporaryDirectory() as target:
            env = dict(os.environ, CARGO_TARGET_DIR=target)
            subprocess.run(["cargo", "test", "--offline", "--manifest-path",
                            str(ROOT / "Cargo.toml")], env=env, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            subprocess.run(["cargo", "build", "--offline", "--manifest-path",
                            str(ROOT / "Cargo.toml")], env=env, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            executable = Path(target) / "debug" / ("shelldeck-rust-transport-probe.exe"
                                                   if os.name == "nt" else "shelldeck-rust-transport-probe")
            data = b"\x00\xff\x1b[31mhello\r\n" + bytes(range(256))
            result = verify_rust_probe(executable, data)
            self.assertEqual(result["bytes"], len(data))
            self.assertEqual(result["fnv1a64"], fnv1a64(data))


if __name__ == "__main__":
    unittest.main()
