from __future__ import annotations

from .board import BOARD_SIZE, bit, coord_to_index, index_to_coord, is_on_board
from .position import MoveResult, Position


def _canonical_steps(board_size: int) -> tuple[tuple[int, int], ...]:
    steps: list[tuple[int, int]] = []
    for d_row in range(-(board_size - 1), board_size):
        for d_col in range(-(board_size - 1), board_size):
            if d_row == 0 and d_col == 0:
                continue
            if d_row < 0:
                continue
            if d_row == 0 and d_col < 0:
                continue
            steps.append((d_row, d_col))
    return tuple(steps)


def _has_pattern_through_move(bits: int, move: int, length: int, board_size: int) -> bool:
    row, col = index_to_coord(move, board_size)
    for d_row, d_col in _canonical_steps(board_size):
        for offset in range(length):
            start_row = row - offset * d_row
            start_col = col - offset * d_col
            cells: list[int] = []
            valid = True
            for step in range(length):
                next_row = start_row + step * d_row
                next_col = start_col + step * d_col
                if not is_on_board(next_row, next_col, board_size):
                    valid = False
                    break
                cells.append(coord_to_index(next_row, next_col, board_size))
            if valid and all(bits & bit(cell) for cell in cells):
                return True
    return False


def brute_force_move_result(position: Position, move: int, board_size: int = BOARD_SIZE) -> MoveResult:
    if not position.is_empty(move):
        raise ValueError(f"illegal move on occupied or invalid cell: {move}")

    mover_bits = position.current_bits() | bit(move)
    if _has_pattern_through_move(mover_bits, move, 5, board_size):
        return MoveResult.WIN
    if _has_pattern_through_move(mover_bits, move, 4, board_size):
        return MoveResult.LOSS
    return MoveResult.NONTERMINAL
