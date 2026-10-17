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
    # Guard both the previous status and eval from `errexit`, while leaving
    # Bash's actual previous $? visible inside the user's evaluated command.
    # In an `if` test Bash does not terminate the persistent interpreter for
    # a nonzero status, so the completion frame can always be emitted.
    evaluation = (f"if eval {quoted} </dev/null; then\n"
                  "    __shelldeck_batch_rc=0\n"
                  "else\n"
                  "    __shelldeck_batch_rc=$?\n"
                  "fi\n")
    return ("if (exit \"${__shelldeck_batch_rc:-0}\"); then\n"
            + evaluation
            + "else\n"
            + evaluation
            + "fi\n"
            + f"printf '\\036SHELLDECK_DONE_{token}:%s\\037' \"$__shelldeck_batch_rc\"\n")



def batch_supports_interactive_stdin():
    """Interactive stdin cannot share the command transport pipe."""
    return False


def default_batch_mode(platform=None):
    """Default for *new* installs; never used to override stored choices."""
    import sys
    platform = sys.platform if platform is None else platform
    return "classic" if platform == "win32" else "batch"


def batch_mode_from_settings(settings, platform=None):
    """A persisted choice wins; missing/invalid settings use the platform default.

    Passing a mapping rather than its .get() value distinguishes a fresh
    installation from the explicitly saved legacy selection.
    """
    value = settings.get("qprocess_bash_mode") if isinstance(settings, dict) else None
    return value if value in ("batch", "classic") else default_batch_mode(platform)


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
