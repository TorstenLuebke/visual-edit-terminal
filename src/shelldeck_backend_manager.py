"""Erkennung und nachträgliche Installation optionaler ShellDeck-Backends."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendPackage:
    package_id: str
    label: str
    reason: str
    program: str
    arguments: tuple[str, ...]


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _windows_packages() -> list[BackendPackage]:
    packages: list[BackendPackage] = []
    winget = shutil.which("winget.exe") or shutil.which("winget")

    # In einer Entwicklungsumgebung kann pywinpty in genau den Interpreter
    # nachinstalliert werden, den ShellDeck verwendet. In einem eingefrorenen
    # EXE-Build muss es dagegen bereits vom Installer mitgeliefert werden.
    if not _has_module("winpty") and not getattr(sys, "frozen", False):
        packages.append(BackendPackage(
            "pywinpty", "ConPTY-Unterstützung (pywinpty)",
            "für interaktive Windows-Terminals",
            sys.executable, ("-m", "pip", "install", "--upgrade", "pywinpty"),
        ))

    if winget and shutil.which("pwsh.exe") is None:
        packages.append(BackendPackage(
            "Microsoft.PowerShell", "PowerShell 7", "modernes PowerShell-Backend",
            winget, ("install", "--id", "Microsoft.PowerShell", "--exact", "--accept-package-agreements", "--accept-source-agreements"),
        ))
    git_bash = any(Path(path).exists() for path in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ))
    if winget and not git_bash:
        packages.append(BackendPackage(
            "Git.Git", "Git Bash", "Bash- und Git-Kompatibilität unter Windows",
            winget, ("install", "--id", "Git.Git", "--exact", "--accept-package-agreements", "--accept-source-agreements"),
        ))
    if winget and shutil.which("wsl.exe") is None:
        packages.append(BackendPackage(
            "Microsoft.WSL", "Windows-Subsystem für Linux", "Linux-Shells unter Windows",
            winget, ("install", "--id", "Microsoft.WSL", "--exact", "--accept-package-agreements", "--accept-source-agreements"),
        ))
    return packages


def _linux_packages() -> list[BackendPackage]:
    packages: list[BackendPackage] = []
    apt = shutil.which("apt-get")
    pkexec = shutil.which("pkexec")
    if not apt or not pkexec:
        return packages
    for executable, package, label in (
        ("zsh", "zsh", "Z Shell"),
        ("fish", "fish", "Fish Shell"),
    ):
        if shutil.which(executable) is None:
            packages.append(BackendPackage(
                package, label, "zusätzliches interaktives Shell-Backend",
                pkexec, (apt, "install", "-y", package),
            ))
    return packages


def missing_backend_packages() -> list[BackendPackage]:
    if sys.platform == "win32":
        return _windows_packages()
    if os.name == "posix":
        return _linux_packages()
    return []


def start_backend_package_install(package: BackendPackage) -> tuple[bool, str]:
    program = str(package.program or "").strip()
    if not program or not Path(program).exists():
        return False, f"Installationsprogramm für {package.label} wurde nicht gefunden."
    try:
        subprocess.Popen(
            [program, *package.arguments],
            close_fds=(sys.platform != "win32"),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0),
        )
    except OSError as exc:
        return False, f"Installation von {package.label} konnte nicht gestartet werden: {exc}"
    return True, f"Installation von {package.label} wurde gestartet."
