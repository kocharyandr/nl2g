from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_langfuse = None
_current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)
_current_node_name: ContextVar[str | None] = ContextVar("current_node_name", default=None)


@dataclass
class TraceHandle:
    id: str | None


def get_current_trace_id() -> str | None:
    return _current_trace_id.get()


def get_current_node_name() -> str | None:
    return _current_node_name.get()


def get_langfuse():
    global _langfuse
    if _langfuse is None and settings.langfuse_enabled:
        try:
            from langfuse import get_client

            try:
                _langfuse = get_client(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
            except TypeError:
                _langfuse = get_client()
        except Exception as exc:
            logger.warning("Langfuse init failed, tracing disabled: %s", exc)
    return _langfuse


def create_trace(session_id: str, user_input: str | None = None, metadata: dict | None = None):
    # SDK v4 creates traces via root observations. Keep a lightweight handle for compatibility.
    _ = session_id, user_input, metadata
    return TraceHandle(id=None)


def get_trace(trace_id: str | None):
    _ = trace_id
    return None


def _infer_trace_id(langfuse_client, observation) -> str | None:
    if observation is not None:
        candidate = getattr(observation, "trace_id", None)
        if isinstance(candidate, str) and candidate:
            return candidate
    try:
        getter = getattr(langfuse_client, "get_current_trace_id", None)
        if callable(getter):
            value = getter()
            if isinstance(value, str) and value:
                return value
    except Exception:
        pass
    return None


class _SpanHandle:
    """Wraps a Langfuse span so callers can set output without holding the raw object."""

    def __init__(self, span: Any) -> None:
        self._span = span

    def set_output(self, output: Any) -> None:
        try:
            if self._span is not None:
                self._span.update(output=output)
        except Exception:
            pass


@contextmanager
def node_span(trace_id: str | None, name: str, input: Any = None, metadata: dict | None = None):
    langfuse_client = get_langfuse()
    tok_trace = _current_trace_id.set(trace_id)
    tok_node = _current_node_name.set(name)

    if langfuse_client is None:
        try:
            yield _SpanHandle(None)
        finally:
            _current_trace_id.reset(tok_trace)
            _current_node_name.reset(tok_node)
        return

    try:
        with langfuse_client.start_as_current_observation(
            as_type="span",
            name=name,
            input=input,
            metadata=metadata or {},
        ) as span:
            active_trace_id = _infer_trace_id(langfuse_client, span) or trace_id
            tok_active_trace = _current_trace_id.set(active_trace_id)
            handle = _SpanHandle(span)
            try:
                yield handle
            finally:
                _current_trace_id.reset(tok_active_trace)
    except Exception as exc:
        logger.warning("Langfuse span error node=%s: %s", name, exc)
        raise
    finally:
        _current_trace_id.reset(tok_trace)
        _current_node_name.reset(tok_node)


def _messages_to_langfuse_input(messages: list[dict] | str) -> Any:
    """Convert messages list to Langfuse-friendly input format.

    Langfuse renders a list of {role, content} dicts as a proper chat view.
    For multimodal messages the content may itself be a list; keep it as-is.
    """
    if isinstance(messages, str):
        return messages
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal: extract text parts for display, keep images as markers
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        parts.append("[image]")
                else:
                    parts.append(str(item))
            result.append({"role": role, "content": "\n".join(parts)})
        else:
            result.append({"role": role, "content": content})
    return result


@contextmanager
def llm_generation(
    trace_id: str | None,
    name: str,
    model: str,
    messages: list[dict] | str,
    metadata: dict | None = None,
    # legacy alias kept for callers that still pass prompt= keyword
    prompt: list[dict] | str | None = None,
):
    langfuse_client = get_langfuse()
    input_data = _messages_to_langfuse_input(messages if messages is not None else (prompt or ""))
    if langfuse_client is None:
        yield lambda result, usage=None: None
        return

    try:
        with langfuse_client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input_data,
            metadata=metadata or {},
        ) as generation:
            def _set_output(result: Any, usage: dict | None = None) -> None:
                try:
                    update_kwargs: dict[str, Any] = {"output": result}
                    if usage is not None:
                        update_kwargs["usage"] = usage
                    generation.update(**update_kwargs)
                except Exception:
                    pass

            yield _set_output
    except Exception as exc:
        logger.warning("Langfuse generation error node=%s: %s", name, exc)
        raise


def flush():
    langfuse_client = get_langfuse()
    if langfuse_client is not None:
        try:
            langfuse_client.flush()
        except Exception as exc:
            logger.warning("Langfuse flush failed: %s", exc)
