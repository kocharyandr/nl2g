"""Validation of generated SQL before it reaches the database.

This is the last line of defence, not the first: the database role is
read-only at the permission level. But prompt injection through the user's
question is a realistic scenario, and "the model was trained not to do that"
is not an argument, so every statement is parsed and checked here too.

Rules (INTEGRATION_SQL_SOURCE.md §5):
  * exactly one statement — no `;`-chained expressions;
  * that statement is a SELECT (a leading WITH ... SELECT is allowed);
  * no write/DDL keywords anywhere outside string literals;
  * no system tables.
"""
from __future__ import annotations

import re

# Statements that must never appear, even inside a subquery.
FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "truncate", "alter", "create",
    "replace", "grant", "revoke", "attach", "detach", "vacuum", "reindex",
    "pragma", "commit", "rollback", "savepoint", "begin",
)

# Names that expose engine internals rather than user data.
FORBIDDEN_TABLES = (
    "sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_sequence",
    "pg_catalog", "pg_class", "pg_user", "pg_shadow", "information_schema",
)


class UnsafeSQLError(ValueError):
    """Raised when generated SQL fails validation. Message is user-facing."""


def strip_sql_noise(sql: str) -> str:
    """Remove comments and string literals so keyword checks can't be fooled.

    Replaces literals with a placeholder rather than deleting them, so that
    token boundaries around them are preserved.
    """
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    without_line = re.sub(r"--[^\n]*", " ", without_block)
    without_single = re.sub(r"'(?:''|[^'])*'", " 'lit' ", without_line)
    without_double = re.sub(r'"(?:""|[^"])*"', ' "id" ', without_single)
    return without_double


def split_statements(sql: str) -> list[str]:
    """Split on `;` after literals and comments have been neutralised."""
    cleaned = strip_sql_noise(sql)
    return [part.strip() for part in cleaned.split(";") if part.strip()]


def validate_single_select(sql: str) -> None:
    """Raise UnsafeSQLError unless `sql` is exactly one read-only SELECT."""
    raw = (sql or "").strip()
    if not raw:
        raise UnsafeSQLError("Пустой SQL-запрос.")

    statements = split_statements(raw)
    if len(statements) == 0:
        raise UnsafeSQLError("SQL не содержит ни одного выражения.")
    if len(statements) > 1:
        raise UnsafeSQLError(
            f"Разрешено ровно одно выражение SELECT, получено {len(statements)}."
        )

    statement = statements[0]
    lowered = statement.lower()

    if not re.match(r"^\s*(select|with)\b", lowered):
        first_word = lowered.split(None, 1)[0] if lowered.split() else "?"
        raise UnsafeSQLError(f"Разрешён только SELECT, получено '{first_word}'.")

    if lowered.startswith("with") and not re.search(r"\bselect\b", lowered):
        raise UnsafeSQLError("Выражение WITH должно завершаться SELECT.")

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise UnsafeSQLError(f"Запрещённая операция в SQL: {keyword.upper()}.")

    for table in FORBIDDEN_TABLES:
        if re.search(rf"\b{re.escape(table)}\b", lowered):
            raise UnsafeSQLError(f"Обращение к системной таблице запрещено: {table}.")


def has_limit(sql: str) -> bool:
    """True when the outermost statement already carries a LIMIT."""
    return bool(re.search(r"\blimit\b", strip_sql_noise(sql).lower()))


def apply_row_cap(sql: str, max_rows: int) -> str:
    """Append a LIMIT so an unbounded SELECT cannot drag the whole table over HTTP.

    A query that sets its own LIMIT is left alone: the caller's intent wins,
    and the fetch loop enforces the hard cap regardless.
    """
    trimmed = (sql or "").strip().rstrip(";").strip()
    if has_limit(trimmed):
        return trimmed
    return f"{trimmed} LIMIT {int(max_rows)}"
