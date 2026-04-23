from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .board import BOARD_CELLS, BOARD_SIZE, index_to_coord
from .incremental import IncrementalState
from .masks import DEFAULT_MASKS, MaskTables
from .position import Color, MoveResult, Position, play_move
from .solver import TacticalOutcome, TacticalSolver
from .tactical_detail import TacticalDetail, resolve_tactical_detail
from .tactics import TacticalSnapshot, analyze_tactics

MATE_SCORE = 1_000_000
ASPIRATION_WINDOW = 512
WIN_MOVE_BONUS = 250_000
BLOCK_MOVE_BONUS = 180_000
DOUBLE_THREAT_BONUS = 120_000
SAFE_THREAT_BONUS = 70_000
CRITICAL_RESTRICTED_BUILD_BONUS = 52_000
CRITICAL_RESTRICTED_RESPONSE_BONUS = 55_000
SAFE_MOVE_BONUS = 20_000
KILLER_MOVE_BONUS = 40_000
SECOND_KILLER_BONUS = 25_000
FUTURE_WIN_BONUS = 8_000
POISON_MOVE_PENALTY = 200_000
FIVE_MASK_LOCAL_BONUS = 16
FOUR_MASK_LOCAL_BONUS = 6
OPPONENT_WIN_REMAINING_PENALTY = 90_000
UNANSWERABLE_RESTRICTED_LINE_BONUS = 1_200
HISTORY_BONUS_UNIT = 128
HISTORY_MALUS_DIVISOR = 2
HISTORY_SCORE_LIMIT = 120_000
QUIESCENCE_SAFE_THREAT_LIMIT = 3
QUIESCENCE_SAFE_THREAT_MAX_SAFE_MOVES = 8
QUIESCENCE_SAFE_THREAT_ALPHA_MARGIN = 600
QUIESCENCE_NONPV_SAFE_THREAT_LIMIT = 1
QUIESCENCE_NONPV_SAFE_THREAT_NEGATIVE_ALPHA_LIMIT = 2
QUIESCENCE_NONPV_SAFE_THREAT_WIDE_MAX_SAFE_MOVES = 5
QUIESCENCE_NONPV_SAFE_THREAT_WIDE_ALPHA_MARGIN = 100
QUIESCENCE_NONPV_SAFE_THREAT_FRONTIER_DEPTH = 2
QUIESCENCE_CRITICAL_RESPONSE_LIMIT = 2
LATE_MOVE_REDUCTION_MIN_DEPTH = 3
LATE_MOVE_REDUCTION_AFTER = 4
FUTILITY_PRUNING_MAX_DEPTH = 2
FUTILITY_MARGIN_BASE = 900
FUTILITY_MARGIN_PER_DEPTH = 1_500
LATE_MOVE_PRUNING_MAX_DEPTH = 3
SEARCH_LIMIT_CHECK_INTERVAL = 256
QUIET_MOVE_BASE_LIMIT = 6
QUIET_MOVE_DEPTH_FACTOR = 2
QUIET_MOVE_ROOT_BONUS = 6
TACTICAL_QUIET_TAIL = 4
TACTICAL_SOLVER_PLIES = 8
PROOF_MAX_FORCED_BLOCKS = 2
PROOF_MAX_SAFE_THREATS = 2
PROOF_MAX_SAFE_MOVES = 6
PROOF_NONPV_FORCE_MAX_PLY = 2
PROOF_NONPV_SAFE_THREAT_MAX_PLY = 1
PROOF_NONPV_QUIESCENCE_MAX_PLY = 1

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
    qtt_probes: int = 0
    qtt_hits: int = 0
    qtt_cutoffs: int = 0
    cutoffs: int = 0
    quiescence_nodes: int = 0
    tactical_quiescence_entries: int = 0
    tactical_extensions: int = 0
    quiescence_forced_block_nodes: int = 0
    quiescence_single_forced_block_nodes: int = 0
    quiescence_double_threat_nodes: int = 0
    quiescence_safe_threat_nodes: int = 0
    quiescence_safe_threat_only_nodes: int = 0
    quiescence_forced_block_moves: int = 0
    quiescence_double_threat_moves: int = 0
    quiescence_safe_threat_moves: int = 0
    quiescence_safe_threat_moves_pruned: int = 0
    quiescence_skip_multi_safe_threat_nodes: int = 0
    quiescence_skip_frontier_safe_threat_nodes: int = 0
    quiescence_skip_wide_safe_threat_nodes: int = 0
    quiescence_skip_alpha_safe_threat_nodes: int = 0
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
    history_malus_updates: int = 0
    killer_updates: int = 0
    late_move_researches: int = 0
    late_move_prunes: int = 0
    futility_prunes: int = 0
    quiet_nodes_limited: int = 0
    quiet_moves_pruned: int = 0
    exact_short_mate_quiet_searches: int = 0
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
            "qtt_probes": self.qtt_probes,
            "qtt_hits": self.qtt_hits,
            "qtt_cutoffs": self.qtt_cutoffs,
            "cutoffs": self.cutoffs,
            "tactical_quiescence_entries": self.tactical_quiescence_entries,
            "tactical_extensions": self.tactical_extensions,
            "quiescence_forced_block_nodes": self.quiescence_forced_block_nodes,
            "quiescence_single_forced_block_nodes": self.quiescence_single_forced_block_nodes,
            "quiescence_double_threat_nodes": self.quiescence_double_threat_nodes,
            "quiescence_safe_threat_nodes": self.quiescence_safe_threat_nodes,
            "quiescence_safe_threat_only_nodes": self.quiescence_safe_threat_only_nodes,
            "quiescence_forced_block_moves": self.quiescence_forced_block_moves,
            "quiescence_double_threat_moves": self.quiescence_double_threat_moves,
            "quiescence_safe_threat_moves": self.quiescence_safe_threat_moves,
            "quiescence_safe_threat_moves_pruned": self.quiescence_safe_threat_moves_pruned,
            "quiescence_skip_multi_safe_threat_nodes": self.quiescence_skip_multi_safe_threat_nodes,
            "quiescence_skip_frontier_safe_threat_nodes": self.quiescence_skip_frontier_safe_threat_nodes,
            "quiescence_skip_wide_safe_threat_nodes": self.quiescence_skip_wide_safe_threat_nodes,
            "quiescence_skip_alpha_safe_threat_nodes": self.quiescence_skip_alpha_safe_threat_nodes,
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
            "history_malus_updates": self.history_malus_updates,
            "killer_updates": self.killer_updates,
            "late_move_researches": self.late_move_researches,
            "late_move_prunes": self.late_move_prunes,
            "futility_prunes": self.futility_prunes,
            "quiet_nodes_limited": self.quiet_nodes_limited,
            "quiet_moves_pruned": self.quiet_moves_pruned,
            "exact_short_mate_quiet_searches": self.exact_short_mate_quiet_searches,
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
                f"qtt={self.qtt_probes}/{self.qtt_hits}/{self.qtt_cutoffs} "
                f"beta_cutoffs={self.cutoffs} fail_high={self.fail_highs} fail_low={self.fail_lows}"
            ),
            (
                f"branching avg_legal={self.average_legal_move_count:.2f} "
                f"avg_searched={self.average_searched_move_count:.2f} "
                f"avg_branch={self.average_branching_factor:.2f}"
            ),
            (
                f"pruning futility={self.futility_prunes} "
                f"lmp={self.late_move_prunes} lmr_re={self.late_move_researches} "
                f"quiet_cap={self.quiet_moves_pruned} "
                f"exact_short_mate={self.exact_short_mate_quiet_searches}"
            ),
            f"ordering history={self.history_updates} malus={self.history_malus_updates} killers={self.killer_updates}",
            (
                f"tactics wins={self.immediate_win_nodes} forced_blocks={self.forced_block_nodes} "
                f"safe_threats={self.safe_threat_nodes} double_threats={self.double_threat_nodes} "
                f"solver={self.proof_solver_activations} skips={self.proof_solver_skips} "
                f"qskip={self.quiescence_soft_skip_nodes} "
                f"cache={self.tactics_cache_hits}/{self.tactics_cache_probes}"
            ),
            (
                f"qmix forced={self.quiescence_forced_block_nodes}/{self.quiescence_forced_block_moves} "
                f"single_forced={self.quiescence_single_forced_block_nodes} "
                f"double={self.quiescence_double_threat_nodes}/{self.quiescence_double_threat_moves} "
                f"safe={self.quiescence_safe_threat_nodes}/{self.quiescence_safe_threat_moves} "
                f"safe_only={self.quiescence_safe_threat_only_nodes} "
                f"safe_pruned={self.quiescence_safe_threat_moves_pruned} "
                f"skip_multi={self.quiescence_skip_multi_safe_threat_nodes} "
                f"skip_frontier={self.quiescence_skip_frontier_safe_threat_nodes} "
                f"skip_wide={self.quiescence_skip_wide_safe_threat_nodes} "
                f"skip_alpha={self.quiescence_skip_alpha_safe_threat_nodes}"
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


@dataclass(frozen=True, slots=True)
class RootMoveScore:
    move: int
    score: int


@dataclass(slots=True)
class SearchResult:
    best_move: int | None
    score: int
    principal_variation: tuple[int, ...]
    depth: int
    stats: SearchStats
    root_move_scores: tuple[RootMoveScore, ...] = field(default_factory=tuple)

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
            "root_move_scores": [
                {
                    "move": root_score.move,
                    "move_coord": {
                        "row": index_to_coord(root_score.move, BOARD_SIZE)[0],
                        "col": index_to_coord(root_score.move, BOARD_SIZE)[1],
                    },
                    "score": root_score.score,
                }
                for root_score in self.root_move_scores
            ],
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
    score += current_tactics.restricted_pressure - opponent_tactics.restricted_pressure
    score += 900 * (current_tactics.critical_restricted_lines - opponent_tactics.critical_restricted_lines)
    if current_tactics.opponent_critical_restricted_lines and not current_tactics.critical_restricted_responses:
        score -= UNANSWERABLE_RESTRICTED_LINE_BONUS * current_tactics.opponent_critical_restricted_lines
    if opponent_tactics.opponent_critical_restricted_lines and not opponent_tactics.critical_restricted_responses:
        score += UNANSWERABLE_RESTRICTED_LINE_BONUS * opponent_tactics.opponent_critical_restricted_lines
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
        self.qtt: dict[tuple[int, int, int], TTEntry] = {}
        self.tactics_cache: dict[tuple[int, int, int, int], TacticalSnapshot] = {}
        self.tactics_pair_cache: dict[tuple[int, int, int], tuple[TacticalSnapshot, TacticalSnapshot]] = {}
        self.history: list[list[int]] = [[0] * BOARD_CELLS for _ in range(2)]
        self.killers: dict[int, list[int | None]] = {}
        self.stats = SearchStats()
        self._static_move_order_scores = tuple(
            _move_proximity_score(move)
            + (len(self.tables.incident5[move]) * FIVE_MASK_LOCAL_BONUS)
            + (len(self.tables.incident4[move]) * FOUR_MASK_LOCAL_BONUS)
            for move in range(BOARD_CELLS)
        )
        self.tactical_solver = TacticalSolver(
            tables=self.tables,
            tactics_fn=lambda position: self._tactics(position, detail=TacticalDetail.BASIC),
            key_fn=_position_key,
            limit_check=self._check_limits,
        )
        self._deadline: float | None = None
        self._node_budget: int | None = None
        self._visited_nodes = 0
        self._analyze_root = False
        self._root_move_scores_current: tuple[RootMoveScore, ...] = ()
        self._root_move_scores_best: tuple[RootMoveScore, ...] = ()

    def _search_incremental_state(self, position: Position) -> IncrementalState:
        return IncrementalState.from_position(position, self.tables)

    def search(
        self,
        position: Position,
        max_depth: int,
        max_time_ms: int | None = None,
        max_nodes: int | None = None,
        analyze_root: bool = False,
    ) -> SearchResult:
        self.stats = SearchStats()
        self.qtt = {}
        self.tactics_cache = {}
        self.tactics_pair_cache = {}
        self.killers = {}
        self.tactical_solver.reset()
        if self.learned_evaluator is not None and hasattr(self.learned_evaluator, "reset"):
            self.learned_evaluator.reset()
        self._visited_nodes = 0
        self._analyze_root = analyze_root
        self._root_move_scores_current = ()
        self._root_move_scores_best = ()
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
                    if analyze_root or depth < 5 or not principal_variation or abs(best_score) >= MATE_SCORE - 2_000:
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
                if analyze_root:
                    self._root_move_scores_best = self._root_move_scores_current
                self.stats.max_depth_completed = depth
        finally:
            self.stats.elapsed_seconds = time.perf_counter() - started_at
            self._deadline = None
            self._node_budget = None
            self._analyze_root = False

        return SearchResult(
            best_move=best_move,
            score=best_score,
            principal_variation=principal_variation,
            depth=self.stats.max_depth_completed,
            stats=self.stats,
            root_move_scores=self._root_move_scores_best,
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
        root_collect = ply == 0 and self._analyze_root
        key = _position_key(position)
        self.stats.tt_probes += 1
        tt_entry = self.tt.get(key)
        if tt_entry and tt_entry.depth >= depth:
            self.stats.tt_hits += 1
            if not root_collect:
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
            return self._quiescence(
                position,
                incremental_state,
                alpha,
                beta,
                ply,
                self.tactical_depth,
                is_pv,
            )

        snapshot = self._tactics(position, incremental_state, detail=TacticalDetail.BASIC)
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
        solved = self._tactical_proof(position, snapshot, ply, in_quiescence=False, is_pv=is_pv)
        if solved is not None:
            return solved

        static_eval: int | None = None
        allow_quiet_pruning = self._allow_quiet_frontier_pruning(snapshot, depth, alpha, beta, is_pv)
        futility_pruning_active = False
        late_move_prune_limit: int | None = None
        if allow_quiet_pruning:
            static_eval = self._evaluate_position(position, incremental_state, snapshot, ply, is_pv)
            futility_pruning_active = static_eval + self._futility_margin(depth) <= alpha
            late_move_prune_limit = self._late_move_prune_limit(depth)

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
        root_scores: list[RootMoveScore] = []
        prior_quiet_moves: list[int] = []
        for move_index, move in enumerate(ordered_moves):
            is_quiet = self._is_quiet_move(snapshot, move)
            exact_short_mate_quiet = is_quiet and self._force_exact_short_mate_search(depth, ply)
            if is_quiet and move_index > 0 and futility_pruning_active:
                self.stats.futility_prunes += 1
                continue
            if (
                is_quiet
                and late_move_prune_limit is not None
                and move_index >= late_move_prune_limit
            ):
                self.stats.late_move_prunes += 1
                continue

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
                    if root_collect:
                        child_score, child_line = self._negamax(
                            next_position,
                            incremental_state,
                            depth - 1,
                            -MATE_SCORE,
                            MATE_SCORE,
                            ply + 1,
                            is_pv and move_index == 0,
                        )
                        score = -child_score
                        line = (move,) + child_line
                    elif exact_short_mate_quiet:
                        self.stats.exact_short_mate_quiet_searches += 1
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
                    elif move_index == 0:
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
                            and not exact_short_mate_quiet
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

            if root_collect:
                root_scores.append(RootMoveScore(move=move, score=score))

            alpha = max(alpha, best_score)
            if not root_collect and alpha >= beta:
                self.stats.cutoffs += 1
                self._record_cutoff(
                    position,
                    snapshot,
                    move,
                    depth,
                    ply,
                    prior_quiet_moves,
                )
                break

            if is_quiet:
                prior_quiet_moves.append(move)

        if best_move is None:
            if root_collect:
                self._root_move_scores_current = ()
            if static_eval is not None:
                return static_eval, ()
            return self._evaluate_position(position, incremental_state, ply=ply, is_pv=is_pv), ()

        if root_collect:
            self._root_move_scores_current = tuple(
                sorted(root_scores, key=lambda root_score: root_score.score, reverse=True)
            )
            bound = Bound.EXACT
        elif best_score <= alpha_orig:
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
            alpha_orig = alpha
            beta_orig = beta
            key = _position_key(position)
            qtt_entry, alpha, beta, qtt_result = self._probe_quiescence_tt(
                key,
                remaining_depth,
                alpha,
                beta,
            )
            if qtt_result is not None:
                return qtt_result
            snapshot = self._tactics(position, incremental_state, detail=TacticalDetail.BASIC)
            self._record_snapshot(snapshot)
            return self._quiescence_from_snapshot(
                position,
                incremental_state,
                snapshot,
                alpha,
                beta,
                alpha_orig,
                beta_orig,
                ply,
                remaining_depth,
                is_pv,
                key,
                qtt_entry,
            )
        finally:
            self.stats.quiescence_time_seconds += time.perf_counter() - started_at

    def _probe_quiescence_tt(
        self,
        key: tuple[int, int, int],
        remaining_depth: int,
        alpha: int,
        beta: int,
    ) -> tuple[TTEntry | None, int, int, tuple[int, tuple[int, ...]] | None]:
        self.stats.qtt_probes += 1
        qtt_entry = self.qtt.get(key)
        if qtt_entry and qtt_entry.depth >= remaining_depth:
            self.stats.qtt_hits += 1
            if qtt_entry.bound is Bound.EXACT:
                return qtt_entry, alpha, beta, (qtt_entry.score, qtt_entry.principal_variation)
            if qtt_entry.bound is Bound.LOWER:
                alpha = max(alpha, qtt_entry.score)
            elif qtt_entry.bound is Bound.UPPER:
                beta = min(beta, qtt_entry.score)
            if alpha >= beta:
                self.stats.qtt_cutoffs += 1
                return qtt_entry, alpha, beta, (qtt_entry.score, qtt_entry.principal_variation)
        return qtt_entry, alpha, beta, None

    def _quiescence_from_snapshot(
        self,
        position: Position,
        incremental_state: IncrementalState,
        snapshot: TacticalSnapshot,
        alpha: int,
        beta: int,
        alpha_orig: int,
        beta_orig: int,
        ply: int,
        remaining_depth: int,
        is_pv: bool,
        key: tuple[int, int, int],
        qtt_entry: TTEntry | None,
    ) -> tuple[int, tuple[int, ...]]:
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
        solved = self._tactical_proof(position, snapshot, ply, in_quiescence=True, is_pv=is_pv)
        if solved is not None:
            return solved
        forced_block_follow = self._follow_single_forced_block_quiescence(
            position,
            incremental_state,
            snapshot,
            alpha,
            beta,
            alpha_orig,
            beta_orig,
            ply,
            remaining_depth,
            is_pv,
            key,
        )
        if forced_block_follow is not None:
            return forced_block_follow

        stand_pat = self._evaluate_position(
            position,
            incremental_state,
            snapshot,
            ply,
            is_pv,
            in_quiescence=True,
        )
        if remaining_depth == 0 or not snapshot.urgent:
            return self._store_quiescence_tt(
                key,
                remaining_depth,
                stand_pat,
                (),
                None,
                alpha_orig,
                beta_orig,
            )
        if stand_pat >= beta:
            return self._store_quiescence_tt(
                key,
                remaining_depth,
                stand_pat,
                (),
                None,
                alpha_orig,
                beta_orig,
            )
        alpha_gap = alpha - stand_pat
        if stand_pat > alpha:
            alpha = stand_pat

        skip_reason = self._quiescence_skip_reason(snapshot, alpha_gap, remaining_depth, is_pv)
        if skip_reason is not None:
            self._record_quiescence_skip_reason(skip_reason)
            self.stats.quiescence_soft_skip_nodes += 1
            return self._store_quiescence_tt(
                key,
                remaining_depth,
                stand_pat,
                (),
                None,
                alpha_orig,
                beta_orig,
            )

        candidates = self._quiescence_moves(
            position,
            incremental_state,
            snapshot,
            ply,
            is_pv,
            alpha_gap,
            remaining_depth,
            qtt_entry.best_move if qtt_entry else None,
        )
        if not candidates:
            return self._store_quiescence_tt(
                key,
                remaining_depth,
                stand_pat,
                (),
                None,
                alpha_orig,
                beta_orig,
            )

        self._record_expansion(position.empty_count, len(candidates))
        self.stats.tactical_extensions += 1
        best_score = stand_pat
        best_line: tuple[int, ...] = ()
        best_move: int | None = None

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
                best_move = move
            if best_score > alpha:
                alpha = best_score
            if alpha >= beta:
                self.stats.cutoffs += 1
                break

        return self._store_quiescence_tt(
            key,
            remaining_depth,
            best_score,
            best_line,
            best_move,
            alpha_orig,
            beta_orig,
        )

    def _forced_chain_leaf_quiescence(
        self,
        position: Position,
        incremental_state: IncrementalState,
        alpha: int,
        beta: int,
        alpha_orig: int,
        beta_orig: int,
        ply: int,
        remaining_depth: int,
        is_pv: bool,
        key: tuple[int, int, int],
    ) -> tuple[int, tuple[int, ...], tuple[tuple[int, int, int], int, int, int, int | None] | None]:
        qtt_entry, alpha, beta, qtt_result = self._probe_quiescence_tt(
            key,
            remaining_depth,
            alpha,
            beta,
        )
        if qtt_result is not None:
            return qtt_result[0], qtt_result[1], None
        snapshot = self._tactics(position, incremental_state, detail=TacticalDetail.BASIC)
        self._record_snapshot(snapshot)
        score, line = self._quiescence_from_snapshot(
            position,
            incremental_state,
            snapshot,
            alpha,
            beta,
            alpha_orig,
            beta_orig,
            ply,
            remaining_depth,
            is_pv,
            key,
            qtt_entry,
        )
        return score, line, (
            key,
            remaining_depth,
            alpha_orig,
            beta_orig,
            line[0] if line else None,
        )

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
                use_ordering_maps=False,
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
                    use_ordering_maps=False,
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
                use_ordering_maps=False,
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
                    use_ordering_maps=False,
                )

            if snapshot.safe_moves:
                self.stats.poison_moves_filtered += len(snapshot.poison_moves)
                priority: list[int] = []
                seen: set[int] = set()
                for bucket in (
                    snapshot.double_threats,
                    snapshot.safe_threats,
                    snapshot.critical_restricted_responses,
                    snapshot.critical_restricted_builds,
                ):
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
                    use_ordering_maps=False,
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
        alpha_gap: int,
        remaining_depth: int,
        tt_move: int | None = None,
    ) -> list[int]:
        if snapshot.opponent_winning_moves:
            forced_blocks = list(snapshot.forced_blocks)
            self.stats.quiescence_forced_block_nodes += 1
            self.stats.quiescence_forced_block_moves += len(forced_blocks)
            if len(forced_blocks) <= 1:
                return forced_blocks
            moves = self._rank_moves(
                position,
                incremental_state,
                snapshot,
                forced_blocks,
                ply,
                tt_move,
                is_pv,
                True,
                use_ordering_maps=False,
            )
            return moves
        if snapshot.double_threats:
            double_threats = list(snapshot.double_threats)
            self.stats.quiescence_double_threat_nodes += 1
            self.stats.quiescence_double_threat_moves += len(double_threats)
            if len(double_threats) <= 1:
                return double_threats
            moves = self._rank_moves(
                position,
                incremental_state,
                snapshot,
                double_threats,
                ply,
                tt_move,
                is_pv,
                True,
                use_ordering_maps=False,
            )
            return moves
        if snapshot.safe_threats:
            safe_threats = list(snapshot.safe_threats)
            limit = self._quiescence_safe_threat_limit(snapshot, alpha_gap, remaining_depth, is_pv)
            self.stats.quiescence_safe_threat_nodes += 1
            self.stats.quiescence_safe_threat_moves += len(safe_threats)
            if not snapshot.opponent_winning_moves and not snapshot.double_threats:
                self.stats.quiescence_safe_threat_only_nodes += 1
            if limit < len(safe_threats):
                self.stats.quiescence_safe_threat_moves_pruned += len(safe_threats) - limit
            if len(safe_threats) <= 1:
                return safe_threats
            ranked = self._rank_moves(
                position,
                incremental_state,
                snapshot,
                safe_threats,
                ply,
                tt_move,
                is_pv,
                True,
                use_ordering_maps=False,
                limit=limit,
            )
            return ranked
        restricted_moves: list[int] = []
        seen_restricted: set[int] = set()
        for bucket in (snapshot.critical_restricted_responses, snapshot.critical_restricted_builds):
            for move in bucket:
                if move not in seen_restricted:
                    restricted_moves.append(move)
                    seen_restricted.add(move)
        if restricted_moves:
            if len(restricted_moves) <= 1:
                return restricted_moves
            return self._rank_moves(
                position,
                incremental_state,
                snapshot,
                restricted_moves,
                ply,
                tt_move,
                is_pv,
                True,
                use_ordering_maps=False,
                limit=QUIESCENCE_CRITICAL_RESPONSE_LIMIT,
            )
        return []

    def _quiescence_skip_reason(
        self,
        snapshot: TacticalSnapshot,
        alpha_gap: int,
        remaining_depth: int,
        is_pv: bool,
    ) -> str | None:
        if is_pv:
            return None
        if snapshot.opponent_winning_moves or snapshot.double_threats or not snapshot.safe_threats:
            return None
        if len(snapshot.safe_threats) > 1:
            return "multi_safe_threat"
        if remaining_depth <= QUIESCENCE_NONPV_SAFE_THREAT_FRONTIER_DEPTH:
            return "frontier_safe_threat"
        if (
            len(snapshot.safe_moves) > QUIESCENCE_NONPV_SAFE_THREAT_WIDE_MAX_SAFE_MOVES
            and alpha_gap >= -QUIESCENCE_NONPV_SAFE_THREAT_WIDE_ALPHA_MARGIN
        ):
            return "wide_safe_threat"
        if len(snapshot.safe_moves) > QUIESCENCE_SAFE_THREAT_MAX_SAFE_MOVES:
            return "wide_safe_threat"
        if alpha_gap > QUIESCENCE_SAFE_THREAT_ALPHA_MARGIN:
            return "alpha_gap_safe_threat"
        return None

    def _record_quiescence_skip_reason(self, reason: str) -> None:
        if reason == "multi_safe_threat":
            self.stats.quiescence_skip_multi_safe_threat_nodes += 1
        elif reason == "frontier_safe_threat":
            self.stats.quiescence_skip_frontier_safe_threat_nodes += 1
        elif reason == "wide_safe_threat":
            self.stats.quiescence_skip_wide_safe_threat_nodes += 1
        elif reason == "alpha_gap_safe_threat":
            self.stats.quiescence_skip_alpha_safe_threat_nodes += 1

    def _should_skip_soft_quiescence(
        self,
        snapshot: TacticalSnapshot,
        alpha_gap: int,
        remaining_depth: int,
        is_pv: bool,
    ) -> bool:
        return self._quiescence_skip_reason(snapshot, alpha_gap, remaining_depth, is_pv) is not None

    def _follow_single_forced_block_quiescence(
        self,
        position: Position,
        incremental_state: IncrementalState,
        snapshot: TacticalSnapshot,
        alpha: int,
        beta: int,
        alpha_orig: int,
        beta_orig: int,
        ply: int,
        remaining_depth: int,
        is_pv: bool,
        key: tuple[int, int, int],
    ) -> tuple[int, tuple[int, ...]] | None:
        if remaining_depth <= 0 or len(snapshot.forced_blocks) != 1 or not snapshot.opponent_winning_moves:
            return None

        trail: list[tuple[tuple[int, int, int], int, int, int, int]] = []
        undos = []
        current_position = position
        current_snapshot = snapshot
        current_key = key
        current_alpha = alpha
        current_beta = beta
        current_alpha_orig = alpha_orig
        current_beta_orig = beta_orig
        current_ply = ply
        current_remaining_depth = remaining_depth
        leaf_score: int | None = None
        leaf_line: tuple[int, ...] = ()
        leaf_store: tuple[tuple[int, int, int], int, int, int, int | None] | None = None

        try:
            while current_remaining_depth > 0:
                move = current_snapshot.forced_blocks[0]
                self.stats.quiescence_single_forced_block_nodes += 1
                self.stats.quiescence_forced_block_nodes += 1
                self.stats.quiescence_forced_block_moves += 1
                self._record_expansion(current_position.empty_count, 1)
                self.stats.tactical_extensions += 1

                result = incremental_state.move_result(move, current_position.side_to_move)
                if result is MoveResult.WIN:
                    leaf_score = MATE_SCORE - current_ply
                    leaf_line = (move,)
                    leaf_store = (current_key, current_remaining_depth, current_alpha_orig, current_beta_orig, move)
                    break
                if result is MoveResult.LOSS:
                    leaf_score = -MATE_SCORE + current_ply
                    leaf_line = (move,)
                    leaf_store = (current_key, current_remaining_depth, current_alpha_orig, current_beta_orig, move)
                    break

                trail.append((current_key, current_remaining_depth, current_alpha_orig, current_beta_orig, move))
                undos.append(incremental_state.make_move(move, current_position.side_to_move))
                current_position = incremental_state.to_position()
                current_ply += 1
                current_remaining_depth -= 1
                current_alpha, current_beta = -current_beta, -current_alpha
                current_alpha_orig, current_beta_orig = current_alpha, current_beta

                if current_remaining_depth < 0:
                    break

                self.stats.quiescence_nodes += 1
                self.stats.tactical_quiescence_entries += 1
                self._visited_nodes += 1
                self._check_limits()

                current_key = _position_key(current_position)
                qtt_entry, current_alpha, current_beta, qtt_result = self._probe_quiescence_tt(
                    current_key,
                    current_remaining_depth,
                    current_alpha,
                    current_beta,
                )
                if qtt_result is not None:
                    leaf_score, leaf_line = qtt_result
                    leaf_store = None
                    break

                current_snapshot = self._tactics(current_position, incremental_state, detail=TacticalDetail.BASIC)
                self._record_snapshot(current_snapshot)

                forced = self._forced_outcome(
                    current_position,
                    incremental_state,
                    current_snapshot,
                    current_ply,
                    qtt_entry.best_move if qtt_entry else None,
                    is_pv,
                    in_quiescence=True,
                )
                if forced is not None:
                    leaf_score, leaf_line = forced
                    leaf_store = (
                        current_key,
                        current_remaining_depth,
                        current_alpha_orig,
                        current_beta_orig,
                        leaf_line[0] if leaf_line else None,
                    )
                    break

                solved = self._tactical_proof(
                    current_position,
                    current_snapshot,
                    current_ply,
                    in_quiescence=True,
                    is_pv=is_pv,
                )
                if solved is not None:
                    leaf_score, leaf_line = solved
                    leaf_store = (
                        current_key,
                        current_remaining_depth,
                        current_alpha_orig,
                        current_beta_orig,
                        leaf_line[0] if leaf_line else None,
                    )
                    break

                if len(current_snapshot.forced_blocks) != 1 or not current_snapshot.opponent_winning_moves:
                    leaf_score, leaf_line = self._quiescence_from_snapshot(
                        current_position,
                        incremental_state,
                        current_snapshot,
                        current_alpha,
                        current_beta,
                        current_alpha_orig,
                        current_beta_orig,
                        current_ply,
                        current_remaining_depth,
                        is_pv,
                        current_key,
                        qtt_entry,
                    )
                    leaf_store = (
                        current_key,
                        current_remaining_depth,
                        current_alpha_orig,
                        current_beta_orig,
                        leaf_line[0] if leaf_line else None,
                    )
                    break

            if leaf_score is None:
                leaf_score, leaf_line, leaf_store = self._forced_chain_leaf_quiescence(
                    current_position,
                    incremental_state,
                    current_alpha,
                    current_beta,
                    current_alpha_orig,
                    current_beta_orig,
                    current_ply,
                    current_remaining_depth,
                    is_pv,
                    current_key,
                )
        finally:
            while undos:
                incremental_state.unmake_move(undos.pop())

        score = leaf_score
        line = leaf_line
        if leaf_store is not None:
            leaf_key, leaf_depth, leaf_alpha_orig, leaf_beta_orig, leaf_best_move = leaf_store
            score, line = self._store_quiescence_tt(
                leaf_key,
                leaf_depth,
                score,
                line,
                leaf_best_move,
                leaf_alpha_orig,
                leaf_beta_orig,
            )

        while trail:
            trail_key, trail_depth, trail_alpha_orig, trail_beta_orig, trail_move = trail.pop()
            score = -score
            line = (trail_move,) + line
            score, line = self._store_quiescence_tt(
                trail_key,
                trail_depth,
                score,
                line,
                trail_move,
                trail_alpha_orig,
                trail_beta_orig,
            )

        return score, line

    def _quiescence_safe_threat_limit(
        self,
        snapshot: TacticalSnapshot,
        alpha_gap: int,
        remaining_depth: int,
        is_pv: bool,
    ) -> int:
        if is_pv:
            return QUIESCENCE_SAFE_THREAT_LIMIT
        if remaining_depth <= QUIESCENCE_NONPV_SAFE_THREAT_FRONTIER_DEPTH:
            return QUIESCENCE_NONPV_SAFE_THREAT_LIMIT
        if len(snapshot.safe_moves) > QUIESCENCE_NONPV_SAFE_THREAT_WIDE_MAX_SAFE_MOVES:
            return QUIESCENCE_NONPV_SAFE_THREAT_LIMIT
        if alpha_gap >= 0:
            return QUIESCENCE_NONPV_SAFE_THREAT_LIMIT
        return min(QUIESCENCE_SAFE_THREAT_LIMIT, QUIESCENCE_NONPV_SAFE_THREAT_NEGATIVE_ALPHA_LIMIT)

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
        use_ordering_maps: bool = True,
        limit: int | None = None,
    ) -> list[int]:
        if not moves:
            return moves

        winning_moves = set(snapshot.winning_moves)
        forced_blocks = set(snapshot.forced_blocks)
        double_threats = set(snapshot.double_threats)
        safe_threats = set(snapshot.safe_threats)
        critical_restricted_builds = set(snapshot.critical_restricted_builds)
        critical_restricted_responses = set(snapshot.critical_restricted_responses)
        safe_moves = set(snapshot.safe_moves)
        side_index = _side_index(position.side_to_move)
        killer0, killer1 = self.killers.get(ply, [None, None])
        future_wins_by_move = snapshot.future_wins_by_move
        opponent_wins_after_move = snapshot.opponent_wins_after_move
        restricted_move_pressure = snapshot.restricted_move_pressure
        future_win_counts: dict[int, int] = {}
        opponent_remaining_counts: dict[int, int] = {}
        use_snapshot_maps = bool(future_wins_by_move or opponent_wins_after_move)
        if not use_snapshot_maps and use_ordering_maps:
            future_win_counts, opponent_remaining_counts = incremental_state.move_map_counts(
                moves,
                position.side_to_move,
                candidate_moves=snapshot.candidate_moves,
            )
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

            score = self._static_move_order_scores[move]
            if move in winning_moves:
                return WIN_MOVE_BONUS + score
            if move in forced_blocks:
                score += BLOCK_MOVE_BONUS
            if move in double_threats:
                score += DOUBLE_THREAT_BONUS
            elif move in safe_threats:
                score += SAFE_THREAT_BONUS
            if move in critical_restricted_builds:
                score += CRITICAL_RESTRICTED_BUILD_BONUS
            if move in critical_restricted_responses:
                score += CRITICAL_RESTRICTED_RESPONSE_BONUS
            if move in safe_moves:
                score += SAFE_MOVE_BONUS
            else:
                score -= POISON_MOVE_PENALTY
            score += restricted_move_pressure.get(move, 0)

            if use_snapshot_maps:
                score += len(future_wins_by_move.get(move, ())) * FUTURE_WIN_BONUS
                score -= len(opponent_wins_after_move.get(move, ())) * OPPONENT_WIN_REMAINING_PENALTY
            else:
                score += future_win_counts.get(move, 0) * FUTURE_WIN_BONUS
                score -= opponent_remaining_counts.get(move, 0) * OPPONENT_WIN_REMAINING_PENALTY
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
            return moves if limit is None else moves[:limit]

        if limit is not None and limit < len(moves):
            return heapq.nlargest(limit, moves, key=base_scores.__getitem__)

        moves.sort(key=lambda move: base_scores[move], reverse=True)
        return moves if limit is None else moves[:limit]

    def _record_cutoff(
        self,
        position: Position,
        snapshot: TacticalSnapshot,
        move: int,
        depth: int,
        ply: int,
        prior_quiet_moves: list[int] | tuple[int, ...] = (),
    ) -> None:
        if not self._is_quiet_move(snapshot, move):
            return

        side_index = _side_index(position.side_to_move)
        bonus = depth * depth * HISTORY_BONUS_UNIT
        self._update_history_score(side_index, move, bonus)
        self.stats.history_updates += 1
        malus = max(HISTORY_BONUS_UNIT, bonus // HISTORY_MALUS_DIVISOR)
        for prior_move in prior_quiet_moves:
            if prior_move == move:
                continue
            self._update_history_score(side_index, prior_move, -malus)
            self.stats.history_malus_updates += 1

        killers = self.killers.setdefault(ply, [None, None])
        if killers[0] != move:
            killers[1] = killers[0]
            killers[0] = move
            self.stats.killer_updates += 1

    def _update_history_score(self, side_index: int, move: int, delta: int) -> None:
        updated = self.history[side_index][move] + delta
        if updated > HISTORY_SCORE_LIMIT:
            updated = HISTORY_SCORE_LIMIT
        elif updated < -HISTORY_SCORE_LIMIT:
            updated = -HISTORY_SCORE_LIMIT
        self.history[side_index][move] = updated

    def _is_quiet_move(self, snapshot: TacticalSnapshot, move: int) -> bool:
        return (
            move in snapshot.safe_moves
            and move not in snapshot.forced_blocks
            and move not in snapshot.safe_threats
            and move not in snapshot.double_threats
            and move not in snapshot.critical_restricted_builds
            and move not in snapshot.critical_restricted_responses
        )

    def _fallback(
        self,
        position: Position,
        incremental_state: IncrementalState,
    ) -> tuple[int | None, int, tuple[int, ...]]:
        if position.empty_count == 0:
            return None, self._evaluate_position(position, incremental_state, ply=0, is_pv=True), ()

        snapshot = self._tactics(position, incremental_state, detail=TacticalDetail.BASIC)
        if snapshot.opponent_winning_moves and snapshot.forced_blocks:
            moves = list(snapshot.forced_blocks)
        elif snapshot.safe_moves:
            priority: list[int] = []
            seen: set[int] = set()
            for bucket in (
                snapshot.double_threats,
                snapshot.safe_threats,
                snapshot.critical_restricted_responses,
                snapshot.critical_restricted_builds,
            ):
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
                0,
                None,
                True,
                None,
                use_ordering_maps=False,
            )
            ranked_quiet = self._rank_moves(
                position,
                incremental_state,
                snapshot,
                quiet_moves,
                0,
                None,
                True,
            )
            quiet_limit = self._quiet_move_limit(position, snapshot, 1, 0)
            moves = ranked_priority + ranked_quiet[:quiet_limit]
        else:
            moves = list(snapshot.candidate_moves)
        ordered = (
            moves
            if snapshot.safe_moves
            else self._rank_moves(position, incremental_state, snapshot, moves, 0, None, True)
        )
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
    def _allow_quiet_frontier_pruning(
        self,
        snapshot: TacticalSnapshot,
        depth: int,
        alpha: int,
        beta: int,
        is_pv: bool,
    ) -> bool:
        if is_pv or depth > FUTILITY_PRUNING_MAX_DEPTH:
            return False
        if not self._is_quiet_node(snapshot):
            return False
        if alpha <= -MATE_SCORE + 5_000 or beta >= MATE_SCORE - 5_000:
            return False
        return True

    def _futility_margin(self, depth: int) -> int:
        return FUTILITY_MARGIN_BASE + FUTILITY_MARGIN_PER_DEPTH * depth

    def _late_move_prune_limit(self, depth: int) -> int | None:
        if depth > LATE_MOVE_PRUNING_MAX_DEPTH:
            return None
        return 2 + (2 * depth)

    def _force_exact_short_mate_search(self, depth: int, ply: int) -> bool:
        return ply == 0 and depth <= 5

    def _store_quiescence_tt(
        self,
        key: tuple[int, int, int],
        remaining_depth: int,
        score: int,
        line: tuple[int, ...],
        best_move: int | None,
        alpha_orig: int,
        beta_orig: int,
    ) -> tuple[int, tuple[int, ...]]:
        if score <= alpha_orig:
            bound = Bound.UPPER
        elif score >= beta_orig:
            bound = Bound.LOWER
        else:
            bound = Bound.EXACT
        self.qtt[key] = TTEntry(
            depth=remaining_depth,
            score=score,
            bound=bound,
            best_move=best_move,
            principal_variation=line,
        )
        return score, line

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
        is_pv: bool,
    ) -> tuple[int, tuple[int, ...]] | None:
        if not self._should_probe_tactical_solver(snapshot, ply, in_quiescence, is_pv):
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
        ply: int,
        in_quiescence: bool,
        is_pv: bool,
    ) -> bool:
        if snapshot.double_threats:
            if in_quiescence and not is_pv and ply > PROOF_NONPV_QUIESCENCE_MAX_PLY:
                return False
            if not is_pv and ply > PROOF_NONPV_FORCE_MAX_PLY:
                return False
            return True

        if snapshot.opponent_winning_moves:
            if not (snapshot.forced_blocks and len(snapshot.forced_blocks) <= PROOF_MAX_FORCED_BLOCKS):
                return False
            if in_quiescence and not is_pv and ply > PROOF_NONPV_QUIESCENCE_MAX_PLY:
                return False
            if not is_pv and ply > PROOF_NONPV_FORCE_MAX_PLY:
                return False
            return True

        if in_quiescence:
            return False

        return bool(
            snapshot.safe_threats
            and len(snapshot.safe_threats) <= PROOF_MAX_SAFE_THREATS
            and len(snapshot.safe_moves) <= PROOF_MAX_SAFE_MOVES
            and (is_pv or ply <= PROOF_NONPV_SAFE_THREAT_MAX_PLY)
        )

    def _tactics(
        self,
        position: Position,
        incremental_state: IncrementalState | None = None,
        include_move_maps: bool = True,
        detail: TacticalDetail | None = None,
    ) -> TacticalSnapshot:
        resolved_detail = resolve_tactical_detail(detail, include_move_maps=include_move_maps)
        cache_flag = 1 if resolved_detail is TacticalDetail.ORDERING else 0
        key = (*_position_key(position), cache_flag)
        self.stats.tactics_cache_probes += 1
        snapshot = self.tactics_cache.get(key)
        if snapshot is not None:
            self.stats.tactics_cache_hits += 1
            return snapshot

        if resolved_detail is TacticalDetail.BASIC:
            full_snapshot = self.tactics_cache.get((*_position_key(position), 1))
            if full_snapshot is not None:
                self.stats.tactics_cache_hits += 1
                self.tactics_cache[key] = full_snapshot
                return full_snapshot

        occupancy_key = _occupancy_key(position)
        pair = self.tactics_pair_cache.get((*occupancy_key, cache_flag))
        if pair is not None:
            self.stats.tactics_cache_hits += 1
            black_snapshot, white_snapshot = pair
        else:
            full_pair = None
            if resolved_detail is TacticalDetail.BASIC:
                full_pair = self.tactics_pair_cache.get((*occupancy_key, 1))
            if full_pair is not None:
                self.stats.tactics_cache_hits += 1
                black_snapshot, white_snapshot = full_pair
                self.tactics_pair_cache[(*occupancy_key, cache_flag)] = full_pair
            else:
                started_at = time.perf_counter()
                if incremental_state is not None:
                    ordered_candidates = incremental_state.ordered_candidate_moves()
                    black_summary, white_summary = incremental_state.paired_tactical_summaries(
                        ordered_candidates,
                        detail=resolved_detail,
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
                        restricted_pressure=black_summary.restricted_pressure,
                        opponent_restricted_pressure=black_summary.opponent_restricted_pressure,
                        critical_restricted_lines=black_summary.critical_restricted_lines,
                        opponent_critical_restricted_lines=black_summary.opponent_critical_restricted_lines,
                        restricted_move_pressure=black_summary.restricted_move_pressure,
                        critical_restricted_builds=black_summary.critical_restricted_builds,
                        critical_restricted_responses=black_summary.critical_restricted_responses,
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
                        restricted_pressure=white_summary.restricted_pressure,
                        opponent_restricted_pressure=white_summary.opponent_restricted_pressure,
                        critical_restricted_lines=white_summary.critical_restricted_lines,
                        opponent_critical_restricted_lines=white_summary.opponent_critical_restricted_lines,
                        restricted_move_pressure=white_summary.restricted_move_pressure,
                        critical_restricted_builds=white_summary.critical_restricted_builds,
                        critical_restricted_responses=white_summary.critical_restricted_responses,
                    )
                else:
                    derived_state = IncrementalState.from_position(position, self.tables)
                    ordered_candidates = derived_state.ordered_candidate_moves()
                    black_summary, white_summary = derived_state.paired_tactical_summaries(
                        ordered_candidates,
                        detail=resolved_detail,
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
                        restricted_pressure=black_summary.restricted_pressure,
                        opponent_restricted_pressure=black_summary.opponent_restricted_pressure,
                        critical_restricted_lines=black_summary.critical_restricted_lines,
                        opponent_critical_restricted_lines=black_summary.opponent_critical_restricted_lines,
                        restricted_move_pressure=black_summary.restricted_move_pressure,
                        critical_restricted_builds=black_summary.critical_restricted_builds,
                        critical_restricted_responses=black_summary.critical_restricted_responses,
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
                        restricted_pressure=white_summary.restricted_pressure,
                        opponent_restricted_pressure=white_summary.opponent_restricted_pressure,
                        critical_restricted_lines=white_summary.critical_restricted_lines,
                        opponent_critical_restricted_lines=white_summary.opponent_critical_restricted_lines,
                        restricted_move_pressure=white_summary.restricted_move_pressure,
                        critical_restricted_builds=white_summary.critical_restricted_builds,
                        critical_restricted_responses=white_summary.critical_restricted_responses,
                    )
                self.stats.tactics_time_seconds += time.perf_counter() - started_at
                self.tactics_pair_cache[(*occupancy_key, cache_flag)] = (black_snapshot, white_snapshot)

        black_key = (*_position_key(position.with_side_to_move(Color.BLACK)), cache_flag)
        white_key = (*_position_key(position.with_side_to_move(Color.WHITE)), cache_flag)
        self.tactics_cache[black_key] = black_snapshot
        self.tactics_cache[white_key] = white_snapshot
        if resolved_detail is TacticalDetail.ORDERING:
            black_lite_key = (*_position_key(position.with_side_to_move(Color.BLACK)), 0)
            white_lite_key = (*_position_key(position.with_side_to_move(Color.WHITE)), 0)
            self.tactics_cache[black_lite_key] = black_snapshot
            self.tactics_cache[white_lite_key] = white_snapshot
            self.tactics_pair_cache[(*occupancy_key, 0)] = (black_snapshot, white_snapshot)
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
                else self._tactics(position, incremental_state, detail=TacticalDetail.BASIC)
            )
            opponent_snapshot = self._tactics(
                position.with_side_to_move(position.side_to_move.opponent),
                incremental_state,
                detail=TacticalDetail.BASIC,
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
            if getattr(self.learned_evaluator, "quiet_value_only", False):
                if in_quiescence or not self._is_quiet_node(current_snapshot):
                    return score

            model_bucket = self._model_call_bucket(current_snapshot, ply, is_pv, in_quiescence)
            model_started_at = time.perf_counter()
            try:
                learned_score = self.learned_evaluator.evaluate(
                    position,
                    current_snapshot,
                    opponent_snapshot,
                    incremental_state=incremental_state,
                )
            except TypeError:
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
            or not getattr(self.learned_evaluator, "supports_policy", True)
            or not self._allow_learned_policy(ply)
        ):
            return {}

        opponent_snapshot = self._tactics(
            position.with_side_to_move(position.side_to_move.opponent),
            incremental_state,
            detail=TacticalDetail.BASIC,
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
            or snapshot.critical_restricted_lines
            or snapshot.opponent_critical_restricted_lines
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
