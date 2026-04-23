from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import (
    BOARD_SIZE,
    __version__,
    Color,
    MoveResult,
    Position,
    SearchResult,
    analyze_tactics,
    coord_to_index,
    index_to_coord,
    play_move,
)
from ..app_runtime import build_engine_controller


DEFAULT_ANALYZE_DEPTH = 4
DEFAULT_ANALYZE_TIME_MS = 1500
VALID_ML_MODES = {"auto", "quiet-value", "full", "policy-only", "root-policy", "root-hybrid"}
VALID_DEVICES = {"cpu", "cuda", "auto"}


class RequestError(ValueError):
    """Raised when a bridge payload is invalid."""


@dataclass(frozen=True, slots=True)
class EngineOptions:
    depth: int
    time_ms: int | None
    analyze_root: bool
    include_move_maps: bool
    model_path: Path | None
    ml_mode: str
    learned_weight: float
    device: str
    symmetry_ensemble: bool


def _expect_mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RequestError(f"{label} must be an object")
    return value


def _expect_bool(value: object, *, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise RequestError(f"{label} must be a boolean")
    return value


def _expect_number(value: object, *, label: str, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        kind = "integer" if integer else "number"
        raise RequestError(f"{label} must be a {kind}")
    if integer:
        if int(value) != value:
            raise RequestError(f"{label} must be an integer")
        return int(value)
    return float(value)


def _parse_color(value: object, *, default: Color | None = None) -> Color:
    if value is None:
        if default is None:
            raise RequestError("side_to_move is required")
        return default
    if not isinstance(value, str):
        raise RequestError("side_to_move must be 'black' or 'white'")
    normalized = value.strip().lower()
    if normalized == "black":
        return Color.BLACK
    if normalized == "white":
        return Color.WHITE
    raise RequestError("side_to_move must be 'black' or 'white'")


def _rows_from_position(position: Position) -> list[str]:
    rows: list[str] = []
    for row in range(BOARD_SIZE):
        cells: list[str] = []
        for col in range(BOARD_SIZE):
            move = coord_to_index(row, col)
            if position.black_bits & (1 << move):
                cells.append("B")
            elif position.white_bits & (1 << move):
                cells.append("W")
            else:
                cells.append(".")
        rows.append("".join(cells))
    return rows


def _move_from_payload(payload: object, *, label: str = "move") -> int:
    if isinstance(payload, int) and not isinstance(payload, bool):
        move = payload
        if 0 <= move < BOARD_SIZE * BOARD_SIZE:
            return move
        raise RequestError(f"{label} index must be between 0 and {BOARD_SIZE * BOARD_SIZE - 1}")

    move_map = _expect_mapping(payload, label=label)
    row = move_map.get("row")
    col = move_map.get("col")
    if row is None or col is None:
        raise RequestError(f"{label} must include row and col")
    row_int = _expect_number(row, label=f"{label}.row", integer=True)
    col_int = _expect_number(col, label=f"{label}.col", integer=True)
    try:
        return coord_to_index(row_int, col_int)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def move_to_payload(move: int | None) -> dict[str, int] | None:
    if move is None:
        return None
    row, col = index_to_coord(move)
    return {"index": move, "row": row, "col": col}


def position_to_payload(position: Position) -> dict[str, object]:
    return {
        "rows": _rows_from_position(position),
        "side_to_move": position.side_to_move.name.lower(),
        "empty_count": position.empty_count,
        "occupied_count": BOARD_SIZE * BOARD_SIZE - position.empty_count,
    }


def position_from_payload(payload: object) -> Position:
    mapping = _expect_mapping(payload, label="position")
    rows_value = mapping.get("rows")
    moves_value = mapping.get("moves")
    side_to_move = mapping.get("side_to_move")

    if rows_value is not None and moves_value is not None:
        raise RequestError("position must provide either rows or moves, not both")

    if rows_value is not None:
        if not isinstance(rows_value, list) or not all(isinstance(row, str) for row in rows_value):
            raise RequestError("position.rows must be a list of board strings")
        try:
            return Position.from_rows(rows_value, side_to_move=_parse_color(side_to_move, default=Color.BLACK))
        except ValueError as exc:
            raise RequestError(str(exc)) from exc

    if moves_value is not None:
        if not isinstance(moves_value, list):
            raise RequestError("position.moves must be a list")
        position = Position.initial()
        for index, move_payload in enumerate(moves_value):
            move = _move_from_payload(move_payload, label=f"position.moves[{index}]")
            try:
                position, result = play_move(position, move)
            except ValueError as exc:
                raise RequestError(str(exc)) from exc
            if result is not MoveResult.NONTERMINAL:
                raise RequestError(
                    f"position.moves contains terminal move at index {index}; provide explicit rows for terminal states"
                )
        if side_to_move is not None:
            parsed_side = _parse_color(side_to_move)
            if parsed_side is not position.side_to_move:
                raise RequestError("position.side_to_move does not match the supplied move history")
        return position

    raise RequestError("position must include rows or moves")


def _parse_engine_options(payload: object | None) -> EngineOptions:
    mapping = {} if payload is None else _expect_mapping(payload, label="engine")
    depth = _expect_number(mapping.get("depth", DEFAULT_ANALYZE_DEPTH), label="engine.depth", integer=True)
    if depth <= 0:
        raise RequestError("engine.depth must be positive")

    time_ms_raw = mapping.get("time_ms", DEFAULT_ANALYZE_TIME_MS)
    time_ms_value = _expect_number(time_ms_raw, label="engine.time_ms", integer=True)
    if time_ms_value < 0:
        raise RequestError("engine.time_ms cannot be negative")
    time_ms = None if time_ms_value == 0 else time_ms_value

    ml_mode = mapping.get("ml_mode", "auto")
    if not isinstance(ml_mode, str) or ml_mode not in VALID_ML_MODES:
        raise RequestError(f"engine.ml_mode must be one of {sorted(VALID_ML_MODES)}")

    device = mapping.get("device", "cpu")
    if not isinstance(device, str) or device not in VALID_DEVICES:
        raise RequestError(f"engine.device must be one of {sorted(VALID_DEVICES)}")

    learned_weight = float(_expect_number(mapping.get("learned_weight", 0.10), label="engine.learned_weight"))
    model_path_value = mapping.get("model_path")
    if model_path_value is None:
        model_path = None
    else:
        if not isinstance(model_path_value, str) or not model_path_value.strip():
            raise RequestError("engine.model_path must be a non-empty string when provided")
        model_path = Path(model_path_value)

    return EngineOptions(
        depth=depth,
        time_ms=time_ms,
        analyze_root=_expect_bool(mapping.get("analyze_root"), label="engine.analyze_root", default=True),
        include_move_maps=_expect_bool(mapping.get("include_move_maps"), label="engine.include_move_maps", default=False),
        model_path=model_path,
        ml_mode=ml_mode,
        learned_weight=learned_weight,
        device=device,
        symmetry_ensemble=_expect_bool(
            mapping.get("symmetry_ensemble"),
            label="engine.symmetry_ensemble",
            default=False,
        ),
    )


def _move_list_payload(moves: tuple[int, ...] | list[int]) -> list[dict[str, int]]:
    return [move_to_payload(move) for move in moves if move is not None]


def _tactics_payload(position: Position, *, include_move_maps: bool) -> dict[str, object]:
    snapshot = analyze_tactics(position, include_move_maps=include_move_maps)
    payload: dict[str, object] = {
        "candidate_moves": _move_list_payload(snapshot.candidate_moves),
        "safe_moves": _move_list_payload(snapshot.safe_moves),
        "winning_moves": _move_list_payload(snapshot.winning_moves),
        "poison_moves": _move_list_payload(snapshot.poison_moves),
        "forced_blocks": _move_list_payload(snapshot.forced_blocks),
        "safe_threats": _move_list_payload(snapshot.safe_threats),
        "double_threats": _move_list_payload(snapshot.double_threats),
        "opponent_winning_moves": _move_list_payload(snapshot.opponent_winning_moves),
        "restricted_pressure": snapshot.restricted_pressure,
        "opponent_restricted_pressure": snapshot.opponent_restricted_pressure,
        "critical_restricted_lines": snapshot.critical_restricted_lines,
        "opponent_critical_restricted_lines": snapshot.opponent_critical_restricted_lines,
        "critical_restricted_builds": _move_list_payload(snapshot.critical_restricted_builds),
        "critical_restricted_responses": _move_list_payload(snapshot.critical_restricted_responses),
    }
    if include_move_maps:
        payload["future_wins_by_move"] = {
            str(move): _move_list_payload(next_moves) for move, next_moves in snapshot.future_wins_by_move.items()
        }
        payload["opponent_wins_after_move"] = {
            str(move): _move_list_payload(next_moves) for move, next_moves in snapshot.opponent_wins_after_move.items()
        }
        payload["restricted_move_pressure"] = {
            str(move): score for move, score in snapshot.restricted_move_pressure.items()
        }
    return payload


def _search_result_payload(result: SearchResult) -> dict[str, object]:
    return {
        "best_move": move_to_payload(result.best_move),
        "score": result.score,
        "depth": result.depth,
        "principal_variation": _move_list_payload(result.principal_variation),
        "root_move_scores": [
            {
                "move": move_to_payload(root_score.move),
                "score": root_score.score,
            }
            for root_score in result.root_move_scores
        ],
        "stats": result.stats.to_dict(),
    }


def _engine_info() -> dict[str, object]:
    return {
        "name": "ukumog-engine",
        "version": __version__,
        "board_size": BOARD_SIZE,
        "rules": {
            "win": "make a valid arithmetic five",
            "loss": "make a valid arithmetic four without also making a five",
        },
        "supported_commands": ["engine_info", "analyze", "play_move"],
    }


def _analyze(payload: dict[str, Any]) -> dict[str, object]:
    position = position_from_payload(payload.get("position"))
    options = _parse_engine_options(payload.get("engine"))
    controller = build_engine_controller(
        color=position.side_to_move,
        model_path=options.model_path,
        ml_mode=options.ml_mode,
        depth=options.depth,
        time_seconds=0.0 if options.time_ms is None else options.time_ms / 1000.0,
        learned_weight=options.learned_weight,
        device=options.device,
        temperature=0.0,
        symmetry_ensemble=options.symmetry_ensemble,
        label="Bridge",
    )
    search_result = controller.engine.search(
        position,
        max_depth=controller.depth,
        max_time_ms=options.time_ms,
        analyze_root=options.analyze_root,
    )
    return {
        "command": "analyze",
        "position": position_to_payload(position),
        "engine": {
            "depth": options.depth,
            "time_ms": options.time_ms or 0,
            "ml_mode": controller.ml_mode,
            "device": options.device,
            "model_path": None if options.model_path is None else str(options.model_path),
            "symmetry_ensemble": options.symmetry_ensemble,
        },
        "analysis": _search_result_payload(search_result),
        "tactics": _tactics_payload(position, include_move_maps=options.include_move_maps),
    }


def _play_move(payload: dict[str, Any]) -> dict[str, object]:
    position = position_from_payload(payload.get("position"))
    move = _move_from_payload(payload.get("move"))
    next_position, result = play_move(position, move)
    return {
        "command": "play_move",
        "position_before": position_to_payload(position),
        "move": move_to_payload(move),
        "result": result.name.lower(),
        "position_after": position_to_payload(next_position),
    }


def handle_request(payload: object) -> dict[str, object]:
    mapping = _expect_mapping(payload, label="request")
    command = mapping.get("command", "analyze")
    if not isinstance(command, str):
        raise RequestError("command must be a string")
    normalized = command.strip().lower()
    if normalized == "engine_info":
        body = _engine_info()
    elif normalized == "analyze":
        body = _analyze(mapping)
    elif normalized == "play_move":
        body = _play_move(mapping)
    else:
        raise RequestError("unsupported command; expected engine_info, analyze, or play_move")
    return {"ok": True, **body}
