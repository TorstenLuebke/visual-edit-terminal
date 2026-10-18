# ShellDeck Core: separate Rust logical-line experiment

`experimental/shelldeck_core` is a stand-alone Rust **data-model prototype**.
It does not parse VT, does not replace pyte, and does not implement terminal
cell-width semantics. No executable GUI, PTY/ConPTY bridge or WezTerm dependency
is introduced by this stage.

Design invariant: stable logical-line IDs and character offsets remain unchanged
when the viewport gets narrower or wider. Eviction invalidates old anchors.
`layout(columns)` returns transient display segments, never mutating logical
text. This prevents the specific horizontal-tail loss of a text store, but does
NOT yet solve terminal reflow for cursor-addressable lines or complex glyphs.

From the project root, after Rust is installed by the user's choice:

    cargo test --manifest-path experimental/shelldeck_core/Cargo.toml --offline

No Cargo installation, download or build occurs automatically. Further stages
must introduce grapheme and display-cell handling and strict alternate-screen
and terminal-control semantics before this could serve as a terminal engine.
