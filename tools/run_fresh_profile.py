#!/usr/bin/env python3
"""Start ShellDeck with a disposable, isolated user profile for GUI acceptance tests.

This does not delete or overwrite the real user's ShellDeck settings.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def isolated_environment(base: Path, inherited: dict[str, str] | None = None) -> dict[str, str]:
    """Redirect home and XDG settings to a fresh, private test directory."""
    env = dict(os.environ if inherited is None else inherited)
    base = Path(base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    for name, suffix in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                         ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        path = base / suffix
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    # Qt could otherwise reuse another session's config through APPDATA.
    env["APPDATA"] = str(base / "appdata")
    (base / "appdata").mkdir(parents=True, exist_ok=True)
    env.pop("SHELLDECK_QPROCESS_BASH_BATCH", None)
    return env


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    entrypoint = project / "src" / "main.py"
    if not entrypoint.is_file():
        raise SystemExit(f"ShellDeck main.py fehlt: {entrypoint}")
    with tempfile.TemporaryDirectory(prefix="shelldeck-fresh-profile-") as temporary:
        env = isolated_environment(Path(temporary))
        print("ShellDeck startet mit einem isolierten Testprofil.", flush=True)
        print("Deine normalen ShellDeck-Einstellungen bleiben unverändert.", flush=True)
        # Keep the working directory stable; only the user profile is replaced.
        try:
            return subprocess.call([sys.executable, str(entrypoint)], cwd=project, env=env)
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
