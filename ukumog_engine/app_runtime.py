from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import random

from . import Color, MoveResult, Position, SearchEngine, SearchResult, index_to_coord, play_move
from .ml import TorchPolicyValueEvaluator


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
    device: str
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
    device: str
    depth: int
    time_seconds: float
    learned_weight: float
    temperature: float
    symmetry_ensemble: bool


def announce_result(actor: str, color: Color, move: int, result: MoveResult) -> str:
    row, col = index_to_coord(move)
    stone = STONE_BY_COLOR[color]
    if result is MoveResult.WIN:
        return f"{actor} played {stone} at ({row}, {col}) and wins immediately."
    if result is MoveResult.LOSS:
        return f"{actor} played {stone} at ({row}, {col}) and loses immediately."
    return f"{actor} played {stone} at ({row}, {col})."


def build_engine_controller(
    color: Color,
    *,
    model_path: Path | None,
    ml_mode: str,
    depth: int,
    time_seconds: float,
    learned_weight: float,
    device: str,
    temperature: float,
    symmetry_ensemble: bool,
    label: str | None = None,
) -> EngineController:
    if not isinstance(depth, int) or isinstance(depth, bool):
        raise TypeError(f"engine depth must be an int, got {type(depth).__name__}")
    if depth <= 0:
        raise ValueError(f"engine depth must be positive, got {depth}")
    if not isinstance(time_seconds, (int, float)) or isinstance(time_seconds, bool):
        raise TypeError(f"engine time_seconds must be numeric, got {type(time_seconds).__name__}")
    time_seconds = float(time_seconds)

    learned_evaluator = (
        TorchPolicyValueEvaluator.from_checkpoint(
            model_path,
            device=device,
            symmetry_ensemble=symmetry_ensemble,
        )
        if model_path is not None
        else None
    )
    resolved_ml_mode = ml_mode
    if resolved_ml_mode == "auto" and learned_evaluator is not None:
        resolved_ml_mode = learned_evaluator.default_ml_mode
    effective_ml_mode = "quiet-value" if resolved_ml_mode == "auto" else resolved_ml_mode
    if label is None:
        if model_path is None:
            label = f"{color.name.title()} PureSearch"
        else:
            label = f"{color.name.title()} ML"

    if effective_ml_mode == "quiet-value":
        learned_policy_max_ply = -1
        learned_value_max_ply = None
        effective_weight = learned_weight
    elif effective_ml_mode == "full":
        learned_policy_max_ply = None
        learned_value_max_ply = None
        effective_weight = learned_weight
    elif effective_ml_mode == "policy-only":
        learned_policy_max_ply = None
        learned_value_max_ply = -1
        effective_weight = 0.0
    elif effective_ml_mode == "root-hybrid":
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
        ml_mode=resolved_ml_mode,
        device=device,
        temperature=temperature,
        symmetry_ensemble=symmetry_ensemble,
        engine=SearchEngine(
            learned_evaluator=learned_evaluator,
            learned_eval_weight=effective_weight,
            learned_policy_max_ply=learned_policy_max_ply,
            learned_value_max_ply=learned_value_max_ply,
        ),
    )


def engine_settings_for_color(
    args: object,
    color: Color,
) -> tuple[Path | None, str, str, int, float, float, float, bool]:
    prefix = "black" if color is Color.BLACK else "white"
    model_path = getattr(args, f"{prefix}_model") or getattr(args, "model")
    ml_mode = getattr(args, f"{prefix}_ml_mode") or getattr(args, "ml_mode")
    device = getattr(args, "device")
    depth = getattr(args, f"{prefix}_depth")
    if depth is None:
        depth = getattr(args, "depth")
    time_seconds = getattr(args, f"{prefix}_time")
    if time_seconds is None:
        time_seconds = getattr(args, "time")
    learned_weight = getattr(args, f"{prefix}_learned_weight")
    if learned_weight is None:
        learned_weight = getattr(args, "learned_weight")
    temperature = getattr(args, f"{prefix}_temperature")
    if temperature is None:
        temperature = getattr(args, "temperature")
    symmetry_ensemble = getattr(args, f"{prefix}_symmetry_ensemble") or getattr(args, "symmetry_ensemble")
    return model_path, ml_mode, device, depth, time_seconds, learned_weight, temperature, symmetry_ensemble


def engine_spec_for_color(
    args: object,
    color: Color,
    name: str,
) -> EngineSpec:
    model_path, ml_mode, device, depth, time_seconds, learned_weight, temperature, symmetry_ensemble = engine_settings_for_color(
        args,
        color,
    )
    return EngineSpec(
        name=name,
        model_path=model_path,
        ml_mode=ml_mode,
        device=device,
        depth=depth,
        time_seconds=time_seconds,
        learned_weight=learned_weight,
        temperature=temperature,
        symmetry_ensemble=symmetry_ensemble,
    )


def describe_engine(controller: EngineController) -> str:
    time_text = "unlimited" if controller.time_ms is None else f"{controller.time_seconds:g}s"
    if controller.model_path is None:
        model_text = "pure search"
    else:
        model_text = f"model={controller.model_path}"
    return (
        f"{controller.label}: depth={controller.depth}, time={time_text}, "
        f"ml_mode={controller.ml_mode}, learned_weight={controller.learned_weight:g}, "
        f"device={controller.device}, "
        f"temperature={controller.temperature:g}, "
        f"symmetry_ensemble={controller.symmetry_ensemble}, {model_text}"
    )


def describe_spec(spec: EngineSpec) -> str:
    time_text = "unlimited" if spec.time_seconds <= 0 else f"{spec.time_seconds:g}s"
    if spec.model_path is None:
        model_text = "pure search"
    else:
        model_text = f"model={spec.model_path}"
    return (
        f"{spec.name}: depth={spec.depth}, time={time_text}, "
        f"ml_mode={spec.ml_mode}, learned_weight={spec.learned_weight:g}, "
        f"device={spec.device}, "
        f"temperature={spec.temperature:g}, "
        f"symmetry_ensemble={spec.symmetry_ensemble}, {model_text}"
    )


def sample_root_move(
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


def append_stats_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def record_search_totals(controller: EngineController, search_result: SearchResult) -> None:
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


def format_time_trace(controller: EngineController, search_result: SearchResult) -> str:
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


def choose_engine_move(
    position: Position,
    controller: EngineController,
    plies_played: int,
    temperature_plies: int,
    sample_top_k: int,
    rng: random.Random,
) -> tuple[int | None, SearchResult, bool]:
    result = controller.engine.search(position, max_depth=controller.depth, max_time_ms=controller.time_ms)
    sampled = False
    move = result.best_move
    if controller.temperature > 0 and plies_played < temperature_plies and result.best_move is not None:
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
        sampled_move = sample_root_move(result.best_move, ordered_moves, controller.temperature, sample_top_k, rng)
        if sampled_move is not None:
            sampled = sampled_move != result.best_move
            move = sampled_move
    return move, result, sampled


def controller_from_spec(color: Color, spec: EngineSpec) -> EngineController:
    return build_engine_controller(
        color=color,
        model_path=spec.model_path,
        ml_mode=spec.ml_mode,
        device=spec.device,
        depth=spec.depth,
        time_seconds=spec.time_seconds,
        learned_weight=spec.learned_weight,
        temperature=spec.temperature,
        symmetry_ensemble=spec.symmetry_ensemble,
        label=f"{spec.name} ({color.name.title()})",
    )


def play_selected_move(position: Position, move: int) -> tuple[Position, MoveResult]:
    return play_move(position, move)
