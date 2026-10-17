"""Opt-in QProcess Bash without job-control: persistent session, no tty.

Every command runs in the same shell via eval but has /dev/null as stdin.
This prevents subprocesses from consuming subsequent control frames from Qt.
Commands requiring interactive stdin belong in the PTY terminal instead.
"""
import shlex
from shelldeck_qprocess_bash_protocol import new_completion_token


def wrap_batch_command(command, token):
    """Build a single shell command with an unambiguous exit marker."""
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise ValueError("Ungueltiger Bash-Befehl")
    # Delegate token validation to existing protocol; never interpolate raw input.
    from shelldeck_qprocess_bash_protocol import BashCompletionDecoder
    BashCompletionDecoder(token)
    quoted = shlex.quote(command)
    return ("(exit \"${__shelldeck_batch_rc:-0}\")\n"
            f"eval {quoted} </dev/null\n"
            "__shelldeck_batch_rc=$?\n"
            f"printf '\\036SHELLDECK_DONE_{token}:%s\\037' \"$__shelldeck_batch_rc\"\n")


def batch_supports_interactive_stdin():
    """Interactive stdin cannot share the command transport pipe."""
    return False


def normalized_batch_mode(value):
    """Only an explicit batch preference enables the experimental path."""
    return "batch" if value == "batch" else "classic"


def batch_for_session(mode, environment=None):
    """A stored GUI preference overrides the opt-in launch variable."""
    if mode is None:
        return batch_requested(environment)
    return normalized_batch_mode(mode) == "batch"


def batch_requested(environment=None):
    import os
    env = os.environ if environment is None else environment
    return env.get('SHELLDECK_QPROCESS_BASH_BATCH') == '1'
