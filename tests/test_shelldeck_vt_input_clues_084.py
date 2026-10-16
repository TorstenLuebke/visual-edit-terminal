from tools.shelldeck_vt_input_clues_084 import analyze


def test_control_counts_are_output_only():
    raw = b"abc\x07\x08\r\n\x1b[10S\x1b[10T\x1b[K\x1b[4X\x1b[12;29r"
    report = analyze(raw)
    assert report["BEL"] == 1
    assert report["BS"] == 1
    assert report["CSI_S"] == report["CSI_T"] == 1
    assert report["CSI_K"] == report["CSI_X"] == report["CSI_r"] == 1
    assert "duplicate" in report["warning"]
    assert "abc" not in str(report)
