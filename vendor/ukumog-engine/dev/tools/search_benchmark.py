from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ukumog_engine import Color, MoveResult, Position, SearchEngine, play_move


TACTICAL_MIDGAME = Position.from_rows(
    [
        "...........",
        "...........",
        "....B......",
        ".....W.....",
        "...B.W.....",
        ".....B.....",
        "....W......",
        "...........",
        "...........",
        "...........",
        "...........",
    ]
)

IMMEDIATE_DOUBLE_THREAT = Position.from_rows(
    [
        "...........",
        ".....B.....",
        "...........",
        ".....B.....",
        "...........",
        ".B.B.....B.",
        "...........",
        "...........",
        "...........",
        ".....B.....",
        "...........",
    ]
)

RESTRICTED_THREAT_REPRO_ROWS = [
    "....B......",
    ".....B.....",
    "...........",
    "...B.......",
    "..B.W.W....",
    ".....B.....",
    "....WWB....",
    "...........",
    "....W......",
    "...........",
    "...........",
]

RESTRICTED_THREAT_BASE_ROWS = [
    "....B......",
    ".....B.....",
    "...........",
    "...B.......",
    "..B.W.W....",
    "...........",
    "....WWB....",
    "...........",
    "....W......",
    "...........",
    "...........",
]

QUIET_MIDGAME_HISTORY = [41, 19, 52, 86, 6, 10, 111, 73, 14, 51, 82, 8, 72, 32, 4, 16, 66, 64]


def _transform_rows(rows: list[str], transform: str) -> list[str]:
    if transform == "identity":
        return list(rows)
    if transform == "rot90":
        size = len(rows)
        return ["".join(rows[size - 1 - col][row] for col in range(size)) for row in range(size)]
    if transform == "rot180":
        return _transform_rows(_transform_rows(rows, "rot90"), "rot90")
    if transform == "rot270":
        return _transform_rows(_transform_rows(rows, "rot180"), "rot90")
    if transform == "flip_h":
        return [row[::-1] for row in rows]
    raise ValueError(f"unknown transform: {transform}")


def _swap_colors(rows: list[str]) -> list[str]:
    swapped: list[str] = []
    for row in rows:
        swapped.append(row.replace("B", "x").replace("W", "B").replace("x", "W"))
    return swapped


def restricted_threat_positions() -> dict[str, Position]:
    transforms = ("identity", "rot90", "rot180", "rot270", "flip_h")
    positions = {
        "restricted_threat_repro": Position.from_rows(RESTRICTED_THREAT_REPRO_ROWS, side_to_move=Color.WHITE),
        "restricted_threat_repro_black": Position.from_rows(
            _swap_colors(RESTRICTED_THREAT_REPRO_ROWS),
            side_to_move=Color.BLACK,
        ),
    }
    for transform in transforms:
        suffix = "" if transform == "identity" else f"_{transform}"
        positions[f"restricted_threat_midgame{suffix}"] = Position.from_rows(
            _transform_rows(RESTRICTED_THREAT_BASE_ROWS, transform),
            side_to_move=Color.WHITE,
        )
        positions[f"restricted_threat_midgame_black{suffix}"] = Position.from_rows(
            _transform_rows(_swap_colors(RESTRICTED_THREAT_BASE_ROWS), transform),
            side_to_move=Color.BLACK,
        )
    return positions


def _position_from_history(history: list[int], side_to_move: Color = Color.BLACK) -> Position:
    position = Position.initial()
    for move in history:
        position, result = play_move(position, move)
        if result is not MoveResult.NONTERMINAL:
            raise ValueError("benchmark history unexpectedly contains a terminal move")
    if position.side_to_move is not side_to_move:
        position = position.with_side_to_move(side_to_move)
    return position


def benchmark_positions() -> dict[str, Position]:
    positions = {
        "initial": Position.initial(),
        "tactical_midgame": TACTICAL_MIDGAME,
        "immediate_double_threat": IMMEDIATE_DOUBLE_THREAT,
        "quiet_midgame": _position_from_history(QUIET_MIDGAME_HISTORY),
    }
    positions.update(restricted_threat_positions())
    return positions


def run_benchmark(depth: int, time_ms: int | None, selected: list[str] | None = None) -> list[str]:
    positions = benchmark_positions()
    names = selected if selected else list(positions)
    lines: list[str] = []
    for name in names:
        position = positions[name]
        engine = SearchEngine()
        started_at = time.perf_counter()
        result = engine.search(position, max_depth=depth, max_time_ms=time_ms)
        elapsed = time.perf_counter() - started_at
        stats = result.stats
        lines.append(
            " ".join(
                [
                    f"name={name}",
                    f"depth={result.depth}",
                    f"elapsed_s={elapsed:.3f}",
                    f"total_nodes={stats.total_nodes}",
                    f"tactics_s={stats.tactics_time_seconds:.3f}",
                    f"quiescence_s={stats.quiescence_time_seconds:.3f}",
                    f"proof_s={stats.proof_solver_time_seconds:.3f}",
                    f"qtt_hits={stats.qtt_hits}",
                    f"qforced_single={stats.quiescence_single_forced_block_nodes}",
                    f"qsafe_only={stats.quiescence_safe_threat_only_nodes}",
                    f"qsafe_pruned={stats.quiescence_safe_threat_moves_pruned}",
                    f"qskip_frontier={stats.quiescence_skip_frontier_safe_threat_nodes}",
                    f"qskip_wide={stats.quiescence_skip_wide_safe_threat_nodes}",
                    f"futility_prunes={stats.futility_prunes}",
                    f"late_move_prunes={stats.late_move_prunes}",
                ]
            )
        )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed Ukumog search benchmark position set.")
    parser.add_argument("--depth", type=int, default=6, help="Search depth for each benchmark position.")
    parser.add_argument(
        "--time-ms",
        type=int,
        default=0,
        help="Optional per-position search time limit in milliseconds. Default: 0 (no limit).",
    )
    parser.add_argument(
        "--positions",
        nargs="*",
        choices=tuple(benchmark_positions().keys()),
        help="Optional subset of benchmark position names to run.",
    )
    args = parser.parse_args()

    time_ms = None if args.time_ms == 0 else args.time_ms
    for line in run_benchmark(args.depth, time_ms, args.positions):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
