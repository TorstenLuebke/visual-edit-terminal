"""Qt-freie xterm-SGR-Mausprotokolltests."""
import unittest
from shelldeck_mouse_protocol import encode_sgr_mouse


class SgrMouseProtocolTests(unittest.TestCase):
    def test_press_release_and_coordinates(self):
        self.assertEqual(encode_sgr_mouse("press", 0, 0), b"\x1b[<0;1;1M")
        self.assertEqual(encode_sgr_mouse("release", 8, 12, button="right"),
                         b"\x1b[<2;13;9m")

    def test_drag_motion_wheel_and_modifiers(self):
        self.assertEqual(encode_sgr_mouse("drag", 4, 2, button="left"), b"\x1b[<32;3;5M")
        self.assertEqual(encode_sgr_mouse("move", 1, 1), b"\x1b[<35;2;2M")
        self.assertEqual(encode_sgr_mouse("wheel_up", 2, 5), b"\x1b[<64;6;3M")
        self.assertEqual(encode_sgr_mouse("wheel_down", 2, 5), b"\x1b[<65;6;3M")
        self.assertEqual(encode_sgr_mouse("press", 0, 0, button="middle",
                                          shift=True, alt=True, ctrl=True),
                         b"\x1b[<29;1;1M")

    def test_large_positions_use_decimal_without_overflow(self):
        self.assertEqual(encode_sgr_mouse("press", 199, 299), b"\x1b[<0;300;200M")

    def test_rejects_invalid_event_and_negative_coordinate(self):
        for kw in ({"event": "click"}, {"event": "press", "button": "other"},
                   {"event": "press", "row": -1}):
            values = dict(event="press", row=0, col=0)
            values.update(kw)
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                encode_sgr_mouse(**values)


if __name__ == "__main__":
    unittest.main()
