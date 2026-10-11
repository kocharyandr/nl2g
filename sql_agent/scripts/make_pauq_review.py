#!/usr/bin/env python3
"""Сравнительный отчёт по PAUQ: русский вопрос против английского.

Страница показывает обе попытки рядом и даёт проставить оценки вручную —
авто-метрика (совпадение результата с эталоном) остаётся подсказкой.

    scripts/make_pauq_review.py pauq_results.json -o PAUQ_РАЗБОР.html
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def esc(x):
    return html.escape("" if x is None else str(x))


def rows_table(rows, limit=6):
    if not rows:
        return '<div class="pill">— пусто —</div>'
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in r) + "</tr>" for r in rows[:limit])
    more = f'<div class="pill">…из {len(rows)}</div>' if len(rows) > limit else ""
    return f'<table class="rows"><tbody>{body}</tbody></table>{more}'


def side(lang, label, rec, gold_sql):
    ok = rec.get("exec_match")
    mark = '<span class="v y">результат совпал</span>' if ok else '<span class="v n">не совпал</span>'
    same_sql = (rec.get("sql") or "").strip().rstrip(";") == gold_sql.strip().rstrip(";")
    tpl = '<span class="pill">SQL дословно как эталон</span>' if same_sql else ""
    err = f'<div class="err">{esc(rec.get("exec_error") or rec.get("message"))}</div>' if (
        rec.get("exec_error") or rec.get("status") != "ok") else ""
    return f"""<div class="side {lang}">
  <div class="lbl">{label} {mark} {tpl}</div>
  <pre>{esc(rec.get("sql") or "— SQL не получен —")}</pre>
  {err}
  <div class="meta">строк {esc(rec.get("row_count"))} · попыток критика {esc(rec.get("attempts"))} · {esc(rec.get("sec"))}с</div>
  {rows_table(rec.get("rows") or [])}
</div>"""


def build(records):
    n = len(records)
    ru_ok = sum(1 for r in records if r["ru"].get("exec_match"))
    en_ok = sum(1 for r in records if r["en"].get("exec_match"))
    both = sum(1 for r in records if r["ru"].get("exec_match") and r["en"].get("exec_match"))
    only_en = sum(1 for r in records if r["en"].get("exec_match") and not r["ru"].get("exec_match"))
    only_ru = sum(1 for r in records if r["ru"].get("exec_match") and not r["en"].get("exec_match"))

    P = ["""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PAUQ — русский против английского</title><style>
:root{color-scheme:light;--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:rgba(11,11,11,.10);--grid:#e1e0d9;--blue:#2a78d6;--orange:#eb6834;--ok:#0ca30c;--bad:#d03b3b}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--line:rgba(255,255,255,.10);--grid:#2c2c2a;--blue:#3987e5;--orange:#d95926}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:15px;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:28px 18px 70px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}h2{font-size:19px;margin:30px 0 12px}
.sub{color:var(--ink2);max-width:82ch;margin:0 0 20px}
.stats{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin:18px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stat .v{font-size:27px;line-height:1;font-variant-numeric:tabular-nums}
.stat .l{font-size:12px;color:var(--ink2);margin-top:6px}
.stat.ru{border-left:3px solid var(--blue)}.stat.en{border-left:3px solid var(--orange)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.q{font-size:15.5px;font-weight:620;margin:0 0 2px}
.qen{font-size:13.5px;color:var(--muted);margin-bottom:10px}
.gold{font-size:12px;color:var(--muted);margin-bottom:12px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:900px){.pair{grid-template-columns:1fr}}
.side{border:1px solid var(--line);border-radius:10px;padding:12px}
.side.ru{border-left:3px solid var(--blue)}.side.en{border-left:3px solid var(--orange)}
.lbl{font-size:12px;color:var(--muted);margin-bottom:7px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.v{font-size:11px;padding:2px 8px;border-radius:20px}
.v.y{background:rgba(12,163,12,.14);color:var(--ok)}.v.n{background:rgba(208,59,59,.12);color:var(--bad)}
.pill{font-size:11px;color:var(--muted)}
pre{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.5;background:var(--bg);
border:1px solid var(--line);border-radius:7px;padding:8px 10px;overflow-x:auto;margin:0;
white-space:pre-wrap;word-break:break-word}
.meta{font-size:11.5px;color:var(--muted);margin:7px 0}
.err{color:var(--bad);font-size:12px;margin-top:6px}
table.rows{border-collapse:collapse;font-size:11.5px;margin-top:6px;width:100%}
table.rows td{border-bottom:1px solid var(--grid);padding:3px 10px 3px 0}
.bar{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 92%,transparent);
backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:16px}
select{font:inherit;font-size:13px;padding:6px 11px;border-radius:8px;border:1px solid var(--line);
background:var(--card);color:var(--ink)}
</style></head><body><div class="wrap">
<h1>PAUQ: русский вопрос против английского</h1>
"""]
    P.append(f"""<p class="sub">{n} параллельных пар из тестового сплита PAUQ — русской адаптации
Spider. Взяты только пары с <b>дословно одинаковым гольд-SQL</b>: тогда разница
объясняется языком вопроса, а не переведёнными литералами. Базы — из PAUQ
(в них дописаны русские значения), а не оригинальные Spider.</p>

<div class="stats">
<div class="stat ru"><div class="v">{ru_ok/max(1,n)*100:.0f}%</div><div class="l">EX по-русски ({ru_ok}/{n})</div></div>
<div class="stat en"><div class="v">{en_ok/max(1,n)*100:.0f}%</div><div class="l">EX по-английски ({en_ok}/{n})</div></div>
<div class="stat"><div class="v">{(en_ok-ru_ok)/max(1,n)*100:+.0f}</div><div class="l">разрыв, п.п.</div></div>
<div class="stat"><div class="v">{both}</div><div class="l">верно на обоих языках</div></div>
<div class="stat"><div class="v">{only_en}</div><div class="l">только по-английски</div></div>
<div class="stat"><div class="v">{only_ru}</div><div class="l">только по-русски</div></div>
</div>

<div class="bar"><select id="f">
<option value="*">все пары</option>
<option value="diff">только расхождения ru/en</option>
<option value="ruko">русский не справился</option>
<option value="both">оба не справились</option>
</select></div>
<h2>Пары</h2>""")

    for i, r in enumerate(records, 1):
        ru_ok_i, en_ok_i = r["ru"].get("exec_match"), r["en"].get("exec_match")
        state = ("both" if not ru_ok_i and not en_ok_i
                 else "diff" if ru_ok_i != en_ok_i else "ok")
        extra = " ruko" if not ru_ok_i else ""
        P.append(f"""<div class="card" data-state="{state}{extra}">
  <p class="q">{i}. {esc(r["question_ru"])}</p>
  <div class="qen">{esc(r["question_en"])}</div>
  <div class="gold">база <b>{esc(r["db_id"])}</b> · эталон: <code>{esc(r["gold_sql"][:150])}</code></div>
  <div class="pair">{side("ru","Русский",r["ru"],r["gold_sql"])}{side("en","Английский",r["en"],r["gold_sql"])}</div>
</div>""")

    P.append("""</div><script>
document.getElementById("f").addEventListener("change", function(e){
  var v = e.target.value;
  document.querySelectorAll(".card").forEach(function(c){
    var s = c.dataset.state || "";
    c.style.display = (v === "*" || s.indexOf(v) >= 0) ? "" : "none";
  });
});
</script></body></html>""")
    return "".join(P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("-o", "--out", default="PAUQ_РАЗБОР.html")
    a = ap.parse_args()
    recs = json.loads(Path(a.results).read_text(encoding="utf-8"))
    Path(a.out).write_text(build(recs), encoding="utf-8")
    print(f"{a.out}: {len(recs)} пар")


if __name__ == "__main__":
    main()
