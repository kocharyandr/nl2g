import logging

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.domain import StageName
from app.graph.nodes.plot_node import plot_creator_node
from app.graph.nodes.image_diffusion_node import image_diffusion_node
from app.graph.nodes.image_input_selector_node import image_input_selector_node
from app.graph.nodes.image_generation_validation_node import image_generation_validation_node
from app.graph.nodes.image_prompt_enhancer_node import image_prompt_enhancer_node
from app.graph.nodes.data_node import data_node, after_data_extractor_router
from app.graph.nodes.table_node import table_data_extractor_node
from app.graph.nodes.sql_source_node import route_after_sql_source, sql_source_node
from app.graph.nodes.interaction_node import interaction_node, route_after_interaction
from app.graph.nodes.image_edit_router_node import image_edit_router_node, route_after_image_edit_router
from app.graph.nodes.pending_node import pending_router
from app.graph.nodes.approve_node import plot_approval_node
from app.graph.nodes.summarizing_node import summarizing_node

from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.core.config import settings

logger = logging.getLogger(__name__)


llm_retry = RetryPolicy(
    max_attempts=3,
    initial_interval=1.0,
    backoff_factor=2.0,
    max_interval=30.0,
    jitter=True,
    retry_on=(LLMServiceUnavailableError,),
)

diffusion_retry = RetryPolicy(
    max_attempts=2,
    initial_interval=0.5,
    backoff_factor=2.0,
    max_interval=5.0,
    jitter=True,
    retry_on=(httpx.HTTPError,),
)


def build_graph(agents):
    graph = StateGraph(AppState)

    async def _interaction(s): return await interaction_node(s, agents.interaction)
    async def _image_edit_router(s): return await image_edit_router_node(s, agents.image_edit_router)
    async def _image_prompt_enhancer(s): return await image_prompt_enhancer_node(s, agents)
    async def _image_generation_validation(s): return await image_generation_validation_node(s, agents)
    async def _text_data_extractor(s): return await data_node(s, agents)
    async def _table_data_extractor(s): return await table_data_extractor_node(s, agents)
    async def _plot_creator(s): return await plot_creator_node(s, agents)
    async def _summarizing(s): return await summarizing_node(s, agents.summary)

    graph.add_node("interaction", _interaction, retry_policy=llm_retry)
    graph.add_node("image_edit_router", _image_edit_router, retry_policy=llm_retry)
    graph.add_node("image_input_selector", image_input_selector_node)
    graph.add_node("image_prompt_enhancer", _image_prompt_enhancer, retry_policy=llm_retry)
    graph.add_node("image_diffusion", image_diffusion_node, retry_policy=diffusion_retry)
    graph.add_node("image_generation_validation", _image_generation_validation, retry_policy=llm_retry)
    graph.add_node("text_data_extractor", _text_data_extractor, retry_policy=llm_retry)
    graph.add_node("table_data_extractor", _table_data_extractor)
    graph.add_node("sql_source", sql_source_node, retry_policy=llm_retry)
    graph.add_node("plot_creator", _plot_creator, retry_policy=llm_retry)
    graph.add_node("plot_approval", plot_approval_node)
    graph.add_node("summarizing", _summarizing)
    graph.add_node("end", lambda s: {})
    graph.add_node("error", _error_node)

    graph.add_conditional_edges(
        START,
        pending_router,
        {
            "plot_approval": "plot_approval",
            "to_ingress": "interaction",
            "text_data_extractor": "text_data_extractor",
            "table_data_extractor": "table_data_extractor",
            "sql_source": "sql_source",
            "image_edit_router": "image_edit_router",
        },
    )

    graph.add_conditional_edges(
        "interaction",
        route_after_interaction,
        {
            "text_data_extractor": "text_data_extractor",
            "table_data_extractor": "table_data_extractor",
            "sql_source": "sql_source",
            "image_edit_router": "image_edit_router",
            "end": "end",
            "error": "error",
        },
    )

    graph.add_conditional_edges(
        "sql_source",
        route_after_sql_source,
        {
            "table_data_extractor": "table_data_extractor",
            "clarification": "interaction",
            "end": "end",
            "error": "error",
        },
    )

    graph.add_conditional_edges(
        "text_data_extractor",
        after_data_extractor_router,
        {
            "plot_creator": "plot_creator",
            "clarification": "interaction",
            "error": "error",
        },
    )

    graph.add_conditional_edges(
        "table_data_extractor",
        after_data_extractor_router,
        {
            "plot_creator": "plot_creator",
            "clarification": "interaction",
            "error": "error",
        },
    )

    graph.add_conditional_edges(
        "image_edit_router",
        route_after_image_edit_router,
        {
            "image_input_selector": "image_input_selector",
            "image_prompt_enhancer": "image_prompt_enhancer",
        },
    )

    graph.add_conditional_edges(
        "image_input_selector",
        route_after_image_input_selector,
        {
            "image_prompt_enhancer": "image_prompt_enhancer",
            "error": "error",
        },
    )

    graph.add_edge("image_prompt_enhancer", "image_diffusion")
    graph.add_edge("image_diffusion", "image_generation_validation")

    graph.add_conditional_edges(
        "image_generation_validation",
        route_after_image_generation_validation,
        {
            "retry": "image_prompt_enhancer",
            "end": "end",
        },
    )

    graph.add_edge("plot_approval", "end")
    graph.add_edge("error", "end")

    graph.add_conditional_edges(
        "end",
        route_after_end,
        {
            "summarizing": "summarizing",
            "finish": END,
        },
    )
    graph.add_edge("summarizing", END)

    return graph.compile()


def _error_node(state: AppState) -> dict:
    # A node that already diagnosed the failure marks the stage itself and
    # leaves a specific message. Overwriting it with the generic routing text
    # destroys the only explanation the user gets — the difference between
    # "уточните, какие колонки использовать" and "что-то пошло не так".
    diagnosed = state.current_stage == StageName.error
    specific = (state.assistant_message or "").strip()

    return {
        "previous_stage": state.current_stage,
        "current_stage": StageName.error,
        "ephemeral_status": "Routing error.",
        "assistant_message": (
            specific if (diagnosed and specific) else "Не удалось определить следующий шаг."
        ),
    }


def route_after_image_input_selector(state: AppState) -> str:
    if state.artefacts.image.input_images_base64:
        return "image_prompt_enhancer"
    return "error"


def route_after_image_generation_validation(state: AppState) -> str:
    if state.artefacts.image.need_next_iteration:
        return "retry"
    return "end"


def route_after_end(state: AppState) -> str:
    history = list(state.summary.last_messeges_for_sumup or [])
    if len(history) >= settings.summary_trigger_min_messages_safe:
        return "summarizing"
    return "finish"
