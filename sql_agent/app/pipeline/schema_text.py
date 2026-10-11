"""Rendering the database schema as DDL for the prompt.

Two things matter for accuracy and were carried over from the NL2SQL work:
example rows (three per table) and the ability to narrow the schema to the
tables the schema agent selected. Narrowing is the RAG step — it both cuts
prompt cost and removes the opportunity to join the wrong table.
"""
from __future__ import annotations

from typing import Iterable

from app.db.connector import TableInfo


def render_schema(tables: Iterable[TableInfo], filter_tables: list[str] | None = None) -> str:
    wanted = {t.lower() for t in filter_tables} if filter_tables is not None else None
    blocks: list[str] = []

    for table in tables:
        if wanted is not None and table.name.lower() not in wanted:
            continue

        if table.ddl:
            create_stmt = table.ddl.strip().rstrip(";") + ";"
        else:
            column_defs = ",\n    ".join(f"{c.name} {c.type.value}" for c in table.columns)
            create_stmt = f"CREATE TABLE {table.name} (\n    {column_defs}\n);"

        block = create_stmt
        if table.sample_rows:
            rendered_rows = "\n".join(
                "  " + str(tuple(str(value) for value in row)) for row in table.sample_rows
            )
            block += f"\n/* 3 example rows from table {table.name}:\n{rendered_rows}\n*/"
        blocks.append(block)

    return "\n\n".join(blocks) if blocks else "Unknown Schema"


def select_tables(raw_answer: str, all_tables: list[str]) -> list[str]:
    """Match the schema agent's free-form answer against real table names.

    Substring matching is deliberately permissive — the agent may answer with
    prose around the names. When nothing matches, the caller falls back to the
    full schema rather than failing the question.
    """
    lowered = (raw_answer or "").lower()
    return [name for name in all_tables if name.lower() in lowered]
