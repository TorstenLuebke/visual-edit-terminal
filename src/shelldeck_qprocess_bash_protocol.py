"""Bausteine fuer eine spaetere nichtinteraktive, dauerhafte Bash-Pipe.

Dieses Modul wird noch nicht an die produktive Shell angeschlossen. Es
liefert einen eindeutigen Befehlsabschluss, ohne auf den Prompt zu vertrauen.
"""

import re
import secrets


_FRAME_RE = re.compile(r"\x1eSHELLDECK_DONE_([0-9a-f]{32}):(-?[0-9]+)\x1f")


def new_completion_token():
    """Erzeuge fuer jede Sitzung ein nicht vorhersagbares Token."""
    return secrets.token_hex(16)


def wrap_bash_command(command, token):
    """Sende einen Befehl und einen eindeutigen Statusabschluss.

    Nicht bei Programmen mit eigener stdin-Interaktion verwenden. Die GUI
    muss vorher wissen, dass der Befehl fuer diese Methode geeignet ist.
    """
    if not re.fullmatch(r"[0-9a-f]{32}", str(token)):
        raise ValueError("Ungueltiges Bash-Sitzungstoken")
    command = str(command)
    if not command.strip():
        raise ValueError("Leerer Bash-Befehl")
    # Ein Kommentar am Ende darf den Statusmarker nicht verschlucken.
    # Die Abschlusszeile ist bewusst eine neue Eingabezeile.
    return (command.rstrip("\n") + "\n"
            + "__shelldeck_exit=$?\n"
            + f"printf '\\036SHELLDECK_DONE_{token}:%s\\037' \"$__shelldeck_exit\"\n")


def extract_bash_completions(text, token):
    """Entferne nur gueltige Marker dieser Sitzung aus der Ausgabe.

    Rueckgabe: (sichtbarer_text, exit_codes). Fremde Marker bleiben erhalten.
    """
    if not re.fullmatch(r"[0-9a-f]{32}", str(token)):
        raise ValueError("Ungueltiges Bash-Sitzungstoken")
    results = []

    def replace(match):
        if match.group(1) != token:
            return match.group(0)
        results.append(int(match.group(2)))
        return ""

    return _FRAME_RE.sub(replace, str(text)), results


class BashCompletionDecoder:
    """Zustandsbehafteter Parser fuer beliebig zerlegte QProcess-Textblöcke.

    `feed` liefert sichtbaren Text und Abschlusscodes. Im noch laufenden
    Block wird eine moegliche Marker-Praefixfolge zurueckgehalten.
    """

    def __init__(self, token):
        if not re.fullmatch(r"[0-9a-f]{32}", str(token)):
            raise ValueError("Ungueltiges Bash-Sitzungstoken")
        self.token = token
        self._prefix = f"\x1eSHELLDECK_DONE_{token}:"
        self._pending = ""

    def feed(self, text):
        self._pending += str(text)
        output = []
        statuses = []
        while self._pending:
            start = self._pending.find(self._prefix)
            if start >= 0:
                output.append(self._pending[:start])
                tail = self._pending[start + len(self._prefix):]
                end = tail.find('\x1f')
                if end < 0:
                    # A malformed frame may be printed by an application.
                    # Do not retain arbitrarily many bytes while waiting.
                    if len(tail) > 128:
                        output.append(self._pending[:start + len(self._prefix)])
                        self._pending = tail
                        continue
                    self._pending = self._pending[start:]
                    break
                digits = tail[:end]
                if re.fullmatch(r"-?[0-9]{1,12}", digits):
                    statuses.append(int(digits))
                    self._pending = tail[end + 1:]
                else:
                    output.append(self._pending[start:start + len(self._prefix)])
                    self._pending = tail
                continue
            # Nur ein Suffix, das noch zum Anfang des Markers werden kann,
            # bleibt fuer den naechsten QProcess-Block im Speicher.
            keep = 0
            for length in range(1, min(len(self._pending), len(self._prefix) - 1) + 1):
                if self._pending.endswith(self._prefix[:length]):
                    keep = length
            if keep:
                output.append(self._pending[:-keep])
                self._pending = self._pending[-keep:]
            else:
                output.append(self._pending)
                self._pending = ''
            break
        return ''.join(output), statuses

    @property
    def has_pending_prefix(self):
        """Whether a possible marker is buffered awaiting subsequent bytes."""
        return bool(self._pending)

    def finish(self):
        """Restliche Ausgabe beim Schliessen der Shell nicht verlieren."""
        remaining = self._pending
        self._pending = ''
        return remaining
