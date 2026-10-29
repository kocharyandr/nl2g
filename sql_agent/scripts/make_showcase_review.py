"""HTML с примерами для презентации: вопрос → график нужного типа → правка → результат.
Страница лежит в папке прогона, картинки — относительными путями; перезагружается раз в 30 с.

    .venv/bin/python scripts/make_showcase_review.py ПРИМЕРЫ_ДЛЯ_ПРЕЗЕНТАЦИИ [--loop]
"""
import html, json, sys, time
from pathlib import Path

TYPE_RU = {"line": "линия", "area": "область", "pie": "круговая", "doughnut": "кольцевая", "histogram": "гистограмма"}
LEVEL_RU = {1: "уровень 1 · цвет", 2: "уровень 2 · форма", 3: "уровень 3 · реализм"}
CSS = """:root{--bg:#f7f7f5;--card:#fff;--ink:#111;--ink2:#555;--mut:#888;--line:rgba(0,0,0,.1);--blue:#2a78d6;--ok:#0c8a3e;--bad:#c8332d}
@media(prefers-color-scheme:dark){:root{--bg:#111;--card:#1b1b1a;--ink:#f2f2f2;--ink2:#c4c3bb;--mut:#999;--line:rgba(255,255,255,.12);--blue:#4b93ea;--ok:#3ccf74;--bad:#ff7a73}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}
.wrap{max-width:1300px;margin:0 auto;padding:26px 16px 80px}h1{font-size:26px;margin:0 0 6px}p.s{color:var(--ink2)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-top:16px}
.hd{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:12.5px;margin-bottom:8px}.b{padding:2px 9px;border-radius:20px;background:rgba(42,120,214,.10);color:var(--blue)}
.b.ok{background:rgba(12,138,62,.12);color:var(--ok)}.b.bad{background:rgba(200,51,45,.12);color:var(--bad)}
.q{display:inline-block;background:#2a78d6;color:#fff;border-radius:16px;padding:7px 14px;font-size:14.5px;margin-bottom:10px}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:800px){.ab{grid-template-columns:1fr}}
.v .t{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-bottom:6px}
.v img{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;display:block}
.wait{height:100%;min-height:200px;border:1px dashed var(--line);border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--mut)}
.edit{margin:10px 0 4px;font-size:14px}.muted{font-size:12.5px;color:var(--mut)}
details{margin-top:6px;font-size:12.5px}summary{cursor:pointer;color:var(--blue)}pre{font:11.5px/1.45 ui-monospace,Menlo,monospace;background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:7px 9px;white-space:pre-wrap}"""


def build(out: Path) -> None:
    p = out / "showcase.json"
    runs = json.load(open(p, encoding="utf-8")) if p.exists() else []
    jp = out / "judge.json"
    judge = json.load(open(jp, encoding="utf-8")) if jp.exists() else {}
    log = (out / "run.log").read_text(encoding="utf-8", errors="replace").splitlines() if (out / "run.log").exists() else []
    phase = ([l for l in log if l.startswith("===")] or ["=== ожидание"])[-1][4:]
    cards = []
    for r in sorted(runs, key=lambda x: x["id"][-2:]):
        v = judge.get(r["id"])
        badges = f'<span class=b>{esc(r.get("db_id"))}</span><span class=b>{TYPE_RU.get(r.get("target_type"), r.get("target_type"))}</span>'
        badges += f'<span class=b>{LEVEL_RU.get(r.get("level"), "")} · {esc(r.get("edit_code"))}</span>'
        if r.get("chart_ex"):
            badges += f'<span class="b {"ok" if r["chart_ex"].get("ok") else "bad"}">данные графика {"✓" if r["chart_ex"].get("ok") else "✗"}</span>'
        if v:
            badges += "".join(f'<span class="b {"ok" if v[k] else "bad"}">{k}={v[k]}</span>' for k in ("A", "P", "AP"))
        before = f'<img src="{r["typed_png"]}">' if r.get("typed_png") else f'<div class=wait>{esc(r.get("message") or "график не построен")}</div>'
        if r.get("edit_png"):
            after = f'<img src="{r["edit_png"]}">'
        elif r.get("edit_status") == "error":
            after = f'<div class=wait>правка не выполнена: {esc(r.get("edit_message") or r.get("error"))}</div>'
        else:
            after = '<div class=wait>правка ещё не выполнена</div>'
        meta = f'график {r.get("t_chart", "?")} с + смена типа {r.get("t_type", 0)} с' + (f' · правка {r["t_edit"]} с' if r.get("t_edit") else "")
        extra = f'<details><summary>SQL</summary><pre>{esc(r.get("pred_sql"))}</pre></details>'
        if r.get("enhanced_prompt"):
            extra += f'<details><summary>промпт для FLUX (составлен LLM)</summary><pre>{esc(r["enhanced_prompt"])}</pre></details>'
        cards.append(f'<section class=card><div class=hd>{badges}</div><div class=q>{esc(r.get("question"))}</div>'
                     f'<div class=ab><div class=v><div class=t>график · {TYPE_RU.get(r.get("target_type"), "")}</div>{before}</div>'
                     f'<div class=v><div class=t>после правки</div>{after}</div></div>'
                     f'<div class=edit>✎ «{esc(r.get("edit"))}»</div><div class=muted>{meta}</div>{extra}</section>')
    done = sum(1 for r in runs if r.get("edit_status") == "ok")
    doc = (f'<!DOCTYPE html><html lang=ru><head><meta charset=utf-8><meta http-equiv=refresh content=30><meta name=viewport content="width=device-width,initial-scale=1">'
           f'<title>Примеры для презентации</title><style>{CSS}</style></head><body><div class=wrap><h1>Примеры: вопрос → график → правка</h1>'
           f'<p class=s>Графиков {sum(1 for r in runs if r.get("typed_png"))} из 15 · правок {done} · текущая фаза: {esc(phase)} · обновлено {time.strftime("%H:%M:%S")}</p>'
           + "".join(cards) + "</div></body></html>")
    (out / "ПРИМЕРЫ.html").write_text(doc, encoding="utf-8")


def esc(s):
    return html.escape(str(s if s is not None else ""))


if __name__ == "__main__":
    out = Path(sys.argv[1])
    while True:
        build(out)
        if "--loop" not in sys.argv:
            break
        time.sleep(30)
