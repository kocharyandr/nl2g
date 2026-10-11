"""
Converts DatasetSpec + ChartIntent into a flat dict that the chart code accesses via data["key"].

Common layouts produced:
  single series:   {"labels": [...], "values": [...]}
  grouped/stacked: {"categories": [...], "SeriesA": [...], "SeriesB": [...]}
  scatter single:  {"x": [...], "y": [...], "labels": [...]}
  scatter multi:   {"SeriesA_x": [...], "SeriesA_y": [...], ...}
  histogram:       {"values": [...]}  or  {"GroupA": [...], "GroupB": [...]}
  box plot:        {"GroupA": [...], "GroupB": [...]}
  heatmap:         {"rows": [...], "cols": [...], "matrix": [[...]]}

Metadata keys always added (may be empty string):
  "title", "x_label", "y_label", "chart_type"
"""
from __future__ import annotations

from typing import Any

from app.api.schemas import ChartIntent, DataPoint, DatasetSpec


def _label_of(p: DataPoint) -> str:
    if p.label is not None:
        return str(p.label)
    if p.x is not None:
        return str(p.x)
    return ""


def _y(p: DataPoint) -> float:
    return float(p.y) if p.y is not None else 0.0


def _x(p: DataPoint) -> float:
    return float(p.x) if p.x is not None else 0.0


def flatten_dataset(
    spec: DatasetSpec,
    chart_intent: ChartIntent | None = None,
    chart_type: str = "bar",
) -> dict[str, Any]:
    points = spec.points or []
    ct = (chart_type or "bar").lower()

    series = list(dict.fromkeys(p.series for p in points if p.series))

    if ct == "histogram":
        if len(series) <= 1:
            result: dict[str, Any] = {"values": [_y(p) for p in points]}
        else:
            result = {ser: [_y(p) for p in points if p.series == ser] for ser in series}

    elif ct in ("box", "box_plot"):
        if not series:
            result = {"values": [_y(p) for p in points]}
        else:
            result = {ser: [_y(p) for p in points if p.series == ser] for ser in series}

    elif ct == "scatter":
        if len(series) <= 1:
            result = {
                "x": [_x(p) for p in points],
                "y": [_y(p) for p in points],
            }
            labels = [p.label or "" for p in points]
            if any(labels):
                result["labels"] = labels
        else:
            result = {}
            for ser in series:
                pts = [p for p in points if p.series == ser]
                result[f"{ser}_x"] = [_x(p) for p in pts]
                result[f"{ser}_y"] = [_y(p) for p in pts]

    elif ct == "heatmap":
        rows = list(dict.fromkeys((p.series or p.label or "") for p in points))
        cols = list(dict.fromkeys(_label_of(p) if p.x is None else str(p.x) for p in points))
        matrix = []
        for row in rows:
            row_data = []
            for col in cols:
                val = next(
                    (_y(p) for p in points
                     if (p.series or p.label or "") == row
                     and (_label_of(p) if p.x is None else str(p.x)) == col),
                    0.0,
                )
                row_data.append(val)
            matrix.append(row_data)
        result = {"rows": rows, "cols": cols, "matrix": matrix}

    elif len(series) <= 1:
        result = {
            "labels": [_label_of(p) for p in points],
            "values": [_y(p) for p in points],
        }

    else:
        categories = list(dict.fromkeys(_label_of(p) for p in points))
        result = {"categories": categories}
        for ser in series:
            ser_map = {_label_of(p): _y(p) for p in points if p.series == ser}
            result[ser] = [ser_map.get(cat, 0.0) for cat in categories]

    # Always include metadata (code may use it for labels/title)
    intent = chart_intent
    result["title"] = (intent.title_hint or "") if intent else ""
    result["x_label"] = (intent.x_label or "") if intent else ""
    result["y_label"] = (intent.y_label or "") if intent else ""
    result["chart_type"] = ct

    return result
