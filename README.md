# Ukumog Engine

`ukumog-engine` is the rules-and-search core for Ukumog, an 11x11 arithmetic-pattern placement game.

It ships with:

* exact rule resolution for arithmetic fours and fives
* tactical search and alpha-beta/PVS move selection
* a desktop GUI for local analysis and play
* a JSON bridge for website/backend integration

## Rules

* Players alternate placing one stone on an empty cell.
* A move wins immediately if it creates a valid arithmetic progression of five.
* A move loses immediately if it creates a valid arithmetic progression of four and not five.
* Patterns do not need to be adjacent.

## Quickstart

Requires Python 3.11+.

Install in editable mode:

```powershell
python -m pip install -e .
```

Run the CLI:

```powershell
ukumog --mode human-vs-engine --depth 4 --time 10
```

Launch the GUI:

```powershell
ukumog-gui
```

Compatibility wrappers are still available:

```powershell
python play_cli.py
python play_gui.py
```

## Website Integration

The supported integration surface for web/backend use is the JSON bridge:

```powershell
ukumog-json
```

It reads a JSON request from stdin and writes a JSON response to stdout.

Example:

```powershell
'{"command":"engine_info"}' | ukumog-json
```

Supported commands:

* `engine_info`
* `analyze`
* `play_move`

The full contract and the recommended Git subtree workflow for the website repo are documented in [docs/WEBSITE_INTEGRATION.md](/d:/ukumog-engine/docs/WEBSITE_INTEGRATION.md).

## Project Layout

* [`ukumog_engine`](/d:/ukumog-engine/ukumog_engine) contains the engine package.
* [`ukumog_engine/apps`](/d:/ukumog-engine/ukumog_engine/apps) contains supported app entrypoints.
* [`ukumog_engine/ports`](/d:/ukumog-engine/ukumog_engine/ports) contains the website/backend bridge layer.
* [`dev`](/d:/ukumog-engine/dev) contains developer-only benchmark and tuning tools.
* [`tests`](/d:/ukumog-engine/tests) contains regression coverage.

## Developer Tools

Benchmark and match scripts now live under `dev/`:

```powershell
python -m dev.tools.search_benchmark --depth 6
python -m dev.tools.ml_match_suite --candidate-name Candidate --depth 4
```

Legacy wrapper paths under `tools/` still work, but `dev/` is the canonical location.

## Verification

Run the test suite:

```powershell
python -m pytest -q
```

## Notes

* The engine core is still written around a fixed `11x11` board.
* ML support remains optional and secondary to the search-first engine path.
* Historical development logs remain under [`docs`](/d:/ukumog-engine/docs) and [`docs/archive`](/d:/ukumog-engine/docs/archive).
