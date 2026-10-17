"""Regression for the conservative production QProcess completion bridge."""
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from shelldeck_qprocess_bash_protocol import (BashCompletionDecoder, new_completion_token, wrap_bash_command)
from shelldeck_qprocess_bash_policy import command_allows_completion_marker


def test_safe_commands_and_source_fallback():
    for cmd in ("pwd", "cd /tmp", "export SAMPLE=foo", "false"):
        assert command_allows_completion_marker(cmd)
    for cmd in ("source .venv/bin/activate", "sudo -v", "python3", "cat | grep x"):
        assert not command_allows_completion_marker(cmd)


def test_decoder_split_marker_and_status():
    token = new_completion_token()
    text = "ausgabe\x1eSHELLDECK_DONE_" + token + ":7\x1fprompt"
    for split in range(len(text)):
        decoder = BashCompletionDecoder(token)
        a, codes_a = decoder.feed(text[:split])
        b, codes_b = decoder.feed(text[split:])
        assert a + b + decoder.finish() == "ausgabeprompt"
        assert codes_a + codes_b == [7]


def test_live_qprocess_bridge_is_conservative():
    text = (SRC / "shelldeck_terminal_widget.py").read_text()
    assert "command_allows_completion_marker(command)" in text
    assert "wrap_bash_command(command, token)" in text
    assert "self._bash_completion_decoder = None" in text
