from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import math
import random

from ukumog_engine import Color, MoveResult, Position, SearchEngine, coord_to_index, index_to_coord, play_move
from ukumog_engine.ml import TorchPolicyValueEvaluator


STONE_BY_COLOR = {
    Color.BLACK: "B",
    Color.WHITE: "W",
}


@dataclass(slots=True)
class EngineController:
    label: str
    depth: int
    time_seconds: float
    learned_weight: float
    model_path: Path | None
    ml_mode: str
    temperature: float
    symmetry_ensemble: bool
    engine: SearchEngine
    searches_run: int = 0
    total_search_seconds: float = 0.0
    total_model_seconds: float = 0.0
    total_nodes: int = 0
    total_qnodes: int = 0
    total_tactics_seconds: float = 0.0
    total_eval_seconds: float = 0.0
    total_ordering_seconds: float = 0.0
    total_quiescence_seconds: float = 0.0
    total_proof_seconds: float = 0.0

    @property
    def time_ms(self) -> int | None:
        return None if self.time_seconds <= 0 else int(self.time_seconds * 1000)


@dataclass(frozen=True, slots=True)
class EngineSpec:
    name: str
    model_path: Path | None
    ml_mode: str
    depth: int
    time_seconds: float
    learned_weight: float
    temperature: float
    symmetry_ensemble: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play Ukumog against the current search engine.")
    parser.add_argument(
        "--mode",
        choices=("human-vs-engine", "engine-vs-engine"),
        default="human-vs-engine",
        help="Run a normal human game or an engine-vs-engine match. Default: human-vs-engine.",
    )
    parser.add_argument(
        "--human",
        choices=("black", "white"),
        default="black",
        help="Which side the human controls. Default: black.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=4,
        help="Search depth for the engine. Default: 4.",
    )
    parser.add_argument(
        "--time",
        type=float,
        default=10.0,
        help="Engine move time limit in seconds. Use 0 to disable. Default: 10.",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help="Optional checkpoint produced by `python -m ukumog_engine.ml.train`.",
    )
    parser.add_argument(
        "--ml-mode",
        choices=("quiet-value", "full", "policy-only", "root-policy", "root-hybrid"),
        default="quiet-value",
        help="How the learned model is used inside search. Default: quiet-value.",
    )
    parser.add_argument(
        "--learned-weight",
        type=float,
        default=0.25,
        help="How strongly to blend the learned evaluator into static evaluation. Default: 0.25.",
    )
    parser.add_argument(
        "--symmetry-ensemble",
        action="store_true",
        help="Average model predictions over all board symmetries for stronger but slower inference.",
    )
    parser.add_argument("--black-model", type=Path, default=None, help="Optional checkpoint for the black engine.")
    parser.add_argument("--white-model", type=Path, default=None, help="Optional checkpoint for the white engine.")
    parser.add_argument("--black-depth", type=int, default=None, help="Black engine search depth override.")
    parser.add_argument("--white-depth", type=int, default=None, help="White engine search depth override.")
    parser.add_argument("--black-time", type=float, default=None, help="Black engine move time limit override.")
    parser.add_argument("--white-time", type=float, default=None, help="White engine move time limit override.")
    parser.add_argument(
        "--black-learned-weight",
        type=float,
        default=None,
        help="Black engine learned-eval weight override.",
    )
    parser.add_argument(
        "--white-learned-weight",
        type=float,
        default=None,
        help="White engine learned-eval weight override.",
    )
    parser.add_argument(
        "--black-ml-mode",
        choices=("quiet-value", "full", "policy-only", "root-policy", "root-hybrid"),
        default=None,
        help="Black engine ML integration mode override.",
    )
    parser.add_argument(
        "--white-ml-mode",
        choices=("quiet-value", "full", "policy-only", "root-policy", "root-hybrid"),
        default=None,
        help="White engine ML integration mode override.",
    )
    parser.add_argument(
        "--black-symmetry-ensemble",
        action="store_true",
        help="Enable symmetry-ensemble inference for the black engine.",
    )
    parser.add_argument(
        "--white-symmetry-ensemble",
        action="store_true",
        help="Enable symmetry-ensemble inference for the white engine.",
    )
    parser.add_argument(
        "--max-moves",
        type=int,
        default=121,
        help="Stop engine-vs-engine games after this many plies if still nonterminal. Default: 121.",
    )
    parser.add_argument(
        "--games",
        type=int,
        default=1,
        help="Number of engine-vs-engine games to run. Default: 1.",
    )
    parser.add_argument(
        "--shuffle-colors",
        action="store_true",
        help="Randomly swap which configured engine gets Black each engine-vs-engine game.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Opening move sampling temperature. `0` keeps deterministic play. Default: 0.",
    )
    parser.add_argument(
        "--black-temperature",
        type=float,
        default=None,
        help="Black engine opening temperature override.",
    )
    parser.add_argument(
        "--white-temperature",
        type=float,
        default=None,
        help="White engine opening temperature override.",
    )
    parser.add_argument(
        "--temperature-plies",
        type=int,
        default=10,
        help="Only sample during the first N plies of a game. Default: 10.",
    )
    parser.add_argument(
        "--sample-top-k",
        type=int,
        default=4,
        help="Sample only from the top K root candidates when temperature is enabled. Default: 4.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260419,
        help="Random seed used for temperature-based move sampling. Default: 20260419.",
    )
    parser.add_argument(
        "--seed-step",
        type=int,
        default=1,
        help="Increment added to the base seed between batch games. Default: 1.",
    )
    parser.add_argument(
        "--search-summary",
        action="store_true",
        help="Print a detailed per-search instrumentation summary after each engine move.",
    )
    parser.add_argument(
        "--stats-jsonl",
        type=Path,
        default=None,
        help="Optional JSONL file that receives structured per-search records during play.",
    )
    parser.add_argument(
        "--time-trace",
        action="store_true",
        help="Print per-move and per-engine timing breakdowns from search stats.",
    )
    return parser.parse_args(argv)


def render_board(position: Position) -> str:
    header = "    " + " ".join(f"{col:2d}" for col in range(11))
    lines = [header]
    for row in range(11):
        cells: list[str] = []
        for col in range(11):
            move = coord_to_index(row, col)
            if position.black_bits & (1 << move):
                cells.append("B ")
            elif position.white_bits & (1 << move):
                cells.append("W ")
            else:
                cells.append(". ")
        lines.append(f"{row:2d}  " + "".join(cells))
    return "\n".join(lines)


def parse_human_move(raw: str) -> tuple[int, int] | None:
    cleaned = raw.strip().lower()
    if cleaned in {"q", "quit", "exit"}:
        return None

    parts = cleaned.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError("enter moves as: row col")

    row = int(parts[0])
    col = int(parts[1])
    if not (0 <= row < 11 and 0 <= col < 11):
        raise ValueError("row and col must both be between 0 and 10")
    return row, col


def announce_result(actor: str, color: Color, move: int, result: MoveResult) -> str:
    row, col = index_to_coord(move)
    stone = STONE_BY_COLOR[color]
    if result is MoveResult.WIN:
        return f"{actor} played {stone} at ({row}, {col}) and wins immediately."
    if result is MoveResult.LOSS:
        return f"{actor} played {stone} at ({row}, {col}) and loses immediately."
    return f"{actor} played {stone} at ({row}, {col})."


def _build_engine_controller(
    color: Color,
    model_path: Path | None,
    ml_mode: str,
    depth: int,
    time_seconds: float,
    learned_weight: float,
    temperature: float,
    symmetry_ensemble: bool,
    label: str | None = None,
) -> EngineController:
    learned_evaluator = (
        TorchPolicyValueEvaluator.from_checkpoint(
            model_path,
            device="cpu",
            symmetry_ensemble=symmetry_ensemble,
        )
        if model_path is not None
        else None
    )
    if label is None:
        if model_path is None:
            label = f"{color.name.title()} PureSearch"
        else:
            label = f"{color.name.title()} ML"

    if ml_mode == "quiet-value":
        learned_policy_max_ply = -1
        learned_value_max_ply = None
        effective_weight = learned_weight
    elif ml_mode == "full":
        learned_policy_max_ply = None
        learned_value_max_ply = None
        effective_weight = learned_weight
    elif ml_mode == "policy-only":
        learned_policy_max_ply = None
        learned_value_max_ply = -1
        effective_weight = 0.0
    elif ml_mode == "root-hybrid":
        learned_policy_max_ply = 0
        learned_value_max_ply = 0
        effective_weight = learned_weight
    else:
        learned_policy_max_ply = 0
        learned_value_max_ply = -1
        effective_weight = 0.0

    return EngineController(
        label=label,
        depth=depth,
        time_seconds=time_seconds,
        learned_weight=effective_weight,
        model_path=model_path,
        ml_mode=ml_mode,
        temperature=temperature,
        symmetry_ensemble=symmetry_ensemble,
        engine=SearchEngine(
            learned_evaluator=learned_evaluator,
            learned_eval_weight=effective_weight,
            learned_policy_max_ply=learned_policy_max_ply,
            learned_value_max_ply=learned_value_max_ply,
        ),
    )


def _engine_settings_for_color(
    args: argparse.Namespace,
    color: Color,
) -> tuple[Path | None, str, int, float, float, float, bool]:
    prefix = "black" if color is Color.BLACK else "white"
    model_path = getattr(args, f"{prefix}_model") or args.model
    ml_mode = getattr(args, f"{prefix}_ml_mode") or args.ml_mode
    depth = getattr(args, f"{prefix}_depth") or args.depth
    time_seconds = getattr(args, f"{prefix}_time")
    if time_seconds is None:
        time_seconds = args.time
    learned_weight = getattr(args, f"{prefix}_learned_weight")
    if learned_weight is None:
        learned_weight = args.learned_weight
    temperature = getattr(args, f"{prefix}_temperature")
    if temperature is None:
        temperature = args.temperature
    symmetry_ensemble = getattr(args, f"{prefix}_symmetry_ensemble") or args.symmetry_ensemble
    return model_path, ml_mode, depth, time_seconds, learned_weight, temperature, symmetry_ensemble


def _engine_spec_for_color(
    args: argparse.Namespace,
    color: Color,
    name: str,
) -> EngineSpec:
    model_path, ml_mode, depth, time_seconds, learned_weight, temperature, symmetry_ensemble = _engine_settings_for_color(
        args,
        color,
    )
    return EngineSpec(
        name=name,
        model_path=model_path,
        ml_mode=ml_mode,
        depth=depth,
        time_seconds=time_seconds,
        learned_weight=learned_weight,
        temperature=temperature,
        symmetry_ensemble=symmetry_ensemble,
    )


def _describe_engine(controller: EngineController) -> str:
    time_text = "unlimited" if controller.time_ms is None else f"{controller.time_seconds:g}s"
    if controller.model_path is None:
        model_text = "pure search"
    else:
        model_text = f"model={controller.model_path}"
    return (
        f"{controller.label}: depth={controller.depth}, time={time_text}, "
        f"ml_mode={controller.ml_mode}, learned_weight={controller.learned_weight:g}, "
        f"temperature={controller.temperature:g}, "
        f"symmetry_ensemble={controller.symmetry_ensemble}, {model_text}"
    )


def _describe_spec(spec: EngineSpec) -> str:
    time_text = "unlimited" if spec.time_seconds <= 0 else f"{spec.time_seconds:g}s"
    if spec.model_path is None:
        model_text = "pure search"
    else:
        model_text = f"model={spec.model_path}"
    return (
        f"{spec.name}: depth={spec.depth}, time={time_text}, "
        f"ml_mode={spec.ml_mode}, learned_weight={spec.learned_weight:g}, "
        f"temperature={spec.temperature:g}, "
        f"symmetry_ensemble={spec.symmetry_ensemble}, {model_text}"
    )


def _sample_root_move(
    preferred_move: int | None,
    ordered_moves: list[int],
    temperature: float,
    sample_top_k: int,
    rng: random.Random,
) -> int | None:
    if preferred_move is None:
        return None
    if temperature <= 0 or len(ordered_moves) <= 1:
        return preferred_move

    shortlist: list[int] = [preferred_move]
    for move in ordered_moves:
        if move != preferred_move:
            shortlist.append(move)
        if len(shortlist) >= max(1, sample_top_k):
            break

    if len(shortlist) == 1:
        return preferred_move

    weights = [math.exp(-(index / temperature)) for index in range(len(shortlist))]
    return rng.choices(shortlist, weights=weights, k=1)[0]


def _append_stats_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _record_search_totals(controller: EngineController, search_result: object) -> None:
    controller.searches_run += 1
    controller.total_search_seconds += search_result.stats.elapsed_seconds
    controller.total_model_seconds += search_result.stats.model_time_seconds
    controller.total_nodes += search_result.stats.nodes
    controller.total_qnodes += search_result.stats.quiescence_nodes
    controller.total_tactics_seconds += search_result.stats.tactics_time_seconds
    controller.total_eval_seconds += search_result.stats.eval_time_seconds
    controller.total_ordering_seconds += search_result.stats.ordering_time_seconds
    controller.total_quiescence_seconds += search_result.stats.quiescence_time_seconds
    controller.total_proof_seconds += search_result.stats.proof_solver_time_seconds


def _format_time_trace(controller: EngineController, search_result: object) -> str:
    stats = search_result.stats
    cumulative_share = 0.0
    if controller.total_search_seconds > 0.0:
        cumulative_share = controller.total_model_seconds / controller.total_search_seconds
    return "\n".join(
        [
            (
                "time "
                f"search={stats.elapsed_seconds:.3f}s "
                f"model={stats.model_time_seconds:.3f}s "
                f"share={stats.model_time_fraction:.1%} "
                f"nodes={stats.nodes} "
                f"qnodes={stats.quiescence_nodes} "
                f"nps={stats.nodes_per_second:.0f} "
                f"qnps={stats.qnodes_per_second:.0f} "
                f"cum_search={controller.total_search_seconds:.3f}s "
                f"cum_model={controller.total_model_seconds:.3f}s "
                f"cum_share={cumulative_share:.1%}"
            ),
            (
                "breakdown "
                f"tactics={stats.tactics_time_seconds:.3f}s "
                f"eval={stats.eval_time_seconds:.3f}s "
                f"ordering={stats.ordering_time_seconds:.3f}s "
                f"quiescence={stats.quiescence_time_seconds:.3f}s "
                f"proof={stats.proof_solver_time_seconds:.3f}s"
            ),
        ]
    )


def _print_match_time_totals(controllers: dict[Color, EngineController]) -> None:
    printed_header = False
    for color in (Color.BLACK, Color.WHITE):
        controller = controllers.get(color)
        if controller is None or controller.searches_run == 0:
            continue
        if not printed_header:
            print("Timing totals:")
            printed_header = True
        avg_search = controller.total_search_seconds / controller.searches_run
        avg_model = controller.total_model_seconds / controller.searches_run
        model_share = 0.0
        if controller.total_search_seconds > 0.0:
            model_share = controller.total_model_seconds / controller.total_search_seconds
        print(
            f"{controller.label}: searches={controller.searches_run}, "
            f"total_search={controller.total_search_seconds:.3f}s, "
            f"avg_search={avg_search:.3f}s, "
            f"total_model={controller.total_model_seconds:.3f}s, "
            f"avg_model={avg_model:.3f}s, "
            f"model_share={model_share:.1%}, "
            f"nodes={controller.total_nodes}, "
            f"qnodes={controller.total_qnodes}"
        )
        print(
            f"{controller.label} breakdown: "
            f"tactics={controller.total_tactics_seconds:.3f}s, "
            f"eval={controller.total_eval_seconds:.3f}s, "
            f"ordering={controller.total_ordering_seconds:.3f}s, "
            f"quiescence={controller.total_quiescence_seconds:.3f}s, "
            f"proof={controller.total_proof_seconds:.3f}s"
        )


def _choose_engine_move(
    position: Position,
    controller: EngineController,
    plies_played: int,
    temperature_plies: int,
    sample_top_k: int,
    rng: random.Random,
) -> tuple[int | None, object, bool]:
    result = controller.engine.search(position, max_depth=controller.depth, max_time_ms=controller.time_ms)
    sampled = False
    move = result.best_move
    if (
        controller.temperature > 0
        and plies_played < temperature_plies
        and result.best_move is not None
    ):
        incremental_state = controller.engine._search_incremental_state(position)
        snapshot = controller.engine._tactics(position, incremental_state)
        ordered_moves = controller.engine._ordered_search_moves(
            position,
            incremental_state,
            snapshot,
            controller.depth,
            0,
            None,
            True,
        )
        sampled_move = _sample_root_move(result.best_move, ordered_moves, controller.temperature, sample_top_k, rng)
        if sampled_move is not None:
            sampled = sampled_move != result.best_move
            move = sampled_move
    return move, result, sampled


def _controller_from_spec(color: Color, spec: EngineSpec) -> EngineController:
    return _build_engine_controller(
        color=color,
        model_path=spec.model_path,
        ml_mode=spec.ml_mode,
        depth=spec.depth,
        time_seconds=spec.time_seconds,
        learned_weight=spec.learned_weight,
        temperature=spec.temperature,
        symmetry_ensemble=spec.symmetry_ensemble,
        label=f"{spec.name} ({color.name.title()})",
    )


def _play_engine_vs_engine_game(
    black_spec: EngineSpec,
    white_spec: EngineSpec,
    args: argparse.Namespace,
    rng: random.Random,
    *,
    game_index: int = 0,
    verbose: bool = True,
) -> dict[str, object]:
    position = Position.initial()
    controllers = {
        Color.BLACK: _controller_from_spec(Color.BLACK, black_spec),
        Color.WHITE: _controller_from_spec(Color.WHITE, white_spec),
    }
    participant_by_color = {
        Color.BLACK: black_spec.name,
        Color.WHITE: white_spec.name,
    }
    plies_played = 0

    if verbose:
        print("Engine-vs-engine mode")
        print(_describe_engine(controllers[Color.BLACK]))
        print(_describe_engine(controllers[Color.WHITE]))
        print(
            f"Opening sampling: first {args.temperature_plies} plies, "
            f"top_k={args.sample_top_k}, seed={args.seed}."
        )

    while True:
        if verbose:
            print()
            print(render_board(position))
        side_to_move = position.side_to_move

        if position.empty_count == 0:
            if verbose:
                print("Board is full. Draw-by-exhaustion handling is not defined, so stopping here.")
                if args.time_trace:
                    _print_match_time_totals(controllers)
            return {
                "winner": None,
                "reason": "board_full",
                "plies_played": plies_played,
                "controllers": controllers,
            }

        controller = controllers[side_to_move]
        if verbose:
            print(f"{controller.label} thinking...")
        move, search_result, sampled = _choose_engine_move(
            position,
            controller,
            plies_played,
            args.temperature_plies,
            args.sample_top_k,
            rng,
        )
        if move is None:
            if verbose:
                print(f"{controller.label} found no legal move. Stopping.")
                if args.time_trace:
                    _print_match_time_totals(controllers)
            return {
                "winner": None,
                "reason": "no_move",
                "plies_played": plies_played,
                "controllers": controllers,
            }

        next_position, move_result = play_move(position, move)
        row, col = index_to_coord(move)
        _record_search_totals(controller, search_result)
        if verbose:
            print(
                f"{controller.label} chooses ({row}, {col}) "
                f"[score={search_result.score}, depth={search_result.depth}, nodes={search_result.stats.nodes}]"
            )
            if args.time_trace:
                print(_format_time_trace(controller, search_result))
            if args.search_summary:
                print(search_result.format_summary())
            if sampled:
                best_row, best_col = index_to_coord(search_result.best_move)
                print(
                    f"{controller.label} sampled an opening move from its root shortlist; "
                    f"strict best was ({best_row}, {best_col})."
                )
            if search_result.stats.aborted:
                if search_result.stats.time_limit_abort:
                    print(
                        f"{controller.label} hit the move time limit and used the best move "
                        "from the last completed iteration."
                    )
                elif search_result.stats.node_limit_abort:
                    print(
                        f"{controller.label} hit its node limit and used the best move "
                        "from the last completed iteration."
                    )
        if args.stats_jsonl is not None:
            _append_stats_record(
                args.stats_jsonl,
                {
                    "event": "search",
                    "game": game_index,
                    "engine": controller.label,
                    "participant": participant_by_color[side_to_move],
                    "side_to_move": side_to_move.name,
                    "ply": plies_played,
                    "sampled": sampled,
                    "selected_move": move,
                    "search": search_result.to_dict(),
                },
            )
        if verbose:
            print(announce_result(controller.label, side_to_move, move, move_result))

        position = next_position
        plies_played += 1

        if plies_played >= args.max_moves and move_result is MoveResult.NONTERMINAL:
            if verbose:
                print()
                print(render_board(position))
                if args.time_trace:
                    _print_match_time_totals(controllers)
                print(f"Reached the engine-vs-engine move cap ({args.max_moves}) without a terminal result.")
            if args.stats_jsonl is not None:
                _append_stats_record(
                    args.stats_jsonl,
                    {
                        "event": "match_end",
                        "game": game_index,
                        "reason": "move_cap",
                        "plies_played": plies_played,
                    },
                )
            return {
                "winner": None,
                "reason": "move_cap",
                "plies_played": plies_played,
                "controllers": controllers,
            }

        if move_result is MoveResult.WIN:
            winner = participant_by_color[side_to_move]
            if verbose:
                print()
                print(render_board(position))
                if args.time_trace:
                    _print_match_time_totals(controllers)
                print(f"{winner} wins.")
            if args.stats_jsonl is not None:
                _append_stats_record(
                    args.stats_jsonl,
                    {
                        "event": "match_end",
                        "game": game_index,
                        "reason": "win",
                        "winner": winner,
                        "plies_played": plies_played,
                    },
                )
            return {
                "winner": winner,
                "reason": "win",
                "plies_played": plies_played,
                "controllers": controllers,
            }

        if move_result is MoveResult.LOSS:
            winner = participant_by_color[side_to_move.opponent]
            if verbose:
                print()
                print(render_board(position))
                if args.time_trace:
                    _print_match_time_totals(controllers)
                print(f"{winner} wins.")
            if args.stats_jsonl is not None:
                _append_stats_record(
                    args.stats_jsonl,
                    {
                        "event": "match_end",
                        "game": game_index,
                        "reason": "loss",
                        "winner": winner,
                        "plies_played": plies_played,
                    },
                )
            return {
                "winner": winner,
                "reason": "loss",
                "plies_played": plies_played,
                "controllers": controllers,
            }


def _run_engine_batch(args: argparse.Namespace, engine_a: EngineSpec, engine_b: EngineSpec) -> int:
    print("Engine-vs-engine batch mode")
    print(_describe_spec(engine_a))
    print(_describe_spec(engine_b))
    print(
        f"Games={args.games}, shuffle_colors={args.shuffle_colors}, "
        f"base_seed={args.seed}, seed_step={args.seed_step}."
    )

    summary = {
        engine_a.name: {"wins": 0, "losses": 0, "draws": 0, "black_games": 0, "white_games": 0},
        engine_b.name: {"wins": 0, "losses": 0, "draws": 0, "black_games": 0, "white_games": 0},
    }

    for game_index in range(args.games):
        game_seed = args.seed + (game_index * args.seed_step)
        game_rng = random.Random(game_seed)
        swap_colors = args.shuffle_colors and bool(game_rng.randrange(2))
        black_spec, white_spec = (engine_b, engine_a) if swap_colors else (engine_a, engine_b)
        summary[black_spec.name]["black_games"] += 1
        summary[white_spec.name]["white_games"] += 1

        result = _play_engine_vs_engine_game(
            black_spec,
            white_spec,
            args,
            game_rng,
            game_index=game_index,
            verbose=False,
        )
        winner = result["winner"]
        if winner is None:
            summary[engine_a.name]["draws"] += 1
            summary[engine_b.name]["draws"] += 1
            outcome_text = result["reason"]
        else:
            loser = engine_b.name if winner == engine_a.name else engine_a.name
            summary[winner]["wins"] += 1
            summary[loser]["losses"] += 1
            outcome_text = f"{winner} wins"

        print(
            f"game {game_index + 1}/{args.games}: seed={game_seed} "
            f"black={black_spec.name} white={white_spec.name} "
            f"result={outcome_text} plies={result['plies_played']}"
        )

    print("Batch summary:")
    for spec in (engine_a, engine_b):
        stats = summary[spec.name]
        win_rate = stats["wins"] / max(1, args.games)
        print(
            f"{spec.name}: wins={stats['wins']} losses={stats['losses']} draws={stats['draws']} "
            f"win_rate={win_rate:.1%} black_games={stats['black_games']} white_games={stats['white_games']}"
        )
    return 0


def main() -> int:
    args = parse_args()
    print("Ukumog CLI")
    if args.mode == "engine-vs-engine":
        engine_a = _engine_spec_for_color(args, Color.BLACK, "Engine A")
        engine_b = _engine_spec_for_color(args, Color.WHITE, "Engine B")
        if args.games > 1:
            return _run_engine_batch(args, engine_a, engine_b)

        _play_engine_vs_engine_game(
            engine_a,
            engine_b,
            args,
            random.Random(args.seed),
            game_index=0,
            verbose=True,
        )
        return 0

    position = Position.initial()
    rng = random.Random(args.seed)

    if args.mode == "human-vs-engine":
        human_color = Color.BLACK if args.human == "black" else Color.WHITE
        engine_color = human_color.opponent
        model_path, ml_mode, depth, time_seconds, learned_weight, temperature, symmetry_ensemble = _engine_settings_for_color(
            args,
            engine_color,
        )
        engine_controller = _build_engine_controller(
            engine_color,
            model_path,
            ml_mode,
            depth,
            time_seconds,
            learned_weight,
            temperature,
            symmetry_ensemble,
        )
        time_text = "unlimited" if engine_controller.time_ms is None else f"{engine_controller.time_seconds:g}s"
        print(
            f"You are {'Black' if human_color is Color.BLACK else 'White'}. "
            f"Engine depth is {engine_controller.depth}. Move time limit is {time_text}."
        )
        print(_describe_engine(engine_controller))
        print("Enter moves as: row col")
        print("Type 'q' to quit.")
        controllers: dict[Color, EngineController] = {engine_color: engine_controller}
    else:
        raise ValueError(f"unsupported mode: {args.mode}")

    plies_played = 0
    while True:
        print()
        print(render_board(position))
        side_to_move = position.side_to_move
        actor = "You" if human_color is not None and side_to_move is human_color else controllers[side_to_move].label

        if position.empty_count == 0:
            print("Board is full. Draw-by-exhaustion handling is not defined, so stopping here.")
            return 0

        if human_color is not None and side_to_move is human_color:
            while True:
                raw = input("Your move: ")
                try:
                    parsed = parse_human_move(raw)
                    if parsed is None:
                        print("Exiting.")
                        return 0
                    move = coord_to_index(*parsed)
                    next_position, result = play_move(position, move)
                    print(announce_result("You", side_to_move, move, result))
                    position = next_position
                    break
                except ValueError as exc:
                    print(f"Invalid move: {exc}")
        else:
            controller = controllers[side_to_move]
            print(f"{controller.label} thinking...")
            move, search_result, sampled = _choose_engine_move(
                position,
                controller,
                plies_played,
                args.temperature_plies,
                args.sample_top_k,
                rng,
            )
            if move is None:
                print(f"{controller.label} found no legal move. Stopping.")
                return 0
            next_position, move_result = play_move(position, move)
            row, col = index_to_coord(move)
            _record_search_totals(controller, search_result)
            print(
                f"{controller.label} chooses ({row}, {col}) "
                f"[score={search_result.score}, depth={search_result.depth}, nodes={search_result.stats.nodes}]"
            )
            if args.time_trace:
                print(_format_time_trace(controller, search_result))
            if args.search_summary:
                print(search_result.format_summary())
            if sampled:
                best_row, best_col = index_to_coord(search_result.best_move)
                print(
                    f"{controller.label} sampled an opening move from its root shortlist; "
                    f"strict best was ({best_row}, {best_col})."
                )
            if search_result.stats.aborted:
                if search_result.stats.time_limit_abort:
                    print(
                        f"{controller.label} hit the move time limit and used the best move "
                        "from the last completed iteration."
                    )
                elif search_result.stats.node_limit_abort:
                    print(
                        f"{controller.label} hit its node limit and used the best move "
                        "from the last completed iteration."
                    )
            if args.stats_jsonl is not None:
                _append_stats_record(
                    args.stats_jsonl,
                    {
                        "event": "search",
                        "engine": controller.label,
                        "side_to_move": side_to_move.name,
                        "ply": plies_played,
                        "sampled": sampled,
                        "selected_move": move,
                        "search": search_result.to_dict(),
                    },
                )
            print(announce_result(controller.label, side_to_move, move, move_result))
            position = next_position
            result = move_result

        plies_played += 1
        if human_color is None and plies_played >= args.max_moves and result is MoveResult.NONTERMINAL:
            print()
            print(render_board(position))
            if args.time_trace:
                _print_match_time_totals(controllers)
            if args.stats_jsonl is not None:
                _append_stats_record(
                    args.stats_jsonl,
                    {
                        "event": "match_end",
                        "reason": "move_cap",
                        "plies_played": plies_played,
                    },
                )
            print(f"Reached the engine-vs-engine move cap ({args.max_moves}) without a terminal result.")
            return 0

        if result is MoveResult.WIN:
            winner = actor
            print()
            print(render_board(position))
            if args.time_trace:
                _print_match_time_totals(controllers)
            if args.stats_jsonl is not None:
                _append_stats_record(
                    args.stats_jsonl,
                    {
                        "event": "match_end",
                        "reason": "win",
                        "winner": winner,
                        "plies_played": plies_played,
                    },
                )
            print(f"{winner} wins.")
            return 0
        if result is MoveResult.LOSS:
            if human_color is not None:
                winner = "Engine" if actor == "You" else "You"
            else:
                winner = controllers[side_to_move.opponent].label
            print()
            print(render_board(position))
            if args.time_trace:
                _print_match_time_totals(controllers)
            if args.stats_jsonl is not None:
                _append_stats_record(
                    args.stats_jsonl,
                    {
                        "event": "match_end",
                        "reason": "loss",
                        "winner": winner,
                        "plies_played": plies_played,
                    },
                )
            print(f"{winner} wins.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
