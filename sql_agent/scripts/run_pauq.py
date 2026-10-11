#!/usr/bin/env python3
"""Параллельный прогон PAUQ: один и тот же вопрос по-русски и по-английски.

PAUQ — русская адаптация Spider с общими id у языковых версий. Берутся только
пары с *дословно одинаковым* гольд-SQL: тогда разница в точности объясняется
языком вопроса, а не переведёнными литералами внутри запроса.

Базы берутся из PAUQ (префикс pauq_), а не из Spider: в PAUQ дописаны русские
значения, и на оригинальных базах 63% гольд-ответов отличаются.

    scripts/run_pauq.py -n 50 -o pauq_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request

PAUQ = os.path.expanduser("~/education/datasets/pauq")
SERVICE = os.environ.get("SQL_AGENT_URL", "http://localhost:8500")


def load_pairs(limit: int, seed: int) -> list[dict]:
    ru = json.load(open(f"{PAUQ}/splits/ru_os_test.json", encoding="utf-8"))
    en = {x["id"]: x for x in json.load(open(f"{PAUQ}/splits/en_os_test.json", encoding="utf-8"))}

    pairs = []
    for item in ru:
        twin = en.get(item["id"])
        if not twin:
            continue
        # только дословно совпадающий гольд — иначе сравниваем языки нечестно
        if item["query"].strip() != twin["query"].strip():
            continue
        if not os.path.exists(db_path(item["db_id"])):
            continue
        pairs.append({
            "id": item["id"], "db_id": item["db_id"], "gold_sql": item["query"].strip(),
            "question_ru": item["question"].strip(), "question_en": twin["question"].strip(),
        })

    random.Random(seed).shuffle(pairs)
    return pairs[:limit]


def db_path(db_id: str) -> str:
    return f"{PAUQ}/database/{db_id}/pauq_{db_id}.sqlite"


def execute(db_id: str, sql: str, limit: int = 200):
    try:
        conn = sqlite3.connect(f"file:{db_path(db_id)}?mode=ro", uri=True, timeout=20)
        conn.text_factory = bytes
        rows = conn.cursor().execute(sql).fetchmany(limit)
        conn.close()
        return [tuple(v.decode("utf-8", "ignore") if isinstance(v, bytes) else v for v in r)
                for r in rows], None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:80]


def ask(question: str, db_id: str, max_rows: int) -> dict:
    payload = json.dumps({"question": question, "datasource_id": f"pauq_{db_id}",
                          "max_rows": max_rows}, ensure_ascii=False).encode()
    req = urllib.request.Request(f"{SERVICE}/query", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def rows_equal(a, b) -> bool:
    if a is None or b is None:
        return False
    return {tuple(r) for r in a} == {tuple(r) for r in b}


def run_one(question: str, pair: dict, gold_rows, max_rows: int) -> dict:
    started = time.monotonic()
    try:
        resp = ask(question, pair["db_id"], max_rows)
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"status": "error", "message": str(exc)[:100], "sec": round(time.monotonic() - started)}

    pred_sql = resp.get("sql", "")
    pred_rows, pred_err = execute(pair["db_id"], pred_sql) if pred_sql else (None, "нет SQL")
    meta = resp.get("meta") or {}
    return {
        "status": resp.get("status"), "sql": pred_sql,
        "explanation": resp.get("explanation", ""),
        "rows": resp.get("rows", [])[:12], "row_count": resp.get("row_count", 0),
        "exec_error": pred_err, "exec_match": rows_equal(pred_rows, gold_rows),
        "tables": meta.get("selected_tables", []), "attempts": meta.get("critic_attempts"),
        "message": resp.get("message"), "sec": round(time.monotonic() - started),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--pairs", type=int, default=50)
    ap.add_argument("-m", "--max-rows", type=int, default=200)
    ap.add_argument("-s", "--seed", type=int, default=13)
    ap.add_argument("-o", "--out", default="pauq_results.json")
    args = ap.parse_args()

    pairs = load_pairs(args.pairs, args.seed)
    print(f"пар с идентичным гольд-SQL: {len(pairs)}", file=sys.stderr)

    results = []
    for i, pair in enumerate(pairs, 1):
        gold_rows, gold_err = execute(pair["db_id"], pair["gold_sql"])
        rec = dict(pair, gold_error=gold_err, gold_rows=[list(r) for r in (gold_rows or [])][:12])
        rec["ru"] = run_one(pair["question_ru"], pair, gold_rows, args.max_rows)
        rec["en"] = run_one(pair["question_en"], pair, gold_rows, args.max_rows)
        results.append(rec)

        mark = lambda r: "✓" if r.get("exec_match") else "✗"  # noqa: E731
        print(f"[{i}/{len(pairs)}] ru{mark(rec['ru'])} en{mark(rec['en'])} "
              f"{pair['db_id'][:20]:<20} {pair['question_ru'][:44]}", flush=True, file=sys.stderr)
        json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)

    ru_ok = sum(1 for r in results if r["ru"].get("exec_match"))
    en_ok = sum(1 for r in results if r["en"].get("exec_match"))
    n = len(results)
    print(f"\nEX ru: {ru_ok}/{n} = {ru_ok/max(1,n)*100:.1f}%", file=sys.stderr)
    print(f"EX en: {en_ok}/{n} = {en_ok/max(1,n)*100:.1f}%", file=sys.stderr)
    print(f"разрыв: {(en_ok-ru_ok)/max(1,n)*100:+.1f} п.п.", file=sys.stderr)


if __name__ == "__main__":
    main()
