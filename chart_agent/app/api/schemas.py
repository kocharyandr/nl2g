from collections import deque
from enum import Enum
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.core.config import settings
from app.domain import StageName


class ChartType(str, Enum):
    bar = "bar"
    line = "line"
    stacked_bar = "stacked_bar"
    pie = "pie"
    doughnut = "doughnut"
    scatter = "scatter"
    area = "area"
    histogram = "histogram"
    heatmap = "heatmap"
    box = "box"


class DecisionValue(str, Enum):
    approve = "approve"
    edit = "edit"
    cancel = "cancel"


class UserActionType(str, Enum):
    message = "message"
    decision = "decision"


class IntentType(str, Enum):
    build_chart = "build_chart"
    edit_chart = "edit_chart"
    generate_image = "generate_image"
    ask_question = "ask_question"
    clarify = "clarify"


class DataFieldRole(str, Enum):
    category = "category"
    value = "value"
    series = "series"
    time = "time"
    text = "text"
    unknown = "unknown"


class AnalyticalGoal(str, Enum):
    comparison = "comparison"
    trend = "trend"
    composition = "composition"
    distribution = "distribution"
    relationship = "relationship"
    unknown = "unknown"


class TableAggregation(str, Enum):
    none = "none"
    sum = "sum"
    avg = "avg"
    count = "count"
    min = "min"
    max = "max"
    median = "median"


class TimeGranularity(str, Enum):
    none = "none"
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"


AvailableExternalData = Literal["images"]


class MessageAction(BaseModel):
    content: str = ""
    images_base64: list[str] = Field(default_factory=list)


class DecisionAction(BaseModel):
    content: str = ""
    images_base64: list[str] = Field(default_factory=list)
    value: DecisionValue


class UserAction(BaseModel):
    type: UserActionType
    content: str = ""
    images_base64: list[str] = Field(default_factory=list)
    value: DecisionValue | None = Field(default=None)
    auto_validate_enabled: bool | None = Field(default=None)
    generation_seed: int | None = Field(default=None)
    csv_data: str | None = Field(default=None, description="Raw CSV or TSV text for tabular input.")
    use_sql_source: bool | None = Field(
        default=None,
        description="Take data from the database via sql_agent instead of text/CSV.",
    )
    sql_datasource_id: str | None = Field(
        default=None,
        description="Which registered database to query; empty for the service default.",
    )
    no_text_mode: bool | None = Field(default=None)


class UserIntent(BaseModel):
    intent_type: IntentType = Field(default=IntentType.build_chart)
    is_editing_existing_result: bool = Field(default=False)
    source_modalities: list[str] = Field(default_factory=list)
    user_goal: str = Field(default="")


class DataFieldSpec(BaseModel):
    name: str = Field(default="")
    role: DataFieldRole = Field(default=DataFieldRole.unknown)
    inferred_type: str = Field(default="unknown")
    unique_count: int | None = Field(default=None)
    non_empty_count: int | None = Field(default=None)
    sample_values: list[str] = Field(default_factory=list)


class DataPoint(BaseModel):
    label: str | None = Field(default=None)
    x: float | str | None = Field(default=None)
    y: float | None = Field(default=None)
    series: str | None = Field(default=None)


class DatasetSpec(BaseModel):
    source_type: str = Field(default="text")
    raw_representation: str = Field(default="")
    fields: list[DataFieldSpec] = Field(default_factory=list)
    points: list[DataPoint] = Field(default_factory=list)
    row_count_estimate: int | None = Field(default=None)
    preview_rows: list[dict[str, str | float | int | None]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ChartIntent(BaseModel):
    analytical_goal: AnalyticalGoal = Field(default=AnalyticalGoal.unknown)
    recommended_chart_type: ChartType | None = Field(default=None)
    title_hint: str = Field(default="")
    x_label: str = Field(default="")
    y_label: str = Field(default="")
    series_label: str = Field(default="")
    reasoning: str = Field(default="")


class TableAnalysisPlan(BaseModel):
    chart_type: ChartType | None = Field(default=None)
    x_column: str | None = Field(default=None)
    y_columns: list[str] = Field(default_factory=list)
    series_column: str | None = Field(default=None)
    aggregation: TableAggregation = Field(default=TableAggregation.none)
    time_granularity: TimeGranularity = Field(default=TimeGranularity.none)
    title_hint: str = Field(default="")
    needs_clarification: bool = Field(default=False)
    clarification_question: str = Field(default="")
    reasoning: str = Field(default="")


class TableCodeSpec(BaseModel):
    chart_type: ChartType | None = Field(default=None)
    title_hint: str = Field(default="")
    x_col: str | None = Field(default=None)
    y_col: str = Field(default="y")
    series_col: str | None = Field(default=None)
    x_label: str = Field(default="", description="Original column name used as x axis (before renaming to 'x')")
    y_label: str = Field(default="", description="Original column name used as y axis (before renaming to 'y')")
    code: str = Field(default="")
    reasoning: str = Field(default="")
    needs_clarification: bool = Field(default=False)
    clarification_question: str = Field(default="")


class ChartCodeOutput(BaseModel):
    intent: str = Field(default="")
    chart_type: str = Field(default="bar")
    title: str = Field(default="")
    x_label: str = Field(default="")
    y_label: str = Field(default="")
    reasoning: str = Field(default="")
    code: str = Field(default="")


class DataValidationReport(BaseModel):
    is_valid: bool = Field(default=False)
    reason: str = Field(default="")
    correction_hint: str = Field(default="")


class DataUnderstandingResult(BaseModel):
    dataset_spec: DatasetSpec = Field(default_factory=DatasetSpec)
    chart_intent: ChartIntent = Field(default_factory=ChartIntent)
    table_plan: TableAnalysisPlan | None = Field(default=None)


class SQLSourceInfo(BaseModel):
    """Provenance for data fetched from the database.

    Shown to the user, not just logged: a chart built on database rows is
    uncheckable unless the query that produced it is visible.
    """

    used: bool = Field(default=False)
    sql: str = Field(default="")
    explanation: str = Field(default="")
    row_count: int = Field(default=0)
    truncated: bool = Field(default=False)


class DataArtefacts(BaseModel):
    user_intent: UserIntent = Field(default_factory=UserIntent)
    understanding: DataUnderstandingResult = Field(default_factory=DataUnderstandingResult)
    validation: DataValidationReport = Field(default_factory=DataValidationReport)
    sql_source: SQLSourceInfo = Field(default_factory=SQLSourceInfo)


class EvaluationReport(BaseModel):
    status: str = Field(default="not_evaluated")
    score: float | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)
    recommendation: str = Field(default="")


class PlotArtefacts(BaseModel):
    code: str = Field(default="")
    image_base64: str | None = Field(default=None)
    mime_type: str = Field(default="image/png")
    approved: bool = Field(default=False)
    chart_attempt: int = Field(default=0)
    evaluation: EvaluationReport = Field(default_factory=EvaluationReport)



class ImageIterationMeta(BaseModel):
    iteration: int
    seed: int | None = None
    prompt: str = ""
    model: str = ""
    mime_type: str = "image/png"
    score: float | None = None
    passed: bool = False
    errors_summary: str = ""


class ImageArtefacts(BaseModel):
    # Input selection
    input_images_base64: list[str] = Field(default_factory=list)
    input_source: str = ""

    # Prompts
    source_prompt: str = ""
    enhanced_prompt: str = ""
    validation_feedback: str = ""

    # Current iteration image (ephemeral: set by diffusion, cleared by validation)
    current_image_b64: str | None = None

    # Best image across all iterations
    image_base64: str | None = None
    best_score: float = -1.0
    mime_type: str = "image/png"
    mocked: bool = False

    # Per-iteration metadata without image bytes
    iterations: list[ImageIterationMeta] = Field(default_factory=list)

    # Accepted image — survives between turns
    last_accepted_image_base64: str | None = None

    # Routing flag
    need_next_iteration: bool = False


class Artefacts(BaseModel):
    data: DataArtefacts = Field(default_factory=DataArtefacts)
    plot: PlotArtefacts = Field(default_factory=PlotArtefacts)
    image: ImageArtefacts = Field(default_factory=ImageArtefacts)


class Summary(BaseModel):
    HISTORY_MAX_LEN: ClassVar[int] = settings.summary_history_max_len_safe

    current_summary: str = ""
    last_messeges_for_sumup: deque[str] = Field(
        default_factory=lambda: deque(maxlen=Summary.HISTORY_MAX_LEN),
    )

    @field_validator("last_messeges_for_sumup", mode="before")
    @classmethod
    def _normalize_history(cls, value):
        if value is None:
            return deque(maxlen=cls.HISTORY_MAX_LEN)
        if isinstance(value, deque):
            return deque(value, maxlen=cls.HISTORY_MAX_LEN)
        if isinstance(value, list):
            return deque(value, maxlen=cls.HISTORY_MAX_LEN)
        raise TypeError("last_messeges_for_sumup must be list, deque, or None")

    @field_serializer("last_messeges_for_sumup")
    def _serialize_history(self, value: deque[str]) -> list[str]:
        return list(value)

    def add_message_for_sumup(self, message: str) -> None:
        self.last_messeges_for_sumup.append(message)

    def clear_last_messeges_state(self) -> None:
        self.last_messeges_for_sumup.clear()

    def clear_current_summary_state(self) -> None:
        self.current_summary = ""


class RollbackRequest(BaseModel):
    target_stage: StageName


class SessionUIData(BaseModel):
    data: dict | None = None
    chart: dict | None = None
    image: dict | None = None


class ActiveBranch(str, Enum):
    chart = "chart"
    image = "image"
    none = "none"


class SessionResponse(BaseModel):
    session_id: str
    current_stage: StageName
    ephemeral_status: str | None = None
    assistant_message: str | None = None
    artefacts: Artefacts | None = None

    # UI control flags — always present so frontend doesn't need to infer them
    awaiting_user_approval: bool = False
    active_branch: ActiveBranch = ActiveBranch.none
    show_approve_cancel: bool = False  # True when approve/cancel buttons should be visible
