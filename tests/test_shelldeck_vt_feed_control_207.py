"""Verlustfreiheit und datensparsame Diagnose für den VT-Feed."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from shelldeck_vt_feed_control import FeedCounters, terminal_feed_chunks


@pytest.mark.parametrize("size", [1, 2, 7, 1024, 4096])
def test_raw_bytes_preserved_across_split_escape_utf8(size):
    payload = (b"\x1b[31m" + "Ä😀".encode("utf-8") + b"\r\n") * 1024
    chunks = list(terminal_feed_chunks(payload, size))
    assert b"".join(chunks) == payload
    assert all(0 < len(chunk) <= size for chunk in chunks)


def test_text_preserved_and_empty_input():
    payload = "Ä\x1b[2J😀" * 200
    assert "".join(terminal_feed_chunks(payload, 3)) == payload
    assert list(terminal_feed_chunks(b"")) == []


def test_invalid_slice_rejected():
    with pytest.raises(ValueError):
        list(terminal_feed_chunks(b"text", 0))


def test_counters_no_log_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("SHELLDECK_VT_FEED_DIAG_PATH", raising=False)
    counters = FeedCounters()
    for _ in range(256):
        counters.record(4096, 4)
    assert counters.calls == 256
    assert counters.bytes == 256 * 4096
    assert not list(tmp_path.iterdir())


def test_counters_record_only_aggregates(tmp_path):
    log = tmp_path / "vt-feed.jsonl"
    counters = FeedCounters(str(log))
    for _ in range(256):
        counters.record(4096, 4)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["calls"] == 256
    assert rows[0]["input_bytes"] == 256 * 4096
    assert set(rows[0]) == {"event", "calls", "input_bytes", "pieces", "max_input", "seconds"}
