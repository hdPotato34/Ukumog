from __future__ import annotations

import unittest
from pathlib import Path

import play_gui
from ukumog_engine.search import RootMoveScore, SearchResult, SearchStats


class GUIHelperTests(unittest.TestCase):
    def test_parse_args_defaults_to_plain_board_mode(self) -> None:
        args = play_gui.parse_args([])
        self.assertEqual(args.mode, "human-vs-human")

    def test_parse_args_supports_side_specific_defaults(self) -> None:
        args = play_gui.parse_args(
            [
                "--mode",
                "engine-vs-engine",
                "--human",
                "white",
                "--depth",
                "5",
                "--black-depth",
                "6",
                "--white-time",
                "0.5",
                "--model",
                "checkpoints/base.pt",
                "--black-model",
                "checkpoints/black.pt",
                "--temperature-plies",
                "8",
                "--sample-top-k",
                "3",
                "--max-moves",
                "40",
                "--seed",
                "42",
            ]
        )

        self.assertEqual(args.mode, "engine-vs-engine")
        self.assertEqual(args.human, "white")
        self.assertEqual(args.depth, 5)
        self.assertEqual(args.black_depth, 6)
        self.assertEqual(args.white_time, 0.5)
        self.assertEqual(args.model, Path("checkpoints/base.pt"))
        self.assertEqual(args.black_model, Path("checkpoints/black.pt"))
        self.assertEqual(args.temperature_plies, 8)
        self.assertEqual(args.sample_top_k, 3)
        self.assertEqual(args.max_moves, 40)
        self.assertEqual(args.seed, 42)

    def test_score_and_move_formatters(self) -> None:
        self.assertEqual(play_gui.format_score_text(37), "+37")
        self.assertEqual(play_gui.format_score_text(-18), "-18")
        self.assertEqual(play_gui.format_move_text(None), "--")
        self.assertEqual(play_gui.format_move_text(0), "0, 0")

    def test_format_pv_text_limits_output(self) -> None:
        principal_variation = tuple(range(10))
        text = play_gui.format_pv_text(principal_variation, limit=3)
        self.assertEqual(text, "0, 0 -> 0, 1 -> 0, 2 ...")

    def test_top_root_rows_formats_rank_move_and_score(self) -> None:
        result = SearchResult(
            best_move=60,
            score=120,
            principal_variation=(60, 61),
            depth=3,
            stats=SearchStats(),
            root_move_scores=(RootMoveScore(move=60, score=120), RootMoveScore(move=61, score=95)),
        )

        rows = play_gui.top_root_rows(result)
        self.assertEqual(rows, [(1, "5, 5", "+120"), (2, "5, 6", "+95")])

    def test_board_cell_from_point_maps_canvas_space(self) -> None:
        metrics = play_gui.compute_board_metrics(600, 600)
        center_x = metrics.origin_x + (5.5 * metrics.cell_size)
        center_y = metrics.origin_y + (5.5 * metrics.cell_size)
        self.assertEqual(play_gui.board_cell_from_point(center_x, center_y, metrics), (5, 5))
        self.assertIsNone(play_gui.board_cell_from_point(metrics.origin_x - 5, metrics.origin_y - 5, metrics))

    def test_history_helpers_follow_current_ply(self) -> None:
        initial = play_gui.Position.initial()
        second, first_result = play_gui.play_move(initial, 60)
        third, second_result = play_gui.play_move(second, 61)
        history = [
            play_gui.PlayedMove(previous_position=initial, next_position=second, move=60, result=first_result, actor="A", color=play_gui.Color.BLACK),
            play_gui.PlayedMove(previous_position=second, next_position=third, move=61, result=second_result, actor="B", color=play_gui.Color.WHITE),
        ]

        self.assertEqual(play_gui.position_from_history(history, 0), initial)
        self.assertEqual(play_gui.position_from_history(history, 1), second)
        self.assertEqual(play_gui.position_from_history(history, 2), third)
        self.assertIsNone(play_gui.last_move_from_history(history, 0))
        self.assertEqual(play_gui.last_move_from_history(history, 2), 61)


if __name__ == "__main__":
    unittest.main()
