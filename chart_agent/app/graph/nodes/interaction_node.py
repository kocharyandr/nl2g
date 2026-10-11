import logging

from app.api.schemas import DecisionValue
from app.api.state_store import publish_ephemeral_status
from app.core.config import settings
from app.domain import StageName
from app.graph.node_schemas.ingress_node import STAGES
from app.graph.node_schemas.interaction_node import InteractionAction, InteractionDecision
from app.graph.state import AppState
from app.infra.guardrails.client import get_guardrails_client
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


# Three top-level intent labels used to short-circuit the interaction LLM
# when guardrails (GLiNER) returns a confident classification.
INTENT_LABEL_DESCRIPTIONS: dict[str, str] = {
    "build_chart": (
        "пользователь хочет построить диаграмму или график по данным/таблице/числам "
        "(столбчатый, линейный, круговой, scatter и т.п.)"
    ),
    "generate_image": (
        "пользователь хочет сгенерировать или отредактировать художественное "
        "изображение через нейросеть-диффузию (картинка, арт, эффект)"
    ),
    "chart_from_database": (
        "пользователь хочет построить график по данным из базы данных: "
        "спрашивает про показатели, метрики, выручку, количество, динамику "
        "за период — но своих чисел и таблицы не приводит"
    ),
    "ask_question": (
        "общий вопрос-ответ: разговорный вопрос, вопрос о возможностях системы, "
        "просьба объяснить что-то — без задания построить график или сгенерировать изображение"
    ),
}

INTENT_TO_STAGE: dict[str, StageName | None] = {
    "build_chart": StageName.data_parsing,
    "chart_from_database": StageName.sql_query,
    "generate_image": StageName.image_generation,
    "ask_question": None,  # → respond
}


async def _try_guardrails_intent(state: AppState, msg: str) -> InteractionDecision | None:
    """Try GLiNER-based intent routing. Returns None on disabled / low confidence / error."""
    if not settings.guardrails_intent_routing_enabled:
        return None
    client = get_guardrails_client()
    if not client.enabled:
        return None

    # The database label is offered to the classifier only when intent routing
    # for that branch is switched on. Until then the branch is chosen by an
    # explicit UI toggle, so the first version's correctness does not depend on
    # classification accuracy.
    descriptions = dict(INTENT_LABEL_DESCRIPTIONS)
    if not settings.sql_agent_intent_routing_enabled:
        descriptions.pop("chart_from_database", None)

    result = await client.classify(
        text=msg,
        task="intent",
        labels=list(descriptions.keys()),
        label_descriptions=descriptions,
        multi_label=False,
    )
    if result is None or not result.passes(settings.guardrails_confidence_threshold):
        logger.debug(
            "guardrails intent routing: low confidence/none, falling back to LLM. session=%s label=%s conf=%s",
            state.session_id,
            (result and result.label),
            (result and result.confidence),
        )
        return None

    label = result.label
    target_stage = INTENT_TO_STAGE.get(label)
    if target_stage is None:
        # ask_question — answer briefly via respond, no LLM needed for trivial cases
        # but interaction LLM still produces a much nicer answer, so we fall back.
        return None

    logger.info(
        "guardrails intent routing: hit. session=%s label=%s conf=%.2f target=%s",
        state.session_id, label, result.confidence, target_stage.value,
    )
    return InteractionDecision(
        action=InteractionAction.route_to_stage,
        target_stage=target_stage,
        assistant_message="",
        reason=f"guardrails:intent={label} confidence={result.confidence:.2f}",
    )


def _normalize_interaction_decision(decision: InteractionDecision) -> InteractionDecision:
    if decision.action == InteractionAction.route_to_stage and decision.target_stage == StageName.chat:
        return InteractionDecision(
            action=InteractionAction.respond,
            target_stage=None,
            assistant_message=(
                decision.assistant_message.strip()
                or "Могу помочь с построением графиков и генерацией изображений. Что сделаем?"
            ),
            reason=f"{decision.reason} [normalized:chat_to_respond]",
        )

    if decision.action != InteractionAction.route_to_stage:
        return decision

    allowed = {stage.name for stage in STAGES if stage.routable_from_ingress}
    allowed.add(StageName.sql_query)
    if decision.target_stage in allowed:
        return decision

    return InteractionDecision(
        action=InteractionAction.ask_clarification,
        target_stage=None,
        assistant_message="Уточните: вам нужно построить график по данным или сгенерировать/изменить изображение?",
        reason=f"{decision.reason} [normalized:invalid_target_stage]",
    )


def _override_decision_for_sql(
    decision: InteractionDecision, state: AppState
) -> InteractionDecision:
    """Route a fresh question to the database when the toggle demands it.

    With «Данные из базы» on, the user already answered "which data" — a chat
    reply or a "what's your data source?" counter-question is the wrong
    reading. Only fresh questions are overridden: when clarification_reason is
    already set on the *incoming* state, the clarification relays a real
    downstream question and must reach the user.
    """
    if decision.action not in {InteractionAction.respond, InteractionAction.ask_clarification}:
        return decision
    if not _wants_sql_source(state):
        return decision
    if not (state.user_input or "").strip() or state.clarification_reason:
        return decision
    return InteractionDecision(
        action=InteractionAction.route_to_stage,
        target_stage=StageName.sql_query,
        assistant_message="",
        reason=f"{decision.reason} [override:sql_source_toggle]",
    )


def _wants_sql_source(state: AppState) -> bool:
    """True when this turn should take its data from the database."""
    if not settings.sql_agent_enabled:
        return False
    return bool(state.use_sql_source or state.persisted_sql_result)


def route_after_interaction(state: AppState) -> str:
    decision = state.interaction_decision
    if not decision:
        return "error"
    if decision.action == InteractionAction.route_to_stage:
        if decision.target_stage == StageName.sql_query:
            return "sql_source"
        if decision.target_stage == StageName.data_parsing:
            # Three sources now fill the same table slot. An explicit request
            # for database data wins over an uploaded CSV, because the toggle
            # is a deliberate user action while a CSV may just be left over
            # from an earlier turn.
            if _wants_sql_source(state):
                return "sql_source"
            if state.user_csv_data or state.persisted_csv:
                return "table_data_extractor"
            return "text_data_extractor"
        if decision.target_stage == StageName.image_generation:
            return "image_edit_router"
        return "error"
    if decision.action in {InteractionAction.respond, InteractionAction.ask_clarification}:
        return "end"
    return "error"


async def interaction_node(state: AppState, agent):
    with node_span(state.trace_id, "interaction", input=state.user_input):
        try:
            msg = (state.user_input or "").strip()
            publish_ephemeral_status(state, "Думаю, что имеется в виду...")

            is_editing_flow = state.user_decision == DecisionValue.edit
            if not is_editing_flow and state.awaiting_user_approval and msg:
                is_editing_flow = True

            # Try fast GLiNER routing for fresh requests (not edit, no pending clarification).
            # On hit it produces a final InteractionDecision and skips the LLM entirely.
            decision: InteractionDecision | None = None
            if not is_editing_flow and not state.clarification_reason and msg:
                decision = await _try_guardrails_intent(state, msg)

            context = {
                "previous_stage": state.previous_stage.value if state.previous_stage else None,
                "current_stage": state.current_stage.value if state.current_stage else None,
                "next_stage": state.next_stage.value if state.next_stage else None,
                "is_editing_flow": is_editing_flow,
                "awaiting_user_approval": state.awaiting_user_approval,
                "has_user_images": bool(state.user_images_base64),
                "has_user_csv": bool(state.user_csv_data),
                "has_persisted_csv": bool(state.persisted_csv),
                "has_plot_image": bool(state.artefacts.plot.image_base64),
                "clarification_reason": state.clarification_reason,
                "summary": state.summary.current_summary,
                "last_messages_for_sumup": list(state.summary.last_messeges_for_sumup),
            }

            if decision is not None:
                # GLiNER short-circuit hit. Skip the LLM call.
                logger.debug("interaction: skipping LLM (guardrails intent confident)")
            else:
                try:
                    decision = await agent.run(user_input=msg, context=context)
                except (ValueError, RuntimeError) as parse_exc:
                    logger.warning(
                        "interaction agent returned non-JSON, using fallback. session=%s error=%s",
                        state.session_id,
                        parse_exc,
                    )
                    has_csv = bool(state.user_csv_data)
                    has_data = bool(state.artefacts.data.validation.is_valid)
                    if has_csv or has_data:
                        decision = InteractionDecision(
                            action=InteractionAction.route_to_stage,
                            target_stage=StageName.data_parsing,
                            assistant_message="",
                            reason="fallback:non_json_response",
                        )
                    else:
                        decision = InteractionDecision(
                            action=InteractionAction.ask_clarification,
                            target_stage=None,
                            assistant_message="Пожалуйста, уточните запрос — что именно нужно построить?",
                            reason="fallback:non_json_response",
                        )
            decision = _normalize_interaction_decision(decision)
            decision = _override_decision_for_sql(decision, state)

            # Guard against intra-run loops:
            # if upstream stage already requested clarification in this run,
            # interaction must end with a clarification question, not re-route.
            if (
                state.clarification_reason
                and not state.after_clarification
                and decision.action == InteractionAction.route_to_stage
            ):
                decision = InteractionDecision(
                    action=InteractionAction.ask_clarification,
                    target_stage=None,
                    assistant_message=(
                        "Пожалуйста, уточните недостающие данные: "
                        f"{state.clarification_reason}"
                    ),
                    reason=f"{state.clarification_reason} [forced_clarification_guard]",
                )
            publish_ephemeral_status(state, "Понял, начинаю работу")

            if decision.action == InteractionAction.route_to_stage:
                state.summary.add_message_for_sumup(
                    "stage=interaction; event=goal_set; "
                    f"target_stage='{decision.target_stage}'; "
                    f"reason='{decision.reason}'"
                )
            elif decision.action == InteractionAction.ask_clarification:
                state.summary.add_message_for_sumup(
                    "stage=interaction; event=clarification_needed; "
                    f"reason='{decision.reason}'"
                )

            after_clarification = False
            if decision.action == InteractionAction.ask_clarification:
                after_clarification = True
            elif decision.action == InteractionAction.route_to_stage:
                after_clarification = state.after_clarification

            return {
                "previous_stage": state.current_stage,
                "current_stage": state.current_stage,
                "interaction_decision": decision,
                "after_clarification": after_clarification,
                "clarification_reason": (
                    decision.reason if decision.action == InteractionAction.ask_clarification else None
                ),
                "assistant_message": (
                    decision.assistant_message
                    if decision.action in {InteractionAction.respond, InteractionAction.ask_clarification}
                    else state.assistant_message
                ),
                "ephemeral_status": "Следующий шаг определен.",
                "summary": state.summary,
            }
        except LLMServiceUnavailableError:
            logger.exception("LLM unavailable in interaction_node, session=%s", state.session_id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("interaction node failed, session=%s", state.session_id)
            raise RuntimeError(f"interaction node: {exc}") from exc
