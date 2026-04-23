from __future__ import annotations

BOARD_SIZE = 11
BOARD_CELLS = BOARD_SIZE * BOARD_SIZE
FULL_BOARD_MASK = (1 << BOARD_CELLS) - 1


def is_on_board(row: int, col: int, board_size: int = BOARD_SIZE) -> bool:
    return 0 <= row < board_size and 0 <= col < board_size


def coord_to_index(row: int, col: int, board_size: int = BOARD_SIZE) -> int:
    if not is_on_board(row, col, board_size):
        raise ValueError(f"coordinate {(row, col)} is outside a {board_size}x{board_size} board")
    return row * board_size + col


def index_to_coord(index: int, board_size: int = BOARD_SIZE) -> tuple[int, int]:
    if not 0 <= index < board_size * board_size:
        raise ValueError(f"cell index {index} is outside a {board_size}x{board_size} board")
    return divmod(index, board_size)


def bit(index: int) -> int:
    return 1 << index


def iter_set_bits(bits: int) -> tuple[int, ...]:
    found: list[int] = []
    remaining = bits
    while remaining:
        lsb = remaining & -remaining
        found.append(lsb.bit_length() - 1)
        remaining ^= lsb
    return tuple(found)
