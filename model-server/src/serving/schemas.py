from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


SUPPORTED_BOARD_SIZES = (9, 11, 13, 15)


class EngineState(BaseModel):
    model_config = ConfigDict(extra="allow")

    board: list[list[Any | None]]
    turn: str = Field(..., pattern="^[BW]$")
    result: dict[str, Any] | None = None
    last: list[int] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "EngineState":
        if not self.board:
            raise ValueError("board must contain at least one row")
        for row in self.board:
            if len(row) != len(self.board):
                raise ValueError("board must be square")
        if self.last is not None and len(self.last) != 2:
            raise ValueError("last must contain exactly two coordinates when provided")
        return self


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    boardSize: int


class EngineRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: EngineState
    config: EngineConfig
    timeBudgetMs: int = Field(..., gt=0, strict=True)
    maxDepth: int = Field(..., gt=0, strict=True)

    @model_validator(mode="after")
    def validate_board_shape_matches_config(self) -> "EngineRequest":
        board_size = int(self.config.boardSize)
        if len(self.state.board) != board_size:
            raise ValueError(f"board must contain {board_size} rows")
        for row in self.state.board:
            if len(row) != board_size:
                raise ValueError(f"each board row must contain {board_size} cells")
        return self


class EngineMovePayload(BaseModel):
    row: int
    col: int
    notation: str


class EngineAnalysisResponse(BaseModel):
    bestMove: EngineMovePayload | None
    score: int
    mate: int | None
    pv: list[EngineMovePayload]
    depth: int
    nodes: int
    timeMs: int
    engineVersion: str
    backend: str


class EngineRangeCapability(BaseModel):
    min: int
    max: int


class EngineCapabilities(BaseModel):
    supportedBoardSizes: list[int]
    timeBudgetMs: EngineRangeCapability
    maxDepth: EngineRangeCapability


class EngineHealthResponse(BaseModel):
    ok: bool
    backend: str
    engineVersion: str
    pythonVersion: str
    capabilities: EngineCapabilities
