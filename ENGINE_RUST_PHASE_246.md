# ShellDeck Rust transport – Phase 246

This is a Qt-free and dependency-free **transport diagnostic only**, not a VT
engine and not a WezTerm adapter. It does not modify the running ShellDeck app.

Build and test locally (only with an already installed Rust toolchain):

```sh
cd experimental/rust_transport
cargo test --offline
cargo build --release --offline
./target/release/shelldeck-rust-transport-probe --probe
```

The `--analyze` command accepts **raw bytes on stdin** and reports byte count,
ESC count, LF count, and FNV-1a hash as versioned JSON; it does not interpret
terminal sequences. The hash is a transport integrity check, not cryptography.

No crate, model, or platform SDK is downloaded or installed by these patches.
The prospective `wezterm-term` dependency is **not added** until a pinned
revision, cargo lockfile, license inventory and Linux/Windows/macOS build gate
are established. The Cargo package license applies only to original ShellDeck
probe code; it does not assert anything about WezTerm dependencies.
