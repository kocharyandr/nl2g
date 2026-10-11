from __future__ import annotations

import logging
import re

from app.infra.tracing import get_current_node_name, get_current_trace_id, llm_generation
from app.prompts.chart_coder import chart_coder_messages

logger = logging.getLogger(__name__)

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_code(raw: str) -> str:
    m = _CODE_BLOCK_RE.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


class ChartCoderAgent:
    def __init__(self, llm, structured_llm=None):
        self.llm = llm

    async def run(self, data: dict) -> dict:
        if not isinstance(data, dict) or not data:
            raise ValueError("ChartCoderAgent: input data must be a non-empty dict")

        chart_type = str(data.get("chart_type") or "bar")
        user_request = str(data.get("user_request") or data.get("edit_request") or "")
        render_error = data.get("render_error_comment") or None
        no_text = bool(data.get("no_text_mode", False))
        _meta_keys = {"chart_type", "user_request", "edit_request", "render_error_comment", "no_text_mode"}
        data_keys = [k for k in data if k not in _meta_keys]

        messages = chart_coder_messages(
            chart_type=chart_type,
            user_request=user_request,
            data_keys=data_keys,
            render_error=render_error,
            no_text=no_text,
        )

        trace_id = get_current_trace_id()
        node_name = get_current_node_name() or "plot_creator"
        model_name = getattr(self.llm, "model", "llm")

        with llm_generation(
            trace_id=trace_id,
            name=f"{node_name}.chart_coder",
            model=str(model_name),
            messages=messages,
            metadata={"chart_type": chart_type},
        ) as set_output:
            raw = await self.llm.chat(messages, temperature=0.2)
            code = _extract_code(raw)
            set_output({"code_len": len(code), "raw_len": len(raw)})

        if not code:
            raise RuntimeError("ChartCoderAgent: LLM returned empty code")

        logger.debug("ChartCoderAgent: chart_type=%s code_len=%d", chart_type, len(code))
        return {"code": code}
