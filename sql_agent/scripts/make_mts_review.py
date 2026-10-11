"""HTML-отчёт по правкам «в стиле МТС» в виде чатов: вопрос → график (SQL, код) → «Подтвердить» →
промпт правки → результат диффузии + вердикт судьи (E1-5 / P1-5, A / P / AP).

    .venv/bin/python scripts/make_mts_review.py МТС_ПРАВКИ -o МТС_ПРАВКИ.html
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

CRIT_RU = {
    "E1_requested_edit_visible": "A1 · изменение видно",
    "E2_correct_target_elements": "A2 · правильные элементы",
    "E3_edit_completeness": "A3 · полнота",
    "E4_edit_specificity_no_unrequested_edit": "A4 · без лишних правок",
    "E5_visual_integration_and_cleanliness": "A5 · целостность",
    "P1_element_count_and_presence": "P1 · состав элементов",
    "P2_spatial_layout_preservation": "P2 · расположение",
    "P3_scale_proportion_and_quantitative_relations": "P3 · масштабы и пропорции",
    "P4_visual_encoding_and_series_identity": "P4 · визуальное кодирование",
    "P5_no_extra_artifacts_or_corruption": "P5 · без артефактов",
}
LEVEL_RU = {1: "уровень 1 · цвет", 2: "уровень 2 · форма элементов", 3: "уровень 3 · реализм"}

CSS = """
:root{color-scheme:light;--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:rgba(11,11,11,.10);--grid:#e1e0d9;--blue:#2a78d6;--red:#e30611;--ubg:#2a78d6;--bbg:#fff;--ok:#0c8a3e;--bad:#c8332d}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--line:rgba(255,255,255,.10);--grid:#2c2c2a;--blue:#3987e5;--ubg:#3987e5;--bbg:#242423;--ok:#3ccf74;--bad:#ff7a73}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:15px;line-height:1.5}
.wrap{max-width:1120px;margin:0 auto;padding:28px 18px 70px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}
.sub{color:var(--ink2);max-width:82ch;margin:0 0 18px}
.stats{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:18px 0 22px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stat .v{font-size:27px;line-height:1;font-variant-numeric:tabular-nums}
.stat .l{font-size:12px;color:var(--ink2);margin-top:6px}
table.lv{border-collapse:collapse;margin:0 0 22px;font-size:13.5px}
table.lv td,table.lv th{border:1px solid var(--line);padding:6px 12px;text-align:center}
table.lv th{background:var(--card);font-weight:600}
.chat{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--red);
border-radius:14px;padding:16px 16px 8px;margin-bottom:18px}
.hd{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px}
.hd .n{font-size:16px;font-weight:650}
.tag{font-size:11px;padding:2px 9px;border-radius:20px;background:rgba(227,6,17,.10);color:var(--red)}
.tag.b{background:rgba(42,120,214,.10);color:var(--blue)}
.row{display:flex;margin:10px 0}.row.u{justify-content:flex-end}.row.c{justify-content:center}
.bub{max-width:88%;border-radius:16px;padding:10px 14px;font-size:14.5px}
.ub{background:var(--ubg);color:#fff;border-bottom-right-radius:5px}
.bb{background:var(--bbg);border:1px solid var(--line);border-bottom-left-radius:5px;max-width:96%}
.sys{font-size:12px;color:var(--muted);border:1px dashed var(--line);border-radius:20px;padding:3px 12px}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px}
@media(max-width:880px){.ab{grid-template-columns:1fr}}
.var{border:1px solid var(--line);border-radius:10px;padding:9px}
.var .t{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:6px}
.var.a{border-left:3px solid var(--muted)}.var.b{border-left:3px solid var(--red)}
img{width:100%;border-radius:8px;border:1px solid var(--grid);display:block;background:#fff}
.note{font-size:12px;color:var(--muted);margin-top:7px}
pre{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.5;background:var(--bg);
border:1px solid var(--line);border-radius:7px;padding:8px 10px;overflow-x:auto;margin:6px 0 0;
white-space:pre-wrap;word-break:break-word}
details{margin:8px 0 2px;font-size:13px}summary{cursor:pointer;color:var(--blue)}
.issue{background:rgba(200,51,45,.10);border:1px solid rgba(200,51,45,.35);color:var(--bad);
border-radius:8px;padding:8px 11px;font-size:13px;margin-top:9px}
table.j{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:8px}
table.j td{border-top:1px solid var(--line);padding:5px 8px;vertical-align:top}
table.j td.k{white-space:nowrap;width:190px;color:var(--ink2)}
table.j td.m{width:26px;text-align:center;font-weight:700}
.ok{color:var(--ok)}.bad{color:var(--bad)}
.agg{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.agg span{font-size:12.5px;padding:3px 10px;border-radius:20px;border:1px solid var(--line)}
.agg .y{background:rgba(12,138,62,.12);color:var(--ok)}.agg .n{background:rgba(200,51,45,.10);color:var(--bad)}
@media print{
 :root{--bg:#fff;--card:#fff;--ink:#000;--ink2:#333;--muted:#666;--line:#d5d5d0;--grid:#e3e3de;--bbg:#f4f4f1}
 body{font-size:10.5pt}.wrap{max-width:none;padding:0}.chat{break-inside:avoid;page-break-inside:avoid}
 .bub{max-width:100%}img{max-height:62mm;width:auto;margin:0 auto}details>summary{display:none}pre{font-size:8pt}
 details{display:block}details:not([open])>*:not(summary){display:none}
}
@page{size:A4;margin:13mm 11mm}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def img_tag(path: Path | None) -> str:
    if not path or not path.exists():
        return '<div class="note">картинки нет</div>'
    b = base64.b64encode(path.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b}" loading="lazy">'


def judge_block(v: dict | None) -> str:
    if not v:
        return '<div class="note">судья не запускался</div>'
    rows = []
    for group in ("adherence", "preservation"):
        for key, crit in v[group].items():
            mark = '<span class="ok">✓</span>' if crit["passed"] else '<span class="bad">✗</span>'
            why = crit.get("evidence") or crit.get("reason") or ""
            rows.append(f'<tr><td class="m">{mark}</td><td class="k">{esc(CRIT_RU.get(key, key))}</td><td>{esc(why)}</td></tr>')
    agg = "".join(
        f'<span class="{"y" if v[k] else "n"}">{k} = {v[k]}</span>' for k in ("A", "P", "AP")
    )
    return f'<div class="agg">{agg}<span>судья {v.get("secs", "?")} с</span></div><table class="j">{"".join(rows)}</table>'


def chat_block(rec: dict, verdict: dict | None, out_dir: Path) -> str:
    n, lvl = rec["n"], rec["level"]
    before = out_dir / rec["before_png"] if rec.get("before_png") else None
    after = out_dir / rec["after_png"] if rec.get("after_png") else None
    parts = [f'<div class="chat"><div class="hd"><span class="n">Правка {n}</span>'
             f'<span class="tag">{LEVEL_RU[lvl]}</span><span class="tag b">{esc(rec["db"])}</span></div>']
    parts.append(f'<div class="row u"><div class="bub ub">{esc(rec["q"])}</div></div>')
    bot = [img_tag(before)]
    if rec.get("sql_explanation"):
        bot.append(f'<div class="note">{esc(rec["sql_explanation"])} · строк: {esc(rec.get("row_count"))} · {rec.get("t_chart", "?")} с</div>')
    if rec.get("sql"):
        bot.append(f'<details><summary>SQL-запрос</summary><pre>{esc(rec["sql"])}</pre></details>')
    if rec.get("code"):
        bot.append(f'<details><summary>Код графика</summary><pre>{esc(rec["code"])}</pre></details>')
    parts.append(f'<div class="row"><div class="bub bb">{"".join(bot)}</div></div>')
    if rec["status"] != "ok" and not rec.get("after_png"):
        parts.append(f'<div class="issue">{esc(rec.get("error"))}</div></div>')
        return "".join(parts)
    parts.append('<div class="row c"><span class="sys">нажато «Подтвердить»</span></div>')
    parts.append(f'<div class="row u"><div class="bub ub">{esc(rec["edit_prompt"])}</div></div>')
    gen = [f'<div class="ab"><div class="var a"><div class="t">A · до</div>{img_tag(before)}</div>'
           f'<div class="var b"><div class="t">B · после ({rec.get("t_edit", "?")} с)</div>{img_tag(after)}</div></div>']
    if rec.get("enhanced_prompt"):
        gen.append(f'<details><summary>Промпт для диффузии (сгенерирован LLM)</summary><pre>{esc(rec["enhanced_prompt"])}</pre></details>')
    gen.append(judge_block(verdict))
    parts.append(f'<div class="row"><div class="bub bb">{"".join(gen)}</div></div></div>')
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("-o", "--out", default="МТС_ПРАВКИ.html")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    recs = json.load(open(out_dir / "mts_edits.json", encoding="utf-8"))
    jpath = out_dir / "mts_judge.json"
    verdicts = json.load(open(jpath, encoding="utf-8")) if jpath.exists() else {}

    ok = [r for r in recs if r["status"] == "ok"]
    judged = [verdicts[str(r["n"])] for r in ok if str(r["n"]) in verdicts]
    def pct(key, subset):
        return f"{sum(v[key] for v in subset)}/{len(subset)}" if subset else "—"
    stats = [(len(recs), "правок задано"), (len(ok), "с картинкой"), (pct("A", judged), "A · правка выполнена"),
             (pct("P", judged), "P · данные сохранены"), (pct("AP", judged), "AP · и то и другое")]
    stats_html = "".join(f'<div class="stat"><div class="v">{v}</div><div class="l">{l}</div></div>' for v, l in stats)
    lv_rows = []
    for lvl in (1, 2, 3):
        sub = [verdicts[str(r["n"])] for r in ok if r["level"] == lvl and str(r["n"]) in verdicts]
        lv_rows.append(f"<tr><td style='text-align:left'>{LEVEL_RU[lvl]}</td><td>{len([r for r in recs if r['level']==lvl])}</td>"
                       f"<td>{pct('A', sub)}</td><td>{pct('P', sub)}</td><td>{pct('AP', sub)}</td></tr>")
    lv_table = ('<table class="lv"><tr><th>Сложность промпта (по диплому Матвея)</th><th>промптов</th><th>A</th><th>P</th><th>AP</th></tr>'
                + "".join(lv_rows) + "</table>")
    chats = "".join(chat_block(r, verdicts.get(str(r["n"])), out_dir) for r in recs)
    doc = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Правки в стиле МТС</title><style>{CSS}</style></head>
<body><div class="wrap"><h1>Правки графиков «в стиле МТС» на русских данных PAUQ</h1>
<p class="sub">Каждый диалог: вопрос по-русски к базе PAUQ → SQL-агент → график → «Подтвердить» → генеративная правка
(FLUX.2 Klein 9B + LoRA, seed 42, одна итерация). Промпты — по трём уровням сложности из диплома Матвея (цвет → форма
элементов → реализм), фирменные признаки описаны словами (красный/белый/чёрный, яйцо), без упоминания бренда — диффузия
его не знает. Оценка — судья из диплома (Qwen2.5-VL-7b, temperature 0): критерии A1-5 (правка выполнена) и P1-5
(аналитика сохранена); A, P, AP = 1, только если пройдены все критерии группы.</p>
<div class="stats">{stats_html}</div>{lv_table}{chats}</div></body></html>"""
    Path(args.out).write_text(doc, encoding="utf-8")
    print(f"{args.out}: {Path(args.out).stat().st_size // 1024} KB, диалогов {len(recs)}, с судьёй {len(judged)}")


if __name__ == "__main__":
    main()
