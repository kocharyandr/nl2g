from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class GuardRailsRequest(BaseModel):
    query: str = Field(..., min_length=1)


class Status(str, Enum):
    OK = "ok"
    REJECT = "reject"


class RejectType(str, Enum):
    SAFETY = "safety"
    ADVERSARIAL = "adversarial"
    HARMFUL = "harmful"
    INTENT = "intent"
    TONE = "tone"
    POLICY = "policy"


class GuardRailsResponse(BaseModel):
    status: Status
    type_reject: RejectType | None = None
    message: str | None = None
    safety: dict[str, Any] | None = None
    adversarial: list[dict[str, Any]] = []
    harmful: list[dict[str, Any]] = []
    intent: dict[str, Any] | None = None
    tone: dict[str, Any] | None = None
    policy: list[dict[str, Any]] = []


# --- Custom classification (zero-shot routing) ---


class ClassifyCustomRequest(BaseModel):
    """Generic zero-shot classification with arbitrary labels.

    Used by chart-agent for routing decisions (intent classification, edit-type
    classification, etc.) without spinning up a dedicated LLM call.
    """

    text: str = Field(..., min_length=1)
    task: str = Field(default="route", description="Task name (used in tracing).")
    labels: list[str] = Field(..., min_length=2)
    label_descriptions: dict[str, str] | None = Field(
        default=None,
        description="Optional natural-language description per label to improve zero-shot accuracy.",
    )
    multi_label: bool = Field(default=False)


class ClassifyCustomResponse(BaseModel):
    task: str
    label: str | None = Field(default=None, description="Top label (single-label mode).")
    labels: list[str] = Field(default_factory=list, description="Predicted labels (multi-label mode).")
    confidence: float = Field(default=0.0, description="Top-label confidence (0..1).")
    all_scores: dict[str, float] = Field(default_factory=dict, description="Score per label.")
    raw: dict[str, Any] | None = Field(default=None, description="Raw model output for debugging.")
