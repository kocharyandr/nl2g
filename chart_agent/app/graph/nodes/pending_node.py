from app.graph.state import AppState
from app.api.schemas import DecisionValue
from app.domain import StageName

import logging

logger = logging.getLogger(__name__)

# Stages that are part of the image generation branch
_IMAGE_BRANCH_STAGES = {StageName.image_generation}

# Stages that are part of the chart branch
_CHART_BRANCH_STAGES = {
    StageName.data_parsing,
    StageName.sql_query,
    StageName.plot_rendering,
    StageName.plot_approval,
    StageName.chart_review,
}


def pending_router(state: AppState):
    if state.user_decision == DecisionValue.edit:
        state.summary.add_message_for_sumup(
            f"stage=pending; event=edit_requested; "
            f"branch='{state.current_stage}'; edit='{state.user_input}'"
        )
        # Stay strictly in the current branch — no interaction agent needed
        if state.current_stage in _IMAGE_BRANCH_STAGES:
            return "image_edit_router"
        # Chart branch: re-run data extraction with the edit.
        # Rows already fetched from the database are re-used directly — going
        # back through sql_source would re-query and could quietly change the
        # numbers under a chart the user is only restyling.
        if state.persisted_sql_result or state.sql_result_table:
            return "table_data_extractor"
        if state.user_csv_data or state.persisted_csv:
            return "table_data_extractor"
        return "text_data_extractor"

    if state.awaiting_user_approval:
        return "plot_approval"

    return "to_ingress"
