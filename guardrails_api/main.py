from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from core.config import settings
from core.logger import logger
from src.routers.base_router import base_router
from src.services.guardrails import GuardRailsService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not torch.cuda.is_available():
        logger.warning(
            "CUDA unavailable. Running on CPU — inference will be significantly slower."
        )
    logger.info(f"Initializing GuardRailsService on {settings.DEVICE}...")
    app.state.guardrails = GuardRailsService()
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.PROJECT_VERSION,
    lifespan=lifespan,
)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(base_router)


@app.exception_handler(Exception)
async def unexpected_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unexpected error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "message": "An unexpected error occurred. Please try again later.",
            "detail": str(exc),
        },
    )


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "model": settings.MODEL_NAME}


instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=False,
)
instrumentator.instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")
