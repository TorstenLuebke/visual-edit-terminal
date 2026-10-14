"""Verify explicit CSI SU/SD reaches ShellDeck's VT screens."""
import pytest

pytest.importorskip("pyte")
from shelldeck_vt_screen import VtScreen


def test_stream_has_local_su_sd_mapping_without_global_mutation():
    import pyte
    model = VtScreen(rows=30, cols=80, enable_history=False)
    assert model.stream.csi["S"] == "scroll_up"
    assert model.stream.csi["T"] == "scroll_down"
    assert model.stream.csi is not pyte.Stream.csi


@pytest.mark.parametrize("with_history", [False, True])
def test_su_sd_work_without_margins_on_normal_screen(with_history):
    model = VtScreen(rows=8, cols=40, enable_history=with_history)
    model.feed("\x1b[2;1Halpha\x1b[3;1Hbeta")
    model.feed("\x1b[1S")
    assert model.display()[0].startswith("alpha")
    assert model.display()[1].startswith("beta")
    model.feed("\x1b[1T")
    assert model.display()[1].startswith("alpha")
    assert model.display()[2].startswith("beta")


def test_csi_commands_are_dispatched_on_alternate_screen():
    model = VtScreen(rows=30, cols=80, enable_history=False)
    model.feed("\x1b[?1049h\x1b[12;29r\x1b[12;1Halpha\x1b[13;1Hbeta")
    model.feed("\x1b[1S")
    assert model.display()[11].startswith("beta")
    assert not model.display()[12].strip()
    model.feed("\x1b[1T")
    assert not model.display()[11].strip()
    assert model.display()[12].startswith("beta")
