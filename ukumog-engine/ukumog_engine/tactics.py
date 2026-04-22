from __future__ import annotations

from dataclasses import dataclass

from .board import bit, iter_set_bits
from .incremental import IncrementalState
from .masks import DEFAULT_MASKS, MaskTables
from .position import MoveType, Position, classify_move_bits
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

    @property
    def urgent(self) -> bool:
        return bool(self.winning_moves or self.opponent_winning_moves or self.safe_threats)

    def tactical_moves(self) -> tuple[int, ...]:
        if self.winning_moves:
            return self.winning_moves
        if self.opponent_winning_moves:
            return self.forced_blocks

        ordered: list[int] = []
        for bucket in (self.double_threats, self.safe_threats):
            for move in bucket:
                if move not in ordered:
                    ordered.append(move)
        return tuple(ordered)


def _candidate_bits(position: Position, tables: MaskTables) -> int:
    occupied_bits = position.occupied_bits
    if not occupied_bits:
        center = tables.board_size // 2
        return bit(center * tables.board_size + center)

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


def _future_wins_from_move(
    current_bits: int,
    opponent_bits: int,
    occupied_bits: int,
    move: int,
    tables: MaskTables,
) -> tuple[int, ...]:
    move_bit = bit(move)
    future_win_bits = 0
    for pattern in tables.incident5[move]:
        pattern_bits = pattern.bitmask
        if pattern_bits & opponent_bits:
            continue

        other_bits = pattern_bits ^ move_bit
        if (current_bits & other_bits).bit_count() != 3:
            continue

        empty_bits = other_bits & ~occupied_bits
        if empty_bits.bit_count() == 1:
            future_win_bits |= empty_bits

    return iter_set_bits(future_win_bits)


def _future_win_count_from_move(
    current_bits: int,
    opponent_bits: int,
    occupied_bits: int,
    move: int,
    tables: MaskTables,
) -> int:
    move_bit = bit(move)
    future_win_bits = 0
    for pattern in tables.incident5[move]:
        pattern_bits = pattern.bitmask
        if pattern_bits & opponent_bits:
            continue

        other_bits = pattern_bits ^ move_bit
        if (current_bits & other_bits).bit_count() != 3:
            continue

        empty_bits = other_bits & ~occupied_bits
        if empty_bits.bit_count() == 1:
            future_win_bits |= empty_bits

    return future_win_bits.bit_count()


def _remaining_wins_after_move(
    move: int,
    winning_masks_by_move: dict[int, tuple[int, ...]],
) -> tuple[int, ...]:
    move_bit = bit(move)
    remaining: list[int] = []
    for winning_move, masks in winning_masks_by_move.items():
        if winning_move == move:
            continue
        if any((mask & move_bit) == 0 for mask in masks):
            remaining.append(winning_move)
    return tuple(remaining)


def _remaining_wins_after_move_count(
    move: int,
    winning_masks_by_move: dict[int, tuple[int, ...]],
) -> int:
    move_bit = bit(move)
    remaining = 0
    for winning_move, masks in winning_masks_by_move.items():
        if winning_move == move:
            continue
        if any((mask & move_bit) == 0 for mask in masks):
            remaining += 1
    return remaining


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
    needs_ordering_maps = detail is TacticalDetail.ORDERING
    if inc_state is not None:
        summary = inc_state.tactical_summary(
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
        )

    occupied_bits = position.occupied_bits
    current_bits = position.current_bits()
    opponent_bits = position.opponent_bits()
    ordered_candidates = _ordered_candidate_moves(position, tables, candidate_moves)
    candidate_bits = _moves_to_bits(ordered_candidates)
    opponent_winning_masks = _winning_move_masks(opponent_bits, current_bits, candidate_bits, tables)
    opponent_winning_moves = tuple(move for move in ordered_candidates if move in opponent_winning_masks)

    safe_moves: list[int] = []
    poison_moves: list[int] = []
    forced_blocks: list[int] = []
    safe_threats: list[int] = []
    double_threats: list[int] = []
    future_wins_by_move: dict[int, tuple[int, ...]] = {}
    opponent_wins_after_move: dict[int, tuple[int, ...]] = {}
    winning_masks = _winning_move_masks(current_bits, opponent_bits, candidate_bits, tables)
    winning_move_set = set(winning_masks)
    winning_moves = tuple(move for move in ordered_candidates if move in winning_masks)

    for move in ordered_candidates:
        if move in winning_move_set:
            continue

        move_type = classify_move_bits(current_bits, occupied_bits, move, tables)
        if move_type is MoveType.POISON:
            poison_moves.append(move)
            continue

        safe_moves.append(move)
        if needs_ordering_maps:
            opponent_wins_after = _remaining_wins_after_move(move, opponent_winning_masks)
            opponent_wins_after_move[move] = opponent_wins_after
            future_wins = _future_wins_from_move(current_bits, opponent_bits, occupied_bits, move, tables)
            future_wins_by_move[move] = future_wins
            opponent_remaining = len(opponent_wins_after)
            future_win_count = len(future_wins)
        else:
            opponent_remaining = _remaining_wins_after_move_count(move, opponent_winning_masks)
            future_win_count = _future_win_count_from_move(current_bits, opponent_bits, occupied_bits, move, tables)

        if opponent_winning_moves and opponent_remaining == 0:
            forced_blocks.append(move)
        if opponent_remaining == 0 and future_win_count > 0:
            safe_threats.append(move)
            if future_win_count >= 2:
                double_threats.append(move)

    return TacticalSnapshot(
        candidate_moves=ordered_candidates,
        safe_moves=tuple(safe_moves),
        winning_moves=tuple(winning_moves),
        poison_moves=tuple(poison_moves),
        forced_blocks=tuple(forced_blocks),
        safe_threats=tuple(safe_threats),
        double_threats=tuple(double_threats),
        opponent_winning_moves=opponent_winning_moves,
        future_wins_by_move=future_wins_by_move,
        opponent_wins_after_move=opponent_wins_after_move,
    )
