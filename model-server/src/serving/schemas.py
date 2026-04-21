from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


SUPPORTED_BOARD_SIZE = 11


class EngineState(BaseModel):
    model_config = ConfigDict(extra="allow")

    board: list[list[Any | None]]
    turn: str = Field(..., pattern="^[BW]$")
    result: dict[str, Any] | None = None
    last: list[int] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "EngineState":
        if len(self.board) != SUPPORTED_BOARD_SIZE:
            raise ValueError(f"board must contain {SUPPORTED_BOARD_SIZE} rows")
        for row in self.board:
            if len(row) != SUPPORTED_BOARD_SIZE:
                raise ValueError(f"each board row must contain {SUPPORTED_BOARD_SIZE} cells")
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


class EngineHealthResponse(BaseModel):
    ok: bool
    backend: str
    engineVersion: str
    pythonVersion: str
