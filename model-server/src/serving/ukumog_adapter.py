from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Iterable

from schemas import EngineAnalysisResponse, EngineMovePayload, EngineRequest, SUPPORTED_BOARD_SIZE
from ukumog_engine import Color, Position, SearchEngine, SearchResult, coord_to_index, index_to_coord

BACKEND_NAME = "ukumog"


class EngineAdapterError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def get_engine_version() -> str:
    for dist_name in ("ukumog-engine", "ukumog_engine"):
        try:
            return version(dist_name)
        except PackageNotFoundError:
            continue
    return "0.1.0"


def to_column_label(col: int) -> str:
    index = int(col)
    label = ""
    while index >= 0:
        label = chr(65 + (index % 26)) + label
        index = index // 26 - 1
    return label


def move_to_notation(row: int, col: int) -> str:
    return f"{to_column_label(col)}{row + 1}"


def _side_to_move(turn: str) -> Color:
    return Color.BLACK if turn == "B" else Color.WHITE


def _cell_to_bits(row: int, col: int, cell: object, black_bits: int, white_bits: int) -> tuple[int, int]:
    if cell is None:
        return black_bits, white_bits

    if cell == "B":
        return black_bits | (1 << coord_to_index(row, col, SUPPORTED_BOARD_SIZE)), white_bits

    if cell == "W":
        return black_bits, white_bits | (1 << coord_to_index(row, col, SUPPORTED_BOARD_SIZE))

    raise EngineAdapterError(400, "invalid_position", f"Unsupported board cell value at ({row}, {col}).")


def frontend_state_to_position(request: EngineRequest) -> Position:
    if request.config.boardSize != SUPPORTED_BOARD_SIZE:
        raise EngineAdapterError(
            400,
            "unsupported_board_size",
            f"Ukumog engine currently supports {SUPPORTED_BOARD_SIZE}x{SUPPORTED_BOARD_SIZE} only.",
        )

    if request.state.result is not None:
        raise EngineAdapterError(400, "terminal_position", "Cannot search a terminal position.")

    black_bits = 0
    white_bits = 0

    for row_index, row in enumerate(request.state.board):
        for col_index, cell in enumerate(row):
            black_bits, white_bits = _cell_to_bits(row_index, col_index, cell, black_bits, white_bits)

    try:
        position = Position(
            black_bits=black_bits,
            white_bits=white_bits,
            side_to_move=_side_to_move(request.state.turn),
        )
    except ValueError as error:
        raise EngineAdapterError(400, "invalid_position", str(error)) from error

    if position.empty_count <= 0:
        raise EngineAdapterError(400, "invalid_position", "Cannot search a full board position.")

    return position


def _to_move_payload(move_index: int) -> EngineMovePayload:
    row, col = index_to_coord(move_index, SUPPORTED_BOARD_SIZE)
    return EngineMovePayload(
        row=row,
        col=col,
        notation=move_to_notation(row, col),
    )


def _pv_to_payloads(principal_variation: Iterable[int]) -> list[EngineMovePayload]:
    return [_to_move_payload(move_index) for move_index in principal_variation]


def search_result_to_response(result: SearchResult) -> EngineAnalysisResponse:
    best_move = _to_move_payload(result.best_move) if result.best_move is not None else None
    nodes = max(0, int(result.stats.total_nodes))
    time_ms = max(0, round(result.stats.elapsed_seconds * 1000))

    return EngineAnalysisResponse(
        bestMove=best_move,
        score=int(result.score),
        mate=None,
        pv=_pv_to_payloads(result.principal_variation),
        depth=int(result.depth),
        nodes=nodes,
        timeMs=time_ms,
        engineVersion=get_engine_version(),
        backend=BACKEND_NAME,
    )


def run_engine_analysis(request: EngineRequest) -> EngineAnalysisResponse:
    position = frontend_state_to_position(request)
    engine = SearchEngine()
    result = engine.search(
        position,
        max_depth=request.maxDepth,
        max_time_ms=request.timeBudgetMs,
    )
    return search_result_to_response(result)
