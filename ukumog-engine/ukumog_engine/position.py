from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from .board import BOARD_SIZE, bit, iter_set_bits
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
    board_size: int = field(default=BOARD_SIZE)

    def __post_init__(self) -> None:
        overlap = self.black_bits & self.white_bits
        if overlap:
            raise ValueError(f"overlapping stones detected: {overlap:b}")
        if self.board_size <= 0:
            raise ValueError("board_size must be positive")
        max_bits = 1 << (self.board_size * self.board_size)
        if self.black_bits < 0 or self.white_bits < 0:
            raise ValueError("bitboards cannot be negative")
        if self.black_bits >= max_bits or self.white_bits >= max_bits:
            raise ValueError(f"stones exceed the {self.board_size}x{self.board_size} board bounds")

    @classmethod
    def initial(cls, board_size: int = BOARD_SIZE) -> "Position":
        return cls(board_size=board_size)

    @classmethod
    def from_rows(
        cls,
        rows: list[str] | tuple[str, ...],
        side_to_move: Color = Color.BLACK,
        board_size: int | None = None,
    ) -> "Position":
        resolved_board_size = len(rows) if board_size is None else board_size
        if len(rows) != resolved_board_size:
            raise ValueError(f"expected {resolved_board_size} rows, found {len(rows)}")

        black_bits = 0
        white_bits = 0
        for row_index, row in enumerate(rows):
            if len(row) != resolved_board_size:
                raise ValueError(f"row {row_index} length is {len(row)} instead of {resolved_board_size}")
            for col_index, cell in enumerate(row):
                cell_bit = bit(row_index * resolved_board_size + col_index)
                if cell in {"B", "b", "X", "x"}:
                    black_bits |= cell_bit
                elif cell in {"W", "w", "O", "o"}:
                    white_bits |= cell_bit
                elif cell != ".":
                    raise ValueError(f"unexpected board character: {cell!r}")
        return cls(
            black_bits=black_bits,
            white_bits=white_bits,
            side_to_move=side_to_move,
            board_size=resolved_board_size,
        )

    @property
    def occupied_bits(self) -> int:
        return self.black_bits | self.white_bits

    @property
    def empty_bits(self) -> int:
        return ((1 << (self.board_size * self.board_size)) - 1) & ~self.occupied_bits

    @property
    def empty_count(self) -> int:
        return (self.board_size * self.board_size) - self.occupied_bits.bit_count()

    def color_bits(self, color: Color) -> int:
        return self.black_bits if color is Color.BLACK else self.white_bits

    def current_bits(self) -> int:
        return self.color_bits(self.side_to_move)

    def opponent_bits(self) -> int:
        return self.color_bits(self.side_to_move.opponent)

    def is_empty(self, move: int) -> bool:
        if not 0 <= move < self.board_size * self.board_size:
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
            board_size=self.board_size,
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
        board_size=position.board_size,
    )
    return next_position, result
