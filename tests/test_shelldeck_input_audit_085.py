"""Patch 085: Geheimnisfreie und optionale PTY-Schreibdiagnose."""
import json
from shelldeck_input_audit_085 import InputWriteAudit


def test_off_by_default(tmp_path):
    audit = InputWriteAudit()
    audit.record(bytes_count=5, status="written", result=5)
    assert audit.counter == 1
    assert list(tmp_path.iterdir()) == []


def test_only_safe_metadata(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = InputWriteAudit(path)
    secret = "PASSWORD_SHOULD_NEVER_APPEAR"
    audit.record(bytes_count=len(secret), status="written", result=len(secret))
    audit.record(bytes_count=2, status="exception")
    raw = path.read_text()
    assert secret not in raw
    entries = [json.loads(row) for row in raw.splitlines()]
    assert entries[0] == {"event": "grid_pty_write", "sequence": 1,
                          "bytes_count": len(secret), "status": "written",
                          "write_result": len(secret)}
    assert entries[1]["sequence"] == 2
    assert entries[1]["status"] == "exception"


def test_unwritable_diagnostic_does_not_break_input(tmp_path):
    audit = InputWriteAudit(tmp_path / "no-directory" / "log.jsonl")
    audit.record(bytes_count=4, status="written", result=4)
    assert audit.counter == 1
