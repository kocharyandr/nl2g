from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from executor import execute_chart_code, validate_code_ast

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chart Code Executor", version="1.0.0")


class ExecuteRequest(BaseModel):
    code: str
    data: dict[str, Any] = Field(default_factory=dict)
    timeout: float = Field(default=10.0, ge=1.0, le=60.0)


class ExecuteResponse(BaseModel):
    image_b64: str
    mime_type: str = "image/png"


class ErrorResponse(BaseModel):
    error: str
    error_type: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/execute", response_model=ExecuteResponse, responses={400: {"model": ErrorResponse}})
def execute(req: ExecuteRequest):
    logger.info("execute request code_len=%d", len(req.code))
    try:
        validate_code_ast(req.code)
    except ValueError as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": str(exc), "error_type": "ValidationError"})

    try:
        image_b64 = execute_chart_code(req.code, req.data, timeout=req.timeout)
    except TimeoutError as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": str(exc), "error_type": "TimeoutError"})
    except Exception as exc:  # noqa: BLE001
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": str(exc), "error_type": type(exc).__name__})

    return ExecuteResponse(image_b64=image_b64)
