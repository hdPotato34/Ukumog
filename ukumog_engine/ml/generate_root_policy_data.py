from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import numpy as np

from ..board import BOARD_CELLS
from ..incremental import IncrementalState
from ..position import MoveResult, Position, play_move
from ..search import RootMoveScore, SearchEngine
from ..tactics import analyze_tactics
from .data import (
    DATASET_KIND_ROOT_POLICY_V1,
    append_root_policy_examples,
    load_dataset_kind,
    save_root_policy_examples,
)
from .features import encode_position
from .symmetry import canonical_position_hash


def _sample_root_move(
    root_move_scores: tuple[RootMoveScore, ...],
    temperature: float,
    sample_top_k: int,
    rng: random.Random,
) -> int | None:
    if not root_move_scores:
        return None
    if temperature <= 0.0 or len(root_move_scores) == 1:
        return root_move_scores[0].move

    shortlist = root_move_scores[: max(1, sample_top_k)]
    weights = [math.exp(-(index / temperature)) for index in range(len(shortlist))]
    return rng.choices([root_score.move for root_score in shortlist], weights=weights, k=1)[0]


def _candidate_legal_mask(root_move_scores: tuple[RootMoveScore, ...]) -> np.ndarray:
    mask = np.zeros((BOARD_CELLS,), dtype=np.bool_)
    for root_score in root_move_scores:
        mask[root_score.move] = True
    return mask


def _is_root_policy_candidate(position: Position, incremental_state: IncrementalState) -> tuple[bool, object, object]:
    snapshot = analyze_tactics(position, inc_state=incremental_state, include_move_maps=False)
    opponent_snapshot = analyze_tactics(
        position.with_side_to_move(position.side_to_move.opponent),
        inc_state=incremental_state,
        include_move_maps=False,
    )
    urgent = (
        snapshot.winning_moves
        or snapshot.forced_blocks
        or snapshot.double_threats
        or snapshot.opponent_winning_moves
        or opponent_snapshot.winning_moves
        or opponent_snapshot.forced_blocks
        or opponent_snapshot.double_threats
        or opponent_snapshot.opponent_winning_moves
    )
    return (not urgent), snapshot, opponent_snapshot


def _load_append_state(output_path: Path) -> tuple[set[int], int, int]:
    if not output_path.exists():
        return set(), 0, 0

    dataset_kind = load_dataset_kind(output_path)
    if dataset_kind != DATASET_KIND_ROOT_POLICY_V1:
        raise ValueError(f"append mode requires a {DATASET_KIND_ROOT_POLICY_V1} dataset")

    with np.load(output_path) as data:
        existing_hashes: set[int] = set()
        if "canonical_hashes" in data.files:
            existing_hashes = {int(value) for value in np.asarray(data["canonical_hashes"]).tolist()}
        next_game_id = 0
        if "game_ids" in data.files and np.asarray(data["game_ids"]).size:
            next_game_id = int(np.asarray(data["game_ids"]).max()) + 1
        existing_samples = int(np.asarray(data["features"]).shape[0])
    return existing_hashes, next_game_id, existing_samples


def collect_root_policy_examples(
    games: int,
    seed: int,
    play_depth: int,
    label_depth: int,
    output_path: str | Path,
    *,
    play_time_ms: int | None = None,
    label_time_ms: int | None = 1_500,
    sample_every: int = 2,
    sample_start_ply: int = 2,
    temperature: float = 0.8,
    temperature_plies: int = 8,
    sample_top_k: int = 4,
    min_candidate_moves: int = 4,
    min_score_gap: int = 50,
    max_score_gap: int = 4_000,
    max_positions: int | None = None,
    append_output: bool = False,
) -> int:
    rng = random.Random(seed)
    play_engine = SearchEngine()
    label_engine = SearchEngine()
    resolved_output_path = Path(output_path)
    features: list[np.ndarray] = []
    legal_masks: list[np.ndarray] = []
    policy_targets: list[int] = []
    best_scores: list[int] = []
    score_gaps: list[int] = []
    search_depths: list[int] = []
    game_ids: list[int] = []
    plies: list[int] = []
    canonical_hashes: list[np.uint64] = []
    seen_hashes: set[int] = set()
    existing_hashes: set[int] = set()
    game_id_offset = 0
    skipped_duplicates = 0
    skipped_urgent = 0
    skipped_small = 0
    skipped_gap = 0

    if append_output:
        existing_hashes, game_id_offset, existing_samples = _load_append_state(resolved_output_path)
        if existing_samples:
            print(
                f"append mode: existing_samples={existing_samples} "
                f"existing_hashes={len(existing_hashes)} next_game_id={game_id_offset}"
            )

    for game_index in range(games):
        position = Position.initial()
        ply = 0
        game_new_samples = 0

        while True:
            if max_positions is not None and len(features) >= max_positions:
                break

            if ply >= sample_start_ply and (ply - sample_start_ply) % sample_every == 0:
                canonical_hash = int(canonical_position_hash(position))
                if canonical_hash in seen_hashes or canonical_hash in existing_hashes:
                    skipped_duplicates += 1
                else:
                    incremental_state = IncrementalState.from_position(position)
                    is_candidate, snapshot, opponent_snapshot = _is_root_policy_candidate(position, incremental_state)
                    if not is_candidate:
                        skipped_urgent += 1
                    else:
                        label_result = label_engine.search(
                            position,
                            max_depth=label_depth,
                            max_time_ms=label_time_ms,
                            analyze_root=True,
                        )
                        root_move_scores = label_result.root_move_scores
                        if len(root_move_scores) < min_candidate_moves:
                            skipped_small += 1
                        else:
                            score_gap = int(root_move_scores[0].score - root_move_scores[1].score)
                            if score_gap < min_score_gap or score_gap > max_score_gap:
                                skipped_gap += 1
                            else:
                                seen_hashes.add(canonical_hash)
                                features.append(
                                    encode_position(
                                        position,
                                        snapshot=snapshot,
                                        opponent_snapshot=opponent_snapshot,
                                    )
                                )
                                legal_masks.append(_candidate_legal_mask(root_move_scores))
                                policy_targets.append(root_move_scores[0].move)
                                best_scores.append(root_move_scores[0].score)
                                score_gaps.append(score_gap)
                                search_depths.append(label_result.depth)
                                game_ids.append(game_id_offset + game_index)
                                plies.append(ply)
                                canonical_hashes.append(np.uint64(canonical_hash))
                                existing_hashes.add(canonical_hash)
                                game_new_samples += 1

            play_result = play_engine.search(
                position,
                max_depth=play_depth,
                max_time_ms=play_time_ms,
                analyze_root=True,
            )
            if play_result.best_move is None:
                break

            move = play_result.best_move
            if ply < temperature_plies and play_result.root_move_scores:
                sampled_move = _sample_root_move(play_result.root_move_scores, temperature, sample_top_k, rng)
                if sampled_move is not None:
                    move = sampled_move

            next_position, move_result = play_move(position, move)
            if move_result is not MoveResult.NONTERMINAL:
                break

            position = next_position
            ply += 1
            if position.empty_count == 0:
                break

        print(
            f"game {game_index + 1}/{games}: samples={len(features)} game_new={game_new_samples} "
            f"skipped_duplicates={skipped_duplicates} skipped_urgent={skipped_urgent} "
            f"skipped_small={skipped_small} skipped_gap={skipped_gap}"
        )
        if max_positions is not None and len(features) >= max_positions:
            break

    if not features:
        if append_output and resolved_output_path.exists():
            return 0
        raise RuntimeError("no root-policy training samples were generated")

    save_fn = append_root_policy_examples if append_output else save_root_policy_examples
    save_fn(
        resolved_output_path,
        np.stack(features),
        np.stack(legal_masks),
        np.array(policy_targets, dtype=np.int64),
        best_scores=np.array(best_scores, dtype=np.int32),
        score_gaps=np.array(score_gaps, dtype=np.int32),
        search_depths=np.array(search_depths, dtype=np.int16),
        extra_arrays={
            "game_ids": np.array(game_ids, dtype=np.int32),
            "plies": np.array(plies, dtype=np.int16),
            "canonical_hashes": np.array(canonical_hashes, dtype=np.uint64),
        },
    )
    return len(features)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate root-policy training data for Ukumog.")
    parser.add_argument("--games", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260421)
    parser.add_argument("--play-depth", type=int, default=2)
    parser.add_argument("--label-depth", type=int, default=6)
    parser.add_argument("--play-time-ms", type=int, default=0)
    parser.add_argument("--label-time-ms", type=int, default=1_500)
    parser.add_argument("--sample-every", type=int, default=2)
    parser.add_argument("--sample-start-ply", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--temperature-plies", type=int, default=8)
    parser.add_argument("--sample-top-k", type=int, default=4)
    parser.add_argument("--min-candidate-moves", type=int, default=4)
    parser.add_argument("--min-score-gap", type=int, default=50)
    parser.add_argument("--max-score-gap", type=int, default=4_000)
    parser.add_argument("--max-positions", type=int, default=None)
    parser.set_defaults(append_output=False)
    parser.add_argument(
        "--append-output",
        dest="append_output",
        action="store_true",
        help="Append new deduplicated samples to an existing root_policy_v1 dataset.",
    )
    parser.add_argument(
        "--replace-output",
        dest="append_output",
        action="store_false",
        help="Replace the output dataset instead of appending. Default.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    play_time_ms = None if args.play_time_ms == 0 else args.play_time_ms
    label_time_ms = None if args.label_time_ms == 0 else args.label_time_ms
    total = collect_root_policy_examples(
        games=args.games,
        seed=args.seed,
        play_depth=args.play_depth,
        label_depth=args.label_depth,
        output_path=args.output,
        play_time_ms=play_time_ms,
        label_time_ms=label_time_ms,
        sample_every=args.sample_every,
        sample_start_ply=args.sample_start_ply,
        temperature=args.temperature,
        temperature_plies=args.temperature_plies,
        sample_top_k=args.sample_top_k,
        min_candidate_moves=args.min_candidate_moves,
        min_score_gap=args.min_score_gap,
        max_score_gap=args.max_score_gap,
        max_positions=args.max_positions,
        append_output=args.append_output,
    )
    action = "appended" if args.append_output else "saved"
    print(f"{action} {total} root-policy samples to {args.output}")


if __name__ == "__main__":
    main()
