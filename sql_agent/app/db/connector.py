"""Database access for the SQL agent.

`DBConnector` is the seam a second backend plugs into. Only SQLite is
implemented for now (that is what the NL2SQL pipeline was measured on); a
PostgreSQL connector implements the same three methods and nothing above this
layer changes.

Everything here is read-only by construction:
  * SQLite is opened through a `file:...?mode=ro` URI;
  * every statement passes `validate_single_select` first;
  * a row cap is applied and a hard fetch limit enforces it;
  * a statement timeout aborts long queries via a progress handler.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.api.schemas import ColumnSpec, ColumnType
from app.db.safety import apply_row_cap, validate_single_select

logger = logging.getLogger(__name__)


class QueryTimeoutError(RuntimeError):
    """Raised when a statement exceeded the configured timeout."""


@dataclass(slots=True)
class QueryResult:
    columns: list[ColumnSpec]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: float
    column_types_raw: dict[str, str] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(slots=True)
class TableInfo:
    name: str
    columns: list[ColumnSpec]
    ddl: str = ""
    sample_rows: list[list[Any]] = field(default_factory=list)


class DBConnector(ABC):
    """Read-only access to one datasource."""

    @abstractmethod
    def list_tables(self) -> list[TableInfo]:
        """Tables with column names and types, plus a few example rows."""

    @abstractmethod
    def execute(self, sql: str, max_rows: int, timeout_sec: float) -> QueryResult:
        """Run one validated SELECT and return at most `max_rows` rows."""

    @abstractmethod
    def probe(self, sql: str, timeout_sec: float) -> str | None:
        """Run a statement for the critic loop. Returns an error string or None."""


# ── SQLite ────────────────────────────────────────────────────────────────

_SQLITE_TYPE_MAP = (
    (("int",), ColumnType.number),
    (("real", "floa", "doub", "num", "dec"), ColumnType.number),
    (("bool",), ColumnType.boolean),
    (("date", "time"), ColumnType.datetime),
    (("char", "clob", "text"), ColumnType.string),
)


def map_sqlite_type(declared: str) -> ColumnType:
    """Map a declared SQLite type to the contract's column type.

    Declared types are used rather than value inspection on purpose: telling a
    year from a four-digit amount by looking at values is guesswork, and the
    database already knows the answer.
    """
    lowered = (declared or "").strip().lower()
    if not lowered:
        return ColumnType.unknown
    for needles, mapped in _SQLITE_TYPE_MAP:
        if any(needle in lowered for needle in needles):
            return mapped
    return ColumnType.unknown


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return value


class SQLiteConnector(DBConnector):
    def __init__(self, db_path: str) -> None:
        if not db_path:
            raise ValueError("DB_PATH is not configured")
        # Paths come from .env, where writing ~ is the natural thing to do.
        resolved = os.path.expanduser(db_path)
        if not os.path.exists(resolved):
            raise FileNotFoundError(f"database file not found: {resolved}")
        self.db_path = resolved

    def _connect(self, timeout_sec: float) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=timeout_sec)
        conn.text_factory = bytes
        deadline = time.monotonic() + timeout_sec

        def _guard() -> int:
            # Non-zero aborts the running statement. Checked every N vm steps.
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(_guard, 10_000)
        return conn

    def list_tables(self) -> list[TableInfo]:
        conn = self._connect(timeout_sec=10.0)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            rows = [(_decode(n), _decode(s) or "") for n, s in cur.fetchall()]

            tables: list[TableInfo] = []
            for name, ddl in rows:
                cur.execute(f'PRAGMA table_info("{name}")')
                columns = [
                    ColumnSpec(name=_decode(r[1]), type=map_sqlite_type(_decode(r[2])))
                    for r in cur.fetchall()
                ]
                samples: list[list[Any]] = []
                try:
                    cur.execute(f'SELECT * FROM "{name}" LIMIT 3')
                    samples = [[_decode(v) for v in row] for row in cur.fetchall()]
                except sqlite3.Error:
                    pass
                tables.append(
                    TableInfo(name=name, columns=columns, ddl=ddl, sample_rows=samples)
                )
            return tables
        finally:
            conn.close()

    def execute(self, sql: str, max_rows: int, timeout_sec: float) -> QueryResult:
        validate_single_select(sql)
        # Cap at max_rows + 1 so that one surplus row can be observed: that is
        # what distinguishes "exactly max_rows rows exist" from "there are more
        # and we cut them off". `truncated` has to be honest — a chart built on
        # a silently clipped result set is wrong without saying so.
        capped = apply_row_cap(sql, max_rows + 1)

        conn = self._connect(timeout_sec)
        started = time.perf_counter()
        try:
            cur = conn.cursor()
            try:
                cur.execute(capped)
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    raise QueryTimeoutError(
                        f"Запрос превысил лимит {timeout_sec:.0f} с."
                    ) from exc
                raise

            description = cur.description or []
            names = [_decode(d[0]) for d in description]

            # Fetch one extra row to detect truncation honestly.
            fetched = cur.fetchmany(max_rows + 1)
            truncated = len(fetched) > max_rows
            fetched = fetched[:max_rows]
            rows = [[_decode(v) for v in row] for row in fetched]

            declared = self._declared_types_for(cur, conn, names)
            columns = [
                ColumnSpec(name=n, type=map_sqlite_type(declared.get(n, "")))
                for n in names
            ]
            # A column with no declared type (an expression such as SUM(x))
            # falls back to the type of the first non-null value.
            self._infer_unknown_from_values(columns, rows)

            duration_ms = (time.perf_counter() - started) * 1000.0
            return QueryResult(
                columns=columns,
                rows=rows,
                truncated=truncated,
                duration_ms=duration_ms,
                column_types_raw=declared,
            )
        finally:
            conn.close()

    def probe(self, sql: str, timeout_sec: float) -> str | None:
        """Execute for the critic loop; return the engine's error text, if any."""
        try:
            validate_single_select(sql)
        except ValueError as exc:
            return str(exc)

        conn = self._connect(timeout_sec)
        try:
            cur = conn.cursor()
            cur.execute(apply_row_cap(sql, 1))
            rows = cur.fetchmany(1)
        except QueryTimeoutError as exc:
            return str(exc)
        except sqlite3.Error as exc:
            if "interrupted" in str(exc).lower():
                return f"Запрос превысил лимит {timeout_sec:.0f} с."
            return str(exc)
        finally:
            conn.close()

        if not rows:
            # An empty result is treated as a logic error, not a success: a
            # syntactically valid query with a wrong JOIN or WHERE returns
            # zero rows just as readily as a correct one over an empty range.
            return (
                "Warning: The query executed successfully but returned 0 rows. "
                "This might mean your WHERE conditions or JOINs are logically incorrect."
            )
        return None

    def _declared_types_for(
        self, cur: sqlite3.Cursor, conn: sqlite3.Connection, names: list[str]
    ) -> dict[str, str]:
        """Best-effort declared types for the result columns.

        SQLite does not report types for a result set, so column names are
        matched back against the tables mentioned in the query.
        """
        declared: dict[str, str] = {}
        try:
            probe = conn.cursor()
            probe.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            for (table_raw,) in probe.fetchall():
                table = _decode(table_raw)
                probe.execute(f'PRAGMA table_info("{table}")')
                for row in probe.fetchall():
                    col_name = _decode(row[1])
                    if col_name in names and col_name not in declared:
                        declared[col_name] = _decode(row[2]) or ""
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.debug("declared type lookup failed: %s", exc)
        return declared

    @staticmethod
    def _infer_unknown_from_values(columns: list[ColumnSpec], rows: list[list[Any]]) -> None:
        for idx, column in enumerate(columns):
            if column.type != ColumnType.unknown:
                continue
            for row in rows:
                if idx >= len(row):
                    continue
                value = row[idx]
                if value is None:
                    continue
                if isinstance(value, bool):
                    column.type = ColumnType.boolean
                elif isinstance(value, (int, float)):
                    column.type = ColumnType.number
                elif isinstance(value, str):
                    column.type = ColumnType.string
                break


def build_connector(backend: str, db_path: str) -> DBConnector:
    normalised = (backend or "sqlite").strip().lower()
    if normalised == "sqlite":
        return SQLiteConnector(db_path)
    raise ValueError(
        f"DB_BACKEND='{normalised}' is not implemented; only 'sqlite' is available."
    )
