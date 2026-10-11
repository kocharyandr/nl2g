from __future__ import annotations

import ast
import base64
import builtins
import concurrent.futures
import io
import logging
import re
from types import MappingProxyType
from typing import Any

import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)

SAFE_BUILTIN_NAMES = {
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "int", "isinstance", "len", "list", "map", "max", "min", "range",
    "round", "set", "sorted", "str", "sum", "tuple", "zip", "print",
    "type", "repr", "vars",
}

FORBIDDEN_CALL_NAMES = {
    "open", "exec", "eval", "compile", "__import__",
    "getattr", "setattr", "delattr",
}
FORBIDDEN_ATTRIBUTE_NAMES = {
    "__base__", "__bases__", "__class__", "__code__",
    "__dict__", "__globals__", "__mro__", "__subclasses__",
}

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def extract_code_from_response(raw: str) -> str:
    match = _CODE_FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def _validate_code_ast(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Синтаксическая ошибка в коде: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            raise ValueError("Код не должен содержать import — библиотеки уже доступны через переменные.")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALL_NAMES:
                raise ValueError(f"Запрещённый вызов: {node.func.id}")

        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTE_NAMES:
            raise ValueError(f"Запрещённый атрибут: {node.attr}")

        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALL_NAMES:
            raise ValueError(f"Запрещённое имя: {node.id}")


def _build_safe_globals() -> dict[str, Any]:
    safe_builtins = {name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES}
    return {
        "plt": plt,
        "np": np,
        "pd": pd,
        "__builtins__": MappingProxyType(safe_builtins),
    }


def _exec_in_thread(code: str, safe_globals: dict[str, Any], local_vars: dict[str, Any]) -> None:
    exec(code, safe_globals, local_vars)  # noqa: S102


def _execute_local(code: str, data: dict, timeout: float = 10.0) -> bytes:
    _validate_code_ast(code)

    plt.close("all")
    local_vars: dict[str, Any] = {"data": data}
    safe_globals = _build_safe_globals()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_exec_in_thread, code, safe_globals, local_vars)
    try:
        future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"Код выполнялся дольше {timeout}с") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    fig = local_vars.get("fig")
    if fig is None:
        fig_nums = plt.get_fignums()
        if fig_nums:
            fig = plt.figure(fig_nums[-1])
    if fig is None:
        raise ValueError("Код не создал переменную fig (matplotlib.figure.Figure).")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close("all")
    return buf.getvalue()


def _execute_remote(code: str, data: dict, timeout: float = 10.0) -> bytes:
    url = settings.code_executor_url_safe
    try:
        resp = httpx.post(
            f"{url}/execute",
            json={"code": code, "data": data, "timeout": timeout},
            timeout=timeout + 5.0,
        )
    except httpx.RequestError as exc:
        raise RuntimeError(f"Code executor service unreachable: {exc}") from exc

    if resp.status_code != 200:
        body = resp.json()
        raise RuntimeError(f"{body.get('error_type', 'Error')}: {body.get('error', resp.text)}")

    image_b64 = resp.json()["image_b64"]
    return base64.b64decode(image_b64)


def execute_chart_code(code: str, data: dict, timeout: float = 10.0) -> bytes:
    """Execute chart code and return PNG bytes.

    Delegates to remote code-executor service when CODE_EXECUTOR_URL is set,
    otherwise falls back to local in-process execution.
    """
    if not code.strip():
        raise ValueError("Код пустой.")

    executor_url = settings.code_executor_url_safe
    if executor_url:
        logger.debug("execute_chart_code: remote executor url=%s", executor_url)
        return _execute_remote(code, data, timeout)

    logger.debug("execute_chart_code: local fallback")
    return _execute_local(code, data, timeout)
