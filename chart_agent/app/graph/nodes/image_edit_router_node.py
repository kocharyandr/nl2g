import logging

from app.api.schemas import DecisionValue
from app.api.state_store import publish_ephemeral_status
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


def route_after_image_edit_router(state: AppState) -> str:
    return state.image_edit_route or "image_input_selector"


async def image_edit_router_node(state: AppState, agent):
    with node_span(state.trace_id, "image_edit_router", input=state.user_input):
        try:
            msg = (state.user_input or "").strip()
            image_artefacts = state.artefacts.image
            has_user_images = bool(state.user_images_base64)
            has_last_accepted = bool((image_artefacts.last_accepted_image_base64 or "").strip())
            is_edit = state.user_decision == DecisionValue.edit

            # Short-circuit: no existing image or user attached a new one — must go through selector
            if not is_edit or not has_last_accepted or has_user_images:
                route = "image_input_selector"
                reason = (
                    "new_user_image" if has_user_images
                    else "no_last_accepted" if not has_last_accepted
                    else "not_edit_flow"
                )
            else:
                publish_ephemeral_status(state, "Определяю, нужно ли менять источник...")
                context = {
                    "has_user_images": has_user_images,
                    "has_last_accepted_image": has_last_accepted,
                    "input_source": image_artefacts.input_source,
                    "summary": state.summary.current_summary,
                }
                try:
                    decision = await agent.run(user_input=msg, context=context)
                    route = decision.target
                    reason = decision.reason
                except (ValueError, RuntimeError) as exc:
                    logger.warning(
                        "image_edit_router parse error, defaulting to image_prompt_enhancer. "
                        "session=%s error=%s",
                        state.session_id,
                        exc,
                    )
                    route = "image_prompt_enhancer"
                    reason = "fallback:parse_error"

            state.summary.add_message_for_sumup(
                f"stage=image_edit_router; route='{route}'; reason='{reason}'"
            )
            publish_ephemeral_status(state, "Понял правку, начинаю работу")

            update: dict = {
                "summary": state.summary,
                "ephemeral_status": "Маршрут генерации определён.",
                "image_edit_route": route,
            }

            # When skipping image_input_selector, pre-populate input_images_base64
            # from last_accepted so image_prompt_enhancer gets a valid source.
            if route == "image_prompt_enhancer" and has_last_accepted:
                updated_image = image_artefacts.model_copy(
                    update={
                        "input_images_base64": [image_artefacts.last_accepted_image_base64],
                        "input_source": "last_generated",
                        "iterations": [],
                        "best_score": -1.0,
                        "validation_feedback": "",
                        "need_next_iteration": False,
                    }
                )
                update["artefacts"] = state.artefacts.model_copy(update={"image": updated_image})

            return update

        except LLMServiceUnavailableError:
            logger.exception(
                "LLM unavailable in image_edit_router_node, session=%s", state.session_id
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("image_edit_router_node failed, session=%s", state.session_id)
            raise RuntimeError(f"image_edit_router_node: {exc}") from exc
