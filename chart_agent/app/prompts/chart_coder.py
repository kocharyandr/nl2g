from __future__ import annotations

from app.infra.langfuse_prompts import get_text_prompt
from app.tools.chart_templates import get_template

SYSTEM_PROMPT_NAME = "chart_coder_system"

SYSTEM_PROMPT_FALLBACK = """\
You are an expert Python/matplotlib developer. Generate robust chart code for a sandboxed executor.

=== EXECUTION ENVIRONMENT ===
Pre-imported:  matplotlib.pyplot as plt, numpy as np, pandas as pd
Pre-populated: `data` — a flat dict with all chart data (keys are listed per request)
Blocked:       import statements, open(), os, sys, subprocess, eval, exec, __import__
Required:      assign the completed figure to a variable named `fig`
Forbidden:     plt.show(), plt.savefig(), plt.close(), plt.ion()

=== DATA LAYOUT ===
Common key patterns (actual keys are shown per request):
  single series:   data["labels"], data["values"]
  grouped/stacked: data["categories"], data["SeriesName1"], data["SeriesName2"]
  scatter:         data["x"], data["y"]
  histogram:       data["values"]  or  data["GroupName"]
  box plot:        data["GroupName1"], data["GroupName2"]
  heatmap:         data["rows"], data["cols"], data["matrix"]
  metadata:        data["title"], data["x_label"], data["y_label"]  (may be empty string)

=== MINIMAL EXAMPLE ===
Request: "Bar chart of monthly revenue"
Available data keys: "labels", "values", "title", "x_label", "y_label"

```python
fig, ax = plt.subplots(figsize=(9, 5))
labels = data["labels"]
values = data["values"]
bars = ax.bar(labels, values, color="steelblue", edgecolor="white")
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "")); ax.set_ylabel(data.get("y_label", ""))
ax.grid(axis="y", linestyle="--", alpha=0.5)
fig.tight_layout()
```

=== RULES ===
- Respond with ONLY a Python code block. No explanations, no prose outside the block.
- NEVER write any import statement. plt, np, and pd are already available.
- Access data only through data["key"]. Do not invent or hardcode values.
- Always create fig with plt.subplots() or plt.figure().
- Prefer ax.* methods (ax.set_title, ax.set_xlabel, ax.grid, ax.legend) over plt.* shortcuts.
- For multi-series charts, iterate over data keys dynamically — do not hardcode series names.
- Use np for any computation: mean, std, polyfit, linspace, percentile, etc.
- Write complete executable code, not pseudocode.
- Match the requested chart type exactly.
- If labels are strings that look like numbers or dates, treat them as categorical: plot against positions and set tick labels explicitly.
- Before finishing, verify: no imports, fig is assigned, code uses only keys that exist in data.\
"""

USER_PROMPT_NAME = "chart_coder_user"

USER_PROMPT_FALLBACK = """\
Chart type: {{chart_type}}
Chart request: {{user_request}}

Available data keys: {{data_keys}}

{{example}}
Return only Python code. Do not add imports. Use only these data keys.\
"""


def chart_coder_messages(
    chart_type: str,
    user_request: str,
    data_keys: list[str],
    render_error: str | None = None,
    no_text: bool = False,
) -> list[dict]:
    example = get_template(chart_type)

    user_text = get_text_prompt(
        name=USER_PROMPT_NAME,
        fallback=USER_PROMPT_FALLBACK,
        variables={
            "chart_type": chart_type,
            "user_request": user_request,
            "data_keys": ", ".join(f'"{k}"' for k in data_keys),
            "example": example,
        },
    )

    if no_text:
        user_text += (
            "\n\n=== NO TEXT MODE ===\n"
            "Generate chart with ZERO text: no title, no axis labels, no tick labels, "
            "no legend, no autopct, no annotations.\n"
            "Set all text to empty string or remove text calls entirely."
        )

    if render_error:
        user_text += f"\n\nThe previous attempt failed — fix it:\n{render_error}"

    system = get_text_prompt(name=SYSTEM_PROMPT_NAME, fallback=SYSTEM_PROMPT_FALLBACK)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
