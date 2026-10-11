from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from app.core.config import settings
from app.infra.tracing import get_langfuse

logger = logging.getLogger(__name__)
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _render_fallback(template: str, variables: dict[str, Any] | None) -> str:
    if not variables:
        return template
    try:
        return _VAR_RE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), template)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to render fallback prompt template: %s", exc)
        return template


def _extract_text_prompt(payload: Any) -> str | None:
    if isinstance(payload, str):
        text = payload.strip()
        return text or None

    if isinstance(payload, Mapping):
        for key in ("prompt", "content", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        messages = payload.get("messages")
        if isinstance(messages, list):
            parts = []
            for item in messages:
                if isinstance(item, Mapping):
                    content = item.get("content")
                    if isinstance(content, str) and content.strip():
                        parts.append(content.strip())
            if parts:
                return "\n\n".join(parts)

    if isinstance(payload, list):
        parts = []
        for item in payload:
            if isinstance(item, Mapping):
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    parts.append(content.strip())
        if parts:
            return "\n\n".join(parts)

    return None


def get_text_prompt(
    name: str,
    fallback: str,
    *,
    variables: dict[str, Any] | None = None,
    label: str | None = None,
) -> str:
    fallback_rendered = _render_fallback(fallback, variables)

    if not settings.langfuse_prompts_enabled:
        return fallback_rendered

    langfuse = get_langfuse()
    if langfuse is None:
        return fallback_rendered

    resolved_label = (label or settings.langfuse_prompt_label or "").strip() or None
    kwargs: dict[str, Any] = {"type": "text"}
    if resolved_label:
        kwargs["label"] = resolved_label

    try:
        try:
            prompt_obj = langfuse.get_prompt(name, **kwargs)
        except TypeError:
            prompt_obj = langfuse.get_prompt(name=name, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse get_prompt failed for '%s': %s", name, exc)
        return fallback_rendered

    try:
        if hasattr(prompt_obj, "compile"):
            compiled = prompt_obj.compile(**(variables or {}))
        else:
            compiled = prompt_obj
        prompt_text = _extract_text_prompt(compiled)
        if prompt_text:
            if _VAR_RE.search(prompt_text):
                logger.warning(
                    "Langfuse prompt '%s' has unsubstituted variables after compile "
                    "(stale template with wrong variable names), using local fallback",
                    name,
                )
                return fallback_rendered
            return prompt_text
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse prompt compile failed for '%s': %s", name, exc)

    return fallback_rendered


def get_system_prompt(name: str, fallback: str) -> str:
    return get_text_prompt(name=name, fallback=fallback)
