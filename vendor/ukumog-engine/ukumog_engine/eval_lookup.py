from __future__ import annotations

from dataclasses import dataclass


FIVE_MASK_WEIGHTS = {1: 8, 2: 30, 3: 140, 4: 900}
FOUR_MASK_WEIGHTS = {1: 2, 2: 8, 3: -120}


@dataclass(frozen=True, slots=True)
class EvalLookupTables:
    four_table: tuple[int, ...]
    five_table: tuple[int, ...]


def _build_mask_eval_table(length: int, weights: dict[int, int]) -> tuple[int, ...]:
    table: list[int] = []
    states = 3**length

    for state_id in range(states):
        black_count = 0
        white_count = 0
        state = state_id
        for _ in range(length):
            digit = state % 3
            if digit == 1:
                black_count += 1
            elif digit == 2:
                white_count += 1
            state //= 3

        if black_count and white_count:
            table.append(0)
        elif black_count:
            table.append(weights.get(black_count, 0))
        elif white_count:
            table.append(-weights.get(white_count, 0))
        else:
            table.append(0)

    return tuple(table)


DEFAULT_EVAL_LOOKUPS = EvalLookupTables(
    four_table=_build_mask_eval_table(4, FOUR_MASK_WEIGHTS),
    five_table=_build_mask_eval_table(5, FIVE_MASK_WEIGHTS),
)
