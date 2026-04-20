from __future__ import annotations

import numpy as np

from ..board import BOARD_SIZE, coord_to_index, index_to_coord

SYMMETRY_COUNT = 8
INVERSE_SYMMETRY = (0, 3, 2, 1, 4, 5, 6, 7)


def transform_coords(row: int, col: int, symmetry: int) -> tuple[int, int]:
    if not 0 <= symmetry < SYMMETRY_COUNT:
        raise ValueError(f"invalid symmetry id: {symmetry}")

    last = BOARD_SIZE - 1
    if symmetry == 0:
        return row, col
    if symmetry == 1:
        return last - col, row
    if symmetry == 2:
        return last - row, last - col
    if symmetry == 3:
        return col, last - row
    if symmetry == 4:
        return row, last - col
    if symmetry == 5:
        return col, row
    if symmetry == 6:
        return last - row, col
    return last - col, last - row


def transform_index(index: int, symmetry: int) -> int:
    row, col = index_to_coord(index)
    next_row, next_col = transform_coords(row, col, symmetry)
    return coord_to_index(next_row, next_col)


def transform_planes(planes: np.ndarray, symmetry: int) -> np.ndarray:
    if planes.ndim < 2:
        raise ValueError("expected at least 2 dimensions for plane transform")

    array = planes
    if symmetry == 0:
        return array.copy()
    if symmetry == 1:
        return np.rot90(array, 1, axes=(-2, -1)).copy()
    if symmetry == 2:
        return np.rot90(array, 2, axes=(-2, -1)).copy()
    if symmetry == 3:
        return np.rot90(array, 3, axes=(-2, -1)).copy()
    if symmetry == 4:
        return np.flip(array, axis=-1).copy()
    if symmetry == 5:
        return np.rot90(np.flip(array, axis=-1), 1, axes=(-2, -1)).copy()
    if symmetry == 6:
        return np.rot90(np.flip(array, axis=-1), 2, axes=(-2, -1)).copy()
    if symmetry == 7:
        return np.rot90(np.flip(array, axis=-1), 3, axes=(-2, -1)).copy()
    raise ValueError(f"invalid symmetry id: {symmetry}")


def transform_flat_mask(mask: np.ndarray, symmetry: int) -> np.ndarray:
    planes = np.asarray(mask).reshape(BOARD_SIZE, BOARD_SIZE)
    return transform_planes(planes, symmetry).reshape(-1)


def inverse_symmetry(symmetry: int) -> int:
    if not 0 <= symmetry < SYMMETRY_COUNT:
        raise ValueError(f"invalid symmetry id: {symmetry}")
    return INVERSE_SYMMETRY[symmetry]
