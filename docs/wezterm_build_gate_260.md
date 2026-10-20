# Patch 260 — WezTerm build/integration gate

The requested **compiled** `wezterm-term` Rust adapter is NOT included:
this source archive contains no vetted upstream commit, dependency lockfile,
full license evidence or checked build. Claiming the adapter builds or works
would be misleading. This patch instead adds an explicit guard that can be
used before an eventual isolated build. It never invokes the network or Cargo.

Required evidence: immutable upstream revision, exact lockfile hash, completed
transitive and native/asset reviews, and review on each target platform.
The inspected `wezterm-term` upstream crate's `0.1.0` package version is not
itself an immutable version of the Git workspace.

Next build step (only after the gate is satisfied): create a separate Cargo
project pinned to the reviewed WezTerm commit and its workspace crates;
verify `cargo build --locked` and a subprocess protocol with actual input,
resize and snapshot operations. Do not replace pyte until parity is proven.
