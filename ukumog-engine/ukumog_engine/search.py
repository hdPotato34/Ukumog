from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .board import BOARD_CELLS, BOARD_SIZE, index_to_coord
from .incremental import IncrementalState
from .masks import DEFAULT_MASKS, MaskTables
from .position import Color, MoveResult, Position, play_move
from .solver import TacticalOutcome, TacticalSolver
from .tactics import TacticalSnapshot, analyze_tactics

MATE_SCORE = 1_000_000
ASPIRATION_WINDOW = 512
WIN_MOVE_BONUS = 250_000
BLOCK_MOVE_BONUS = 180_000
DOUBLE_THREAT_BONUS = 120_000
SAFE_THREAT_BONUS = 70_000
SAFE_MOVE_BONUS = 20_000
KILLER_MOVE_BONUS = 40_000
SECOND_KILLER_BONUS = 25_000
FUTURE_WIN_BONUS = 8_000
POISON_MOVE_PENALTY = 200_000
FIVE_MASK_LOCAL_BONUS = 16
FOUR_MASK_LOCAL_BONUS = 6
OPPONENT_WIN_REMAINING_PENALTY = 90_000
QUIESCENCE_SAFE_THREAT_LIMIT = 3
QUIESCENCE_SAFE_THREAT_MAX_SAFE_MOVES = 8
QUIESCENCE_SAFE_THREAT_ALPHA_MARGIN = 600
LATE_MOVE_REDUCTION_MIN_DEPTH = 3
LATE_MOVE_REDUCTION_AFTER = 4
SEARCH_LIMIT_CHECK_INTERVAL = 256
QUIET_MOVE_BASE_LIMIT = 6
QUIET_MOVE_DEPTH_FACTOR = 2
QUIET_MOVE_ROOT_BONUS = 6
TACTICAL_QUIET_TAIL = 4
TACTICAL_SOLVER_PLIES = 8
PROOF_MAX_FORCED_BLOCKS = 2
PROOF_MAX_SAFE_THREATS = 2
PROOF_MAX_SAFE_MOVES = 6


class Bound(Enum):
    EXACT = auto()
    LOWER = auto()
    UPPER = auto()


@dataclass(slots=True)
class SearchStats:
    nodes: int = 0
    tt_probes: int = 0
    tt_hits: int = 0
    tt_cutoffs: int = 0
    cutoffs: int = 0
    quiescence_nodes: int = 0
    tactical_quiescence_entries: int = 0
    tactical_extensions: int = 0
    immediate_win_nodes: int = 0
    safe_threat_nodes: int = 0
    double_threat_nodes: int = 0
    tactics_cache_hits: int = 0
    tactics_cache_probes: int = 0
    aspiration_researches: int = 0
    pvs_researches: int = 0
    fail_highs: int = 0
    fail_lows: int = 0
    poison_moves_filtered: int = 0
    forced_win_nodes: int = 0
    forced_loss_nodes: int = 0
    forced_block_nodes: int = 0
    forced_block_restrictions: int = 0
    all_poison_nodes: int = 0
    history_updates: int = 0
    killer_updates: int = 0
    late_move_researches: int = 0
    quiet_nodes_limited: int = 0
    quiet_moves_pruned: int = 0
    expanded_nodes: int = 0
    legal_moves_total: int = 0
    searched_moves_total: int = 0
    tactical_solver_queries: int = 0
    tactical_solver_cache_hits: int = 0
    tactical_solver_wins: int = 0
    tactical_solver_losses: int = 0
    tactical_solver_unknown: int = 0
    proof_solver_activations: int = 0
    proof_solver_skips: int = 0
    quiescence_soft_skip_nodes: int = 0
    model_calls_total: int = 0
    model_calls_root: int = 0
    model_calls_pv_quiet: int = 0
    model_calls_nonpv_quiet: int = 0
    model_calls_tactical: int = 0
    model_calls_quiescence: int = 0
    model_time_seconds: float = 0.0
    tactics_time_seconds: float = 0.0
    eval_time_seconds: float = 0.0
    ordering_time_seconds: float = 0.0
    quiescence_time_seconds: float = 0.0
    proof_solver_time_seconds: float = 0.0
    policy_reorder_events: int = 0
    policy_best_move_rank_before_total: int = 0
    policy_best_move_rank_after_total: int = 0
    elapsed_seconds: float = 0.0
    aborted: bool = False
    time_limit_abort: bool = False
    node_limit_abort: bool = False
    max_depth_completed: int = 0

    @property
    def total_nodes(self) -> int:
        return self.nodes + self.quiescence_nodes

    @property
    def nodes_per_second(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.nodes / self.elapsed_seconds

    @property
    def qnodes_per_second(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.quiescence_nodes / self.elapsed_seconds

    @property
    def average_branching_factor(self) -> float:
        if self.expanded_nodes == 0:
            return 0.0
        return self.searched_moves_total / self.expanded_nodes

    @property
    def average_legal_move_count(self) -> float:
        if self.expanded_nodes == 0:
            return 0.0
        return self.legal_moves_total / self.expanded_nodes

    @property
    def average_searched_move_count(self) -> float:
        return self.average_branching_factor

    @property
    def tactics_cache_hit_rate(self) -> float:
        if self.tactics_cache_probes == 0:
            return 0.0
        return self.tactics_cache_hits / self.tactics_cache_probes

    @property
    def model_mean_latency_ms(self) -> float:
        if self.model_calls_total == 0:
            return 0.0
        return (self.model_time_seconds * 1000.0) / self.model_calls_total

    @property
    def model_time_fraction(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.model_time_seconds / self.elapsed_seconds

    @property
    def tactics_time_fraction(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.tactics_time_seconds / self.elapsed_seconds

    @property
    def eval_time_fraction(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.eval_time_seconds / self.elapsed_seconds

    @property
    def ordering_time_fraction(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.ordering_time_seconds / self.elapsed_seconds

    @property
    def quiescence_time_fraction(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.quiescence_time_seconds / self.elapsed_seconds

    @property
    def proof_solver_time_fraction(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return self.proof_solver_time_seconds / self.elapsed_seconds

    @property
    def average_policy_best_move_rank_before(self) -> float:
        if self.policy_reorder_events == 0:
            return 0.0
        return self.policy_best_move_rank_before_total / self.policy_reorder_events

    @property
    def average_policy_best_move_rank_after(self) -> float:
        if self.policy_reorder_events == 0:
            return 0.0
        return self.policy_best_move_rank_after_total / self.policy_reorder_events

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "nodes": self.nodes,
            "qnodes": self.quiescence_nodes,
            "total_nodes": self.total_nodes,
            "tt_probes": self.tt_probes,
            "tt_hits": self.tt_hits,
            "tt_cutoffs": self.tt_cutoffs,
            "cutoffs": self.cutoffs,
            "tactical_quiescence_entries": self.tactical_quiescence_entries,
            "tactical_extensions": self.tactical_extensions,
            "immediate_win_nodes": self.immediate_win_nodes,
            "forced_win_nodes": self.forced_win_nodes,
            "forced_loss_nodes": self.forced_loss_nodes,
            "forced_block_nodes": self.forced_block_nodes,
            "forced_block_restrictions": self.forced_block_restrictions,
            "safe_threat_nodes": self.safe_threat_nodes,
            "double_threat_nodes": self.double_threat_nodes,
            "all_poison_nodes": self.all_poison_nodes,
            "poison_moves_filtered": self.poison_moves_filtered,
            "tactics_cache_probes": self.tactics_cache_probes,
            "tactics_cache_hits": self.tactics_cache_hits,
            "tactics_cache_hit_rate": self.tactics_cache_hit_rate,
            "aspiration_researches": self.aspiration_researches,
            "pvs_researches": self.pvs_researches,
            "fail_highs": self.fail_highs,
            "fail_lows": self.fail_lows,
            "history_updates": self.history_updates,
            "killer_updates": self.killer_updates,
            "late_move_researches": self.late_move_researches,
            "quiet_nodes_limited": self.quiet_nodes_limited,
            "quiet_moves_pruned": self.quiet_moves_pruned,
            "expanded_nodes": self.expanded_nodes,
            "legal_moves_total": self.legal_moves_total,
            "searched_moves_total": self.searched_moves_total,
            "average_branching_factor": self.average_branching_factor,
            "average_legal_move_count": self.average_legal_move_count,
            "average_searched_move_count": self.average_searched_move_count,
            "tactical_solver_queries": self.tactical_solver_queries,
            "tactical_solver_cache_hits": self.tactical_solver_cache_hits,
            "tactical_solver_wins": self.tactical_solver_wins,
            "tactical_solver_losses": self.tactical_solver_losses,
            "tactical_solver_unknown": self.tactical_solver_unknown,
            "proof_solver_activations": self.proof_solver_activations,
            "proof_solver_skips": self.proof_solver_skips,
            "quiescence_soft_skip_nodes": self.quiescence_soft_skip_nodes,
            "model_calls_total": self.model_calls_total,
            "model_calls_root": self.model_calls_root,
            "model_calls_pv_quiet": self.model_calls_pv_quiet,
            "model_calls_nonpv_quiet": self.model_calls_nonpv_quiet,
            "model_calls_tactical": self.model_calls_tactical,
            "model_calls_quiescence": self.model_calls_quiescence,
            "model_time_seconds": self.model_time_seconds,
            "model_mean_latency_ms": self.model_mean_latency_ms,
            "model_time_fraction": self.model_time_fraction,
            "tactics_time_seconds": self.tactics_time_seconds,
            "tactics_time_fraction": self.tactics_time_fraction,
            "eval_time_seconds": self.eval_time_seconds,
            "eval_time_fraction": self.eval_time_fraction,
            "ordering_time_seconds": self.ordering_time_seconds,
            "ordering_time_fraction": self.ordering_time_fraction,
            "quiescence_time_seconds": self.quiescence_time_seconds,
            "quiescence_time_fraction": self.quiescence_time_fraction,
            "proof_solver_time_seconds": self.proof_solver_time_seconds,
            "proof_solver_time_fraction": self.proof_solver_time_fraction,
            "policy_reorder_events": self.policy_reorder_events,
            "policy_best_move_rank_before_total": self.policy_best_move_rank_before_total,
            "policy_best_move_rank_after_total": self.policy_best_move_rank_after_total,
            "average_policy_best_move_rank_before": self.average_policy_best_move_rank_before,
            "average_policy_best_move_rank_after": self.average_policy_best_move_rank_after,
            "elapsed_seconds": self.elapsed_seconds,
            "nodes_per_second": self.nodes_per_second,
            "qnodes_per_second": self.qnodes_per_second,
            "aborted": self.aborted,
            "time_limit_abort": self.time_limit_abort,
            "node_limit_abort": self.node_limit_abort,
            "max_depth_completed": self.max_depth_completed,
        }

    def format_summary(self) -> str:
        lines = [
            (
                f"nodes={self.nodes} qnodes={self.quiescence_nodes} total={self.total_nodes} "
                f"time={self.elapsed_seconds:.3f}s nps={self.nodes_per_second:.0f} qnps={self.qnodes_per_second:.0f}"
            ),
            (
                f"tt probes={self.tt_probes} hits={self.tt_hits} cutoffs={self.tt_cutoffs} "
                f"beta_cutoffs={self.cutoffs} fail_high={self.fail_highs} fail_low={self.fail_lows}"
            ),
            (
                f"branching avg_legal={self.average_legal_move_count:.2f} "
                f"avg_searched={self.average_searched_move_count:.2f} "
                f"avg_branch={self.average_branching_factor:.2f}"
            ),
            (
                f"tactics wins={self.immediate_win_nodes} forced_blocks={self.forced_block_nodes} "
                f"safe_threats={self.safe_threat_nodes} double_threats={self.double_threat_nodes} "
                f"solver={self.proof_solver_activations} skips={self.proof_solver_skips} "
                f"qskip={self.quiescence_soft_skip_nodes} "
                f"cache={self.tactics_cache_hits}/{self.tactics_cache_probes}"
            ),
            (
                f"ml calls={self.model_calls_total} root={self.model_calls_root} pv_quiet={self.model_calls_pv_quiet} "
                f"nonpv_quiet={self.model_calls_nonpv_quiet} tactical={self.model_calls_tactical} "
                f"q={self.model_calls_quiescence} mean={self.model_mean_latency_ms:.2f}ms "
                f"wall={self.model_time_seconds:.4f}s frac={self.model_time_fraction:.1%}"
            ),
            (
                f"time tactics={self.tactics_time_seconds:.4f}s eval={self.eval_time_seconds:.4f}s "
                f"ordering={self.ordering_time_seconds:.4f}s quiescence={self.quiescence_time_seconds:.4f}s "
                f"proof={self.proof_solver_time_seconds:.4f}s"
            ),
        ]
        if self.policy_reorder_events:
            lines.append(
                "policy ranks "
                f"before={self.average_policy_best_move_rank_before:.2f} "
                f"after={self.average_policy_best_move_rank_after:.2f} "
                f"events={self.policy_reorder_events}"
            )
        return "\n".join(lines)


@dataclass(slots=True)
class SearchResult:
    best_move: int | None
    score: int
    principal_variation: tuple[int, ...]
    depth: int
    stats: SearchStats

    def to_dict(self) -> dict[str, object]:
        best_move_coord = None
        if self.best_move is not None:
            row, col = index_to_coord(self.best_move, BOARD_SIZE)
            best_move_coord = {"row": row, "col": col}
        return {
            "best_move": self.best_move,
            "best_move_coord": best_move_coord,
            "score": self.score,
            "principal_variation": list(self.principal_variation),
            "depth": self.depth,
            "stats": self.stats.to_dict(),
        }

    def format_summary(self) -> str:
        if self.best_move is None:
            move_text = "best_move=None"
        else:
            row, col = index_to_coord(self.best_move, BOARD_SIZE)
            move_text = f"best_move={self.best_move} ({row}, {col})"
        return (
            f"{move_text} score={self.score} depth={self.depth}\n"
            f"{self.stats.format_summary()}"
        )


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    bound: Bound
    best_move: int | None
    principal_variation: tuple[int, ...] = field(default_factory=tuple)


class SearchAborted(RuntimeError):
    pass


def _position_key(position: Position) -> tuple[int, int, int]:
    side_flag = 0 if position.side_to_move is Color.BLACK else 1
    return position.black_bits, position.white_bits, side_flag


def _occupancy_key(position: Position) -> tuple[int, int]:
    return position.black_bits, position.white_bits


def _side_index(color: Color) -> int:
    return 0 if color is Color.BLACK else 1


def _move_proximity_score(move: int) -> int:
    row, col = index_to_coord(move, BOARD_SIZE)
    center = BOARD_SIZE // 2
    return -abs(row - center) - abs(col - center)


def evaluate(
    position: Position,
    tables: MaskTables = DEFAULT_MASKS,
    snapshot: TacticalSnapshot | None = None,
    opponent_snapshot: TacticalSnapshot | None = None,
    incremental_state: IncrementalState | None = None,
) -> int:
    side = position.side_to_move
    current_tactics = snapshot if snapshot is not None else analyze_tactics(position, tables)
    opponent_position = position.with_side_to_move(side.opponent)
    opponent_tactics = (
        opponent_snapshot if opponent_snapshot is not None else analyze_tactics(opponent_position, tables)
    )

    if incremental_state is not None:
        score = incremental_state.absolute_lookup_score()
        if side is Color.WHITE:
            score = -score
    else:
        fallback_state = IncrementalState.from_position(position, tables)
        score = fallback_state.absolute_lookup_score()
        if side is Color.WHITE:
            score = -score
    score += 3_500 * (len(current_tactics.winning_moves) - len(opponent_tactics.winning_moves))
    score += 2_200 * (len(current_tactics.double_threats) - len(opponent_tactics.double_threats))
    score += 900 * (len(current_tactics.safe_threats) - len(opponent_tactics.safe_threats))
    score += 280 * (len(current_tactics.forced_blocks) - len(opponent_tactics.forced_blocks))
    score += 12 * (len(current_tactics.safe_moves) - len(opponent_tactics.safe_moves))
    score -= 50 * (len(current_tactics.poison_moves) - len(opponent_tactics.poison_moves))

    return score


class SearchEngine:
    def __init__(
        self,
        tables: MaskTables = DEFAULT_MASKS,
        tactical_depth: int = 4,
        learned_evaluator: Any | None = None,
        learned_eval_weight: float = 0.35,
        learned_policy_max_ply: int | None = None,
        learned_value_max_ply: int | None = None,
    ) -> None:
        self.tables = tables
        self.tactical_depth = tactical_depth
        self.learned_evaluator = learned_evaluator
        self.learned_eval_weight = learned_eval_weight
        self.learned_policy_max_ply = learned_policy_max_ply
        self.learned_value_max_ply = learned_value_max_ply
        self.tt: dict[tuple[int, int, int], TTEntry] = {}
        self.tactics_cache: dict[tuple[int, int, int, int], TacticalSnapshot] = {}
        self.tactics_pair_cache: dict[tuple[int, int, int], tuple[TacticalSnapshot, TacticalSnapshot]] = {}
        self.history: list[list[int]] = [[0] * BOARD_CELLS for _ in range(2)]
        self.killers: dict[int, list[int | None]] = {}
        self.stats = SearchStats()
        self.tactical_solver = TacticalSolver(
            tables=self.tables,
            tactics_fn=self._tactics,
            key_fn=_position_key,
            limit_check=self._check_limits,
        )
        self._deadline: float | None = None
        self._node_budget: int | None = None
        self._visited_nodes = 0

    def _search_incremental_state(self, position: Position) -> IncrementalState:
        return IncrementalState.from_position(position, self.tables)

    def search(
        self,
        position: Position,
        max_depth: int,
        max_time_ms: int | None = None,
        max_nodes: int | None = None,
    ) -> SearchResult:
        self.stats = SearchStats()
        self.tactics_cache = {}
        self.tactics_pair_cache = {}
        self.killers = {}
        self.tactical_solver.reset()
        if self.learned_evaluator is not None and hasattr(self.learned_evaluator, "reset"):
            self.learned_evaluator.reset()
        self._visited_nodes = 0
        started_at = time.perf_counter()
        self._deadline = None if max_time_ms is None else time.perf_counter() + (max_time_ms / 1000.0)
        self._node_budget = max_nodes
        incremental_state = self._search_incremental_state(position)

        fallback_move, fallback_score, fallback_line = self._fallback(position, incremental_state)
        best_move = fallback_move
        best_score = fallback_score
        principal_variation = fallback_line

        try:
            for depth in range(1, max_depth + 1):
                try:
                    if depth < 5 or not principal_variation or abs(best_score) >= MATE_SCORE - 2_000:
                        score, line = self._negamax(
                            position,
                            incremental_state,
                            depth,
                            -MATE_SCORE,
                            MATE_SCORE,
                            0,
                            True,
                        )
                    else:
                        score, line = self._aspiration_search(position, incremental_state, depth, best_score)
                except SearchAborted:
                    self.stats.aborted = True
                    break

                if line:
                    best_move = line[0]
                    principal_variation = line
                best_score = score
                self.stats.max_depth_completed = depth
        finally:
            self.stats.elapsed_seconds = time.perf_counter() - started_at
            self._deadline = None
            self._node_budget = None

        return SearchResult(
            best_move=best_move,
            score=best_score,
            principal_variation=principal_variation,
            depth=self.stats.max_depth_completed,
            stats=self.stats,
        )

    def _aspiration_search(
        self,
        position: Position,
        incremental_state: IncrementalState,
        depth: int,
        guess: int,
    ) -> tuple[int, tuple[int, ...]]:
        window = ASPIRATION_WINDOW
        alpha = max(-MATE_SCORE, guess - window)
        beta = min(MATE_SCORE, guess + window)

        while True:
            score, line = self._negamax(position, incremental_state, depth, alpha, beta, 0, True)
            if alpha < score < beta:
                return score, line

            self.stats.aspiration_researches += 1
            window *= 2
            alpha = max(-MATE_SCORE, guess - window)
            beta = min(MATE_SCORE, guess + window)

    def _negamax(
        self,
        position: Position,
        incremental_state: IncrementalState,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
        is_pv: bool,
    ) -> tuple[int, tuple[int, ...]]:
        self.stats.nodes += 1
        self._visited_nodes += 1
        self._check_limits()
        alpha_orig = alpha
        beta_orig = beta
        key = _position_key(position)
        self.stats.tt_probes += 1
        tt_entry = self.tt.get(key)
        if tt_entry and tt_entry.depth >= depth:
            self.stats.tt_hits += 1
            if tt_entry.bound is Bound.EXACT:
                return tt_entry.score, tt_entry.principal_variation
            if tt_entry.bound is Bound.LOWER:
                alpha = max(alpha, tt_entry.score)
            elif tt_entry.bound is Bound.UPPER:
                beta = min(beta, tt_entry.score)
            if alpha >= beta:
                self.stats.tt_cutoffs += 1
                return tt_entry.score, tt_entry.principal_variation

        if position.empty_count == 0:
            return self._evaluate_position(position, incremental_state, ply=ply, is_pv=is_pv), ()
        if depth == 0:
            return self._quiescence(position, incremental_state, alpha, beta, ply, self.tactical_depth, is_pv)

        snapshot = self._tactics(position, incremental_state)
        self._record_snapshot(snapshot)
        forced = self._forced_outcome(
            position,
            incremental_state,
            snapshot,
            ply,
            tt_entry.best_move if tt_entry else None,
            is_pv,
        )
        if forced is not None:
            return forced
        solved = self._tactical_proof(position, snapshot, ply, in_quiescence=False)
        if solved is not None:
            return solved

        ordered_moves = self._ordered_search_moves(
            position,
            incremental_state,
            snapshot,
            depth,
            ply,
            tt_entry.best_move if tt_entry else None,
            is_pv,
        )
        self._record_expansion(position.empty_count, len(ordered_moves))

        best_score = -MATE_SCORE
        best_line: tuple[int, ...] = ()
        best_move: int | None = None

        for move_index, move in enumerate(ordered_moves):
            result = incremental_state.move_result(move, position.side_to_move)
            if result is MoveResult.WIN:
                score = MATE_SCORE - ply
                line = (move,)
            elif result is MoveResult.LOSS:
                score = -MATE_SCORE + ply
                line = (move,)
            else:
                undo = incremental_state.make_move(move, position.side_to_move)
                next_position = incremental_state.to_position()
                is_quiet = self._is_quiet_move(snapshot, move)
                try:
                    if move_index == 0:
                        child_score, child_line = self._negamax(
                            next_position,
                            incremental_state,
                            depth - 1,
                            -beta,
                            -alpha,
                            ply + 1,
                            is_pv,
                        )
                        score = -child_score
                        line = (move,) + child_line
                    else:
                        if (
                            depth >= LATE_MOVE_REDUCTION_MIN_DEPTH
                            and move_index >= LATE_MOVE_REDUCTION_AFTER
                            and is_quiet
                        ):
                            reduced_depth = max(depth - 2, 0)
                            child_score, child_line = self._negamax(
                                next_position,
                                incremental_state,
                                reduced_depth,
                                -alpha - 1,
                                -alpha,
                                ply + 1,
                                False,
                            )
                            score = -child_score
                            line = (move,) + child_line
                            if score > alpha:
                                self.stats.late_move_researches += 1
                                child_score, child_line = self._negamax(
                                    next_position,
                                    incremental_state,
                                    depth - 1,
                                    -beta,
                                    -alpha,
                                    ply + 1,
                                    False,
                                )
                                score = -child_score
                                line = (move,) + child_line
                        else:
                            child_score, child_line = self._negamax(
                                next_position,
                                incremental_state,
                                depth - 1,
                                -alpha - 1,
                                -alpha,
                                ply + 1,
                                False,
                            )
                            score = -child_score
                            line = (move,) + child_line
                            if alpha < score < beta:
                                self.stats.pvs_researches += 1
                                child_score, child_line = self._negamax(
                                    next_position,
                                    incremental_state,
                                    depth - 1,
                                    -beta,
                                    -alpha,
                                    ply + 1,
                                    False,
                                )
                                score = -child_score
                                line = (move,) + child_line
                finally:
                    incremental_state.unmake_move(undo)

            if score > best_score:
                best_score = score
                best_line = line
                best_move = move

            alpha = max(alpha, best_score)
            if alpha >= beta:
                self.stats.cutoffs += 1
                self._record_cutoff(position, snapshot, move, depth, ply)
                break

        if best_move is None:
            return self._evaluate_position(position, incremental_state, ply=ply, is_pv=is_pv), ()

        if best_score <= alpha_orig:
            bound = Bound.UPPER
            self.stats.fail_lows += 1
        elif best_score >= beta_orig:
            bound = Bound.LOWER
            self.stats.fail_highs += 1
        else:
            bound = Bound.EXACT
        self.tt[key] = TTEntry(
            depth=depth,
            score=best_score,
            bound=bound,
            best_move=best_move,
            principal_variation=best_line,
        )
        return best_score, best_line

    def _quiescence(
        self,
        position: Position,
        incremental_state: IncrementalState,
        alpha: int,
        beta: int,
        ply: int,
        remaining_depth: int,
        is_pv: bool,
    ) -> tuple[int, tuple[int, ...]]:
        started_at = time.perf_counter()
        try:
            self.stats.quiescence_nodes += 1
            self.stats.tactical_quiescence_entries += 1
            self._visited_nodes += 1
            self._check_limits()
            snapshot = self._tactics(position, incremental_state)
            self._record_snapshot(snapshot)

            forced = self._forced_outcome(
                position,
                incremental_state,
                snapshot,
                ply,
                None,
                is_pv,
                in_quiescence=True,
            )
            if forced is not None:
                return forced
            solved = self._tactical_proof(position, snapshot, ply, in_quiescence=True)
            if solved is not None:
                return solved

            stand_pat = self._evaluate_position(
                position,
                incremental_state,
                snapshot,
                ply,
                is_pv,
                in_quiescence=True,
            )
            if remaining_depth == 0 or not snapshot.urgent:
                return stand_pat, ()
            if stand_pat >= beta:
                return stand_pat, ()
            alpha_gap = alpha - stand_pat
            if stand_pat > alpha:
                alpha = stand_pat

            if self._should_skip_soft_quiescence(snapshot, alpha_gap, is_pv):
                self.stats.quiescence_soft_skip_nodes += 1
                return stand_pat, ()

            candidates = self._quiescence_moves(position, incremental_state, snapshot, ply, is_pv)
            if not candidates:
                return stand_pat, ()

            self._record_expansion(position.empty_count, len(candidates))
            self.stats.tactical_extensions += 1
            best_score = stand_pat
            best_line: tuple[int, ...] = ()

            for move in candidates:
                result = incremental_state.move_result(move, position.side_to_move)
                if result is MoveResult.WIN:
                    score = MATE_SCORE - ply
                    line = (move,)
                elif result is MoveResult.LOSS:
                    score = -MATE_SCORE + ply
                    line = (move,)
                else:
                    undo = incremental_state.make_move(move, position.side_to_move)
                    next_position = incremental_state.to_position()
                    try:
                        child_score, child_line = self._quiescence(
                            next_position,
                            incremental_state,
                            -beta,
                            -alpha,
                            ply + 1,
                            remaining_depth - 1,
                            is_pv and move == candidates[0],
                        )
                        score = -child_score
                        line = (move,) + child_line
                    finally:
                        incremental_state.unmake_move(undo)

                if score > best_score:
                    best_score = score
                    best_line = line
                if best_score > alpha:
                    alpha = best_score
                if alpha >= beta:
                    self.stats.cutoffs += 1
                    break

            return best_score, best_line
        finally:
            self.stats.quiescence_time_seconds += time.perf_counter() - started_at

    def _forced_outcome(
        self,
        position: Position,
        incremental_state: IncrementalState,
        snapshot: TacticalSnapshot,
        ply: int,
        tt_move: int | None,
        is_pv: bool,
        in_quiescence: bool = False,
    ) -> tuple[int, tuple[int, ...]] | None:
        if snapshot.winning_moves:
            self.stats.forced_win_nodes += 1
            ordered = self._rank_moves(
                position,
                incremental_state,
                snapshot,
                list(snapshot.winning_moves),
                ply,
                tt_move,
                is_pv,
                in_quiescence,
            )
            return MATE_SCORE - ply, (ordered[0],)

        if snapshot.safe_moves:
            if snapshot.opponent_winning_moves and not snapshot.forced_blocks:
                self.stats.forced_loss_nodes += 1
                ordered = self._rank_moves(
                    position,
                    incremental_state,
                    snapshot,
                    list(snapshot.safe_moves),
                    ply,
                    tt_move,
                    is_pv,
                    in_quiescence,
                )
                return -MATE_SCORE + ply + 1, (ordered[0],)
            return None

        if snapshot.poison_moves:
            self.stats.all_poison_nodes += 1
            ordered = self._rank_moves(
                position,
                incremental_state,
                snapshot,
                list(snapshot.poison_moves),
                ply,
                tt_move,
                is_pv,
                in_quiescence,
            )
            return -MATE_SCORE + ply, (ordered[0],)

        return None

    def _ordered_search_moves(
        self,
        position: Position,
        incremental_state: IncrementalState,
        snapshot: TacticalSnapshot,
        depth: int,
        ply: int,
        tt_move: int | None,
        is_pv: bool,
    ) -> list[int]:
        started_at = time.perf_counter()
        try:
            if snapshot.opponent_winning_moves and snapshot.forced_blocks:
                self.stats.forced_block_nodes += 1
                self.stats.forced_block_restrictions += 1
                self.stats.poison_moves_filtered += len(snapshot.poison_moves)
                return self._rank_moves(
                    position,
                    incremental_state,
                    snapshot,
                    list(snapshot.forced_blocks),
                    ply,
                    tt_move,
                    is_pv,
                )

            if snapshot.safe_moves:
                self.stats.poison_moves_filtered += len(snapshot.poison_moves)
                priority: list[int] = []
                seen: set[int] = set()
                for bucket in (snapshot.double_threats, snapshot.safe_threats):
                    for move in bucket:
                        if move not in seen:
                            priority.append(move)
                            seen.add(move)

                quiet_moves = [move for move in snapshot.safe_moves if move not in seen]
                ranked_priority = self._rank_moves(
                    position,
                    incremental_state,
                    snapshot,
                    priority,
                    ply,
                    tt_move,
                    is_pv,
                )
                ranked_quiet = self._rank_moves(
                    position,
                    incremental_state,
                    snapshot,
                    quiet_moves,
                    ply,
                    tt_move,
                    is_pv,
                )

                quiet_limit = self._quiet_move_limit(position, snapshot, depth, ply)
                if quiet_limit < len(ranked_quiet):
                    self.stats.quiet_nodes_limited += 1
                    self.stats.quiet_moves_pruned += len(ranked_quiet) - quiet_limit
                    ranked_quiet = ranked_quiet[:quiet_limit]

                return ranked_priority + ranked_quiet

            return self._rank_moves(
                position,
                incremental_state,
                snapshot,
                list(snapshot.candidate_moves),
                ply,
                tt_move,
                is_pv,
            )
        finally:
            self.stats.ordering_time_seconds += time.perf_counter() - started_at

    def _quiescence_moves(
        self,
        position: Position,
        incremental_state: IncrementalState,
        snapshot: TacticalSnapshot,
        ply: int,
        is_pv: bool,
    ) -> list[int]:
        if snapshot.opponent_winning_moves:
            return self._rank_moves(
                position,
                incremental_state,
                snapshot,
                list(snapshot.forced_blocks),
                ply,
                None,
                is_pv,
                True,
            )
        if snapshot.double_threats:
            return self._rank_moves(
                position,
                incremental_state,
                snapshot,
                list(snapshot.double_threats),
                ply,
                None,
                is_pv,
                True,
            )
        if snapshot.safe_threats:
            ranked = self._rank_moves(
                position,
                incremental_state,
                snapshot,
                list(snapshot.safe_threats),
                ply,
                None,
                is_pv,
                True,
            )
            return ranked[:QUIESCENCE_SAFE_THREAT_LIMIT]
        return []

    def _should_skip_soft_quiescence(
        self,
        snapshot: TacticalSnapshot,
        alpha_gap: int,
        is_pv: bool,
    ) -> bool:
        if is_pv:
            return False
        if snapshot.opponent_winning_moves or snapshot.double_threats or not snapshot.safe_threats:
            return False
        if len(snapshot.safe_threats) > 1:
            return True
        if len(snapshot.safe_moves) > QUIESCENCE_SAFE_THREAT_MAX_SAFE_MOVES:
            return True
        return alpha_gap > QUIESCENCE_SAFE_THREAT_ALPHA_MARGIN

    def _rank_moves(
        self,
        position: Position,
        incremental_state: IncrementalState,
        snapshot: TacticalSnapshot,
        moves: list[int],
        ply: int,
        tt_move: int | None,
        is_pv: bool,
        in_quiescence: bool = False,
    ) -> list[int]:
        if not moves:
            return moves

        winning_moves = set(snapshot.winning_moves)
        forced_blocks = set(snapshot.forced_blocks)
        double_threats = set(snapshot.double_threats)
        safe_threats = set(snapshot.safe_threats)
        safe_moves = set(snapshot.safe_moves)
        side_index = _side_index(position.side_to_move)
        killer0, killer1 = self.killers.get(ply, [None, None])
        future_wins_by_move = snapshot.future_wins_by_move
        opponent_wins_after_move = snapshot.opponent_wins_after_move
        history_scores = self.history[side_index]
        policy_bonuses = self._policy_move_bonuses(
            position,
            incremental_state,
            snapshot,
            moves,
            ply,
            is_pv,
            in_quiescence,
        )

        def base_score(move: int) -> int:
            if tt_move is not None and move == tt_move:
                return 10_000_000

            score = _move_proximity_score(move)
            if move in winning_moves:
                return WIN_MOVE_BONUS + score
            if move in forced_blocks:
                score += BLOCK_MOVE_BONUS
            if move in double_threats:
                score += DOUBLE_THREAT_BONUS
            elif move in safe_threats:
                score += SAFE_THREAT_BONUS
            if move in safe_moves:
                score += SAFE_MOVE_BONUS
            else:
                score -= POISON_MOVE_PENALTY

            score += len(future_wins_by_move.get(move, ())) * FUTURE_WIN_BONUS
            score -= len(opponent_wins_after_move.get(move, ())) * OPPONENT_WIN_REMAINING_PENALTY
            score += len(self.tables.incident5[move]) * FIVE_MASK_LOCAL_BONUS
            score += len(self.tables.incident4[move]) * FOUR_MASK_LOCAL_BONUS
            score += history_scores[move]

            if move == killer0:
                score += KILLER_MOVE_BONUS
            elif move == killer1:
                score += SECOND_KILLER_BONUS

            return score

        base_scores = {move: base_score(move) for move in moves}

        def final_score(move: int) -> int:
            if tt_move is not None and move == tt_move:
                return base_scores[move]
            if move in winning_moves:
                return base_scores[move]
            return base_scores[move] + policy_bonuses.get(move, 0)

        if policy_bonuses:
            before_policy = sorted(moves, key=lambda move: base_scores[move], reverse=True)
            after_policy = sorted(moves, key=final_score, reverse=True)
            chosen_move = after_policy[0]
            self.stats.policy_reorder_events += 1
            self.stats.policy_best_move_rank_before_total += before_policy.index(chosen_move) + 1
            self.stats.policy_best_move_rank_after_total += after_policy.index(chosen_move) + 1
            moves[:] = after_policy
            return moves

        moves.sort(key=lambda move: base_scores[move], reverse=True)
        return moves

    def _record_cutoff(
        self,
        position: Position,
        snapshot: TacticalSnapshot,
        move: int,
        depth: int,
        ply: int,
    ) -> None:
        if not self._is_quiet_move(snapshot, move):
            return

        side_index = _side_index(position.side_to_move)
        self.history[side_index][move] = min(self.history[side_index][move] + depth * depth, 1_000_000)
        self.stats.history_updates += 1

        killers = self.killers.setdefault(ply, [None, None])
        if killers[0] != move:
            killers[1] = killers[0]
            killers[0] = move
            self.stats.killer_updates += 1

    def _is_quiet_move(self, snapshot: TacticalSnapshot, move: int) -> bool:
        return (
            move in snapshot.safe_moves
            and move not in snapshot.forced_blocks
            and move not in snapshot.safe_threats
            and move not in snapshot.double_threats
        )

    def _fallback(
        self,
        position: Position,
        incremental_state: IncrementalState,
    ) -> tuple[int | None, int, tuple[int, ...]]:
        if position.empty_count == 0:
            return None, self._evaluate_position(position, incremental_state, ply=0, is_pv=True), ()

        snapshot = self._tactics(position, incremental_state)
        if snapshot.opponent_winning_moves and snapshot.forced_blocks:
            moves = list(snapshot.forced_blocks)
        elif snapshot.safe_moves:
            priority: list[int] = []
            seen: set[int] = set()
            for bucket in (snapshot.double_threats, snapshot.safe_threats):
                for move in bucket:
                    if move not in seen:
                        priority.append(move)
                        seen.add(move)
            quiet_moves = [move for move in snapshot.safe_moves if move not in seen]
            ranked_priority = self._rank_moves(position, incremental_state, snapshot, priority, 0, None, True)
            ranked_quiet = self._rank_moves(position, incremental_state, snapshot, quiet_moves, 0, None, True)
            quiet_limit = self._quiet_move_limit(position, snapshot, 1, 0)
            moves = ranked_priority + ranked_quiet[:quiet_limit]
        else:
            moves = list(snapshot.candidate_moves)
        ordered = self._rank_moves(position, incremental_state, snapshot, moves, 0, None, True)
        best_move = ordered[0] if ordered else None
        score = self._evaluate_position(position, incremental_state, snapshot, 0, True)
        line = (best_move,) if best_move is not None else ()
        return best_move, score, line

    def _quiet_move_limit(
        self,
        position: Position,
        snapshot: TacticalSnapshot,
        depth: int,
        ply: int,
    ) -> int:
        if position.empty_count <= 24:
            return len(snapshot.safe_moves)

        limit = QUIET_MOVE_BASE_LIMIT + QUIET_MOVE_DEPTH_FACTOR * depth
        if ply == 0:
            limit += QUIET_MOVE_ROOT_BONUS

        if snapshot.safe_threats or snapshot.double_threats:
            limit = min(limit, TACTICAL_QUIET_TAIL)

        return max(TACTICAL_QUIET_TAIL, limit)

    def _check_limits(self) -> None:
        if self._node_budget is not None and self._visited_nodes >= self._node_budget:
            self.stats.node_limit_abort = True
            raise SearchAborted()

        if self._deadline is None:
            return

        if self._visited_nodes % SEARCH_LIMIT_CHECK_INTERVAL == 0 and time.perf_counter() >= self._deadline:
            self.stats.time_limit_abort = True
            raise SearchAborted()

    def _tactical_proof(
        self,
        position: Position,
        snapshot: TacticalSnapshot,
        ply: int,
        in_quiescence: bool,
    ) -> tuple[int, tuple[int, ...]] | None:
        if not self._should_probe_tactical_solver(snapshot, in_quiescence):
            self.stats.proof_solver_skips += 1
            return None

        self.stats.proof_solver_activations += 1
        started_at = time.perf_counter()
        try:
            result = self.tactical_solver.solve(position, TACTICAL_SOLVER_PLIES)
            self.stats.tactical_solver_queries = self.tactical_solver.stats.queries
            self.stats.tactical_solver_cache_hits = self.tactical_solver.stats.cache_hits
            self.stats.tactical_solver_wins = self.tactical_solver.stats.wins_proven
            self.stats.tactical_solver_losses = self.tactical_solver.stats.losses_proven
            self.stats.tactical_solver_unknown = self.tactical_solver.stats.unknown

            if result.outcome is TacticalOutcome.WIN:
                line = result.line
                return MATE_SCORE - ply, line
            if result.outcome is TacticalOutcome.LOSS:
                return -MATE_SCORE + ply, ()
            return None
        finally:
            self.stats.proof_solver_time_seconds += time.perf_counter() - started_at

    def _should_probe_tactical_solver(
        self,
        snapshot: TacticalSnapshot,
        in_quiescence: bool,
    ) -> bool:
        if snapshot.double_threats:
            return True

        if snapshot.opponent_winning_moves:
            return bool(snapshot.forced_blocks) and len(snapshot.forced_blocks) <= PROOF_MAX_FORCED_BLOCKS

        if in_quiescence:
            return False

        return bool(
            snapshot.safe_threats
            and len(snapshot.safe_threats) <= PROOF_MAX_SAFE_THREATS
            and len(snapshot.safe_moves) <= PROOF_MAX_SAFE_MOVES
        )

    def _tactics(
        self,
        position: Position,
        incremental_state: IncrementalState | None = None,
        include_move_maps: bool = True,
    ) -> TacticalSnapshot:
        cache_flag = 1 if include_move_maps else 0
        key = (*_position_key(position), cache_flag)
        self.stats.tactics_cache_probes += 1
        snapshot = self.tactics_cache.get(key)
        if snapshot is not None:
            self.stats.tactics_cache_hits += 1
            return snapshot

        occupancy_key = _occupancy_key(position)
        pair = self.tactics_pair_cache.get((*occupancy_key, cache_flag))
        if pair is not None:
            self.stats.tactics_cache_hits += 1
            black_snapshot, white_snapshot = pair
        else:
            started_at = time.perf_counter()
            if incremental_state is not None:
                ordered_candidates = incremental_state.ordered_candidate_moves()
                black_summary, white_summary = incremental_state.paired_tactical_summaries(
                    ordered_candidates,
                    include_move_maps=include_move_maps,
                )
                black_snapshot = TacticalSnapshot(
                    candidate_moves=black_summary.candidate_moves,
                    safe_moves=black_summary.safe_moves,
                    winning_moves=black_summary.winning_moves,
                    poison_moves=black_summary.poison_moves,
                    forced_blocks=black_summary.forced_blocks,
                    safe_threats=black_summary.safe_threats,
                    double_threats=black_summary.double_threats,
                    opponent_winning_moves=black_summary.opponent_winning_moves,
                    future_wins_by_move=black_summary.future_wins_by_move,
                    opponent_wins_after_move=black_summary.opponent_wins_after_move,
                )
                white_snapshot = TacticalSnapshot(
                    candidate_moves=white_summary.candidate_moves,
                    safe_moves=white_summary.safe_moves,
                    winning_moves=white_summary.winning_moves,
                    poison_moves=white_summary.poison_moves,
                    forced_blocks=white_summary.forced_blocks,
                    safe_threats=white_summary.safe_threats,
                    double_threats=white_summary.double_threats,
                    opponent_winning_moves=white_summary.opponent_winning_moves,
                    future_wins_by_move=white_summary.future_wins_by_move,
                    opponent_wins_after_move=white_summary.opponent_wins_after_move,
                )
            else:
                black_position = position.with_side_to_move(Color.BLACK)
                white_position = position.with_side_to_move(Color.WHITE)
                black_snapshot = analyze_tactics(black_position, self.tables, include_move_maps=include_move_maps)
                white_snapshot = analyze_tactics(white_position, self.tables, include_move_maps=include_move_maps)
            self.stats.tactics_time_seconds += time.perf_counter() - started_at
            self.tactics_pair_cache[(*occupancy_key, cache_flag)] = (black_snapshot, white_snapshot)

        black_key = (*_position_key(position.with_side_to_move(Color.BLACK)), cache_flag)
        white_key = (*_position_key(position.with_side_to_move(Color.WHITE)), cache_flag)
        self.tactics_cache[black_key] = black_snapshot
        self.tactics_cache[white_key] = white_snapshot
        return black_snapshot if position.side_to_move is Color.BLACK else white_snapshot

    def _evaluate_position(
        self,
        position: Position,
        incremental_state: IncrementalState | None = None,
        snapshot: TacticalSnapshot | None = None,
        ply: int = 0,
        is_pv: bool = False,
        in_quiescence: bool = False,
    ) -> int:
        started_at = time.perf_counter()
        try:
            current_snapshot = (
                snapshot
                if snapshot is not None
                else self._tactics(position, incremental_state, include_move_maps=False)
            )
            opponent_snapshot = self._tactics(
                position.with_side_to_move(position.side_to_move.opponent),
                incremental_state,
                include_move_maps=False,
            )
            score = evaluate(
                position,
                self.tables,
                current_snapshot,
                opponent_snapshot,
                incremental_state,
            )
            if (
                self.learned_evaluator is None
                or self.learned_eval_weight == 0.0
                or not self._allow_learned_value(ply)
            ):
                return score

            model_bucket = self._model_call_bucket(current_snapshot, ply, is_pv, in_quiescence)
            model_started_at = time.perf_counter()
            learned_score = self.learned_evaluator.evaluate(position, current_snapshot, opponent_snapshot)
            self._record_model_call(model_bucket, time.perf_counter() - model_started_at)
            return score + int(round(self.learned_eval_weight * learned_score))
        finally:
            self.stats.eval_time_seconds += time.perf_counter() - started_at

    def _policy_move_bonuses(
        self,
        position: Position,
        incremental_state: IncrementalState,
        snapshot: TacticalSnapshot,
        moves: list[int],
        ply: int,
        is_pv: bool,
        in_quiescence: bool = False,
    ) -> dict[int, int]:
        if (
            self.learned_evaluator is None
            or len(moves) <= 1
            or not self._allow_learned_policy(ply)
        ):
            return {}

        opponent_snapshot = self._tactics(
            position.with_side_to_move(position.side_to_move.opponent),
            incremental_state,
            include_move_maps=False,
        )
        model_bucket = self._model_call_bucket(snapshot, ply, is_pv, in_quiescence)
        started_at = time.perf_counter()
        bonuses = self.learned_evaluator.move_priors(position, moves, snapshot, opponent_snapshot)
        self._record_model_call(model_bucket, time.perf_counter() - started_at)
        return bonuses

    def _record_snapshot(self, snapshot: TacticalSnapshot) -> None:
        if snapshot.winning_moves:
            self.stats.immediate_win_nodes += 1
        if snapshot.safe_threats:
            self.stats.safe_threat_nodes += 1
        if snapshot.double_threats:
            self.stats.double_threat_nodes += 1

    def _record_expansion(self, legal_moves: int, searched_moves: int) -> None:
        self.stats.expanded_nodes += 1
        self.stats.legal_moves_total += legal_moves
        self.stats.searched_moves_total += searched_moves

    def _is_quiet_node(self, snapshot: TacticalSnapshot) -> bool:
        return not (
            snapshot.winning_moves
            or snapshot.opponent_winning_moves
            or snapshot.forced_blocks
            or snapshot.safe_threats
            or snapshot.double_threats
        )

    def _model_call_bucket(
        self,
        snapshot: TacticalSnapshot,
        ply: int,
        is_pv: bool,
        in_quiescence: bool,
    ) -> str:
        if in_quiescence:
            return "quiescence"
        if ply == 0:
            return "root"
        if not self._is_quiet_node(snapshot):
            return "tactical"
        if is_pv:
            return "pv_quiet"
        return "nonpv_quiet"

    def _record_model_call(self, bucket: str, elapsed_seconds: float) -> None:
        self.stats.model_calls_total += 1
        self.stats.model_time_seconds += elapsed_seconds
        if bucket == "root":
            self.stats.model_calls_root += 1
        elif bucket == "pv_quiet":
            self.stats.model_calls_pv_quiet += 1
        elif bucket == "nonpv_quiet":
            self.stats.model_calls_nonpv_quiet += 1
        elif bucket == "quiescence":
            self.stats.model_calls_quiescence += 1
        else:
            self.stats.model_calls_tactical += 1

    def _allow_learned_policy(self, ply: int) -> bool:
        return self.learned_policy_max_ply is None or ply <= self.learned_policy_max_ply

    def _allow_learned_value(self, ply: int) -> bool:
        return self.learned_value_max_ply is None or ply <= self.learned_value_max_ply
