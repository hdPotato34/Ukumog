# Ukumog Engine Development Agenda

This file is the working roadmap for the engine in this repo. It started from the original game brief and has been updated to reflect what the codebase now contains, what we learned while implementing it, and which ideas are worth pursuing next.

## 1. Game definition

### Board

* 11x11 grid
* Two players alternate placing one stone of their own color on an empty cell
* Passing is not allowed

### Win / loss condition

After a player places a stone, evaluate only the patterns newly created by that move.

* If the move creates a pattern of five, that player wins immediately
* Otherwise, if the move creates a pattern of four, that player loses immediately
* If both happen at once, pattern of five overrides pattern of four, so the player wins

### Pattern definition

A pattern of `n` means:

* there are `n` stones of the same color
* all lie on one straight line
* the spacing between consecutive stones is equal

This is an arithmetic progression on the board.

Notes:

* the line may be horizontal, vertical, or any slope that stays on the grid
* the stones do not need to be adjacent
* pieces in the gaps do not matter

Example:

* `(r, c), (r+1, c+2), (r+2, c+4), (r+3, c+6)` is a valid pattern of four if all are on board and the same color

## 2. Strategy choice

The chosen route remains:

* exact symbolic rule engine
* negamax / alpha-beta search
* strong move ordering
* tactical threat analysis
* transposition table
* optional later learned evaluation

This is still the right default because the game is deterministic, zero-sum, tactically sharp, and full of instantly losing moves.

Do not start with:

* random-rollout MCTS
* AlphaZero-from-scratch
* large neural nets without exact tactical logic

## 3. Current repo status

Completed so far:

* board indexing and integer bitboard representation
* full distinct 4-mask and 5-mask generation
* verified mask counts:
  * 780 four-pattern masks
  * 420 five-pattern masks
* incident tables for fast move resolution
* exact move application logic with 5-over-4 precedence
* brute-force move-result validator
* baseline search engine:
  * negamax
  * alpha-beta
  * iterative deepening
  * transposition table
  * principal variation tracking
  * budget-aware iterative deepening that can return the last completed depth under a move time limit
  * handcrafted evaluator
  * exact tactical move filtering for winning moves, forced replies, and poison avoidance
  * selective quiet-move widening in wide non-tactical positions
  * history and killer move ordering heuristics
  * selective late-move reduction for quiet moves
  * aspiration windows enabled for deeper iterations
  * principal variation search on non-PV sibling moves
  * richer per-search instrumentation with structured stats export
* tactical layer:
  * immediate win detector
  * poison detector
  * forced-block detector
  * safe-threat detector
  * double-threat detector
* tactical quiescence extension
* local bitboard threat derivation for future wins and defensive blocks
* precomputed cell influence masks for faster candidate generation
* selective exact tactical proof solver for sharp positions
* machine-readable search summaries and CLI JSONL logging for profiling runs
* regression tests for rules, tactical motifs, and basic search behavior

In short:

* Phase 1 is done
* Phase 2 is done in baseline form
* Phase 3 core tactical functionality is now present

## 4. Engine design

### 4.1 Board representation

Use:

* one 121-bit board for black
* one 121-bit board for white
* side to move

Current implementation uses Python integers for bitboards, which is clean and fast enough for the first versions.

Next likely addition:

* Zobrist hashing for a compact TT key and future repetition-safe instrumentation

### 4.2 Precomputed pattern masks

Keep precomputing all distinct arithmetic-line masks for:

* all 4-pattern masks
* all 5-pattern masks

Also maintain:

* `incident4[cell]`
* `incident5[cell]`

This remains the key low-level optimization because move resolution only needs masks that touch the played cell.

### 4.3 Fast move resolution

The fast path stays:

```python
place stone at s

if any incident 5-mask at s is fully occupied by mover:
    return WIN

if any incident 4-mask at s is fully occupied by mover:
    return LOSS

return NONTERMINAL
```

Check 5 first, then 4.

## 5. Tactical layer

### 5.1 Tactical concepts

For side `X`, define:

* `WinNow(X)`: a legal move that creates a 5 immediately
* `Poison(X)`: a legal move that creates a 4 and no 5
* `ForcedBlock(X)`: a safe legal move that removes all of the opponent's immediate wins
* `SafeThreat(X)`: a safe move that leaves at least one immediate winning continuation on the next turn while not allowing the opponent an immediate win
* `DoubleThreat(X)`: a safe move that leaves at least two distinct immediate winning continuations on the next turn while not allowing the opponent an immediate win

Current implementation notes:

* `SafeThreat` and `DoubleThreat` are based on concrete next-turn winning continuations
* `DoubleThreat` is treated as especially important because it often implies a forced win in one more move
* the current analyzer now derives many tactical consequences locally from the played move instead of recomputing whole-position win maps for each hypothetical continuation

### 5.2 Tactical search

The engine now has a restricted tactical extension at leaf nodes.

At tactical leaves, prioritize:

* immediate wins
* forced blocks
* double threats
* safe threats

Important consequence:

* shallow search can already recognize some forced tactical sequences that the plain evaluator would miss

### 5.3 Quiescence guidance

Do not stop at a leaf if:

* the side to move has an immediate win
* the side to move must answer an immediate opponent win
* a safe threat or double threat is present

Instead run a short tactical extension over restricted tactical candidates only.

## 6. Evaluation

The evaluator should remain handcrafted for now, but increasingly tactical-aware.

Current useful features:

* pure-color 5-mask potential
* pure-color 4-mask pressure
* immediate wins
* safe threats
* double threats
* forced-block resources
* safe mobility
* poison pressure

Key rule:

* only count safe tactical resources as genuinely valuable

A move that looks promising but loses immediately is worthless.

## 7. Updated development agenda

### Phase 1: rules and correctness

Status: complete

Built:

* board indexing
* bitboard representation
* full 4-mask and 5-mask generator
* incident mask tables
* exact move application logic
* brute-force validator

Deliverable:

* rule engine correctness base

### Phase 2: baseline engine

Status: complete in first playable form

Built:

* negamax
* alpha-beta
* iterative deepening
* transposition table
* basic move ordering
* handcrafted evaluation

Deliverable:

* playable engine

### Phase 3: tactical upgrade

Status: core complete, refinement ongoing

Built:

* immediate win detector
* poison detector
* forced-block detector
* threat and double-threat detector
* tactical leaf extension

Next refinements:

* more selective tactical move ordering
* better tactical caching across deeper iterative deepening passes
* deeper threat-space proof logic for sharp positions

Deliverable:

* strong short-horizon tactical play

### Phase 4: performance and pruning

Status: underway

Add:

* better candidate generation than raw "incident to any occupied stone"
* history heuristic
* killer heuristic
* aspiration windows
* profiling and hot-path cleanup
* optional move-count based late widening

Built so far:

* exact search-side filtering of dominated poison moves when any safe move exists
* exact restriction to forced blocks when the opponent has an immediate win
* selective quiet-move caps in wide non-urgent positions, while keeping tactical moves exact
* killer heuristic
* history heuristic
* aspiration windows for deeper iterative deepening passes
* principal variation search
* conservative late-move reduction on quiet moves
* tighter quiescence candidate selection
* time-budgeted interactive search fallback to the last fully completed iteration

Deliverable:

* deeper search under the same compute budget

### Phase 5: exact tactical solver

Status: complete

Add:

* proof-number or DFPN-style tactical subsolver
* selective activation in sharp positions
* integration with double-threat and forced-block motifs

Built so far:

* selective tactical proof solver that only returns proven win/loss results when the tactical move set is exhaustive enough to make that claim safely
* integration into the main search and quiescence paths for sharp positions
* solver memoization across a search

Current scope:

* immediate tactical wins
* forced-loss states with no safe defense
* double-threat proofs
* recursive forced-block / safe-threat tactical lines

Current limitation:

* it is intentionally conservative and returns `UNKNOWN` rather than over-claiming outside sharp tactical subspaces

Deliverable:

* stronger forced win/loss solving

### Phase 6: learned evaluator

Status: underway

Built so far:

* Torch-based dual-head policy/value network scaffold
* hybrid board encoder that mixes raw occupancy with exact tactical feature planes
* self-play data generation with search-labeled policy/value targets
* compressed NPZ dataset format with legal-move masks
* training entrypoint for supervised policy/value fitting
* checkpoint loader that can plug the learned evaluator back into search for static-eval blending and move-order priors
* symmetry-aware training augmentation so the model learns from all board isometries without regenerating data
* optional symmetry-ensemble inference for stronger but slower evaluation
* more robust ML training defaults through label smoothing, Huber-style value loss, and learning-rate decay

Near-term focus:

* generate the first serious dataset
* compare pure handcrafted eval against hybrid handcrafted-plus-learned eval
* tune the learned-eval weight so it helps quiet positions without overriding exact tactical logic
* test whether symmetry-ensemble inference is worth its runtime cost in match play

Deliverable:

* better positional judgment and move ordering

### Phase 7: Stockfish-style hybrid upgrade

Status: underway

Built so far:

* stage-7 working tracker in `DEV_NEXT_STAGE.md`
* expanded search instrumentation:
  * TT probes, hits, and cutoffs
  * fail-high / fail-low counts
  * branching and searched-move averages
  * tactical cache probe / hit tracking
  * proof-solver activation counts
  * ML call counts by node bucket
  * ML latency and wall-time share
  * policy-prior reorder rank tracking
* human-readable search summaries and structured JSON-ready summaries
* CLI support for `--search-summary` and `--stats-jsonl`
* reversible incremental mask-state foundation:
  * per-mask black / white occupancy counts
  * ternary mask-state ids
  * make/unmake undo tokens
  * incremental immediate-win and poison queries
* recursive search integration for the new incremental state:
  * negamax and quiescence use make/unmake
  * child move resolution uses incremental classification
  * tactical analysis can consume incremental move queries
* completed incremental tactical bookkeeping:
  * incremental tactical summaries for forced blocks, safe threats, double threats, and reply maps
  * parity-tested incremental tactical analysis path
* completed the current lookup-based evaluation objective:
  * precomputed 4-mask and 5-mask state tables
  * incremental aggregate mask score maintenance under make/unmake
  * search-side eval now uses the lookup-backed mask score
  * eval traces are now negligible relative to the remaining tactical work

Next:

* explicit quiet-node ML gating using the new instrumentation baseline

Deliverable:

* measurable speedups and better quiet-node search guidance without tactical regression

## 8. New ideas worth pursuing

These are not mandatory yet, but they look promising.

### 8.1 Incremental tactical bookkeeping

The current tactical layer recomputes more than it should. A strong improvement path is:

* cache tactical snapshots per position during search
* later maintain incremental per-mask occupancy counts under make/unmake

That would likely be the single biggest practical speedup before ML.

Note:

* a first cheaper version is now in place through per-search tactic caching, influence masks, and local move-based threat derivation
* a second layer is now in place through exact tactical move filtering and search-side pruning heuristics
* a third layer is now in place through selective quiet-position widening, which is especially important once influence masks cover most of the board

### 8.2 Mask-state lookup tables

For each mask:

* 5-mask state count is `3^5 = 243`
* 4-mask state count is `3^4 = 81`

Precomputing mask-state labels should allow:

* faster evaluation
* faster threat classification
* better overlap features

This is likely better than trying to hand-optimize Python loops too early.

### 8.3 Symmetry-aware opening work

The empty board and many early positions have strong symmetry. A useful future path:

* canonicalize positions under board symmetries for opening analysis
* optionally build a small opening book from search

### 8.4 Search instrumentation

Track during runs:

* nodes searched
* nodes per second
* TT hit rate
* average branching factor
* number of poison moves filtered
* tactical extension frequency
* tactical cache hit rate
* win/loss rate by seat
* opening bias

### 8.5 Long-term ML direction

If learning is added later, a plain image CNN is probably not the best fit.

A better representation is likely a cell-pattern graph:

* cell nodes
* 4-mask nodes
* 5-mask nodes
* message passing between them

Reason:

* the game's natural structure is a hypergraph of arithmetic-line masks

## 9. Must-have tests

Keep regression coverage for:

* simple 5 creation -> win
* simple 4 creation -> loss
* simultaneous 4 and 5 -> win
* gapped arithmetic patterns
* arbitrary slopes
* reverse-direction duplicate handling
* move classification correctness
* random-position oracle cross-check
* forced-block detection
* safe-threat detection
* double-threat detection
* shallow tactical search converting a fork into a winning choice

## 10. Implementation priority from here

Recommended next order:

1. implement reversible per-mask incremental bookkeeping and re-profile quiescence
2. port evaluation toward mask-state lookup tables
3. add explicit quiet-node ML gating on top of the new node-class instrumentation
4. improve candidate generation for quiet positions beyond pure influence masks and current quiet-move caps
5. scale Phase 6 data generation and begin evaluator training runs after the search-side speed work lands

That remains the cleanest path to a much stronger engine.
