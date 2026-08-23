"""Qt-freie Tastatur-/Paste-Codierung für ein echtes Terminal (ShellDeck).

Wandelt eine abstrakte Tastenbeschreibung (Name + Text + Modifier) in die
Byte-Sequenzen um, die eine Shell/ein TUI-Programm über das PTY erwartet
(xterm-kompatibel). Bewusst ohne Qt, damit die Codierung vollständig und
schnell testbar ist; das Qt-Widget mappt nur QKeyEvent → diese Funktionen.
"""

from __future__ import annotations


# Cursor-/Navigationstasten mit CSI-Endbuchstaben.
_CURSOR_LETTERS = {
    "Up": "A", "Down": "B", "Right": "C", "Left": "D", "Home": "H", "End": "F",
}
# Tasten mit "~"-Codierung und fester Nummer.
_TILDE_NUMBERS = {"Insert": 2, "Delete": 3, "PageUp": 5, "PageDown": 6}
# F1–F4 als SS3-Sequenzen.
_F_SS3 = {"F1": "P", "F2": "Q", "F3": "R", "F4": "S"}
# F5–F12 als "~"-Sequenzen.
_F_TILDE = {"F5": 15, "F6": 17, "F7": 18, "F8": 19,
            "F9": 20, "F10": 21, "F11": 23, "F12": 24}

# Ctrl-Kombinationen für Nicht-Buchstaben.
_CTRL_SYMBOLS = {
    "@": 0, " ": 0, "[": 27, "\\": 28, "]": 29, "^": 30, "_": 31, "?": 127,
}


def modifier_code(ctrl=False, alt=False, shift=False, meta=False) -> int:
    """xterm-Modifier-Code (1 = keiner, 2 = Shift, 3 = Alt, 5 = Ctrl, …)."""
    code = 1
    if shift:
        code += 1
    if alt:
        code += 2
    if ctrl:
        code += 4
    if meta:
        code += 8
    return code


def _encode_text(text: str, ctrl: bool) -> bytes:
    if not text:
        return b""
    if ctrl:
        char = text[0]
        low = char.lower()
        if "a" <= low <= "z":
            return bytes([ord(low) - ord("a") + 1])
        if char in _CTRL_SYMBOLS:
            return bytes([_CTRL_SYMBOLS[char]])
        # Bereits ein Steuerzeichen (manche Plattformen liefern das direkt).
        if len(char) == 1 and ord(char) < 0x20:
            return char.encode("latin-1")
    return text.encode("utf-8", errors="replace")


def encode_key(name: str, text: str = "", *, ctrl=False, alt=False,
               shift=False, meta=False, application_cursor=False) -> bytes:
    """Codiert eine Taste in die an das PTY zu sendenden Bytes.

    name: normalisierter Tastenname ("Up", "F5", "Home", "Enter", "Backspace",
    "Tab", "Backtab", "Escape", "Insert", "Delete", "PageUp", "PageDown") oder
    "" für druckbaren Text (dann zählt ``text``).
    """
    mod = modifier_code(ctrl, alt, shift, meta)
    has_mod = mod > 1

    if name in _CURSOR_LETTERS:
        letter = _CURSOR_LETTERS[name]
        if has_mod:
            return ("\x1b[1;%d%s" % (mod, letter)).encode("ascii")
        if application_cursor:
            return ("\x1bO%s" % letter).encode("ascii")
        return ("\x1b[%s" % letter).encode("ascii")

    if name in _TILDE_NUMBERS:
        num = _TILDE_NUMBERS[name]
        if has_mod:
            return ("\x1b[%d;%d~" % (num, mod)).encode("ascii")
        return ("\x1b[%d~" % num).encode("ascii")

    if name in _F_SS3:
        letter = _F_SS3[name]
        if has_mod:
            return ("\x1b[1;%d%s" % (mod, letter)).encode("ascii")
        return ("\x1bO%s" % letter).encode("ascii")

    if name in _F_TILDE:
        num = _F_TILDE[name]
        if has_mod:
            return ("\x1b[%d;%d~" % (num, mod)).encode("ascii")
        return ("\x1b[%d~" % num).encode("ascii")

    if name in ("Enter", "Return"):
        seq = b"\r"
        return b"\x1b" + seq if alt else seq
    if name == "Backspace":
        seq = b"\x08" if ctrl else b"\x7f"
        return b"\x1b" + seq if alt else seq
    if name == "Tab":
        seq = b"\t"
        return b"\x1b" + seq if alt else seq
    if name == "Backtab":
        return b"\x1b[Z"
    if name == "Escape":
        return b"\x1b"

    # Druckbarer Text bzw. Ctrl-/Alt-Kombination darauf.
    if text:
        data = _encode_text(text, ctrl)
        if alt and data:
            return b"\x1b" + data
        return data
    return b""


def encode_paste(text: str, bracketed: bool = False) -> bytes:
    """Codiert eingefügten Text; optional als Bracketed Paste umschlossen."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", "\r")
    raw = normalized.encode("utf-8", errors="replace")
    if bracketed:
        return b"\x1b[200~" + raw + b"\x1b[201~"
    return raw
