# GUI Dev Log

Active notes for the desktop GUI layer that now sits alongside the search engine and CLI.

## 2026-04-22 - First Interactive GUI Pass

What landed:

* `play_gui.py` now launches a `tkinter` desktop app with a custom-drawn 11x11 board, mouse input, a move log, and an analysis panel
* the GUI supports `human-vs-engine` and `engine-vs-engine`
* both Black and White now have live-editable engine panels for depth, time, temperature, model path, ML mode, learned weight, device, and symmetry ensemble
* `Analyze` runs a full search on the current position and surfaces score, best move, PV, top root moves, depth, nodes, and basic tactical counts
* engine searches run on a background worker thread so the window stays responsive while the engine thinks

Compatibility decisions:

* the existing `play_cli.py` workflow stays supported; the GUI is additive, not a replacement
* shared engine/controller setup was pulled into `ukumog_engine/app_runtime.py` so CLI and GUI use the same search wiring
* legacy checkpoint loading behavior is preserved because the GUI uses the same evaluator/controller path as the CLI

Intentional v1 limits:

* board size is still fixed at `11x11`
* there is no hard search cancellation yet; when the board is reset mid-search, the in-flight result is discarded after it returns
* the GUI focuses on one interactive game at a time; batch benchmarking remains a CLI workflow

Follow-up ideas:

* cache or prewarm heavy model loads more aggressively when users switch checkpoints often
* add optional automatic current-position re-analysis after each move
* add richer stats panes for search-summary and time-trace data
* revisit board-size configuration only after the core engine, masks, tests, and ML stack are generalized together

## 2026-04-22 - Position Workbench Follow-Up

What changed:

* `human-vs-human` plain-board mode is now the default GUI mode so the board can be used as a position setup surface before analysis
* the right panel now shows a prominent recommendation line and highlights the recommended move on the board after `Analyze`
* move history is now a real timeline with `Start`, `Prev`, `Next`, `End`, plus `Branch Here` for trimming future moves and continuing from an earlier position
* the right-side control surface is now scrollable, and both engine config blocks are collapsible to reduce zoom/layout pressure

Compatibility notes:

* the CLI remains unchanged from a user-workflow perspective; the new behavior is GUI-only
* rewinding in the GUI no longer destroys future moves unless the user explicitly branches or plays a new move from that earlier point
