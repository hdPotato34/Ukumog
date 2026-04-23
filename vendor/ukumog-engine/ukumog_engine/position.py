from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .board import BOARD_CELLS, BOARD_SIZE, FULL_BOARD_MASK, bit, iter_set_bits
from .masks import DEFAULT_MASKS, MaskTables


class Color(Enum):
    BLACK = auto()
    WHITE = auto()

    @property
    def opponent(self) -> "Color":
        return Color.WHITE if self is Color.BLACK else Color.BLACK


class MoveResult(Enum):
    NONTERMINAL = auto()
    WIN = auto()
    LOSS = auto()


class MoveType(Enum):
    SAFE = auto()
    WINNING_NOW = auto()
    POISON = auto()


@dataclass(frozen=True, slots=True)
class Position:
    black_bits: int = 0
    white_bits: int = 0
    side_to_move: Color = Color.BLACK

    def __post_init__(self) -> None:
        overlap = self.black_bits & self.white_bits
        if overlap:
            raise ValueError(f"overlapping stones detected: {overlap:b}")

    @classmethod
    def initial(cls) -> "Position":
        return cls()

    @classmethod
    def from_rows(cls, rows: list[str] | tuple[str, ...], side_to_move: Color = Color.BLACK) -> "Position":
        if len(rows) != BOARD_SIZE:
            raise ValueError(f"expected {BOARD_SIZE} rows, found {len(rows)}")

        black_bits = 0
        white_bits = 0
        for row_index, row in enumerate(rows):
            if len(row) != BOARD_SIZE:
                raise ValueError(f"row {row_index} length is {len(row)} instead of {BOARD_SIZE}")
            for col_index, cell in enumerate(row):
                cell_bit = bit(row_index * BOARD_SIZE + col_index)
                if cell in {"B", "b", "X", "x"}:
                    black_bits |= cell_bit
                elif cell in {"W", "w", "O", "o"}:
                    white_bits |= cell_bit
                elif cell != ".":
                    raise ValueError(f"unexpected board character: {cell!r}")
        return cls(black_bits=black_bits, white_bits=white_bits, side_to_move=side_to_move)

    @property
    def occupied_bits(self) -> int:
        return self.black_bits | self.white_bits

    @property
    def empty_bits(self) -> int:
        return FULL_BOARD_MASK & ~self.occupied_bits

    @property
    def empty_count(self) -> int:
        return BOARD_CELLS - self.occupied_bits.bit_count()

    def color_bits(self, color: Color) -> int:
        return self.black_bits if color is Color.BLACK else self.white_bits

    def current_bits(self) -> int:
        return self.color_bits(self.side_to_move)

    def opponent_bits(self) -> int:
        return self.color_bits(self.side_to_move.opponent)

    def is_empty(self, move: int) -> bool:
        if not 0 <= move < BOARD_CELLS:
            return False
        return not bool(self.occupied_bits & bit(move))

    def legal_moves(self) -> list[int]:
        return list(iter_set_bits(self.empty_bits))

    def with_move(self, move: int) -> tuple["Position", MoveResult]:
        return play_move(self, move)

    def with_side_to_move(self, side_to_move: Color) -> "Position":
        return Position(
            black_bits=self.black_bits,
            white_bits=self.white_bits,
            side_to_move=side_to_move,
        )


def _resolve_result_for_bits(mover_bits: int, move: int, tables: MaskTables) -> MoveResult:
    for pattern in tables.incident5[move]:
        if mover_bits & pattern.bitmask == pattern.bitmask:
            return MoveResult.WIN

    for pattern in tables.incident4[move]:
        if mover_bits & pattern.bitmask == pattern.bitmask:
            return MoveResult.LOSS

    return MoveResult.NONTERMINAL


def classify_move(position: Position, move: int, tables: MaskTables = DEFAULT_MASKS) -> MoveType:
    if not position.is_empty(move):
        raise ValueError(f"illegal move on occupied or invalid cell: {move}")

    return classify_move_bits(position.current_bits(), position.occupied_bits, move, tables)


def classify_move_bits(
    current_bits: int, occupied_bits: int, move: int, tables: MaskTables = DEFAULT_MASKS
) -> MoveType:
    if occupied_bits & bit(move):
        raise ValueError(f"illegal move on occupied cell: {move}")

    mover_bits = current_bits | bit(move)
    result = _resolve_result_for_bits(mover_bits, move, tables)
    if result is MoveResult.WIN:
        return MoveType.WINNING_NOW
    if result is MoveResult.LOSS:
        return MoveType.POISON
    return MoveType.SAFE


def play_move(position: Position, move: int, tables: MaskTables = DEFAULT_MASKS) -> tuple[Position, MoveResult]:
    if not position.is_empty(move):
        raise ValueError(f"illegal move on occupied or invalid cell: {move}")

    move_bit = bit(move)
    if position.side_to_move is Color.BLACK:
        next_black_bits = position.black_bits | move_bit
        next_white_bits = position.white_bits
        mover_bits = next_black_bits
    else:
        next_black_bits = position.black_bits
        next_white_bits = position.white_bits | move_bit
        mover_bits = next_white_bits

    result = _resolve_result_for_bits(mover_bits, move, tables)
    next_position = Position(
        black_bits=next_black_bits,
        white_bits=next_white_bits,
        side_to_move=position.side_to_move.opponent,
    )
    return next_position, result
