"""Wire contract for the SQL agent service.

Shapes follow INTEGRATION_SQL_SOURCE.md §3 exactly. Two properties of the
contract are load-bearing and must not be relaxed:

* `columns` carries types coming from the database, so chart_agent never has
  to infer them from values — an inference that is ambiguous by nature.
* `sql` and `explanation` are present on success, because the user has to be
  able to check which query the chart was built from.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class QueryStatus(str, Enum):
    ok = "ok"
    need_clarification = "need_clarification"
    error = "error"


class ErrorType(str, Enum):
    sql_error = "sql_error"
    llm_error = "llm_error"
    unsafe_sql = "unsafe_sql"
    db_error = "db_error"
    timeout = "timeout"
    internal = "internal"


class ColumnType(str, Enum):
    string = "string"
    number = "number"
    boolean = "boolean"
    datetime = "datetime"
    unknown = "unknown"


class ColumnSpec(BaseModel):
    name: str
    type: ColumnType = ColumnType.unknown


class QueryHints(BaseModel):
    schema_name: str | None = Field(default=None, alias="schema")
    tables: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural-language question.")
    session_id: str | None = Field(default=None, description="chart_agent session id, for tracing only.")
    datasource_id: str | None = Field(
        default=None,
        description="Which database to query; omit for the configured default.",
    )
    max_rows: int | None = Field(default=None, description="Row cap; server clamps to DB_MAX_ROWS.")
    hints: QueryHints | None = Field(default=None)


class QueryResponse(BaseModel):
    status: QueryStatus

    # status=ok
    columns: list[ColumnSpec] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    sql: str = ""
    explanation: str = ""

    datasource_id: str = ""

    # status=need_clarification
    question_to_user: str | None = None

    # status=error
    error_type: ErrorType | None = None
    message: str | None = None

    # diagnostics — never contains result data, only shape and timings
    meta: dict[str, Any] = Field(default_factory=dict)


class TableSchema(BaseModel):
    name: str
    description: str = ""
    columns: list[ColumnSpec] = Field(default_factory=list)
    column_descriptions: dict[str, str] = Field(default_factory=dict)


class DatasourceInfo(BaseModel):
    id: str
    size_bytes: int = 0
    is_default: bool = False


class DatasourceListResponse(BaseModel):
    default_id: str = ""
    count: int = 0
    datasources: list[DatasourceInfo] = Field(default_factory=list)


class SchemaResponse(BaseModel):
    db_id: str = ""
    overview: str = ""
    tables: list[TableSchema] = Field(default_factory=list)
