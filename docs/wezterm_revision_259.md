# WezTerm dependency decision – Patch 259

Status: **BLOCKED for compiling, packaging, redistribution and production activation**.

Source: https://github.com/wezterm/wezterm/tree/main/term
Upstream crate name: `wezterm-term`; declared crate version in the inspected
`term/Cargo.toml`: `0.1.0`; license declared: MIT.
MIT license text: https://github.com/wezterm/wezterm/blob/main/term/LICENSE.md

**0.1.0 is not a uniquely identified upstream revision.** The package depends
on workspace dependencies and sibling workspace crates. Do not treat the crate
version or moving branch `main` as a reproducible source reference. No source
revision is approved in this patch, because no verified immutable commit SHA,
complete Cargo.lock and redistributed-source audit are available.

Before enabling a WezTerm build, record an immutable full upstream commit SHA,
verify it against the fetched repository, build with `--locked` against a
reviewed lockfile, audit all recursive Cargo dependencies, build scripts,
native libraries and bundled assets, and archive the applicable notice texts.
Check distribution on Linux, Windows and macOS separately. The MIT declaration
of the terminal crate is not a license clearance for its dependencies.

The existing ShellDeck Python application, pyte adapter, QProcess mode and
independent `experimental/shelldeck_core` crate remain untouched.

Verification: `python src/shelldeck_wezterm_revision_259.py --manifest docs/wezterm_candidate_259.json`
A nonzero result is the expected safe outcome until proof is supplied.
