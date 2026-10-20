import json
import unittest
from pathlib import Path
from shelldeck_wezterm_revision_259 import inspect_candidate

class RevisionGate259Tests(unittest.TestCase):
    def test_checked_in_candidate_is_fail_closed(self):
        path = Path(__file__).resolve().parents[1] / "docs" / "wezterm_candidate_259.json"
        result = inspect_candidate(json.loads(path.read_text(encoding="utf-8")))
        self.assertFalse(result["ready_for_manual_review"])
        self.assertFalse(result["distribution_approved"])
        self.assertGreater(len(result["findings"]), 0)

    def test_unpinned_revision_is_not_sufficient(self):
        self.assertFalse(inspect_candidate({"revision": "main"})["ready_for_manual_review"])
