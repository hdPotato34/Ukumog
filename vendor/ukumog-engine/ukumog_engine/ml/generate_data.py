from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..board import BOARD_SIZE
from ..incremental import IncrementalState
from ..position import MoveResult, Position, play_move
from ..search import MATE_SCORE, SearchEngine
from .data import append_quiet_value_examples, save_quiet_value_examples, score_to_value_target
from .mask_features import encode_mask_states
from .symmetry import canonical_position_hash, canonical_position_key, canonicalize_position


@dataclass(frozen=True, slots=True)
class QuietCandidate:
    position: Position
    ply: int
    canonical_key: tuple[int, int, int]
    canonical_hash: int
    effective_label_depth: int
    effective_label_time_ms: int | None
    priority: tuple[float, int, int, float]


def _position_key(position: Position) -> tuple[int, int, int]:
    side_flag = 0 if position.side_to_move.name == "BLACK" else 1
    return position.black_bits, position.white_bits, side_flag


def _dedup_key(position: Position, dedup: str) -> tuple[int, int, int] | None:
    if dedup == "none":
        return None
    if dedup == "exact":
        return _position_key(position)
    return canonical_position_key(position)


def _effective_search_budget(
    ply: int,
    base_depth: int,
    base_time_ms: int | None,
    opening_plies: int,
    opening_depth: int | None,
    opening_time_ms: int | None,
) -> tuple[int, int | None]:
    if opening_plies <= 0 or ply >= opening_plies:
        return base_depth, base_time_ms

    depth = base_depth if opening_depth is None else opening_depth
    time_ms = base_time_ms if opening_time_ms is None else opening_time_ms
    return depth, time_ms


def _load_incremental_state(output_path: Path) -> tuple[set[int], int, int]:
    if not output_path.exists():
        return set(), 0, 0

    with np.load(output_path) as data:
        if "four_states" not in data.files:
            raise ValueError("append mode requires a quiet_value_v1 dataset")
        existing_hashes: set[int] = set()
        if "canonical_hashes" in data.files:
            existing_hashes = {int(value) for value in np.asarray(data["canonical_hashes"]).tolist()}
        next_game_id = 0
        if "game_ids" in data.files and np.asarray(data["game_ids"]).size:
            next_game_id = int(np.asarray(data["game_ids"]).max()) + 1
        existing_samples = int(np.asarray(data["four_states"]).shape[0])
    return existing_hashes, next_game_id, existing_samples


def _move_in_center_window(move: int, center_size: int) -> bool:
    if center_size <= 0 or center_size > BOARD_SIZE:
        return False
    row, col = divmod(move, BOARD_SIZE)
    start = (BOARD_SIZE - center_size) // 2
    end = start + center_size
    return start <= row < end and start <= col < end


def _sample_weighted_prefix(moves: list[int], top_k: int, rng: random.Random) -> int | None:
    if not moves:
        return None
    top_count = min(len(moves), max(1, top_k))
    top_moves = moves[:top_count]
    weights = [top_count - index for index in range(top_count)]
    return rng.choices(top_moves, weights=weights, k=1)[0]


def _adaptive_exploration_settings(
    base_explore_plies: int,
    base_explore_top_k: int,
    consecutive_zero_sample_games: int,
    adaptive_stall_games: int,
    adaptive_explore_step: int,
    adaptive_explore_plies_step: int,
    adaptive_max_top_k: int,
    adaptive_max_explore_plies: int,
) -> tuple[int, int]:
    if adaptive_stall_games <= 0 or consecutive_zero_sample_games < adaptive_stall_games:
        return base_explore_plies, base_explore_top_k

    level = 1 + ((consecutive_zero_sample_games - adaptive_stall_games) // adaptive_stall_games)
    explore_top_k = min(adaptive_max_top_k, base_explore_top_k + (level * adaptive_explore_step))
    explore_plies = min(adaptive_max_explore_plies, base_explore_plies + (level * adaptive_explore_plies_step))
    return explore_plies, explore_top_k


def _choose_selfplay_move(
    position: Position,
    engine: SearchEngine,
    rng: random.Random,
    ply: int,
    play_depth: int,
    play_time_ms: int | None,
    explore_plies: int,
    explore_top_k: int,
    opening_plies: int,
    opening_play_depth: int | None,
    opening_play_time_ms: int | None,
    diversify_opening_plies: int,
    diversify_opening_top_k: int,
    diversify_center_size: int,
) -> int | None:
    effective_depth, effective_time_ms = _effective_search_budget(
        ply,
        play_depth,
        play_time_ms,
        opening_plies,
        opening_play_depth,
        opening_play_time_ms,
    )
    incremental_state = engine._search_incremental_state(position)
    snapshot = engine._tactics(position, incremental_state)
    ordered = engine._ordered_search_moves(position, incremental_state, snapshot, effective_depth, 0, None, True)

    if ply < diversify_opening_plies and ordered:
        preferred_moves = [move for move in ordered if move in snapshot.safe_moves and _move_in_center_window(move, diversify_center_size)]
        if not preferred_moves:
            preferred_moves = [move for move in ordered if _move_in_center_window(move, diversify_center_size)]
        if not preferred_moves:
            preferred_moves = list(ordered)
        diversified = _sample_weighted_prefix(preferred_moves, diversify_opening_top_k, rng)
        if diversified is not None:
            return diversified

    if ply < explore_plies and ordered:
        explored = _sample_weighted_prefix(list(ordered), explore_top_k, rng)
        if explored is not None:
            return explored

    result = engine.search(position, max_depth=effective_depth, max_time_ms=effective_time_ms)
    return result.best_move


def _is_quiet_training_position(snapshot, opponent_snapshot) -> bool:
    return not (
        snapshot.winning_moves
        or snapshot.forced_blocks
        or snapshot.safe_threats
        or snapshot.double_threats
        or snapshot.opponent_winning_moves
        or opponent_snapshot.safe_threats
        or opponent_snapshot.double_threats
    )


def _candidate_priority(
    position: Position,
    incremental_state: IncrementalState,
    snapshot,
    ply: int,
    rng: random.Random,
) -> tuple[float, int, int, float]:
    balance_score = -abs(incremental_state.absolute_lookup_score())
    safe_move_count = len(snapshot.safe_moves)
    centrality = 0
    for move in snapshot.safe_moves[: min(8, len(snapshot.safe_moves))]:
        if _move_in_center_window(move, 5):
            centrality += 1
    return (float(balance_score), safe_move_count, ply + centrality, rng.random())


def _select_candidates_for_game(
    sampled_positions: list[tuple[Position, int]],
    *,
    dedup: str,
    append_output: bool,
    existing_hashes: set[int],
    seen_positions: set[tuple[int, int, int]],
    samples_per_game: int,
    label_depth: int,
    label_time_ms: int | None,
    opening_plies: int,
    opening_label_depth: int | None,
    opening_label_time_ms: int | None,
    rng: random.Random,
    label_engine: SearchEngine,
) -> tuple[list[QuietCandidate], int, int]:
    skipped_duplicates = 0
    skipped_tactical = 0
    selected: dict[int, QuietCandidate] = {}

    for sampled, sampled_ply in sampled_positions:
        dedup_key = _dedup_key(sampled, dedup)
        if dedup_key is not None and dedup_key in seen_positions:
            skipped_duplicates += 1
            continue
        if dedup_key is not None:
            seen_positions.add(dedup_key)

        canonical_key = canonical_position_key(sampled)
        canonical_hash = int(canonical_position_hash(sampled))
        if append_output and canonical_hash in existing_hashes:
            skipped_duplicates += 1
            continue

        incremental_state = IncrementalState.from_position(sampled)
        snapshot = label_engine._tactics(sampled, incremental_state)
        opponent_snapshot = label_engine._tactics(
            sampled.with_side_to_move(sampled.side_to_move.opponent),
            incremental_state,
        )
        if not _is_quiet_training_position(snapshot, opponent_snapshot):
            skipped_tactical += 1
            continue

        effective_label_depth, effective_label_time_ms = _effective_search_budget(
            sampled_ply,
            label_depth,
            label_time_ms,
            opening_plies,
            opening_label_depth,
            opening_label_time_ms,
        )
        candidate = QuietCandidate(
            position=sampled,
            ply=sampled_ply,
            canonical_key=canonical_key,
            canonical_hash=canonical_hash,
            effective_label_depth=effective_label_depth,
            effective_label_time_ms=effective_label_time_ms,
            priority=_candidate_priority(sampled, incremental_state, snapshot, sampled_ply, rng),
        )
        current = selected.get(canonical_hash)
        if current is None or candidate.priority > current.priority:
            selected[canonical_hash] = candidate

    ranked = sorted(selected.values(), key=lambda candidate: candidate.priority, reverse=True)
    return ranked[: max(1, samples_per_game)], skipped_duplicates, skipped_tactical


def collect_selfplay_examples(
    games: int,
    seed: int,
    play_depth: int,
    label_depth: int,
    output_path: str | Path,
    play_time_ms: int | None = None,
    label_time_ms: int | None = None,
    sample_every: int = 1,
    max_positions: int | None = None,
    target_new_samples: int | None = None,
    explore_plies: int = 8,
    explore_top_k: int = 4,
    dedup: str = "symmetry",
    opening_plies: int = 0,
    opening_play_depth: int | None = None,
    opening_label_depth: int | None = None,
    opening_play_time_ms: int | None = None,
    opening_label_time_ms: int | None = None,
    sample_start_ply: int = 2,
    append_output: bool = True,
    samples_per_game: int = 4,
    diversify_opening_plies: int = 6,
    diversify_opening_top_k: int = 8,
    diversify_center_size: int = 5,
    adaptive_stall_games: int = 6,
    adaptive_explore_step: int = 2,
    adaptive_explore_plies_step: int = 4,
    adaptive_max_top_k: int = 16,
    adaptive_max_explore_plies: int = 32,
) -> int:
    rng = random.Random(seed)
    play_engine = SearchEngine()
    label_engine = SearchEngine()
    resolved_output_path = Path(output_path)

    four_states: list[np.ndarray] = []
    five_states: list[np.ndarray] = []
    value_targets: list[float] = []
    raw_scores: list[int] = []
    search_depths: list[int] = []
    game_ids: list[int] = []
    plies: list[int] = []
    canonical_hashes: list[np.uint64] = []
    seen_positions: set[tuple[int, int, int]] = set()
    label_cache: dict[tuple[tuple[int, int, int], int, int | None], tuple[int, int]] = {}
    skipped_duplicates = 0
    skipped_tactical = 0
    skipped_mates = 0
    label_cache_hits = 0
    existing_hashes: set[int] = set()
    game_id_offset = 0
    existing_samples = 0
    consecutive_zero_sample_games = 0
    quiet_candidates_seen = 0

    if append_output:
        existing_hashes, game_id_offset, existing_samples = _load_incremental_state(resolved_output_path)
        if existing_samples:
            print(
                f"append mode: existing_samples={existing_samples} "
                f"existing_hashes={len(existing_hashes)} next_game_id={game_id_offset}"
            )

    effective_target = target_new_samples
    if max_positions is not None:
        effective_target = max_positions if effective_target is None else min(max_positions, effective_target)

    for game_index in range(games):
        position = Position.initial()
        sampled_positions: list[tuple[Position, int]] = []
        ply = 0
        dynamic_explore_plies, dynamic_explore_top_k = _adaptive_exploration_settings(
            explore_plies,
            explore_top_k,
            consecutive_zero_sample_games,
            adaptive_stall_games,
            adaptive_explore_step,
            adaptive_explore_plies_step,
            adaptive_max_top_k,
            adaptive_max_explore_plies,
        )

        while True:
            if ply >= sample_start_ply and ply % sample_every == 0:
                sampled_positions.append((position, ply))

            move = _choose_selfplay_move(
                position,
                play_engine,
                rng,
                ply,
                play_depth,
                play_time_ms,
                dynamic_explore_plies,
                dynamic_explore_top_k,
                opening_plies,
                opening_play_depth,
                opening_play_time_ms,
                diversify_opening_plies,
                diversify_opening_top_k,
                diversify_center_size,
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

        game_candidates, game_skipped_duplicates, game_skipped_tactical = _select_candidates_for_game(
            sampled_positions,
            dedup=dedup,
            append_output=append_output,
            existing_hashes=existing_hashes,
            seen_positions=seen_positions,
            samples_per_game=samples_per_game,
            label_depth=label_depth,
            label_time_ms=label_time_ms,
            opening_plies=opening_plies,
            opening_label_depth=opening_label_depth,
            opening_label_time_ms=opening_label_time_ms,
            rng=rng,
            label_engine=label_engine,
        )
        quiet_candidates_seen += len(game_candidates)
        skipped_duplicates += game_skipped_duplicates
        skipped_tactical += game_skipped_tactical

        game_new_samples = 0
        for candidate in game_candidates:
            canonical_position, _ = canonicalize_position(candidate.position)
            label_cache_key = (
                candidate.canonical_key,
                candidate.effective_label_depth,
                candidate.effective_label_time_ms,
            )
            cached_label = label_cache.get(label_cache_key)
            if cached_label is None:
                label = label_engine.search(
                    canonical_position,
                    max_depth=candidate.effective_label_depth,
                    max_time_ms=candidate.effective_label_time_ms,
                )
                cached_label = (label.score, label.depth)
                label_cache[label_cache_key] = cached_label
            else:
                label_cache_hits += 1

            cached_score, cached_depth = cached_label
            if abs(cached_score) >= MATE_SCORE - 1_000:
                skipped_mates += 1
                continue

            incremental_state = IncrementalState.from_position(candidate.position)
            encoded_four_states, encoded_five_states = encode_mask_states(candidate.position, incremental_state)
            four_states.append(encoded_four_states)
            five_states.append(encoded_five_states)
            value_targets.append(score_to_value_target(cached_score))
            raw_scores.append(cached_score)
            search_depths.append(cached_depth)
            game_ids.append(game_id_offset + game_index)
            plies.append(candidate.ply)
            canonical_hashes.append(np.uint64(candidate.canonical_hash))
            existing_hashes.add(candidate.canonical_hash)
            game_new_samples += 1

            if effective_target is not None and len(four_states) >= effective_target:
                break

        if game_new_samples == 0:
            consecutive_zero_sample_games += 1
        else:
            consecutive_zero_sample_games = 0

        print(
            f"game {game_index + 1}/{games}: samples={len(four_states)} game_new={game_new_samples} "
            f"candidates={len(game_candidates)} quiet_seen={quiet_candidates_seen} "
            f"skipped={skipped_duplicates} tactical_skips={skipped_tactical} mate_skips={skipped_mates} "
            f"cache_hits={label_cache_hits} explore_plies={dynamic_explore_plies} explore_top_k={dynamic_explore_top_k} "
            f"stall_games={consecutive_zero_sample_games}"
        )
        if effective_target is not None and len(four_states) >= effective_target:
            break

    if not four_states:
        if append_output and resolved_output_path.exists():
            return 0
        raise RuntimeError("no quiet training samples were generated")

    save_fn = append_quiet_value_examples if append_output else save_quiet_value_examples
    save_fn(
        resolved_output_path,
        np.stack(four_states),
        np.stack(five_states),
        np.array(value_targets, dtype=np.float32),
        np.array(raw_scores, dtype=np.int32),
        np.array(search_depths, dtype=np.int16),
        extra_arrays={
            "game_ids": np.array(game_ids, dtype=np.int32),
            "plies": np.array(plies, dtype=np.int16),
            "canonical_hashes": np.array(canonical_hashes, dtype=np.uint64),
        },
    )
    return len(four_states)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate quiet self-play search labels for Ukumog.")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260419)
    parser.add_argument("--play-depth", type=int, default=3)
    parser.add_argument("--label-depth", type=int, default=6)
    parser.add_argument("--play-time-ms", type=int, default=500)
    parser.add_argument("--label-time-ms", type=int, default=3_000)
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument(
        "--sample-start-ply",
        type=int,
        default=2,
        help="Skip recording samples before this ply. Default: 2.",
    )
    parser.add_argument("--max-positions", type=int, default=None)
    parser.add_argument(
        "--target-new-samples",
        type=int,
        default=None,
        help="Stop once this many new samples have been appended in the current run.",
    )
    parser.add_argument("--explore-plies", type=int, default=8)
    parser.add_argument("--explore-top-k", type=int, default=4)
    parser.add_argument(
        "--samples-per-game",
        type=int,
        default=4,
        help="Keep at most this many deduplicated quiet candidates per game for labeling. Default: 4.",
    )
    parser.add_argument(
        "--opening-plies",
        type=int,
        default=0,
        help="For the first N plies, allow cheaper opening-specific play/label budgets. Default: 0.",
    )
    parser.add_argument(
        "--opening-play-depth",
        type=int,
        default=None,
        help="Optional shallower play depth for plies before --opening-plies.",
    )
    parser.add_argument(
        "--opening-label-depth",
        type=int,
        default=None,
        help="Optional shallower label depth for sampled plies before --opening-plies.",
    )
    parser.add_argument(
        "--opening-play-time-ms",
        type=int,
        default=None,
        help="Optional play time budget for plies before --opening-plies.",
    )
    parser.add_argument(
        "--opening-label-time-ms",
        type=int,
        default=None,
        help="Optional label time budget for sampled plies before --opening-plies.",
    )
    parser.add_argument(
        "--diversify-opening-plies",
        type=int,
        default=6,
        help="Randomize among safe opening choices for the first N plies. Default: 6.",
    )
    parser.add_argument(
        "--diversify-opening-top-k",
        type=int,
        default=8,
        help="Sample among the top K diversified opening moves. Default: 8.",
    )
    parser.add_argument(
        "--diversify-center-size",
        type=int,
        default=5,
        help="Prefer moves in the centered NxN opening window. Default: 5.",
    )
    parser.add_argument(
        "--adaptive-stall-games",
        type=int,
        default=6,
        help="After this many zero-sample games in a row, increase exploration. Default: 6.",
    )
    parser.add_argument(
        "--adaptive-explore-step",
        type=int,
        default=2,
        help="How much to increase explore_top_k per stall tier. Default: 2.",
    )
    parser.add_argument(
        "--adaptive-explore-plies-step",
        type=int,
        default=4,
        help="How much to increase explore_plies per stall tier. Default: 4.",
    )
    parser.add_argument(
        "--adaptive-max-top-k",
        type=int,
        default=16,
        help="Maximum adaptive explore_top_k. Default: 16.",
    )
    parser.add_argument(
        "--adaptive-max-explore-plies",
        type=int,
        default=32,
        help="Maximum adaptive explore_plies. Default: 32.",
    )
    parser.add_argument(
        "--dedup",
        choices=("none", "exact", "symmetry"),
        default="symmetry",
        help="Drop repeated sampled positions before labeling. Default: symmetry.",
    )
    parser.set_defaults(append_output=True)
    parser.add_argument(
        "--append-output",
        dest="append_output",
        action="store_true",
        help="Append new samples to an existing quiet-value dataset. Default: enabled.",
    )
    parser.add_argument(
        "--replace-output",
        dest="append_output",
        action="store_false",
        help="Replace the output dataset instead of appending.",
    )
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
        sample_start_ply=args.sample_start_ply,
        max_positions=args.max_positions,
        target_new_samples=args.target_new_samples,
        explore_plies=args.explore_plies,
        explore_top_k=args.explore_top_k,
        dedup=args.dedup,
        opening_plies=args.opening_plies,
        opening_play_depth=args.opening_play_depth,
        opening_label_depth=args.opening_label_depth,
        opening_play_time_ms=args.opening_play_time_ms,
        opening_label_time_ms=args.opening_label_time_ms,
        append_output=args.append_output,
        samples_per_game=args.samples_per_game,
        diversify_opening_plies=args.diversify_opening_plies,
        diversify_opening_top_k=args.diversify_opening_top_k,
        diversify_center_size=args.diversify_center_size,
        adaptive_stall_games=args.adaptive_stall_games,
        adaptive_explore_step=args.adaptive_explore_step,
        adaptive_explore_plies_step=args.adaptive_explore_plies_step,
        adaptive_max_top_k=args.adaptive_max_top_k,
        adaptive_max_explore_plies=args.adaptive_max_explore_plies,
    )
    action = "appended" if args.append_output else "saved"
    print(f"{action} {total} quiet samples to {args.output}")


if __name__ == "__main__":
    main()
