import json
import logging
import re

from app.infra.tracing import (
    get_current_node_name,
    get_current_trace_id,
    llm_generation,
)

logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


class BaseJsonAgent:
    def __init__(self, llm, structured_llm=None):
        self.llm = llm
        self.structured_llm = structured_llm

    @staticmethod
    def _extract_json_text(raw: str) -> str:
        text = (raw or "").strip()
        fence = _JSON_FENCE_RE.search(text)
        if fence:
            return fence.group(1).strip()
        return text

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escaped = False

        for idx in range(start, len(text)):
            ch = text[idx]

            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]

        return None

    @classmethod
    def _load_json_payload(cls, raw: str) -> dict:
        text = cls._extract_json_text(raw)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        candidate = cls._extract_first_json_object(text) or cls._extract_first_json_object(raw)
        if candidate is None:
            raise ValueError("No JSON object found in model output")

        payload = json.loads(candidate)
        if not isinstance(payload, dict):
            raise ValueError("Model output JSON must be an object")
        return payload

    @staticmethod
    def _to_image_url(image_data: str) -> str:
        value = (image_data or "").strip()
        if not value:
            return value
        if value.startswith("data:image/"):
            return value
        # Default to PNG base64 payload.
        return f"data:image/png;base64,{value}"

    def _build_messages(
        self,
        prompt: str,
        images: list[str] | None = None,
    ) -> list[dict]:
        image_urls = [self._to_image_url(img) for img in (images or []) if img and img.strip()]
        if not image_urls:
            content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        else:
            content = [{"type": "text", "text": prompt}]
            content.extend([{"type": "image_url", "image_url": {"url": url}} for url in image_urls])
        return [{"role": "user", "content": content}]

    async def _chat(
        self,
        prompt: str,
        temperature: float = 0.0,
        images: list[str] | None = None,
        json_schema: dict | None = None,
    ) -> str:
        messages = self._build_messages(prompt, images)
        return await self.llm.chat(
            messages,
            temperature=temperature,
            json_schema=json_schema,
        )

    async def run_json_model(
        self,
        prompt: str,
        model_cls: type,
        temperature: float = 0.0,
        images: list[str] | None = None,
    ):
        schema = model_cls.model_json_schema() if not images else None
        trace_id = get_current_trace_id()
        node_name = get_current_node_name() or "llm"
        model_name = getattr(self.llm, "model", "llm")
        messages = self._build_messages(prompt, images)
        with llm_generation(
            trace_id=trace_id,
            name=f"{node_name}.json_model",
            model=str(model_name),
            messages=messages,
            metadata={"model_cls": model_cls.__name__},
        ) as set_output:
            raw = await self.llm.chat(messages, temperature=temperature, json_schema=schema)
            try:
                payload = self._load_json_payload(raw)
                result = model_cls.model_validate(payload)
                set_output(result.model_dump() if hasattr(result, "model_dump") else str(result))
                return result
            except Exception as exc:
                set_output({"parse_error": str(exc), "raw_response": raw})
                raise

    async def run_structured_or_json_model(
        self,
        prompt: str,
        model_cls: type,
        temperature: float = 0.0,
        images: list[str] | None = None,
    ):
        if images:
            return await self.run_json_model(
                prompt=prompt,
                model_cls=model_cls,
                temperature=temperature,
                images=images,
            )

        if self.structured_llm is not None:
            try:
                chain = self.structured_llm.with_structured_output(model_cls)
                trace_id = get_current_trace_id()
                node_name = get_current_node_name() or "llm"
                model_name = getattr(self.structured_llm, "model_name", None) or getattr(
                    self.structured_llm, "model", "structured_llm"
                )
                with llm_generation(
                    trace_id=trace_id,
                    name=f"{node_name}.structured_output",
                    model=str(model_name),
                    messages=self._build_messages(prompt),
                    metadata={"model_cls": model_cls.__name__},
                ) as set_output:
                    parsed = await chain.ainvoke(prompt)
                    if hasattr(parsed, "model_dump"):
                        set_output(parsed.model_dump())
                    elif isinstance(parsed, (dict, list)):
                        set_output(parsed)
                    else:
                        set_output(str(parsed))
                return parsed
            except Exception as structured_exc:  # noqa: BLE001
                logger.warning(
                    "structured_output failed for %s, falling back to json_model: %s",
                    model_cls.__name__,
                    structured_exc,
                )

        return await self.run_json_model(
            prompt=prompt,
            model_cls=model_cls,
            temperature=temperature,
            images=images,
        )

    async def run(
        self,
        *,
        prompt: str,
        model_cls: type,
        temperature: float = 0.0,
        images: list[str] | None = None,
        prefer_structured: bool = True,
    ):
        if prefer_structured:
            return await self.run_structured_or_json_model(
                prompt=prompt,
                model_cls=model_cls,
                temperature=temperature,
                images=images,
            )
        return await self.run_json_model(
            prompt=prompt,
            model_cls=model_cls,
            temperature=temperature,
            images=images,
        )
