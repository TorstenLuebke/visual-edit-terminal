# Patch 264: integration status and test boundaries

Patch 262 audits an offline checkout; Patch 263 defines a fail-closed
process transport; Patch 264 protects the handshake with regression tests.

**NOT DONE:** pin a verified upstream revision, audit transitive licenses,
compile a Rust `wezterm-term` executable, validate protocol compatibility,
compare terminal snapshots, test interactive PTY behavior or approve release.

Before enabling live tests, build a genuine Rust engine with a trusted
checkout and retained Cargo.lock; use `cargo metadata --locked`,
`cargo tree --locked` and a full dependency-license review. The 260 build
gate remains blocking and must not be bypassed. The existing pyte and QProcess
implementations remain unchanged. No performance or functional claims about
WezTerm are supported by these patches.
