"""Schema profile: human-readable descriptions of tables and columns.

Profiles are produced ahead of time by the NL2SQL schema profiler and cached
as one JSON per database. They are the single cheapest accuracy lever measured
in the NL2SQL work (+4.9 p.p. execution accuracy, concentrated on simple
questions), so they are on by default when a profile file exists.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_cache: dict[str, dict | None] = {}


def load_profile(profiles_dir: str, db_id: str) -> dict | None:
    if not profiles_dir or not db_id:
        return None
    key = f"{profiles_dir}::{db_id}"
    if key in _cache:
        return _cache[key]

    path = os.path.join(profiles_dir, f"{db_id}.json")
    if not os.path.exists(path):
        _cache[key] = None
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            _cache[key] = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read profile %s: %s", path, exc)
        _cache[key] = None
    return _cache[key]


def format_profile_block(profile: dict | None, filter_tables: list[str] | None = None) -> str:
    """Render a profile as prompt text, optionally narrowed to some tables."""
    if not profile:
        return ""

    lines: list[str] = []
    overview = (profile.get("db_overview") or "").strip()
    if overview:
        lines.append(f"Database overview: {overview}")
        lines.append("")

    wanted = {t.lower() for t in filter_tables} if filter_tables is not None else None
    for table_name, table_data in (profile.get("tables") or {}).items():
        if wanted is not None and table_name.lower() not in wanted:
            continue
        description = (table_data.get("description") or "").strip()
        lines.append(f"Table {table_name}: {description}" if description else f"Table {table_name}:")
        for column_name, column_data in (table_data.get("columns") or {}).items():
            column_description = (column_data.get("description") or "").strip()
            if column_description:
                lines.append(f"  - {column_name}: {column_description}")
        lines.append("")

    return "\n".join(lines).rstrip()
