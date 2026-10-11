"""Прогон правок «в стиле МТС» через chart_agent: вопрос к русской базе PAUQ → график →
«Подтвердить» → генеративная правка (диффузия). Автовалидация выключена: судья
запускается отдельно (scripts/judge_edits.py) на VL-модели, как в дипломе Матвея.

    .venv/bin/python scripts/run_mts_edits.py -o МТС_ПРАВКИ --phase chart   # вопрос → график → Подтвердить
    .venv/bin/python scripts/run_mts_edits.py -o МТС_ПРАВКИ --phase edit    # правка диффузией в той же сессии
Фазы разделены, чтобы LoRA-модели SQL-агента и FLUX не жили в памяти одновременно;
сессии между фазами хранятся в Redis оркестратора.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("CHART_AGENT_URL", "http://127.0.0.1:8010").rstrip("/")
TIMEOUT = 900
# Приписка из диплома Матвея (табл. 1) — к каждому промпту.
KEEP = "Сохрани график 1 в 1. Оси, подписи и масштаб должны быть идентичными исходному графику."
# Роутер правок Матвея отправляет «чисто цветовые» правки в код matplotlib, а диплом — про
# диффузию. Сигнальные слова из его же промпта роутера («нарисуй», «нейросеть», «стиль»)
# заставляют все уровни идти одним путём — через модель редактирования изображений.
PREFIX = "Нарисуй нейросетью в новом стиле: "

ITEMS = [
    dict(n=1, level=1, db="pauq_world_1", q="построй график: топ-10 стран по населению",
         edit="Замени цвета графика на ярко-красный. Фон сделай белым, сетку и оси — чёрными."),
    dict(n=2, level=1, db="pauq_world_1", q="сколько стран в каждом континенте — построй диаграмму",
         edit="Сделай фон сплошным красным, столбцы и весь текст — белыми."),
    dict(n=3, level=1, db="pauq_flight_2", q="топ-10 аэропортов по числу вылетов — построй график",
         edit="Оставь только три цвета: красный, белый и чёрный — самый большой столбец красный, остальные белые с чёрной обводкой."),
    dict(n=4, level=2, db="pauq_car_1", q="построй график: сколько моделей машин с каждым числом цилиндров",
         edit="Сделай столбцы в форме белых яиц на красном фоне — высота яйца равна высоте столбца."),
    dict(n=5, level=2, db="pauq_car_1", q="средний расход топлива по годам выпуска — построй линейный график",
         edit="Замени точки на линейном графике на маленькие белые яйца, линию сделай красной."),
    dict(n=6, level=2, db="pauq_flight_2", q="сколько рейсов у каждой авиакомпании — диаграмма",
         edit="Скругли верх столбцов так, чтобы каждый заканчивался куполом как верхушка яйца; столбцы красные, фон белый."),
    dict(n=7, level=2, db="pauq_car_1", q="Какие мощность и расход топлива у каждой машины?",
         edit="Круги на диаграмме рассеяния замени на белые яйца с красной обводкой."),
    dict(n=8, level=3, db="pauq_wta_1", q="топ-10 стран по числу теннисисток — построй график",
         edit="Перерисуй столбцы как настоящие белые куриные яйца, стоящие вертикально на красной скатерти; чем выше значение, тем крупнее яйцо."),
    dict(n=9, level=3, db="pauq_world_1", q="круговая диаграмма: сколько стран на каждом континенте, с названиями континентов в подписях долей",
         edit="Перерисуй круговую диаграмму как разрезанное сверху варёное яйцо на красной тарелке, каждая доля — кусок яйца."),
    dict(n=10, level=3, db="pauq_wta_1", q="число матчей по годам — построй линейный график",
         edit="Дорисуй за графиком красную студийную стену с мягким светом, а линию графика сделай белым шнуром, на котором висят белые яйца в точках данных."),
]


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def message(sid: str, content: str, **flags) -> dict:
    body = {"type": "message", "content": content, "images_base64": [], "csv_data": None, "value": None,
            "auto_validate_enabled": False, "generation_seed": 42, "no_text_mode": False}
    body.update(flags)
    return call("POST", f"/sessions/{sid}/messages", body)


def decision(sid: str, value: str) -> dict:
    return call("POST", f"/sessions/{sid}/messages",
                {"type": "decision", "value": value, "content": "", "images_base64": []})


def save_png(b64: str | None, path: Path) -> str | None:
    if not b64:
        return None
    path.write_bytes(base64.b64decode(b64))
    return path.name


def run_chart(item: dict, out: Path) -> dict:
    """Вопрос к базе → график → «Подтвердить». Возвращает запись со status=chart_ok|error."""
    rec = dict(item, edit_prompt=f"{PREFIX}{item['edit']} {KEEP}", status="error", error=None)
    sid = call("POST", "/sessions")["session_id"]
    rec["session_id"] = sid

    t0 = time.time()
    r1 = message(sid, item["q"], use_sql_source=True, sql_datasource_id=item["db"])
    rec["t_chart"] = round(time.time() - t0)
    art = r1.get("artefacts") or {}
    plot_b64 = (art.get("plot") or {}).get("image_base64")
    rec["assistant_message_chart"] = r1.get("assistant_message")
    src = ((art.get("data") or {}).get("sql_source") or {})
    rec["sql"] = src.get("sql")
    rec["sql_explanation"] = src.get("explanation")
    rec["row_count"] = src.get("row_count")
    rec["code"] = (art.get("plot") or {}).get("code")
    rec["before_png"] = save_png(plot_b64, out / f"{item['n']:02d}_before.png")
    if not plot_b64 or not r1.get("show_approve_cancel"):
        rec["error"] = f"график не построен: stage={r1.get('current_stage')} msg={r1.get('assistant_message')}"
        return rec
    decision(sid, "approve")
    rec["status"] = "chart_ok"
    return rec


def run_edit(rec: dict, out: Path) -> dict:
    """Генеративная правка в уже подтверждённой сессии. status → ok|error."""
    rec = dict(rec, error=None)
    t1 = time.time()
    r3 = message(rec["session_id"], rec["edit_prompt"], use_sql_source=False)
    rec["t_edit"] = round(time.time() - t1)
    img = ((r3.get("artefacts") or {}).get("image") or {})
    rec["assistant_message_edit"] = r3.get("assistant_message")
    rec["enhanced_prompt"] = img.get("enhanced_prompt")
    rec["after_png"] = save_png(img.get("image_base64"), out / f"{rec['n']:02d}_after.png")
    if not rec["after_png"]:
        rec["status"] = "error"
        rec["error"] = f"картинка не сгенерирована: stage={r3.get('current_stage')} msg={r3.get('assistant_message')}"
        return rec
    rec["status"] = "ok"
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="МТС_ПРАВКИ")
    ap.add_argument("--phase", choices=["chart", "edit"], required=True)
    ap.add_argument("--only", default="", help="номера через запятую")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    results_path = out / "mts_edits.json"
    results: dict[str, dict] = {}
    if results_path.exists():
        results = {str(r["n"]): r for r in json.load(open(results_path, encoding="utf-8"))}
    only = {int(x) for x in args.only.split(",") if x.strip()}

    def dump() -> None:
        json.dump([results[k] for k in sorted(results, key=int)], open(results_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    for item in ITEMS:
        if only and item["n"] not in only:
            continue
        n = str(item["n"])
        try:
            if args.phase == "chart":
                print(f"[{n}/10] ур.{item['level']} {item['db']:<14} {item['q'][:55]}", file=sys.stderr, flush=True)
                rec = run_chart(item, out)
            else:
                rec = results.get(n)
                if rec and rec["status"] == "ok" and rec.get("after_png"):
                    continue  # уже есть картинка
                if not rec or not rec.get("session_id") or not rec.get("before_png"):
                    print(f"[{n}/10] нет графика — пропуск", file=sys.stderr)
                    continue
                print(f"[{n}/10] ур.{item['level']} правка: {item['edit'][:60]}", file=sys.stderr, flush=True)
                rec = run_edit(rec, out)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            rec = dict(results.get(n) or item, edit_prompt=f"{PREFIX}{item['edit']} {KEEP}", status="error", error=f"transport: {exc}")
        results[n] = rec
        mark = "✓" if rec["status"] in {"ok", "chart_ok"} else "✗"
        took = rec.get("t_chart" if args.phase == "chart" else "t_edit", "-")
        print(f"      {mark} {took}с" + (f" — {rec['error']}" if rec.get("error") else ""), file=sys.stderr, flush=True)
        dump()
    done = sum(1 for r in results.values() if r["status"] == ("chart_ok" if args.phase == "chart" else "ok"))
    print(f"\nфаза {args.phase}: {done}/{len(results)} → {results_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
