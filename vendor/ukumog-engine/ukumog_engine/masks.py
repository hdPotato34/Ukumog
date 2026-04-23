from __future__ import annotations

from dataclasses import dataclass

from .board import BOARD_CELLS, BOARD_SIZE, bit, coord_to_index, is_on_board


@dataclass(frozen=True, slots=True)
class PatternMask:
    length: int
    cells: tuple[int, ...]
    bitmask: int


@dataclass(frozen=True, slots=True)
class MaskTables:
    board_size: int
    masks4: tuple[PatternMask, ...]
    masks5: tuple[PatternMask, ...]
    incident4: tuple[tuple[PatternMask, ...], ...]
    incident5: tuple[tuple[PatternMask, ...], ...]
    influence: tuple[int, ...]


def _all_steps(board_size: int) -> tuple[tuple[int, int], ...]:
    steps: list[tuple[int, int]] = []
    for d_row in range(-(board_size - 1), board_size):
        for d_col in range(-(board_size - 1), board_size):
            if d_row == 0 and d_col == 0:
                continue
            steps.append((d_row, d_col))
    return tuple(steps)


def _build_patterns(board_size: int, length: int) -> tuple[PatternMask, ...]:
    steps = _all_steps(board_size)
    seen: set[tuple[int, ...]] = set()

    for row in range(board_size):
        for col in range(board_size):
            for d_row, d_col in steps:
                cells: list[int] = []
                valid = True
                for offset in range(length):
                    next_row = row + offset * d_row
                    next_col = col + offset * d_col
                    if not is_on_board(next_row, next_col, board_size):
                        valid = False
                        break
                    cells.append(coord_to_index(next_row, next_col, board_size))
                if valid:
                    seen.add(tuple(sorted(cells)))

    patterns = tuple(
        PatternMask(
            length=length,
            cells=cells,
            bitmask=sum(bit(cell) for cell in cells),
        )
        for cells in sorted(seen)
    )
    return patterns


def _build_incident_table(
    patterns: tuple[PatternMask, ...], board_cells: int = BOARD_CELLS
) -> tuple[tuple[PatternMask, ...], ...]:
    incident: list[list[PatternMask]] = [[] for _ in range(board_cells)]
    for pattern in patterns:
        for cell in pattern.cells:
            incident[cell].append(pattern)
    return tuple(tuple(entries) for entries in incident)


def _build_influence_table(
    incident4: tuple[tuple[PatternMask, ...], ...],
    incident5: tuple[tuple[PatternMask, ...], ...],
) -> tuple[int, ...]:
    influence: list[int] = []
    for cell in range(len(incident4)):
        cell_bits = 0
        for pattern in incident4[cell]:
            cell_bits |= pattern.bitmask
        for pattern in incident5[cell]:
            cell_bits |= pattern.bitmask
        influence.append(cell_bits)
    return tuple(influence)


def generate_masks(board_size: int = BOARD_SIZE) -> MaskTables:
    board_cells = board_size * board_size
    masks4 = _build_patterns(board_size, 4)
    masks5 = _build_patterns(board_size, 5)
    incident4 = _build_incident_table(masks4, board_cells)
    incident5 = _build_incident_table(masks5, board_cells)
    influence = _build_influence_table(incident4, incident5)
    return MaskTables(
        board_size=board_size,
        masks4=masks4,
        masks5=masks5,
        incident4=incident4,
        incident5=incident5,
        influence=influence,
    )


DEFAULT_MASKS = generate_masks()

if len(DEFAULT_MASKS.masks4) != 780:
    raise RuntimeError(f"expected 780 four-pattern masks, found {len(DEFAULT_MASKS.masks4)}")

if len(DEFAULT_MASKS.masks5) != 420:
    raise RuntimeError(f"expected 420 five-pattern masks, found {len(DEFAULT_MASKS.masks5)}")
