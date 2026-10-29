"""Отчёт по прогону run_chart_types.py: сводка Chart-EX по целевым типам и карточка на вопрос —
исходный график и его перестроения (линия, область, кольцо, круг, гистограмма, накопление…).

    .venv/bin/python scripts/make_chart_types_review.py PAUQ_ТИПЫ_ГРАФИКОВ -o ТИПЫ_ГРАФИКОВ_ОТЧЁТ.html
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

SKIP = {"bar", "barh"}  # столбцы среди целевых типов не показываем
NOT_COMPARABLE = {"histogram", "box"}  # агрегируют значения — построчная сверка с эталоном неприменима
TYPE_RU = {"box": "ящик с усами", "bar": "столбцы", "barh": "горизонтальные столбцы", "line": "линия", "area": "область", "pie": "круговая",
           "doughnut": "кольцевая", "histogram": "гистограмма", "stacked_bar": "с накоплением", "scatter": "рассеяние"}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#111;--ink2:#555;--mut:#888;--line:rgba(0,0,0,.1);--blue:#2a78d6;--ok:#0c8a3e;--bad:#c8332d}
@media(prefers-color-scheme:dark){:root{--bg:#111;--card:#1b1b1a;--ink:#f2f2f2;--ink2:#c4c3bb;--mut:#999;--line:rgba(255,255,255,.12);--blue:#4b93ea;--ok:#3ccf74;--bad:#ff7a73}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.5 system-ui,-apple-system,sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:26px 16px 80px}h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:26px 0 10px}p.s{color:var(--ink2);max-width:95ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}.t{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}.tv{font-size:26px}.tl{font-size:12px;color:var(--ink2)}
table.s{border-collapse:collapse;background:var(--card);font-size:13.5px}table.s td,table.s th{border:1px solid var(--line);padding:6px 12px;text-align:center}table.s td:first-child{text-align:left}
.f{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line)}
select,input{font:inherit;font-size:13px;padding:5px 8px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:14px}
.ch{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px}.n{font-weight:700;font-size:14px}.id{color:var(--mut)}
.b{padding:1px 8px;border-radius:20px;background:rgba(42,120,214,.10);color:var(--blue)}.b.ok{background:rgba(12,138,62,.12);color:var(--ok)}.b.bad{background:rgba(200,51,45,.12);color:var(--bad)}
.q{font-size:15px;font-weight:550;margin:8px 0}.row{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.v{border:1px solid var(--line);border-radius:10px;padding:8px}.v .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-bottom:5px;display:flex;justify-content:space-between}
.v img{width:100%;border-radius:6px;background:#fff;display:block}.muted{font-size:12px;color:var(--mut);margin-top:5px}.issue{color:var(--bad);font-size:12px;margin-top:5px}
details{margin-top:6px;font-size:12.5px}summary{cursor:pointer;color:var(--blue)}pre{font:11px/1.45 ui-monospace,Menlo,monospace;background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:7px 9px;white-space:pre-wrap;word-break:break-word;margin:5px 0}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def img(path: Path) -> str:
    if not path.exists():
        return '<div class="muted">картинки нет</div>'
    data = path.read_bytes()
    mime = "png"
    if Image is not None:
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((700, 700))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        data, mime = buf.getvalue(), "jpeg"
    return f'<img loading="lazy" src="data:image/{mime};base64,{base64.b64encode(data).decode()}">'


def variant(label, path: Path | None, ce: dict | None, prompt: str = "", secs=None, code: str = "", msg: str = "", na: bool = False) -> str:
    ok = None if na else (ce.get("ok") if ce else None)
    mark = "" if ok is None else (f'<span class="b ok">данные ✓</span>' if ok else '<span class="b bad">данные ✗</span>')
    body = img(path) if path else f'<div class="issue">{esc(msg or "график не перестроен")}</div>'
    extra = f'<div class="muted">«{esc(prompt)}» · {secs} с</div>' if prompt else ""
    if ce and path:
        extra += (f'<div class="muted">точек {ce.get("n_points")} / строк {ce.get("n_gold")}; числа {"✓" if ce.get("values_ok") else "✗"}'
                  + ("" if ce.get("labels_ok") is None else f', подписи {"✓" if ce.get("labels_ok") else "✗"}') + "</div>")
    if code:
        extra += f'<details><summary>код</summary><pre>{esc(code)}</pre></details>'
    return f'<div class="v"><div class="lbl"><span>{esc(label)}</span>{mark}</div>{body}{extra}</div>'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("-o", "--out", default="ТИПЫ_ГРАФИКОВ_ОТЧЁТ.html")
    args = ap.parse_args()
    out = Path(args.run_dir)
    runs = json.load(open(out / "runs.json", encoding="utf-8"))
    for r in runs:
        r["edits"] = [e for e in r.get("edits", []) if e["type"] not in SKIP]
    charts = [r for r in runs if r.get("outcome") == "chart"]
    edits = [(r, e) for r in charts for e in r.get("edits", [])]
    by = defaultdict(lambda: [0, 0, 0])
    for _, e in edits:
        d = by[e["type"]]; d[0] += 1; d[1] += int(e["ok"]); d[2] += int(e["chart_ex"].get("ok", False))
    comparable = [(r, e) for r, e in edits if e["type"] not in NOT_COMPARABLE]
    pct = lambda k, n: f"{k}/{n} = {k / n * 100:.0f}%" if n else "—"
    n_ok = sum(e["ok"] for _, e in edits); n_ex = sum(e["chart_ex"].get("ok", False) for _, e in comparable)
    tiles = [(len(runs), "вопросов"), (len(charts), "исходных графиков"), (len(edits), "смен типа"),
             (pct(n_ok, len(edits)), "график перестроен"), (pct(n_ex, len(comparable)), "данные совпали с эталоном (без гистограмм и ящиков)"),
             (sum(1 for r in charts if r.get("base_chart_ex", {}).get("ok")), "исходных с верными данными")]
    tiles_html = "".join(f'<div class=t><div class=tv>{v}</div><div class=tl>{l}</div></div>' for v, l in tiles)
    rows = "".join(f"<tr><td>{TYPE_RU.get(t, t)} ({t})</td><td>{d[0]}</td><td>{pct(d[1], d[0])}</td><td>{"не применимо" if t in NOT_COMPARABLE else pct(d[2], d[0])}</td></tr>"
                   for t, d in sorted(by.items(), key=lambda kv: -kv[1][0]))
    # потери по цепочке: исходный верен, а после смены типа — нет
    lost = [(r, e) for r, e in comparable if r.get("base_chart_ex", {}).get("ok") and e["ok"] and not e["chart_ex"].get("ok")]
    notbuilt = [(r, e) for r, e in edits if not e["ok"]]
    lost_html = "".join(f'<li><a href="#{esc(r["id"])}">{esc(r["id"])}</a> → {TYPE_RU.get(e["type"], e["type"])}: точек {e["chart_ex"].get("n_points")} / строк {e["chart_ex"].get("n_gold")}, '
                        f'числа {"✓" if e["chart_ex"].get("values_ok") else "✗"}</li>' for r, e in lost[:40])
    nb_html = "".join(f'<li><a href="#{esc(r["id"])}">{esc(r["id"])}</a> → {TYPE_RU.get(e["type"], e["type"])}: <i>{esc((e.get("message") or "")[:120])}</i></li>' for r, e in notbuilt[:40])
    types = "".join(f"<option value='{t}'>{TYPE_RU.get(t, t)}</option>" for t in sorted(by))
    cards = []
    for r in runs:
        attrs = f'data-o="{r.get("outcome")}" data-db="{esc(r["db_id"])}" data-src="{r.get("chart_type")}" data-types="{" ".join(e["type"] for e in r.get("edits", []))}" ' \
                f'data-lost="{int(any(e["ok"] and not e["chart_ex"].get("ok") for e in r.get("edits", [])))}" data-nb="{int(any(not e["ok"] for e in r.get("edits", [])))}"'
        head = (f'<div class=ch><span class=n>{esc(r["id"])}</span><span class=b>{esc(r["db_id"])}</span><span class=b>исходный: {TYPE_RU.get(r.get("chart_type"), r.get("chart_type"))}</span>'
                f'<span class=b>строк: {esc(r.get("pred_n"))}</span></div><div class=q>{esc(r["question"])}</div>')
        if r.get("outcome") != "chart":
            cards.append(f'<section id="{esc(r["id"])}" class=card {attrs}>{head}<div class=issue>{esc(r.get("message") or r.get("error") or "график не построен")}</div></section>')
            continue
        vs = [variant("исходный график", out / r["base_png"], r.get("base_chart_ex"), code=r.get("base_code") or "")]
        for e in r["edits"]:
            vs.append(variant(TYPE_RU.get(e["type"], e["type"]), (out / e["png"]) if e.get("png") else None, e["chart_ex"] if e.get("png") else None,
                              e["prompt"], e.get("t"), e.get("code") or "", e.get("message"), na=e["type"] in NOT_COMPARABLE))
        sql = f'<details><summary>SQL сервиса</summary><pre>{esc(r.get("pred_sql"))}</pre></details>'
        cards.append(f'<section id="{esc(r["id"])}" class=card {attrs}>{head}<div class=row>{"".join(vs)}</div>{sql}</section>')
    dbs = "".join(f"<option>{esc(d)}</option>" for d in sorted({r['db_id'] for r in runs}))
    doc = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Смена типа графика</title><style>{CSS}</style></head><body><div class=wrap>
<h1>Те же вопросы — другие типы графиков</h1>
<p class=s>{len(runs)} вопросов PAUQ из прогона с графиками. Для каждого заново построен исходный график, затем правками текстом до «Подтвердить» он перестроен
в другие типы (правки в сессии накапливаются: каждая следующая применяется к предыдущему результату). После каждой правки данные на графике сверены
с эталонным ответом (Chart-EX: числа каждой серии и подписи).</p>
<div class=tiles>{tiles_html}</div>
<table class=s><tr><th>целевой тип</th><th>правок</th><th>график перестроен</th><th>данные совпали</th></tr>{rows}</table>
<h2>Где смена типа теряет данные ({len(lost)})</h2><ul>{lost_html or "<li>нет</li>"}</ul>
<h2>Где график не перестроился ({len(notbuilt)})</h2><ul>{nb_html or "<li>нет</li>"}</ul>
<h2>Все вопросы</h2>
<div class=f><select id=ty><option value="">любой целевой тип</option>{types}</select><select id=db><option value="">любая база</option>{dbs}</select>
<select id=lost><option value="">все</option><option value=1>есть потеря данных</option></select><select id=nb><option value="">все</option><option value=1>есть неперестроенные</option></select>
<input id=q placeholder="поиск" size=22><span id=cnt class=muted></span></div>
{"".join(cards)}</div>
<script>const $=i=>document.getElementById(i);function f(){{const ty=$('ty').value,db=$('db').value,lost=$('lost').value,nb=$('nb').value,q=$('q').value.toLowerCase();let n=0;
document.querySelectorAll('.card').forEach(e=>{{const ok=(!ty||e.dataset.types.split(' ').includes(ty))&&(!db||e.dataset.db==db)&&(!lost||e.dataset.lost==lost)&&(!nb||e.dataset.nb==nb)&&(!q||e.textContent.toLowerCase().includes(q));e.style.display=ok?'':'none';n+=ok}});$('cnt').textContent=n+' вопросов'}}
['ty','db','lost','nb'].forEach(i=>$(i).onchange=f);$('q').oninput=f;f();</script></body></html>"""
    Path(args.out).write_text(doc, encoding="utf-8")
    print(f"{args.out}: {Path(args.out).stat().st_size // 1024} KB, вопросов {len(runs)}, смен типа {len(edits)}")


if __name__ == "__main__":
    main()
