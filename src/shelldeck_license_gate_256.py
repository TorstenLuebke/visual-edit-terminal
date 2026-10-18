"""Fail-closed evidence gate for a future WezTerm integration.

This checks explicit audit evidence, never guesses SPDX licenses from Cargo.lock.
It neither invokes Cargo nor downloads source material.
"""
from __future__ import annotations

import json
from pathlib import Path


def audit(lock_report: dict, evidence: dict) -> dict:
    packages = lock_report.get("locked_packages", [])
    approvals = evidence.get("packages", [])
    index = {(p.get("name"), p.get("version"), p.get("source")): p for p in approvals}
    problems = []
    if not lock_report.get("lock_present"):
        problems.append("Cargo.lock fehlt")
    if not packages:
        problems.append("Keine aufgelösten Pakete im Lockfile")
    for package in packages:
        key = (package.get("name"), package.get("version"), package.get("source"))
        entry = index.get(key)
        if entry is None:
            problems.append(f"Nachweis fehlt: {key[0]} {key[1]}")
        elif not (entry.get("license_expression") and entry.get("license_file_checked") is True
                  and entry.get("redistribution_checked") is True and entry.get("reviewer")):
            problems.append(f"Nachweis unvollständig: {key[0]} {key[1]}")
    unknown = set(index) - {(p.get("name"), p.get("version"), p.get("source")) for p in packages}
    if unknown:
        problems.append("Nachweise enthalten nicht aufgelöste Pakete")
    # A mechanically complete inventory is NOT legal license approval.
    return {"evidence_complete": not problems, "license_approved": False,
            "findings": problems, "manual_legal_review_required": True}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.inventory.read_text(encoding="utf8")),
                   json.loads(args.evidence.read_text(encoding="utf8")))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["evidence_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
