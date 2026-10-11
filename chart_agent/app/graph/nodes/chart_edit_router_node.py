import logging

from app.api.state_store import publish_ephemeral_status
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


def route_after_chart_edit_router(state: AppState) -> str:
    route = state.chart_edit_route
    if route == "plot_creator":
        return "plot_creator"
    # re_extract (or unknown fallback): pick the right extractor by data source
    if state.user_csv_data or state.persisted_csv:
        return "table_data_extractor"
    return "text_data_extractor"


async def chart_edit_router_node(state: AppState, agent):
    with node_span(state.trace_id, "chart_edit_router", input=state.user_input):
        try:
            msg = (state.user_input or "").strip()
            publish_ephemeral_status(state, "Анализирую тип правки...")

            understanding = state.artefacts.data.understanding
            chart_intent = understanding.chart_intent
            dataset_spec = understanding.dataset_spec

            context = {
                "chart_type": chart_intent.recommended_chart_type.value
                if chart_intent.recommended_chart_type else None,
                "title": chart_intent.title_hint,
                "fields": [f.name for f in dataset_spec.fields],
                "point_count": len(dataset_spec.points),
                "summary": state.summary.current_summary,
            }

            try:
                decision = await agent.run(user_input=msg, context=context)
                route = decision.target  # "plot_creator" or "re_extract"
                reason = decision.reason
            except (ValueError, RuntimeError) as exc:
                logger.warning(
                    "chart_edit_router parse error, defaulting to plot_creator. "
                    "session=%s error=%s",
                    state.session_id,
                    exc,
                )
                # Style edit is the safer default — preserves data and just regenerates code
                route = "plot_creator"
                reason = "fallback:parse_error"

            state.summary.add_message_for_sumup(
                f"stage=chart_edit_router; route='{route}'; reason='{reason}'"
            )
            publish_ephemeral_status(state, "Понял правку, начинаю работу")

            return {
                "summary": state.summary,
                "ephemeral_status": "Тип правки определён.",
                "chart_edit_route": route,
            }

        except LLMServiceUnavailableError:
            logger.exception(
                "LLM unavailable in chart_edit_router_node, session=%s", state.session_id
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("chart_edit_router_node failed, session=%s", state.session_id)
            raise RuntimeError(f"chart_edit_router_node: {exc}") from exc
