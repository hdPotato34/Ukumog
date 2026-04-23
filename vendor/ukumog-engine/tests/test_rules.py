from __future__ import annotations

import random
import subprocess
import sys
import unittest
from pathlib import Path

from ukumog_engine import (
    DEFAULT_MASKS,
    Color,
    MoveResult,
    MoveType,
    Position,
    SearchEngine,
    TacticalOutcome,
    TacticalSolver,
    analyze_tactics,
    brute_force_move_result,
    classify_move,
    coord_to_index,
    play_move,
)


RESTRICTED_THREAT_REPRO_ROWS = [
    "....B......",
    ".....B.....",
    "...........",
    "...B.......",
    "..B.W.W....",
    ".....B.....",
    "....WWB....",
    "...........",
    "....W......",
    "...........",
    "...........",
]

RESTRICTED_THREAT_BASE_ROWS = [
    "....B......",
    ".....B.....",
    "...........",
    "...B.......",
    "..B.W.W....",
    "...........",
    "....WWB....",
    "...........",
    "....W......",
    "...........",
    "...........",
]

RESTRICTED_THREAT_DEFENSE = (7, 4)
RESTRICTED_THREAT_SPECULATIVE = (5, 4)
RESTRICTED_THREAT_TRANSFORMS = ("identity", "rot90", "rot180", "rot270", "flip_h")
LARGE_GAP_RESTRICTED_CLAIM_ROWS = [
    "...........",
    ".B.........",
    "...........",
    ".BB.B......",
    "...........",
    ".....W.....",
    "...........",
    ".B..B.....B",
    "...........",
    "...........",
    "...........",
]
LARGE_GAP_RESTRICTED_CLAIM_MOVE = (5, 9)


def _transform_rows(rows: list[str], transform: str) -> list[str]:
    if transform == "identity":
        return list(rows)
    if transform == "rot90":
        size = len(rows)
        return ["".join(rows[size - 1 - col][row] for col in range(size)) for row in range(size)]
    if transform == "rot180":
        return _transform_rows(_transform_rows(rows, "rot90"), "rot90")
    if transform == "rot270":
        return _transform_rows(_transform_rows(rows, "rot180"), "rot90")
    if transform == "flip_h":
        return [row[::-1] for row in rows]
    raise ValueError(f"unknown transform: {transform}")


def _transform_coord(coord: tuple[int, int], transform: str, size: int = 11) -> tuple[int, int]:
    row, col = coord
    if transform == "identity":
        return coord
    if transform == "rot90":
        return (col, size - 1 - row)
    if transform == "rot180":
        return (size - 1 - row, size - 1 - col)
    if transform == "rot270":
        return (size - 1 - col, row)
    if transform == "flip_h":
        return (row, size - 1 - col)
    raise ValueError(f"unknown transform: {transform}")


def _swap_colors(rows: list[str]) -> list[str]:
    swapped: list[str] = []
    for row in rows:
        swapped.append(row.replace("B", "x").replace("W", "B").replace("x", "W"))
    return swapped


class MaskGenerationTests(unittest.TestCase):
    def test_mask_counts_match_brief(self) -> None:
        self.assertEqual(len(DEFAULT_MASKS.masks4), 780)
        self.assertEqual(len(DEFAULT_MASKS.masks5), 420)

    def test_masks_are_unique_even_with_reverse_directions(self) -> None:
        four_cells = [pattern.cells for pattern in DEFAULT_MASKS.masks4]
        five_cells = [pattern.cells for pattern in DEFAULT_MASKS.masks5]
        self.assertEqual(len(four_cells), len(set(four_cells)))
        self.assertEqual(len(five_cells), len(set(five_cells)))


class RuleResolutionTests(unittest.TestCase):
    def test_mask_tables_include_long_step_slopes(self) -> None:
        steps: set[tuple[int, int]] = set()
        for pattern in DEFAULT_MASKS.masks5:
            first = divmod(pattern.cells[0], 11)
            second = divmod(pattern.cells[1], 11)
            steps.add((second[0] - first[0], second[1] - first[1]))

        self.assertIn((1, 2), steps)
        self.assertIn((2, -1), steps)

    def test_simple_five_creation_is_a_win(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "B.B.B.B....",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(5, 8)
        _, result = play_move(position, move)
        self.assertEqual(result, MoveResult.WIN)
        self.assertEqual(classify_move(position, move), MoveType.WINNING_NOW)

    def test_simple_four_creation_is_a_loss(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "B.B.B......",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(5, 6)
        _, result = play_move(position, move)
        self.assertEqual(result, MoveResult.LOSS)
        self.assertEqual(classify_move(position, move), MoveType.POISON)

    def test_five_overrides_four_when_both_are_created(self) -> None:
        rows = [
            "...........",
            "...........",
            "..B........",
            "...B.......",
            "....B......",
            ".....B.....",
            ".B........B",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(6, 6)
        _, result = play_move(position, move)
        self.assertEqual(result, MoveResult.WIN)

    def test_gapped_arithmetic_progression_counts(self) -> None:
        rows = [
            "...........",
            ".B.........",
            "...........",
            "...B.......",
            "...........",
            ".....B.....",
            "...........",
            ".......B...",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(9, 9)
        _, result = play_move(position, move)
        self.assertEqual(result, MoveResult.WIN)

    def test_arbitrary_negative_slope_is_detected(self) -> None:
        rows = [
            "...........",
            "...........",
            "........B..",
            "......B....",
            "....B......",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(5, 2)
        _, result = play_move(position, move)
        self.assertEqual(result, MoveResult.LOSS)

    def test_long_step_positive_slope_is_detected(self) -> None:
        rows = [
            "...........",
            ".B.........",
            "...B.......",
            ".....B.....",
            ".......B...",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(5, 9)
        _, result = play_move(position, move)
        self.assertEqual(result, MoveResult.WIN)

    def test_long_step_negative_slope_is_detected(self) -> None:
        rows = [
            "...........",
            "........B..",
            "...........",
            ".......B...",
            "...........",
            "......B....",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(7, 5)
        _, result = play_move(position, move)
        self.assertEqual(result, MoveResult.LOSS)

    def test_random_play_matches_bruteforce_oracle(self) -> None:
        rng = random.Random(20260419)
        position = Position.initial()

        for _ in range(300):
            move = rng.choice(position.legal_moves())
            expected = brute_force_move_result(position, move)
            next_position, actual = play_move(position, move)
            self.assertEqual(actual, expected)
            if actual is MoveResult.NONTERMINAL:
                position = next_position
            else:
                position = Position.initial()


class SearchTests(unittest.TestCase):
    @staticmethod
    def _position_from_history(history: list[int], side_to_move: Color = Color.BLACK) -> Position:
        position = Position.initial()
        for move in history:
            position, result = play_move(position, move)
            if result is not MoveResult.NONTERMINAL:
                raise AssertionError("history unexpectedly contains a terminal move")
        if position.side_to_move is not side_to_move:
            position = position.with_side_to_move(side_to_move)
        return position

    def test_forced_block_detector_finds_only_safe_parry(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "W.W.W.W....",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        tactics = analyze_tactics(position)
        self.assertEqual(tactics.opponent_winning_moves, (coord_to_index(5, 8),))
        self.assertEqual(tactics.forced_blocks, (coord_to_index(5, 8),))

    def test_safe_threat_detector_finds_single_future_win(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "B.B...B....",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(5, 8)
        tactics = analyze_tactics(position)
        self.assertIn(move, tactics.safe_threats)
        self.assertNotIn(move, tactics.double_threats)
        self.assertEqual(tactics.future_wins_by_move[move], (coord_to_index(5, 4),))

    def test_double_threat_detector_finds_fork_move(self) -> None:
        rows = [
            "...........",
            ".....B.....",
            "...........",
            ".....B.....",
            "...........",
            ".B.B.....B.",
            "...........",
            "...........",
            "...........",
            ".....B.....",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        move = coord_to_index(5, 5)
        tactics = analyze_tactics(position)
        self.assertIn(move, tactics.safe_threats)
        self.assertIn(move, tactics.double_threats)
        self.assertEqual(
            set(tactics.future_wins_by_move[move]),
            {coord_to_index(5, 7), coord_to_index(7, 5)},
        )

    def test_tactics_expose_opponent_restricted_pressure_from_poisoned_five(self) -> None:
        rows = [
            "...........",
            "...B.B.B...",
            "...........",
            "...B.B.B...",
            "...........",
            ".W.......W.",
            "...........",
            "...B.B.B...",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        tactics = analyze_tactics(position)

        self.assertFalse(tactics.opponent_winning_moves)
        self.assertGreater(tactics.opponent_restricted_pressure, 0)
        self.assertGreater(tactics.opponent_critical_restricted_lines, 0)
        self.assertTrue(tactics.critical_restricted_responses)

    def test_tactics_expose_large_gap_restricted_claim_and_response(self) -> None:
        claim_move = coord_to_index(*LARGE_GAP_RESTRICTED_CLAIM_MOVE)
        attacker_position = Position.from_rows(LARGE_GAP_RESTRICTED_CLAIM_ROWS, side_to_move=Color.WHITE)
        defender_position = attacker_position.with_side_to_move(Color.BLACK)
        attacker_tactics = analyze_tactics(attacker_position)
        defender_tactics = analyze_tactics(defender_position)

        self.assertIn(claim_move, attacker_tactics.critical_restricted_builds)
        self.assertGreater(attacker_tactics.restricted_pressure, 0)
        self.assertIn(claim_move, defender_tactics.critical_restricted_responses)
        self.assertGreater(defender_tactics.opponent_restricted_pressure, 0)

    def test_search_finds_immediate_win(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "B.B.B.B....",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        engine = SearchEngine()
        result = engine.search(position, max_depth=2)
        self.assertEqual(result.best_move, coord_to_index(5, 8))

    def test_search_blocks_opponent_immediate_win(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "W.W.W.W....",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        engine = SearchEngine()
        result = engine.search(position, max_depth=1)
        self.assertEqual(result.best_move, coord_to_index(5, 8))
        self.assertGreater(result.stats.tactical_solver_queries, 0)

    def test_search_avoids_obvious_poison_when_safe_move_exists(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            "B.B.B......",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        engine = SearchEngine()
        result = engine.search(position, max_depth=1)
        self.assertNotEqual(result.best_move, coord_to_index(5, 6))
        self.assertGreater(result.stats.poison_moves_filtered, 0)

    def test_quiescence_converts_double_threat_into_depth_one_choice(self) -> None:
        rows = [
            "...........",
            ".....B.....",
            "...........",
            ".....B.....",
            "...........",
            ".B.B.....B.",
            "...........",
            "...........",
            "...........",
            ".....B.....",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        engine = SearchEngine()
        result = engine.search(position, max_depth=1)
        self.assertEqual(result.best_move, coord_to_index(5, 5))
        self.assertGreater(result.score, 900_000)

    def test_search_blocks_poison_constrained_long_five_threat(self) -> None:
        rows = [
            "...........",
            ".B.........",
            "...........",
            "....B......",
            "...........",
            ".W...W...W.",
            "...........",
            "..........B",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        engine = SearchEngine()
        result = engine.search(position, max_depth=2, analyze_root=True)
        defense = coord_to_index(5, 3)

        self.assertIn(defense, analyze_tactics(position).critical_restricted_responses)
        self.assertEqual(result.best_move, defense)

    def test_search_matches_deeper_large_gap_restricted_claim_motif(self) -> None:
        position = Position.from_rows(LARGE_GAP_RESTRICTED_CLAIM_ROWS, side_to_move=Color.WHITE)
        claim_move = coord_to_index(*LARGE_GAP_RESTRICTED_CLAIM_MOVE)
        deep_engine = SearchEngine()
        deep = deep_engine.search(position, max_depth=6, analyze_root=True)
        shallow_engine = SearchEngine()
        shallow = shallow_engine.search(position, max_depth=3, analyze_root=True)

        self.assertEqual(deep.best_move, claim_move)
        self.assertEqual(shallow.best_move, claim_move)

    def test_iterative_deepening_prefers_center_on_empty_board(self) -> None:
        engine = SearchEngine()
        result = engine.search(Position.initial(), max_depth=3)
        self.assertEqual(result.best_move, coord_to_index(5, 5))
        self.assertEqual(result.depth, 3)
        self.assertTrue(result.principal_variation)

    def test_search_node_budget_returns_fallback_move(self) -> None:
        engine = SearchEngine()
        result = engine.search(Position.initial(), max_depth=5, max_nodes=1)
        self.assertTrue(result.stats.aborted)
        self.assertTrue(result.stats.node_limit_abort)
        self.assertEqual(result.best_move, coord_to_index(5, 5))
        self.assertEqual(result.depth, 0)

    def test_search_prunes_quiet_midgame_candidate_bulk(self) -> None:
        history = [41, 19, 52, 86, 6, 10, 111, 73, 14, 51, 82, 8, 72, 32, 4, 16, 66, 64]
        position = self._position_from_history(history)
        engine = SearchEngine()
        result = engine.search(position, max_depth=2)
        self.assertIsNotNone(result.best_move)
        self.assertGreater(result.stats.quiet_nodes_limited, 0)
        self.assertGreater(result.stats.quiet_moves_pruned, 0)

    def test_search_applies_additional_quiet_pruning_in_deeper_tree(self) -> None:
        engine = SearchEngine()
        result = engine.search(Position.initial(), max_depth=4)
        self.assertEqual(result.best_move, coord_to_index(5, 5))
        self.assertGreater(result.stats.futility_prunes + result.stats.late_move_prunes, 0)

    def test_exact_short_mate_search_guard_applies_near_root_only(self) -> None:
        engine = SearchEngine()
        self.assertTrue(engine._force_exact_short_mate_search(5, 0))
        self.assertFalse(engine._force_exact_short_mate_search(4, 1))
        self.assertFalse(engine._force_exact_short_mate_search(3, 2))
        self.assertFalse(engine._force_exact_short_mate_search(6, 0))
        self.assertFalse(engine._force_exact_short_mate_search(5, 3))

    def test_deep_search_scores_sparse_restricted_threat_defense_no_worse_than_speculative(self) -> None:
        boards = {
            "base": RESTRICTED_THREAT_BASE_ROWS,
            "base_swapped": _swap_colors(RESTRICTED_THREAT_BASE_ROWS),
        }
        for board_name, base_rows in boards.items():
            for transform in RESTRICTED_THREAT_TRANSFORMS:
                rows = _transform_rows(base_rows, transform)
                side_to_move = Color.BLACK if board_name.endswith("_swapped") else Color.WHITE
                position = Position.from_rows(rows, side_to_move=side_to_move)
                defense = coord_to_index(*_transform_coord(RESTRICTED_THREAT_DEFENSE, transform))
                speculative = coord_to_index(*_transform_coord(RESTRICTED_THREAT_SPECULATIVE, transform))
                deep_engine = SearchEngine()
                deep = deep_engine.search(position, max_depth=6, analyze_root=True)
                deep_scores = {root_score.move: root_score.score for root_score in deep.root_move_scores}

                with self.subTest(board=board_name, transform=transform):
                    self.assertIn(defense, deep_scores)
                    self.assertIn(speculative, deep_scores)
                    self.assertGreaterEqual(deep_scores[defense], deep_scores.get(speculative, -1_000_000))

    def test_rank_moves_respects_tt_move_priority(self) -> None:
        history = [41, 19, 52, 86, 6, 10, 111, 73, 14, 51, 82, 8, 72, 32, 4, 16, 66, 64]
        position = self._position_from_history(history)
        engine = SearchEngine()
        incremental_state = engine._search_incremental_state(position)
        snapshot = engine._tactics(position, incremental_state, include_move_maps=False)
        quiet_moves = [move for move in snapshot.safe_moves if engine._is_quiet_move(snapshot, move)]

        self.assertGreaterEqual(len(quiet_moves), 2)
        tt_move = quiet_moves[-1]
        ranked = engine._rank_moves(
            position,
            incremental_state,
            snapshot,
            quiet_moves[:],
            0,
            tt_move,
            True,
        )

        self.assertEqual(ranked[0], tt_move)

    def test_record_cutoff_updates_history_and_killers_for_quiet_move(self) -> None:
        history = [41, 19, 52, 86, 6, 10, 111, 73, 14, 51, 82, 8, 72, 32, 4, 16, 66, 64]
        position = self._position_from_history(history)
        engine = SearchEngine()
        incremental_state = engine._search_incremental_state(position)
        snapshot = engine._tactics(position, incremental_state, include_move_maps=False)
        quiet_move = next(move for move in snapshot.safe_moves if engine._is_quiet_move(snapshot, move))
        side_index = 0 if position.side_to_move is Color.BLACK else 1

        engine._record_cutoff(
            position,
            snapshot,
            quiet_move,
            depth=3,
            ply=1,
        )

        self.assertGreater(engine.history[side_index][quiet_move], 0)
        self.assertEqual(engine.killers[1][0], quiet_move)
        self.assertGreater(engine.stats.history_updates, 0)
        self.assertGreater(engine.stats.killer_updates, 0)

    def test_record_cutoff_applies_history_malus_to_prior_quiet_moves(self) -> None:
        history = [41, 19, 52, 86, 6, 10, 111, 73, 14, 51, 82, 8, 72, 32, 4, 16, 66, 64]
        position = self._position_from_history(history)
        engine = SearchEngine()
        incremental_state = engine._search_incremental_state(position)
        snapshot = engine._tactics(position, incremental_state, include_move_maps=False)
        quiet_moves = [move for move in snapshot.safe_moves if engine._is_quiet_move(snapshot, move)]

        self.assertGreaterEqual(len(quiet_moves), 2)
        prior_quiet_move = quiet_moves[0]
        cutoff_quiet_move = quiet_moves[1]
        side_index = 0 if position.side_to_move is Color.BLACK else 1

        engine._record_cutoff(
            position,
            snapshot,
            cutoff_quiet_move,
            depth=4,
            ply=1,
            prior_quiet_moves=[prior_quiet_move],
        )

        self.assertLess(engine.history[side_index][prior_quiet_move], 0)
        self.assertGreater(engine.history[side_index][cutoff_quiet_move], 0)
        self.assertGreater(engine.stats.history_malus_updates, 0)

    def test_search_make_unmake_does_not_mutate_root_position(self) -> None:
        position = self._position_from_history([41, 19, 52, 86, 6, 10, 111, 73])
        original = Position(
            black_bits=position.black_bits,
            white_bits=position.white_bits,
            side_to_move=position.side_to_move,
        )
        engine = SearchEngine()

        first = engine.search(position, max_depth=3)
        second = engine.search(position, max_depth=3)

        self.assertEqual(position, original)
        self.assertEqual(first.best_move, second.best_move)

    def test_full_tactics_cache_can_satisfy_lite_snapshot_request(self) -> None:
        position = self._position_from_history([41, 19, 52, 86, 6, 10, 111, 73])
        engine = SearchEngine()
        incremental_state = engine._search_incremental_state(position)

        full_snapshot = engine._tactics(position, incremental_state, include_move_maps=True)
        hits_before = engine.stats.tactics_cache_hits
        lite_snapshot = engine._tactics(position, incremental_state, include_move_maps=False)

        self.assertGreater(engine.stats.tactics_cache_hits, hits_before)
        self.assertEqual(lite_snapshot.safe_moves, full_snapshot.safe_moves)
        self.assertEqual(lite_snapshot.winning_moves, full_snapshot.winning_moves)
        self.assertEqual(lite_snapshot.opponent_winning_moves, full_snapshot.opponent_winning_moves)

    def test_quiescence_tt_hits_on_repeated_query(self) -> None:
        engine = SearchEngine()
        position = Position.initial()
        incremental_state = engine._search_incremental_state(position)

        first = engine._quiescence(position, incremental_state, -1_000_000, 1_000_000, 0, 0, True)
        hits_before = engine.stats.qtt_hits
        second = engine._quiescence(position, incremental_state, -1_000_000, 1_000_000, 0, 0, True)

        self.assertEqual(first, second)
        self.assertGreater(engine.stats.qtt_hits, hits_before)

    def test_quiescence_fast_paths_single_forced_block_chain(self) -> None:
        position = Position.from_rows(
            [
                "...........",
                "...........",
                "...........",
                "...........",
                "...........",
                "W.W.W.W....",
                "...........",
                "...........",
                "...........",
                "...........",
                "...........",
            ],
            side_to_move=Color.BLACK,
        )
        engine = SearchEngine()
        incremental_state = engine._search_incremental_state(position)
        snapshot = engine._tactics(position, incremental_state, include_move_maps=False)
        score, line = engine._follow_single_forced_block_quiescence(
            position,
            incremental_state,
            snapshot,
            -1_000_000,
            1_000_000,
            -1_000_000,
            1_000_000,
            0,
            2,
            False,
            (position.black_bits, position.white_bits, 0),
        )

        self.assertIsInstance(line, tuple)
        self.assertGreater(engine.stats.quiescence_single_forced_block_nodes, 0)
        self.assertLess(score, 1_000_000)

    def test_quiescence_skips_nonpv_frontier_single_safe_threat(self) -> None:
        position = Position.from_rows(
            [
                "...........",
                "...........",
                "...........",
                "...........",
                "...........",
                "B.B...B....",
                "...........",
                "...........",
                "...........",
                "...........",
                "...........",
            ],
            side_to_move=Color.BLACK,
        )
        engine = SearchEngine()
        incremental_state = engine._search_incremental_state(position)
        snapshot = engine._tactics(position, incremental_state, include_move_maps=False)

        self.assertTrue(snapshot.safe_threats)
        self.assertEqual(engine._quiescence_skip_reason(snapshot, 0, 1, False), "frontier_safe_threat")
        self.assertTrue(engine._should_skip_soft_quiescence(snapshot, 0, 1, False))
        self.assertFalse(engine._should_skip_soft_quiescence(snapshot, 0, 1, True))
        self.assertEqual(engine._quiescence_safe_threat_limit(snapshot, 0, 1, False), 1)
        self.assertEqual(
            engine._quiescence_safe_threat_limit(snapshot, -1, engine.tactical_depth, True),
            3,
        )


class TacticalSolverTests(unittest.TestCase):
    def test_solver_proves_double_threat_win(self) -> None:
        rows = [
            "...........",
            ".....B.....",
            "...........",
            ".....B.....",
            "...........",
            ".B.B.....B.",
            "...........",
            "...........",
            "...........",
            ".....B.....",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        solver = TacticalSolver()
        result = solver.solve(position, max_plies=6)
        self.assertEqual(result.outcome, TacticalOutcome.WIN)
        self.assertEqual(result.line[0], coord_to_index(5, 5))

    def test_solver_stays_unknown_on_empty_board(self) -> None:
        solver = TacticalSolver()
        result = solver.solve(Position.initial(), max_plies=6)
        self.assertEqual(result.outcome, TacticalOutcome.UNKNOWN)

    def test_search_uses_tactical_solver_on_sharp_position(self) -> None:
        rows = [
            "...........",
            ".....B.....",
            "...........",
            ".....B.....",
            "...........",
            ".B.B.....B.",
            "...........",
            "...........",
            "...........",
            ".....B.....",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        engine = SearchEngine()
        result = engine.search(position, max_depth=2)
        self.assertEqual(result.best_move, coord_to_index(5, 5))
        self.assertGreater(result.stats.tactical_solver_queries, 0)
        self.assertGreater(result.stats.tactical_solver_wins, 0)


class BenchmarkToolTests(unittest.TestCase):
    def test_search_benchmark_script_emits_expected_fields(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, "tools/search_benchmark.py", "--depth", "1"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 5)
        self.assertTrue(any("name=initial" in line for line in lines))
        self.assertTrue(any("name=restricted_threat_midgame" in line for line in lines))
        expected_fields = (
            "depth=",
            "elapsed_s=",
            "total_nodes=",
            "tactics_s=",
            "quiescence_s=",
            "proof_s=",
            "qtt_hits=",
            "qforced_single=",
            "qsafe_only=",
            "qsafe_pruned=",
            "qskip_frontier=",
            "qskip_wide=",
            "futility_prunes=",
            "late_move_prunes=",
        )
        for field in expected_fields:
            self.assertTrue(all(field in line for line in lines), msg=field)


if __name__ == "__main__":
    unittest.main()
