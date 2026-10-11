from typing import Literal

from pydantic import BaseModel, Field


class ImageEditRouterDecision(BaseModel):
    target: Literal["image_prompt_enhancer", "image_input_selector"] = Field(
        ...,
        description=(
            "image_prompt_enhancer — keep existing source image, re-run with updated prompt; "
            "image_input_selector — new source image is needed before generating."
        ),
    )
    reason: str = Field(
        ...,
        description="Short explanation of why this route was selected.",
    )
