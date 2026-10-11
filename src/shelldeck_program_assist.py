"""Sichere, rein lesende Erkennung lokaler Vordergrundprogramme im POSIX-PTY.

Ein angezeigter Hilfeknopf darf keinen Prozess in einem anderen Tab treffen.
Darum wird die aktive Prozessgruppe beim Klick erneut verglichen. Wenn ein
Backend keine vertrauenswuerdige Vordergrundinformation liefert (z.B. ConPTY),
bleibt die Programmautomatik vorerst deaktiviert.
"""

from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
import subprocess
import sys


@dataclass(frozen=True)
class ProgramGuide:
    name: str
    label: str
    exit_bytes: bytes
    help_text: str
    primary_label: str = "Beenden"


GUIDES = {
    "vim": ProgramGuide(
        "vim", "Vim / Vi / Neovim", b"\x1b:q\r",
        "Navigation: Pfeiltasten oder h/j/k/l.\n"
        "Text eingeben: i.\n"
        "Eingabemodus verlassen: Esc.\n"
        "Speichern: :w + Enter.\n"
        "Normal beenden: Esc, :q + Enter (sicher, bei Aenderungen bleibt Vim offen).\n"
        "Speichern und beenden: Esc, :wq + Enter.\n"
        "Ohne Speichern beenden: Esc, :q! + Enter (Datenverlust moeglich).",
    ),
    "nano": ProgramGuide(
        "nano", "Nano", b"\x18",  # Ctrl+X; Nano fragt bei Aenderungen nach
        "Beenden: Strg+X; bei ungespeicherten Aenderungen fragt Nano nach.\n"
        "Speichern: Strg+O, Enter.\nSuchen: Strg+W.\nHilfe: Strg+G."
    ),
    "htop": ProgramGuide("htop", "Htop", b"q", "Beenden: q oder F10.\nSortieren: F6.\nSuchen: F3.\nHilfe: F1."),
    "top": ProgramGuide("top", "Top", b"q", "Beenden: q.\nHilfe: h.\nAktualisierung erzwingen: Leertaste."),
    "less": ProgramGuide("less", "Less", b"q", "Beenden: q.\nSuche: /Begriff + Enter.\nWeiter: n.\nBlaettern: Leertaste / b."),
    "more": ProgramGuide("more", "More", b"q", "Beenden: q.\nWeiter: Leertaste.\nZeile: Enter."),
    "man": ProgramGuide("man", "Man", b"q", "Beenden: q (bei Standard-Pager less).\nSuche: /Begriff + Enter.\nWeiter: n."),
    "watch": ProgramGuide("watch", "Watch", b"\x03", "Beenden: Strg+C.\nIntervall einstellen: watch -n 2 BEFEHL."),
    "btop": ProgramGuide("btop", "Btop", b"q",
        "Beenden: q.\nMenue/Hilfe: Esc.\nProzesse: Pfeiltasten."),
    "micro": ProgramGuide("micro", "Micro", b"\x11",  # Strg+Q
        "Beenden: Strg+Q (bei ungespeicherten Aenderungen Rueckfrage beachten).\n"
        "Speichern: Strg+S.\nSuchen: Strg+F.\nHilfe: Strg+G."),
    "mc": ProgramGuide("mc", "Midnight Commander", b"\x1b[21~",  # F10
        "Beenden: F10.\nMenue: F9.\nDatei anzeigen: F3.\nDatei bearbeiten: F4."),
    # Detach beendet weder tmux/screen noch die darin laufenden Sitzungen.
    # Nur Standard-Prefix; bei Benutzerkonfiguration bitte manuell trennen.
    "tmux": ProgramGuide("tmux", "Tmux", b"\x02d",  # Strg+B, danach d
        "Trennen: Strg+B, dann d (Standard-Prefix).\n"
        "Wieder verbinden: tmux attach.\nNeues Fenster: Strg+B, dann c.\n"
        "Bei geaendertem Prefix die Tasten bitte manuell ausfuehren.\n"
        "Programme innerhalb von tmux werden nicht separat erkannt.",
        primary_label="Trennen"),
    "screen": ProgramGuide("screen", "GNU Screen", b"\x01d",  # Strg+A, danach d
        "Trennen: Strg+A, dann d (Standard-Prefix).\n"
        "Wieder verbinden: screen -r.\nNeues Fenster: Strg+A, dann c.\n"
        "Bei geaendertem Prefix die Tasten bitte manuell ausfuehren.\n"
        "Programme innerhalb von screen werden nicht separat erkannt.",
        primary_label="Trennen"),
}

ALIASES = {
    "vi": "vim", "vim": "vim", "vim.basic": "vim", "vim.tiny": "vim",
    "view": "vim", "nvim": "vim", "rvim": "vim", "vimdiff": "vim",
    "nano": "nano", "htop": "htop", "top": "top", "less": "less",
    "more": "more", "man": "man", "watch": "watch",
    "btop": "btop", "micro": "micro", "mc": "mc", "mcedit": "mc",
    "mview": "mc", "tmux": "tmux", "tmux: client": "tmux",
    "screen": "screen", "screen-4.09.01": "screen",
}


def canonical_program(executable):
    """Nur bekannte, exakt benannte Programme anzeigen (keine Substring-Heuristik)."""
    name = str(executable or "").strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return ALIASES.get(name)


def _process_name(pid):
    """Lokal nachschlagen; niemals die gesamte Prozessliste oder Shell auswerten."""
    if sys.platform.startswith("linux"):
        try:
            return Path(f"/proc/{int(pid)}/comm").read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["ps", "-p", str(int(pid)), "-o", "comm="],
                capture_output=True, text=True, timeout=0.15, check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return ""
    return ""


def foreground_guide(pty_child):
    """Liefert (Programmschluessel, PGID) nur fuer das echte Vordergrund-Job.

    Ein Shell-Prozess, unbekannte Namen oder fehlende TTY-Information liefern
    None. Dies verhindert Aktionen auf veraltete oder falsche Tabs.
    """
    if os.name != "posix" or pty_child is None:
        return None
    fd = getattr(pty_child, "fd", -1)
    pid = getattr(pty_child, "pid", None)
    try:
        if not isinstance(fd, int) or fd < 0 or pid is None:
            return None
        foreground_group = os.tcgetpgrp(fd)
        shell_group = os.getpgid(int(pid))
        if foreground_group <= 0 or foreground_group == shell_group:
            return None
    except (OSError, ValueError, TypeError):
        return None
    name = canonical_program(_process_name(foreground_group))
    return (name, foreground_group) if name is not None else None


# Optionale Erweiterungen als reine Daten ohne Python-Plugincode.
# Keine Automatik fuer fremde Shells, SSH, Systemprogramme oder integrierte Hilfen.
_PROGRAM_NAME = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,63}$")
_PROTECTED = frozenset({
    "bash", "sh", "dash", "zsh", "fish", "ksh", "csh", "tcsh", "pwsh",
    "powershell", "cmd", "ssh", "sudo", "su", "doas", "python", "python3",
    "node", "git", "login", "systemd", "screen", "tmux",
})


def user_guides_path():
    """Konfiguration ist unabhaengig von Arbeitsverzeichnis und Terminal-Tabs."""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "ShellDeck" / "program_guides.json"


def encode_guide_keys(keys):
    """Erlaubte Tastenkombinationen in ein PTY-Bytekommando umwandeln.

    Keine Shellbefehle oder freien ANSI-Payloads; max. 12 Tasten.
    """
    if not isinstance(keys, list) or not 1 <= len(keys) <= 12:
        raise ValueError("keys: 1 bis 12 Tasten erwartet")
    special = {"ESC": b"\x1b", "ENTER": b"\r", "TAB": b"\t",
               "SPACE": b" ", "BACKSPACE": b"\x7f"}
    fkeys = {i: (b"\x1bO" + bytes([ord("P") + i - 1])) for i in range(1, 5)}
    fkeys.update({5: b"\x1b[15~", 6: b"\x1b[17~", 7: b"\x1b[18~",
                  8: b"\x1b[19~", 9: b"\x1b[20~", 10: b"\x1b[21~",
                  11: b"\x1b[23~", 12: b"\x1b[24~"})
    encoded = []
    for key in keys:
        if not isinstance(key, str):
            raise ValueError("key muss ein String sein")
        upper = key.upper()
        if upper in special:
            encoded.append(special[upper])
        elif re.fullmatch(r"F(?:[1-9]|1[0-2])", upper):
            encoded.append(fkeys[int(upper[1:])])
        elif len(upper) == 6 and upper.startswith("CTRL+") and "A" <= upper[-1] <= "Z":
            encoded.append(bytes([ord(upper[-1]) - ord("A") + 1]))
        elif len(key) == 1 and 0x21 <= ord(key) <= 0x7e:
            encoded.append(key.encode("ascii"))
        else:
            raise ValueError(f"nicht zugelassene Taste: {key!r}")
    return b"".join(encoded)


def load_user_guides(path=None):
    """Liest ein optionales Programmregister (Guides, Aliase, Fehlermeldungen).

    Fehlerhafte oder mehrfach vergebene Eintraege werden uebersprungen.
    Integrierte Guides haben Vorrang und bleiben unveraendert.
    """
    file_path = Path(path) if path is not None else user_guides_path()
    if not file_path.is_file():
        return {}, {}, []
    try:
        if file_path.stat().st_size > 65536:
            raise ValueError("Konfigurationsdatei zu gross (max. 64 KiB)")
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        entries = payload["programs"]
        if not isinstance(entries, list) or len(entries) > 64:
            raise ValueError("programs muss eine Liste mit hoechstens 64 Eintraegen sein")
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        return {}, {}, [str(exc)]
    guides, aliases, diagnostics = {}, {}, []
    for index, item in enumerate(entries):
        try:
            if not isinstance(item, dict):
                raise ValueError("Eintrag muss ein Objekt sein")
            name, label, hint = item["name"], item["label"], item["help_text"]
            title, raw_aliases = item.get("button_label", "Beenden"), item.get("aliases", [])
            if (not isinstance(name, str) or not _PROGRAM_NAME.fullmatch(name)
                    or name in _PROTECTED or name in ALIASES or name in aliases):
                raise ValueError("ungueltiger, geschuetzter oder belegter Programmname")
            if (not isinstance(label, str) or not 1 <= len(label) <= 72
                    or not isinstance(hint, str) or not 1 <= len(hint) <= 4000
                    or title not in ("Beenden", "Trennen")
                    or not isinstance(raw_aliases, list) or len(raw_aliases) > 12):
                raise ValueError("ungueltige Metadaten")
            names = [name, *raw_aliases]
            if (len(set(names)) != len(names) or any(
                    not isinstance(alias, str) or not _PROGRAM_NAME.fullmatch(alias)
                    or alias in _PROTECTED or alias in ALIASES or alias in aliases
                    for alias in names)):
                raise ValueError("ungueltiger, geschuetzter oder doppelter Alias")
            raw = encode_guide_keys(item["keys"])
        except (ValueError, KeyError, TypeError) as exc:
            diagnostics.append(f"programs[{index}]: {exc}")
            continue
        guides[name] = ProgramGuide(name, label, raw, hint, primary_label=title)
        aliases.update({alias: name for alias in names})
    return guides, aliases, diagnostics


# Beim Import laden, niemals pro Tab oder je Ausgabe-Chunk erneut lesen.
_extra_guides, _extra_aliases, USER_GUIDE_ERRORS = load_user_guides()
GUIDES.update(_extra_guides)
ALIASES.update(_extra_aliases)
