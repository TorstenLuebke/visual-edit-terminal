import unittest
from pathlib import Path
from shelldeck_wezterm_build_gate_260 import require_build_evidence, WezTermBuildBlocked

class WezTermBuildGate260Tests(unittest.TestCase):
    def test_unapproved_archive_never_builds(self):
        manifest = Path(__file__).resolve().parents[1] / "docs" / "wezterm_candidate_259.json"
        with self.assertRaisesRegex(WezTermBuildBlocked, "build blocked"):
            require_build_evidence(manifest)
