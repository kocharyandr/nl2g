"""LLM-судья из диплома Матвея (критерии A1-5 = E1-5 и P1-5, агрегаты A / P / AP) для пар
«до/после» из run_mts_edits.py. Модель — Qwen2.5-VL через Ollama (как в дипломе), temperature=0.

Запускать интерпретатором chart_agent (там живёт код судьи):
    ../chart_agent/.venv/bin/python scripts/judge_edits.py МТС_ПРАВКИ
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

CHART_AGENT = Path(__file__).resolve().parents[2] / "chart_agent"
ORIG_CWD = Path.cwd()  # os.chdir ниже нужен для .env оркестратора; пути аргументов считаем от исходной cwd
os.environ.setdefault("OPENAI_API_BASE", "http://127.0.0.1:11434/v1")
os.environ.setdefault("OPENAI_MODEL_NAME", "qwen2.5vl:7b")
os.environ["LANGFUSE_ENABLED"] = "false"
os.environ["LLM_JSON_OUTPUT_ENABLED"] = "false"
sys.path.insert(0, str(CHART_AGENT))
os.chdir(CHART_AGENT)

import httpx  # noqa: E402

from app.agents.image_generation_validator_agent import ImageGenerationValidatorAgent  # noqa: E402
from app.graph.node_schemas.image_generation_validator import (  # noqa: E402
    ADHERENCE_CRITERIA,
    PRESERVATION_CRITERIA,
)


class PatientLLM:
    """Тот же контракт, что у LLMClient.chat, но с таймаутом под VL-модель на Mac."""

    def __init__(self, base_url: str, model: str) -> None:
        self.api_base = base_url.rstrip("/")
        self.model = model

    async def chat(self, messages: list[dict], temperature: float = 0.0, json_schema: dict | None = None) -> str:
        async with httpx.AsyncClient(timeout=900.0) as client:
            r = await client.post(
                f"{self.api_base}/chat/completions",
                json={"model": self.model, "messages": messages, "temperature": temperature,
                      "top_p": 1.0, "max_tokens": 1800, "seed": 0},
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


async def judge_all(records: list[dict], out_dir: Path, llm: PatientLLM, only: set, cfg: argparse.Namespace) -> dict:
    agent = ImageGenerationValidatorAgent(llm)
    verdicts_path = out_dir / cfg.verdicts
    verdicts: dict = json.load(open(verdicts_path, encoding="utf-8")) if verdicts_path.exists() else {}
    todo = [r for r in records if r.get(cfg.status_field) == "ok" and (not only or str(r[cfg.key]) in only)]
    for idx, rec in enumerate(todo, 1):
        n = rec[cfg.key]
        if str(n) in verdicts and not only:
            continue
        t0 = time.time()
        result = await agent.run(
            source_image_b64=b64(out_dir / rec[cfg.before]),
            generated_image_b64=b64(out_dir / rec[cfg.after]),
            user_request=rec["edit_prompt"],
            prompt_used=rec.get("enhanced_prompt") or "",
            iteration=1,
            total_iterations=1,
        )
        d = result.model_dump()
        pres = {k: d["preservation"][k] for k in PRESERVATION_CRITERIA}
        adh = {k: d["adherence"][k] for k in ADHERENCE_CRITERIA}
        a = all(v["passed"] for v in adh.values())
        p = all(v["passed"] for v in pres.values())
        verdicts[str(n)] = {
            "A": int(a), "P": int(p), "AP": int(a and p),
            "adherence": adh, "preservation": pres,
            "fact_checks": d["preservation"].get("fact_checks", []),
            "score": d.get("score"), "secs": round(time.time() - t0),
        }
        flags = "".join("✓" if v["passed"] else "✗" for v in list(adh.values()) + list(pres.values()))
        print(f"[judge {idx}/{len(todo)}] {n} ур.{rec.get('level')} A={int(a)} P={int(p)} AP={int(a and p)}  E1-5,P1-5={flags[:5]}|{flags[5:]}  {round(time.time()-t0)}с",
              file=sys.stderr, flush=True)
        json.dump(verdicts, open(verdicts_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return verdicts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--only", default="")
    ap.add_argument("--model", default=os.environ["OPENAI_MODEL_NAME"])
    ap.add_argument("--file", default="mts_edits.json", help="записи прогона внутри out_dir")
    ap.add_argument("--key", default="n")
    ap.add_argument("--before", default="before_png")
    ap.add_argument("--after", default="after_png")
    ap.add_argument("--status-field", default="status")
    ap.add_argument("--verdicts", default="mts_judge.json")
    args = ap.parse_args()
    out_dir = (ORIG_CWD / args.out_dir).resolve()
    records = json.load(open(out_dir / args.file, encoding="utf-8"))
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    llm = PatientLLM(os.environ["OPENAI_API_BASE"], args.model)
    verdicts = asyncio.run(judge_all(records, out_dir, llm, only, args))
    n = len(verdicts)
    if n:
        for key in ("A", "P", "AP"):
            print(f"{key}: {sum(v[key] for v in verdicts.values())}/{n} = {sum(v[key] for v in verdicts.values())/n*100:.0f}%", file=sys.stderr)


if __name__ == "__main__":
    main()
