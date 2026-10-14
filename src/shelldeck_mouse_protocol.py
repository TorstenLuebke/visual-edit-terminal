"""Qt-freie xterm-SGR-Mauscodierung fuer interaktive Terminalprogramme.

Nur wenn das Gegenprogramm selbst DEC-Mausmodi und SGR (1006) aktiviert,
werden Mausereignisse in PTY-Bytes umgewandelt. Ausserhalb dieser Modi
verwaltet das Terminalwidget die normale Textauswahl und den Scrollback.
"""

from __future__ import annotations


_BUTTONS = {"left": 0, "middle": 1, "right": 2}
_MODIFIERS = {"shift": 4, "alt": 8, "ctrl": 16}


def encode_sgr_mouse(event: str, row: int, col: int, *, button: str = "left",
                     shift: bool = False, alt: bool = False,
                     ctrl: bool = False) -> bytes:
    """Kodiert ein Mausereignis nach XTerm SGR 1006.

    ``row``/``col`` sind nullbasierte Zellen. SGR uebertraegt einsbasierte
    Koordinaten. Gueltige Events: press, release, drag, move, wheel_up,
    wheel_down. Release nutzt den gekennzeichneten Button mit Abschluss 'm'.
    Bei freier Mausbewegung wird die Basis 3 (kein gedrueckter Button) genutzt.
    """
    if event not in {"press", "release", "drag", "move", "wheel_up", "wheel_down"}:
        raise ValueError("Unbekanntes Mausereignis: " + str(event))
    if button not in _BUTTONS:
        raise ValueError("Unbekannte Maustaste: " + str(button))
    if row < 0 or col < 0:
        raise ValueError("Mauskoordinaten muessen nichtnegativ sein")

    code = _BUTTONS[button]
    if event == "move":
        code = 3 + 32
    elif event == "drag":
        code += 32
    elif event == "wheel_up":
        code = 64
    elif event == "wheel_down":
        code = 65
    for name, enabled in (("shift", shift), ("alt", alt), ("ctrl", ctrl)):
        if enabled:
            code += _MODIFIERS[name]
    suffix = "m" if event == "release" else "M"
    return f"\x1b[<{code};{col + 1};{row + 1}{suffix}".encode("ascii")
