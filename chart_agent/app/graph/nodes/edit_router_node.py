import logging

from app.api.state_store import publish_ephemeral_status
from app.domain import StageName
from app.graph.node_schemas.interaction_node import InteractionAction, InteractionDecision
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)

_STAGE_MAP = {
    "data_parsing": StageName.data_parsing,
    "image_generation": StageName.image_generation,
}


def route_after_edit_router(state: AppState) -> str:
    decision = state.interaction_decision
    if not decision or decision.action != InteractionAction.route_to_stage:
        return "error"
    if decision.target_stage == StageName.data_parsing:
        return "table_data_extractor" if (state.user_csv_data or state.persisted_csv) else "text_data_extractor"
    if decision.target_stage == StageName.image_generation:
        return "image_edit_router"
    return "error"


async def edit_router_node(state: AppState, agent):
    with node_span(state.trace_id, "edit_router", input=state.user_input):
        try:
            msg = (state.user_input or "").strip()
            publish_ephemeral_status(state, "Определяю тип правки...")

            context = {
                "has_plot_image": bool(state.artefacts.plot.image_base64),
                "has_diffusion_image": bool(state.artefacts.image.last_accepted_image_base64),
                "previous_stage": state.previous_stage.value if state.previous_stage else None,
                "summary": state.summary.current_summary,
            }

            try:
                edit_decision = await agent.run(user_input=msg, context=context)
                target_stage = _STAGE_MAP.get(edit_decision.target_stage)
                reason = edit_decision.reason
            except (ValueError, RuntimeError) as exc:
                logger.warning(
                    "edit_router parse error, defaulting to data_parsing. session=%s error=%s",
                    state.session_id,
                    exc,
                )
                target_stage = StageName.data_parsing
                reason = "fallback:parse_error"

            if target_stage is None:
                target_stage = StageName.data_parsing

            decision = InteractionDecision(
                action=InteractionAction.route_to_stage,
                target_stage=target_stage,
                assistant_message="",
                reason=reason,
            )

            state.summary.add_message_for_sumup(
                f"stage=edit_router; target='{target_stage.value}'; reason='{reason}'"
            )
            publish_ephemeral_status(state, "Понял правку, начинаю работу")

            return {
                "interaction_decision": decision,
                "summary": state.summary,
                "ephemeral_status": "Маршрут правки определён.",
            }
        except LLMServiceUnavailableError:
            logger.exception("LLM unavailable in edit_router_node, session=%s", state.session_id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("edit_router_node failed, session=%s", state.session_id)
            raise RuntimeError(f"edit_router_node: {exc}") from exc
