from __future__ import annotations

import numpy as np

from ..board import BOARD_CELLS, BOARD_SIZE, iter_set_bits
from ..masks import DEFAULT_MASKS, MaskTables
from ..position import Position
from ..tactics import TacticalSnapshot, analyze_tactics

FEATURE_NAMES = (
    "current_stones",
    "opponent_stones",
    "empty_cells",
    "safe_moves",
    "winning_moves",
    "poison_moves",
    "forced_blocks",
    "safe_threats",
    "double_threats",
    "opponent_winning_moves",
    "opponent_safe_threats",
    "opponent_double_threats",
    "occupancy_ratio",
    "row_coord",
    "col_coord",
)
FEATURE_CHANNELS = len(FEATURE_NAMES)


def _bits_to_plane(bits: int) -> np.ndarray:
    plane = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
    for index in iter_set_bits(bits):
        row, col = divmod(index, BOARD_SIZE)
        plane[row, col] = 1.0
    return plane


def _moves_to_bits(moves: tuple[int, ...]) -> int:
    bits = 0
    for move in moves:
        bits |= 1 << move
    return bits


def encode_position(
    position: Position,
    tables: MaskTables = DEFAULT_MASKS,
    snapshot: TacticalSnapshot | None = None,
    opponent_snapshot: TacticalSnapshot | None = None,
) -> np.ndarray:
    current_snapshot = snapshot if snapshot is not None else analyze_tactics(position, tables)
    opponent_position = position.with_side_to_move(position.side_to_move.opponent)
    other_snapshot = (
        opponent_snapshot if opponent_snapshot is not None else analyze_tactics(opponent_position, tables)
    )

    current_bits = position.current_bits()
    opponent_bits = position.opponent_bits()
    empty_bits = position.empty_bits

    features = np.zeros((FEATURE_CHANNELS, BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
    features[0] = _bits_to_plane(current_bits)
    features[1] = _bits_to_plane(opponent_bits)
    features[2] = _bits_to_plane(empty_bits)
    features[3] = _bits_to_plane(_moves_to_bits(current_snapshot.safe_moves))
    features[4] = _bits_to_plane(_moves_to_bits(current_snapshot.winning_moves))
    features[5] = _bits_to_plane(_moves_to_bits(current_snapshot.poison_moves))
    features[6] = _bits_to_plane(_moves_to_bits(current_snapshot.forced_blocks))
    features[7] = _bits_to_plane(_moves_to_bits(current_snapshot.safe_threats))
    features[8] = _bits_to_plane(_moves_to_bits(current_snapshot.double_threats))
    features[9] = _bits_to_plane(_moves_to_bits(current_snapshot.opponent_winning_moves))
    features[10] = _bits_to_plane(_moves_to_bits(other_snapshot.safe_threats))
    features[11] = _bits_to_plane(_moves_to_bits(other_snapshot.double_threats))
    features[12].fill(1.0 - (position.empty_count / BOARD_CELLS))

    coords = np.linspace(-1.0, 1.0, BOARD_SIZE, dtype=np.float32)
    features[13] = coords[:, None]
    features[14] = coords[None, :]
    return features
