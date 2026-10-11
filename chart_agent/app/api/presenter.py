from app.api.schemas import ActiveBranch, SessionResponse
from app.domain import StageName
from app.graph.state import AppState

# Stages that belong to the chart branch
_CHART_STAGES = {StageName.data_parsing, StageName.sql_query, StageName.plot_rendering, StageName.plot_approval, StageName.chart_review}
# Stages that belong to the image generation branch
_IMAGE_STAGES = {StageName.image_generation}


def _active_branch(state: AppState) -> ActiveBranch:
    if state.current_stage in _CHART_STAGES:
        return ActiveBranch.chart
    if state.current_stage in _IMAGE_STAGES:
        return ActiveBranch.image
    # Infer from artefacts when stage is ambiguous (e.g. ingress after first build)
    if state.artefacts.plot.image_base64:
        return ActiveBranch.chart
    if state.artefacts.image.image_base64 or state.artefacts.image.last_accepted_image_base64:
        return ActiveBranch.image
    return ActiveBranch.none


def build_session_response(state: AppState, include_chart: bool = True) -> SessionResponse:
    artefacts = state.artefacts
    if not include_chart:
        artefacts = artefacts.model_copy(
            update={
                "plot": artefacts.plot.model_copy(update={"image_base64": None}),
            }
        )

    branch = _active_branch(state)
    show_approve_cancel = state.awaiting_user_approval

    return SessionResponse(
        session_id=state.session_id,
        current_stage=state.current_stage,
        ephemeral_status=state.ephemeral_status,
        assistant_message=state.assistant_message,
        artefacts=artefacts,
        awaiting_user_approval=state.awaiting_user_approval,
        active_branch=branch,
        show_approve_cancel=show_approve_cancel,
    )
