import logging

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="SQL Agent",
    description=(
        "NL2SQL data source for chart_agent. Answers a natural-language question "
        "with a raw result table (Variant A): no aggregation, no chart decisions."
    ),
    version="0.1.0",
)
app.include_router(router)
