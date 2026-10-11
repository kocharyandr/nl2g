#!/usr/bin/env python3
"""Ad-hoc querying of the SQL agent from the command line.

    scripts/ask.py "топ-5 стран по числу энергоблоков"
    scripts/ask.py -d TheHistoryofBaseball "сколько игроков в каждой команде"
    scripts/ask.py --list | grep -i base
    scripts/ask.py --schema -d concert_singer
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def call(url: str, payload: dict | None = None, timeout: float = 900.0) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        sys.exit(f"сервис недоступен по {url}: {exc}")


def render_table(columns: list[dict], rows: list[list]) -> str:
    names = [c["name"] for c in columns]
    grid = [names] + [["" if v is None else str(v) for v in row] for row in rows]
    widths = [max(len(row[i]) for row in grid) for i in range(len(names))]
    line = "  ".join("-" * w for w in widths)
    out = ["  ".join(n.ljust(w) for n, w in zip(names, widths)), line]
    out += ["  ".join(c.ljust(w) for c, w in zip(row, widths)) for row in grid[1:]]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", help="вопрос на естественном языке")
    parser.add_argument("-d", "--datasource", help="id базы (по умолчанию — из конфигурации сервиса)")
    parser.add_argument("-n", "--max-rows", type=int, default=20)
    parser.add_argument("-u", "--url", default="http://localhost:8500")
    parser.add_argument("--list", action="store_true", help="показать доступные базы")
    parser.add_argument("--schema", action="store_true", help="показать схему базы")
    parser.add_argument("--json", action="store_true", help="сырой JSON-ответ")
    args = parser.parse_args()

    base = args.url.rstrip("/")

    if args.list:
        data = call(f"{base}/datasources")
        for source in data["datasources"]:
            mark = " *" if source["is_default"] else ""
            print(f"{source['id']:<32}{source['size_bytes'] / 1e6:9.1f} МБ{mark}")
        print(f"\nвсего {data['count']}, по умолчанию помечен *")
        return

    if args.schema:
        suffix = f"?datasource_id={args.datasource}" if args.datasource else ""
        data = call(f"{base}/schema{suffix}")
        print(f"# {data['db_id']}")
        if data.get("overview"):
            print(data["overview"], end="\n\n")
        for table in data["tables"]:
            print(f"{table['name']}: {table.get('description', '')}".rstrip(": "))
            for column in table["columns"]:
                note = table.get("column_descriptions", {}).get(column["name"], "")
                print(f"    {column['name']:<28} {column['type']:<9} {note}".rstrip())
            print()
        return

    if not args.question:
        parser.error("нужен вопрос (или --list / --schema)")

    payload = {"question": args.question, "max_rows": args.max_rows}
    if args.datasource:
        payload["datasource_id"] = args.datasource
    result = call(f"{base}/query", payload)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    status = result["status"]
    if status == "need_clarification":
        print(f"нужно уточнение: {result['question_to_user']}")
        sys.exit(2)
    if status != "ok":
        print(f"ошибка [{result.get('error_type')}]: {result.get('message')}")
        sys.exit(1)

    meta = result.get("meta") or {}
    print(f"-- база: {result.get('datasource_id')}  таблицы: {meta.get('selected_tables')}"
          f"  попыток критика: {meta.get('critic_attempts')}  {meta.get('total_duration_ms', 0) / 1000:.1f}с")
    print(f"-- {result['explanation']}")
    print(" ".join(result["sql"].split()))
    print()
    print(render_table(result["columns"], result["rows"]))
    tail = f"\nстрок: {result['row_count']}"
    if result["truncated"]:
        tail += " (выборка обрезана по лимиту — уточните условия отбора)"
    print(tail)


if __name__ == "__main__":
    main()
