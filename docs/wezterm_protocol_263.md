# Patch 263: isolated experimental engine transport

`WezTermProcessAdapter` is a **transport**, not a bundled WezTerm build.
The binary MUST be a genuinely linked `wezterm-term` implementation.
Requests are newline-delimited JSON (`initialize`, `feed`, `resize`, `snapshot`,
`transcript`), with `feed.data_base64` containing raw PTY bytes.
Responses require `{ "ok": true }`; initialization also requires
`{ "engine": "wezterm-term", "ready": true }`.

No binary is provided and the transport is not activated by production ShellDeck.
This process protocol is provisional until verified against a compiled Rust host.
Never select an untrusted executable: it runs with the user's permissions.
