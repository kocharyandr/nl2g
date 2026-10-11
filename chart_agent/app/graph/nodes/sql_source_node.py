"""SQL data source node.

The third way to fill the table slot, alongside user text and an uploaded CSV.
Its whole job is to obtain rows; everything after it — deciding how to shape
them for a particular chart — is the existing `table_data_extractor` codegen
step, unchanged.

Variant A: the service returns the raw result set and this node does not
aggregate. Keeping the "what shape should the data be" decision in exactly one
place is why an edit like "now the same thing as a line" costs nothing here.
"""
from __future__ import annotations

import logging

from app.api.schemas import SQLSourceInfo
from app.api.state_store import publish_ephemeral_status
from app.core.config import settings
from app.domain import StageName
from app.graph.state import AppState
from app.infra.sql_agent.client import SQLAgentUnavailableError, get_sql_agent_client
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)

# Asking for "top 3 countries" is a perfectly good question, but a model may
# answer it with `SELECT country ... ORDER BY count(*)` — the measure is in the
# query yet not in the projection, so there is nothing to plot. Rather than
# pushing that back on the user, the question is re-asked once with the
# requirement made explicit. Same shape as the critic loop: retry with feedback.
MEASURE_HINT = (
    " Обязательно включи в SELECT числовую величину рядом с категорией "
    "(COUNT(*), SUM(...), AVG(...)) — результат нужен для построения графика."
)

CHARTABLE_TYPES = {"number", "datetime"}


# Spider stores missing numbers as the literal string 'null' in TEXT columns.
_MISSING_TOKENS = {"", "null", "none", "nan", "n/a", "-"}


def _numeric_text(values: list) -> bool:
    """True when every non-empty value parses as a number.

    Spider-style databases (and PAUQ built on them) declare plenty of numeric
    columns as TEXT — `MPG`, `Horsepower` in car_1 — so the declared type alone
    would send a perfectly chartable projection back for a "measure".
    """
    seen = False
    for value in values:
        if value is None or str(value).strip().lower() in _MISSING_TOKENS:
            continue
        seen = True
        try:
            float(str(value).replace(",", ".").replace(" ", ""))
        except ValueError:
            return False
    return seen


def _measure_columns(columns: list[dict], rows: list[list] | None = None) -> list[str]:
    """Columns a chart can put on its value axis."""
    sample = (rows or [])[:200]
    result = []
    for idx, column in enumerate(columns):
        name = str(column.get("name"))
        if str(column.get("type", "")).lower() in CHARTABLE_TYPES:
            result.append(name)
        elif sample and _numeric_text([row[idx] for row in sample if idx < len(row)]):
            result.append(name)
    return result


def route_after_sql_source(state: AppState) -> str:
    if state.current_stage == StageName.error:
        return "error"
    if state.clarification_reason and not state.sql_result_table:
        return "clarification"
    if state.sql_scalar_answered:
        return "end"
    return "table_data_extractor"


def _error_patch(state: AppState, message: str) -> dict:
    return {
        "errors": [*state.errors, message],
        "previous_stage": state.current_stage,
        "current_stage": StageName.error,
        "after_clarification": False,
        "ephemeral_status": "Не удалось получить данные из базы.",
        "assistant_message": message,
    }


async def sql_source_node(state: AppState) -> dict:
    question = (state.user_input or "").strip()

    with node_span(state.trace_id, "sql_source", input={"question": question}):
        # An edit within the same turn re-uses rows already fetched, so that
        # "now as a line" does not re-query the database and cannot silently
        # show different numbers than the chart the user just approved.
        if state.persisted_sql_result and not state.user_csv_data:
            logger.info("sql_source: re-using persisted result. session=%s", state.session_id)
            publish_ephemeral_status(state, "Использую уже полученные данные")
            return {
                "sql_result_table": state.persisted_sql_result,
                "previous_stage": state.current_stage,
                "current_stage": StageName.sql_query,
                "ephemeral_status": "Данные из базы уже получены.",
            }

        if not question:
            return _error_patch(state, "Не задан вопрос к базе данных.")

        client = get_sql_agent_client()
        publish_ephemeral_status(state, "Запрашиваю данные из базы")

        try:
            result = await client.query(
                question=question,
                session_id=state.session_id,
                max_rows=settings.sql_agent_max_rows_safe,
                datasource_id=state.sql_datasource_id,
            )
        except SQLAgentUnavailableError as exc:
            # No fail-open: without data there is nothing to plot, so the user
            # gets an honest message instead of a silently different chart.
            logger.warning("sql_source: service unavailable. session=%s err=%s", state.session_id, exc)
            return _error_patch(state, str(exc))

        if result.needs_clarification:
            question_to_user = result.question_to_user or "Уточните вопрос к данным."
            state.summary.add_message_for_sumup(
                f"stage=sql_query; event=clarification_needed; reason='{question_to_user}'"
            )
            return {
                "previous_stage": state.current_stage,
                "current_stage": StageName.sql_query,
                "after_clarification": False,
                "clarification_reason": question_to_user,
                "ephemeral_status": "Нужно уточнение по запросу к базе.",
            }

        if not result.ok:
            message = result.message or "Не удалось выполнить запрос к базе."
            state.summary.add_message_for_sumup(
                f"stage=sql_query; event=query_failed; error_type='{result.error_type}'"
            )
            return _error_patch(state, f"Запрос к базе не выполнен: {message}")

        if not result.rows:
            return _error_patch(
                state,
                "Запрос к базе выполнен, но данных не вернул — уточните условия отбора.",
            )

        # A single number is an answer, not a dataset: charting a 1x1 result
        # fails downstream in confusing ways, while saying the number outright
        # answers questions like "how many X in total" the way a person would.
        if result.row_count == 1 and len(result.columns) == 1 and result.rows:
            value = result.rows[0][0]
            explanation = (result.explanation or "").strip()
            answer = f"{explanation} Ответ: {value}." if explanation else f"Ответ: {value}."
            answer += "\n\nSQL-запрос:\n```sql\n" + result.sql + "\n```"
            state.artefacts = state.artefacts.model_copy(
                update={
                    "data": state.artefacts.data.model_copy(
                        update={
                            "sql_source": SQLSourceInfo(
                                used=True, sql=result.sql,
                                explanation=result.explanation,
                                row_count=1, truncated=False,
                            )
                        }
                    )
                }
            )
            state.summary.add_message_for_sumup(
                f"stage=sql_query; event=scalar_answer; value='{value}'"
            )
            return {
                "artefacts": state.artefacts,
                "sql_scalar_answered": True,
                "sql_query_text": result.sql,
                "sql_explanation": result.explanation,
                "previous_stage": state.current_stage,
                "current_stage": StageName.sql_query,
                "after_clarification": False,
                "assistant_message": answer,
                "ephemeral_status": "Ответ получен из базы.",
                "summary": state.summary,
            }

        # A chart needs a measure. If the projection has none, ask once more
        # with the requirement spelled out before giving up on the question.
        if not _measure_columns(result.columns, result.rows):
            logger.info(
                "sql_source: no measure in result, re-asking with hint. session=%s cols=%s",
                state.session_id,
                [c.get("name") for c in result.columns],
            )
            publish_ephemeral_status(state, "Уточняю запрос, чтобы получить числа")
            try:
                retried = await client.query(
                    question=question + MEASURE_HINT,
                    session_id=state.session_id,
                    max_rows=settings.sql_agent_max_rows_safe,
                    datasource_id=state.sql_datasource_id,
                )
            except SQLAgentUnavailableError as exc:
                return _error_patch(state, str(exc))

            if retried.ok and retried.rows and _measure_columns(retried.columns, retried.rows):
                result = retried
            else:
                names = ", ".join(str(c.get("name")) for c in result.columns) or "—"
                return _error_patch(
                    state,
                    f"Запрос к базе вернул только текстовые колонки ({names}), "
                    "по ним график не построить. Уточните, какую величину показать "
                    "на графике — например «по количеству» или «по суммарной мощности».",
                )

        table = {
            "columns": result.columns,
            "rows": result.rows,
            "sql": result.sql,
            "explanation": result.explanation,
            "truncated": result.truncated,
        }

        state.artefacts = state.artefacts.model_copy(
            update={
                "data": state.artefacts.data.model_copy(
                    update={
                        "sql_source": SQLSourceInfo(
                            used=True,
                            sql=result.sql,
                            explanation=result.explanation,
                            row_count=result.row_count,
                            truncated=result.truncated,
                        )
                    }
                )
            }
        )
        state.summary.add_message_for_sumup(
            "stage=sql_query; event=rows_fetched; "
            f"rows={result.row_count}; truncated={result.truncated}"
        )

        status = f"Получено строк: {result.row_count}."
        if result.truncated:
            status += " Выборка обрезана по лимиту."

        return {
            "artefacts": state.artefacts,
            "sql_result_table": table,
            "persisted_sql_result": table,
            "sql_query_text": result.sql,
            "sql_explanation": result.explanation,
            "sql_truncated": result.truncated,
            "previous_stage": state.current_stage,
            "current_stage": StageName.sql_query,
            "after_clarification": False,
            "clarification_reason": None,
            "ephemeral_status": status,
            "summary": state.summary,
        }
