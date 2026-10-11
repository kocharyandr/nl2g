from __future__ import annotations

import ast
import base64
import builtins
import io
import multiprocessing
import queue
import os
import signal
from types import MappingProxyType
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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


def validate_code_ast(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"SyntaxError: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            raise ValueError("Import statements are not allowed — libraries are pre-imported.")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALL_NAMES:
                raise ValueError(f"Forbidden call: {node.func.id}")

        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTE_NAMES:
            raise ValueError(f"Forbidden attribute: {node.attr}")

        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALL_NAMES:
            raise ValueError(f"Forbidden name: {node.id}")


def _worker(code: str, data: dict, result_queue: multiprocessing.Queue) -> None:
    try:
        safe_builtins = {name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES}
        safe_globals: dict[str, Any] = {
            "plt": plt,
            "np": np,
            "pd": pd,
            "__builtins__": MappingProxyType(safe_builtins),
        }
        local_vars: dict[str, Any] = {"data": data}

        exec(code, safe_globals, local_vars)  # noqa: S102

        fig = local_vars.get("fig")
        if fig is None:
            fig_nums = plt.get_fignums()
            if fig_nums:
                fig = plt.figure(fig_nums[-1])
        if fig is None:
            result_queue.put({"error": "Code did not assign a `fig` variable."})
            return

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close("all")
        result_queue.put({"image_b64": base64.b64encode(buf.getvalue()).decode("ascii")})
    except Exception as exc:  # noqa: BLE001
        result_queue.put({"error": f"{type(exc).__name__}: {exc}"})


def execute_chart_code(code: str, data: dict, timeout: float = 10.0) -> str:
    """Execute chart code in a subprocess and return base64-encoded PNG."""
    if not code.strip():
        raise ValueError("Empty code.")

    validate_code_ast(code)

    ctx = multiprocessing.get_context("fork")
    result_queue: multiprocessing.Queue = ctx.Queue()
    proc = ctx.Process(target=_worker, args=(code, data, result_queue), daemon=True)
    proc.start()

    # Read the result BEFORE joining. A Queue is backed by a pipe with a finite
    # buffer (64 KB), and put() blocks once it is full. Joining first deadlocks
    # on any payload above that: the child waits to finish writing, the parent
    # waits for the child to exit. A base64 PNG crosses 64 KB at roughly a
    # 48 KB image — i.e. on any moderately detailed chart.
    try:
        result = result_queue.get(timeout=timeout)
    except queue.Empty:
        proc.kill()
        proc.join()
        raise TimeoutError(f"Code execution exceeded {timeout}s timeout.") from None

    # The payload is drained, so the child can now exit on its own.
    proc.join(timeout=5)
    if proc.is_alive():
        proc.kill()
        proc.join()
    if "error" in result:
        raise RuntimeError(result["error"])

    return result["image_b64"]
