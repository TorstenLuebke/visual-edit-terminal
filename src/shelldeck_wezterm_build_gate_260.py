"""Build permission guard, not an adapter and not a license approval."""
from __future__ import annotations
import json
from pathlib import Path
from shelldeck_wezterm_revision_259 import inspect_candidate

class WezTermBuildBlocked(RuntimeError):
    pass

def require_build_evidence(manifest_path: str | Path) -> None:
    candidate = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    result = inspect_candidate(candidate)
    if not result["ready_for_manual_review"]:
        raise WezTermBuildBlocked("WezTerm build blocked: " + "; ".join(result["findings"]))
    # Complete inventory alone never establishes legal approval.
    raise WezTermBuildBlocked("WezTerm build blocked: independent legal/build verification outstanding")
