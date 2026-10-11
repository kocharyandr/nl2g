from fastapi import APIRouter

from core.config import settings
from src.routers.v1.router_guardrails import router_guardrails

base_router = APIRouter(prefix=settings.API_VERSION)

base_router.include_router(router_guardrails)
