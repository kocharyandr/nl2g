import json
import logging

from app.agents.base_agent import BaseJsonAgent
from app.infra.tracing import get_current_node_name, get_current_trace_id, llm_generation
from app.graph.node_schemas.image_generation_validator import (
    ADHERENCE_CRITERIA,
    PRESERVATION_CRITERIA,
    AdherenceResult,
    CriterionResult,
    FactCheck,
    ImageGenerationValidationResult,
    PreservationResult,
)
from app.prompts.image_generation_validator import (
    build_adherence_messages,
    build_facts_messages,
    build_preservation_messages,
)

logger = logging.getLogger(__name__)


def _to_image_url(b64: str) -> str:
    value = (b64 or "").strip()
    if not value:
        return value
    if value.startswith("data:image/"):
        return value
    return f"data:image/png;base64,{value}"


def _parse_pass(value) -> bool:
    """Accept the verdict as bool or as the strings a local model tends to emit.

    `bool("false")` is True, so a string verdict must be read explicitly; the
    key also drifts between `pass`, `passed` and `verdict` across responses.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "yes", "pass", "passed", "1"}


def _parse_criterion(raw: dict) -> CriterionResult:
    if not isinstance(raw, dict):
        return CriterionResult()
    verdict = next((raw[k] for k in ("pass", "passed", "verdict") if k in raw), None)
    return CriterionResult(
        evidence=str(raw.get("evidence", "")),
        reason=str(raw.get("reason", "")),
        passed=_parse_pass(verdict),
    )


class ImageGenerationValidatorAgent(BaseJsonAgent):
    def __init__(self, llm):
        super().__init__(llm)

    async def run(
        self,
        *,
        source_image_b64: str,
        generated_image_b64: str,
        user_request: str,
        prompt_used: str,
        iteration: int,
        total_iterations: int,
    ) -> ImageGenerationValidationResult:
        source_url = _to_image_url(source_image_b64)
        generated_url = _to_image_url(generated_image_b64)
        edit_prompt = user_request or prompt_used or ""

        trace_id = get_current_trace_id()
        node_name = get_current_node_name() or "image_validator"
        model_name = str(getattr(self.llm, "model", "llm"))

        # Step 1: extract analytical facts from source image
        facts_json = "[]"
        try:
            facts_msgs = build_facts_messages(source_url)
            with llm_generation(
                trace_id=trace_id,
                name=f"{node_name}.facts_extraction",
                model=model_name,
                messages=facts_msgs,
                metadata={"iteration": iteration},
            ) as set_output:
                facts_raw = await self.llm.chat(facts_msgs, temperature=0.0)
                facts_payload = self._load_json_payload(facts_raw)
                facts_list = facts_payload.get("analytical_facts", [])
                facts_json = json.dumps(facts_list, ensure_ascii=False)
                set_output({"facts_count": len(facts_list)})
        except Exception:  # noqa: BLE001
            logger.warning("image_validator: facts extraction failed, continuing with empty facts")

        # Step 2: preservation check (source + generated)
        preservation = PreservationResult()
        try:
            pres_msgs = build_preservation_messages(source_url, generated_url, edit_prompt, facts_json)
            with llm_generation(
                trace_id=trace_id,
                name=f"{node_name}.preservation_check",
                model=model_name,
                messages=pres_msgs,
                metadata={"iteration": iteration},
            ) as set_output:
                pres_raw = await self.llm.chat(pres_msgs, temperature=0.0)
                set_output(pres_raw[:500] if isinstance(pres_raw, str) else pres_raw)
            pres_payload = self._load_json_payload(pres_raw)

            fact_checks = []
            for fc in pres_payload.get("fact_checks", []):
                try:
                    fact_checks.append(FactCheck(
                        id=str(fc.get("id", "")),
                        fact=str(fc.get("fact", "")),
                        importance=str(fc.get("importance", "minor")),
                        status=str(fc.get("status", "uncertain")),
                        reason=str(fc.get("reason", "")),
                    ))
                except Exception:  # noqa: BLE001
                    pass

            preservation = PreservationResult(
                fact_checks=fact_checks,
                **{k: _parse_criterion(pres_payload.get(k, {})) for k in PRESERVATION_CRITERIA},
            )
        except Exception:  # noqa: BLE001
            logger.warning("image_validator: preservation check failed")

        # Step 3: adherence check (source + generated)
        adherence = AdherenceResult()
        try:
            adh_msgs = build_adherence_messages(source_url, generated_url, edit_prompt)
            with llm_generation(
                trace_id=trace_id,
                name=f"{node_name}.adherence_check",
                model=model_name,
                messages=adh_msgs,
                metadata={"iteration": iteration},
            ) as set_output:
                adh_raw = await self.llm.chat(adh_msgs, temperature=0.0)
                set_output(adh_raw[:500] if isinstance(adh_raw, str) else adh_raw)
            adh_payload = self._load_json_payload(adh_raw)
            adherence = AdherenceResult(
                **{k: _parse_criterion(adh_payload.get(k, {})) for k in ADHERENCE_CRITERIA},
            )
        except Exception:  # noqa: BLE001
            logger.warning("image_validator: adherence check failed")

        # Score = fraction of passed criteria across both judges (5 + 5 = 10 total)
        p_passes = sum(1 for k in PRESERVATION_CRITERIA if getattr(preservation, k).passed)
        e_passes = sum(1 for k in ADHERENCE_CRITERIA if getattr(adherence, k).passed)
        score = (p_passes + e_passes) / 10.0

        # Build feedback for next iteration
        failed: list[str] = []
        for k in PRESERVATION_CRITERIA:
            cr = getattr(preservation, k)
            if not cr.passed:
                failed.append(f"{k}: {cr.reason}")
        for k in ADHERENCE_CRITERIA:
            cr = getattr(adherence, k)
            if not cr.passed:
                failed.append(f"{k}: {cr.reason}")

        errors_summary = "; ".join(failed[:4]) if failed else ""

        return ImageGenerationValidationResult(
            preservation=preservation,
            adherence=adherence,
            score=score,
            errors_summary=errors_summary,
            key_issues=failed,
        )
