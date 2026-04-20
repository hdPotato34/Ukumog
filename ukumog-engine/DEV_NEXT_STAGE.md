# Ukumog Engine Stage 7 Tracker

This file is the active engineering log for Stage 7. It replaces the earlier draft spec with a working tracker so implementation progress, measurement notes, and next tickets stay in one place.

## Stage 7 direction

Goal: push the engine toward a more Stockfish-style hybrid.

Principles:

* keep exact tactical logic and alpha-beta / PVS as the core
* spend effort on speed per node before expensive ML usage
* use ML first for quiet-node ordering, not tactical override
* make every change measurable under equal wall-clock time

## Current status

Overall status: underway

Completed or materially started:

* `WP-A` instrumentation baseline: done
* `WP-B` incremental tactical bookkeeping: complete
* `WP-C` mask-state lookup eval: complete
* `WP-D` quiet-node ML gating: groundwork started through node classification stats
* `WP-E` policy-prior-first ML integration: baseline already present, now instrumented
* `WP-F` dataset refactor: not started
* `WP-G` auxiliary tactical heads: not started
* `WP-H` accumulator-style evaluator prototype: not started

## Latest dev note

Date: 2026-04-19

Implemented:

* added `ukumog_engine.incremental.IncrementalState`
* added `IncrementalTacticalSummary` as the incremental tactical-query surface
* added reversible per-mask bookkeeping for all 4-masks and 5-masks:
  * black occupancy counts
  * white occupancy counts
  * ternary state ids
  * stack-friendly `make_move()` / `unmake_move()` via `UndoToken`
* added exact incremental queries for:
  * `classify_move()`
  * `move_result()`
  * `is_win_now()`
  * `is_poison()`
  * `winning_moves()`
  * `poison_moves()`
  * `has_immediate_win()`
* added parity tests against the existing rule engine for:
  * make/unmake reversibility
  * move classification
  * immediate winning move detection for both sides
  * poison move extraction
* threaded incremental state through recursive search:
  * one root `IncrementalState` is built per search
  * negamax and quiescence now use make/unmake around child search
  * child move results now come from incremental queries instead of full rule recomputation
* finished the remaining WP-B tactical queries in incremental form:
  * ordered candidate generation
  * future winning continuations from a move
  * opponent winning replies after a move
  * forced blocks
  * safe threats
  * double threats
  * full incremental tactical summary generation
* `analyze_tactics()` now delegates fully to incremental tactical summary generation when an incremental state is available
* added a search regression test that checks recursive search does not mutate the root position
* added parity tests showing incremental tactical summaries match the legacy tactical analyzer on random positions

Earlier in Stage 7:

* expanded `SearchStats` so searches now report:
  * TT probes, hits, and TT cutoffs
  * fail-high / fail-low counts
  * tactical quiescence entries
  * average legal move count and searched move count
  * average branching factor
  * immediate-win, safe-threat, double-threat, and forced-block node counts
  * tactical cache probes and hit rate
  * proof-solver activation count
  * model-call counts bucketed by:
    * root
    * PV quiet
    * non-PV quiet
    * tactical
    * quiescence
  * model wall time, mean latency, and share of total search time
  * policy-prior reorder rank tracking
* added `SearchStats.to_dict()` and `SearchStats.format_summary()`
* added `SearchResult.to_dict()` and `SearchResult.format_summary()`
* added CLI support for:
  * `--search-summary` for human-readable per-search instrumentation
  * `--stats-jsonl <path>` for machine-readable JSONL logging during play
  * `--time-trace` for per-move and cumulative timing breakdowns across:
    * model inference
    * tactical analysis
    * evaluation
    * move ordering
    * quiescence
    * proof search
* optimized incremental tactical summary generation so opponent winning replies are derived directly from winning-mask overlap, instead of doing make/unmake plus full immediate-win recomputation for every safe move
* started WP-C with a live lookup-eval layer:
  * added `eval_lookup.py`
  * precomputed `3^4` and `3^5` mask-state tables
  * incremental state now maintains reversible lookup score sums under make/unmake
  * search evaluation now consumes the lookup-backed incremental score instead of rescanning masks every node
  * opponent-side tactical snapshots used by eval and policy ordering now reuse the same incremental state instead of falling back to fresh whole-position tactical analysis
  * search now caches black-side and white-side tactical snapshots together per occupied board, so paired eval/order requests can reuse one shared tactical computation
  * incremental tactical summaries for both colors are now built together in one paired pass when search needs both sides on the same occupied board
* added parity tests showing the lookup score matches the old brute mask-scan heuristic
* tightened proof-solver activation so it now prefers only narrow, solver-friendly tactical branches:
  * always probe on double threats
  * probe on forced-block cases only when the defensive set is small
  * skip broad safe-threat probes inside quiescence
  * track proof-solver skips in search stats
* tightened quiescence so non-PV "soft safe-threat" nodes can now stop early when:
  * there is no opponent immediate win to answer
  * there is no double threat present
  * the safe-threat set is broad or the safe-move set is wide
  * the stand-pat score is still well below alpha
* added `quiescence_soft_skip_nodes` to the search stats for traceability
* added tests for the new search instrumentation and JSONL logging path

Why this matters:

* WP-B now covers both search recursion and tactical classification on top of reversible per-mask state
* this is the data-layer prerequisite for WP-C lookup-table eval work
* WP-C has now reduced static-eval cost to a negligible runtime share in match traces, which is enough to call the current lookup-eval objective complete
* the instrumentation baseline remains in place to measure the payoff once search uses the new state
* CLI timing traces now make it easier to tell whether a change is hidden by model inference cost, Python overhead, or remaining tactical work
* because inference cost is still negligible in match traces, improving the learned evaluator remains a good medium-term strength target as long as tactical correctness stays search-led

## Immediate queue

Recommended next order:

1. keep reducing the tactical and quiescence buckets through selectivity and lighter tactical views
2. use the negligible ML runtime budget to improve the learned evaluator without letting it override exact tactics
3. refactor dataset generation toward quiet/disagreement-heavy positions
4. add auxiliary tactical targets once the dataset split is in place
5. benchmark gated ML configurations in equal-time matches

## Work packages

### WP-A: Instrumentation and profiling

Status: baseline complete

Done:

* richer search, tactical, and ML counters
* human-readable search summaries
* structured JSON-ready search summaries
* CLI JSONL logging for batch experiments

Still worth adding:

* CSV exporter for sweep-style experiments
* match-level aggregate summaries in addition to per-search logs
* dedicated profiling scripts under `tools/`

### WP-B: Incremental tactical bookkeeping

Status: complete

Built so far:

* indexed mask metadata cached from `MaskTables`
* reversible per-mask 4/5 occupancy counts
* reversible ternary state ids
* exact incremental move classification
* exact incremental immediate-win and poison queries
* recursive search and quiescence now use incremental make/unmake
* tactical analysis uses incremental tactical summary generation when an incremental state is available
* parity tests cover move classification, winning moves, tactical summaries, and search-side make/unmake stability

Deliverable achieved:

* reversible per-mask tactical bookkeeping is live and search-visible

Acceptance target:

* exact classification parity with current logic
* lower quiescence cost
* deeper search at equal time

### WP-C: Mask-state lookup evaluation

Status: complete

Built so far:

* precomputed lookup tables for all 4-mask and 5-mask ternary states
* reversible incremental aggregate lookup score maintenance in `IncrementalState`
* search eval integration using the lookup-backed mask score instead of repeated bit-count scans
* parity tests against the legacy mask-scan heuristic
* opponent-side eval/order tactical snapshots reuse incremental state
* paired tactical snapshot caching per occupied board

Acceptance result:

* lookup-based eval is live
* incremental lookup contributions stay reversible under make/unmake
* match traces show the `eval` bucket is now negligible compared with the remaining tactical work

Next:

* move to the next objective instead of over-investing in eval micro-optimizations
* focus on the remaining dominant buckets: tactics, quiescence, and proof/tactical selectivity

Target:

* precompute local contributions for all `3^4` and `3^5` mask states
* convert evaluation from repeated mask scanning to lookup aggregation

### WP-D: Quiet-node ML gating

Status: groundwork started

Now available:

* search already records whether model calls are hitting root, quiet PV, quiet non-PV, tactical, or quiescence contexts

Next:

* use the same classification to hard-gate model inference away from tactical nodes

### WP-E: Policy-prior-first ML integration

Status: baseline present, needs measurement

Current focus:

* evaluate whether the existing learned prior is helping root and quiet-node ordering
* use the new reorder-rank stats plus equal-time matches to decide whether the prior should stay on by default

### WP-F: Dataset refactor

Status: not started

Desired buckets:

* quiet positions
* shallow vs deeper disagreement positions
* handcrafted-eval disagreement positions
* tactical auxiliary positions

Near-term training spec:

* first baseline dataset:
  * self-play with `play_depth=3`
  * label with `label_depth=5` or a small move-time budget if depth becomes too slow
  * keep symmetry augmentation on
  * cap the first run to a size that trains in hours, not days
* first baseline model run:
  * keep the current policy/value net
  * train with the existing defaults first before changing architecture
  * compare top-1 policy agreement and equal-time match impact before tuning hyperparameters aggressively
* acceptance bar:
  * no tactical regression in engine matches
  * neutral-or-better equal-time strength with root/PV-gated usage

### WP-G: Auxiliary tactical heads

Status: not started

Desired extra targets:

* immediate-win map
* poison map
* forced-block map
* safe-threat map
* double-threat map
* safe-move mask

### WP-H: Accumulator-style evaluator prototype

Status: not started

Target:

* small CPU-friendly model over compact mask-derived features
* eventually make the feature accumulator incremental

## How to use the new instrumentation

CLI examples:

```bash
python play_cli.py --mode engine-vs-engine --depth 4 --time 0.5 --search-summary
python play_cli.py --mode engine-vs-engine --depth 4 --time 0.5 --stats-jsonl logs/search_runs.jsonl
```

Expected use:

* use `--search-summary` while tuning locally
* use `--stats-jsonl` when collecting a batch of comparable runs

## Training Run Spec

Use this as the next clean ML baseline once the current tactical/selectivity pass stabilizes.

### Dataset generation

Example:

```bash
python -m ukumog_engine.ml.generate_data ^
  --games 400 ^
  --play-depth 3 ^
  --label-depth 5 ^
  --play-time-ms 300 ^
  --label-time-ms 1500 ^
  --sample-every 2 ^
  --max-positions 20000 ^
  --output data/phase7_baseline.npz
```

Why this baseline:

* deep enough to produce useful labels
* small enough to iterate quickly
* aligned with the current engine, which is still search-first and tactic-heavy

### Training

Example:

```bash
python -m ukumog_engine.ml.train ^
  --data data/phase7_baseline.npz ^
  --output checkpoints/phase7_baseline.pt ^
  --epochs 12 ^
  --batch-size 128 ^
  --learning-rate 3e-4 ^
  --channels 64 ^
  --blocks 6
```

### Evaluation protocol

Check in this order:

1. policy accuracy / validation loss
2. root-policy-only equal-time matches
3. root/PV-gated equal-time matches
4. only then consider broader ML usage

## Benchmark rule

Do not accept Stage 7 search or ML changes on depth alone.

Primary decision rule:

* equal wall-clock match results first
* instrumentation counters second
* offline loss or training metrics third

## Dev log

### 2026-04-19

* stage tracker rewritten into an active implementation log
* instrumentation baseline landed in engine search and CLI
* reversible incremental mask state landed with make/unmake, exact move classification, and parity tests
* recursive search and quiescence now run on the incremental state via make/unmake
* incremental tactical summaries now cover forced blocks, safe threats, double threats, and reply maps
* lookup-table mask evaluation is now live and incrementally maintained under make/unmake
* WP-C lookup eval is considered complete for this stage; the next wins are tactical rather than evaluative
