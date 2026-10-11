"""Статистика по прогону PAUQ ru vs en (pauq_results*.json): EX по языкам, парный тест
Макнемара, бутстреп-интервал разрыва, разбивка по конструкциям SQL и по базам.

    .venv/bin/python scripts/pauq_stats.py pauq_results_100.json [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys


def sql_features(sql: str) -> list[str]:
    s = sql.upper()
    feats = []
    if " JOIN " in s:
        feats.append("JOIN")
    if "GROUP BY" in s:
        feats.append("GROUP BY")
    if "ORDER BY" in s:
        feats.append("ORDER BY")
    if re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", s):
        feats.append("агрегат")
    if s.count("SELECT") > 1:
        feats.append("вложенный")
    if " WHERE " in s:
        feats.append("WHERE")
    if not feats:
        feats.append("простой SELECT")
    return feats


def mcnemar_exact(b: int, c: int) -> float:
    """Точный двусторонний тест Макнемара по дискордантным парам (b: ru✓en✗, c: ru✗en✓)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    rows = json.load(open(args.results, encoding="utf-8"))
    n = len(rows)
    ru = [bool(r["ru"].get("exec_match")) for r in rows]
    en = [bool(r["en"].get("exec_match")) for r in rows]
    ru_ok, en_ok = sum(ru), sum(en)
    b = sum(1 for x, y in zip(ru, en) if x and not y)   # только ru верно
    c = sum(1 for x, y in zip(ru, en) if y and not x)   # только en верно
    both = sum(1 for x, y in zip(ru, en) if x and y)
    neither = n - both - b - c
    p_mc = mcnemar_exact(b, c)
    rnd = random.Random(0)
    gaps = []
    for _ in range(5000):
        idx = [rnd.randrange(n) for _ in range(n)]
        gaps.append((sum(en[i] for i in idx) - sum(ru[i] for i in idx)) / n * 100)
    gaps.sort()
    lo, hi = gaps[int(0.025 * len(gaps))], gaps[int(0.975 * len(gaps))]
    same_sql = sum(1 for r in rows if (r["ru"].get("sql") or "").strip() == (r["en"].get("sql") or "").strip())
    ru_err = sum(1 for r in rows if r["ru"].get("status") != "ok")
    en_err = sum(1 for r in rows if r["en"].get("status") != "ok")
    ru_sec = sorted(r["ru"].get("sec") or 0 for r in rows)
    en_sec = sorted(r["en"].get("sec") or 0 for r in rows)
    att = lambda lang: sum((r[lang].get("attempts") or 1) for r in rows) / n

    out = {
        "n": n, "ex_ru": ru_ok, "ex_en": en_ok, "ci_ru": wilson(ru_ok, n), "ci_en": wilson(en_ok, n),
        "both": both, "only_ru": b, "only_en": c, "neither": neither, "mcnemar_p": p_mc,
        "gap_pp": (en_ok - ru_ok) / n * 100, "gap_ci": (lo, hi), "same_sql": same_sql,
        "errors_ru": ru_err, "errors_en": en_err, "median_sec_ru": ru_sec[n // 2], "median_sec_en": en_sec[n // 2],
        "attempts_ru": att("ru"), "attempts_en": att("en"),
    }
    print(f"пар: {n}")
    print(f"EX ru: {ru_ok}/{n} = {ru_ok/n*100:.1f}%  (95% ДИ {out['ci_ru'][0]*100:.0f}–{out['ci_ru'][1]*100:.0f}%)")
    print(f"EX en: {en_ok}/{n} = {en_ok/n*100:.1f}%  (95% ДИ {out['ci_en'][0]*100:.0f}–{out['ci_en'][1]*100:.0f}%)")
    print(f"оба верно {both} · только ru {b} · только en {c} · оба неверно {neither}")
    print(f"разрыв en−ru: {out['gap_pp']:.1f} п.п. (бутстреп 95% ДИ {lo:.1f}…{hi:.1f}), Макнемар p = {p_mc:.3f}")
    print(f"одинаковый SQL ru/en: {same_sql}/{n}; отказов/ошибок сервиса ru {ru_err}, en {en_err}")
    print(f"медиана времени ru {out['median_sec_ru']:.0f} с, en {out['median_sec_en']:.0f} с; попыток критика ru {out['attempts_ru']:.2f}, en {out['attempts_en']:.2f}")

    print("\nпо конструкциям gold-SQL (EX ru / en):")
    feats: dict[str, list] = {}
    for r, x, y in zip(rows, ru, en):
        for f in sql_features(r["gold_sql"]):
            feats.setdefault(f, []).append((x, y))
    out["by_feature"] = {}
    for f, lst in sorted(feats.items(), key=lambda kv: -len(kv[1])):
        m = len(lst)
        out["by_feature"][f] = {"n": m, "ru": sum(x for x, _ in lst), "en": sum(y for _, y in lst)}
        print(f"  {f:<16} n={m:<3} ru {sum(x for x,_ in lst)/m*100:5.1f}%  en {sum(y for _,y in lst)/m*100:5.1f}%")

    print("\nпо базам (EX ru / en):")
    dbs: dict[str, list] = {}
    for r, x, y in zip(rows, ru, en):
        dbs.setdefault(r["db_id"], []).append((x, y))
    out["by_db"] = {}
    for d, lst in sorted(dbs.items(), key=lambda kv: -len(kv[1])):
        m = len(lst)
        out["by_db"][d] = {"n": m, "ru": sum(x for x, _ in lst), "en": sum(y for _, y in lst)}
        print(f"  {d:<24} n={m:<3} ru {sum(x for x,_ in lst)}/{m}  en {sum(y for _,y in lst)}/{m}")

    print("\nтолько на русском неверно:")
    for r, x, y in zip(rows, ru, en):
        if y and not x:
            print(f"  [{r['id']}] {r['db_id']}: {r['question_ru'][:90]}")
            print(f"      ru: {(r['ru'].get('sql') or r['ru'].get('message') or '')[:120]}")
    if args.json:
        json.dump(out, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
