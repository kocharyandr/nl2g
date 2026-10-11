from typing import Literal

from pydantic import BaseModel, Field


class ChartEditRouterDecision(BaseModel):
    target: Literal["plot_creator", "re_extract"] = Field(
        ...,
        description=(
            "plot_creator — edit is about appearance/style, existing data is reused; "
            "re_extract — edit changes the underlying data, chart type, aggregation, or filtering "
            "(routing layer picks the correct extractor based on whether CSV is available)."
        ),
    )
    reason: str = Field(
        ...,
        description="Short explanation of why this route was selected.",
    )
