import logging

from app.api.state_store import publish_ephemeral_status
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)

async def summarizing_node(state: AppState, agent):
    with node_span(state.trace_id, "summarizing"):
        try:
            publish_ephemeral_status(state, "Обновляю память о диалоге")
            summary_answer = await agent.run(summary=state.summary)
            publish_ephemeral_status(state, "Запомнил всё важное")
            state.summary.current_summary = summary_answer.current_summary
            state.summary.clear_last_messeges_state()
            return {
                "ephemeral_status": "Контекст обновлен.",
                "summary": state.summary,
            }
        except LLMServiceUnavailableError:
            logger.warning("LLM unavailable in summarizing_node, skipping. session=%s", state.session_id)
            state.summary.clear_last_messeges_state()
            return {"summary": state.summary}
        except Exception as exc:  # noqa: BLE001
            logger.warning("summarizing_node failed, skipping summary update. session=%s error=%s", state.session_id, exc)
            state.summary.clear_last_messeges_state()
            return {"summary": state.summary}
