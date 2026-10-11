"""Страница прогресса замеров: раз в 30 с собирает МТС_ПРАВКИ/ПРОГРЕСС.html (сама обновляется в браузере)
и печатает ту же сводку в терминал при --once.

    .venv/bin/python scripts/progress.py          # фоновый цикл
    .venv/bin/python scripts/progress.py --once   # разово в терминал
"""
from __future__ import annotations

import base64
import html
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "МТС_ПРАВКИ"
LOGS = OUT / "logs"
SERVICES = [("ollama", 11434, "/api/tags"), ("sql_agent", 8500, "/health"), ("chart_agent", 8010, "/docs"),
            ("executor", 8080, "/docs"), ("diffusion", 8001, "/health"), ("redis", 6379, None)]


def up(port: int, path: str | None) -> bool:
    if path is None:
        return subprocess.run(["redis-cli", "-p", str(port), "ping"], capture_output=True, text=True).stdout.strip() == "PONG"
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=20)
        return True
    except Exception:  # noqa: BLE001
        return False


def tail(name: str, n: int = 6) -> str:
    p = LOGS / f"{name}.log"
    if not p.exists():
        return "(нет лога)"
    lines = p.read_text(encoding="utf-8", errors="replace").replace("\r", "\n").splitlines()
    lines = [l for l in lines if l.strip()]
    return "\n".join(l[:160] for l in lines[-n:])


def vl_status() -> str:
    lst = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
    if "qwen2.5vl" in lst:
        return "скачана ✓"
    t = tail("pull_vl", 1)
    return t.split("pulling")[-1].strip()[:60] if "pulling" in t else t[-80:]


def collect() -> dict:
    recs = json.load(open(OUT / "mts_edits.json", encoding="utf-8")) if (OUT / "mts_edits.json").exists() else []
    jp = OUT / "mts_judge.json"
    judge = json.load(open(jp, encoding="utf-8")) if jp.exists() else {}
    return {
        "time": time.strftime("%H:%M:%S"),
        "services": {n: up(p, path) for n, p, path in SERVICES},
        "recs": recs, "judge": judge, "vl": vl_status(),
        "pauq": (ROOT / "pauq_stats_100.json").exists(),
    }


def text_report(d: dict) -> str:
    s = [f"[{d['time']}] сервисы: " + "  ".join(f"{k} {'✓' if v else '✗'}" for k, v in d["services"].items())]
    s.append(f"PAUQ 100 пар: {'готово (pauq_stats_100.json, PAUQ_РАЗБОР_100.html)' if d['pauq'] else 'нет'}")
    s.append(f"VL-судья qwen2.5vl:7b: {d['vl']}")
    charts = sum(1 for r in d["recs"] if r.get("before_png"))
    edits = sum(1 for r in d["recs"] if r["status"] == "ok")
    s.append(f"МТС-правки: графиков {charts}/10, картинок после правки {edits}/10, оценено судьёй {len(d['judge'])}/10")
    for r in d["recs"]:
        v = d["judge"].get(str(r["n"]))
        mark = {"ok": "✓ правка", "chart_ok": "· график, ждёт правку", "error": "✗ " + (r.get("error") or "")[:70]}[r["status"]]
        jd = f"  судья A={v['A']} P={v['P']} AP={v['AP']}" if v else ""
        s.append(f"  {r['n']:2d} ур.{r['level']} {mark}{jd}")
    s.append("— хвост лога правок —\n" + tail("mts_edit"))
    return "\n".join(s)


def thumb(path: Path) -> str:
    if not path.exists():
        return ""
    return f'<img src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}">'


def html_report(d: dict) -> str:
    rows = []
    for r in d["recs"]:
        v = d["judge"].get(str(r["n"]))
        st = {"ok": "✓ правка готова", "chart_ok": "график построен, правка в очереди", "error": "✗ " + (r.get("error") or "")}[r["status"]]
        jd = f"A={v['A']} P={v['P']} AP={v['AP']}" if v else "—"
        rows.append(f"<tr><td>{r['n']}</td><td>ур.{r['level']}</td><td>{html.escape(r['q'][:60])}</td><td>{html.escape(st)}</td>"
                    f"<td>{r.get('t_chart','')}/{r.get('t_edit','')} с</td><td>{jd}</td>"
                    f"<td class=i>{thumb(OUT / (r.get('before_png') or 'x'))}</td><td class=i>{thumb(OUT / (r.get('after_png') or 'x'))}</td></tr>")
    svc = " ".join(f'<span class="{"ok" if v else "bad"}">{k}</span>' for k, v in d["services"].items())
    logs = "".join(f"<h3>{n}</h3><pre>{html.escape(tail(n, 8))}</pre>" for n in ("mts_edit", "diffusion", "pull_vl"))
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta http-equiv="refresh" content="30">
<title>Прогресс замеров</title><style>body{{font-family:system-ui;margin:24px;color:#0b0b0b;background:#f9f9f7}}
.ok{{color:#0c8a3e}}.bad{{color:#c8332d}}span{{margin-right:10px}}table{{border-collapse:collapse;font-size:13px}}
td,th{{border:1px solid #ddd;padding:4px 8px;vertical-align:top}}td.i img{{width:180px;display:block}}
pre{{background:#fff;border:1px solid #ddd;padding:8px;font-size:11px;white-space:pre-wrap}}h3{{margin:14px 0 4px;font-size:13px}}</style></head>
<body><h1>Прогресс замеров <small style="font-weight:400;color:#777">обновлено {d['time']}, страница перезагружается сама</small></h1>
<p>Сервисы: {svc}</p><p>PAUQ 100 пар: <b>{'готово' if d['pauq'] else 'нет'}</b> · VL-судья: <b>{html.escape(d['vl'])}</b></p>
<table><tr><th>#</th><th>ур.</th><th>вопрос</th><th>статус</th><th>график/правка</th><th>судья</th><th>до</th><th>после</th></tr>{''.join(rows)}</table>
{logs}</body></html>"""


PAUQ_RUN = ROOT / "PAUQ_ГРАФИКИ_ПРОГОН"


def pauq_page(svc: dict) -> None:
    """Страница прогресса прогона PAUQ → график → стиль МТС (картинки — ссылками, страница лёгкая)."""
    runs_p = PAUQ_RUN / "runs.json"
    runs = json.load(open(runs_p, encoding="utf-8")) if runs_p.exists() else []
    total = len(json.load(open(PAUQ_RUN / "selection.json"))) if (PAUQ_RUN / "selection.json").exists() else 100
    n = len(runs)
    cnt = lambda f: sum(1 for r in runs if f(r))
    charts = cnt(lambda r: r.get("outcome") == "chart")
    jp = PAUQ_RUN / "judge.json"
    judge = json.load(open(jp, encoding="utf-8")) if jp.exists() else {}
    edited = cnt(lambda r: r.get("edit_status") == "ok")
    log_all = (PAUQ_RUN / "run.log").read_text(encoding="utf-8", errors="replace") if (PAUQ_RUN / "run.log").exists() else ""
    phase = ([l for l in log_all.splitlines() if l.startswith("===")] or ["=== ожидание"])[-1][4:]
    jv = list(judge.values())
    stats = [(f"{n}/{total}", "график: обработано"), (charts, "графиков построено"),
             (cnt(lambda r: r.get("outcome") in {"no_chart", "clarification", "transport_error", "text_answer"}), "без графика"),
             (cnt(lambda r: r.get("sql_ex")), "SQL-EX ✓"), (cnt(lambda r: r.get("chart_ex", {}).get("ok")), "Chart-EX ✓"),
             (f"{edited}/{charts}", "правок диффузией"), (f"{len(judge)}/{edited}", "оценено судьёй"),
             (sum(v["AP"] for v in jv), "AP = 1")]
    tiles = "".join(f"<div class=st><b>{v}</b><span>{l}</span></div>" for v, l in stats)
    mk = lambda b: "✓" if b else ("✗" if b is not None else "")
    rows = "".join(
        f"<tr><td>{i}</td><td>{html.escape(r['db_id'])}</td><td>{html.escape(r['question'])}</td>"
        f"<td>{r.get('outcome')}</td><td>{mk(r.get('sql_ex'))}</td><td>{mk(r.get('chart_ex', {}).get('ok'))}</td>"
        f"<td>ур.{r.get('level', '')} {html.escape(r.get('edit_code', ''))}</td><td>{r.get('edit_status', '')}</td>"
        f"<td>{'A=%d P=%d AP=%d' % (judge[r['id']]['A'], judge[r['id']]['P'], judge[r['id']]['AP']) if r['id'] in judge else ''}</td>"
        f"<td>{r.get('t_chart', '')}+{r.get('t_edit', '')} с</td>"
        f"<td class=i>{'<img src=\"' + r['chart_png'] + '\">' if r.get('chart_png') else ''}</td>"
        f"<td class=i>{'<img src=\"' + r['edit_png'] + '\">' if r.get('edit_png') else ''}</td></tr>"
        for i, r in reversed(list(enumerate(runs, 1))))
    eta = f"текущая фаза: {html.escape(phase)}"
    svc_html = " ".join(f'<span class="{"ok" if v else "bad"}">{k}</span>' for k, v in svc.items())
    log = html.escape("\n".join(log_all.splitlines()[-8:]))
    (PAUQ_RUN / "ПРОГРЕСС.html").write_text(f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta http-equiv="refresh" content="30">
<title>Прогресс: PAUQ → графики</title><style>body{{font-family:system-ui;margin:24px;background:#f9f9f7;color:#0b0b0b}}
.ok{{color:#0c8a3e}}.bad{{color:#c8332d}}span{{margin-right:8px}}.sts{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
.st{{background:#fff;border:1px solid #ddd;border-radius:10px;padding:8px 14px}}.st b{{font-size:22px;display:block}}.st span{{font-size:12px;color:#666}}
table{{border-collapse:collapse;font-size:13px;background:#fff}}td,th{{border:1px solid #ddd;padding:4px 7px;vertical-align:top}}td.i img{{width:170px;display:block}}
pre{{background:#fff;border:1px solid #ddd;padding:8px;font-size:11px;white-space:pre-wrap}}</style></head><body>
<h1>PAUQ → график → правка «в стиле МТС» → судья <small style="font-weight:400;color:#777">{time.strftime('%H:%M:%S')}, обновляется каждые 30 с {eta}</small></h1>
<p>Сервисы: {svc_html}</p><div class=sts>{tiles}</div><pre>{log}</pre>
<table><tr><th>#</th><th>база</th><th>вопрос</th><th>итог</th><th>SQL-EX</th><th>Chart-EX</th><th>промпт</th><th>правка</th><th>судья</th><th>время</th><th>график</th><th>после правки</th></tr>{rows}</table></body></html>""", encoding="utf-8")


def main() -> None:
    once = "--once" in sys.argv
    while True:
        d = collect()
        (OUT / "ПРОГРЕСС.html").write_text(html_report(d), encoding="utf-8")
        if PAUQ_RUN.exists():
            pauq_page(d["services"])
        if once:
            print(text_report(d))
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
