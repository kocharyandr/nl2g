from typing import Literal

from pydantic import BaseModel, Field


class EditRouterDecision(BaseModel):
    target_stage: Literal["data_parsing", "image_generation"] = Field(
        ...,
        description="Pipeline to route the edit to.",
    )
    reason: str = Field(
        ...,
        description="Short explanation of why this route was selected.",
    )
