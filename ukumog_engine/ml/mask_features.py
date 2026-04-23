from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..incremental import IncrementalState
from ..masks import DEFAULT_MASKS
from ..position import Color, Position

FOUR_MASK_COUNT = len(DEFAULT_MASKS.masks4)
FIVE_MASK_COUNT = len(DEFAULT_MASKS.masks5)
FOUR_STATE_COUNT = 3**4
FIVE_STATE_COUNT = 3**5
TOTAL_MASK_FEATURES = (FOUR_MASK_COUNT * FOUR_STATE_COUNT) + (FIVE_MASK_COUNT * FIVE_STATE_COUNT)


def _swap_colors_in_state(state_id: int, length: int) -> int:
    swapped = 0
    factor = 1
    state = state_id
    for _ in range(length):
        digit = state % 3
        if digit == 1:
            digit = 2
        elif digit == 2:
            digit = 1
        swapped += digit * factor
        factor *= 3
        state //= 3
    return swapped


@lru_cache(maxsize=2)
def _normalization_tables() -> tuple[np.ndarray, np.ndarray]:
    table4 = np.array(
        [_swap_colors_in_state(state_id, 4) for state_id in range(FOUR_STATE_COUNT)],
        dtype=np.uint8,
    )
    table5 = np.array(
        [_swap_colors_in_state(state_id, 5) for state_id in range(FIVE_STATE_COUNT)],
        dtype=np.uint8,
    )
    return table4, table5


def encode_mask_states(
    position: Position,
    incremental_state: IncrementalState | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    resolved_state = incremental_state if incremental_state is not None else IncrementalState.from_position(position)
    four_states = np.asarray(resolved_state.four_state_id, dtype=np.uint8)
    five_states = np.asarray(resolved_state.five_state_id, dtype=np.uint8)
    if position.side_to_move is Color.BLACK:
        return four_states, five_states

    table4, table5 = _normalization_tables()
    return table4[four_states], table5[five_states]
