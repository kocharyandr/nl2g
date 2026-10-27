"""Те же 100 вопросов PAUQ: исходный график, затем смена типа правкой кодом (до «Подтвердить»).
После каждой правки данные на графике сверяются с эталоном (Chart-EX). Правки в сессии накапливаются:
вторая применяется к графику после первой. Результаты дописываются в <out>/runs.json, картинки —
<out>/<id>_<тип>.png, прогресс — <out>/ПРОГРЕСС.html.

    .venv/bin/python scripts/run_chart_types.py -o PAUQ_ТИПЫ_ГРАФИКОВ
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pauq_charts as base  # noqa: E402  — переиспользуем API-обёртки и метрики

EDITS = {
    "line": "а теперь линией",
    "area": "сделай график с заливкой области под линией",
    "pie": "сделай круговую диаграмму с подписями категорий",
    "doughnut": "сделай кольцевую диаграмму с подписями категорий",
    "barh": "сделай горизонтальные столбцы",
    "bar": "сделай обычные вертикальные столбцы",
    "histogram": "построй гистограмму распределения значений",
    "stacked_bar": "сделай столбцы с накоплением: серии друг на друге",
    "scatter": "сделай диаграмму рассеяния: по оси X первая числовая колонка, по оси Y вторая, подпиши точки",
}


def numeric_columns(table: dict | None) -> int:
    """Сколько числовых колонок в ответе SQL (по значениям первой строки, без id)."""
    if not table or not table.get("rows"):
        return 0
    n = 0
    for i, col in enumerate(table.get("columns") or []):
        name = str(col.get("name", "")).lower()
        if name.endswith("id") or name == "id":
            continue
        v = table["rows"][0][i] if i < len(table["rows"][0]) else None
        if base.num(v) is not None:
            n += 1
    return n


def plan_types(item: dict, n_rows: int, n_numeric: int) -> list[str]:
    """Набор целевых типов для вопроса: по форме данных, 4 правки на вопрос."""
    src = item.get("chart_type") or "bar"
    small = n_rows <= 8
    types = []
    if src != "line":
        types.append("line")
    types.append("area")
    types.append("doughnut" if small else "histogram")
    if n_numeric >= 2:
        types.append("stacked_bar")
    elif src == "pie":
        types.append("bar")
    else:
        types.append("pie" if small else "barh")
    if src == "line":
        types.insert(0, "bar")
    return types[:4]


def snapshot(sid: str, gold):
    st = base.session_state(sid)
    pts = (((st.get("artefacts") or {}).get("data") or {}).get("understanding") or {}).get("dataset_spec", {}).get("points") or []
    plot = (st.get("artefacts") or {}).get("plot") or {}
    return st, pts, plot, base.chart_matches(pts, gold or [])


def run_item(item: dict, out: Path) -> dict:
    rec = {k: item[k] for k in ("id", "split", "db_id", "question", "chart_type")}
    gold, _ = base.run_sql(item["db_id"], item["sql"])
    rec["gold_n"] = len(gold or [])
    sid = base.call("POST", "/sessions")["session_id"]
    rec["session_id"] = sid
    t0 = time.time()
    r1 = base.message(sid, item["question"], use_sql_source=True, sql_datasource_id=f"pauq_{item['db_id']}")
    rec["t_chart"] = round(time.time() - t0)
    art = r1.get("artefacts") or {}
    src = ((art.get("data") or {}).get("sql_source") or {})
    rec["pred_sql"], rec["pred_n"] = src.get("sql"), src.get("row_count")
    plot_b64 = (art.get("plot") or {}).get("image_base64")
    rec["base_png"] = base.save_png(plot_b64, out / f"{item['id']}_base.png")
    if not plot_b64 or not r1.get("show_approve_cancel"):
        rec["outcome"] = "no_chart"
        rec["message"] = r1.get("assistant_message")
        return rec
    rec["outcome"] = "chart"
    st, pts, plot, ce = snapshot(sid, gold)
    rec["base_chart_ex"] = ce
    rec["base_code"] = plot.get("code")
    rec["n_numeric"] = numeric_columns(st.get("sql_result_table") or st.get("persisted_sql_result"))
    rec["edits"] = []
    for typ in plan_types(item, rec["pred_n"] or 0, rec["n_numeric"]):
        e = {"type": typ, "prompt": EDITS[typ]}
        t1 = time.time()
        r = base.message(sid, EDITS[typ])
        e["t"] = round(time.time() - t1)
        p2 = ((r.get("artefacts") or {}).get("plot") or {})
        png = p2.get("image_base64")
        e["png"] = base.save_png(png, out / f"{item['id']}_{typ}.png") if png and png != plot_b64 else None
        e["message"] = (r.get("assistant_message") or "")[:200]
        st, pts, plot, ce = snapshot(sid, gold)
        e["chart_ex"] = ce
        e["n_points"] = len(pts)
        e["code"] = plot.get("code")
        e["stage"] = r.get("current_stage")
        e["ok"] = bool(e["png"]) and r.get("show_approve_cancel", False)
        plot_b64 = png or plot_b64
        rec["edits"].append(e)
    return rec


def progress_page(runs: list[dict], total: int, out: Path) -> None:
    n = len(runs)
    charts = [r for r in runs if r.get("outcome") == "chart"]
    edits = [e for r in charts for e in r.get("edits", [])]
    by = {}
    for e in edits:
        d = by.setdefault(e["type"], [0, 0, 0]); d[0] += 1; d[1] += int(e["ok"]); d[2] += int(e["chart_ex"].get("ok", False))
    tiles = "".join(f"<div class=st><b>{v}</b><span>{l}</span></div>" for v, l in
                    [(f"{n}/{total}", "обработано"), (len(charts), "исходных графиков"), (len(edits), "смен типа"),
                     (sum(e['ok'] for e in edits), "график перестроен"), (sum(e['chart_ex'].get('ok', False) for e in edits), "данные совпали с эталоном")])
    ty = "".join(f"<tr><td>{t}</td><td>{d[0]}</td><td>{d[1]}</td><td>{d[2]}</td></tr>" for t, d in sorted(by.items()))
    rows = ""
    for r in reversed(runs):
        imgs = (f'<td class=i><img src="{r["base_png"]}"></td>' if r.get("base_png") else "<td></td>")
        for e in r.get("edits", []):
            imgs += f'<td class=i>{"<img src=%s>" % e["png"] if e["png"] else "—"}<div>{e["type"]} · {"✓" if e["chart_ex"].get("ok") else "✗"} · {e["t"]} с</div></td>'
        rows += f"<tr><td>{html.escape(r['id'])}</td><td>{html.escape(r['question'][:70])}</td><td>{r.get('outcome')}</td>{imgs}</tr>"
    (out / "ПРОГРЕСС.html").write_text(f"""<!DOCTYPE html><html lang=ru><head><meta charset=utf-8><meta http-equiv=refresh content=30><title>Типы графиков</title>
<style>body{{font-family:system-ui;margin:24px;background:#f9f9f7}}.sts{{display:flex;gap:8px;flex-wrap:wrap}}.st{{background:#fff;border:1px solid #ddd;border-radius:10px;padding:8px 14px}}.st b{{font-size:22px;display:block}}.st span{{font-size:12px;color:#666}}
table{{border-collapse:collapse;font-size:12px;background:#fff;margin-top:12px}}td,th{{border:1px solid #ddd;padding:4px 6px;vertical-align:top}}td.i img{{width:190px;display:block}}td.i div{{font-size:11px;color:#555}}</style></head>
<body><h1>Те же вопросы — другие типы графиков <small style="font-weight:400;color:#777">{time.strftime('%H:%M:%S')}, обновляется каждые 30 с</small></h1>
<div class=sts>{tiles}</div><table><tr><th>тип</th><th>правок</th><th>перестроено</th><th>Chart-EX ✓</th></tr>{ty}</table>
<table><tr><th>id</th><th>вопрос</th><th>итог</th><th>исходный</th><th>правка 1</th><th>правка 2</th><th>правка 3</th><th>правка 4</th></tr>{rows}</table></body></html>""", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="PAUQ_ТИПЫ_ГРАФИКОВ")
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(exist_ok=True)
    strong = json.load(open(base.SELECTION, encoding="utf-8"))
    sel_ids = json.load(open(Path(__file__).resolve().parents[1] / "PAUQ_ГРАФИКИ_ПРОГОН" / "selection.json"))
    by_id = {x["id"]: x for x in strong}
    items = [by_id[i] for i in sel_ids][: args.n]
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    runs_path = out / "runs.json"
    runs = {r["id"]: r for r in json.load(open(runs_path, encoding="utf-8"))} if runs_path.exists() else {}
    for i, item in enumerate(items, 1):
        if only and item["id"] not in only:
            continue
        if item["id"] in runs and runs[item["id"]].get("outcome") != "transport_error":
            continue
        try:
            rec = run_item(item, out)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            rec = {k: item[k] for k in ("id", "split", "db_id", "question", "chart_type")}
            rec.update(outcome="transport_error", error=str(exc))
        runs[item["id"]] = rec
        ordered = [runs[x["id"]] for x in items if x["id"] in runs]
        json.dump(ordered, open(runs_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        progress_page(ordered, len(items), out)
        ed = " ".join(f"{e['type']}:{'✓' if e['chart_ex'].get('ok') else '✗'}" for e in rec.get("edits", []))
        print(f"[{i}/{len(items)}] {rec['outcome']} {rec.get('t_chart', '-')}с {ed} | {item['db_id']}: {item['question'][:50]}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
