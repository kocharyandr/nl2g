"""Отчёт-чат по прогону run_pauq_charts.py: вопрос → ответ сервиса (график, SQL, код) →
«Подтвердить» → правка «в стиле МТС» диффузией → вердикт судьи (A1-5 / P1-5), плюс метрики
SQL-EX / Chart-EX / A / P / AP и фильтры.

    .venv/bin/python scripts/make_pauq_charts_review.py PAUQ_ГРАФИКИ_ПРОГОН -o PAUQ_ГРАФИКИ_ПРОГОН.html
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
from collections import Counter
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # без Pillow картинки встраиваются как есть
    Image = None

CRIT_RU = {
    "E1_requested_edit_visible": "A1 · изменение видно", "E2_correct_target_elements": "A2 · правильные элементы",
    "E3_edit_completeness": "A3 · полнота", "E4_edit_specificity_no_unrequested_edit": "A4 · без лишних правок",
    "E5_visual_integration_and_cleanliness": "A5 · целостность", "P1_element_count_and_presence": "P1 · состав элементов",
    "P2_spatial_layout_preservation": "P2 · расположение", "P3_scale_proportion_and_quantitative_relations": "P3 · масштабы",
    "P4_visual_encoding_and_series_identity": "P4 · кодирование", "P5_no_extra_artifacts_or_corruption": "P5 · без артефактов",
}
LEVEL_RU = {1: "ур.1 · цвет", 2: "ур.2 · форма", 3: "ур.3 · реализм"}
OUTCOME_RU = {"chart": "график", "text_answer": "ответ текстом", "clarification": "уточнение",
              "no_chart": "без графика", "transport_error": "ошибка сервиса (HTTP 500)"}

CSS = """
:root{color-scheme:light;--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:rgba(11,11,11,.10);--grid:#e1e0d9;--blue:#2a78d6;--red:#e30611;--ubg:#2a78d6;--bbg:#fff;--ok:#0c8a3e;--bad:#c8332d}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#9a998f;
--line:rgba(255,255,255,.10);--grid:#2c2c2a;--blue:#3987e5;--ubg:#3987e5;--bbg:#242423;--ok:#3ccf74;--bad:#ff7a73}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:28px 16px 70px}h1{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}
.sub{color:var(--ink2);max-width:84ch;margin:0 0 16px}
.stats{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.stat .v{font-size:25px;line-height:1.1;font-variant-numeric:tabular-nums}.stat .l{font-size:12px;color:var(--ink2);margin-top:4px}
.f{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:2}
select,input{font:inherit;font-size:13.5px;padding:5px 8px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
.chat{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:14px;padding:14px 14px 6px;margin-bottom:16px}
.chat.bad{border-left-color:var(--bad)}.hd{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.hd .n{font-weight:650}.tag{font-size:11px;padding:2px 8px;border-radius:20px;background:rgba(42,120,214,.10);color:var(--blue)}
.tag.y{background:rgba(12,138,62,.12);color:var(--ok)}.tag.x{background:rgba(200,51,45,.10);color:var(--bad)}
.row{display:flex;margin:9px 0}.row.u{justify-content:flex-end}
.bub{max-width:88%;border-radius:16px;padding:9px 13px;font-size:14.5px}.ub{background:var(--ubg);color:#fff;border-bottom-right-radius:5px}
.bb{background:var(--bbg);border:1px solid var(--line);border-bottom-left-radius:5px;max-width:96%}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:820px){.ab{grid-template-columns:1fr}}
.var{border:1px solid var(--line);border-radius:10px;padding:8px}.var .t{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:5px}
img{width:100%;border-radius:8px;border:1px solid var(--grid);display:block;background:#fff}
.note{font-size:12.5px;color:var(--muted);margin-top:6px}
pre{font:11.5px/1.5 ui-monospace,Menlo,monospace;background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:7px 9px;margin:5px 0 0;white-space:pre-wrap;word-break:break-word}
details{margin:6px 0 2px;font-size:13px}summary{cursor:pointer;color:var(--blue)}
table.g{border-collapse:collapse;font-size:12px;margin-top:5px}table.g td{border:1px solid var(--line);padding:2px 7px}
.issue{background:rgba(200,51,45,.10);border:1px solid rgba(200,51,45,.35);color:var(--bad);border-radius:8px;padding:7px 10px;font-size:13px;margin-top:7px}
table.j{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}table.j td{border-top:1px solid var(--line);padding:4px 7px;vertical-align:top}
table.j td.k{white-space:nowrap;color:var(--ink2)}.ok{color:var(--ok)}.no{color:var(--bad)}
table.m{border-collapse:collapse;font-size:13.5px;margin:6px 0 16px;background:var(--card)}table.m td,table.m th{border:1px solid var(--line);padding:5px 11px;text-align:center}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def img(path: Path) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    mime = "png"
    if Image is not None:
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((1100, 1100))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=84)
        data, mime = buf.getvalue(), "jpeg"
    return f'<img loading="lazy" src="data:image/{mime};base64,{base64.b64encode(data).decode()}">'


def mini_table(rows, limit=8) -> str:
    if not rows:
        return ""
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in r) + "</tr>" for r in rows[:limit])
    more = f"<div class=note>… всего строк: {len(rows)}</div>" if len(rows) > limit else ""
    return f"<table class=g>{body}</table>{more}"


def tag(ok, yes, no) -> str:
    if ok is None:
        return ""
    return f'<span class="tag {"y" if ok else "x"}">{yes if ok else no}</span>'


verdicts: dict = {}


def chat(i: int, r: dict, out: Path) -> str:
    ce = r.get("chart_ex") or {}
    bad = not ce.get("ok")
    attrs = (f'data-o="{r.get("outcome")}" data-sql="{int(bool(r.get("sql_ex")))}" data-cex="{int(bool(ce.get("ok")))}" '
             f'data-db="{esc(r["db_id"])}" data-sp="{r.get("split")}" data-lv="{r.get("level", "")}" '
             f'data-egg="{int("яйц" in (r.get("edit") or ""))}" data-ap="{(verdicts.get(r["id"]) or {}).get("AP", "")}"')
    p = [f'<div class="chat{" bad" if bad else ""}" {attrs}><div class=hd><span class=n>#{i} · {esc(r["id"])}</span>'
         f'<span class=tag>{esc(r["db_id"])}</span><span class=tag>{r.get("split")}</span>'
         f'<span class=tag>{OUTCOME_RU.get(r.get("outcome"), r.get("outcome"))}</span>'
         f'{tag(r.get("sql_ex"), "SQL-EX ✓", "SQL-EX ✗")}{tag(ce.get("ok") if r.get("outcome") == "chart" else None, "Chart-EX ✓", "Chart-EX ✗")}'
         f'<span class=tag>{esc(LEVEL_RU.get(r.get("level"), ""))} · {esc(r.get("edit_code", ""))}</span></div>']
    p.append(f'<div class="row u"><div class="bub ub">{esc(r["question"])}</div></div>')
    bot = []
    if r.get("chart_png"):
        bot.append(img(out / r["chart_png"]))
    if r.get("outcome") != "chart":
        bot.append(f'<div class=issue>{esc(r.get("assistant_message") or r.get("error") or "график не построен")}</div>')
    if r.get("sql_explanation"):
        bot.append(f'<div class=note>{esc(r["sql_explanation"])} · строк: {esc(r.get("pred_n"))} · {r.get("t_chart", "?")} с</div>')
    if r.get("outcome") == "chart":
        ce_txt = (f'Chart-EX: точек на графике {ce.get("n_points")}, строк в эталоне {ce.get("n_gold")}; '
                  f'числа {"совпали" if ce.get("values_ok") else "не совпали"}'
                  + ("" if ce.get("labels_ok") is None else f', подписи {"совпали" if ce.get("labels_ok") else "не совпали"}'))
        bot.append(f'<div class=note>{esc(ce_txt)}</div>')
    bot.append(f'<details><summary>SQL сервиса и эталон</summary><pre>{esc(r.get("pred_sql") or "—")}</pre>'
               f'<div class=note>эталон:</div><pre>{esc(r.get("gold_sql"))}</pre>{mini_table(r.get("gold_rows"))}</details>')
    if r.get("code"):
        bot.append(f'<details><summary>Код графика</summary><pre>{esc(r["code"])}</pre></details>')
    p.append(f'<div class=row><div class="bub bb">{"".join(bot)}</div></div>')
    if r.get("outcome") == "chart":
        p.append('<div class=row style="justify-content:center"><span class=note>нажато «Подтвердить»</span></div>')
        p.append(f'<div class="row u"><div class="bub ub">{esc(r.get("edit_prompt"))}</div></div>')
        if r.get("edit_png"):
            gen = (f'<div class=ab><div class=var><div class=t>A · до</div>{img(out / r["chart_png"])}</div>'
                   f'<div class=var><div class=t>B · {esc(LEVEL_RU.get(r.get("level")))} · {esc(r.get("edit_code"))} ({r.get("t_edit", "?")} с)</div>{img(out / r["edit_png"])}</div></div>')
            if r.get("enhanced_prompt"):
                gen += f'<details><summary>Промпт для диффузии (сгенерирован LLM)</summary><pre>{esc(r["enhanced_prompt"])}</pre></details>'
            v = verdicts.get(r["id"])
            if v:
                crit = "".join(
                    f'<tr><td class="{"ok" if c["passed"] else "no"}">{"✓" if c["passed"] else "✗"}</td><td class=k>{esc(CRIT_RU.get(k, k))}</td>'
                    f'<td>{esc(c.get("evidence") or c.get("reason") or "")}</td></tr>'
                    for grp in ("adherence", "preservation") for k, c in v[grp].items())
                gen += (f'<div class=hd style="margin-top:8px">{tag(bool(v["A"]), "A = 1", "A = 0")}{tag(bool(v["P"]), "P = 1", "P = 0")}'
                        f'{tag(bool(v["AP"]), "AP = 1", "AP = 0")}</div><details><summary>Критерии судьи</summary><table class=j>{crit}</table></details>')
            else:
                gen += '<div class=note>судья ещё не оценил</div>'
        elif r.get("edit_status") == "pending":
            gen = '<div class=note>правка ещё не выполнена</div>'
        else:
            gen = f'<div class=issue>{esc(r.get("edit_message") or "картинка не сгенерирована")}</div>'
        p.append(f'<div class=row><div class="bub bb">{gen}</div></div>')
    p.append("</div>")
    return "".join(p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("-o", "--out", default="PAUQ_ГРАФИКИ_ПРОГОН.html")
    args = ap.parse_args()
    out = Path(args.run_dir)
    runs = json.load(open(out / "runs.json", encoding="utf-8"))
    n = len(runs)
    c = lambda f: sum(1 for r in runs if f(r))
    charts = [r for r in runs if r.get("outcome") == "chart"]
    pct = lambda k, m: f"{k}/{m} = {k / m * 100:.0f}%" if m else "—"
    global verdicts
    vp = out / "judge.json"
    verdicts = json.load(open(vp, encoding="utf-8")) if vp.exists() else {}
    edited = [r for r in runs if r.get("edit_status") == "ok"]
    judged = [verdicts[r["id"]] for r in edited if r["id"] in verdicts]
    agg = lambda key, sub: pct(sum(v[key] for v in sub), len(sub))
    stats = [(n, "вопросов"), (pct(len(charts), n), "график построен"),
             (pct(c(lambda r: r.get("sql_ex")), n), "SQL-EX"),
             (pct(c(lambda r: (r.get("chart_ex") or {}).get("ok")), n), "Chart-EX (от всех)"),
             (pct(c(lambda r: (r.get("chart_ex") or {}).get("ok")), len(charts)), "Chart-EX (от графиков)"),
             (pct(len(edited), len(charts)), "правка диффузией получена"),
             (agg("A", judged), "A · правка выполнена"), (agg("P", judged), "P · данные сохранены"), (agg("AP", judged), "AP")]
    lv_rows = ""
    for lvl in (1, 2, 3):
        sub = [verdicts[r["id"]] for r in edited if r.get("level") == lvl and r["id"] in verdicts]
        lv_rows += (f"<tr><th>{LEVEL_RU[lvl]}</th><td>{sum(1 for r in charts if r.get('level') == lvl)}</td>"
                    f"<td>{agg('A', sub)}</td><td>{agg('P', sub)}</td><td>{agg('AP', sub)}</td></tr>")
    for name, flt in (("с яйцом", lambda r: "яйц" in (r.get("edit") or "")), ("без яйца", lambda r: "яйц" not in (r.get("edit") or ""))):
        sub = [verdicts[r["id"]] for r in edited if flt(r) and r["id"] in verdicts]
        lv_rows += (f"<tr><th>{name}</th><td>{sum(1 for r in charts if flt(r))}</td>"
                    f"<td>{agg('A', sub)}</td><td>{agg('P', sub)}</td><td>{agg('AP', sub)}</td></tr>")
    code_rows = ""
    for code in sorted({r.get("edit_code") for r in charts if r.get("edit_code")}):
        sub = [verdicts[r["id"]] for r in edited if r.get("edit_code") == code and r["id"] in verdicts]
        code_rows += f"<tr><th>{esc(code)}</th><td>{sum(1 for r in charts if r.get('edit_code') == code)}</td><td>{agg('A', sub)}</td><td>{agg('P', sub)}</td><td>{agg('AP', sub)}</td></tr>"
    judge_tbl = ("<table class=m><tr><th>срез</th><th>правок</th><th>A</th><th>P</th><th>AP</th></tr>" + lv_rows + "</table>"
                 "<table class=m><tr><th>промпт</th><th>правок</th><th>A</th><th>P</th><th>AP</th></tr>" + code_rows + "</table>")
    stats_html = "".join(f'<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>' for v, l in stats)
    oc = Counter(r.get("outcome") for r in runs)
    # таблица сопряжённости: верный SQL → верный график?
    both = c(lambda r: r.get("sql_ex") and (r.get("chart_ex") or {}).get("ok"))
    sql_only = c(lambda r: r.get("sql_ex") and not (r.get("chart_ex") or {}).get("ok"))
    chart_only = c(lambda r: not r.get("sql_ex") and (r.get("chart_ex") or {}).get("ok"))
    neither = n - both - sql_only - chart_only
    matrix = (f"<table class=m><tr><th></th><th>Chart-EX ✓</th><th>Chart-EX ✗</th></tr>"
              f"<tr><th>SQL-EX ✓</th><td>{both}</td><td>{sql_only}</td></tr>"
              f"<tr><th>SQL-EX ✗</th><td>{chart_only}</td><td>{neither}</td></tr></table>")
    outcomes = " · ".join(f"{OUTCOME_RU.get(k, k)}: {v}" for k, v in oc.most_common())
    dbs = "".join(f"<option>{esc(d)}</option>" for d in sorted({r["db_id"] for r in runs}))
    chats = "".join(chat(i, r, out) for i, r in enumerate(runs, 1))
    doc = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PAUQ: графики в стиле МТС</title><style>{CSS}</style></head><body><div class=wrap>
<h1>PAUQ → SQL → график → стиль МТС</h1>
<p class=sub>{n} «сильных» русских вопросов PAUQ (сначала все test, затем случайные train) прогнаны через весь сервис: SQL-агент (LoRA, Ollama) → pandas → matplotlib →
«Подтвердить» → генеративная правка «в стиле МТС» (FLUX.2 Klein 9B + LoRA, одна итерация). Промпты — три уровня из диплома Матвея
(цвет → форма → реализм), 59 из 100 — с яйцом; к каждому добавлено «Сохрани график 1 в 1…». <b>SQL-EX</b> — строки запроса сервиса совпали с эталонными. <b>Chart-EX</b> — числа (и подписи, если есть)
на графике совпали с эталонным ответом: ловит потерю данных между SQL и графиком.</p>
<div class=stats>{stats_html}</div><p class=sub>Итоги: {outcomes}. Верный SQL → верный график:</p>{matrix}
<p class=sub>Судья Матвея (Qwen2.5-VL-7b) по уровням сложности промпта и по отдельным промптам:</p>{judge_tbl}
<div class=f><select id=o><option value="">любой итог</option>{"".join(f'<option value="{k}">{OUTCOME_RU.get(k, k)}</option>' for k in oc)}</select>
<select id=sq><option value="">SQL-EX любой</option><option value=1>SQL-EX ✓</option><option value=0>SQL-EX ✗</option></select>
<select id=ce><option value="">Chart-EX любой</option><option value=1>Chart-EX ✓</option><option value=0>Chart-EX ✗</option></select>
<select id=lv><option value="">любой уровень</option><option value=1>ур.1 · цвет</option><option value=2>ур.2 · форма</option><option value=3>ур.3 · реализм</option></select>
<select id=egg><option value="">яйцо / нет</option><option value=1>с яйцом</option><option value=0>без яйца</option></select>
<select id=ap><option value="">AP любой</option><option value=1>AP = 1</option><option value=0>AP = 0</option></select>
<select id=db><option value="">любая база</option>{dbs}</select><select id=sp><option value="">test+train</option><option>test</option><option>train</option></select>
<span id=cnt class=sub></span></div>{chats}</div>
<script>const $=i=>document.getElementById(i);function f(){{const v={{o:$('o').value,sql:$('sq').value,cex:$('ce').value,lv:$('lv').value,egg:$('egg').value,ap:$('ap').value,db:$('db').value,sp:$('sp').value}};let n=0;
document.querySelectorAll('.chat').forEach(e=>{{const ok=Object.entries(v).every(([k,x])=>!x||e.dataset[k]==x);e.style.display=ok?'':'none';n+=ok}});$('cnt').textContent=n+' диалогов'}}
['o','sq','ce','lv','egg','ap','db','sp'].forEach(i=>$(i).onchange=f);f();</script></body></html>"""
    Path(args.out).write_text(doc, encoding="utf-8")
    print(f"{args.out}: {Path(args.out).stat().st_size // 1024} KB, диалогов {n}")


if __name__ == "__main__":
    main()
