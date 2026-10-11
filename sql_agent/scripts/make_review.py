#!/usr/bin/env python3
"""Build a single self-contained review page from benchmark_results.json.

The page is for judging runs by hand: every question shows where each part of
the answer came from, and carries two verdicts the reviewer sets — accuracy
and template conformance. Marks live in localStorage and export to CSV/JSON.

    scripts/make_review.py benchmark_results.json -o review.html
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

TEMPLATE_HEAD = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Разбор прогона NL2SQL</title>
<style>
:root {
  color-scheme: light;
  --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --line:rgba(11,11,11,.10);
  --mine:#2a78d6; --his:#eb6834; --base:#898781;
  --ok:#0ca30c; --bad:#d03b3b; --warn:#fab219;
  --wash:rgba(42,120,214,.08); --wash-bad:rgba(208,59,59,.08);
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  color-scheme: dark;
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --line:rgba(255,255,255,.10);
  --mine:#3987e5; --his:#d95926;
  --wash:rgba(57,135,229,.12); --wash-bad:rgba(208,59,59,.14);
}}
:root[data-theme="dark"]{
  color-scheme: dark;
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --line:rgba(255,255,255,.10);
  --mine:#3987e5; --his:#d95926;
  --wash:rgba(57,135,229,.12); --wash-bad:rgba(208,59,59,.14);
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:15px;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:28px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:19px;margin:34px 0 12px;letter-spacing:-.01em}
.sub{color:var(--ink2);margin:0 0 22px;max-width:80ch}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
code{background:var(--wash);padding:1px 5px;border-radius:4px;font-size:.88em}
pre{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:10px 12px;overflow-x:auto;font-size:12.5px;line-height:1.5;margin:0;white-space:pre-wrap;word-break:break-word}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;letter-spacing:.04em}
.tag.mine{background:var(--wash);color:var(--mine)}
.tag.his{background:rgba(235,104,52,.10);color:var(--his)}
.tag.base{background:rgba(137,135,129,.14);color:var(--muted)}
.stats{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-bottom:8px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stat .v{font-size:30px;line-height:1;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat .l{font-size:12px;color:var(--ink2);margin-top:6px}
.bar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--plane) 92%,transparent);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:18px;
  display:flex;gap:10px;flex-wrap:wrap;align-items:center}
select,button{font:inherit;font-size:13px;padding:6px 11px;border-radius:8px;
  border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer}
button:hover{border-color:var(--mine)}
button.primary{background:var(--mine);color:#fff;border-color:var(--mine)}
.q{font-size:16px;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}
.meta{font-size:12.5px;color:var(--muted);margin-bottom:12px;display:flex;gap:14px;flex-wrap:wrap}
.meta b{color:var(--ink2);font-weight:600}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:860px){.cols{grid-template-columns:1fr}}
.lbl{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:5px}
.verdicts{display:flex;gap:22px;flex-wrap:wrap;margin-top:14px;padding-top:14px;border-top:1px solid var(--grid)}
.vgroup{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.vgroup .name{font-size:12.5px;color:var(--ink2);margin-right:2px}
.opt{border:1px solid var(--line);background:var(--surface);border-radius:20px;padding:4px 13px;font-size:13px}
.opt[aria-pressed="true"].yes{background:var(--ok);border-color:var(--ok);color:#fff}
.opt[aria-pressed="true"].no{background:var(--bad);border-color:var(--bad);color:#fff}
.note{width:100%;margin-top:10px;font:inherit;font-size:13px;padding:7px 10px;border-radius:8px;
  border:1px solid var(--line);background:var(--plane);color:var(--ink);resize:vertical;min-height:34px}
.auto{font-size:12px;padding:2px 8px;border-radius:20px}
.auto.y{background:rgba(12,163,12,.14);color:var(--ok)}
.auto.n{background:var(--wash-bad);color:var(--bad)}
.rows{font-size:12px;max-height:180px;overflow:auto}
.rows td,.rows th{padding:4px 8px;font-size:12px}
details summary{cursor:pointer;color:var(--mine);font-size:13px}
.pill{font-size:11.5px;color:var(--muted)}
.err{color:var(--bad);font-size:13px}
.hint{font-size:12.5px;color:var(--muted);margin-top:6px}
</style>
</head>
<body>
<div class="wrap">
"""

TEMPLATE_TAIL = """
</div>
<script>
const KEY = "nl2sql-review-v1";
let marks = {};
try { marks = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { marks = {}; }

function save(){ try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch(e){} render(); }

function setMark(id, field, value){
  marks[id] = marks[id] || {};
  marks[id][field] = marks[id][field] === value ? null : value;
  save();
}
function setNote(id, text){
  marks[id] = marks[id] || {};
  marks[id].note = text;
  try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch(e){}
}

function render(){
  let acc = 0, accNo = 0, tpl = 0, tplNo = 0, done = 0;
  DATA.forEach(function(item){
    const m = marks[item.id] || {};
    if (m.accuracy === "yes") acc++;
    if (m.accuracy === "no") accNo++;
    if (m.template === "yes") tpl++;
    if (m.template === "no") tplNo++;
    if (m.accuracy && m.template) done++;

    document.querySelectorAll('[data-id="'+item.id+'"] .opt').forEach(function(btn){
      btn.setAttribute("aria-pressed", String(m[btn.dataset.field] === btn.dataset.value));
    });
    const note = document.querySelector('[data-id="'+item.id+'"] .note');
    if (note && document.activeElement !== note) note.value = m.note || "";
  });

  document.getElementById("s-acc").textContent = acc;
  document.getElementById("s-accno").textContent = accNo;
  document.getElementById("s-tpl").textContent = tpl;
  document.getElementById("s-tplno").textContent = tplNo;
  document.getElementById("s-done").textContent = done + " / " + DATA.length;
  const judged = acc + accNo;
  document.getElementById("s-ex").textContent =
    judged ? (acc / judged * 100).toFixed(1) + "%" : "—";
  applyFilter();
}

function applyFilter(){
  const db = document.getElementById("f-db").value;
  const st = document.getElementById("f-state").value;
  DATA.forEach(function(item){
    const el = document.querySelector('[data-id="'+item.id+'"]');
    if (!el) return;
    const m = marks[item.id] || {};
    let ok = (db === "*" || item.db === db);
    if (ok && st === "unjudged") ok = !(m.accuracy && m.template);
    if (ok && st === "judged")   ok = !!(m.accuracy && m.template);
    if (ok && st === "disagree") ok = m.accuracy && (m.accuracy === "yes") !== item.auto;
    if (ok && st === "autofail") ok = !item.auto;
    el.style.display = ok ? "" : "none";
  });
}

function download(name, text, mime){
  const blob = new Blob([text], {type: mime});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportCsv(){
  const head = ["id","db","question","gold_sql","pred_sql","auto_exec_match",
                "accuracy","template","note","critic_attempts","elapsed_sec"];
  const esc = function(v){ return '"' + String(v === null || v === undefined ? "" : v).replace(/"/g,'""') + '"'; };
  const lines = [head.join(",")];
  DATA.forEach(function(i){
    const m = marks[i.id] || {};
    lines.push([i.id,i.db,i.question,i.gold_sql,i.pred_sql,i.auto,
                m.accuracy||"",m.template||"",m.note||"",i.attempts,i.elapsed].map(esc).join(","));
  });
  download("nl2sql-review.csv", "\\uFEFF" + lines.join("\\n"), "text/csv;charset=utf-8");
}

function exportJson(){
  const out = DATA.map(function(i){
    const m = marks[i.id] || {};
    return Object.assign({}, i, {accuracy: m.accuracy||null, template: m.template||null, note: m.note||""});
  });
  download("nl2sql-review.json", JSON.stringify(out, null, 2), "application/json");
}

function resetMarks(){
  if (!confirm("Стереть все проставленные оценки?")) return;
  marks = {}; save();
}

document.addEventListener("click", function(e){
  const btn = e.target.closest(".opt");
  if (btn) setMark(btn.closest("[data-id]").dataset.id, btn.dataset.field, btn.dataset.value);
});
document.addEventListener("input", function(e){
  if (e.target.classList.contains("note"))
    setNote(e.target.closest("[data-id]").dataset.id, e.target.value);
});
document.getElementById("f-db").addEventListener("change", applyFilter);
document.getElementById("f-state").addEventListener("change", applyFilter);
document.getElementById("b-csv").addEventListener("click", exportCsv);
document.getElementById("b-json").addEventListener("click", exportJson);
document.getElementById("b-reset").addEventListener("click", resetMarks);
document.getElementById("b-theme").addEventListener("click", function(){
  const root = document.documentElement;
  const dark = root.getAttribute("data-theme") === "dark" ||
    (!root.hasAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  root.setAttribute("data-theme", dark ? "light" : "dark");
});

render();
</script>
</body>
</html>
"""


def plural(n: int, one: str, few: str, many: str) -> str:
    """Russian numeral agreement: 1 вопрос, 2 вопроса, 5 вопросов."""
    if 11 <= n % 100 <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def rows_table(columns: list[str], rows: list[list]) -> str:
    if not rows:
        return '<div class="pill">— пусто —</div>'
    # Gold rows come straight from SQLite and carry no column names.
    labels = columns or [f"кол. {i + 1}" for i in range(len(rows[0]))]
    head = "".join(f"<th>{esc(c)}</th>" for c in labels)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in rows[:12]
    )
    more = f'<div class="pill">…показано {min(12,len(rows))} из {len(rows)}</div>' if len(rows) > 12 else ""
    return f'<div class="rows"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{more}'


def build(records: list[dict]) -> str:
    databases = sorted({r["db_id"] for r in records})
    auto_ok = sum(1 for r in records if r.get("auto_exec_match"))

    parts = [TEMPLATE_HEAD]
    parts.append(f"""
<h1>Разбор прогона NL2SQL</h1>
<p class="sub">Прогон через сервис: {len(records)} {plural(len(records), "гольд-вопрос", "гольд-вопроса", "гольд-вопросов")}
из тестовой выборки KaggleDBQA. Для каждого видно, что и какой моделью сделано, и проставляются две оценки:
<b>точность</b> (правильный ли ответ) и <b>шаблон</b> (совпадает ли структура запроса
с эталонной). Оценки сохраняются в браузере и выгружаются в CSV или JSON.</p>

<div class="stats">
  <div class="stat"><div class="v" id="s-ex">—</div><div class="l">точность по вашим оценкам</div></div>
  <div class="stat"><div class="v" id="s-acc">0</div><div class="l">отмечено «верно»</div></div>
  <div class="stat"><div class="v" id="s-accno">0</div><div class="l">отмечено «неверно»</div></div>
  <div class="stat"><div class="v" id="s-tpl">0</div><div class="l">шаблон совпал</div></div>
  <div class="stat"><div class="v" id="s-tplno">0</div><div class="l">шаблон не совпал</div></div>
  <div class="stat"><div class="v" id="s-done">0</div><div class="l">размечено полностью</div></div>
</div>
<p class="hint">Автоматическая оценка (сравнение результатов с эталоном, как в дипломе):
<b>{auto_ok} из {len(records)} = {auto_ok/max(1,len(records))*100:.1f}%</b>. Она проставлена как
подсказка на каждой карточке, но ни на что не влияет — итог считается по вашим отметкам.</p>

<h2>Что откуда</h2>
<div class="card">
<table>
<thead><tr><th>Этап</th><th>Кто выполняет</th><th>Модель</th><th>Происхождение</th></tr></thead>
<tbody>
<tr><td>Выбор таблиц (сужение схемы)</td><td>Агент-схемотехник</td><td><code>nl2sql-schema</code> = Qwen2.5-Coder-14B + <code>schema_adapter</code></td><td><span class="tag mine">твой диплом · LoRA на Spider</span></td></tr>
<tr><td><b>Генерация SQL</b></td><td>Агент-программист</td><td><code>nl2sql-sql</code> = Qwen2.5-Coder-14B + <code>sql_adapter</code></td><td><span class="tag mine">твой диплом · LoRA на Spider</span></td></tr>
<tr><td>Починка SQL по ошибке движка</td><td>Агент-критик</td><td><code>nl2sql-critic</code> = Qwen2.5-Coder-14B + <code>critic_adapter</code></td><td><span class="tag mine">твой диплом · LoRA на Spider</span></td></tr>
<tr><td>Описания таблиц и колонок в промпте</td><td>Schema Profiler (заранее)</td><td>LLM-генерация, кэш <code>BD_profiles/*.json</code></td><td><span class="tag mine">твой диплом</span></td></tr>
<tr><td>Исполнение SQL, лимиты, валидация</td><td><code>connector</code> + <code>safety</code></td><td>—</td><td><span class="tag base">детерминированный код</span></td></tr>
<tr><td>pandas-код (подготовка таблицы)</td><td>агент <code>data_understanding</code></td><td><code>qwen2.5-coder:14b</code>, <b>без адаптеров</b></td><td><span class="tag base">базовая модель</span></td></tr>
<tr><td>matplotlib-код (рисование)</td><td>агент <code>plot_planner</code></td><td><code>qwen2.5-coder:14b</code>, <b>без адаптеров</b></td><td><span class="tag base">базовая модель</span></td></tr>
<tr><td>Архитектура графиков, изоляция кода</td><td><code>chart_agent</code>, <code>code_executor</code></td><td>—</td><td><span class="tag his">диплом Матвея</span></td></tr>
<tr><td>Визуальное улучшение графика</td><td><code>diffusion_service</code></td><td>FLUX.2 [Klein] 9B + LoRA rank 16</td><td><span class="tag his">диплом Матвея · выключено</span></td></tr>
</tbody>
</table>
<p class="hint">В этом прогоне участвовали только первые пять строк: вопросы шли прямо в
<code>sql_agent</code>, без построения графиков.</p>
</div>

<h2>Вопросы</h2>
<div class="bar">
  <select id="f-db"><option value="*">все базы</option>{"".join(f'<option value="{esc(d)}">{esc(d)}</option>' for d in databases)}</select>
  <select id="f-state">
    <option value="*">все</option>
    <option value="unjudged">не размечено</option>
    <option value="judged">размечено</option>
    <option value="disagree">расхожусь с авто-оценкой</option>
    <option value="autofail">авто-оценка «не совпало»</option>
  </select>
  <button id="b-csv" class="primary">Выгрузить CSV</button>
  <button id="b-json">JSON</button>
  <button id="b-reset">Сбросить</button>
  <button id="b-theme">Тема</button>
</div>
""")

    for index, record in enumerate(records, 1):
        rid = f"q{index}"
        auto = bool(record.get("auto_exec_match"))
        auto_badge = (
            '<span class="auto y">авто: совпало с эталоном</span>' if auto
            else '<span class="auto n">авто: не совпало</span>'
        )
        status = record.get("status")
        problem = ""
        if status != "ok":
            problem = f'<div class="err">Сервис вернул <b>{esc(status)}</b>: {esc(record.get("message"))}</div>'
        elif record.get("pred_exec_error"):
            problem = f'<div class="err">SQL не выполнился: {esc(record["pred_exec_error"])}</div>'

        parts.append(f"""
<div class="card" data-id="{rid}">
  <p class="q">{index}. {esc(record["question"])}</p>
  <div class="meta">
    <span><b>база</b> {esc(record["db_id"])}</span>
    <span><b>таблицы</b> {esc(", ".join(record.get("selected_tables") or []) or "—")}</span>
    <span><b>попыток критика</b> {esc(record.get("critic_attempts"))}</span>
    <span><b>профиль</b> {"да" if record.get("profile_used") else "нет"}</span>
    <span><b>{esc(record.get("elapsed_sec"))}с</b></span>
    {auto_badge}
  </div>
  {problem}
  <div class="cols">
    <div>
      <div class="lbl">SQL от модели · nl2sql-sql</div>
      <pre>{esc(record.get("pred_sql") or "—")}</pre>
    </div>
    <div>
      <div class="lbl">Эталонный SQL из выборки</div>
      <pre>{esc(record.get("gold_sql") or "—")}</pre>
    </div>
  </div>
  <div class="cols" style="margin-top:12px">
    <div>
      <div class="lbl">Результат модели · строк: {esc(record.get("pred_row_count"))}</div>
      {rows_table(record.get("columns") or [], record.get("pred_rows") or [])}
    </div>
    <div>
      <div class="lbl">Результат эталона</div>
      {rows_table([], record.get("gold_rows") or [])}
    </div>
  </div>
  <div class="verdicts">
    <div class="vgroup">
      <span class="name">Точность:</span>
      <button class="opt yes" data-field="accuracy" data-value="yes" aria-pressed="false">верно</button>
      <button class="opt no"  data-field="accuracy" data-value="no"  aria-pressed="false">неверно</button>
    </div>
    <div class="vgroup">
      <span class="name">Шаблон запроса:</span>
      <button class="opt yes" data-field="template" data-value="yes" aria-pressed="false">соответствует</button>
      <button class="opt no"  data-field="template" data-value="no"  aria-pressed="false">не соответствует</button>
    </div>
  </div>
  <textarea class="note" placeholder="Замечание (необязательно)"></textarea>
</div>""")

    payload = [
        {
            "id": f"q{i}",
            "db": r["db_id"],
            "question": r["question"],
            "gold_sql": r.get("gold_sql", ""),
            "pred_sql": r.get("pred_sql", ""),
            "auto": bool(r.get("auto_exec_match")),
            "attempts": r.get("critic_attempts"),
            "elapsed": r.get("elapsed_sec"),
        }
        for i, r in enumerate(records, 1)
    ]
    parts.append(f"<script>const DATA = {json.dumps(payload, ensure_ascii=False)};</script>")
    parts.append(TEMPLATE_TAIL)
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", help="benchmark_results.json")
    parser.add_argument("-o", "--out", default="review.html")
    args = parser.parse_args()

    records = json.loads(Path(args.results).read_text(encoding="utf-8"))
    Path(args.out).write_text(build(records), encoding="utf-8")
    print(f"{args.out}: {len(records)} вопросов")


if __name__ == "__main__":
    main()
