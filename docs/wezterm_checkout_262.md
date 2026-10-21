# Patch 262: upstream provenance

The inspector examines a **user-provided existing checkout**, without network access or mutations.
It reports HEAD, Cargo.lock SHA-256 and suspicious checkout conditions. It does not
establish the origin's authenticity, full dependency provenance, license acceptability,
or approval for binary distribution. Do not copy values to the candidate manifest
without validating the fetched source and the entire transitive/native dependency tree.

`PYTHONPATH=src python src/shelldeck_wezterm_checkout_262.py --checkout /path/to/wezterm`
