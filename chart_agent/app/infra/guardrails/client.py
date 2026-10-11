"""HTTP client for the guardrails_api service (GLiNER2-based).

Two operations are exposed:

* `safety_check(text)` — full safety classification (6 dims). Returns a
  `SafetyResult` with `status=ok|reject` and a user-facing rejection message
  if rejected.
* `classify(text, task, labels, ...)` — zero-shot classification with
  caller-supplied labels. Used by routers as a fast, no-LLM path.

Both calls are traced via Langfuse spans (`guardrails.safety` /
`guardrails.classify`) so every routing decision is visible alongside LLM
calls. The label set itself is logged into the span so it acts as a
"prompt-equivalent" artefact in Langfuse.

Disabled / failing service is treated according to `GUARDRAILS_FAIL_OPEN`:
* fail-open=True (default): returns `None` (or `safe`) so caller falls back
  to the existing LLM path — no requests are blocked by guardrails outage.
* fail-open=False: returns an error result; safety filter blocks the request.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SafetyResult:
    status: str  # "ok" | "reject" | "error"
    type_reject: str | None = None
    message: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def rejected(self) -> bool:
        return self.status == "reject"


@dataclass(slots=True)
class ClassifyResult:
    label: str | None
    confidence: float
    all_scores: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] | None = None

    def passes(self, threshold: float) -> bool:
        return self.label is not None and self.confidence >= threshold


class GuardrailsClient:
    """Async HTTP client for the guardrails_api service."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        api_version: str | None = None,
        timeout: float | None = None,
        fail_open: bool | None = None,
    ) -> None:
        self.host = host or settings.guardrails_host
        self.port = port or settings.guardrails_port
        self.api_version = (api_version or settings.guardrails_api_version).rstrip("/")
        self.timeout = timeout or settings.guardrails_timeout_sec
        self.fail_open = fail_open if fail_open is not None else settings.guardrails_fail_open
        self._enabled = settings.guardrails_enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}{self.api_version}"

    async def health(self) -> bool:
        if not self._enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"http://{self.host}:{self.port}/metrics")
                return r.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("guardrails health probe failed: %s", exc)
            return False

    # ── Safety ──────────────────────────────────────────────────────────

    async def safety_check(self, text: str) -> SafetyResult:
        """Full safety classification. Logs span `guardrails.safety`.

        Returns:
            SafetyResult with status `ok`/`reject`/`error`.
            On disabled/error and `fail_open=True` returns `ok`.
        """
        if not self._enabled or not settings.guardrails_safety_enabled:
            return SafetyResult(status="ok", raw={"skipped": True})

        with node_span(
            trace_id=None,
            name="guardrails.safety",
            input={"text": text},
            metadata={"endpoint": "/classify", "model": "gliner2"},
        ) as span:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(
                        f"{self.base_url}/classify",
                        json={"query": text},
                    )
                    r.raise_for_status()
                    data = r.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("guardrails safety_check failed: %s", exc)
                if span is not None:
                    try:
                        span.update(output={"error": str(exc), "fail_open": self.fail_open})
                    except Exception:  # noqa: BLE001
                        pass
                if self.fail_open:
                    return SafetyResult(status="ok", raw={"error": str(exc)})
                return SafetyResult(status="error", message=str(exc))

            result = SafetyResult(
                status=data.get("status", "ok"),
                type_reject=data.get("type_reject"),
                message=data.get("message"),
                raw=data,
            )
            if span is not None:
                try:
                    span.update(
                        output={
                            "status": result.status,
                            "type_reject": result.type_reject,
                            "message": result.message,
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
            return result

    # ── Custom classification (routing) ─────────────────────────────────

    async def classify(
        self,
        text: str,
        task: str,
        labels: list[str],
        label_descriptions: dict[str, str] | None = None,
        multi_label: bool = False,
    ) -> ClassifyResult | None:
        """Zero-shot classify. Logs span `guardrails.classify.<task>`.

        Returns:
            ClassifyResult on success, or None if disabled / service errored
            (so caller falls back to LLM).
        """
        if not self._enabled:
            return None

        with node_span(
            trace_id=None,
            name=f"guardrails.classify.{task}",
            input={"text": text, "labels": labels, "label_descriptions": label_descriptions},
            metadata={"endpoint": "/classify/custom", "task": task, "multi_label": multi_label},
        ) as span:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(
                        f"{self.base_url}/classify/custom",
                        json={
                            "text": text,
                            "task": task,
                            "labels": labels,
                            "label_descriptions": label_descriptions,
                            "multi_label": multi_label,
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("guardrails classify(%s) failed: %s", task, exc)
                if span is not None:
                    try:
                        span.update(output={"error": str(exc)})
                    except Exception:  # noqa: BLE001
                        pass
                return None

            result = ClassifyResult(
                label=data.get("label"),
                confidence=float(data.get("confidence", 0.0)),
                all_scores=dict(data.get("all_scores") or {}),
                raw=data,
            )
            if span is not None:
                try:
                    span.update(
                        output={
                            "label": result.label,
                            "confidence": result.confidence,
                            "all_scores": result.all_scores,
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
            return result


# Module-level singleton
_client: GuardrailsClient | None = None


def get_guardrails_client() -> GuardrailsClient:
    global _client
    if _client is None:
        _client = GuardrailsClient()
    return _client
