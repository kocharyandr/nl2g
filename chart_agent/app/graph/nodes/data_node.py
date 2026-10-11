import logging

from app.api.schemas import (
    AnalyticalGoal,
    ChartIntent,
    DataArtefacts,
    DataFieldRole,
    DataFieldSpec,
    DataValidationReport,
    DatasetSpec,
    DecisionValue,
    UserIntent,
)
from app.api.state_store import publish_ephemeral_status
from app.domain import StageName
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)
SUPPORTED_PLOT_TYPES = {
    "bar",
    "line",
    "stacked_bar",
    "pie",
    "doughnut",
    "scatter",
    "area",
    "histogram",
    "box",
}

GOAL_BY_CHART_TYPE = {
    "bar": AnalyticalGoal.comparison,
    "line": AnalyticalGoal.trend,
    "stacked_bar": AnalyticalGoal.composition,
    "pie": AnalyticalGoal.composition,
    "doughnut": AnalyticalGoal.composition,
    "scatter": AnalyticalGoal.relationship,
    "area": AnalyticalGoal.trend,
    "histogram": AnalyticalGoal.distribution,
    "box": AnalyticalGoal.distribution,
}


def _build_user_intent(state: AppState) -> UserIntent:
    modalities: list[str] = []
    if state.user_input:
        modalities.append("text")
    if state.user_images_base64:
        modalities.append("images")
    intent_type = "edit_chart" if state.user_decision == DecisionValue.edit else "build_chart"
    return UserIntent(
        intent_type=intent_type,
        is_editing_existing_result=bool(state.user_decision == DecisionValue.edit),
        source_modalities=modalities,
        user_goal=(state.user_input or "").strip(),
    )


def _normalize_understanding(understanding) -> tuple[DatasetSpec, ChartIntent]:
    dataset_spec = understanding.dataset_spec
    chart_intent = understanding.chart_intent
    if not dataset_spec.fields:
        dataset_spec.fields = [
            DataFieldSpec(name="dimension", role=DataFieldRole.category, inferred_type="string"),
            DataFieldSpec(name="value", role=DataFieldRole.value, inferred_type="float"),
        ]
    if chart_intent.analytical_goal == AnalyticalGoal.unknown and chart_intent.recommended_chart_type:
        chart_intent.analytical_goal = GOAL_BY_CHART_TYPE.get(
            chart_intent.recommended_chart_type.value,
            AnalyticalGoal.unknown,
        )
    updates: dict = {}
    if not chart_intent.x_label:
        x_field = next(
            (f for f in dataset_spec.fields if f.role in (DataFieldRole.category, DataFieldRole.time)), None
        )
        if x_field:
            updates["x_label"] = x_field.name
    if not chart_intent.y_label:
        y_field = next((f for f in dataset_spec.fields if f.role == DataFieldRole.value), None)
        if y_field:
            updates["y_label"] = y_field.name
    if updates:
        chart_intent = chart_intent.model_copy(update=updates)
    return dataset_spec, chart_intent


def after_data_extractor_router(state: AppState):
    if state.current_stage == StageName.error:
        return "error"
    if state.artefacts.data.validation.is_valid:
        return "plot_creator"
    return "clarification"


async def data_node(state: AppState, agents):
    with node_span(state.trace_id, "data_extractor", input=state.user_input):
        try:
            user_input = state.user_input or ""
            current_data = state.artefacts.data if (
                state.after_clarification or state.user_decision == DecisionValue.edit
            ) else None

            publish_ephemeral_status(state, "Извлекаю данные из текста")
            understanding = await agents.data_understanding.run(
                user_input=user_input,
                context=current_data,
                agent_type="parser",
            )

            dataset_spec, chart_intent = _normalize_understanding(understanding)
            recommended_type = chart_intent.recommended_chart_type
            selected_chart_type = recommended_type.value if recommended_type else None
            state.summary.add_message_for_sumup(
                "stage=data_parsing; event=goal_update; "
                f"plot_type='{selected_chart_type}'"
            )

            if selected_chart_type not in SUPPORTED_PLOT_TYPES:
                validation = DataValidationReport(
                    is_valid=False,
                    reason="Указанный тип графика не поддерживается.",
                    correction_hint=(
                        "Необходимо явно указать один из поддерживаемых типов графика: "
                        f"{', '.join(sorted(SUPPORTED_PLOT_TYPES))}."
                    ),
                )
                state.artefacts.data = DataArtefacts(
                    user_intent=_build_user_intent(state),
                    understanding=understanding.model_copy(
                        update={"dataset_spec": dataset_spec, "chart_intent": chart_intent}
                    ),
                    validation=validation,
                )
                state.summary.add_message_for_sumup(
                    "stage=data_parsing; event=error; "
                    f"reason='{validation.reason}'; "
                    f"clarification_hint='{validation.correction_hint}'"
                )
                return {
                    "artefacts": state.artefacts,
                    "previous_stage": state.current_stage,
                    "current_stage": StageName.data_parsing,
                    "after_clarification": False,
                    "clarification_reason": validation.reason,
                    "ephemeral_status": "Ошибка извлечения данных.",
                }

            state.artefacts.data = DataArtefacts(
                user_intent=_build_user_intent(state),
                understanding=understanding.model_copy(
                    update={"dataset_spec": dataset_spec, "chart_intent": chart_intent}
                ),
                validation=DataValidationReport(is_valid=True),
            )

            publish_ephemeral_status(state, "Данные готовы, начинаю строить график")
            return {
                "artefacts": state.artefacts,
                "previous_stage": state.current_stage,
                "current_stage": StageName.data_parsing,
                "after_clarification": False,
                "next_stage": StageName.plot_rendering,
                "ephemeral_status": "Данные извлечены. Строю график.",
            }
        except LLMServiceUnavailableError:
            logger.exception("LLM unavailable in data_node, session=%s", state.session_id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Data node failed, session=%s", state.session_id)
            return {
                "errors": [*state.errors, f"data_node: {exc}"],
                "previous_stage": state.current_stage,
                "current_stage": StageName.error,
                "after_clarification": False,
                "ephemeral_status": "Data parsing failed.",
                "assistant_message": "Не удалось извлечь данные из сообщения.",
            }
