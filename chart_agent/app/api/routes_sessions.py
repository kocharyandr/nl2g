import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.agents.registry import AgentRegistry
from app.api.presenter import build_session_response
from app.api.state_store import get_state, publish_ephemeral_status, publish_state
from app.api.schemas import (
    DecisionValue,
    ImageArtefacts,
    RollbackRequest,
    SessionResponse,
    UserAction,
    UserActionType,
)
from app.graph.invalidation import invalidate
from app.graph.pipeline import build_graph
from app.graph.state import AppState
from app.infra.guardrails.client import get_guardrails_client
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import create_trace, flush, node_span

router = APIRouter(prefix="/sessions", tags=["sessions"])
meta_router = APIRouter(tags=["meta"])


@meta_router.get("/sql/datasources")
async def sql_datasources():
    """Datasource list proxied from sql_agent for the chat's picker.

    The chat only knows the orchestrator's address, and the database boundary
    should stay behind sql_agent — hence a proxy rather than a direct call.
    """
    import httpx as _httpx

    from app.core.config import settings as _settings

    if not _settings.sql_agent_enabled or not _settings.sql_agent_url_safe:
        return {"enabled": False, "datasources": [], "default_id": ""}
    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{_settings.sql_agent_url_safe}/datasources")
            response.raise_for_status()
            data = response.json()
    except _httpx.HTTPError as exc:
        logger.warning("sql datasources proxy failed: %s", exc)
        return {"enabled": True, "datasources": [], "default_id": "", "error": str(exc)}
    return {
        "enabled": True,
        "default_id": data.get("default_id", ""),
        "datasources": [d["id"] for d in data.get("datasources", [])],
    }

logger = logging.getLogger(__name__)
registry = AgentRegistry()
graph = build_graph(registry)


APPROVE_MESSAGE_ALIASES = {
    "approve",
    "ok",
    "yes",
    "подтвердить",
    "подтверждаю",
    "да",
}


def _validate_action_payload(action: UserAction) -> None:
    if action.type == UserActionType.message and action.value is not None:
        raise HTTPException(
            status_code=400,
            detail="Message action must not include decision value",
        )

    if action.type == UserActionType.decision and action.value is None:
        raise HTTPException(
            status_code=400,
            detail="Decision action requires 'value'",
        )

    if action.type == UserActionType.decision and action.value == DecisionValue.edit:
        has_text = bool((action.content or "").strip())
        has_images = bool(action.images_base64)
        if not has_text and not has_images:
            raise HTTPException(
                status_code=400,
                detail="Edit decision requires correction text or images",
            )
    # cancel carries no content — no extra validation needed


def _normalize_action_for_approval(state: AppState, action: UserAction) -> UserAction:
    if not state.awaiting_user_approval:
        return action
    if action.type != UserActionType.message:
        return action

    content = (action.content or "").strip()
    normalized = content.lower()
    if normalized in APPROVE_MESSAGE_ALIASES:
        return UserAction(type=UserActionType.decision, value=DecisionValue.approve)
    if content:
        return UserAction(
            type=UserActionType.decision,
            value=DecisionValue.edit,
            content=content,
            images_base64=action.images_base64,
        )
    return action


async def _run(state: AppState) -> AppState:
    logger.debug(
        "graph_run: start session=%s current_stage=%s next_stage=%s action_type=%s decision=%s",
        state.session_id,
        state.current_stage,
        state.next_stage,
        state.user_action_type,
        state.user_decision,
    )
    result = await graph.ainvoke(state)
    if isinstance(result, AppState):
        logger.debug(
            "graph_run: end session=%s current_stage=%s next_stage=%s",
            result.session_id,
            result.current_stage,
            result.next_stage,
        )
        return result
    if isinstance(result, dict):
        mapped = AppState(**result)
        logger.debug(
            "graph_run: end(dict) session=%s current_stage=%s next_stage=%s",
            mapped.session_id,
            mapped.current_stage,
            mapped.next_stage,
        )
        return mapped
    raise RuntimeError("Unexpected graph result type")


def _state_snapshot(state: AppState) -> dict:
    """Return lightweight state fields for Langfuse tracing — no image bytes."""
    return {
        "session_id": state.session_id,
        "current_stage": state.current_stage.value if state.current_stage else None,
        "previous_stage": state.previous_stage.value if state.previous_stage else None,
        "next_stage": state.next_stage.value if state.next_stage else None,
        "awaiting_user_approval": state.awaiting_user_approval,
        "user_decision": state.user_decision.value if state.user_decision else None,
        "user_action_type": state.user_action_type.value if state.user_action_type else None,
        "no_text_mode": state.no_text_mode,
        "image_auto_validation_enabled": state.image_auto_validation_enabled,
        "chart_attempt": state.chart_attempt,
        "has_plot_image": bool(state.artefacts.plot.image_base64),
        "has_image_artefact": bool(
            state.artefacts.image.image_base64 or state.artefacts.image.last_accepted_image_base64
        ),
        "has_persisted_csv": bool(state.persisted_csv),
        "has_user_images": bool(state.user_images_base64),
        "errors": state.errors,
        "interaction_decision": (
            state.interaction_decision.model_dump() if state.interaction_decision else None
        ),
        "clarification_reason": state.clarification_reason,
        "after_clarification": state.after_clarification,
        "image_iterations": len(state.artefacts.image.iterations),
        "image_best_score": state.artefacts.image.best_score if state.artefacts.image.iterations else None,
    }


def _build_response_and_mark_chart_sent(state: AppState) -> tuple[AppState, SessionResponse]:
    has_chart_base64 = bool(state.artefacts.plot.image_base64)
    include_chart = has_chart_base64 and state.chart_attempt > state.chart_last_sent_attempt
    logger.debug(
        "response_build: session=%s has_chart=%s chart_attempt=%s chart_last_sent_attempt=%s include_chart=%s",
        state.session_id,
        has_chart_base64,
        state.chart_attempt,
        state.chart_last_sent_attempt,
        include_chart,
    )

    response = build_session_response(state, include_chart=include_chart)
    if include_chart:
        state = state.model_copy(update={"chart_last_sent_attempt": state.chart_attempt})
    return state, response


@router.post("", response_model=SessionResponse)
async def create_session():
    session_id = str(uuid4())
    state = AppState(session_id=session_id, current_stage="ingress")
    publish_state(state)
    return build_session_response(state, include_chart=False)


@router.post("/{session_id}/messages", response_model=SessionResponse)
async def post_message(session_id: str, action: UserAction):
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id must not be empty")

    state = get_state(session_id)
    if not state:
        if action.type != UserActionType.message:
            raise HTTPException(status_code=404, detail="Session not found")
        state = AppState(session_id=session_id, current_stage="ingress")
        publish_state(state)
        logger.debug("post_message: lazily created session state session=%s", session_id)

    action = _normalize_action_for_approval(state, action)
    _validate_action_payload(action)

    if state.awaiting_user_approval and action.type != UserActionType.decision:
        raise HTTPException(status_code=400, detail="System is waiting for user approval decision")
    
    if not state.awaiting_user_approval and action.type == UserActionType.decision:
        raise HTTPException(status_code=400, detail="System is not waiting for user approval decision")

    has_message_payload = bool((action.content or "").strip()) or bool(action.csv_data) or bool(action.images_base64)
    if not state.awaiting_user_approval and not has_message_payload:
        raise HTTPException(status_code=400, detail="Input user message is empty.")

    # ── Guardrails safety filter ──
    # NOTE: safety_check is invoked inside the graph_run span block below so the
    # `guardrails.safety` observation appears as a child of graph_run in Langfuse
    # rather than as a separate trace. Compute the flag here, run later.
    safety_text = (action.content or "").strip()
    needs_safety = bool(safety_text) and not (
        action.type == UserActionType.decision
        and action.value in (DecisionValue.approve, DecisionValue.cancel)
    )

    # Preserve last_accepted_image across turns, reset rest of image artefacts
    last_accepted = state.artefacts.image.last_accepted_image_base64
    preserved_image = ImageArtefacts(last_accepted_image_base64=last_accepted)

    patch: dict[str, object] = {
        "user_action_type": action.type,
        "user_decision": None,
        "user_images_base64": action.images_base64,
        "errors": [],
        "artefacts": state.artefacts.model_copy(update={"image": preserved_image}),
    }
    if action.auto_validate_enabled is not None:
        patch["image_auto_validation_enabled"] = action.auto_validate_enabled
    if action.no_text_mode is not None:
        patch["no_text_mode"] = action.no_text_mode
    if action.generation_seed is not None:
        patch["image_generation_seed"] = action.generation_seed
    if action.csv_data is not None:
        patch["user_csv_data"] = action.csv_data
        patch["persisted_csv"] = action.csv_data
    # Scalar-answer flag is turn-scoped — never inherited from the last turn.
    patch["sql_scalar_answered"] = False
    if action.sql_datasource_id is not None:
        requested = action.sql_datasource_id.strip() or None
        if requested != state.sql_datasource_id:
            # Switching databases invalidates rows fetched from the old one:
            # an edit must not quietly restyle another database's numbers.
            patch["sql_result_table"] = None
            patch["persisted_sql_result"] = None
        patch["sql_datasource_id"] = requested
    if action.use_sql_source is not None:
        patch["use_sql_source"] = action.use_sql_source
        # Turning the database source off drops the fetched rows, so the next
        # question does not silently inherit the previous result set.
        if not action.use_sql_source:
            patch["sql_result_table"] = None
            patch["persisted_sql_result"] = None

    if action.type == UserActionType.message:
        patch["user_input"] = action.content or (
            "Построй график по загруженной таблице." if action.csv_data else action.content
        )
        # A fresh database question must not reuse the previous result set.
        if action.use_sql_source and (action.content or "").strip():
            patch["sql_result_table"] = None
            patch["persisted_sql_result"] = None
        patch["next_stage"] = None
    elif action.type == UserActionType.decision:
        patch["user_decision"] = action.value
        patch["user_input"] = action.content or state.user_input
        if action.value == DecisionValue.edit:
            patch["awaiting_user_approval"] = False
            patch["next_stage"] = None
        elif action.value == DecisionValue.cancel:
            patch["awaiting_user_approval"] = False
            patch["next_stage"] = None
            patch["clarification_reason"] = None
            patch["interaction_decision"] = None
            patch["errors"] = []
            patch["assistant_message"] = "Хорошо, отменил. Чем могу помочь?"

    # Cancel: skip graph entirely, just reset approval state and return
    if action.type == UserActionType.decision and action.value == DecisionValue.cancel:
        state = state.model_copy(update={**patch, "user_action_type": None, "user_decision": None})
        state, response = _build_response_and_mark_chart_sent(state)
        publish_state(state)
        return response

    # SDK v4: trace создаётся автоматически как root observation в graph_run span.
    trace = create_trace(
        session_id=session_id,
        user_input=action.content,
        metadata={
            "action_type": action.type.value if action.type else None,
            "previous_trace_id": state.trace_id,
        },
    )
    patch["trace_id"] = trace.id if trace is not None else None
    state = state.model_copy(update=patch)
    publish_ephemeral_status(state, "Принял, разбираюсь...")
    logger.debug(
        "post_message: session=%s action_type=%s content_len=%s images=%s decision=%s",
        session_id,
        action.type,
        len(action.content or ""),
        len(action.images_base64 or []),
        action.value,
    )
    try:
        with node_span(
            None,
            "graph_run",
            input={
                "user_input": action.content,
                "action_type": action.type.value if action.type else None,
                "state_before": _state_snapshot(state),
            },
            metadata={"action_type": action.type.value if action.type else None},
        ) as graph_span:
            # Safety filter inside the graph_run span so guardrails.safety nests
            # as a child observation in the same trace.
            if needs_safety:
                guardrails = get_guardrails_client()
                verdict = await guardrails.safety_check(safety_text)
                if verdict.rejected:
                    logger.info(
                        "Safety reject: session=%s type=%s msg=%s",
                        session_id, verdict.type_reject, verdict.message,
                    )
                    reject_state = state.model_copy(update={
                        "user_action_type": None,
                        "user_decision": None,
                        "user_images_base64": [],
                        "user_csv_data": None,
                        "ephemeral_status": None,
                        "errors": [],
                        "assistant_message": verdict.message
                            or "Запрос отклонён фильтром безопасности.",
                    })
                    _, response = _build_response_and_mark_chart_sent(reject_state)
                    publish_state(reject_state)
                    flush()
                    return response

            state = await _run(state)
            graph_span.set_output(_state_snapshot(state))
    except LLMServiceUnavailableError as exc:
        logger.exception("LLM unavailable while processing session=%s", session_id)
        flush()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected graph error in session=%s", session_id)
        flush()
        raise HTTPException(status_code=500, detail=f"Internal graph error: {exc}") from exc

    state = state.model_copy(
        update={
            "user_action_type": None,
            "user_decision": None,
            "user_images_base64": [],
            "user_csv_data": None,
            "ephemeral_status": None,
        }
    )
    state, response = _build_response_and_mark_chart_sent(state)
    publish_state(state)
    flush()
    return response


@router.post("/{session_id}/rollback", response_model=SessionResponse)
async def rollback(session_id: str, payload: RollbackRequest):
    state = get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        patch = invalidate(state, payload.target_stage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = state.model_copy(update=patch)
    state, response = _build_response_and_mark_chart_sent(state)
    publish_state(state)
    return response


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    state = get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    # GET is used by the chat UI for polling ephemeral_status during processing.
    # We must NOT consume the chart here (i.e. bump chart_last_sent_attempt) —
    # otherwise a poll racing with a freshly built chart would steal it from the
    # main POST response, and the user never sees the new chart.
    response = build_session_response(state, include_chart=False)
    return response
