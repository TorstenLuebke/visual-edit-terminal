"""No-GUI tests for the content-free, opt-in resize audit (Patch 288)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shelldeck_resize_audit_288 import ResizeAudit


class ResizeAudit288(unittest.TestCase):
    def test_disabled_is_entirely_inert(self):
        with patch.dict(os.environ, {}, clear=True):
            audit = ResizeAudit.from_environment()
        self.assertFalse(audit.enabled)
        self.assertFalse(audit.record("host_resize", width=800))

    def test_only_content_free_fields_are_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resize.jsonl"
            audit = ResizeAudit(str(path))
            self.assertTrue(audit.record("host_resize", width=800, chars=20,
                                         command="private-command", text="secret"))
            record = json.loads(path.read_text())
            self.assertEqual(record["width"], 800)
            self.assertEqual(record["chars"], 20)
            self.assertNotIn("command", record)
            self.assertNotIn("text", record)
            self.assertNotIn("private-command", path.read_text())
            self.assertNotIn("secret", path.read_text())

    def test_fixed_event_names_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resize.jsonl"
            audit = ResizeAudit(str(path))
            self.assertFalse(audit.record("secret", width=1))
            self.assertFalse(path.exists())

    def test_bounded_records(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = ResizeAudit(str(Path(folder) / "resize.jsonl"))
            audit.count = audit.MAX_RECORDS
            self.assertFalse(audit.record("host_resize", width=600))

    def test_explicit_environment_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "resize.jsonl")
            with patch.dict(os.environ, {"SHELLDECK_RESIZE_DIAG_PATH": path}):
                audit = ResizeAudit.from_environment()
            self.assertTrue(audit.enabled)
            self.assertEqual(audit.path, path)


if __name__ == "__main__":
    unittest.main()
