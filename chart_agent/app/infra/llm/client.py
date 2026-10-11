import json

import httpx

from app.infra.tracing import (
    get_current_node_name,
    get_current_trace_id,
    llm_generation,
)

class LLMServiceError(Exception):
    pass


class LLMServiceUnavailableError(LLMServiceError):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        raw_base = base_url.rstrip("/")
        self.api_base = raw_base if raw_base.endswith("/v1") else f"{raw_base}/v1"
        self.api_key = api_key
        self.model = model

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def check_model_available(self, timeout: float = 5.0) -> None:
        # Primary check: OpenAI-style models endpoint.
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{self.api_base}/models", headers=self._headers)
                if response.status_code == 404:
                    # Some custom OpenAI wrappers do not expose /models.
                    health = await client.get(f"{self.api_base}/health", headers=self._headers)
                    health.raise_for_status()
                    return
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMServiceUnavailableError(
                f"LLM healthcheck failed for {self.api_base}/models (fallback /health): {exc}"
            ) from exc

        try:
            payload = response.json()
            models = payload.get("data", [])
            available = {
                item.get("id")
                for item in models
                if isinstance(item, dict) and item.get("id")
            }
            if available and self.model and self.model not in available:
                raise LLMServiceUnavailableError(
                    f"Model '{self.model}' is not exposed by {self.api_base}. "
                    f"Available: {', '.join(sorted(available))}"
                )
        except (AttributeError, TypeError, ValueError) as exc:
            # Keep backward compatibility with wrappers that return non-standard payload.
            # If /models is reachable but payload is custom, treat endpoint as alive.
            return

    async def chat(self, messages: list[dict], temperature: float = 0.2, json_schema: dict | None = None):
        from app.core.config import settings
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if settings.llm_disable_reasoning:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if settings.llm_json_output_enabled and json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": False,
                    "schema": json_schema,
                },
            }
        trace_id = get_current_trace_id()
        node_name = get_current_node_name() or "llm"
        generation_name = f"{node_name}.llm_call"
        prompt_snapshot = self._messages_for_trace(messages)
        try:
            with llm_generation(
                trace_id=trace_id,
                name=generation_name,
                model=self.model,
                messages=prompt_snapshot,
                metadata={"temperature": temperature, "json_schema": bool(json_schema)},
            ) as set_output:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        f"{self.api_base}/chat/completions",
                        headers=self._headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    usage_raw = data.get("usage")
                    usage = None
                    if isinstance(usage_raw, dict):
                        usage = {
                            "input": usage_raw.get("prompt_tokens"),
                            "output": usage_raw.get("completion_tokens"),
                            "total": usage_raw.get("total_tokens"),
                            "unit": "TOKENS",
                        }
                    set_output(self._parse_trace_output(content), usage=usage)
                    return content
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMServiceUnavailableError(
                f"LLM request failed for model '{self.model}' at {self.api_base}: {exc}"
            ) from exc

    @staticmethod
    def _messages_for_trace(messages: list[dict], max_text_chars: int = 4000) -> list[dict]:
        safe_messages: list[dict] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if isinstance(content, str):
                safe_messages.append(
                    {"role": role, "content": content[:max_text_chars]}
                )
                continue

            if isinstance(content, list):
                safe_content: list[dict] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    if item_type == "text":
                        text = str(item.get("text") or "")
                        safe_content.append({"type": "text", "text": text[:max_text_chars]})
                    elif item_type == "image_url":
                        safe_content.append({"type": "image_url", "image_url": {"url": "[redacted]"}})
                    else:
                        safe_content.append({"type": item_type})
                safe_messages.append({"role": role, "content": safe_content})
                continue

            safe_messages.append({"role": role, "content": str(content)[:max_text_chars]})

        return safe_messages

    @staticmethod
    def _parse_trace_output(content: object) -> object:
        if not isinstance(content, str):
            return content
        text = content.strip()
        if not text:
            return ""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return content
