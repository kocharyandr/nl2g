from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.domain import StageName


class InteractionAction(str, Enum):
    route_to_stage = "route_to_stage"
    respond = "respond"
    ask_clarification = "ask_clarification"


class InteractionDecision(BaseModel):
    action: InteractionAction = Field(
        ...,
        description="Next action produced by interaction node.",
    )
    target_stage: Optional[StageName] = Field(
        default=None,
        description="Required only when action is route_to_stage.",
    )
    assistant_message: str = Field(
        default="",
        description="User-facing text for respond/ask_clarification actions.",
    )
    reason: str = Field(
        ...,
        description="Short explanation of why this action was selected.",
    )

    @model_validator(mode="after")
    def validate_by_action(self) -> "InteractionDecision":
        if self.action == InteractionAction.route_to_stage and self.target_stage is None:
            raise ValueError("target_stage is required when action='route_to_stage'")

        if self.action != InteractionAction.route_to_stage and self.target_stage is not None:
            raise ValueError("target_stage must be omitted unless action='route_to_stage'")

        if self.action in {InteractionAction.respond, InteractionAction.ask_clarification}:
            if not (self.assistant_message or "").strip():
                raise ValueError("assistant_message is required for respond/ask_clarification actions")

        return self
