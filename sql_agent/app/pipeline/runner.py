"""The three-role NL2SQL pipeline behind POST /query.

Schema agent → SQL agent → critic loop, exactly the configuration measured in
the NL2SQL work (57.3% execution accuracy on KaggleDBQA with per-role LoRA
adapters and the schema profile enabled).

The critic loop is what makes this safe to expose as a service: the query is
actually executed against the database before the caller sees it, so a
statement that does not run never leaves this process.

Variant A: whatever the query returns is returned as-is. No aggregation is
performed here — deciding how to shape data for a specific chart is
chart_agent's existing codegen step, and duplicating that decision in two
services is what Variant B would have cost.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.db.connector import DBConnector, QueryResult, QueryTimeoutError
from app.db.safety import UnsafeSQLError, validate_single_select
from app.llm.client import LLMUnavailableError, get_role_client
from app.pipeline import prompts
from app.pipeline.profile import format_profile_block, load_profile
from app.pipeline.schema_text import render_schema, select_tables

logger = logging.getLogger(__name__)

CLARIFICATION_MARKER = "NEED_CLARIFICATION:"


class ClarificationNeeded(Exception):
    """The schema agent could not resolve the question against this database."""

    def __init__(self, question_to_user: str) -> None:
        super().__init__(question_to_user)
        self.question_to_user = question_to_user


@dataclass(slots=True)
class PipelineOutcome:
    sql: str
    explanation: str
    result: QueryResult
    meta: dict[str, object] = field(default_factory=dict)


def extract_sql(text: str) -> str:
    """Pull SQL out of a ```sql fence, tolerating a missing closing fence."""
    fenced = re.search(r"```sql\s*(.*?)\s*```", text or "", re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    unclosed = re.search(r"```sql\s*(.*)", text or "", re.DOTALL | re.IGNORECASE)
    if unclosed:
        return unclosed.group(1).strip().rstrip("`").strip()
    # No fence: drop any <thinking> block and take what remains.
    without_thinking = re.sub(r"<thinking>.*?</thinking>", " ", text or "", flags=re.DOTALL | re.IGNORECASE)
    return without_thinking.replace("```", "").strip()


async def _run_schema_agent(
    question: str, schema_text: str, profile_block: str, all_tables: list[str]
) -> list[str]:
    client = get_role_client("schema")
    system = (
        prompts.SCHEMA_SYSTEM_WITH_CLARIFICATION
        if settings.clarification_enabled
        else prompts.SCHEMA_SYSTEM
    )
    answer = await client.ask(
        system=system,
        user=prompts.build_schema_prompt(schema_text, profile_block, question),
        max_tokens=256,
    )

    if settings.clarification_enabled and CLARIFICATION_MARKER in answer.upper():
        idx = answer.upper().index(CLARIFICATION_MARKER)
        asked = answer[idx + len(CLARIFICATION_MARKER):].strip()
        raise ClarificationNeeded(asked or "Уточните, пожалуйста, вопрос к данным.")

    selected = select_tables(answer, all_tables)
    if not selected:
        # The agent produced nothing usable. Falling back to the full schema
        # loses the RAG benefit but keeps the question answerable.
        logger.info("schema agent selected no tables, falling back to full schema")
        return all_tables
    return selected


async def _run_sql_agent(question: str, schema_text: str, profile_block: str) -> str:
    client = get_role_client("sql")
    answer = await client.ask(
        system=prompts.SQL_SYSTEM,
        user=prompts.build_sql_prompt(schema_text, profile_block, question),
        max_tokens=settings.llm_max_tokens,
    )
    return extract_sql(answer)


async def _run_critic(question: str, schema_text: str, current_sql: str, feedback: str) -> str:
    client = get_role_client("critic")
    answer = await client.ask(
        system=prompts.CRITIC_SYSTEM,
        user=prompts.build_critic_prompt(schema_text, question, current_sql, feedback),
        max_tokens=settings.llm_max_tokens,
    )
    return extract_sql(answer)


async def _explain(question: str, sql: str) -> str:
    if not settings.explanation_llm_call:
        return ""
    try:
        client = get_role_client("sql")
        text = await client.ask(
            system=prompts.EXPLANATION_SYSTEM,
            user=prompts.build_explanation_prompt(question, sql),
            max_tokens=120,
            temperature=0.0,
        )
    except LLMUnavailableError as exc:
        logger.warning("explanation step failed, continuing without it: %s", exc)
        return ""
    # Keep it to one line — this goes straight into the chart_agent response.
    return " ".join(text.split()).strip().strip('"')


async def run_pipeline(
    question: str,
    connector: DBConnector,
    max_rows: int,
    hint_tables: list[str] | None = None,
    db_id: str | None = None,
) -> PipelineOutcome:
    started = time.perf_counter()
    timeout = settings.db_statement_timeout_safe

    tables = await asyncio.to_thread(connector.list_tables)
    all_table_names = [t.name for t in tables]
    if not all_table_names:
        raise RuntimeError("В базе нет доступных таблиц.")

    # The profile file is named after the datasource id, so switching database
    # picks up the matching descriptions with no extra configuration.
    profile = (
        load_profile(settings.profiles_dir_safe, db_id or settings.db_id)
        if settings.use_profile
        else None
    )

    full_schema_text = render_schema(tables)
    full_profile_block = format_profile_block(profile)

    # 1. Schema agent — which tables does this question need?
    if hint_tables:
        known = {name.lower() for name in all_table_names}
        selected = [name for name in hint_tables if name.lower() in known] or all_table_names
        logger.info("schema selection taken from caller hints: %s", selected)
    else:
        selected = await _run_schema_agent(
            question, full_schema_text, full_profile_block, all_table_names
        )

    narrowed_schema = render_schema(tables, filter_tables=selected)
    narrowed_profile = format_profile_block(profile, filter_tables=selected)

    # 2. SQL agent — draft the query against the narrowed schema.
    current_sql = await _run_sql_agent(question, narrowed_schema, narrowed_profile)

    # 3. Critic loop — execute for real, feed the engine's own error back.
    attempts = 0
    last_feedback: str | None = None
    for attempt in range(settings.critic_max_attempts_safe):
        attempts = attempt + 1
        feedback = await asyncio.to_thread(connector.probe, current_sql, timeout)
        if feedback is None:
            last_feedback = None
            break
        last_feedback = feedback
        if attempt == settings.critic_max_attempts_safe - 1:
            break
        current_sql = await _run_critic(question, narrowed_schema, current_sql, feedback)

    # The critic may have run out of attempts. Validation still decides whether
    # the statement is allowed to touch the database at all.
    validate_single_select(current_sql)

    try:
        result = await asyncio.to_thread(
            connector.execute, current_sql, max_rows, timeout
        )
    except QueryTimeoutError:
        raise
    except UnsafeSQLError:
        raise

    explanation = await _explain(question, current_sql)

    meta = {
        "selected_tables": selected,
        "used_hint_tables": bool(hint_tables),
        "critic_attempts": attempts,
        "critic_last_feedback": last_feedback,
        "datasource_id": db_id or settings.db_id,
        "profile_used": bool(profile),
        "db_duration_ms": round(result.duration_ms, 2),
        "total_duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
    }
    return PipelineOutcome(
        sql=current_sql, explanation=explanation, result=result, meta=meta
    )
