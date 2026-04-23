from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

from .masks import DEFAULT_MASKS, MaskTables
from .position import MoveResult, Position, play_move
from .tactics import TacticalSnapshot, analyze_tactics


class TacticalOutcome(Enum):
    WIN = auto()
    LOSS = auto()
    UNKNOWN = auto()


@dataclass(slots=True)
class TacticalSolveStats:
    queries: int = 0
    cache_hits: int = 0
    wins_proven: int = 0
    losses_proven: int = 0
    unknown: int = 0


@dataclass(frozen=True, slots=True)
class TacticalSolveResult:
    outcome: TacticalOutcome
    line: tuple[int, ...] = field(default_factory=tuple)


class TacticalSolver:
    def __init__(
        self,
        tables: MaskTables = DEFAULT_MASKS,
        tactics_fn: Callable[[Position], TacticalSnapshot] | None = None,
        key_fn: Callable[[Position], tuple[int, int, int]] | None = None,
        limit_check: Callable[[], None] | None = None,
    ) -> None:
        self.tables = tables
        self.tactics_fn = tactics_fn if tactics_fn is not None else (lambda position: analyze_tactics(position, tables))
        self.key_fn = (
            key_fn
            if key_fn is not None
            else lambda position: (
                position.black_bits,
                position.white_bits,
                0 if position.side_to_move.name == "BLACK" else 1,
            )
        )
        self.limit_check = limit_check
        self.cache: dict[tuple[tuple[int, int, int], int], TacticalSolveResult] = {}
        self.stats = TacticalSolveStats()

    def reset(self) -> None:
        self.cache = {}
        self.stats = TacticalSolveStats()

    def solve(self, position: Position, max_plies: int) -> TacticalSolveResult:
        self.stats.queries += 1
        result = self._solve(position, max_plies)
        if result.outcome is TacticalOutcome.WIN:
            self.stats.wins_proven += 1
        elif result.outcome is TacticalOutcome.LOSS:
            self.stats.losses_proven += 1
        else:
            self.stats.unknown += 1
        return result

    def _solve(self, position: Position, remaining_plies: int) -> TacticalSolveResult:
        self._check_limits()
        key = (self.key_fn(position), remaining_plies)
        cached = self.cache.get(key)
        if cached is not None:
            self.stats.cache_hits += 1
            return cached

        snapshot = self.tactics_fn(position)

        if snapshot.winning_moves:
            result = TacticalSolveResult(TacticalOutcome.WIN, (snapshot.winning_moves[0],))
            self.cache[key] = result
            return result

        if snapshot.opponent_winning_moves and not snapshot.forced_blocks:
            result = TacticalSolveResult(TacticalOutcome.LOSS, ())
            self.cache[key] = result
            return result

        if not snapshot.safe_moves:
            result = TacticalSolveResult(TacticalOutcome.LOSS, ())
            self.cache[key] = result
            return result

        if snapshot.double_threats:
            result = TacticalSolveResult(TacticalOutcome.WIN, (snapshot.double_threats[0],))
            self.cache[key] = result
            return result

        if remaining_plies == 0:
            result = TacticalSolveResult(TacticalOutcome.UNKNOWN, ())
            self.cache[key] = result
            return result

        if snapshot.opponent_winning_moves:
            moves = snapshot.forced_blocks
            exhaustive = True
        elif snapshot.safe_threats:
            moves = snapshot.double_threats + tuple(
                move for move in snapshot.safe_threats if move not in snapshot.double_threats
            )
            exhaustive = False
        else:
            result = TacticalSolveResult(TacticalOutcome.UNKNOWN, ())
            self.cache[key] = result
            return result

        saw_unknown = False
        for move in moves:
            self._check_limits()
            next_position, result = play_move(position, move, self.tables)
            if result is MoveResult.WIN:
                solved = TacticalSolveResult(TacticalOutcome.WIN, (move,))
                self.cache[key] = solved
                return solved
            if result is MoveResult.LOSS:
                continue

            child = self._solve(next_position, remaining_plies - 1)
            if child.outcome is TacticalOutcome.LOSS:
                solved = TacticalSolveResult(TacticalOutcome.WIN, (move,) + child.line)
                self.cache[key] = solved
                return solved
            if child.outcome is TacticalOutcome.UNKNOWN:
                saw_unknown = True

        if exhaustive and not saw_unknown:
            solved = TacticalSolveResult(TacticalOutcome.LOSS, ())
        else:
            solved = TacticalSolveResult(TacticalOutcome.UNKNOWN, ())
        self.cache[key] = solved
        return solved

    def _check_limits(self) -> None:
        if self.limit_check is not None:
            self.limit_check()
