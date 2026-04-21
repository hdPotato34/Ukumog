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
        self.assertGreaterEqual(len(lines), 4)
        self.assertTrue(any("name=initial" in line for line in lines))
        expected_fields = (
            "depth=",
            "elapsed_s=",
            "total_nodes=",
            "tactics_s=",
            "quiescence_s=",
            "proof_s=",
            "qtt_hits=",
            "futility_prunes=",
            "late_move_prunes=",
        )
        for field in expected_fields:
            self.assertTrue(all(field in line for line in lines), msg=field)


if __name__ == "__main__":
    unittest.main()
