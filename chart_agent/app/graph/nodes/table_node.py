"""
Table data extractor node.

Table flow:
1. Obtain a DataFrame — parsed from CSV/TSV, or taken from the sql_agent
   result table. This is the only step that differs between data sources;
   steps 2-6 are shared.
2. Build a compact table context for the agent.
3. Ask the table-code agent for pandas transformation code.
4. Execute generated code in a restricted pandas context.
5. Send the transformed DatasetSpec to the chart agent.
"""
from __future__ import annotations

import logging
import traceback

from app.api.schemas import (
    DataArtefacts,
    DataUnderstandingResult,
    DataValidationReport,
    DecisionValue,
    UserIntent,
)
from app.api.state_store import publish_ephemeral_status
from app.core.config import settings
from app.domain import StageName
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span
from app.tools.table_code_executor import (
    dataframe_to_dataset_spec,
    execute_code_safely,
    validate_result_dataframe,
)
from app.tools.table_ingest import (
    build_table_prompt_context,
    dataframe_from_result_table,
    parse_table,
)

logger = logging.getLogger(__name__)


def _build_user_intent(state: AppState) -> UserIntent:
    modalities: list[str] = []
    if state.user_input:
        modalities.append("text")
    if state.user_csv_data:
        modalities.append("csv")
    if state.user_images_base64:
        modalities.append("images")
    intent_type = "edit_chart" if state.user_decision == DecisionValue.edit else "build_chart"
    return UserIntent(
        intent_type=intent_type,
        is_editing_existing_result=bool(state.user_decision == DecisionValue.edit),
        source_modalities=modalities,
        user_goal=(state.user_input or "").strip(),
    )


def _build_planning_context(
    table_context: dict[str, object],
    execution_error: str | None = None,
    previous_code: str | None = None,
) -> dict[str, object]:
    return {
        "table": table_context,
        "execution_error": execution_error,
        "previous_code": previous_code,
    }


async def table_data_extractor_node(state: AppState, agents) -> dict:
    with node_span(state.trace_id, "table_data_extractor", input={"rows": "?"}):
        try:
            user_hint = (state.user_input or "").strip()
            result_table = state.sql_result_table or state.persisted_sql_result

            # Step 1 — the only source-specific step. A table fetched from the
            # database carries its own column types, so the CSV type heuristic
            # is bypassed for that path.
            column_types: dict[str, str] = {}
            if result_table and not state.user_csv_data:
                publish_ephemeral_status(state, "Разбираю данные из базы")
                df, column_types = dataframe_from_result_table(result_table)
                source_type = "sql"
            else:
                csv_raw = state.user_csv_data or state.persisted_csv or ""
                publish_ephemeral_status(state, "Читаю таблицу")
                df = parse_table(csv_raw)
                source_type = "csv"

            if df.empty or len(df.columns) == 0:
                raise ValueError("Таблица пустая или не содержит колонок.")

            publish_ephemeral_status(state, "Изучаю структуру данных")
            table_context = build_table_prompt_context(df)

            last_validation = DataValidationReport(
                is_valid=False,
                reason="Не удалось построить план по таблице.",
                correction_hint="Уточните, какие колонки и агрегацию использовать.",
            )
            last_understanding = DataUnderstandingResult()
            last_spec = None
            execution_error: str | None = None
            previous_code: str | None = None
            needs_clarification_from_llm = False

            for attempt_idx in range(settings.table_planner_max_retries_safe):
                attempt_num = attempt_idx + 1
                publish_ephemeral_status(
                    state,
                    "Пишу код для обработки таблицы" if attempt_num == 1 else "Что-то пошло не так, пробую снова",
                )
                planning_context = _build_planning_context(
                    table_context=table_context,
                    execution_error=execution_error,
                    previous_code=previous_code,
                )
                spec = await agents.data_understanding.run(
                    user_input=user_hint,
                    context=planning_context,
                    agent_type="table_code_generator",
                )
                last_spec = spec
                previous_code = spec.code

                if spec.needs_clarification:
                    needs_clarification_from_llm = True
                    last_validation = DataValidationReport(
                        is_valid=False,
                        reason=spec.clarification_question or "Нужно уточнение по таблице.",
                        correction_hint=spec.clarification_question,
                    )
                    break

                # A pie without a category column has anonymous slices. The
                # planner sometimes reads "без оси X" literally and drops the
                # labels; send it back with the requirement spelled out.
                chart_type_value = getattr(spec.chart_type, "value", spec.chart_type)
                if str(chart_type_value or "").lower() == "pie" and not spec.x_col:
                    execution_error = (
                        "Для круговой диаграммы обязательна колонка категорий: укажи x_col "
                        "(названия долей) и оставь её в результирующем DataFrame рядом с y_col."
                    )
                    continue

                publish_ephemeral_status(
                    state,
                    "Запускаю код, смотрю что получится" if attempt_num == 1 else "Запускаю исправленный код",
                )
                try:
                    result_df = execute_code_safely(spec.code, df)
                except Exception:  # noqa: BLE001
                    tb_lines = traceback.format_exc().strip().splitlines()
                    execution_error = "\n".join(tb_lines[-3:])
                    continue

                validation_errors = validate_result_dataframe(result_df, spec)
                # A declared-but-missing series column is a cosmetic slip, not
                # a broken result: x and y are what a chart needs, series only
                # splits it into groups. The model occasionally names a series
                # in the plan and then never materialises it in code — drop
                # the claim instead of failing the whole attempt.
                if (
                    validation_errors
                    and spec.series_col
                    and spec.series_col not in result_df.columns
                ):
                    spec = spec.model_copy(update={"series_col": None})
                    validation_errors = validate_result_dataframe(result_df, spec)
                if validation_errors:
                    execution_error = "Результат DataFrame невалиден: " + "; ".join(validation_errors)
                    continue

                dataset_spec, chart_intent, validation = dataframe_to_dataset_spec(
                    result_df,
                    spec,
                    list(df.columns),
                    column_types=column_types,
                    source_type=source_type,
                )
                last_validation = validation
                last_understanding = DataUnderstandingResult(
                    dataset_spec=dataset_spec,
                    chart_intent=chart_intent,
                )

                if validation.is_valid:
                    break

                execution_error = f"{validation.reason} {validation.correction_hint}".strip()

            data_artefacts = DataArtefacts(
                user_intent=_build_user_intent(state),
                understanding=last_understanding,
                validation=last_validation,
                # Provenance is written upstream by sql_source and must survive
                # this rebuild: without it the user never sees the query the
                # chart was built from.
                sql_source=state.artefacts.data.sql_source,
            )
            state.artefacts = state.artefacts.model_copy(update={"data": data_artefacts})

            chart_type_val = (
                last_understanding.chart_intent.recommended_chart_type.value
                if last_understanding.chart_intent.recommended_chart_type
                else "unknown"
            )
            code_attempt = "present" if last_spec is not None and last_spec.code else "missing"
            state.summary.add_message_for_sumup(
                "stage=table_parsing; event=plan_ready; "
                f"source={source_type}; rows={len(df)}; cols={len(df.columns)}; "
                f"chart_type={chart_type_val}; code_attempt={code_attempt}"
            )

            if not last_validation.is_valid:
                clarification_text = last_validation.reason
                if last_validation.correction_hint and last_validation.correction_hint not in clarification_text:
                    clarification_text = f"{clarification_text} {last_validation.correction_hint}".strip()

                if needs_clarification_from_llm:
                    state.summary.add_message_for_sumup(
                        "stage=table_parsing; event=clarification_needed; "
                        f"reason='{clarification_text}'"
                    )
                    return {
                        "artefacts": state.artefacts,
                        "previous_stage": state.current_stage,
                        "current_stage": StageName.data_parsing,
                        "after_clarification": False,
                        "clarification_reason": clarification_text,
                        "ephemeral_status": "Нужно уточнение по таблице.",
                    }

                # Код упал при выполнении — это не вина пользователя, идём в error
                logger.warning(
                    "table_data_extractor: code execution failed after all retries, session=%s reason=%s",
                    state.session_id,
                    clarification_text,
                )
                state.summary.add_message_for_sumup(
                    "stage=table_parsing; event=code_execution_failed; "
                    f"reason='{clarification_text}'"
                )
                return {
                    "artefacts": state.artefacts,
                    "errors": [*state.errors, clarification_text],
                    "previous_stage": state.current_stage,
                    "current_stage": StageName.error,
                    "after_clarification": False,
                    "ephemeral_status": "Ошибка при обработке таблицы.",
                    "assistant_message": f"Не удалось обработать таблицу: {clarification_text}",
                }

            publish_ephemeral_status(state, "Таблица обработана, строю график")
            return {
                "artefacts": state.artefacts,
                "user_csv_data": None,
                "previous_stage": state.current_stage,
                "current_stage": StageName.data_parsing,
                "after_clarification": False,
                "next_stage": StageName.plot_rendering,
                "ephemeral_status": "Данные из таблицы подготовлены. Строю график.",
            }

        except LLMServiceUnavailableError:
            logger.exception("LLM unavailable in table_data_extractor_node, session=%s", state.session_id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("table_data_extractor_node failed, session=%s", state.session_id)
            return {
                "errors": [*state.errors, f"table_node: {exc}"],
                "previous_stage": state.current_stage,
                "current_stage": StageName.error,
                "after_clarification": False,
                "ephemeral_status": "Ошибка при разборе таблицы.",
                "assistant_message": f"Не удалось обработать таблицу: {exc}",
            }
