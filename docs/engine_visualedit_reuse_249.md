# ShellDeck: VisualEdit reuse audit (experimental architecture only)

This audit compares the VisualEdit source archive `VisualEdit_Quellcode_20261018-183416.zip`
with ShellDeck's engine architecture after patch 248. It authorizes **no copy of
third-party components** and does not alter the production engine.

| VisualEdit source | Candidate for ShellDeck | Decision |
|---|---|---|
| `core/editor/work_scheduler.py` (`EditorWorkScheduler`) | Coalesce redundant UI repaint requests | Transfer the idea, **not** the editor-specific QObject implementation. Never drop/reorder PTY bytes. |
| `core/editor/large_file_policy.py` | Bound expensive analysis of large transcripts | Adapt policies separately; no automatic truncation of terminal data. |
| `core/editor/analysis_cache.py` | Cache expensive derived read-only data | Cache by immutable snapshot/revision, not by viewport coordinates. |
| `ui/terminal_widget.py` | QProcess transcript and Qt text selection | Preserve the existing QProcess view. `QTextCursor` offsets do **not** index VT cells. |
| `ui/shelldeck_terminal_adapter.py` | Existing cross-app ShellDeck integration | Audit API compatibility before consolidating; no blind module replacement. |
| `core/theme/manager.py` | Consistent visual settings | Reuse design tokens only after schema and license review. |

## Boundaries

* Raw PTY/ConPTY input must always reach the parser in order, exactly once.
* A repaint request may be merged with another; an input event may not.
* Terminal selection must identify screen generation, stable logical row, and
  cell columns rather than physical Qt pixels.
* Alternate screen changes invalidate selections belonging to the old screen.
* Resize/reflow requires the engine to publish row-identity mappings; absent
  such a mapping, the client must invalidate or explicitly freeze the selection.
* VisualEdit's source is user-owned but its dependencies/assets still need a
  separate distribution-license review before code is copied into ShellDeck.

These prototypes are intentionally **not wired into production**.
