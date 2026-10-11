"""Einheitliche, abgeleitete Sitzungszustände für beide Terminal-Engines.

Die Daten sind Snapshots, keine zweite veränderliche Zustandsmaschine.
Prozess-/Befehlsflags bleiben bei den bestehenden ShellDeck-Verantwortlichen.
Keine Qt-Abhängigkeit, daher auch auf Windows/macOS direkt testbar.
"""
from dataclasses import dataclass
from enum import Enum


class SessionPhase(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    INTERACTIVE = "interactive"


@dataclass(frozen=True)
class SessionSnapshot:
    phase: SessionPhase
    shell_running: bool
    command_pending: bool
    interactive: bool
    engine: str
    generation: int

    @property
    def busy(self) -> bool:
        """True, solange die Shell noch einen Befehl/Antwort verarbeitet."""
        return self.phase in (SessionPhase.RUNNING, SessionPhase.INTERACTIVE)


def evaluate_session_state(*, process_state, running_state, starting_state,
                           command_pending=False, interactive=False,
                           closed=False, engine="", generation=0) -> SessionSnapshot:
    """Liefert einen stabilen Zustand ohne Prozesse oder Qt zu beeinflussen.

    Der Prozesszustand kommt sowohl von QProcess als auch vom PTY-Adapter.
    Ein beendeter Prozess kann niemals RUNNING/INTERACTIVE sein, auch wenn
    verzögerte GUI-Flags noch auf einen früheren Befehl zeigen.
    """
    alive = not closed and process_state == running_state
    pending = bool(command_pending) if alive else False
    asking = bool(interactive) if alive else False
    if not alive:
        phase = SessionPhase.STARTING if not closed and process_state == starting_state else SessionPhase.STOPPED
    elif asking:
        phase = SessionPhase.INTERACTIVE
    elif pending:
        phase = SessionPhase.RUNNING
    else:
        phase = SessionPhase.READY
    return SessionSnapshot(phase=phase, shell_running=alive,
                           command_pending=pending, interactive=asking,
                           engine=str(engine or ""), generation=int(generation))
