from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ukumog_engine.apps import cli as play_cli
from ukumog_engine import Color, MoveResult, Position, SearchEngine, play_move
from ukumog_engine.search import RootMoveScore
from dev.tools.search_benchmark import benchmark_positions



DEFAULT_OPENING_SEEDS = tuple(range(20260421, 20260429))


@dataclass(frozen=True, slots=True)
class SuitePosition:
    name: str
    position: Position


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


def generate_opening_prefix_position(
    seed: int,
    *,
    opening_plies: int = 8,
    depth: int = 2,
    temperature: float = 0.8,
    sample_top_k: int = 4,
) -> Position:
    rng = random.Random(seed)
    engine = SearchEngine()
    position = Position.initial()

    for ply in range(opening_plies):
        result = engine.search(position, max_depth=depth, analyze_root=True)
        if result.best_move is None:
            break

        move = result.best_move
        sampled_move = _sample_root_move(result.root_move_scores, temperature, sample_top_k, rng)
        if sampled_move is not None:
            move = sampled_move

        next_position, move_result = play_move(position, move)
        if move_result is not MoveResult.NONTERMINAL:
            return next_position
        position = next_position

    return position


def default_suite_positions() -> list[SuitePosition]:
    positions: list[SuitePosition] = []
    for seed in DEFAULT_OPENING_SEEDS:
        positions.append(
            SuitePosition(
                name=f"opening_seed_{seed}",
                position=generate_opening_prefix_position(seed),
            )
        )

    benchmark = benchmark_positions()
    positions.append(SuitePosition(name="quiet_midgame", position=benchmark["quiet_midgame"]))
    positions.append(SuitePosition(name="tactical_midgame", position=benchmark["tactical_midgame"]))
    return positions


def run_match_suite(
    candidate_spec: play_cli.EngineSpec,
    baseline_spec: play_cli.EngineSpec,
    *,
    suite_positions: list[SuitePosition] | None = None,
    time_controls: tuple[float, ...] = (0.5, 1.0),
    max_moves: int = 121,
) -> dict[str, object]:
    positions = suite_positions if suite_positions is not None else default_suite_positions()
    summary: dict[str, object] = {"results": [], "time_controls": {}}

    match_args = argparse.Namespace(
        temperature_plies=0,
        sample_top_k=1,
        max_moves=max_moves,
        search_summary=False,
        time_trace=False,
        stats_jsonl=None,
        seed=0,
    )

    for time_control in time_controls:
        candidate_timed = replace(candidate_spec, time_seconds=time_control, temperature=0.0)
        baseline_timed = replace(baseline_spec, time_seconds=time_control, temperature=0.0)
        control_key = f"{time_control:g}"
        control_summary = {
            candidate_spec.name: {"wins": 0, "losses": 0, "draws": 0},
            baseline_spec.name: {"wins": 0, "losses": 0, "draws": 0},
            "games": 0,
        }

        for position_index, suite_position in enumerate(positions):
            for paired_index, candidate_as_black in enumerate((True, False)):
                black_spec = candidate_timed if candidate_as_black else baseline_timed
                white_spec = baseline_timed if candidate_as_black else candidate_timed
                game_seed = 10_000 + (position_index * 10) + paired_index
                result = play_cli._play_engine_vs_engine_game(
                    black_spec,
                    white_spec,
                    match_args,
                    random.Random(game_seed),
                    game_index=control_summary["games"],
                    verbose=False,
                    start_position=suite_position.position,
                )
                winner = result["winner"]
                control_summary["games"] += 1
                if winner is None:
                    control_summary[candidate_spec.name]["draws"] += 1
                    control_summary[baseline_spec.name]["draws"] += 1
                else:
                    loser = baseline_spec.name if winner == candidate_spec.name else candidate_spec.name
                    control_summary[winner]["wins"] += 1
                    control_summary[loser]["losses"] += 1

                summary["results"].append(
                    {
                        "time_seconds": time_control,
                        "position": suite_position.name,
                        "candidate_as_black": candidate_as_black,
                        "winner": winner,
                        "reason": result["reason"],
                        "plies_played": result["plies_played"],
                    }
                )

        candidate_score = (
            control_summary[candidate_spec.name]["wins"]
            + (0.5 * control_summary[candidate_spec.name]["draws"])
        ) / max(1, control_summary["games"])
        control_summary["candidate_score_fraction"] = candidate_score
        summary["time_controls"][control_key] = control_summary

    return summary


def _print_summary(summary: dict[str, object], candidate_name: str, baseline_name: str) -> None:
    print("ML match suite")
    for time_key, control_summary in summary["time_controls"].items():
        print(f"time={time_key}s games={control_summary['games']}")
        for name in (candidate_name, baseline_name):
            stats = control_summary[name]
            print(
                f"{name}: wins={stats['wins']} losses={stats['losses']} draws={stats['draws']}"
            )
        print(f"{candidate_name} score={control_summary['candidate_score_fraction']:.1%}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed Ukumog ML match suite.")
    parser.add_argument("--candidate-name", type=str, default="Candidate")
    parser.add_argument("--baseline-name", type=str, default="PureSearch")
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument(
        "--ml-mode",
        choices=("auto", "quiet-value", "full", "policy-only", "root-policy", "root-hybrid"),
        default="auto",
    )
    parser.add_argument("--learned-weight", type=float, default=0.10)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--symmetry-ensemble", action="store_true")
    parser.add_argument("--baseline-model", type=Path, default=None)
    parser.add_argument(
        "--baseline-ml-mode",
        choices=("auto", "quiet-value", "full", "policy-only", "root-policy", "root-hybrid"),
        default="auto",
    )
    parser.add_argument("--baseline-learned-weight", type=float, default=0.10)
    parser.add_argument("--baseline-device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--baseline-symmetry-ensemble", action="store_true")
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument(
        "--candidate-depth",
        type=int,
        default=None,
        help="Candidate search depth override. Defaults to --depth.",
    )
    parser.add_argument(
        "--baseline-depth",
        type=int,
        default=None,
        help="Baseline search depth override. Defaults to --depth.",
    )
    parser.add_argument("--max-moves", type=int, default=121)
    parser.add_argument("--time-controls", type=float, nargs="*", default=[0.5, 1.0])
    args = parser.parse_args()

    candidate_depth = args.depth if args.candidate_depth is None else args.candidate_depth
    baseline_depth = args.depth if args.baseline_depth is None else args.baseline_depth

    candidate_spec = play_cli.EngineSpec(
        name=args.candidate_name,
        model_path=args.model,
        ml_mode=args.ml_mode,
        device=args.device,
        depth=candidate_depth,
        time_seconds=0.0,
        learned_weight=args.learned_weight,
        temperature=0.0,
        symmetry_ensemble=args.symmetry_ensemble,
    )
    baseline_spec = play_cli.EngineSpec(
        name=args.baseline_name,
        model_path=args.baseline_model,
        ml_mode=args.baseline_ml_mode,
        device=args.baseline_device,
        depth=baseline_depth,
        time_seconds=0.0,
        learned_weight=args.baseline_learned_weight,
        temperature=0.0,
        symmetry_ensemble=args.baseline_symmetry_ensemble,
    )

    summary = run_match_suite(
        candidate_spec,
        baseline_spec,
        time_controls=tuple(args.time_controls),
        max_moves=args.max_moves,
    )
    _print_summary(summary, candidate_spec.name, baseline_spec.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
