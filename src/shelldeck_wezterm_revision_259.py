"""Explicit fail-closed build readiness gate; does not download/build code."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

PLATFORMS = frozenset({"linux", "windows", "macos"})

def inspect_candidate(manifest: dict) -> dict:
    issues = []
    if manifest.get("upstream") != "https://github.com/wezterm/wezterm":
        issues.append("unrecognized upstream")
    if manifest.get("crate") != "wezterm-term":
        issues.append("wrong crate")
    sha = manifest.get("revision")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        issues.append("immutable 40-character Git revision missing")
    lock = manifest.get("lockfile_sha256")
    if not isinstance(lock, str) or not re.fullmatch(r"[0-9a-f]{64}", lock):
        issues.append("verified Cargo.lock checksum missing")
    if manifest.get("transitive_license_review_complete") is not True:
        issues.append("transitive license review incomplete")
    if manifest.get("native_and_assets_review_complete") is not True:
        issues.append("native/build-script/asset review incomplete")
    platforms = manifest.get("target_platforms_reviewed")
    if not isinstance(platforms, list) or set(platforms) != PLATFORMS:
        issues.append("three-platform review incomplete")
    return {"ready_for_manual_review": not issues, "distribution_approved": False,
            "findings": issues}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = inspect_candidate(json.loads(args.manifest.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ready_for_manual_review"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
