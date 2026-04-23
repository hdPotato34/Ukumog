from __future__ import annotations

from dataclasses import dataclass

from .board import BOARD_SIZE, bit, iter_set_bits
from .incremental import IncrementalState
from .masks import DEFAULT_MASKS, MaskTables
from .position import Position
from .tactical_detail import TacticalDetail, resolve_tactical_detail


@dataclass(frozen=True, slots=True)
class TacticalSnapshot:
    candidate_moves: tuple[int, ...]
    safe_moves: tuple[int, ...]
    winning_moves: tuple[int, ...]
    poison_moves: tuple[int, ...]
    forced_blocks: tuple[int, ...]
    safe_threats: tuple[int, ...]
    double_threats: tuple[int, ...]
    opponent_winning_moves: tuple[int, ...]
    future_wins_by_move: dict[int, tuple[int, ...]]
    opponent_wins_after_move: dict[int, tuple[int, ...]]
    restricted_pressure: int
    opponent_restricted_pressure: int
    critical_restricted_lines: int
    opponent_critical_restricted_lines: int
    restricted_move_pressure: dict[int, int]
    critical_restricted_builds: tuple[int, ...]
    critical_restricted_responses: tuple[int, ...]

    @property
    def urgent(self) -> bool:
        return bool(
            self.winning_moves
            or self.opponent_winning_moves
            or self.safe_threats
            or self.critical_restricted_lines
            or self.opponent_critical_restricted_lines
        )

    def tactical_moves(self) -> tuple[int, ...]:
        if self.winning_moves:
            return self.winning_moves
        if self.opponent_winning_moves:
            return self.forced_blocks

        ordered: list[int] = []
        for bucket in (
            self.double_threats,
            self.safe_threats,
            self.critical_restricted_responses,
            self.critical_restricted_builds,
        ):
            for move in bucket:
                if move not in ordered:
                    ordered.append(move)
        return tuple(ordered)


def _candidate_bits(position: Position, tables: MaskTables) -> int:
    occupied_bits = position.occupied_bits
    if not occupied_bits:
        center = BOARD_SIZE // 2
        return bit(center * BOARD_SIZE + center)

    relevant_bits = 0
    for cell in iter_set_bits(occupied_bits):
        relevant_bits |= tables.influence[cell]

    candidate_bits = relevant_bits & position.empty_bits
    if candidate_bits:
        return candidate_bits
    return position.empty_bits


def _moves_to_bits(candidate_moves: set[int] | tuple[int, ...] | list[int]) -> int:
    bits = 0
    for move in candidate_moves:
        bits |= bit(move)
    return bits


def relevant_empty_cells(position: Position, tables: MaskTables = DEFAULT_MASKS) -> set[int]:
    return set(iter_set_bits(_candidate_bits(position, tables)))


def _winning_move_masks(
    player_bits: int,
    opponent_bits: int,
    candidate_bits: int,
    tables: MaskTables,
) -> dict[int, tuple[int, ...]]:
    winning_masks: dict[int, list[int]] = {}
    for pattern in tables.masks5:
        pattern_bits = pattern.bitmask
        if pattern_bits & opponent_bits:
            continue

        missing_bits = pattern_bits & ~player_bits
        if missing_bits.bit_count() != 1 or not (missing_bits & candidate_bits):
            continue

        move = missing_bits.bit_length() - 1
        winning_masks.setdefault(move, []).append(pattern_bits)

    return {move: tuple(masks) for move, masks in winning_masks.items()}


def _ordered_candidate_moves(position: Position, tables: MaskTables, candidate_moves: set[int] | None) -> tuple[int, ...]:
    if candidate_moves is None:
        return iter_set_bits(_candidate_bits(position, tables))
    return tuple(sorted(candidate_moves))


def immediate_winning_moves(
    position: Position, tables: MaskTables = DEFAULT_MASKS, candidate_moves: set[int] | None = None
) -> tuple[int, ...]:
    ordered_candidates = _ordered_candidate_moves(position, tables, candidate_moves)
    candidate_bits = _moves_to_bits(ordered_candidates)
    winning_masks = _winning_move_masks(position.current_bits(), position.opponent_bits(), candidate_bits, tables)
    return tuple(move for move in ordered_candidates if move in winning_masks)


def analyze_tactics(
    position: Position,
    tables: MaskTables = DEFAULT_MASKS,
    candidate_moves: set[int] | None = None,
    inc_state: IncrementalState | None = None,
    include_move_maps: bool = True,
) -> TacticalSnapshot:
    detail = resolve_tactical_detail(include_move_maps=include_move_maps)
    resolved_state = inc_state if inc_state is not None else IncrementalState.from_position(position, tables)
    summary = resolved_state.tactical_summary(
        position.side_to_move,
        candidate_moves,
        include_move_maps,
        detail=detail,
    )
    return TacticalSnapshot(
        candidate_moves=summary.candidate_moves,
        safe_moves=summary.safe_moves,
        winning_moves=summary.winning_moves,
        poison_moves=summary.poison_moves,
        forced_blocks=summary.forced_blocks,
        safe_threats=summary.safe_threats,
        double_threats=summary.double_threats,
        opponent_winning_moves=summary.opponent_winning_moves,
        future_wins_by_move=summary.future_wins_by_move,
        opponent_wins_after_move=summary.opponent_wins_after_move,
        restricted_pressure=summary.restricted_pressure,
        opponent_restricted_pressure=summary.opponent_restricted_pressure,
        critical_restricted_lines=summary.critical_restricted_lines,
        opponent_critical_restricted_lines=summary.opponent_critical_restricted_lines,
        restricted_move_pressure=summary.restricted_move_pressure,
        critical_restricted_builds=summary.critical_restricted_builds,
        critical_restricted_responses=summary.critical_restricted_responses,
    )
