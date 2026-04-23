from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .board import iter_set_bits
from .eval_lookup import DEFAULT_EVAL_LOOKUPS, EvalLookupTables
from .masks import DEFAULT_MASKS, MaskTables, PatternMask
from .position import Color, MoveResult, MoveType, Position
from .tactical_detail import TacticalDetail, resolve_tactical_detail


@dataclass(frozen=True, slots=True)
class UndoToken:
    move: int
    color: Color
    previous_side_to_move: Color


@dataclass(frozen=True, slots=True)
class IndexedMaskTables:
    four_bitmasks: tuple[int, ...]
    five_bitmasks: tuple[int, ...]
    incident4_indices: tuple[tuple[int, ...], ...]
    incident5_indices: tuple[tuple[int, ...], ...]
    four_state_updates: tuple[tuple[tuple[int, int], ...], ...]
    five_state_updates: tuple[tuple[tuple[int, int], ...], ...]


@dataclass(frozen=True, slots=True)
class IncrementalTacticalSummary:
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


RESTRICTED_LINE_PROGRESS_WEIGHTS = {1: 180, 2: 500, 3: 2_200}
RESTRICTED_LINE_UNBLOCKABLE_MULTIPLIER = 3
RESTRICTED_LINE_MIN_DELAY_NUMERATOR = 1


def _moves_to_bits(moves: set[int] | tuple[int, ...] | list[int]) -> int:
    bits = 0
    for move in moves:
        bits |= 1 << move
    return bits


def _restricted_line_weight(
    attacker_count: int,
    defender_safe_count: int,
    attacker_poisoned_empty_count: int,
    total_empty_count: int,
) -> int:
    base = RESTRICTED_LINE_PROGRESS_WEIGHTS.get(attacker_count, 0)
    if base == 0 or defender_safe_count > 1 or total_empty_count <= attacker_poisoned_empty_count:
        return 0
    if defender_safe_count == 0:
        base *= RESTRICTED_LINE_UNBLOCKABLE_MULTIPLIER
    if attacker_poisoned_empty_count:
        playable_empty_count = total_empty_count - attacker_poisoned_empty_count
        delay_numerator = max(RESTRICTED_LINE_MIN_DELAY_NUMERATOR, playable_empty_count)
        base = (base * delay_numerator) // total_empty_count
    return base


def _color_digit(color: Color) -> int:
    return 1 if color is Color.BLACK else 2


def _mask_indices_by_cell(
    patterns: tuple[PatternMask, ...],
    board_cells: int,
) -> tuple[tuple[int, ...], ...]:
    incident: list[list[int]] = [[] for _ in range(board_cells)]
    for pattern_index, pattern in enumerate(patterns):
        for cell in pattern.cells:
            incident[cell].append(pattern_index)
    return tuple(tuple(entries) for entries in incident)


def _state_updates_by_cell(
    patterns: tuple[PatternMask, ...],
    board_cells: int,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    updates: list[list[tuple[int, int]]] = [[] for _ in range(board_cells)]
    for pattern_index, pattern in enumerate(patterns):
        for local_index, cell in enumerate(pattern.cells):
            updates[cell].append((pattern_index, 3**local_index))
    return tuple(tuple(entries) for entries in updates)


@lru_cache(maxsize=None)
def _indexed_tables(tables: MaskTables) -> IndexedMaskTables:
    board_cells = tables.board_size * tables.board_size
    return IndexedMaskTables(
        four_bitmasks=tuple(pattern.bitmask for pattern in tables.masks4),
        five_bitmasks=tuple(pattern.bitmask for pattern in tables.masks5),
        incident4_indices=_mask_indices_by_cell(tables.masks4, board_cells),
        incident5_indices=_mask_indices_by_cell(tables.masks5, board_cells),
        four_state_updates=_state_updates_by_cell(tables.masks4, board_cells),
        five_state_updates=_state_updates_by_cell(tables.masks5, board_cells),
    )


def _initial_counts_and_states(
    patterns: tuple[PatternMask, ...],
    black_bits: int,
    white_bits: int,
) -> tuple[list[int], list[int], list[int]]:
    black_counts: list[int] = []
    white_counts: list[int] = []
    state_ids: list[int] = []

    for pattern in patterns:
        black_count = (black_bits & pattern.bitmask).bit_count()
        white_count = (white_bits & pattern.bitmask).bit_count()
        state_id = 0
        for local_index, cell in enumerate(pattern.cells):
            cell_bit = 1 << cell
            if black_bits & cell_bit:
                state_id += 3**local_index
            elif white_bits & cell_bit:
                state_id += 2 * (3**local_index)
        black_counts.append(black_count)
        white_counts.append(white_count)
        state_ids.append(state_id)

    return black_counts, white_counts, state_ids


class IncrementalState:
    def __init__(
        self,
        black_bits: int,
        white_bits: int,
        side_to_move: Color,
        tables: MaskTables = DEFAULT_MASKS,
        *,
        four_black_count: list[int] | None = None,
        four_white_count: list[int] | None = None,
        four_state_id: list[int] | None = None,
        five_black_count: list[int] | None = None,
        five_white_count: list[int] | None = None,
        five_state_id: list[int] | None = None,
        four_eval_sum: int | None = None,
        five_eval_sum: int | None = None,
        eval_lookups: EvalLookupTables = DEFAULT_EVAL_LOOKUPS,
    ) -> None:
        overlap = black_bits & white_bits
        if overlap:
            raise ValueError(f"overlapping stones detected: {overlap:b}")

        self.tables = tables
        self._indexed = _indexed_tables(tables)
        self.black_bits = black_bits
        self.white_bits = white_bits
        self.side_to_move = side_to_move
        self.eval_lookups = eval_lookups
        self.empty_count = tables.board_size * tables.board_size - self.occupied_bits.bit_count()

        if (
            four_black_count is None
            or four_white_count is None
            or four_state_id is None
            or five_black_count is None
            or five_white_count is None
            or five_state_id is None
        ):
            self.four_black_count, self.four_white_count, self.four_state_id = _initial_counts_and_states(
                tables.masks4,
                black_bits,
                white_bits,
            )
            self.five_black_count, self.five_white_count, self.five_state_id = _initial_counts_and_states(
                tables.masks5,
                black_bits,
                white_bits,
            )
        else:
            self.four_black_count = four_black_count
            self.four_white_count = four_white_count
            self.four_state_id = four_state_id
            self.five_black_count = five_black_count
            self.five_white_count = five_white_count
            self.five_state_id = five_state_id

        if four_eval_sum is None:
            self.four_eval_sum = sum(self.eval_lookups.four_table[state_id] for state_id in self.four_state_id)
        else:
            self.four_eval_sum = four_eval_sum
        if five_eval_sum is None:
            self.five_eval_sum = sum(self.eval_lookups.five_table[state_id] for state_id in self.five_state_id)
        else:
            self.five_eval_sum = five_eval_sum

    @classmethod
    def from_position(
        cls,
        position: Position,
        tables: MaskTables = DEFAULT_MASKS,
    ) -> "IncrementalState":
        return cls(
            black_bits=position.black_bits,
            white_bits=position.white_bits,
            side_to_move=position.side_to_move,
            tables=tables,
        )

    @property
    def occupied_bits(self) -> int:
        return self.black_bits | self.white_bits

    @property
    def empty_bits(self) -> int:
        return ((1 << (self.tables.board_size * self.tables.board_size)) - 1) & ~self.occupied_bits

    def copy(self) -> "IncrementalState":
        return IncrementalState(
            black_bits=self.black_bits,
            white_bits=self.white_bits,
            side_to_move=self.side_to_move,
            tables=self.tables,
            four_black_count=self.four_black_count.copy(),
            four_white_count=self.four_white_count.copy(),
            four_state_id=self.four_state_id.copy(),
            five_black_count=self.five_black_count.copy(),
            five_white_count=self.five_white_count.copy(),
            five_state_id=self.five_state_id.copy(),
            four_eval_sum=self.four_eval_sum,
            five_eval_sum=self.five_eval_sum,
            eval_lookups=self.eval_lookups,
        )

    def to_position(self) -> Position:
        return Position(
            black_bits=self.black_bits,
            white_bits=self.white_bits,
            side_to_move=self.side_to_move,
        )

    def absolute_lookup_score(self) -> int:
        return self.five_eval_sum + self.four_eval_sum

    def _validate_empty(self, move: int) -> None:
        if not 0 <= move < self.tables.board_size * self.tables.board_size:
            raise ValueError(f"illegal move on invalid cell: {move}")
        if self.occupied_bits & (1 << move):
            raise ValueError(f"illegal move on occupied cell: {move}")

    def _counts_for_color(self, color: Color, length: int) -> tuple[list[int], list[int], list[int]]:
        if length == 4:
            if color is Color.BLACK:
                return self.four_black_count, self.four_white_count, self.four_state_id
            return self.four_white_count, self.four_black_count, self.four_state_id
        if color is Color.BLACK:
            return self.five_black_count, self.five_white_count, self.five_state_id
        return self.five_white_count, self.five_black_count, self.five_state_id

    def _candidate_bits(
        self,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> int:
        if candidate_moves is not None:
            bits = 0
            for move in candidate_moves:
                bits |= 1 << move
            return bits

        occupied_bits = self.occupied_bits
        if not occupied_bits:
            center = self.tables.board_size // 2
            return 1 << (center * self.tables.board_size + center)

        relevant_bits = 0
        for cell in iter_set_bits(occupied_bits):
            relevant_bits |= self.tables.influence[cell]

        candidate_bits = relevant_bits & self.empty_bits
        if candidate_bits:
            return candidate_bits
        return self.empty_bits

    def ordered_candidate_moves(
        self,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[int, ...]:
        if candidate_moves is None:
            return iter_set_bits(self._candidate_bits())
        return tuple(sorted(candidate_moves))

    def relevant_empty_cells(self) -> set[int]:
        return set(self.ordered_candidate_moves())

    def classify_move(self, move: int, color: Color | None = None) -> MoveType:
        color = self.side_to_move if color is None else color
        self._validate_empty(move)
        player_counts5, opponent_counts5, _ = self._counts_for_color(color, 5)
        player_counts4, opponent_counts4, _ = self._counts_for_color(color, 4)
        return self._classify_move_from_counts(
            move,
            player_counts5,
            opponent_counts5,
            player_counts4,
            opponent_counts4,
        )

    def move_result(self, move: int, color: Color | None = None) -> MoveResult:
        move_type = self.classify_move(move, color)
        if move_type is MoveType.WINNING_NOW:
            return MoveResult.WIN
        if move_type is MoveType.POISON:
            return MoveResult.LOSS
        return MoveResult.NONTERMINAL

    def is_win_now(self, move: int, color: Color | None = None) -> bool:
        return self.classify_move(move, color) is MoveType.WINNING_NOW

    def is_poison(self, move: int, color: Color | None = None) -> bool:
        return self.classify_move(move, color) is MoveType.POISON

    def winning_moves(
        self,
        color: Color | None = None,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[int, ...]:
        return tuple(
            sorted(
                self._winning_move_masks_by_move(
                    self.side_to_move if color is None else color,
                    candidate_moves,
                )
            )
        )

    def poison_moves(
        self,
        color: Color | None = None,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[int, ...]:
        color = self.side_to_move if color is None else color
        player_counts, opponent_counts, _ = self._counts_for_color(color, 4)
        ordered_candidates = self.ordered_candidate_moves(candidate_moves)
        candidate_bits = self._candidate_bits(ordered_candidates)
        winning_moves = set(self.winning_moves(color, candidate_moves))
        poison_moves = self._poison_move_set_from_counts(
            player_counts,
            opponent_counts,
            candidate_bits,
            winning_moves,
        )
        return tuple(move for move in ordered_candidates if move in poison_moves)

    def has_immediate_win(self, color: Color | None = None) -> bool:
        return bool(self.winning_moves(color))

    def _winning_move_masks_by_move(
        self,
        color: Color,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> dict[int, tuple[int, ...]]:
        ordered_candidates = self.ordered_candidate_moves(candidate_moves)
        candidate_bits = self._candidate_bits(ordered_candidates)
        return self._winning_move_masks_by_ordered_candidates(color, ordered_candidates, candidate_bits)

    def _winning_move_masks_by_ordered_candidates(
        self,
        color: Color,
        ordered_candidates: tuple[int, ...],
        candidate_bits: int,
    ) -> dict[int, tuple[int, ...]]:
        player_counts, opponent_counts, _ = self._counts_for_color(color, 5)
        occupied_bits = self.occupied_bits

        winning_masks: dict[int, list[int]] = {}
        for mask_index, mask_bits in enumerate(self._indexed.five_bitmasks):
            if opponent_counts[mask_index] != 0 or player_counts[mask_index] != 4:
                continue

            missing_bit = mask_bits & ~occupied_bits
            if not (missing_bit & candidate_bits):
                continue

            move = missing_bit.bit_length() - 1
            winning_masks.setdefault(move, []).append(mask_bits)

        return {move: tuple(masks) for move, masks in winning_masks.items()}

    def _paired_winning_move_data(
        self,
        candidate_bits: int,
    ) -> tuple[dict[int, tuple[int, ...]], dict[int, tuple[int, ...]], dict[int, int], dict[int, int], int, int]:
        occupied_bits = self.occupied_bits
        black_counts = self.five_black_count
        white_counts = self.five_white_count
        black_winning_masks: dict[int, list[int]] = {}
        white_winning_masks: dict[int, list[int]] = {}
        black_future_bits_by_move: dict[int, int] = {}
        white_future_bits_by_move: dict[int, int] = {}
        black_winning_bits = 0
        white_winning_bits = 0

        for mask_index, mask_bits in enumerate(self._indexed.five_bitmasks):
            black_count = black_counts[mask_index]
            white_count = white_counts[mask_index]

            if white_count == 0:
                if black_count == 4:
                    missing_bit = mask_bits & ~occupied_bits
                    black_winning_bits |= missing_bit
                    if missing_bit & candidate_bits:
                        move = missing_bit.bit_length() - 1
                        black_winning_masks.setdefault(move, []).append(mask_bits)
                elif black_count == 3:
                    future_empty_bits = mask_bits & ~occupied_bits
                    candidate_future_bits = future_empty_bits & candidate_bits
                    if candidate_future_bits:
                        first_bit = future_empty_bits & -future_empty_bits
                        second_bit = future_empty_bits ^ first_bit
                        if candidate_future_bits == future_empty_bits:
                            first_move = first_bit.bit_length() - 1
                            second_move = second_bit.bit_length() - 1
                            black_future_bits_by_move[first_move] = (
                                black_future_bits_by_move.get(first_move, 0) | second_bit
                            )
                            black_future_bits_by_move[second_move] = (
                                black_future_bits_by_move.get(second_move, 0) | first_bit
                            )
                        elif candidate_future_bits == first_bit:
                            first_move = first_bit.bit_length() - 1
                            black_future_bits_by_move[first_move] = (
                                black_future_bits_by_move.get(first_move, 0) | second_bit
                            )
                        else:
                            second_move = second_bit.bit_length() - 1
                            black_future_bits_by_move[second_move] = (
                                black_future_bits_by_move.get(second_move, 0) | first_bit
                            )

            if black_count == 0:
                if white_count == 4:
                    missing_bit = mask_bits & ~occupied_bits
                    white_winning_bits |= missing_bit
                    if missing_bit & candidate_bits:
                        move = missing_bit.bit_length() - 1
                        white_winning_masks.setdefault(move, []).append(mask_bits)
                elif white_count == 3:
                    future_empty_bits = mask_bits & ~occupied_bits
                    candidate_future_bits = future_empty_bits & candidate_bits
                    if candidate_future_bits:
                        first_bit = future_empty_bits & -future_empty_bits
                        second_bit = future_empty_bits ^ first_bit
                        if candidate_future_bits == future_empty_bits:
                            first_move = first_bit.bit_length() - 1
                            second_move = second_bit.bit_length() - 1
                            white_future_bits_by_move[first_move] = (
                                white_future_bits_by_move.get(first_move, 0) | second_bit
                            )
                            white_future_bits_by_move[second_move] = (
                                white_future_bits_by_move.get(second_move, 0) | first_bit
                            )
                        elif candidate_future_bits == first_bit:
                            first_move = first_bit.bit_length() - 1
                            white_future_bits_by_move[first_move] = (
                                white_future_bits_by_move.get(first_move, 0) | second_bit
                            )
                        else:
                            second_move = second_bit.bit_length() - 1
                            white_future_bits_by_move[second_move] = (
                                white_future_bits_by_move.get(second_move, 0) | first_bit
                            )

        return (
            {move: tuple(masks) for move, masks in black_winning_masks.items()},
            {move: tuple(masks) for move, masks in white_winning_masks.items()},
            black_future_bits_by_move,
            white_future_bits_by_move,
            black_winning_bits,
            white_winning_bits,
        )

    def future_winning_moves_from_move(
        self,
        move: int,
        color: Color | None = None,
    ) -> tuple[int, ...]:
        color = self.side_to_move if color is None else color
        self._validate_empty(move)
        player_counts, opponent_counts, _ = self._counts_for_color(color, 5)
        return iter_set_bits(self._future_winning_bits_from_move(move, player_counts, opponent_counts))

    def winning_moves_after_move(
        self,
        move: int,
        color: Color | None = None,
        *,
        target_color: Color | None = None,
    ) -> tuple[int, ...]:
        color = self.side_to_move if color is None else color
        self._validate_empty(move)
        resolved_target = color if target_color is None else target_color
        undo = self.make_move(move, color)
        try:
            return self.winning_moves(resolved_target)
        finally:
            self.unmake_move(undo)

    def _future_winning_bits_from_move(
        self,
        move: int,
        player_counts: list[int],
        opponent_counts: list[int],
    ) -> int:
        move_bit = 1 << move
        future_win_bits = 0
        occupied_bits = self.occupied_bits
        for mask_index in self._indexed.incident5_indices[move]:
            if opponent_counts[mask_index] != 0 or player_counts[mask_index] != 3:
                continue

            future_win_bits |= self._indexed.five_bitmasks[mask_index] & ~occupied_bits & ~move_bit
        return future_win_bits

    def _future_win_bits_by_move_from_counts(
        self,
        player_counts: list[int],
        opponent_counts: list[int],
        candidate_bits: int,
    ) -> dict[int, int]:
        future_bits_by_move: dict[int, int] = {}
        occupied_bits = self.occupied_bits
        for mask_index, mask_bits in enumerate(self._indexed.five_bitmasks):
            if opponent_counts[mask_index] != 0 or player_counts[mask_index] != 3:
                continue

            future_empty_bits = mask_bits & ~occupied_bits
            candidate_future_bits = future_empty_bits & candidate_bits
            if not candidate_future_bits:
                continue

            first_bit = future_empty_bits & -future_empty_bits
            second_bit = future_empty_bits ^ first_bit
            if candidate_future_bits == future_empty_bits:
                first_move = first_bit.bit_length() - 1
                future_bits_by_move[first_move] = future_bits_by_move.get(first_move, 0) | second_bit
                second_move = second_bit.bit_length() - 1
                future_bits_by_move[second_move] = future_bits_by_move.get(second_move, 0) | first_bit
            elif candidate_future_bits == first_bit:
                first_move = first_bit.bit_length() - 1
                future_bits_by_move[first_move] = future_bits_by_move.get(first_move, 0) | second_bit
            else:
                second_move = second_bit.bit_length() - 1
                future_bits_by_move[second_move] = future_bits_by_move.get(second_move, 0) | first_bit
        return future_bits_by_move

    def _opponent_winning_moves_and_future_bits_from_counts(
        self,
        player_counts: list[int],
        opponent_counts: list[int],
        ordered_candidates: tuple[int, ...],
        winning_candidate_bits: int,
        future_candidate_bits: int,
    ) -> tuple[tuple[int, ...], dict[int, int]]:
        occupied_bits = self.occupied_bits
        winning_move_bits = 0
        future_bits_by_move: dict[int, int] = {}

        for mask_index, mask_bits in enumerate(self._indexed.five_bitmasks):
            player_count = player_counts[mask_index]
            opponent_count = opponent_counts[mask_index]

            if player_count == 0 and opponent_count == 4:
                missing_bit = mask_bits & ~occupied_bits
                if missing_bit & winning_candidate_bits:
                    winning_move_bits |= missing_bit
            elif opponent_count == 0 and player_count == 3:
                future_empty_bits = mask_bits & ~occupied_bits
                candidate_future_bits = future_empty_bits & future_candidate_bits
                if not candidate_future_bits:
                    continue

                first_bit = future_empty_bits & -future_empty_bits
                second_bit = future_empty_bits ^ first_bit
                if candidate_future_bits == future_empty_bits:
                    first_move = first_bit.bit_length() - 1
                    future_bits_by_move[first_move] = future_bits_by_move.get(first_move, 0) | second_bit
                    second_move = second_bit.bit_length() - 1
                    future_bits_by_move[second_move] = future_bits_by_move.get(second_move, 0) | first_bit
                elif candidate_future_bits == first_bit:
                    first_move = first_bit.bit_length() - 1
                    future_bits_by_move[first_move] = future_bits_by_move.get(first_move, 0) | second_bit
                else:
                    second_move = second_bit.bit_length() - 1
                    future_bits_by_move[second_move] = future_bits_by_move.get(second_move, 0) | first_bit

        winning_moves = tuple(move for move in ordered_candidates if winning_move_bits & (1 << move))
        return winning_moves, future_bits_by_move

    def _opponent_wins_after_move_maps(
        self,
        moves: list[int] | tuple[int, ...],
        opponent_winning_moves: tuple[int, ...],
    ) -> tuple[dict[int, tuple[int, ...]], dict[int, int]]:
        total = len(opponent_winning_moves)
        if total == 0:
            empty_map = {move: () for move in moves}
            return empty_map, {move: 0 for move in moves}

        opponent_winning_set = set(opponent_winning_moves)
        if total == 1:
            only_move = opponent_winning_moves[0]
            after_map = {
                move: (() if move == only_move else opponent_winning_moves)
                for move in moves
            }
            count_map = {move: 0 if move == only_move else 1 for move in moves}
            return after_map, count_map

        blocked_templates = {
            winning_move: tuple(move for move in opponent_winning_moves if move != winning_move)
            for winning_move in opponent_winning_moves
        }
        after_map = {
            move: (
                blocked_templates[move]
                if move in opponent_winning_set
                else opponent_winning_moves
            )
            for move in moves
        }
        count_map = {
            move: total - 1 if move in opponent_winning_set else total
            for move in moves
        }
        return after_map, count_map

    def _opponent_wins_after_move_counts(
        self,
        moves: list[int] | tuple[int, ...],
        opponent_winning_moves: tuple[int, ...],
    ) -> dict[int, int]:
        total = len(opponent_winning_moves)
        if total == 0:
            return {move: 0 for move in moves}

        opponent_winning_set = set(opponent_winning_moves)
        if total == 1:
            only_move = opponent_winning_moves[0]
            return {move: 0 if move == only_move else 1 for move in moves}

        return {
            move: total - 1 if move in opponent_winning_set else total
            for move in moves
        }

    def _classify_move_from_counts(
        self,
        move: int,
        player_counts5: list[int],
        opponent_counts5: list[int],
        player_counts4: list[int],
        opponent_counts4: list[int],
    ) -> MoveType:
        for mask_index in self._indexed.incident5_indices[move]:
            if opponent_counts5[mask_index] == 0 and player_counts5[mask_index] == 4:
                return MoveType.WINNING_NOW

        for mask_index in self._indexed.incident4_indices[move]:
            if opponent_counts4[mask_index] == 0 and player_counts4[mask_index] == 3:
                return MoveType.POISON

        return MoveType.SAFE

    def _poison_move_set_from_counts(
        self,
        player_counts4: list[int],
        opponent_counts4: list[int],
        candidate_bits: int,
        winning_moves: set[int],
    ) -> set[int]:
        poison_moves: set[int] = set()
        occupied_bits = self.occupied_bits
        for mask_index, mask_bits in enumerate(self._indexed.four_bitmasks):
            if opponent_counts4[mask_index] != 0 or player_counts4[mask_index] != 3:
                continue

            missing_bit = mask_bits & ~occupied_bits
            if not (missing_bit & candidate_bits):
                continue

            move = missing_bit.bit_length() - 1
            if move not in winning_moves:
                poison_moves.add(move)
        return poison_moves

    def _paired_poison_move_data(
        self,
        candidate_bits: int,
        black_candidate_winning_bits: int,
        white_candidate_winning_bits: int,
        black_full_winning_bits: int,
        white_full_winning_bits: int,
    ) -> tuple[set[int], set[int], int, int]:
        black_poison_moves: set[int] = set()
        white_poison_moves: set[int] = set()
        black_full_poison_bits = 0
        white_full_poison_bits = 0
        occupied_bits = self.occupied_bits
        black_counts = self.four_black_count
        white_counts = self.four_white_count

        for mask_index, mask_bits in enumerate(self._indexed.four_bitmasks):
            black_count = black_counts[mask_index]
            white_count = white_counts[mask_index]

            if white_count == 0 and black_count == 3:
                missing_bit = mask_bits & ~occupied_bits
                if missing_bit & candidate_bits and not (missing_bit & black_candidate_winning_bits):
                    move = missing_bit.bit_length() - 1
                    black_poison_moves.add(move)
                if not (missing_bit & black_full_winning_bits):
                    black_full_poison_bits |= missing_bit

            if black_count == 0 and white_count == 3:
                missing_bit = mask_bits & ~occupied_bits
                if missing_bit & candidate_bits and not (missing_bit & white_candidate_winning_bits):
                    move = missing_bit.bit_length() - 1
                    white_poison_moves.add(move)
                if not (missing_bit & white_full_winning_bits):
                    white_full_poison_bits |= missing_bit

        return black_poison_moves, white_poison_moves, black_full_poison_bits, white_full_poison_bits

    def move_maps(
        self,
        moves: list[int] | tuple[int, ...],
        color: Color | None = None,
        *,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[dict[int, tuple[int, ...]], dict[int, tuple[int, ...]]]:
        color = self.side_to_move if color is None else color
        ordered_candidates = self.ordered_candidate_moves(candidate_moves)
        return self._move_maps_for_ordered_candidates(moves, color, ordered_candidates)

    def move_map_counts(
        self,
        moves: list[int] | tuple[int, ...],
        color: Color | None = None,
        *,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[dict[int, int], dict[int, int]]:
        color = self.side_to_move if color is None else color
        ordered_candidates = self.ordered_candidate_moves(candidate_moves)
        return self._move_map_counts_for_ordered_candidates(moves, color, ordered_candidates)

    def _move_maps_for_ordered_candidates(
        self,
        moves: list[int] | tuple[int, ...],
        color: Color,
        ordered_candidates: tuple[int, ...],
    ) -> tuple[dict[int, tuple[int, ...]], dict[int, tuple[int, ...]]]:
        candidate_bits = self._candidate_bits(ordered_candidates)
        moves_bits = self._candidate_bits(moves)
        player_counts, opponent_counts, _ = self._counts_for_color(color, 5)
        opponent_winning_moves, future_bits_by_move = self._opponent_winning_moves_and_future_bits_from_counts(
            player_counts,
            opponent_counts,
            ordered_candidates,
            candidate_bits,
            moves_bits,
        )
        opponent_wins_after_move, _ = self._opponent_wins_after_move_maps(moves, opponent_winning_moves)

        future_wins_by_move: dict[int, tuple[int, ...]] = {}
        for move in moves:
            future_wins_by_move[move] = iter_set_bits(future_bits_by_move.get(move, 0))

        return future_wins_by_move, opponent_wins_after_move

    def _move_map_counts_for_ordered_candidates(
        self,
        moves: list[int] | tuple[int, ...],
        color: Color,
        ordered_candidates: tuple[int, ...],
    ) -> tuple[dict[int, int], dict[int, int]]:
        candidate_bits = self._candidate_bits(ordered_candidates)
        moves_bits = self._candidate_bits(moves)
        player_counts, opponent_counts, _ = self._counts_for_color(color, 5)
        opponent_winning_moves, future_bits_by_move = self._opponent_winning_moves_and_future_bits_from_counts(
            player_counts,
            opponent_counts,
            ordered_candidates,
            candidate_bits,
            moves_bits,
        )
        future_win_counts = {
            move: future_bits_by_move.get(move, 0).bit_count()
            for move in moves
        }
        opponent_remaining_counts = self._opponent_wins_after_move_counts(moves, opponent_winning_moves)
        return future_win_counts, opponent_remaining_counts

    def tactical_summary(
        self,
        color: Color | None = None,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
        include_move_maps: bool = True,
        detail: TacticalDetail | None = None,
    ) -> IncrementalTacticalSummary:
        black_summary, white_summary = self.paired_tactical_summaries(
            candidate_moves,
            include_move_maps,
            detail=detail,
        )
        color = self.side_to_move if color is None else color
        return black_summary if color is Color.BLACK else white_summary

    def paired_tactical_summaries(
        self,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
        include_move_maps: bool = True,
        detail: TacticalDetail | None = None,
    ) -> tuple[IncrementalTacticalSummary, IncrementalTacticalSummary]:
        resolved_detail = resolve_tactical_detail(detail, include_move_maps=include_move_maps)
        needs_ordering_maps = resolved_detail is TacticalDetail.ORDERING
        ordered_candidates = self.ordered_candidate_moves(candidate_moves)
        candidate_bits = self._candidate_bits(ordered_candidates)
        all_empty_bits = self.empty_bits
        (
            black_winning_masks,
            white_winning_masks,
            black_future_bits_by_move,
            white_future_bits_by_move,
            black_full_winning_bits,
            white_full_winning_bits,
        ) = self._paired_winning_move_data(candidate_bits)
        black_winning_moves = tuple(move for move in ordered_candidates if move in black_winning_masks)
        white_winning_moves = tuple(move for move in ordered_candidates if move in white_winning_masks)
        black_winning_set = set(black_winning_moves)
        white_winning_set = set(white_winning_moves)
        black_candidate_winning_bits = _moves_to_bits(black_winning_moves)
        white_candidate_winning_bits = _moves_to_bits(white_winning_moves)
        black_opponent_winning_total = len(white_winning_moves)
        white_opponent_winning_total = len(black_winning_moves)
        black_poison_set, white_poison_set, black_poison_bits, white_poison_bits = self._paired_poison_move_data(
            candidate_bits,
            black_candidate_winning_bits,
            white_candidate_winning_bits,
            black_full_winning_bits,
            white_full_winning_bits,
        )
        black_has_opponent_wins = bool(white_winning_moves)
        white_has_opponent_wins = bool(black_winning_moves)
        if needs_ordering_maps:
            black_opponent_wins_after_templates, black_opponent_remaining_by_move = (
                self._opponent_wins_after_move_maps(ordered_candidates, white_winning_moves)
            )
            white_opponent_wins_after_templates, white_opponent_remaining_by_move = (
                self._opponent_wins_after_move_maps(ordered_candidates, black_winning_moves)
            )
        else:
            black_opponent_wins_after_templates = {}
            white_opponent_wins_after_templates = {}
            black_opponent_remaining_by_move = {}
            white_opponent_remaining_by_move = {}

        black_safe_moves: list[int] = []
        black_poison_moves: list[int] = []
        black_forced_blocks: list[int] = []
        black_safe_threats: list[int] = []
        black_double_threats: list[int] = []
        black_future_wins_by_move: dict[int, tuple[int, ...]] = {}
        black_opponent_wins_after_move: dict[int, tuple[int, ...]] = {}
        black_restricted_pressure = 0
        black_critical_restricted_lines = 0
        black_restricted_move_pressure: dict[int, int] = {}
        black_critical_build_bits = 0
        black_critical_response_bits = 0

        white_safe_moves: list[int] = []
        white_poison_moves: list[int] = []
        white_forced_blocks: list[int] = []
        white_safe_threats: list[int] = []
        white_double_threats: list[int] = []
        white_future_wins_by_move: dict[int, tuple[int, ...]] = {}
        white_opponent_wins_after_move: dict[int, tuple[int, ...]] = {}
        white_restricted_pressure = 0
        white_critical_restricted_lines = 0
        white_restricted_move_pressure: dict[int, int] = {}
        white_critical_build_bits = 0
        white_critical_response_bits = 0

        for move in ordered_candidates:
            if move not in black_winning_set:
                if move in black_poison_set:
                    black_poison_moves.append(move)
                else:
                    black_safe_moves.append(move)
                    black_future_bits = black_future_bits_by_move.get(move, 0)
                    if needs_ordering_maps:
                        black_future_wins = iter_set_bits(black_future_bits)
                        black_future_wins_by_move[move] = black_future_wins
                        black_future_count = black_future_bits.bit_count()
                        black_opponent_wins_after = black_opponent_wins_after_templates.get(move, ())
                        black_opponent_remaining = black_opponent_remaining_by_move.get(move, 0)
                        black_opponent_wins_after_move[move] = black_opponent_wins_after
                    else:
                        black_future_count = black_future_bits.bit_count()
                        if black_has_opponent_wins:
                            black_opponent_remaining = (
                                black_opponent_winning_total - 1
                                if move in white_winning_set
                                else black_opponent_winning_total
                            )
                        else:
                            black_opponent_remaining = 0

                    if black_has_opponent_wins and black_opponent_remaining == 0:
                        black_forced_blocks.append(move)
                    if black_opponent_remaining == 0 and black_future_count > 0:
                        black_safe_threats.append(move)
                        if black_future_count >= 2:
                            black_double_threats.append(move)

            if move not in white_winning_set:
                if move in white_poison_set:
                    white_poison_moves.append(move)
                else:
                    white_safe_moves.append(move)
                    white_future_bits = white_future_bits_by_move.get(move, 0)
                    if needs_ordering_maps:
                        white_future_wins = iter_set_bits(white_future_bits)
                        white_future_wins_by_move[move] = white_future_wins
                        white_future_count = white_future_bits.bit_count()
                        white_opponent_wins_after = white_opponent_wins_after_templates.get(move, ())
                        white_opponent_remaining = white_opponent_remaining_by_move.get(move, 0)
                        white_opponent_wins_after_move[move] = white_opponent_wins_after
                    else:
                        white_future_count = white_future_bits.bit_count()
                        if white_has_opponent_wins:
                            white_opponent_remaining = (
                                white_opponent_winning_total - 1
                                if move in black_winning_set
                                else white_opponent_winning_total
                            )
                        else:
                            white_opponent_remaining = 0

                    if white_has_opponent_wins and white_opponent_remaining == 0:
                        white_forced_blocks.append(move)
                    if white_opponent_remaining == 0 and white_future_count > 0:
                        white_safe_threats.append(move)
                        if white_future_count >= 2:
                            white_double_threats.append(move)

        if black_poison_bits or white_poison_bits:
            restricted_counts = RESTRICTED_LINE_PROGRESS_WEIGHTS
            for mask_index, mask_bits in enumerate(self._indexed.five_bitmasks):
                empty_bits = mask_bits & all_empty_bits
                if empty_bits == 0:
                    continue

                total_empty_count = empty_bits.bit_count()
                black_count = self.five_black_count[mask_index]
                white_count = self.five_white_count[mask_index]

                if white_count == 0 and black_count in restricted_counts:
                    relevant_poison_bits = empty_bits & (black_poison_bits | white_poison_bits)
                    if relevant_poison_bits:
                        attacker_poisoned_empty_bits = empty_bits & black_poison_bits
                        attacker_poisoned_empty_count = attacker_poisoned_empty_bits.bit_count()
                        if total_empty_count > attacker_poisoned_empty_count:
                            defender_playable_bits = empty_bits & ~white_poison_bits
                            defender_safe_count = defender_playable_bits.bit_count()
                            if defender_safe_count <= 1:
                                weight = _restricted_line_weight(
                                    black_count,
                                    defender_safe_count,
                                    attacker_poisoned_empty_count,
                                    total_empty_count,
                                )
                                if weight:
                                    build_bits = (empty_bits & candidate_bits) & ~attacker_poisoned_empty_bits
                                    response_bits = defender_playable_bits & candidate_bits
                                    if defender_safe_count == 1:
                                        critical_build_bits = build_bits & defender_playable_bits
                                    elif black_count >= 2:
                                        critical_build_bits = build_bits
                                    else:
                                        critical_build_bits = 0
                                    black_restricted_pressure += weight
                                    if critical_build_bits:
                                        black_critical_restricted_lines += 1
                                    for move in iter_set_bits(build_bits):
                                        black_restricted_move_pressure[move] = (
                                            black_restricted_move_pressure.get(move, 0) + weight
                                        )
                                    for move in iter_set_bits(response_bits):
                                        white_restricted_move_pressure[move] = (
                                            white_restricted_move_pressure.get(move, 0) + weight
                                        )
                                    black_critical_build_bits |= critical_build_bits
                                    if critical_build_bits:
                                        white_critical_response_bits |= response_bits

                if black_count == 0 and white_count in restricted_counts:
                    relevant_poison_bits = empty_bits & (white_poison_bits | black_poison_bits)
                    if relevant_poison_bits:
                        attacker_poisoned_empty_bits = empty_bits & white_poison_bits
                        attacker_poisoned_empty_count = attacker_poisoned_empty_bits.bit_count()
                        if total_empty_count > attacker_poisoned_empty_count:
                            defender_playable_bits = empty_bits & ~black_poison_bits
                            defender_safe_count = defender_playable_bits.bit_count()
                            if defender_safe_count <= 1:
                                weight = _restricted_line_weight(
                                    white_count,
                                    defender_safe_count,
                                    attacker_poisoned_empty_count,
                                    total_empty_count,
                                )
                                if weight:
                                    build_bits = (empty_bits & candidate_bits) & ~attacker_poisoned_empty_bits
                                    response_bits = defender_playable_bits & candidate_bits
                                    if defender_safe_count == 1:
                                        critical_build_bits = build_bits & defender_playable_bits
                                    elif white_count >= 2:
                                        critical_build_bits = build_bits
                                    else:
                                        critical_build_bits = 0
                                    white_restricted_pressure += weight
                                    if critical_build_bits:
                                        white_critical_restricted_lines += 1
                                    for move in iter_set_bits(build_bits):
                                        white_restricted_move_pressure[move] = (
                                            white_restricted_move_pressure.get(move, 0) + weight
                                        )
                                    for move in iter_set_bits(response_bits):
                                        black_restricted_move_pressure[move] = (
                                            black_restricted_move_pressure.get(move, 0) + weight
                                        )
                                    white_critical_build_bits |= critical_build_bits
                                    if critical_build_bits:
                                        black_critical_response_bits |= response_bits

        black_summary = IncrementalTacticalSummary(
            candidate_moves=ordered_candidates,
            safe_moves=tuple(black_safe_moves),
            winning_moves=black_winning_moves,
            poison_moves=tuple(black_poison_moves),
            forced_blocks=tuple(black_forced_blocks),
            safe_threats=tuple(black_safe_threats),
            double_threats=tuple(black_double_threats),
            opponent_winning_moves=white_winning_moves,
            future_wins_by_move=black_future_wins_by_move,
            opponent_wins_after_move=black_opponent_wins_after_move,
            restricted_pressure=black_restricted_pressure,
            opponent_restricted_pressure=white_restricted_pressure,
            critical_restricted_lines=black_critical_restricted_lines,
            opponent_critical_restricted_lines=white_critical_restricted_lines,
            restricted_move_pressure=black_restricted_move_pressure,
            critical_restricted_builds=tuple(
                move for move in ordered_candidates if black_critical_build_bits & (1 << move)
            ),
            critical_restricted_responses=tuple(
                move for move in ordered_candidates if black_critical_response_bits & (1 << move)
            ),
        )
        white_summary = IncrementalTacticalSummary(
            candidate_moves=ordered_candidates,
            safe_moves=tuple(white_safe_moves),
            winning_moves=white_winning_moves,
            poison_moves=tuple(white_poison_moves),
            forced_blocks=tuple(white_forced_blocks),
            safe_threats=tuple(white_safe_threats),
            double_threats=tuple(white_double_threats),
            opponent_winning_moves=black_winning_moves,
            future_wins_by_move=white_future_wins_by_move,
            opponent_wins_after_move=white_opponent_wins_after_move,
            restricted_pressure=white_restricted_pressure,
            opponent_restricted_pressure=black_restricted_pressure,
            critical_restricted_lines=white_critical_restricted_lines,
            opponent_critical_restricted_lines=black_critical_restricted_lines,
            restricted_move_pressure=white_restricted_move_pressure,
            critical_restricted_builds=tuple(
                move for move in ordered_candidates if white_critical_build_bits & (1 << move)
            ),
            critical_restricted_responses=tuple(
                move for move in ordered_candidates if white_critical_response_bits & (1 << move)
            ),
        )
        return black_summary, white_summary

    def forced_blocks(
        self,
        color: Color | None = None,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[int, ...]:
        return self.tactical_summary(color, candidate_moves).forced_blocks

    def safe_threats(
        self,
        color: Color | None = None,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[int, ...]:
        return self.tactical_summary(color, candidate_moves).safe_threats

    def double_threats(
        self,
        color: Color | None = None,
        candidate_moves: list[int] | tuple[int, ...] | set[int] | None = None,
    ) -> tuple[int, ...]:
        return self.tactical_summary(color, candidate_moves).double_threats

    def make_move(self, move: int, color: Color | None = None) -> UndoToken:
        color = self.side_to_move if color is None else color
        self._validate_empty(move)

        move_bit = 1 << move
        if color is Color.BLACK:
            self.black_bits |= move_bit
        else:
            self.white_bits |= move_bit
        self.empty_count -= 1

        digit = _color_digit(color)
        for mask_index, weight in self._indexed.four_state_updates[move]:
            previous_state = self.four_state_id[mask_index]
            next_state = previous_state + digit * weight
            if color is Color.BLACK:
                self.four_black_count[mask_index] += 1
            else:
                self.four_white_count[mask_index] += 1
            self.four_state_id[mask_index] = next_state
            self.four_eval_sum += self.eval_lookups.four_table[next_state] - self.eval_lookups.four_table[previous_state]

        for mask_index, weight in self._indexed.five_state_updates[move]:
            previous_state = self.five_state_id[mask_index]
            next_state = previous_state + digit * weight
            if color is Color.BLACK:
                self.five_black_count[mask_index] += 1
            else:
                self.five_white_count[mask_index] += 1
            self.five_state_id[mask_index] = next_state
            self.five_eval_sum += self.eval_lookups.five_table[next_state] - self.eval_lookups.five_table[previous_state]

        previous_side_to_move = self.side_to_move
        self.side_to_move = color.opponent
        return UndoToken(move=move, color=color, previous_side_to_move=previous_side_to_move)

    def unmake_move(self, undo: UndoToken) -> None:
        move_bit = 1 << undo.move
        if undo.color is Color.BLACK:
            if not (self.black_bits & move_bit):
                raise ValueError("cannot unmake black move that is not present")
            self.black_bits ^= move_bit
        else:
            if not (self.white_bits & move_bit):
                raise ValueError("cannot unmake white move that is not present")
            self.white_bits ^= move_bit
        self.empty_count += 1

        digit = _color_digit(undo.color)
        for mask_index, weight in self._indexed.four_state_updates[undo.move]:
            previous_state = self.four_state_id[mask_index]
            next_state = previous_state - digit * weight
            if undo.color is Color.BLACK:
                self.four_black_count[mask_index] -= 1
            else:
                self.four_white_count[mask_index] -= 1
            self.four_state_id[mask_index] = next_state
            self.four_eval_sum += self.eval_lookups.four_table[next_state] - self.eval_lookups.four_table[previous_state]

        for mask_index, weight in self._indexed.five_state_updates[undo.move]:
            previous_state = self.five_state_id[mask_index]
            next_state = previous_state - digit * weight
            if undo.color is Color.BLACK:
                self.five_black_count[mask_index] -= 1
            else:
                self.five_white_count[mask_index] -= 1
            self.five_state_id[mask_index] = next_state
            self.five_eval_sum += self.eval_lookups.five_table[next_state] - self.eval_lookups.five_table[previous_state]

        self.side_to_move = undo.previous_side_to_move
