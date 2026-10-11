import base64
import logging
import traceback

from app.api.schemas import EvaluationReport, PlotArtefacts
from app.api.schemas import DecisionValue
from app.api.state_store import publish_ephemeral_status
from app.core.config import settings
from app.domain import StageName
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span
from app.tools.chart_code_executor import execute_chart_code
from app.tools.flat_dataset import flatten_dataset

logger = logging.getLogger(__name__)


def _short_error(exc: Exception) -> str:
    tb = traceback.format_exc()
    lines = tb.strip().splitlines()
    return f"{type(exc).__name__}: {exc}\n" + "\n".join(lines[-8:])


def _build_flat_data(state: AppState) -> dict:
    understanding = state.artefacts.data.understanding
    dataset_spec = understanding.dataset_spec
    chart_intent = understanding.chart_intent
    chart_type = (
        chart_intent.recommended_chart_type.value
        if chart_intent.recommended_chart_type
        else "bar"
    )
    return flatten_dataset(dataset_spec, chart_intent=chart_intent, chart_type=chart_type)


async def plot_creator_node(state: AppState, agents):
    understanding = state.artefacts.data.understanding
    chart_intent = understanding.chart_intent
    dataset_spec = understanding.dataset_spec
    selected_chart_type = (
        chart_intent.recommended_chart_type.value
        if chart_intent.recommended_chart_type
        else None
    )

    flat_data = _build_flat_data(state)

    # Build user request description for the LLM
    user_request_parts = []
    if chart_intent.analytical_goal:
        user_request_parts.append(chart_intent.analytical_goal)
    elif chart_intent.title_hint:
        user_request_parts.append(chart_intent.title_hint)
    else:
        user_request_parts.append(f"Build a {selected_chart_type or 'bar'} chart")

    # Always include the raw user message so styling/formatting instructions are not lost
    raw_user_input = (state.user_input or "").strip()
    if raw_user_input:
        user_request_parts.append(raw_user_input)

    is_edit = (
        state.user_decision == DecisionValue.edit
        or state.current_stage == StageName.chart_review
    ) and bool(raw_user_input)

    edit_request = raw_user_input if is_edit else None
    user_request = ". ".join(dict.fromkeys(user_request_parts))

    with node_span(
        state.trace_id,
        "plot_creator",
        input={"chart_type": selected_chart_type, "user_request": user_request},
        metadata={"chart_type": selected_chart_type},
    ):
        if not selected_chart_type or not dataset_spec.points:
            return {
                "errors": [*state.errors, "plot_node: missing chart_type or dataset points"],
                "previous_stage": state.current_stage,
                "current_stage": StageName.error,
                "ephemeral_status": "Недостаточно данных для построения графика.",
                "assistant_message": "Не хватает данных для построения графика.",
            }

        max_retries = settings.chart_render_max_retries_safe
        render_feedback: str | None = None
        last_error: Exception | None = None

        for retry_idx in range(max_retries):
            attempt_num = retry_idx + 1
            agent_input: dict = {
                "chart_type": selected_chart_type,
                "user_request": user_request,
                **flat_data,
            }
            if state.no_text_mode:
                agent_input["no_text_mode"] = True
            if render_feedback:
                agent_input["render_error_comment"] = render_feedback

            try:
                publish_ephemeral_status(
                    state,
                    "Пишу код для графика" if attempt_num == 1 else "Переписываю код, ищу другой подход",
                )
                result = await agents.plot_planner.run(agent_input)
                last_code = result["code"]

                publish_ephemeral_status(
                    state,
                    "Запускаю код, рисую график" if attempt_num == 1 else "Запускаю исправленный код",
                )
                png_bytes = execute_chart_code(last_code, flat_data)
                image_base64 = base64.b64encode(png_bytes).decode("ascii")

                next_chart_attempt = state.chart_attempt + 1
                artefacts = state.artefacts.model_copy(
                    update={
                        "plot": PlotArtefacts(
                            code=last_code,
                            image_base64=image_base64,
                            mime_type="image/png",
                            approved=False,
                            chart_attempt=next_chart_attempt,
                            evaluation=EvaluationReport(
                                status="base_chart_rendered",
                                score=1.0,
                                issues=[],
                                recommendation="ready_for_user_or_diffusion_review",
                            ),
                        )
                    }
                )

                event = "edit_applied" if edit_request else "chart_built"
                state.summary.add_message_for_sumup(
                    f"stage=plot_rendering; event={event}; chart_type='{selected_chart_type}'"
                )

                return {
                    "artefacts": artefacts,
                    "chart_attempt": next_chart_attempt,
                    "awaiting_user_approval": True,
                    "current_stage": StageName.plot_rendering,
                    "next_stage": StageName.plot_approval,
                    "assistant_message": (
                        f"График построен (попытка {next_chart_attempt}).\n"
                        "Подтвердите или отправьте правки сообщением."
                    ),
                    "ephemeral_status": "График построен. Жду подтверждения.",
                }

            except LLMServiceUnavailableError:
                logger.exception("LLM unavailable in plot_node, session=%s", state.session_id)
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                render_feedback = _short_error(exc)
                publish_ephemeral_status(state, "Нашёл ошибку, исправляю")
                logger.exception(
                    "plot_node: attempt_failed retry=%s/%s session=%s error=%s",
                    attempt_num, max_retries, state.session_id, exc,
                )

        state.summary.add_message_for_sumup(
            f"stage=plot_rendering; event=error; reason='{last_error}'"
        )
        return {
            "errors": [*state.errors, f"plot_node: {last_error}"],
            "awaiting_user_approval": False,
            "current_stage": StageName.error,
            "next_stage": None,
            "assistant_message": (
                "Не удалось построить график после автоматических ретраев. "
                "Уточните данные или требования к графику и попробуйте снова."
            ),
            "ephemeral_status": "Chart render failed.",
            "summary": state.summary,
        }
