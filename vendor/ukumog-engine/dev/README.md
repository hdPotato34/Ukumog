# Dev Layout

Developer-only scripts now live under `dev/`.

Current tools:

* `python -m dev.tools.search_benchmark --depth 6`
* `python -m dev.tools.ml_match_suite --candidate-name Candidate --depth 4`

Compatibility wrappers remain under `tools/` for older local commands, but `dev/` is the canonical location.
