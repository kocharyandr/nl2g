"""Прогон «сильных» русских вопросов PAUQ через весь сервис: вопрос → SQL-агент → pandas →
график → «Подтвердить» → генеративная правка «в стиле МТС» (диффузия) → судья Матвея.

Промпты правок — три уровня сложности из диплома Матвея (цвет → форма → реализм), с упором
на «яйцо»; подбираются по типу графика и чередуются по кругу. Фазы разделены, чтобы LoRA-модели,
FLUX и VL-судья не жили в памяти одновременно (см. scripts/run_pauq_charts_all.sh):
    --phase chart   вопрос → график → «Подтвердить»
    --phase edit    правка диффузией в той же сессии

Для каждого вопроса считается:
  sql_ex     — строки предсказанного SQL == строки эталонного (как EX в дипломе);
  chart_ex   — данные на графике (dataset_spec.points) совпадают с эталонным ответом:
               мультимножество чисел совпадает с одной из числовых колонок эталона,
               а подписи — с одной из текстовых (если подписи есть);
  styled_ex  — то же после правки стиля (не потерялись ли данные при перегенерации).

Результаты дописываются по одному в <out>/runs.json — прогон можно прервать и продолжить.

    .venv/bin/python scripts/run_pauq_charts.py -n 100 -o PAUQ_ГРАФИКИ_ПРОГОН
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

API = os.environ.get("CHART_AGENT_URL", "http://127.0.0.1:8010").rstrip("/")
PAUQ = Path(os.path.expanduser("~/education/datasets/pauq"))
SELECTION = Path(__file__).resolve().parents[1] / "PAUQ_ГРАФИКИ_ОТБОР" / "pauq_chart_questions_strong.json"
TIMEOUT = 900
KEEP = "Сохрани график 1 в 1. Оси, подписи и масштаб должны быть идентичными исходному графику."
PREFIX = "Нарисуй нейросетью в новом стиле: "  # иначе роутер Матвея уводит цветовые правки в код
# (уровень, код промпта, текст). Для каждого типа графика — свой круг; яйца — 60% столбчатых.
EDITS = {
    "bar": [
        (1, "красный", "Замени цвета графика на ярко-красный. Фон сделай белым, сетку и оси — чёрными."),
        (2, "яйца-столбцы", "Сделай столбцы в форме белых яиц на красном фоне — высота яйца равна высоте столбца."),
        (1, "инверсия", "Сделай фон сплошным красным, столбцы и весь текст — белыми."),
        (2, "купол-яйцо", "Скругли верх столбцов так, чтобы каждый заканчивался куполом как верхушка яйца; столбцы красные, фон белый."),
        (3, "настоящие яйца", "Перерисуй столбцы как настоящие белые куриные яйца, стоящие вертикально на красной скатерти; чем выше значение, тем крупнее яйцо."),
    ],
    "barh": [
        (1, "красный", "Замени цвета графика на ярко-красный. Фон сделай белым, сетку и оси — чёрными."),
        (2, "яйца-полосы", "Сделай полосы в форме вытянутых белых яиц на красном фоне — длина яйца равна длине полосы."),
        (1, "инверсия", "Сделай фон сплошным красным, полосы и весь текст — белыми."),
        (2, "купол-яйцо", "Скругли концы полос так, чтобы каждая заканчивалась куполом как верхушка яйца; полосы красные, фон белый."),
        (3, "настоящие яйца", "Перерисуй полосы как настоящие белые куриные яйца, лежащие на красной скатерти; чем больше значение, тем длиннее яйцо."),
    ],
    "line": [
        (1, "красный", "Сделай линию графика ярко-красной и толще, фон белый, оси и текст чёрные."),
        (2, "яйца-маркеры", "Замени точки на линейном графике на маленькие белые яйца, линию сделай красной."),
        (3, "шнур с яйцами", "Дорисуй за графиком красную студийную стену с мягким светом, а линию графика сделай белым шнуром, на котором висят белые яйца в точках данных."),
    ],
    "pie": [
        (1, "красный", "Замени цвета секторов на оттенки красного, фон белый, границы секторов белые."),
        (3, "варёное яйцо", "Перерисуй круговую диаграмму как разрезанное сверху варёное яйцо на красной тарелке, каждая доля — кусок яйца."),
    ],
    "scatter": [
        (1, "красный", "Сделай все точки ярко-красными, фон белый, оси чёрные."),
        (2, "яйца-точки", "Круги на диаграмме рассеяния замени на белые яйца с красной обводкой."),
    ],
}


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def message(sid: str, content: str, **flags) -> dict:
    body = {"type": "message", "content": content, "images_base64": [], "csv_data": None, "value": None,
            "auto_validate_enabled": False, "generation_seed": 42, "no_text_mode": False}
    body.update(flags)
    return call("POST", f"/sessions/{sid}/messages", body)


def db_file(db_id: str) -> Path:
    return PAUQ / "database" / db_id / f"pauq_{db_id}.sqlite"


def run_sql(db_id: str, sql: str, limit: int = 5000):
    try:
        con = sqlite3.connect(f"file:{db_file(db_id)}?mode=ro", uri=True)
        con.execute("pragma query_only=1")
        cur = con.execute(sql)
        return [list(r) for r in cur.fetchmany(limit)], None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return round(float(str(v).replace(",", ".")), 2)
    except ValueError:
        return None


def rows_equal(a, b) -> bool:
    # всё к строкам: в одной колонке SQLite бывают и числа, и текст — кортежи иначе не сортируются
    norm = lambda rows: sorted(tuple(str(num(v)) if num(v) is not None else str(v) for v in r) for r in rows)
    return a is not None and b is not None and norm(a) == norm(b)


def chart_matches(points: list[dict], gold: list[list]) -> dict:
    """Сверка данных графика с эталоном. Точки делятся на серии; числа каждой серии
    (мультимножество) должны совпасть с какой-то числовой колонкой эталона, а подписи —
    с какой-то его колонкой (если подписи есть)."""
    if not points or not gold:
        return {"ok": False, "values_ok": False, "labels_ok": None, "n_points": len(points or []), "n_gold": len(gold or [])}
    # строки с NULL на график попасть не могут (нет подписи или значения) — не считаем их потерей
    gold = [r for r in gold if all(v is not None for v in r)] or gold
    ncols = len(gold[0])
    gold_cols = [Counter(num(r[i]) for r in gold) for i in range(ncols)]
    series: dict = {}
    for pt in points:
        series.setdefault(pt.get("series"), []).append(pt)
    values_ok = all(Counter(num(pt.get("y")) for pt in pts) in gold_cols for pts in series.values())
    labels = {str(pt["label"]).strip() for pt in points if pt.get("label") not in (None, "")}
    labels_ok = None
    if labels:
        labels_ok = any({str(r[i]).strip() for r in gold} == labels for i in range(ncols)) or \
            any({str(num(r[i])) for r in gold} == {str(num(l)) for l in labels} for i in range(ncols))
    return {"ok": values_ok and labels_ok is not False, "values_ok": values_ok, "labels_ok": labels_ok,
            "n_points": len(points), "n_gold": len(gold), "n_series": len(series)}


def session_state(sid: str) -> dict:
    raw = subprocess.run(["redis-cli", "--raw", "get", f"chart_agent:state:{sid}"], capture_output=True, text=True).stdout
    return json.loads(raw) if raw.strip() else {}


def save_png(b64: str | None, path: Path) -> str | None:
    if not b64:
        return None
    path.write_bytes(base64.b64decode(b64))
    return path.name


def pick_edit(item: dict, counters: Counter) -> tuple[int, str, str]:
    kind = item.get("chart_type") if item.get("chart_type") in EDITS else "bar"
    pool = EDITS[kind]
    choice = pool[counters[kind] % len(pool)]
    counters[kind] += 1
    return choice


def run_chart(item: dict, out: Path, edit: tuple[int, str, str]) -> dict:
    rec = {k: item[k] for k in ("id", "split", "db_id", "question", "chart_type")}
    rec["level"], rec["edit_code"], rec["edit"] = edit
    rec["edit_prompt"] = f"{PREFIX}{rec['edit']} {KEEP}"
    rec["gold_sql"] = item["sql"]
    gold, _ = run_sql(item["db_id"], item["sql"])
    rec["gold_rows"] = gold[:60] if gold else gold
    rec["gold_n"] = len(gold) if gold else 0
    sid = call("POST", "/sessions")["session_id"]
    rec["session_id"] = sid

    t0 = time.time()
    r1 = message(sid, item["question"], use_sql_source=True, sql_datasource_id=f"pauq_{item['db_id']}")
    rec["t_chart"] = round(time.time() - t0)
    art = r1.get("artefacts") or {}
    src = ((art.get("data") or {}).get("sql_source") or {})
    rec.update(pred_sql=src.get("sql"), sql_explanation=src.get("explanation"), pred_n=src.get("row_count"),
               assistant_message=r1.get("assistant_message"), stage=r1.get("current_stage"))
    plot = art.get("plot") or {}
    rec["code"] = plot.get("code")
    rec["chart_png"] = save_png(plot.get("image_base64"), out / f"{item['id']}_chart.png")
    st = session_state(sid)
    rec["chart_attempt"] = st.get("chart_attempt")
    rec["errors"] = st.get("errors") or []
    pts = (((st.get("artefacts") or {}).get("data") or {}).get("understanding") or {}).get("dataset_spec", {}).get("points") or []
    rec["points"] = pts[:60]
    if rec["pred_sql"]:
        pred, pred_err = run_sql(item["db_id"], rec["pred_sql"])
        rec["pred_exec_error"] = pred_err
        rec["sql_ex"] = rows_equal(pred, gold)
    else:
        rec["sql_ex"] = False
    if not rec["chart_png"] or not r1.get("show_approve_cancel"):
        rec["outcome"] = "text_answer" if st.get("sql_scalar_answered") else (
            "clarification" if st.get("clarification_reason") else "no_chart")
        rec["chart_ex"] = {"ok": False}
        return rec
    rec["outcome"] = "chart"
    rec["chart_ex"] = chart_matches(pts, gold or [])
    call("POST", f"/sessions/{sid}/messages", {"type": "decision", "value": "approve", "content": "", "images_base64": []})
    rec["edit_status"] = "pending"
    return rec


def run_edit(rec: dict, out: Path) -> dict:
    rec = dict(rec)
    t1 = time.time()
    r = message(rec["session_id"], rec["edit_prompt"], use_sql_source=False)
    rec["t_edit"] = round(time.time() - t1)
    img = ((r.get("artefacts") or {}).get("image") or {})
    rec["enhanced_prompt"] = img.get("enhanced_prompt")
    rec["edit_message"] = r.get("assistant_message")
    rec["edit_png"] = save_png(img.get("image_base64"), out / f"{rec['id']}_mts.png")
    rec["edit_status"] = "ok" if rec["edit_png"] else "error"
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("-o", "--out", default="PAUQ_ГРАФИКИ_ПРОГОН")
    ap.add_argument("-s", "--seed", type=int, default=13)
    ap.add_argument("--phase", choices=["chart", "edit"], required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    strong = json.load(open(SELECTION, encoding="utf-8"))
    test = [x for x in strong if x["split"] == "test"]
    train = [x for x in strong if x["split"] == "train"]
    random.Random(args.seed).shuffle(train)
    items = (test + train)[: args.n]
    json.dump([x["id"] for x in items], open(out / "selection.json", "w"), indent=0)
    counters: Counter = Counter()
    edits = {x["id"]: pick_edit(x, counters) for x in items}  # детерминированно, до пропусков

    runs_path = out / "runs.json"
    runs = {r["id"]: r for r in json.load(open(runs_path, encoding="utf-8"))} if runs_path.exists() else {}
    dump = lambda: json.dump([runs[x["id"]] for x in items if x["id"] in runs], open(runs_path, "w", encoding="utf-8"),
                             ensure_ascii=False, indent=1)
    for i, item in enumerate(items, 1):
        prev = runs.get(item["id"])
        try:
            if args.phase == "chart":
                if prev and prev.get("outcome") != "transport_error":
                    continue
                rec = run_chart(item, out, edits[item["id"]])
                line = (f"{'📊' if rec['outcome'] == 'chart' else '✗ ' + rec['outcome']} sql_ex={'✓' if rec.get('sql_ex') else '✗'} "
                        f"chart_ex={'✓' if rec.get('chart_ex', {}).get('ok') else '✗'} {rec.get('t_chart')}с")
            else:
                if not prev or prev.get("outcome") != "chart" or prev.get("edit_status") == "ok":
                    continue
                rec = run_edit(prev, out)
                line = f"{'🥚' if 'яйц' in rec['edit_code'] or 'яйц' in rec['edit'] else '🎨'} ур.{rec['level']} {rec['edit_code']}: " \
                       f"{'✓' if rec['edit_status'] == 'ok' else '✗ ' + str(rec.get('edit_message'))[:60]} {rec.get('t_edit')}с"
        except Exception as exc:  # noqa: BLE001 — один вопрос не должен ронять весь прогон
            rec = dict(prev or {k: item[k] for k in ("id", "split", "db_id", "question", "chart_type")})
            if args.phase == "chart":
                rec.update(outcome="transport_error", error=str(exc), sql_ex=False, chart_ex={"ok": False})
            else:
                rec.update(edit_status="error", edit_message=f"transport: {exc}")
            line = f"⚠ {exc}"
        runs[item["id"]] = rec
        dump()
        print(f"[{args.phase} {i}/{len(items)}] {line} | {item['db_id']}: {item['question'][:55]}", file=sys.stderr, flush=True)
    done = list(runs.values())
    print(f"\nфаза {args.phase}: вопросов {len(done)}, графиков {sum(r.get('outcome') == 'chart' for r in done)}, "
          f"SQL-EX {sum(bool(r.get('sql_ex')) for r in done)}, Chart-EX {sum(r.get('chart_ex', {}).get('ok', False) for r in done)}, "
          f"правок с картинкой {sum(r.get('edit_status') == 'ok' for r in done)}", file=sys.stderr)


if __name__ == "__main__":
    main()
