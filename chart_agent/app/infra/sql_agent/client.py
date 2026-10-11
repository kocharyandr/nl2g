"""HTTP client for the sql_agent service (NL2SQL data source).

Modelled on `app/infra/guardrails/client.py` — same shape, same tracing — with
one deliberate difference: **there is no fail-open here.** Guardrails can be
skipped and the request still works; a data source cannot. With no table there
is nothing to plot, so an outage becomes an honest message to the user rather
than a silent degradation.

Result rows never enter the span: only the SQL, row count and timings. The
table itself is the user's data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


class SQLAgentUnavailableError(RuntimeError):
    """Service unreachable or answered with an unusable payload."""


@dataclass(slots=True)
class SQLQueryResult:
    status: str  # "ok" | "need_clarification" | "error"
    datasource_id: str = ""
    columns: list[dict[str, str]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    sql: str = ""
    explanation: str = ""
    question_to_user: str | None = None
    error_type: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def needs_clarification(self) -> bool:
        return self.status == "need_clarification"


class SQLAgentClient:
    def __init__(self) -> None:
        self.base_url = settings.sql_agent_url_safe
        self.timeout = settings.sql_agent_timeout_safe

    @property
    def enabled(self) -> bool:
        return bool(settings.sql_agent_enabled and self.base_url)

    async def query(
        self,
        question: str,
        session_id: str,
        max_rows: int | None = None,
        hint_tables: list[str] | None = None,
        datasource_id: str | None = None,
    ) -> SQLQueryResult:
        if not self.enabled:
            raise SQLAgentUnavailableError("SQL-агент выключен (SQL_AGENT_ENABLED=false).")

        payload: dict[str, Any] = {
            "question": question,
            "session_id": session_id,
            "max_rows": max_rows or settings.sql_agent_max_rows_safe,
        }
        if hint_tables:
            payload["hints"] = {"tables": hint_tables}
        resolved_datasource = datasource_id or settings.sql_agent_datasource_id_safe
        if resolved_datasource:
            payload["datasource_id"] = resolved_datasource
        source = (datasource_id or settings.sql_agent_datasource_safe).strip()
        if source:
            payload["datasource_id"] = source

        with node_span(
            trace_id=None,
            name="sql_agent.query",
            input={"question": question, "max_rows": payload["max_rows"]},
            metadata={"endpoint": "/query", "url": self.base_url, "datasource_id": source or "default"},
        ) as span:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(f"{self.base_url}/query", json=payload)
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPError as exc:
                logger.warning("sql_agent query failed: %s", exc)
                if span is not None:
                    try:
                        span.update(output={"error": str(exc)})
                    except Exception:  # noqa: BLE001
                        pass
                raise SQLAgentUnavailableError(
                    f"Сервис данных недоступен: {exc}"
                ) from exc

            result = SQLQueryResult(
                status=data.get("status", "error"),
                datasource_id=data.get("datasource_id") or "",
                columns=list(data.get("columns") or []),
                rows=list(data.get("rows") or []),
                row_count=int(data.get("row_count") or 0),
                truncated=bool(data.get("truncated")),
                sql=data.get("sql") or "",
                explanation=data.get("explanation") or "",
                question_to_user=data.get("question_to_user"),
                error_type=data.get("error_type"),
                message=data.get("message"),
            )

            if span is not None:
                try:
                    # Deliberately no rows — only shape.
                    span.update(
                        output={
                            "status": result.status,
                            "sql": result.sql,
                            "datasource_id": result.datasource_id,
                            "row_count": result.row_count,
                            "truncated": result.truncated,
                            "error_type": result.error_type,
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
            return result

    async def health(self) -> bool:
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except httpx.HTTPError:
            return False


_client: SQLAgentClient | None = None


def get_sql_agent_client() -> SQLAgentClient:
    global _client
    if _client is None:
        _client = SQLAgentClient()
    return _client
