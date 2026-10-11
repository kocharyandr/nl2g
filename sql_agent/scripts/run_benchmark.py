#!/usr/bin/env python3
"""Run gold questions from the KaggleDBQA test split through the service.

Produces one JSON record per question with everything needed to judge it:
the question, the gold SQL, the SQL the pipeline generated, which tables the
schema agent picked, how many critic attempts it took, and both result sets.

Execution accuracy is computed the same way the diploma measured it — set
equality of returned rows — and is only a *proposal*: the reviewer overrides
it in the report.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

KAGGLE = os.path.expanduser("~/education/KaggleDBQA")
SERVICE = os.environ.get("SQL_AGENT_URL", "http://localhost:8500")


def load_gold(limit_per_db: int, only_db: str | None) -> list[dict]:
    items = []
    for path in sorted(glob.glob(os.path.join(KAGGLE, "examples", "*_test.json"))):
        db_id = os.path.basename(path).replace("_test.json", "")
        if only_db and db_id != only_db:
            continue
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        for entry in data[:limit_per_db]:
            items.append({
                "db_id": db_id,
                "question": (entry.get("question") or "").strip(),
                "gold_sql": (entry.get("query") or "").strip(),
            })
    return items


def db_path(db_id: str) -> str:
    return os.path.join(KAGGLE, "databases", db_id, f"{db_id}.sqlite")


def execute(db_id: str, sql: str, limit: int = 200):
    """Run SQL directly for the gold side. Returns (rows, error)."""
    if not sql:
        return None, "empty sql"
    try:
        conn = sqlite3.connect(f"file:{db_path(db_id)}?mode=ro", uri=True, timeout=20)
        conn.text_factory = bytes
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(limit)
        conn.close()
        decoded = [
            tuple(v.decode("utf-8", "ignore") if isinstance(v, bytes) else v for v in row)
            for row in rows
        ]
        return decoded, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def ask(question: str, db_id: str, max_rows: int) -> dict:
    payload = json.dumps({
        "question": question, "datasource_id": db_id, "max_rows": max_rows,
    }).encode()
    request = urllib.request.Request(
        f"{SERVICE}/query", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.load(response)


def rows_equal(pred, gold) -> bool:
    """Set equality, as in the diploma's execution-accuracy metric."""
    if pred is None or gold is None:
        return False
    return {tuple(r) for r in pred} == {tuple(r) for r in gold}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--per-db", type=int, default=5)
    parser.add_argument("-d", "--db", default=None)
    parser.add_argument("-m", "--max-rows", type=int, default=200)
    parser.add_argument("-o", "--out", default="benchmark_results.json")
    args = parser.parse_args()

    items = load_gold(args.per_db, args.db)
    print(f"вопросов: {len(items)}", file=sys.stderr)

    results = []
    for index, item in enumerate(items, 1):
        started = time.monotonic()
        record = dict(item)
        try:
            response = ask(item["question"], item["db_id"], args.max_rows)
        except (urllib.error.URLError, TimeoutError) as exc:
            response = {"status": "error", "error_type": "transport", "message": str(exc)}

        meta = response.get("meta") or {}
        record.update({
            "status": response.get("status"),
            "pred_sql": response.get("sql", ""),
            "explanation": response.get("explanation", ""),
            "columns": [c["name"] for c in response.get("columns", [])],
            "column_types": [c["type"] for c in response.get("columns", [])],
            "pred_rows": response.get("rows", [])[:20],
            "pred_row_count": response.get("row_count", 0),
            "truncated": response.get("truncated", False),
            "error_type": response.get("error_type"),
            "message": response.get("message"),
            "selected_tables": meta.get("selected_tables", []),
            "critic_attempts": meta.get("critic_attempts"),
            "profile_used": meta.get("profile_used"),
            "elapsed_sec": round(time.monotonic() - started, 1),
        })

        gold_rows, gold_err = execute(item["db_id"], item["gold_sql"])
        pred_rows, pred_err = (
            execute(item["db_id"], record["pred_sql"]) if record["pred_sql"] else (None, "no sql")
        )
        record["gold_rows"] = [list(r) for r in (gold_rows or [])][:20]
        record["gold_error"] = gold_err
        record["pred_exec_error"] = pred_err
        record["auto_exec_match"] = rows_equal(pred_rows, gold_rows)

        results.append(record)
        mark = "✓" if record["auto_exec_match"] else "✗"
        print(
            f"[{index}/{len(items)}] {mark} {item['db_id']:<24} {record['elapsed_sec']:>5.1f}с  "
            f"{item['question'][:56]}",
            file=sys.stderr,
        )

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)

    matched = sum(1 for r in results if r["auto_exec_match"])
    print(f"\nавто-EX: {matched}/{len(results)} = {matched/max(1,len(results))*100:.1f}%", file=sys.stderr)
    print(f"записано: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
