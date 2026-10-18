"""Offline read-only Cargo manifest/lock inventory; NOT a license approval.

No packages are installed, no Cargo subprocess is launched, and no network is used.
The caller must explicitly supply a manifest/lockfile to inspect.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tomllib


def inventory(manifest_path: Path, lock_path: Path) -> dict:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else None
    dependencies = manifest.get("dependencies", {})
    packages = [] if lock is None else [
        {"name": p["name"], "version": p["version"], "source": p.get("source"),
         "checksum": p.get("checksum")}
        for p in lock.get("package", [])
    ]
    # A Cargo.lock entry does not carry the dependency's license. Never infer it.
    return {"manifest": str(manifest_path), "lockfile": str(lock_path),
            "lock_present": lock is not None, "direct_dependencies": sorted(dependencies),
            "locked_packages": packages, "licensing_verified": False,
            "approval": "BLOCKED: audit each resolved package license, artifacts and notices"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = inventory(args.manifest, args.lock)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
