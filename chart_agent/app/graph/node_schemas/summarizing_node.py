from typing import Literal, List, Optional
from enum import Enum
from pydantic import BaseModel, Field


class SummaryAnswer(BaseModel):
    current_summary: str = Field(
        ...,
        description="The answer to the user's message.",
    )
