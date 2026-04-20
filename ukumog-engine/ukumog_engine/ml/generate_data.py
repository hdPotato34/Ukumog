from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np

from ..board import BOARD_CELLS
from ..position import MoveResult, Position, play_move
from ..search import SearchEngine
from .data import save_examples, score_to_value_target
from .features import FEATURE_CHANNELS, encode_position


def _legal_mask(position: Position) -> np.ndarray:
    mask = np.zeros(BOARD_CELLS, dtype=np.bool_)
    for move in position.legal_moves():
        mask[move] = True
    return mask


def _choose_selfplay_move(
    position: Position,
    engine: SearchEngine,
    rng: random.Random,
    ply: int,
    play_depth: int,
    play_time_ms: int | None,
    explore_plies: int,
    explore_top_k: int,
) -> int | None:
    if ply < explore_plies:
        incremental_state = engine._search_incremental_state(position)
        snapshot = engine._tactics(position, incremental_state)
        ordered = engine._ordered_search_moves(position, incremental_state, snapshot, play_depth, 0, None, True)
        if ordered:
            top_count = min(len(ordered), max(1, explore_top_k))
            top_moves = ordered[:top_count]
            weights = [top_count - index for index in range(top_count)]
            return rng.choices(top_moves, weights=weights, k=1)[0]

    result = engine.search(position, max_depth=play_depth, max_time_ms=play_time_ms)
    return result.best_move


def collect_selfplay_examples(
    games: int,
    seed: int,
    play_depth: int,
    label_depth: int,
    output_path: str | Path,
    play_time_ms: int | None = None,
    label_time_ms: int | None = None,
    sample_every: int = 2,
    max_positions: int | None = None,
    explore_plies: int = 8,
    explore_top_k: int = 4,
) -> int:
    rng = random.Random(seed)
    play_engine = SearchEngine()
    label_engine = SearchEngine()

    features: list[np.ndarray] = []
    legal_masks: list[np.ndarray] = []
    policy_targets: list[int] = []
    value_targets: list[float] = []
    raw_scores: list[int] = []
    search_depths: list[int] = []

    for game_index in range(games):
        position = Position.initial()
        sampled_positions: list[Position] = []
        ply = 0

        while True:
            if ply % sample_every == 0:
                sampled_positions.append(position)

            move = _choose_selfplay_move(
                position,
                play_engine,
                rng,
                ply,
                play_depth,
                play_time_ms,
                explore_plies,
                explore_top_k,
            )
            if move is None:
                break

            next_position, result = play_move(position, move)
            if result is not MoveResult.NONTERMINAL:
                break

            position = next_position
            ply += 1
            if position.empty_count == 0:
                break

        for sampled in sampled_positions:
            label = label_engine.search(sampled, max_depth=label_depth, max_time_ms=label_time_ms)
            if label.best_move is None:
                continue

            snapshot = label_engine._tactics(sampled)
            opponent_snapshot = label_engine._tactics(
                sampled.with_side_to_move(sampled.side_to_move.opponent)
            )
            features.append(encode_position(sampled, snapshot=snapshot, opponent_snapshot=opponent_snapshot))
            legal_masks.append(_legal_mask(sampled))
            policy_targets.append(label.best_move)
            value_targets.append(score_to_value_target(label.score))
            raw_scores.append(label.score)
            search_depths.append(label.depth)

            if max_positions is not None and len(features) >= max_positions:
                break

        print(
            f"game {game_index + 1}/{games}: samples={len(features)} "
            f"play_depth={play_depth} label_depth={label_depth}"
        )
        if max_positions is not None and len(features) >= max_positions:
            break

    if not features:
        raise RuntimeError("no training samples were generated")

    save_examples(
        output_path,
        np.stack(features).reshape((-1, FEATURE_CHANNELS, 11, 11)),
        np.stack(legal_masks),
        np.array(policy_targets, dtype=np.int64),
        np.array(value_targets, dtype=np.float32),
        np.array(raw_scores, dtype=np.int32),
        np.array(search_depths, dtype=np.int16),
    )
    return len(features)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate self-play search labels for Ukumog.")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260419)
    parser.add_argument("--play-depth", type=int, default=2)
    parser.add_argument("--label-depth", type=int, default=4)
    parser.add_argument("--play-time-ms", type=int, default=500)
    parser.add_argument("--label-time-ms", type=int, default=3_000)
    parser.add_argument("--sample-every", type=int, default=2)
    parser.add_argument("--max-positions", type=int, default=None)
    parser.add_argument("--explore-plies", type=int, default=8)
    parser.add_argument("--explore-top-k", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    total = collect_selfplay_examples(
        games=args.games,
        seed=args.seed,
        play_depth=args.play_depth,
        label_depth=args.label_depth,
        output_path=args.output,
        play_time_ms=args.play_time_ms,
        label_time_ms=args.label_time_ms,
        sample_every=args.sample_every,
        max_positions=args.max_positions,
        explore_plies=args.explore_plies,
        explore_top_k=args.explore_top_k,
    )
    print(f"saved {total} samples to {args.output}")


if __name__ == "__main__":
    main()
