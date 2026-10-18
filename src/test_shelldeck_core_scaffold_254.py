"""Python-side invariants for the optional Rust prototype (no build required)."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARGO = ROOT / "experimental" / "shelldeck_core" / "Cargo.toml"


class RustScaffold254Tests(unittest.TestCase):
    def test_manifest_requires_no_external_crates(self):
        import tomllib
        manifest = tomllib.loads(CARGO.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("dependencies", {}), {})
        self.assertFalse(manifest["package"]["publish"])

    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain not installed")
    def test_rust_line_model(self):
        subprocess.run(["cargo", "test", "--offline", "--manifest-path", str(CARGO)],
                       cwd=ROOT, check=True, timeout=120, capture_output=True, text=True)
