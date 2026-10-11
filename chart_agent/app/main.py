import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_sessions
from app.api.routes_sessions import meta_router, router as sessions_router
from app.core.config import settings

_LOG_LEVEL_NAME = settings.log_level.upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
logger.setLevel(_LOG_LEVEL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await routes_sessions.registry.check_health()
        logger.info("LLM startup healthcheck passed")
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM startup healthcheck failed: %s", exc)
    yield


app = FastAPI(title="MVP Chart Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(meta_router)
