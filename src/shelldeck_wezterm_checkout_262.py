"""Verify an existing local upstream checkout; never fetch or alter it.

Usage: python src/shelldeck_wezterm_checkout_262.py --checkout PATH
The command deliberately does NOT grant license or distribution approval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def inspect_checkout(path: str | Path) -> dict:
    root = Path(path).expanduser().resolve()
    issues = []
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.strip()
    if not root.is_dir():
        return {"valid": False, "issues": ["checkout directory does not exist"], "revision": None}
    try:
        toplevel = Path(git("rev-parse", "--show-toplevel")).resolve()
        if toplevel != root:
            issues.append("path must be the Git working tree root")
        revision = git("rev-parse", "HEAD")
        if git("status", "--porcelain", "--untracked-files=no"):
            issues.append("tracked working tree changes detected")
        remotes = git("remote", "-v")
        if "github.com/wezterm/wezterm" not in remotes:
            issues.append("WezTerm upstream remote not identified; verify origin manually")
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"valid": False, "issues": ["git inspection failed: " + str(exc)], "revision": None}
    lock = root / "Cargo.lock"
    manifest = root / "term" / "Cargo.toml"
    if not lock.is_file():
        issues.append("upstream Cargo.lock missing")
    if not manifest.is_file():
        issues.append("term/Cargo.toml missing")
    elif 'name = "wezterm-term"' not in manifest.read_text(encoding="utf-8"):
        issues.append("wezterm-term crate not found in term/Cargo.toml")
    return {"valid": not issues, "issues": issues, "revision": revision,
            "lockfile_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None,
            "checkout": str(root), "license_approved": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args()
    report = inspect_checkout(args.checkout)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
