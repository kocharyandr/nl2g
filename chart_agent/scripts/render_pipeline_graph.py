from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.registry import AgentRegistry
from app.graph.pipeline import build_graph
from langchain_core.runnables.graph_mermaid import MermaidDrawMethod, draw_mermaid_png


def _sanitize_mermaid_syntax(mermaid_syntax: str) -> str:
    sanitized = mermaid_syntax
    sanitized = sanitized.replace("\tend(end)", "\tgraph_end(end)")
    sanitized = sanitized.replace("\tend ", "\tgraph_end ")
    sanitized = sanitized.replace("-> end;", "-> graph_end;")
    return sanitized


def main() -> Path:
    compiled = build_graph(AgentRegistry())
    mermaid_syntax = compiled.get_graph().draw_mermaid()
    mermaid_syntax = _sanitize_mermaid_syntax(mermaid_syntax)
    png_bytes = draw_mermaid_png(
        mermaid_syntax,
        draw_method=MermaidDrawMethod.PYPPETEER,
    )

    out_path = PROJECT_ROOT / "app" / "graph" / "pipeline_graph.png"
    out_path.write_bytes(png_bytes)
    return out_path


if __name__ == "__main__":
    path = main()
    print(path)
