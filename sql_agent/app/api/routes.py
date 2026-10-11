"""HTTP surface: POST /query, GET /schema, GET /health.

Synchronous and stateless. `session_id` is accepted for tracing only — the
service holds no session state of its own; that stays in chart_agent.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.schemas import (
    DatasourceInfo,
    DatasourceListResponse,
    ErrorType,
    QueryRequest,
    QueryResponse,
    QueryStatus,
    SchemaResponse,
    TableSchema,
)
from app.core.config import settings
from app.db.connector import QueryTimeoutError, build_connector
from app.db.registry import DatasourceRegistry
from app.db.safety import UnsafeSQLError
from app.llm.client import LLMUnavailableError, get_role_client
from app.pipeline.profile import load_profile
from app.pipeline.runner import ClarificationNeeded, run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()

_registry: DatasourceRegistry | None = None
_connectors: dict[str, object] = {}


def get_registry() -> DatasourceRegistry:
    global _registry
    if _registry is None:
        _registry = DatasourceRegistry(
            roots=settings.datasource_roots_safe,
            explicit_path=settings.db_path,
            explicit_id=settings.db_id,
        )
    return _registry


def get_connector(datasource_id: str | None = None):
    """Connector for one datasource, cached per id.

    Connections themselves are opened per statement; what is cached here is
    only the resolved path, so hundreds of registered databases cost nothing
    until they are actually queried.
    """
    source = get_registry().get(datasource_id)
    if source.id not in _connectors:
        _connectors[source.id] = build_connector(settings.db_backend, source.path)
    return _connectors[source.id], source


def _error(error_type: ErrorType, message: str) -> QueryResponse:
    return QueryResponse(status=QueryStatus.error, error_type=error_type, message=message)


@router.post("/query", response_model=QueryResponse, response_model_exclude_none=True)
async def query(request: QueryRequest) -> QueryResponse:
    question = (request.question or "").strip()
    if not question:
        return _error(ErrorType.internal, "Пустой вопрос.")

    max_rows = min(request.max_rows or settings.db_max_rows_safe, settings.db_max_rows_safe)
    hint_tables = list(request.hints.tables) if request.hints else None

    try:
        connector, source = get_connector(request.datasource_id)
    except KeyError as exc:
        available = ", ".join(s.id for s in get_registry().list()[:10])
        return _error(
            ErrorType.db_error,
            f"{exc.args[0]}. Доступные (первые 10): {available}",
        )
    except (ValueError, FileNotFoundError) as exc:
        logger.exception("connector unavailable")
        return _error(ErrorType.db_error, f"База данных недоступна: {exc}")

    try:
        outcome = await run_pipeline(
            question=question,
            connector=connector,
            max_rows=max_rows,
            hint_tables=hint_tables,
            db_id=source.id,
        )
    except ClarificationNeeded as exc:
        return QueryResponse(
            status=QueryStatus.need_clarification,
            question_to_user=exc.question_to_user,
        )
    except LLMUnavailableError as exc:
        return _error(ErrorType.llm_error, str(exc))
    except UnsafeSQLError as exc:
        # Logged loudly: this is either a model failure or an injection attempt.
        logger.warning("unsafe SQL rejected. session=%s reason=%s", request.session_id, exc)
        return _error(ErrorType.unsafe_sql, str(exc))
    except QueryTimeoutError as exc:
        return _error(ErrorType.timeout, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("query pipeline failed. session=%s", request.session_id)
        return _error(ErrorType.sql_error, str(exc))

    result = outcome.result
    # Result rows are deliberately absent from the log line — only shape.
    logger.info(
        "query ok. session=%s datasource=%s rows=%d truncated=%s tables=%s attempts=%s ms=%s",
        request.session_id,
        source.id,
        result.row_count,
        result.truncated,
        outcome.meta.get("selected_tables"),
        outcome.meta.get("critic_attempts"),
        outcome.meta.get("total_duration_ms"),
    )
    return QueryResponse(
        status=QueryStatus.ok,
        datasource_id=source.id,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        sql=outcome.sql,
        explanation=outcome.explanation,
        meta=outcome.meta,
    )


@router.get("/datasources", response_model=DatasourceListResponse)
async def datasources() -> DatasourceListResponse:
    registry = get_registry()
    return DatasourceListResponse(
        default_id=registry.default_id or "",
        count=len(registry),
        datasources=[
            DatasourceInfo(
                id=source.id,
                size_bytes=source.size_bytes,
                is_default=source.id == registry.default_id,
            )
            for source in registry.list()
        ],
    )


@router.get("/schema", response_model=SchemaResponse)
async def schema(datasource_id: str | None = None) -> SchemaResponse:
    connector, source = get_connector(datasource_id)
    tables = connector.list_tables()
    profile = load_profile(settings.profiles_dir_safe, source.id) if settings.use_profile else None
    profile_tables = (profile or {}).get("tables") or {}

    rendered: list[TableSchema] = []
    for table in tables:
        entry = profile_tables.get(table.name) or {}
        column_descriptions = {
            name: (data.get("description") or "")
            for name, data in (entry.get("columns") or {}).items()
        }
        rendered.append(
            TableSchema(
                name=table.name,
                description=(entry.get("description") or "").strip(),
                columns=table.columns,
                column_descriptions=column_descriptions,
            )
        )

    return SchemaResponse(
        db_id=source.id,
        overview=((profile or {}).get("db_overview") or "").strip(),
        tables=rendered,
    )


@router.get("/health")
async def health() -> dict:
    roles = {}
    for role in ("schema", "sql", "critic"):
        client = get_role_client(role)
        roles[role] = {"base_url": client.base_url, "reachable": await client.health()}

    db_ok = True
    db_error = None
    try:
        connector, _ = get_connector()
        connector.list_tables()
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = str(exc)

    ready = db_ok and all(r["reachable"] for r in roles.values())
    return {
        "status": "ok" if ready else "degraded",
        "db": {
            "backend": settings.db_backend,
            "ok": db_ok,
            "error": db_error,
            "datasources": len(get_registry()),
            "default": get_registry().default_id,
        },
        "roles": roles,
    }
