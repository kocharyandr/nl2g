from app.graph.state import AppState
from app.api.schemas import DataValidationReport
from app.domain import StageName
from app.infra.tracing import node_span

import logging

logger = logging.getLogger(__name__)

Approve_router_dict = {
   StageName.plot_rendering: "plot_approval"
}

def approve_router(state: AppState):
    current_stage = state.current_stage

    if current_stage in Approve_router_dict:
        return Approve_router_dict[current_stage]
    raise ValueError(f"Unsupported approve stage: {current_stage}")

def plot_approval_node(state: AppState):
    with node_span(state.trace_id, "plot_approval"):
        # Clear large raw data fields that are no longer needed after approval
        lean_dataset_spec = state.artefacts.data.understanding.dataset_spec.model_copy(
            update={"raw_representation": "", "preview_rows": []}
        )
        lean_understanding = state.artefacts.data.understanding.model_copy(
            update={"dataset_spec": lean_dataset_spec}
        )
        lean_data = state.artefacts.data.model_copy(
            update={
                "understanding": lean_understanding,
                "validation": DataValidationReport(is_valid=True, reason="", correction_hint=""),
            }
        )
        artefacts = state.artefacts.model_copy(
            update={
                "data": lean_data,
                "plot": state.artefacts.plot.model_copy(update={"approved": True}),
            }
        )

        state.summary.add_message_for_sumup("chart_approval: approved")
        state.interaction_decision = None
        return {
            "previous_stage": state.current_stage,
            "current_stage": StageName.plot_approval,
            "next_stage": None,
            "awaiting_user_approval": False,
            "assistant_message": "График подтвержден.",
            "ephemeral_status": "Подтверждение получено.",
            "artefacts": artefacts,
            "summary": state.summary,
        }
