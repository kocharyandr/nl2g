from typing import Literal, List, Optional
from enum import Enum
from pydantic import BaseModel, Field, model_validator
from app.domain import StageName

class ActionName(str, Enum):
    ask_clarification = "ask_clarification"
    ask_user_input = "ask_user_input"
    route_to_stage = "route_to_stage"

class StageSpec(BaseModel):
    name: StageName = Field(
        ...,
        description="Unique stage name used by the workflow router.",
    )
    description: str = Field(
        ...,
        description="What this stage is responsible for.",
    )
    expected_input: str = Field(
        ...,
        description="What kind of input this stage expects.",
    )
    expected_output: str = Field(
        ...,
        description="What this stage should produce.",
    )
    routable_from_ingress: bool = Field(
        default=False,
        description="Whether ingress can route directly to this stage via task_router.",
    )
    downstream_stages: List[StageName] = Field(
        default_factory=list,
        description=(
            "Workflow stages that typically follow this stage. "
            "This is context metadata for ingress reasoning, not direct ingress targets."
        ),
    )


class ActionSpec(BaseModel):
    name: ActionName = Field(
        ...,
        description="Unique action name used by the ingress agent.",
    )
    description: str = Field(
        ...,
        description="What this action means and when it should be used.",
    )
    required_fields: List[str] = Field(
        ...,
        description="Fields that must be present in IngressDecision when this action is selected.",
    )


STAGES = [
    StageSpec(
        name=StageName.data_parsing,
        description="Extract and normalize data from user input, then generate a chart from this data.",
        expected_input="User text and/or images containing numbers, categories, trends, or raw data.",
        expected_output="Parsed structured data and a rendered chart artifact ready for user review.",
        routable_from_ingress=True,
        downstream_stages=[StageName.plot_rendering],
    ),
    StageSpec(
        name=StageName.image_generation,
        description=(
            "Image generation/edit flow using uploaded user image(s) and text prompt."
        ),
        expected_input=(
            "User text prompt plus one or more input images."
        ),
        expected_output=(
            "Generated/edited image artifact in base64 with metadata."
        ),
        routable_from_ingress=True,
    ),
]


ACTIONS = [
    ActionSpec(
        name=ActionName.ask_clarification,
        description=(
            "Use this when the user request is ambiguous, underspecified, or has multiple valid interpretations. "
            "The main issue is unclear intent."
        ),
        required_fields=["action", "reason"],
    ),
    # ActionSpec(
    #     name=ActionName.ask_user_input,
    #     description=(
    #         "Use this when the next step is clear, but the system cannot continue because required user-provided "
    #         "inputs are missing, such as data, files, parameters, or preferences."
    #     ),
    #     required_fields=["action", "reason"],
    # ),
    ActionSpec(
        name=ActionName.route_to_stage,
        description=(
            "Use this when the request is clear enough to continue and the task should be routed to a specific stage."
        ),
        required_fields=["action", "target_stage", "reason"],
    ),
]

class IngressDecision(BaseModel):
    action: ActionName = Field(
        ...,
        description="The next action selected by the ingress agent.",
    )
    target_stage: Optional[StageName] = Field(
        default=None,
        description="The target stage. Required only when action is 'route_to_stage'.",
    )
    reason: str = Field(
        ...,
        description="Short explanation of why this decision was made.",
    )

    @model_validator(mode="after")
    def validate_by_action(self) -> "IngressDecision":
        if self.action == "route_to_stage":
            if self.target_stage is None:
                raise ValueError(
                    "target_stage is required when action='route_to_stage'"
                )

        if self.action in {"ask_clarification", "ask_user_input"}:
            if self.target_stage is not None:
                raise ValueError(
                    f"target_stage must be omitted when action='{self.action}'"
                )

        return self
    
class IngressCatalog(BaseModel):
    stages: List[StageSpec] = Field(
        ...,
        description="Available workflow stages with explicit responsibilities and IO contracts.",
    )
    actions: List[ActionSpec] = Field(
        ...,
        description="Available ingress actions with explicit usage rules.",
    )


INGRESS_CATALOG = IngressCatalog(
    stages=STAGES,
    actions=ACTIONS,
)

class IngressContext(BaseModel):
    previous_stage: Optional[StageName] = Field(
        default=None,
        description="The previous stage.",
    )
    current_stage: Optional[StageName] = Field(
        default=None,
        description="The current stage.",
    )
    next_stage: Optional[StageName] = Field(
        default=None,
        description="The next stage.",
    )
    summary: Optional[str] = Field(
        default=None,
        description="A summary of the conversation history.",
    )
    is_editing_flow: bool = Field(
        default=False,
        description=(
            "True when user is editing previously built chart and request should be "
            "treated as update of existing context."
        ),
    )
    global_stages: List[StageName] = Field(
        default_factory=lambda: [stage for stage in StageName],
        description="All globally available stages in the workflow.",
    )
    ingress_routable_stages: List[StageName] = Field(
        default_factory=lambda: [
            stage.name for stage in STAGES if stage.routable_from_ingress
        ],
        description="Stages that ingress may route to directly via task_router.",
    )
    has_user_images: bool = Field(
        default=False,
        description="True if current user request contains at least one image.",
    )
    has_plot_image: bool = Field(
        default=False,
        description="True if there is an existing rendered plot image in artefacts.",
    )
