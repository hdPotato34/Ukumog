# Ukumog Engine

Search-first engine for an arithmetic-pattern placement game on an 11x11 board. The current codebase is closest to a Stockfish-style hybrid: exact rules, tactical search, alpha-beta/PVS, heavy instrumentation, and only light ML assistance where search can stay in control.

## Overview

Game rules:

* Two players alternate placing one stone on an empty cell.
* A move wins immediately if it creates a valid pattern of five.
* A move loses immediately if it creates a valid pattern of four and not five.
* A pattern is an arithmetic progression on the board; stones do not need to be adjacent.

Repo goal:

* keep the engine search-led and tactically exact
* improve depth and efficiency before spending more complexity on ML
* use ML as a helper for quiet-node evaluation only after it proves value in equal-time matches

## What Works Now

The current repo is not just scaffolding. These parts are implemented and covered by tests:

* exact rule engine with precomputed 4-mask and 5-mask tables
* tactical analysis for immediate wins, poison moves, forced blocks, safe threats, and double threats
* alpha-beta negamax with iterative deepening, PVS, aspiration windows, killer/history ordering, quiet-move caps, and tactical quiescence
* reversible incremental state with make/unmake and lookup-backed mask evaluation
* selective tactical proof solver for sharp positions
* CLI play and engine-vs-engine benchmarking with structured search summaries
* quiet-position self-play data generation, mask-state value training, dataset inspection, and checkpoint loading
* legacy CNN checkpoint loading for comparison runs against older experiments
* regression coverage for rules, tactical motifs, incremental parity, search behavior, and ML plumbing

Current verification:

* `python -m pytest -q` passes: `59 passed`
* representative search summaries show tactics, quiescence, and proof work dominate wall time
* static eval is now a small runtime share, and the primary ML path is now restricted to quiet-node value guidance

## What Is Outdated

These ideas or narratives should stop being treated as active priorities:

* the old phase-by-phase milestone story in the previous dev logs
* Stage 7 work packages that are already complete but still read like live roadmap items
* any suggestion that static evaluation speed is still the main bottleneck
* the previous policy-first board-CNN workflow as a primary direction; it is now legacy comparison-only

The bottleneck has shifted. On real search traces, the expensive buckets are tactical analysis, quiescence, and tactical proof/selectivity. The right next push is deeper and cleaner search, not more eval micro-optimization.

## How To Run

Human vs engine:

```powershell
python play_cli.py --mode human-vs-engine --depth 4 --time 10
```

Engine vs engine with instrumentation:

```powershell
python play_cli.py --mode engine-vs-engine --depth 4 --time 0.5 --search-summary --time-trace
```

Fixed benchmark suite:

```powershell
python tools/search_benchmark.py --depth 6
```

Engine vs engine with a trained checkpoint:

```powershell
python play_cli.py --mode engine-vs-engine --depth 4 --time 0.5 --model checkpoints/quiet_value_v1.pt --ml-mode quiet-value
```

Batch engine evaluation with random seeds and shuffled colors:

```powershell
python play_cli.py --mode engine-vs-engine --games 40 --shuffle-colors --seed 20260419 --seed-step 1 --temperature 0 --black-temperature 0 --white-temperature 0 --black-model checkpoints/quiet_value_v1.pt --white-model checkpoints/phase7_baseline.pt --black-ml-mode quiet-value --white-ml-mode root-policy --depth 4 --time 0.5
```

Generate training data:

```powershell
python -m ukumog_engine.ml.generate_data --games 400 --play-depth 2 --label-depth 4 --play-time-ms 0 --label-time-ms 0 --sample-every 1 --sample-start-ply 0 --samples-per-game 4 --target-new-samples 300 --explore-plies 10 --explore-top-k 6 --diversify-opening-plies 8 --diversify-opening-top-k 10 --adaptive-stall-games 4 --adaptive-explore-step 2 --adaptive-explore-plies-step 2 --append-output --output data/quiet_value_v1.npz
```

Inspect a dataset:

```powershell
python -m ukumog_engine.ml.inspect_data --data data/quiet_value_v1.npz
```

Train a model:

```powershell
python -m ukumog_engine.ml.train --data data/quiet_value_v1.npz --output checkpoints/quiet_value_v1.pt --epochs 12 --batch-size 128 --learning-rate 3e-4 --accumulator-width 64 --hidden-width 32 --split-group auto
```

Notes:

* `play_cli.py` supports `--search-summary`, `--stats-jsonl`, `--time-trace`, side-specific depth/time/model overrides, and opening sampling controls.
* `tools/search_benchmark.py` runs the fixed search-tuning position set: `initial`, `tactical_midgame`, `immediate_double_threat`, and `quiet_midgame`.
* `play_cli.py` can now run repeated engine-vs-engine batches with `--games`, `--shuffle-colors`, and per-game seed stepping, then report a final win-rate summary.
* the primary ML runtime mode is now `quiet-value`, which only blends learned scores into quiet non-quiescent nodes.
* `ukumog_engine.ml.generate_data` now emits a `quiet_value_v1` dataset made from mask-state features, skips tactical positions, filters mate-like labels, and appends incrementally by default.
* the generator now buffers quiet candidates per game, labels only the best few, supports `--target-new-samples`, diversifies opening play, and adapts exploration when append yield stalls.
* `ukumog_engine.ml.train` now trains a shallow NNUE-style value net over the 4-mask and 5-mask ternary states already tracked by `IncrementalState`.
* the previous board-CNN policy/value workflow is still loadable for comparison via legacy checkpoints, but it is no longer the primary documented training path.

## Short History

The engine has progressed in a sensible order:

* rules and mask generation first
* baseline alpha-beta search next
* tactical reasoning layered on top
* reversible incremental state and lookup-backed eval after profiling showed repeated recomputation
* supervised ML pipeline added after the search core was already functional
* first policy-first CNN experiments retired as the primary path after they failed to show reproducible match gains
* quiet-value mask-state evaluation introduced as the current ML baseline

That ordering still looks right. The repo is strongest where it stayed symbolic and exact.

## Critical Review

What is genuinely strong:

* exact move classification and tactical legality handling
* search-side structure and pruning discipline
* reversible incremental bookkeeping
* instrumentation good enough to guide the next stage

What is currently weaker or riskier:

* the new quiet-value path is structurally better aligned with the engine, but it still has to prove reproducible equal-time gains over pure search
* the current label source is still search supervision, so quiet-sample quality and depth discipline matter more than raw sample count
* the first-pass mask evaluator does not yet carry a true search-stack accumulator

Evidence from the shipped datasets:

* older policy-first datasets were heavily tactical and mate-skewed, which made them poor targets for a quiet evaluator
* the new `quiet_value_v1` builder removes immediate wins, forced blocks, safe threats, double threats, opponent threats, and mate-like labels before writing samples
* validation now splits by canonical position metadata by default, which makes leakage much harder

Implication:

* the current learned model should be treated as a quiet-node helper only, not as evidence that the engine should become ML-led

## Idea Review

Opening base or shallow first 3-5 moves in the center 5x5:

* medium value for training-data generation efficiency and early-position diversity
* low-to-medium value for engine strength right now
* recommended use: canonicalized opening seeds for self-play, not a major standalone engine feature

Rotation and mirroring:

* still useful for deduplication and canonical hashing
* less central to the new primary model, because the quiet-value pipeline is mask-state based rather than board-plane augmentation led

Current ML evaluation overfitting:

* high-priority problem
* the current response is a full reset toward quiet-only mask-state value learning
* remaining fixes should focus on quieter labels, deeper search supervision, and eventual accumulator-style inference

Self-evolution once ML beats pure search:

* defer
* revisit only after the model proves equal-time match gains in root or quiet-PV usage without tactical regression

Caching positions across games during one training session:

* medium value if implemented as a symmetry-canonical label cache in data generation
* low value as a vague global cache without measured repeat rate and clear invalidation rules

## Recommended Next Curriculum

1. Reduce tactical, quiescence, and proof-solver overhead while improving quiet-node selectivity.
2. Tighten measurement discipline around equal-time matches, search summaries, and reproducible benchmark settings.
3. Refactor dataset generation toward quiet, disagreement-heavy, and less-correlated positions.
4. Add a true search-stack accumulator to the quiet-value evaluator after the current mask-state path proves useful.
5. Re-test ML only as a quiet-node eval aid after the stronger dataset exists.

## Next-Stage Direction

If the target is "closer to Stockfish," the practical reading is:

* search remains the engine
* tactical correctness remains exact
* incremental state and pruning quality matter more than bigger models
* ML must earn its place through measured equal-time gain, not offline loss alone

That means the next stage should optimize for deeper and more efficient search first, then bring ML back in only where the search instrumentation says it helps.

## Search Review: 2026-04-20

What Stockfish is really doing when it reaches depth 20+ quickly:

* the reported depth is selective depth, not full-width brute force
* the official Stockfish docs explicitly center aggressive pruning and reductions such as null-move pruning, futility pruning, late-move pruning, and late-move reductions
* official Stockfish docs also note that aggressive pruning lowers effective branching factor dramatically; even small branching-factor improvements compound into huge node savings
* Stockfish also benefits from highly optimized native code, very cheap move generation, tight incremental state, and SMP search

What the current Ukumog search already has:

* iterative deepening
* alpha-beta negamax with PVS and aspiration windows
* transposition table in the main search
* killer/history ordering
* late-move reductions
* tactical quiescence
* selective tactical proof search
* reversible incremental state and incremental lookup eval

What local profiling says is still expensive:

* `ukumog_engine/search.py` spends most time inside `_tactics`, `_quiescence`, and `_tactical_proof`
* after Stage 5, the hot inner loops are still in `ukumog_engine/incremental.py`, especially `paired_tactical_summaries`, `_future_winning_bits_from_move`, and subset move-map derivation
* make/unmake is not the main problem right now; tactical summary generation is

Representative local pure-search measurements on one tactical midgame position:

* before the first cache fix: depth 4 about `2.0s`, depth 5 about `4.5s`, depth 6 about `55.0s`
* first low-risk fix landed on `2026-04-20`: full tactical snapshots now satisfy later lite-snapshot requests from the cache
* after that fix on the same position: depth 5 about `2.9s`, depth 6 about `34.2s`
* Stage 1 landed on `2026-04-20`: light tactical snapshots now skip building per-move future-win maps up front, search/proof paths request light snapshots by default, and exact move maps are generated lazily only when move ordering needs them
* after Stage 1 on the same position: depth 5 about `2.8s`, depth 6 about `31.4s`
* Stage 2 landed on `2026-04-20`: conservative futility pruning and late-move pruning now skip quiet non-PV tail work while preserving exact tactical handling on urgent nodes
* after Stage 2 on the same position: depth 5 about `2.0s`, depth 6 about `6.7s`, depth 7 about `37.9s`
* Stage 2 makes deeper search materially more realistic, but it also exposes the next bottleneck clearly: tactical proof activations still explode on sharp lines
* Stage 3 landed on `2026-04-20`: tactical proof search is now gated much more tightly on non-PV and deeper side branches, while staying active on PV and near-root forcing lines
* after Stage 3 on the same position: depth 6 about `5.1s`, depth 7 about `24.2s`
* a depth-8 probe on that same position still did not fully finish within `60s`, but the engine now completes depth 7 inside that budget and proof time becomes almost negligible there
* Stage 4 landed on `2026-04-20`: quiescence now has a dedicated hash table with bound reuse and hash-move ordering, which cuts repeated horizon work without mixing q-search entries into the main TT
* after Stage 4 on the same position: depth 6 about `5.0s`, depth 7 about `24.5s`
* Stage 4 is a modest gain rather than a breakthrough, but q-hash hits are real and horizon overhead is now cleaner to measure
* Stage 5 landed on `2026-04-21`: tactical summaries now use an explicit `BASIC` vs `ORDERING` split, poison detection is derived in bulk, and exact ordering maps are reserved for the quiet subset instead of broad tactical buckets
* after Stage 5 on the same position: depth 6 about `3.0s`
* Stage 5 is the first tactical-summary refactor that clearly beats the Stage 4 tactical-midgame baseline
* the improvement is real, but it is still nowhere near enough for comfortable depth-8 search on sharp positions

Current orientation after Stage 5:

* the biggest wins came from pruning, proof-solver gating, and now the first real tactical-summary refactor
* proof search is no longer the main problem on representative sharp midgames
* static eval is not the problem
* the primary wall is still tactical summary generation plus quiescence work on positions that are sharp enough to stay tactical, but not forcing enough to collapse immediately
* exact ordering maps are now much better targeted, so the next gains should come from cheaper basic tactical summaries and tighter non-PV quiescence selectivity

Small benchmark set snapshot at depth 6:

* opening-like root (`Position.initial()`): about `0.54s`, total nodes about `1680`, proof time effectively `0s`
* representative tactical midgame: about `3.0s`, total nodes about `8868`, tactics about `1.9s`, quiescence about `1.8s`, proof about `0.02s`
* immediate double-threat win: essentially solved instantly, total nodes about `6`
* quiet midgame from the search tests: about `0.87s`, total nodes about `3718`

Interpretation:

* the engine already handles truly forcing positions well
* the remaining hard class is the "wide tactical midgame" where many safe threats and tactical continuations still exist
* that means the next direction still should not be more generic pruning first
* it should be a second tactical-efficiency pass aimed at cheaper basic summaries and narrower non-PV quiescence work

Important caution on "borrow Stockfish tech":

* null-move pruning is one of Stockfish's biggest weapons, but it should not be copied blindly here
* this game is pure tempo and threat creation, and illegal-pass assumptions may be much less safe than in chess
* safer first ports are quiescence TT support, stronger quiet-node pruning, better move-order histories, and tactical-pipeline laziness

Revised implementation order after Stage 5:

1. Tighten the basic tactical-summary pass further.
   Focus on reducing repeated future-win and opponent-reply derivation inside `paired_tactical_summaries` and subset move-map generation.
2. Tighten quiescence candidate selection further on non-PV nodes.
   Focus on reducing broad safe-threat expansions that rarely change the bound.
3. Improve tactical move ordering inside the remaining sharp nodes.
   Good candidates: continuation/countermove history, stronger reuse of prior PV/hash moves, and tactical bucket ordering that does less per-move work.
4. Add a small fixed benchmark suite to the repo workflow.
   Opening, wide tactical midgame, immediate forcing win, and one quiet midgame should become the standard timing set before further search changes land.
5. Re-profile the hottest incremental tactical functions before doing another search rewrite.
   Right now `paired_tactical_summaries`, `_future_winning_bits_from_move`, and subset move-map derivation deserve the most scrutiny.
6. Only after the tactical-summary path is lighter should we decide whether native acceleration is warranted for the hottest loops.
7. Keep ML out of the critical path until the search-side bottlenecks above flatten further.

What is effectively complete for this phase:

* light-vs-full tactical snapshot split
* tactical cache reuse across full and lite requests
* conservative quiet-node futility and late-move pruning
* aggressive proof-solver gating on non-PV/deeper side branches
* quiescence TT groundwork
* first tactical-summary tier refactor with subset-only ordering maps

What should not be the immediate next bet:

* null-move pruning
* more generic pruning without new tactical evidence
* another round of eval micro-optimization
* ML-led search guidance as a substitute for tactical selectivity

Practical expectation:

* depth 8 in seconds will not come from one trick
* it will come from lowering the effective branching factor, reducing tactical recomputation, and being much more selective about which quiet and tactical branches deserve full work
* the engine is already structurally close enough to a Stockfish-style searcher that this is a realistic path
* the next work should stay search-first and measurement-first

Suggested benchmark discipline for this phase:

* maintain a small fixed set of opening, quiet-midgame, and tactical-midgame positions
* track depth, wall time, total nodes, average searched moves, quiescence share, proof-solver share, and tactics cache hit rate
* treat "same strength at lower time" or "more depth at same time" as the main success criteria, not raw node count alone

## Archived Logs

The previous working logs were intentionally moved out of the repo root:

* [DEV_AGENDA.md](docs/archive/DEV_AGENDA.md)
* [DEV_NEXT_STAGE.md](docs/archive/DEV_NEXT_STAGE.md)

They remain useful as historical notes, but `README.md` is now the single authoritative project document.
