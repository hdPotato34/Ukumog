from __future__ import annotations

import logging
import sys

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from schemas import EngineAnalysisResponse, EngineHealthResponse, EngineRequest
from ukumog_adapter import BACKEND_NAME, EngineAdapterError, get_engine_capabilities, get_engine_version, run_engine_analysis

logger = logging.getLogger("ukumog-serving")

app = FastAPI(
    title="Ukumog Engine Service",
    version=get_engine_version(),
)


def error_payload(code: str, message: str) -> dict[str, str]:
    return {
        "type": "error",
        "code": code,
        "message": message,
    }


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    logger.warning("Request validation failed: %s", error)
    return JSONResponse(
        status_code=422,
        content=error_payload("invalid_request", "Request body validation failed."),
    )


@app.exception_handler(EngineAdapterError)
async def handle_adapter_error(_: Request, error: EngineAdapterError) -> JSONResponse:
    logger.warning("Engine adapter rejected request: %s", error.message)
    return JSONResponse(
        status_code=error.status_code,
        content=error_payload(error.code, error.message),
    )


@app.exception_handler(Exception)
async def handle_internal_error(_: Request, error: Exception) -> JSONResponse:
    logger.exception("Unhandled engine service error: %s", error)
    return JSONResponse(
        status_code=500,
        content=error_payload("internal_error", "The engine service hit an internal error."),
    )


@app.get("/health", response_model=EngineHealthResponse)
async def health() -> EngineHealthResponse:
    return EngineHealthResponse(
        ok=True,
        backend=BACKEND_NAME,
        engineVersion=get_engine_version(),
        pythonVersion=sys.version.split()[0],
        capabilities=get_engine_capabilities(),
    )


@app.post("/search", response_model=EngineAnalysisResponse)
async def search(request: EngineRequest) -> EngineAnalysisResponse:
    return run_engine_analysis(request)


@app.post("/analyze", response_model=EngineAnalysisResponse)
async def analyze(request: EngineRequest) -> EngineAnalysisResponse:
    return run_engine_analysis(request)
