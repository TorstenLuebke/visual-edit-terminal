import json
import os
import stat
import sys
import pytest
from shelldeck_wezterm_process_263 import EngineProtocolError, WezTermProcessAdapter


def test_missing_binary(tmp_path):
    with pytest.raises(FileNotFoundError):
        WezTermProcessAdapter(executable=tmp_path / "absent")


def test_handshake_rejects_wrong_engine(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX executable script fixture")
    script = tmp_path / "fake-engine"
    script.write_text("#!" + sys.executable + "\nimport sys,json\nfor line in sys.stdin:\n print(json.dumps({'ok': True, 'ready': True, 'engine': 'not-wezterm'}),flush=True)\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(EngineProtocolError, match="did not identify"):
        WezTermProcessAdapter(executable=script)


def test_feed_rejects_text_before_launch(tmp_path):
    with pytest.raises(FileNotFoundError):
        WezTermProcessAdapter(executable=tmp_path / "absent")
