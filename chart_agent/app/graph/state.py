from typing import Optional

from pydantic import BaseModel, Field

from app.graph.node_schemas.interaction_node import InteractionDecision
from app.domain import StageName
from app.api.schemas import (
    Artefacts,
    DecisionValue,
    UserActionType,
    Summary,
)
from app.core.config import settings

class AppState(BaseModel):
    session_id: str

    interaction_decision: InteractionDecision | None = None

    previous_stage: StageName | None = None
    current_stage: StageName = "ingress"
    next_stage: StageName | None = None
    awaiting_user_approval: bool = False

    user_input: str | None = None
    user_images_base64: list[str] = Field(default_factory=list)
    user_csv_data: str | None = None
    # CSV that persists across turns so user can upload once and keep editing
    persisted_csv: str | None = None

    # ── SQL data source ──
    # Explicit request to take data from the database. Set by the UI toggle;
    # routing does not depend on intent classification in this version.
    use_sql_source: bool = False
    # Result table from sql_agent, kept serialisable (columns + rows) because
    # the whole state is written to Redis on every step.
    sql_result_table: dict | None = None
    # Persists across turns so an edit like "now as a line" re-uses the rows
    # instead of hitting the database again.
    persisted_sql_result: dict | None = None
    sql_query_text: str | None = None
    # Turn-scoped: set when the query answered with a single number and the
    # graph should end with text instead of charting.
    sql_scalar_answered: bool = False
    # Which datasource to query; empty means the service default.
    sql_datasource_id: str | None = None
    sql_explanation: str | None = None
    sql_truncated: bool = False
    user_action_type: UserActionType | None = None
    user_decision: DecisionValue | None = None
    image_auto_validation_enabled: bool = settings.image_auto_validation_enabled
    image_generation_seed: int | None = None
    no_text_mode: bool = False

    artefacts: Artefacts = Field(default_factory=Artefacts)

    summary: Summary = Field(default_factory=Summary)
    assistant_message: str | None = None
    clarification_reason: str | None = None
    after_clarification: bool = False

    chart_attempt: int = 0
    chart_last_sent_attempt: int = 0

    trace_id: str | None = None

    ephemeral_status: Optional[str] = None
    errors: list[str] = Field(default_factory=list)

    # Ephemeral routing flag set by image edit router; cleared after use
    image_edit_route: str | None = None
