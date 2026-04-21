from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SERVING_DIR = ROOT / "model-server" / "src" / "serving"
UKUMOG_DIR = ROOT / "ukumog-engine"

for path in (str(SERVING_DIR), str(UKUMOG_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from schemas import EngineConfig, EngineRequest, EngineState
from ukumog_adapter import EngineAdapterError, frontend_state_to_position, move_to_notation, run_engine_analysis


def empty_board() -> list[list[None]]:
    return [[None for _ in range(11)] for _ in range(11)]


def request_from_board(
    board: list[list[object | None]],
    *,
    turn: str = "B",
    board_size: int = 11,
    result: dict[str, object] | None = None,
    max_depth: int = 2,
    time_budget_ms: int = 120,
) -> EngineRequest:
    return EngineRequest(
        state=EngineState(
            board=board,
            turn=turn,
            result=result,
        ),
        config=EngineConfig(boardSize=board_size),
        timeBudgetMs=time_budget_ms,
        maxDepth=max_depth,
    )


class UkumogAdapterTests(unittest.TestCase):
    def test_empty_board_maps_and_returns_center_move(self) -> None:
        request = request_from_board(empty_board(), max_depth=1)
        position = frontend_state_to_position(request)
        self.assertEqual(position.empty_count, 121)

        response = run_engine_analysis(request)
        self.assertIsNotNone(response.bestMove)
        self.assertEqual((response.bestMove.row, response.bestMove.col), (5, 5))
        self.assertEqual(response.bestMove.notation, "F6")

    def test_win_now_position_returns_winning_move(self) -> None:
        board = empty_board()
        for col in (0, 2, 4, 6):
            board[5][col] = "B"

        response = run_engine_analysis(request_from_board(board, turn="B", max_depth=2))
        self.assertIsNotNone(response.bestMove)
        self.assertEqual((response.bestMove.row, response.bestMove.col), (5, 8))

    def test_forced_block_position_returns_safe_block(self) -> None:
        board = empty_board()
        for col in (0, 2, 4, 6):
            board[5][col] = "W"

        response = run_engine_analysis(request_from_board(board, turn="B", max_depth=2))
        self.assertIsNotNone(response.bestMove)
        self.assertEqual((response.bestMove.row, response.bestMove.col), (5, 8))

    def test_poison_position_does_not_choose_obvious_poison_move(self) -> None:
        board = empty_board()
        for col in (0, 2, 4):
            board[5][col] = "B"

        response = run_engine_analysis(request_from_board(board, turn="B", max_depth=1))
        self.assertIsNotNone(response.bestMove)
        self.assertNotEqual((response.bestMove.row, response.bestMove.col), (5, 6))

    def test_unsupported_board_size_raises_specific_error(self) -> None:
        request = request_from_board(empty_board(), board_size=9)

        with self.assertRaises(EngineAdapterError) as raised:
            frontend_state_to_position(request)

        self.assertEqual(raised.exception.code, "unsupported_board_size")

    def test_terminal_position_raises_specific_error(self) -> None:
        request = request_from_board(empty_board(), result={"winner": "B"})

        with self.assertRaises(EngineAdapterError) as raised:
            run_engine_analysis(request)

        self.assertEqual(raised.exception.code, "terminal_position")

    def test_response_contains_pv_nodes_time_and_notation(self) -> None:
        response = run_engine_analysis(request_from_board(empty_board(), max_depth=1))

        self.assertGreaterEqual(response.nodes, 0)
        self.assertGreaterEqual(response.timeMs, 0)
        self.assertTrue(response.pv)
        for move in response.pv:
            self.assertEqual(move.notation, move_to_notation(move.row, move.col))


if __name__ == "__main__":
    unittest.main()
