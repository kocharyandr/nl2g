import logging

from app.graph.state import AppState
from app.graph.node_schemas.ingress_node import STAGES

logger = logging.getLogger(__name__)


def route_after_task_router(state: AppState):
    decision = state.interaction_decision
    allowed_stages = [
        stage.name for stage in STAGES if stage.routable_from_ingress
    ]
    if decision and decision.target_stage in allowed_stages:
        logger.debug(
            "route_after_task_router: route=%s session=%s",
            decision.target_stage.value,
            state.session_id,
        )
        return decision.target_stage.value
    logger.debug("route_after_task_router: route=error session=%s", state.session_id)
    return "error"
