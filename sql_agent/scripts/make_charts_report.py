"""Локальный отчёт по графикам прогона PAUQ: метрики, разбор потерь и карточка на каждый вопрос
(вопрос → SQL сервиса и эталон → результаты обоих → график → правка «в стиле МТС» с вердиктом судьи).
Картинки подключаются относительными путями — отчёт открывается из папки sql_agent.

    .venv/bin/python scripts/make_charts_report.py
"""
from __future__ import annotations

import html
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "PAUQ_ГРАФИКИ_ПРОГОН"
OUT = ROOT / "ГРАФИКИ_PAUQ_ОТЧЁТ.html"
sys.path.insert(0, str(ROOT / "scripts"))
import run_pauq_charts as m  # noqa: E402

CRIT_RU = {
    "E1_requested_edit_visible": "A1 изменение видно", "E2_correct_target_elements": "A2 правильные элементы",
    "E3_edit_completeness": "A3 полнота", "E4_edit_specificity_no_unrequested_edit": "A4 без лишних правок",
    "E5_visual_integration_and_cleanliness": "A5 целостность", "P1_element_count_and_presence": "P1 состав элементов",
    "P2_spatial_layout_preservation": "P2 расположение", "P3_scale_proportion_and_quantitative_relations": "P3 масштабы",
    "P4_visual_encoding_and_series_identity": "P4 кодирование", "P5_no_extra_artifacts_or_corruption": "P5 без артефактов",
}
LEVEL = {1: "ур.1 цвет", 2: "ур.2 форма", 3: "ур.3 реализм"}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def table(cols, rows, limit=12) -> str:
    if rows is None:
        return '<div class="muted">запрос не выполнился</div>'
    if not rows:
        return '<div class="muted">пусто</div>'
    head = "".join(f"<th>{esc(c)}</th>" for c in cols) if cols else ""
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in r) + "</tr>" for r in rows[:limit])
    more = f'<div class="muted">… всего строк: {len(rows)}</div>' if len(rows) > limit else ""
    return f"<div class=tw><table class=d>{'<tr>' + head + '</tr>' if head else ''}{body}</table></div>{more}"


def run_with_cols(db_id, sql):
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{m.db_file(db_id)}?mode=ro", uri=True)
        cur = con.execute(sql)
        return [d[0] for d in cur.description], [list(r) for r in cur.fetchmany(5000)]
    except Exception as exc:  # noqa: BLE001
        return [str(exc)], None


def badge(ok, yes, no, cls_yes="ok", cls_no="bad"):
    return f'<span class="b {cls_yes if ok else cls_no}">{yes if ok else no}</span>'


def verdict_of(r):
    ce = (r.get("chart_ex") or {}).get("ok")
    if r.get("outcome") != "chart":
        return "nochart"
    if r.get("sql_ex") and ce:
        return "ok"
    if r.get("sql_ex") and not ce:
        return "lost"
    if not r.get("sql_ex") and ce:
        return "sqldiff"
    return "sqlbad"


VERDICT_RU = {"ok": "SQL ✓ · график ✓", "lost": "SQL ✓ · график ✗ (потеря на стыке)", "sqldiff": "SQL ≠ эталон · график ✓",
              "sqlbad": "SQL ✗ · график ✗", "nochart": "график не построен"}


def card(i, r, judge):
    v = verdict_of(r)
    ce = r.get("chart_ex") or {}
    j = judge.get(r["id"])
    gcols, grows = run_with_cols(r["db_id"], r["gold_sql"])
    pcols, prows = run_with_cols(r["db_id"], r["pred_sql"]) if r.get("pred_sql") else ([], None)
    attrs = (f'data-v="{v}" data-db="{esc(r["db_id"])}" data-sp="{r.get("split")}" data-ct="{r.get("chart_type")}" '
             f'data-ap="{"" if not j else j["AP"]}" data-egg="{int("яйц" in (r.get("edit") or ""))}"')
    head = (f'<div class=ch><span class=n>#{i}</span><span class=id>{esc(r["id"])}</span><span class=b>{esc(r["db_id"])}</span>'
            f'<span class=b>{r.get("split")}</span>'
            + (badge(r.get("sql_ex"), "SQL-EX ✓", "SQL-EX ✗") if r.get("pred_sql") else "")
            + (badge(ce.get("ok"), "Chart-EX ✓", "Chart-EX ✗") if r.get("outcome") == "chart" else '<span class="b bad">без графика</span>')
            + "</div>")
    q = f'<div class=q>{esc(r["question"])}</div>'
    if r.get("chart_png") and r.get("edit_png"):
        jv = judge.get(r["id"])
        jb = (f'{badge(jv["A"], "A=1", "A=0")}{badge(jv["P"], "P=1", "P=0")}{badge(jv["AP"], "AP=1", "AP=0")}' if jv else "")
        pic = (f'<div class=two><div><div class=lbl>график</div><a href="PAUQ_ГРАФИКИ_ПРОГОН/{r["chart_png"]}" target=_blank>'
               f'<img loading=lazy src="PAUQ_ГРАФИКИ_ПРОГОН/{r["chart_png"]}"></a></div>'
               f'<div><div class=lbl>после правки · {LEVEL.get(r.get("level"), "")} · {esc(r.get("edit_code"))}</div>'
               f'<a href="PAUQ_ГРАФИКИ_ПРОГОН/{r["edit_png"]}" target=_blank><img loading=lazy src="PAUQ_ГРАФИКИ_ПРОГОН/{r["edit_png"]}"></a></div></div>'
               f'<div class=q2>✎ {esc(r.get("edit"))}</div><div class=agg>{jb}</div>')
    elif r.get("chart_png"):
        pic = (f'<a href="PAUQ_ГРАФИКИ_ПРОГОН/{r["chart_png"]}" target=_blank><img loading=lazy src="PAUQ_ГРАФИКИ_ПРОГОН/{r["chart_png"]}"></a>'
               f'<div class=muted>Правка «в стиле МТС» не выполнена (сбой памяти при прогоне, HTTP 503).</div>')
    else:
        pic = f'<div class="issue">{esc(r.get("assistant_message") or r.get("error") or "график не построен")}</div>'
    note = f'<div class="issue">{esc(r["note"])}</div>' if r.get("note") else ""
    ce_line = ""
    if r.get("outcome") == "chart":
        ce_line = (f'<div class=muted>Chart-EX: точек на графике {ce.get("n_points")}, строк в эталоне {ce.get("n_gold")}'
                   f'{f" (из них с NULL {r.get(chr(103)+"old_null_rows")} — на график не попадают)" if r.get("gold_null_rows") else ""}; '
                   f'серий {ce.get("n_series", 1)}; числа {"совпали" if ce.get("values_ok") else "не совпали"}'
                   f'{"" if ce.get("labels_ok") is None else ", подписи " + ("совпали" if ce.get("labels_ok") else "не совпали")} · '
                   f'{r.get("t_chart", "?")} с</div>')
    sqls = (f'<div class=two><div><div class=lbl>SQL сервиса</div><pre>{esc(r.get("pred_sql") or "—")}</pre>{table(pcols, prows)}</div>'
            f'<div><div class=lbl>Эталон PAUQ</div><pre>{esc(r["gold_sql"])}</pre>{table(gcols, grows)}</div></div>')
    pts = r.get("points") or []
    pts_tbl = table(["подпись", "x", "y", "серия"], [[p.get("label"), p.get("x"), p.get("y"), p.get("series")] for p in pts])
    code = f'<pre>{esc(r.get("code"))}</pre>' if r.get("code") else ""
    edit = ""
    if r.get("edit_png"):
        crit = ""
        if j:
            crit = "".join(f'<tr><td class="{"okc" if c["passed"] else "badc"}">{"✓" if c["passed"] else "✗"}</td><td>{CRIT_RU.get(k, k)}</td>'
                           f'<td>{esc(c.get("evidence") or c.get("reason"))}</td></tr>' for g in ("adherence", "preservation") for k, c in j[g].items())
            crit = (f'<div class=agg>{badge(j["A"], "A=1", "A=0")}{badge(j["P"], "P=1", "P=0")}{badge(j["AP"], "AP=1", "AP=0")}</div>'
                    f'<table class=d>{crit}</table>')
        edit = (f'<details><summary>Правка: полный промпт и 10 критериев судьи</summary><div class=q2>{esc(r.get("edit_prompt"))}</div>'
                f'<div class=muted>время правки: {r.get("t_edit", "?")} с</div>'
                f'<div class=muted>Промпт диффузии: {esc(r.get("enhanced_prompt"))}</div>{crit}</details>')
    return (f'<section id="{esc(r["id"])}" class="card v-{v}" {attrs}>{head}{q}<div class=pic>{pic}</div>{note}{ce_line}'
            f'<details><summary>SQL сервиса и эталон, результаты обоих</summary>{sqls}</details>'
            f'<details><summary>Данные на графике ({ce.get("n_points", len(pts))} точек{", показаны первые " + str(len(pts)) if ce.get("n_points", 0) > len(pts) else ""})</summary>{pts_tbl}</details>'
            f'<details><summary>Код графика</summary>{code}</details>{edit}</section>')


def main() -> None:
    runs = json.load(open(RUN / "runs.json", encoding="utf-8"))
    judge = json.load(open(RUN / "judge.json", encoding="utf-8")) if (RUN / "judge.json").exists() else {}
    n = len(runs)
    ch = [r for r in runs if r.get("outcome") == "chart"]
    V = Counter(verdict_of(r) for r in runs)
    sql_ok = sum(bool(r.get("sql_ex")) for r in runs)
    sql_strict = sum(bool(r.get("sql_ex_strict")) for r in runs)
    chart_ok = sum((r.get("chart_ex") or {}).get("ok", False) for r in runs)
    tiles = [(n, "вопросов"), (len(ch), "графиков построено"), (n - len(ch), "без графика"),
             (f"{sql_ok}", "SQL-EX (верный SQL)"), (f"{chart_ok}", "Chart-EX (верные данные на графике)"),
             (V["lost"], "потерь на стыке SQL → график"), (sum((r.get("chart_attempt") or 1) > 1 for r in ch), "графиков со 2+ попытки рендера")]
    tiles_html = "".join(f'<div class=t><div class=tv>{v}</div><div class=tl>{l}</div></div>' for v, l in tiles)
    matrix = (f'<table class=m><tr><th></th><th>данные на графике верны</th><th>данные неверны</th></tr>'
              f'<tr><th>SQL верный</th><td class=g>{V["ok"]}</td><td class=r>{V["lost"]}</td></tr>'
              f'<tr><th>SQL неверный</th><td class=y>{V["sqldiff"]}</td><td class=r>{V["sqlbad"]}</td></tr></table>')

    def grp(rows, key):
        c = Counter(key(r) for r in rows)
        out = []
        for k, cnt in c.most_common():
            sub = [r for r in rows if key(r) == k]
            out.append(f"<tr><td>{esc(k)}</td><td>{cnt}</td><td>{sum(1 for r in sub if r.get('outcome') == 'chart')}</td>"
                       f"<td>{sum(bool(r.get('sql_ex')) for r in sub)}</td><td>{sum((r.get('chart_ex') or {}).get('ok', False) for r in sub)}</td></tr>")
        return "".join(out)
    by_type = grp(runs, lambda r: r.get("chart_type"))
    by_db = grp(runs, lambda r: r["db_id"])
    lost = "".join(f'<li><a href="#{esc(r["id"])}">{esc(r["id"])}</a> — {esc(r.get("note") or r["question"])}</li>' for r in runs if verdict_of(r) == "lost")
    nochart = "".join(f'<li><a href="#{esc(r["id"])}">{esc(r["id"])}</a> — {esc(r["question"][:90])}: '
                      f'<i>{esc((r.get("assistant_message") or r.get("error") or "")[:120])}</i></li>' for r in runs if r.get("outcome") != "chart")

    jv = list(judge.values())
    edited = [r for r in runs if r.get("edit_png")]
    def ap(sub):
        vs = [judge[r["id"]] for r in sub if r["id"] in judge]
        return f"{sum(v['AP'] for v in vs)}/{len(vs)}" if vs else "—"
    edit_rows = "".join(f"<tr><td>{LEVEL[l]}</td><td>{ap([r for r in edited if r.get('level') == l])}</td></tr>" for l in (1, 2, 3))
    edit_rows += f"<tr><td>с яйцом</td><td>{ap([r for r in edited if 'яйц' in r.get('edit', '')])}</td></tr>"
    edit_rows += f"<tr><td>без яйца</td><td>{ap([r for r in edited if 'яйц' not in r.get('edit', '')])}</td></tr>"

    cards = "".join(card(i, r, judge) for i, r in enumerate(runs, 1))
    dbs = "".join(f"<option>{esc(d)}</option>" for d in sorted({r['db_id'] for r in runs}))
    vopts = "".join(f'<option value="{k}">{VERDICT_RU[k]} ({V[k]})</option>' for k in ("ok", "lost", "sqldiff", "sqlbad", "nochart") if V[k])

    doc = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Графики по PAUQ</title><style>
:root{{color-scheme:light;--bg:#f7f7f5;--card:#fff;--ink:#111;--ink2:#555;--mut:#888;--line:rgba(0,0,0,.1);--blue:#2a78d6;--ok:#0c8a3e;--bad:#c8332d;--warn:#b26b00}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111;--card:#1b1b1a;--ink:#f2f2f2;--ink2:#c4c3bb;--mut:#999;--line:rgba(255,255,255,.12);--blue:#4b93ea;--ok:#3ccf74;--bad:#ff7a73;--warn:#f0a83a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:1200px;margin:0 auto;padding:26px 16px 80px}}h1{{font-size:26px;margin:0 0 6px}}h2{{font-size:19px;margin:30px 0 10px}}
p.s{{color:var(--ink2);max-width:90ch}}.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}}
.t{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}.tv{{font-size:26px;font-variant-numeric:tabular-nums}}.tl{{font-size:12px;color:var(--ink2)}}
table.m,table.s{{border-collapse:collapse;background:var(--card);font-size:13.5px}}table.m td,table.m th,table.s td,table.s th{{border:1px solid var(--line);padding:6px 12px;text-align:center}}
table.s td:first-child{{text-align:left}}td.g{{color:var(--ok);font-weight:650}}td.r{{color:var(--bad);font-weight:650}}td.y{{color:var(--warn);font-weight:650}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}@media(max-width:860px){{.cols{{grid-template-columns:1fr}}}}
.f{{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line)}}
select,input{{font:inherit;font-size:13px;padding:5px 8px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--ink)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(640px,1fr));gap:14px;margin-top:14px}}@media(max-width:600px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--ok);border-radius:12px;padding:12px 14px}}
.card.v-lost,.card.v-sqlbad,.card.v-nochart{{border-left-color:var(--bad)}}.card.v-sqldiff{{border-left-color:var(--warn)}}
.ch{{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px}}.n{{font-weight:700;font-size:14px}}.id{{color:var(--mut)}}
.b{{padding:1px 8px;border-radius:20px;background:rgba(42,120,214,.10);color:var(--blue)}}.b.ok{{background:rgba(12,138,62,.12);color:var(--ok)}}.b.bad{{background:rgba(200,51,45,.12);color:var(--bad)}}
.q{{font-size:15px;font-weight:550;margin:8px 0}}.q2{{font-size:13px;color:var(--ink2);margin:6px 0}}.pic img{{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;display:block}}
.muted{{font-size:12.5px;color:var(--mut);margin-top:6px}}.issue{{background:rgba(200,51,45,.08);border:1px solid rgba(200,51,45,.3);color:var(--bad);border-radius:8px;padding:7px 10px;font-size:13px;margin-top:8px}}
details{{margin-top:7px;font-size:13px}}summary{{cursor:pointer;color:var(--blue)}}pre{{font:11.5px/1.45 ui-monospace,Menlo,monospace;background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:7px 9px;white-space:pre-wrap;word-break:break-word;margin:5px 0}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.two img{{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff}}.lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-top:6px}}
.tw{{overflow-x:auto}}table.d{{border-collapse:collapse;font-size:12px;margin-top:4px}}table.d td,table.d th{{border:1px solid var(--line);padding:2px 7px;text-align:left;vertical-align:top}}
td.okc{{color:var(--ok)}}td.badc{{color:var(--bad)}}.agg{{display:flex;gap:6px;margin:6px 0}}ul{{margin:6px 0;padding-left:20px}}a{{color:var(--blue)}}
</style></head><body><div class=wrap>
<h1>Графики по русским вопросам PAUQ</h1>
<p class=s>100 «сильных» вопросов на построение графика (91 из test и 9 из train; отбор: <code>PAUQ_ГРАФИКИ_ОТБОР/</code>) прогнаны через
весь сервис: вопрос по-русски → SQL-агент (LoRA через Ollama) → pandas → matplotlib в оркестраторе Матвея. Каждая карточка ниже — один вопрос:
график, SQL сервиса против эталона с результатами обоих, данные на графике, код и правка «в стиле МТС» с вердиктом судьи.</p>
<div class=tiles>{tiles_html}</div>
<div class=cols><div><h2>Верный SQL → верный график?</h2>{matrix}
<p class=s><b>SQL-EX</b> — результат запроса сервиса совпадает с эталоном (порядок строк и колонок не важен, как в оценке Spider;
со строгим порядком колонок было бы {sql_strict}). <b>Chart-EX</b> — числа на графике (по каждой серии) и подписи совпадают с эталонным
ответом; строки эталона с NULL не учитываются, т.к. на график попасть не могут. Жёлтые — SQL отличается от эталона, но данные на графике те же
(например, лишняя колонка id).</p></div>
<div><h2>По типам графиков</h2><table class=s><tr><th>тип</th><th>вопросов</th><th>графиков</th><th>SQL-EX</th><th>Chart-EX</th></tr>{by_type}</table>
<h2>Правки «в стиле МТС» (AP судьи)</h2><table class=s><tr><th>срез</th><th>AP</th></tr>{edit_rows}</table>
<p class=s>Оценено {len(jv)} правок; ещё {len(ch) - len(edited)} не выполнены из-за нехватки памяти (HTTP 503) и в цифры не входят.</p></div></div>
<h2>Где теряются данные</h2>
<p class=s><b>Потери на стыке SQL → график ({V["lost"]}):</b> SQL верный, а на графике данные расходятся.</p><ul>{lost}</ul>
<p class=s><b>Графики не построены ({n - len(ch)}):</b></p><ul>{nochart}</ul>
<p class=s>Остальные ошибки ({V["sqlbad"]}) — неверный SQL: смотрите карточки с фильтром «SQL ✗ · график ✗», там SQL сервиса и эталон с результатами стоят рядом.</p>
<details><summary>По базам</summary><table class=s><tr><th>база</th><th>вопросов</th><th>графиков</th><th>SQL-EX</th><th>Chart-EX</th></tr>{by_db}</table></details>
<h2>Все вопросы</h2>
<div class=f><select id=v><option value="">все исходы</option>{vopts}</select>
<select id=ct><option value="">любой тип</option><option>bar</option><option>barh</option><option>line</option><option>pie</option></select>
<select id=db><option value="">любая база</option>{dbs}</select><select id=sp><option value="">test+train</option><option>test</option><option>train</option></select>
<select id=ap><option value="">правка: любая</option><option value=1>AP = 1</option><option value=0>AP = 0</option></select>
<select id=egg><option value="">яйцо / нет</option><option value=1>с яйцом</option><option value=0>без яйца</option></select>
<input id=q placeholder="поиск по вопросу" size=22><span id=cnt class=muted></span></div>
<div class=grid id=g>{cards}</div></div>
<script>const $=i=>document.getElementById(i);function f(){{const v={{v:$('v').value,ct:$('ct').value,db:$('db').value,sp:$('sp').value,ap:$('ap').value,egg:$('egg').value}};
const q=$('q').value.toLowerCase();let n=0;document.querySelectorAll('.card').forEach(e=>{{const ok=Object.entries(v).every(([k,x])=>!x||e.dataset[k]==x)&&(!q||e.textContent.toLowerCase().includes(q));
e.style.display=ok?'':'none';n+=ok}});$('cnt').textContent=n+' вопросов'}}['v','ct','db','sp','ap','egg'].forEach(i=>$(i).onchange=f);$('q').oninput=f;f();</script>
</body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"{OUT.name}: {OUT.stat().st_size // 1024} KB, карточек {n}")


if __name__ == "__main__":
    main()
