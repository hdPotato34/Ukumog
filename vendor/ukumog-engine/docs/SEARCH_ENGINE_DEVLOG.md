# Search Engine Dev Log

Active search-engine roadmap and measurement log for the current repo state.

Historical context lives in [README_HISTORY_20260421.md](archive/README_HISTORY_20260421.md). That archive is still worth keeping around because it records how Stages 1-5 were reached, but this file is the active search-specific planning document going forward.

## Latest Update: 2026-04-23 Single-Forced-Block Chain Compression

The next-stage q-search pass is now landed.

The core change was structural rather than tactical-pattern-specific:

* split `_quiescence` into a thin entry path plus a `_quiescence_from_snapshot` continuation path
* added `_probe_quiescence_tt` so forced-block chain nodes can reuse q-search TT logic without bouncing back through a fresh `_quiescence` frame
* changed `_follow_single_forced_block_quiescence` so singleton reply chains stay inside the same search-side flow until the chain truly branches or terminates
* when a chain reaches a non-singleton tactical node, continue from the already-built child snapshot instead of re-entering `_quiescence` and recomputing the same node boundary work

Why this helped:

* the previous chain follower flattened the move sequence, but it still paid a second full q-search entry cost at the leaf boundary
* that meant duplicate TT probing, duplicate tactical entry/setup logic, and extra recursive frame overhead exactly in the hotspot class
* the new version keeps the work on the search side and only falls back to full recursive q-search when it is actually searching child candidates, not when it is merely crossing the forced-chain boundary

Depth-6 benchmark snapshot on `2026-04-23`:

Before this pass, current baseline:

* `initial`: `0.657s`, `2858` nodes
* `tactical_midgame`: `4.558s`, `16122` nodes
* `quiet_midgame`: `1.283s`, `4812` nodes
* `restricted_threat_midgame`: `0.153s`, `505` nodes
* `restricted_threat_repro`: `0.158s`, `505` nodes

After this pass:

* `initial`: `0.640s`, `2855` nodes
* `tactical_midgame`: `4.093s`, `15136` nodes
* `quiet_midgame`: `1.033s`, `4333` nodes
* `restricted_threat_midgame`: `0.123s`, `497` nodes
* `restricted_threat_repro`: `0.122s`, `497` nodes

Fixed depth-7 real-play suite on `2026-04-23`:

* the 8 opening-prefix positions plus `quiet_midgame` and `tactical_midgame` now averaged `2.464s` to `2.828s` across two local passes
* average total nodes on that suite were `10795.6`, down from the previously documented `11959.3`

Interpretation:

* this is a real search-shape improvement, not only a per-node micro-optimization
* the dominant single-forced-block q-chain class is still expensive, but it is materially cheaper now
* `tactical_midgame` remains the main noisiest and most expensive benchmark, so the next work should target shared tactical cost on the surviving nodes rather than reopening quiet-threat side channels

Verification after this pass:

* `python -m pytest -q` -> `94 passed`
* `python tools/search_benchmark.py --depth 6`
* two local depth-7 fixed-suite passes via `tools.ml_match_suite.default_suite_positions()`

## Latest Update: 2026-04-23 First-Principles Quiet-Threat Rollback

The safety-commit investigation made the main structural problem clear: the engine was no longer just "evaluating quiet threats." It was running hidden mini-searches for them inside normal move ordering and inside the main negamax loop.

The expensive pieces were:

* `_single_safe_threat_order_bonus`
* `_follow_single_safe_threat_verification`

Both paths were repeatedly making a candidate move, deriving a fresh tactical snapshot for the child, often making the forced reply too, and then either rescoring or continuing search from there. That was not first-principles move ordering anymore; it was a side-channel tactical extension that duplicated work the real search should have been doing once, in one place.

This pass deliberately removed that design:

* deleted the exact single-safe-threat ordering probe
* deleted the exact single-safe-threat verification shortcut from `_negamax`
* removed the now-obsolete cache and instrumentation fields tied to that helper path
* dropped the helper-specific tests that locked in the removed mechanism rather than core game understanding
* kept the cheaper local signals already present in the current snapshot: safe-threat classification, future-win counts, immediate-win blocking, and restricted-line pressure

Depth-7 fixed real-play suite on `2026-04-23`:

Safety baseline `884bdf4` before this pass:

* average elapsed: `7.888s`
* average total nodes: `18668.4`
* average tactics time: `5.164s`
* average quiescence time: `2.958s`

After this pass:

* average elapsed: `3.243s`
* average total nodes: `11959.3`
* average tactics time: `2.201s`
* average quiescence time: `1.913s`

That is the important result for actual search usage: the first-principles version is much cheaper on the opening and quiet-heavy positions that dominate real games.

Fixed depth-6 benchmark split:

Safety baseline `884bdf4` before this pass:

* `initial`: `0.695s`, `2858` nodes
* `tactical_midgame`: `2.554s`, `8273` nodes
* `quiet_midgame`: `4.811s`, `8291` nodes
* `restricted_threat_midgame`: `0.231s`, `640` nodes
* `restricted_threat_repro`: `0.225s`, `636` nodes

After this pass:

* `initial`: `0.657s`, `2858` nodes
* `tactical_midgame`: `4.558s`, `16122` nodes
* `quiet_midgame`: `1.283s`, `4812` nodes
* `restricted_threat_midgame`: `0.153s`, `505` nodes
* `restricted_threat_repro`: `0.158s`, `505` nodes

Interpretation:

* this is a real first-principles simplification, not a micro-optimization
* the broad practical workload got much faster
* the cost was tactical-midgame selectivity: without the exact quiet-threat side channel, more single-forced-block chains survive into q-search
* that tactical benchmark is now the clearest remaining hotspot, but it should be solved by direct search/quiescence design rather than bringing back hidden quiet-threat mini-searches

Verification after this pass:

* `python -m pytest -q` -> `94 passed`
* `python tools/search_benchmark.py --depth 6 --positions initial tactical_midgame quiet_midgame restricted_threat_midgame restricted_threat_repro`

## Roadmap From Here

After the first-principles rollback, the next destination is clearer than it was before:

1. Fix tactical sharpness and throughput together inside q-search and forced-block handling.
2. Only do another broad tactical-kernel speed pass if profiling still shows a clear shared hotspot.
3. Keep ML in a supporting role until search stabilizes again across both the real-play suite and the tactical benchmark.

Why this ordering:

* the broad depth-7 real-play suite now looks much healthier
* the remaining bad class is concentrated rather than global
* that class is exactly the kind of thing the search should solve directly rather than by adding another expensive quiet-threat side channel

### Next Destination: Tactical Chain Handling

The highest-value next stage is not a full AI evaluator and not another generic speed cleanup. It is a search-design pass aimed at the new dominant failure/cost shape:

* many single-forced-block q-nodes
* tactical-midgame widening after the quiet-threat helper removal
* too much repeated work along forced reply chains

The target should be a direct, explicit chain handler for single-forced-block tactical sequences, with strict scope:

* only activate when the reply set is genuinely singleton and stable
* do not recompute broad tactical summaries more than necessary along the chain
* keep the logic inside q-search / tactical extension handling, not hidden inside quiet move ordering
* measure both node count and wall time on `tactical_midgame` plus the fixed real-play suite

This is the best next step because it attacks the new hotspot at the right boundary: the tactical frontier itself.

Scoped attempt note:

* a first lightweight q-search chain-summary experiment was tried immediately after this roadmap update
* the idea was to replace full tactical summaries on continuing single-forced-block q-chain nodes with a minimal forced-chain summary
* that version did not beat the current baseline in local measurement and was backed out rather than landed
* practical reading: the right next experiment is now narrower, likely either better cache reuse on chain nodes or search-side chain compression, not a separate uncached tactical-summary path

### ML Stance

ML should not be the next primary push.

Recommended near-term stance:

* do not prioritize a new quiet-value evaluator pass yet
* do not spend the next stage on learned weights for static eval blending
* keep root-policy as the only ML path worth active attention once the search baseline settles again

Practical reading:

* root-policy can still be useful later for root ordering and equal-time conversion
* full-board learned evaluation is still downstream of search quality and search stability
* the repo is not yet in the state where a stronger evaluator is the cleanest next bottleneck break

### Efficiency Curriculum

Efficiency still matters, but it should now be subordinate to tactical-shape work rather than treated as a separate first move.

The right efficiency questions for the next stage are:

* after a direct forced-block-chain pass, is `paired_tactical_summaries` still the main broad hotspot?
* does the shared poison/restricted scan still dominate enough to justify another kernel refactor?
* can q-search reuse or lightweight summaries reduce repeated tactical recomputation on chain nodes?

If the answer to those stays "yes" after the tactical-chain work, then another kernel cleanup is justified. If not, more low-level cleanup would be polishing the wrong wall.

### Acceptance Gates

Future search work should pass all of these, not just one:

* `python -m pytest -q`
* `python tools/search_benchmark.py --depth 6 --positions initial tactical_midgame quiet_midgame restricted_threat_midgame restricted_threat_repro`
* the fixed depth-7 real-play suite of 8 opening-prefix positions plus `quiet_midgame` and `tactical_midgame`
* at least one equal-time engine-vs-engine or `tools/ml_match_suite.py` check before declaring a node-shape change "good"

### Practical Priority Order

If I were sequencing the next work from the current repo state, I would do it in this order:

1. Implement and profile a direct single-forced-block chain handler in q-search / tactical extensions.
2. Re-benchmark tactical-midgame and the fixed depth-7 real-play suite to see whether the tactical widening comes back under control.
3. Only then decide whether another tactical-kernel cleanup is still worth doing.
4. Once search behavior is stable again, refresh the root-policy baseline and rerun the ML match suite.
5. Leave quiet-value and heavier evaluator ideas archived unless search stops being the main limiter.

## Latest Update: 2026-04-23 Speed Recovery Pass

The recent poisoned-line strength pass was real, but it also made the engine materially slower in practice. The user-facing symptom was simple: searches that had been taking only a few seconds at depth 7 were now landing closer to `12s` per move on the same machine.

Depth-6 profiling showed that the slowdown was mostly tactical-kernel overhead, not a broad alpha-beta regression:

* `paired_tactical_summaries` became the dominant hot path again
* the old restricted-line helper path was spending millions of calls on masks that could never contribute
* full-board winning-mask and poison-mask scans were being repeated even though the earlier candidate pass had already walked the same data
* the `search._tactics` fallback was rebuilding incremental state more than necessary when it had to derive both sides' snapshots outside the main search path

Changes landed in this recovery pass:

* merged candidate and full-board winning-mask derivation into one shared `_paired_winning_move_data` pass
* merged candidate poison-set collection and full poison-bit derivation into one shared `_paired_poison_move_data` pass
* inlined restricted-line evaluation behind cheap guards so we only pay for masks that both contain poison and have a relevant attacker count
* replaced set-heavy restricted critical-build / response accumulation with board-bit masks
* removed the extra incremental rebuild in the `search._tactics` fallback by deriving paired tactical summaries from one temporary `IncrementalState`
* restored the broader tactical classification for lone-safe-blocker restricted races after an over-narrowed version briefly reduced per-node work but exploded tactical node count on the wide midgame benchmark

Depth-6 benchmark snapshot on `2026-04-23`:

Before this pass:

* `initial`: `1.216s`, `2858` nodes
* `tactical_midgame`: `3.762s`, `8273` nodes
* `quiet_midgame`: `4.338s`, `8291` nodes
* `restricted_threat_midgame`: `0.208s`, `640` nodes

After this pass:

* `initial`: `0.729s`, `2858` nodes
* `tactical_midgame`: `2.485s`, `8273` nodes
* `quiet_midgame`: `3.135s`, `8291` nodes
* `restricted_threat_midgame`: `0.167s`, `640` nodes
* `restricted_threat_repro`: `0.165s`, `636` nodes

Verification after the speed pass:

* `python -m pytest -q` -> `96 passed`
* `python tools/search_benchmark.py --depth 6 --positions initial tactical_midgame quiet_midgame restricted_threat_midgame restricted_threat_repro`

Repo surface note:

* a desktop GUI now ships via `play_gui.py`, but this log remains search-focused
* the GUI reuses the same shared controller/runtime path as `play_cli.py`, so search and ML compatibility still live in one place
* board size remains fixed at `11x11`; the GUI did not change the engine's board assumptions

## Current Standing

The engine is already structurally in a strong place:

* alpha-beta negamax with iterative deepening, PVS, aspiration windows, TT, killer/history ordering, and LMR
* tactical quiescence with a dedicated q-search TT
* conservative quiet-node futility and late-move pruning
* selective proof-solver gating for forcing branches
* incremental tactical bookkeeping with a `BASIC` vs `ORDERING` tactical-detail split and bulk future-win derivation
* benchmark and test coverage that is good enough to support search-first iteration

The big result from the Stage 1-5 work, as documented in the archived README, still holds today:

* proof search is no longer the primary bottleneck
* static evaluation is not the primary bottleneck
* the hard class is still the wide tactical midgame, where many non-forcing tactical continuations survive long enough to keep both tactical-summary generation and quiescence expensive

In other words, the search engine is already "Stockfish-like" in broad shape, but not yet in tactical throughput. The next gains will not come from one magic trick. They will come from driving down the effective branching factor and the tactical recomputation cost inside the surviving nodes.

Stage 7 status:

* a conservative non-PV quiescence narrowing pass has now landed
* the change is intentionally narrow: it only tightens safe-threat-only quiescence behavior away from PV lines and leaves forced blocks and double threats alone
* repeated local benchmarks on the representative tactical midgame were mixed and did not materially reduce node counts
* practical reading: this was a safe exploratory pass, not a breakthrough, and the Stage 6 baseline remains the last clearly large search-speed jump

Fine-grained q-search follow-up:

* the benchmark tool and search summaries now expose q-search mix data such as single-forced-block nodes, safe-threat-only nodes, and q-skip reasons
* on the representative tactical midgame at depth 7, the key q-search fact is now clear: the engine sees thousands of single-forced-block q-nodes and almost no safe-threat-only q-nodes
* practical reading: the previous safe-threat-focused Stage 7 heuristic was aimed at a real q-search category, but not at the dominant one on the benchmark that matters most
* a stronger single-forced-block chain follower has now landed on top of that profiling pass
* repeated local tactical-benchmark runs are still somewhat noisy, but they now show a more consistent structural win: q-search time drops materially when the benchmark is dominated by forced-block chains
* a follow-up tactical-summary plumbing cleanup has also landed: paired summaries and move-map generation now reuse already-known ordered candidate sets and candidate-bit masks instead of recomputing them through helper calls
* a deeper tactical bulk-pass has now landed: paired summaries derive black/white immediate wins, future wins, and poison sets in shared passes, and search ordering now uses count-only move-map data when it only needs lengths
* a broader ordering hot-path cleanup has now landed: the tactical-biased continuation-ordering experiment was backed out, static move-order bonuses are precomputed, and ranking now avoids extra per-move count dicts when snapshot move maps already exist
* another broad tactical-kernel pass has now landed: the hot 4-mask and 5-mask scans stop re-checking empty counts that are already implied by the incremental mask counts, and `move_map_counts` / `move_maps` now derive opponent winning replies and future wins from one shared 5-mask pass instead of two
* a strength-oriented ordering pass has now landed: quiet-history updates are finally scaled strongly enough to matter, and quiet moves searched before a quiet beta cutoff now receive history maluses instead of being forgotten

## Historical Baseline Snapshot (2026-04-22)

Verification run on `2026-04-22` after the quiet-history ordering pass:

* `python -m pytest -q` -> `78 passed`
* `python tools/search_benchmark.py --depth 7 --positions tactical_midgame quiet_midgame initial`
* `python tools/search_benchmark.py --depth 8 --time-ms 60000 --positions tactical_midgame`
* `python tools/ml_match_suite.py --candidate-name Depth6Dense --model checkpoints/phase7_ml_bigger_dense.pt --ml-mode auto --candidate-depth 6 --baseline-name Depth5 --baseline-depth 5 --time-controls 0.5`

Observed benchmark ranges from local spot checks under varying machine load:

* `initial` depth 7: about `1.36s` to `1.40s`, `7162` total nodes
* `quiet_midgame` depth 7: about `1.94s` to `2.00s`, `12807` total nodes
* `tactical_midgame` depth 7: about `6.1s` to `7.7s`, `33051` total nodes
* `tactical_midgame` depth 8 with a `60000ms` budget: about `18.8s` to `26.6s`, `109638` total nodes

Time-share observations from those same runs:

* on the representative tactical midgame at depth 7, tactics time is about `3.3s` to `4.2s` and quiescence time is about `2.8s` to `3.6s`
* at the depth-8 probe, tactics time is about `10.5s` to `15.2s` and quiescence time about `9.0s` to `13.1s`
* proof time stays near zero in all of those runs, which confirms the archived conclusion that proof search is no longer the wall
* the q-search mix changed meaningfully on the tactical benchmark because the engine is now finding earlier cutoffs: at depth 7 the run produced about `2755` single-forced-block q-nodes instead of the older `4529`
* this is no longer just a per-node cleanup stage; the quiet-history change materially reduced node count on the tactical benchmark

Interpretation:

* efficient depth 8 is already realistic on easy and quiet positions
* time-limited depth 8 is now much more comfortable on the wide tactical benchmark position than it was before the quiet-history pass
* the current blocker is still tactical summary generation plus quiescence expansion, not static eval
* inside q-search specifically, the current benchmark still looks much more like a forced-block chain problem than a broad safe-threat expansion problem
* the new quiet-history stage proves something important for strength: turning compute into Elo is not just about nominal depth, it is about getting stronger ordering signals so the extra search actually reaches the right lines
* pure search is still under-converting some of that gain at equal time, but search+policy guidance is now clearly more promising than either raw depth or ML-alone stories

## What Stage 1-8 Actually Bought Us

The archived README records the sequence well, and the repo still reflects it:

* Stage 1: light tactical snapshots stopped paying for move maps up front
* Stage 2: conservative futility and late-move pruning dramatically lowered quiet tail work
* Stage 3: proof-solver gating prevented deep non-PV tactical proof explosions
* Stage 4: q-search TT reuse cleaned up repeated horizon work
* Stage 5: tactical summaries moved to explicit `BASIC` vs `ORDERING` tiers, and exact move maps are now computed for a smaller ranked subset
* Stage 6: `BASIC` tactical summaries now derive future wins in one pass over the five-masks, and opponent-win-after bookkeeping no longer iterates masks per move
* Stage 7: non-PV quiescence now narrows safe-threat-only frontier handling more aggressively, but the measured gain so far is modest and noisy
* Fine-grained q-search pass: the engine now exposes q-search mix counters and has a direct single-forced-block chain follower, which clarifies that the tactical benchmark is dominated by forced-block chains and can cut q-search time materially on repeat runs
* Confirmed follow-up benchmark: the representative tactical midgame now finishes a `depth=8`, `time-ms=60000` probe in about `44.4s`
* Tactical-summary plumbing cleanup: internal incremental helpers now reuse ordered candidates and candidate-bit masks instead of recomputing them, which trims tactical overhead without changing search behavior
* Paired tactical bulk-pass: shared 5-mask and 4-mask scans now derive both colors' winning, future-win, and poison bookkeeping together, and ordering now uses count-only move-map data when full tuples would be thrown away
* Broader ordering hot-path cleanup: the tactical-ordering experiment was backed out for the live baseline, static move-order bonuses are now precomputed, and ranking no longer builds extra count dicts when snapshot move maps already exist
* Broad tactical-kernel cleanup: hot 4-mask and 5-mask scans now trust count-implied empties, and the single-color move-map path now derives opponent winning replies and future wins from one scan instead of two
* Strength-oriented quiet-history pass: quiet cutoffs now create a strong positive ordering signal, and earlier quiet misses in the same node now receive a negative signal instead of being treated neutrally

Those were the right stages. They got the engine from "depth 6 is painful" to "depth 7 is practical and depth 8 now fits inside a 60-second tactical benchmark budget with meaningful slack." The next phase should stay on that same axis rather than resetting the strategy, but it still needs stricter measurement because future node-reduction experiments can help one position class while hurting another.

## Present Bottlenecks

The current standing view, combining the archive with the fresh measurements, is:

1. `paired_tactical_summaries` is still a hot path even after the new paired bulk pass.
2. Within that path, the shared poison scan now looks like the clearest remaining broad tactical hotspot.
3. The one-pass move-map refactor helped the `move_map_counts` path, so that piece is less urgent than it was before this stage.
4. Quiescence is still expensive, but the dominant benchmark shape is now much clearer: many single-forced-block chains, not broad safe-threat-only tails.
5. The new quiet-history pass shows that node-count reduction can be worth keeping when it survives strength checks, not just speed checks.
6. Pure search still does not convert all of that extra tactical efficiency into a dominant equal-time edge over depth 5 by itself.
7. The strongest current match result comes from pairing the faster search with a root-policy checkpoint, which suggests the near-term determinant is search quality first and ML-guided root ordering second.
8. On the current depth-8 tactical benchmark, tactics time is still larger than quiescence time, so another tactical-kernel cleanup is still a plausible next broad-speed win.

That means the next curriculum should be broad-speed-first again: cheaper hot paths that help the whole engine, with node-reduction experiments treated as opt-in and heavily measured.

## Current Next Priority

The most practical next-step ordering from the new baseline is:

1. Keep the new candidate/baseline-depth match-suite workflow in the acceptance path for future strength work.
2. Re-profile the shared poison scan inside `paired_tactical_summaries` now that the move-map path is cheaper again.
3. Keep the fixed suite split by position class: opening-like, quiet, and tactical benchmarks should all stay visible for every future search change.
4. Treat node-reduction ideas as experiments behind both speed and strength guardrails rather than as the default next move.
5. If one more Python-side tactical-kernel pass does not move throughput enough, start a scoped native-acceleration experiment for the hottest tactical kernels rather than polishing around the edges.

## Strength Guardrails

Recent strength-side checks matter for the next decision:

* the latest quiet-history pass is not a low-risk per-node cleanup; it is a real node-shape change, so the strength checks matter more than they did on the last stage
* that risk showed up clearly: pure depth 6 and depth 7 no longer look automatically stronger than depth 5 just because the tactical benchmark got faster
* the bigger tactical-risk frontier is still move ordering: anything that changes which quiet moves are searched first can interact with futility pruning, late-move pruning, and proof gating
* that makes the new candidate/baseline-depth match-suite path part of the real regression gate, not just a nice-to-have diagnostic

Small fixed-time search checks on `tactical_midgame` are useful here:

* pure search with `max_time_ms=500` completed `depth=5` and chose move `59`
* pure search with `max_time_ms=1000` also completed `depth=5` and chose move `59`
* pure search with `max_time_ms=2000` completed `depth=6` and switched to move `36`
* the current `phase7_baseline.pt` root-policy run still completed only `depth=5` at `max_time_ms=2000` and stayed on move `59`

Practical reading:

* higher search efficiency does buy tactically meaningful extra depth once it crosses the next completed-depth boundary
* that benefit is not guaranteed at very short controls; at `500ms` there was no move change on the representative tactical benchmark
* raw nominal depth is still not the full story; the search needs strong enough ordering to make the extra effort land on the right lines
* the current root-policy models can now matter again when paired with the faster search, especially at the root where ordering quality is most valuable

Small opening-prefix equal-time checks reinforce that caution:

* on a small 8-game paired suite, pure depth 7 vs pure depth 5 split `4/8`, which is not enough to call it consistently stronger
* on the full 20-game paired suite at `0.5s`, `Depth6 + phase7_ml_bigger_dense.pt` scored `13/20` (`65%`) against pure depth 5
* on that same path, `phase7_baseline.pt` was only a modest edge over depth 5, so checkpoint choice still matters

Implication for the roadmap:

* the default next stage should still stay search-first, but "search-first" now includes explicit strength-gate measurements
* node-count reduction via tactical ordering is worth keeping only when it survives those strength gates
* ML is not the determinant by itself yet, but it is now a credible multiplier on top of the faster search
* before or alongside any future node-reduction pass, the repo should keep:
  a solver-backed forcing regression position beyond the immediate double-threat case
  and the tiny fixed-time opening-prefix strength gate so speed gains are not mistaken for strength gains

## Curriculum For Efficient Depth 8 And Beyond

### Next Broad-Speed Stage: Tactical Kernel Cleanup

Goal:
Lower per-node tactical cost across opening-like, quiet, and tactical positions together.

Priority ideas:

* re-profile the shared poison scan inside `paired_tactical_summaries` before touching quiescence again
* look for another paired-summary pass that reduces classification work without re-widening the code path for quiet positions
* keep the one-pass `move_map_counts` / `move_maps` helper, but only revisit it if new profiling says it is still disproportionately expensive
* keep static ordering work cheap and avoid reintroducing dynamic per-move bookkeeping into `_rank_moves`
* prefer improvements that leave node counts unchanged while reducing wall time across the full benchmark set

Why first:

* the latest stage clearly improved the deep timed tactical probe and real node count on the tactical benchmark
* the quiet benchmark did not improve by the same margin, which means the next broad pass should be chosen with that guardrail in mind
* the present tactical benchmark still spends more time in tactics than in quiescence
* broad ML data-generation throughput benefits more from cheaper nodes everywhere than from a narrower tactical-only tree win

Success target:

* move `initial`, `quiet_midgame`, and `tactical_midgame` forward together from the current baseline, with `quiet_midgame` explicitly treated as a no-regression gate

### Guarded Experimental Stage: Node-Count Reduction

Goal:
Lower total nodes on the hard tactical benchmark without adopting a narrower live baseline that hurts the broader engine.

Priority ideas:

* revisit tactical ordering only after the broad-speed baseline is stable
* reuse hash/PV preferences and tactical buckets carefully, but treat continuation-style ideas as experiments rather than defaults
* keep the solver-backed forcing regression and tiny fixed-time opening-prefix strength gate in the acceptance workflow
* reject any node-reduction pass that helps `tactical_midgame` while clearly regressing `initial` or `quiet_midgame`

Why second:

* the recent tactical-ordering experiment proved node reduction is possible
* it also proved that a faster tactical benchmark alone is not enough for the broader-speed target

Success target:

* lower `tactical_midgame` node count meaningfully while preserving or improving the opening-like and quiet benchmarks

### Escalation Stage: Native Boundary Decision

Goal:
Decide whether Python-level search work still has enough headroom, or whether the hottest tactical loops should be moved behind a faster implementation boundary.

Priority ideas:

* keep the fixed benchmark suite as the gate for all new search changes
* add one or two profiling snapshots around `paired_tactical_summaries` and q-search candidate generation before each major refactor
* only consider native acceleration after the tactical pipeline is cleaner, so we are not freezing a wasteful algorithm in a faster language

Why later:

* algorithmic wins are still being found
* native acceleration before the next tactical cleanup risks locking in the wrong work

## Immediate Next Moves

These are the next concrete steps I would take from the current repo state:

1. Keep q-search profiling in the standard benchmark output, but treat it as supporting data rather than the first knob to turn again.
2. Keep the new `tools/ml_match_suite.py` depth-split workflow in the standard strength gate for pure-search and search+ML candidates.
3. Re-profile `paired_tactical_summaries`, especially the shared poison path, on `initial`, `quiet_midgame`, and `tactical_midgame` after each tactical-kernel change.
4. Run the full position-class split after every broad-speed stage:
   depth 7 on `initial`, `quiet_midgame`, and `tactical_midgame`, plus the time-limited depth 8 tactical probe.
5. Keep node-reduction ideas in a side lane until the broad tactical kernels stop moving enough to matter.
6. If one more broad tactical-kernel pass still leaves ML data generation uncomfortably slow, promote the native-acceleration decision earlier instead of waiting for a perfect pure-Python endpoint.

## What Not To Do Next

The archived README was right to warn about these, and the current measurements do not change that:

* do not jump to null-move pruning yet
* do not assume more generic pruning is the best next move
* do not go back to static-eval micro-optimization as the main strategy
* do not try to solve search throughput by pushing ML further into the critical path

## Practical Goalposts

For the next search phase, the right definition of progress is:

* hold tactical correctness and search regressions steady
* keep `initial` depth 7 around or below about `1.35s`
* keep `quiet_midgame` depth 7 around or below about `2.0s`
* keep `tactical_midgame` depth 7 around or below about `6.5s`
* keep time-limited depth 8 tactical probes around or below about `20-27s` depending on local load
* keep `Depth6 + phase7_ml_bigger_dense.pt` clearly above `50%` against pure depth 5 on the full paired suite
* reject any future speed stage that wins only by helping the tactical benchmark while giving back too much on the opening-like or quiet cases

If those move in the right direction, then efficient depth 8 and beyond becomes a realistic engineering path rather than a slogan.
