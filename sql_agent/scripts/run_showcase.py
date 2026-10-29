"""Примеры для презентации: вопрос PAUQ → график нужного типа (не столбцы) → «Подтвердить» →
правка изображения диффузией. Фазы разделены, как в run_pauq_charts.py (память):
    --phase chart   вопрос → график → смена типа кодом → «Подтвердить»
    --phase edit    правка диффузией
Судья: scripts/judge_edits.py <out> --file showcase.json --key id --before typed_png --after edit_png --status-field edit_status

    .venv/bin/python scripts/run_showcase.py -o ПРИМЕРЫ_ДЛЯ_ПРЕЗЕНТАЦИИ --phase chart
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pauq_charts as base  # noqa: E402

TYPE_PROMPT = {
    "line": "а теперь линией",
    "area": "сделай график с заливкой области под линией",
    "pie": "сделай круговую диаграмму, подпиши секторы названиями категорий",
    "doughnut": "сделай кольцевую диаграмму с подписями категорий",
    "histogram": "построй гистограмму распределения значений",
}

# (вопрос, тип графика, уровень, код правки, текст правки)
CASES = [
    ("D_0128", "line", 1, "красная линия", "Сделай линию графика ярко-красной и толще, точки — белые с красной обводкой, фон белый."),
    ("D_0128", "line", 2, "яйца-маркеры", "Замени точки на линейном графике на маленькие белые яйца, линию сделай красной."),
    ("D_0128", "line", 3, "шнур с яйцами", "Дорисуй за графиком красную студийную стену с мягким светом, а линию графика сделай белым шнуром, на котором висят белые яйца в точках данных."),
    ("D_0129", "area", 1, "красная область", "Залей область под линией ярко-красным, линию сделай белой и толстой, фон белый."),
    ("D_0129", "area", 3, "холм с яйцами", "Перерисуй область под линией как красный бархатный холм, а в каждой точке данных на его вершине положи белое яйцо."),
    ("D_0483", "line", 2, "яйца-маркеры", "Замени точки на линейном графике на белые яйца, линию сделай красной и толстой, фон белый."),
    ("D_0091", "pie", 1, "оттенки красного", "Замени цвета секторов на оттенки красного, фон белый, границы секторов белые."),
    ("D_0091", "pie", 3, "варёное яйцо", "Перерисуй круговую диаграмму как разрезанное сверху варёное яйцо на красной тарелке, каждая доля — кусок яйца."),
    ("D_0491", "pie", 2, "выпуклые дольки", "Сделай секторы круговой диаграммы выпуклыми, как дольки, в оттенках красного, между дольками — белые промежутки."),
    ("D_0012", "doughnut", 1, "красное кольцо", "Сделай кольцо в оттенках красного, центр кольца и фон белые."),
    ("D_0877", "doughnut", 2, "яйцо в разрезе", "Сделай кольцевую диаграмму похожей на разрезанное яйцо: центр — жёлтый желток, секторы кольца — белок в оттенках красного и белого."),
    ("D_1013", "doughnut", 3, "пончик", "Перерисуй кольцевую диаграмму как настоящий пончик с красной глазурью, каждый сектор — глазурь своего оттенка красного."),
    ("D_0395", "pie", 1, "оттенки красного", "Замени цвета секторов на оттенки красного, фон белый, подписи чёрные."),
    ("D_0094", "histogram", 1, "красная гистограмма", "Сделай столбцы гистограммы ярко-красными с белой обводкой, фон белый, оси чёрные."),
    ("D_0094", "histogram", 2, "яйца-столбцы", "Сделай столбцы гистограммы в форме белых яиц на красном фоне — высота яйца равна высоте столбца."),
]


def run_chart(qid: str, typ: str, item: dict, out: Path, key: str) -> dict:
    rec = {"id": key, "qid": qid, "db_id": item["db_id"], "question": item["question"], "target_type": typ}
    gold, _ = base.run_sql(item["db_id"], item["sql"])
    sid = base.call("POST", "/sessions")["session_id"]
    rec["session_id"] = sid
    t0 = time.time()
    r1 = base.message(sid, item["question"], use_sql_source=True, sql_datasource_id=f"pauq_{item['db_id']}")
    rec["t_chart"] = round(time.time() - t0)
    art = r1.get("artefacts") or {}
    src = ((art.get("data") or {}).get("sql_source") or {})
    rec["pred_sql"], rec["pred_n"] = src.get("sql"), src.get("row_count")
    b64 = (art.get("plot") or {}).get("image_base64")
    rec["base_png"] = base.save_png(b64, out / f"{key}_base.png")
    if not b64 or not r1.get("show_approve_cancel"):
        rec["outcome"] = "no_chart"; rec["message"] = r1.get("assistant_message"); return rec
    if True:  # тип в отборе не всегда совпадает с тем, что построил сервис, — переводим всегда
        t1 = time.time()
        r2 = base.message(sid, TYPE_PROMPT[typ])
        rec["t_type"] = round(time.time() - t1)
        b2 = ((r2.get("artefacts") or {}).get("plot") or {}).get("image_base64")
        if not b2 or b2 == b64 or not r2.get("show_approve_cancel"):
            rec["outcome"] = "type_failed"; rec["message"] = r2.get("assistant_message"); return rec
        b64 = b2
    rec["typed_png"] = base.save_png(b64, out / f"{key}_{typ}.png")
    st = base.session_state(sid)
    pts = (((st.get("artefacts") or {}).get("data") or {}).get("understanding") or {}).get("dataset_spec", {}).get("points") or []
    rec["chart_ex"] = base.chart_matches(pts, gold or [])
    rec["code"] = ((st.get("artefacts") or {}).get("plot") or {}).get("code")
    base.call("POST", f"/sessions/{sid}/messages", {"type": "decision", "value": "approve", "content": "", "images_base64": []})
    rec["outcome"] = "chart"
    rec["edit_status"] = "pending"
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="ПРИМЕРЫ_ДЛЯ_ПРЕЗЕНТАЦИИ")
    ap.add_argument("--phase", choices=["chart", "edit"], required=True)
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(exist_ok=True)
    sel = {x["id"]: x for x in json.load(open(base.SELECTION, encoding="utf-8"))}
    path = out / "showcase.json"
    runs = {r["id"]: r for r in json.load(open(path, encoding="utf-8"))} if path.exists() else {}
    for i, (qid, typ, level, code, edit) in enumerate(CASES, 1):
        key = f"{qid}_{typ}_{i:02d}"
        prev = runs.get(key)
        try:
            if args.phase == "chart":
                if prev and prev.get("outcome") == "chart":
                    continue
                rec = run_chart(qid, typ, sel[qid], out, key)
                rec.update(level=level, edit_code=code, edit=edit, edit_prompt=f"{base.PREFIX}{edit} {base.KEEP}")
                line = f"{rec['outcome']} {rec.get('t_chart')}+{rec.get('t_type', 0)}с данные {'✓' if rec.get('chart_ex', {}).get('ok') else '✗'}"
            else:
                if not prev or prev.get("outcome") != "chart" or prev.get("edit_status") == "ok":
                    continue
                rec = base.run_edit(prev, out)
                line = f"правка ур.{rec['level']} {rec['edit_code']}: {'✓' if rec['edit_status'] == 'ok' else '✗ ' + str(rec.get('edit_message'))[:60]} {rec.get('t_edit')}с"
        except Exception as exc:  # noqa: BLE001
            rec = dict(prev or {"id": key, "qid": qid, "target_type": typ})
            rec.update(outcome=rec.get("outcome", "error"), error=str(exc))
            if args.phase == "edit":
                rec["edit_status"] = "error"
            line = f"⚠ {exc}"
        runs[key] = rec
        json.dump([runs[k] for k in sorted(runs)], open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[{args.phase} {i}/{len(CASES)}] {typ:9s} {line} | {qid}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
