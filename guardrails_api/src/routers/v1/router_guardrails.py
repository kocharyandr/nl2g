from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from src.schemas.guardrails import (
    ClassifyCustomRequest,
    ClassifyCustomResponse,
    GuardRailsRequest,
    GuardRailsResponse,
)

if TYPE_CHECKING:
    from src.services.guardrails import GuardRailsService

router_guardrails = APIRouter(prefix="/classify", tags=["Guard"])


@router_guardrails.post("", response_model=None)
async def classify(
    body: GuardRailsRequest,
    request: Request,
) -> GuardRailsResponse:
    service: GuardRailsService = request.app.state.guardrails
    return await service.classify(body.query)


@router_guardrails.post("/custom", response_model=ClassifyCustomResponse)
async def classify_custom(
    body: ClassifyCustomRequest,
    request: Request,
) -> ClassifyCustomResponse:
    """Zero-shot classification with caller-supplied labels.

    Used for routing decisions in chart-agent (intent, edit-type, etc.)
    so a small CPU model replaces an LLM call for simple classification.
    """
    service: GuardRailsService = request.app.state.guardrails
    result = await service.classify_custom(
        text=body.text,
        task=body.task,
        labels=body.labels,
        label_descriptions=body.label_descriptions,
        multi_label=body.multi_label,
    )
    return ClassifyCustomResponse(**result)
