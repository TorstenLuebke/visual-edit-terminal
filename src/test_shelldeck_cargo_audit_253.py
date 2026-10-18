import tempfile
import unittest
from pathlib import Path
from shelldeck_cargo_audit_253 import inventory


class CargoAudit253Tests(unittest.TestCase):
    def test_missing_lock_is_not_a_license_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Cargo.toml").write_text('[package]\nname="probe"\nversion="0.1.0"\n[dependencies]\nwezterm-term="0.1"\n')
            result = inventory(root / "Cargo.toml", root / "Cargo.lock")
            self.assertFalse(result["lock_present"])
            self.assertFalse(result["licensing_verified"])
            self.assertEqual(result["direct_dependencies"], ["wezterm-term"])

    def test_lock_inventory_preserves_sources_without_guessing_licenses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Cargo.toml").write_text('[package]\nname="probe"\nversion="0.1.0"\n')
            (root / "Cargo.lock").write_text('version = 3\n[[package]]\nname="foo"\nversion="1.0.0"\nsource="registry+test"\nchecksum="abc"\n')
            result = inventory(root / "Cargo.toml", root / "Cargo.lock")
            self.assertEqual(result["locked_packages"][0]["source"], "registry+test")
            self.assertNotIn("license", result["locked_packages"][0])
            self.assertFalse(result["licensing_verified"])
