from __future__ import annotations

import random
import unittest

from ukumog_engine import (
    DEFAULT_MASKS,
    Color,
    IncrementalState,
    MoveType,
    Position,
    analyze_tactics,
    classify_move,
    evaluate,
    immediate_winning_moves,
    play_move,
)
from ukumog_engine.eval_lookup import FIVE_MASK_WEIGHTS, FOUR_MASK_WEIGHTS


def _random_nonterminal_position(seed: int, plies: int = 18) -> Position:
    rng = random.Random(seed)
    position = Position.initial()
    played = 0
    while played < plies:
        move = rng.choice(position.legal_moves())
        next_position, result = play_move(position, move)
        if result.name != "NONTERMINAL":
            position = Position.initial()
            played = 0
            continue
        position = next_position
        played += 1
    return position


def _absolute_mask_score(position: Position) -> int:
    score = 0
    for pattern in DEFAULT_MASKS.masks5:
        black_count = (position.black_bits & pattern.bitmask).bit_count()
        white_count = (position.white_bits & pattern.bitmask).bit_count()
        if black_count and white_count:
            continue
        if black_count:
            score += FIVE_MASK_WEIGHTS.get(black_count, 0)
        elif white_count:
            score -= FIVE_MASK_WEIGHTS.get(white_count, 0)

    for pattern in DEFAULT_MASKS.masks4:
        black_count = (position.black_bits & pattern.bitmask).bit_count()
        white_count = (position.white_bits & pattern.bitmask).bit_count()
        if black_count and white_count:
            continue
        if black_count:
            score += FOUR_MASK_WEIGHTS.get(black_count, 0)
        elif white_count:
            score -= FOUR_MASK_WEIGHTS.get(white_count, 0)

    return score


class IncrementalStateTests(unittest.TestCase):
    def test_make_unmake_restores_position_and_counts(self) -> None:
        position = _random_nonterminal_position(20260419, plies=12)
        state = IncrementalState.from_position(position)
        baseline = state.copy()
        move = position.legal_moves()[0]

        undo = state.make_move(move)
        state.unmake_move(undo)

        self.assertEqual(state.to_position(), position)
        self.assertEqual(state.four_black_count, baseline.four_black_count)
        self.assertEqual(state.four_white_count, baseline.four_white_count)
        self.assertEqual(state.four_state_id, baseline.four_state_id)
        self.assertEqual(state.five_black_count, baseline.five_black_count)
        self.assertEqual(state.five_white_count, baseline.five_white_count)
        self.assertEqual(state.five_state_id, baseline.five_state_id)

    def test_classify_move_matches_existing_rule_logic(self) -> None:
        for seed in range(12):
            position = _random_nonterminal_position(1000 + seed, plies=10 + seed)
            state = IncrementalState.from_position(position)
            for move in position.legal_moves():
                self.assertEqual(
                    state.classify_move(move),
                    classify_move(position, move),
                    msg=f"seed={seed} move={move}",
                )

    def test_winning_moves_match_existing_detector_for_both_sides(self) -> None:
        for seed in range(10):
            position = _random_nonterminal_position(2000 + seed, plies=8 + seed)
            state = IncrementalState.from_position(position)
            self.assertEqual(
                state.winning_moves(position.side_to_move),
                immediate_winning_moves(position),
            )

            opponent = position.side_to_move.opponent
            self.assertEqual(
                state.winning_moves(opponent),
                immediate_winning_moves(position.with_side_to_move(opponent)),
            )

    def test_poison_moves_match_incremental_classification(self) -> None:
        position = Position.from_rows(
            [
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
            ],
            side_to_move=Color.BLACK,
        )
        state = IncrementalState.from_position(position)
        expected = tuple(
            move
            for move in position.legal_moves()
            if state.classify_move(move) is MoveType.POISON
        )
        self.assertEqual(state.poison_moves(), expected)

    def test_explicit_color_queries_work_without_changing_side_to_move(self) -> None:
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
        state = IncrementalState.from_position(position)

        self.assertTrue(state.has_immediate_win(Color.WHITE))
        self.assertEqual(state.winning_moves(Color.WHITE), (63,))
        self.assertEqual(state.side_to_move, Color.BLACK)

    def test_tactical_summary_matches_full_tactics_snapshot(self) -> None:
        for seed in range(10):
            position = _random_nonterminal_position(3000 + seed, plies=10 + seed)
            state = IncrementalState.from_position(position)
            self.assertEqual(
                analyze_tactics(position),
                analyze_tactics(position, inc_state=state),
                msg=f"seed={seed}",
            )

    def test_light_tactical_snapshot_preserves_tactical_sets(self) -> None:
        for seed in range(8):
            position = _random_nonterminal_position(3500 + seed, plies=9 + seed)
            state = IncrementalState.from_position(position)
            full = analyze_tactics(position, inc_state=state)
            light = analyze_tactics(position, inc_state=state, include_move_maps=False)

            self.assertEqual(full.candidate_moves, light.candidate_moves, msg=f"seed={seed}")
            self.assertEqual(full.safe_moves, light.safe_moves, msg=f"seed={seed}")
            self.assertEqual(full.winning_moves, light.winning_moves, msg=f"seed={seed}")
            self.assertEqual(full.poison_moves, light.poison_moves, msg=f"seed={seed}")
            self.assertEqual(full.forced_blocks, light.forced_blocks, msg=f"seed={seed}")
            self.assertEqual(full.safe_threats, light.safe_threats, msg=f"seed={seed}")
            self.assertEqual(full.double_threats, light.double_threats, msg=f"seed={seed}")
            self.assertEqual(full.opponent_winning_moves, light.opponent_winning_moves, msg=f"seed={seed}")
            self.assertEqual(light.future_wins_by_move, {}, msg=f"seed={seed}")
            self.assertEqual(light.opponent_wins_after_move, {}, msg=f"seed={seed}")

    def test_move_maps_match_full_snapshot_for_subset(self) -> None:
        position = _random_nonterminal_position(3601, plies=12)
        state = IncrementalState.from_position(position)
        full = analyze_tactics(position, inc_state=state)
        subset = tuple(full.safe_moves[: min(5, len(full.safe_moves))])

        future_wins_by_move, opponent_wins_after_move = state.move_maps(
            subset,
            position.side_to_move,
            candidate_moves=full.candidate_moves,
        )

        self.assertEqual(
            future_wins_by_move,
            {move: full.future_wins_by_move[move] for move in subset},
        )
        self.assertEqual(
            opponent_wins_after_move,
            {move: full.opponent_wins_after_move[move] for move in subset},
        )

    def test_future_winning_moves_match_full_snapshot_for_subset(self) -> None:
        for seed in range(6):
            position = _random_nonterminal_position(3650 + seed, plies=11 + seed)
            state = IncrementalState.from_position(position)
            full = analyze_tactics(position, inc_state=state)
            subset = tuple(full.safe_moves[: min(6, len(full.safe_moves))])

            for move in subset:
                self.assertEqual(
                    state.future_winning_moves_from_move(move, position.side_to_move),
                    full.future_wins_by_move[move],
                    msg=f"seed={seed} move={move}",
                )

    def test_move_map_counts_match_full_snapshot_for_subset(self) -> None:
        position = _random_nonterminal_position(3602, plies=13)
        state = IncrementalState.from_position(position)
        full = analyze_tactics(position, inc_state=state)
        subset = tuple(full.safe_moves[: min(6, len(full.safe_moves))])

        future_win_counts, opponent_remaining_counts = state.move_map_counts(
            subset,
            position.side_to_move,
            candidate_moves=full.candidate_moves,
        )

        self.assertEqual(
            future_win_counts,
            {move: len(full.future_wins_by_move[move]) for move in subset},
        )
        self.assertEqual(
            opponent_remaining_counts,
            {move: len(full.opponent_wins_after_move[move]) for move in subset},
        )

    def test_move_maps_match_full_snapshot_for_forced_block_subset(self) -> None:
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
        state = IncrementalState.from_position(position)
        full = analyze_tactics(position, inc_state=state)
        subset = tuple(full.safe_moves[: min(4, len(full.safe_moves))])

        future_wins_by_move, opponent_wins_after_move = state.move_maps(
            subset,
            position.side_to_move,
            candidate_moves=full.candidate_moves,
        )

        self.assertEqual(
            future_wins_by_move,
            {move: full.future_wins_by_move[move] for move in subset},
        )
        self.assertEqual(
            opponent_wins_after_move,
            {move: full.opponent_wins_after_move[move] for move in subset},
        )

    def test_move_map_counts_match_full_snapshot_for_forced_block_subset(self) -> None:
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
        state = IncrementalState.from_position(position)
        full = analyze_tactics(position, inc_state=state)
        subset = tuple(full.safe_moves[: min(4, len(full.safe_moves))])

        future_win_counts, opponent_remaining_counts = state.move_map_counts(
            subset,
            position.side_to_move,
            candidate_moves=full.candidate_moves,
        )

        self.assertEqual(
            future_win_counts,
            {move: len(full.future_wins_by_move[move]) for move in subset},
        )
        self.assertEqual(
            opponent_remaining_counts,
            {move: len(full.opponent_wins_after_move[move]) for move in subset},
        )

    def test_incremental_tactical_queries_match_known_forcing_position(self) -> None:
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
        state = IncrementalState.from_position(position)
        summary = state.tactical_summary()

        self.assertEqual(summary.opponent_winning_moves, (63,))
        self.assertEqual(summary.forced_blocks, (63,))
        self.assertEqual(state.forced_blocks(), (63,))

    def test_lookup_score_matches_bruteforce_mask_score(self) -> None:
        for seed in range(10):
            position = _random_nonterminal_position(4000 + seed, plies=9 + seed)
            state = IncrementalState.from_position(position)
            self.assertEqual(
                state.absolute_lookup_score(),
                _absolute_mask_score(position),
                msg=f"seed={seed}",
            )

    def test_evaluate_matches_with_and_without_incremental_lookup_state(self) -> None:
        for seed in range(8):
            position = _random_nonterminal_position(5000 + seed, plies=11 + seed)
            state = IncrementalState.from_position(position)
            self.assertEqual(
                evaluate(position),
                evaluate(position, incremental_state=state),
                msg=f"seed={seed}",
            )


if __name__ == "__main__":
    unittest.main()
