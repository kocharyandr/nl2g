from __future__ import annotations

import ast
import builtins
import concurrent.futures
import logging
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from app.api.schemas import (
    AnalyticalGoal,
    ChartIntent,
    ChartType,
    DataFieldRole,
    DataFieldSpec,
    DataPoint,
    DatasetSpec,
    DataValidationReport,
    TableCodeSpec,
)
from app.tools.table_ingest import infer_column_type

SAFE_BUILTIN_NAMES = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "filter",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "map",
    "max",
    "min",
    "range",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
    "print",
    "type",
    "repr",
}

FORBIDDEN_CALL_NAMES = {"open", "exec", "eval", "compile", "__import__", "getattr", "setattr", "delattr"}
FORBIDDEN_ATTRIBUTE_NAMES = {
    "__base__",
    "__bases__",
    "__class__",
    "__code__",
    "__dict__",
    "__globals__",
    "__mro__",
    "__subclasses__",
}

GOAL_BY_CHART_TYPE = {
    "bar": AnalyticalGoal.comparison,
    "line": AnalyticalGoal.trend,
    "stacked_bar": AnalyticalGoal.composition,
    "pie": AnalyticalGoal.composition,
    "doughnut": AnalyticalGoal.composition,
    "scatter": AnalyticalGoal.relationship,
    "area": AnalyticalGoal.trend,
    "histogram": AnalyticalGoal.distribution,
    "box": AnalyticalGoal.distribution,
}


def _build_safe_globals() -> dict[str, Any]:
    safe_builtins = {name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES}
    return {
        "pd": pd,
        "np": np,
        "__builtins__": MappingProxyType(safe_builtins),
    }


def _validate_code_ast(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Сгенерированный код содержит синтаксическую ошибку: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            raise ValueError("Сгенерированный код не должен содержать import.")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALL_NAMES:
                raise ValueError(f"Сгенерированный код использует запрещенный вызов: {node.func.id}.")

        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTE_NAMES:
            raise ValueError(f"Сгенерированный код использует запрещенный атрибут: {node.attr}.")

        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALL_NAMES:
            raise ValueError(f"Сгенерированный код использует запрещенное имя: {node.id}.")


def _exec_in_thread(code: str, safe_globals: dict[str, Any], local_vars: dict[str, Any]) -> None:
    exec(code, safe_globals, local_vars)  # noqa: S102


def execute_code_safely(code: str, df: pd.DataFrame, timeout: float = 5.0) -> pd.DataFrame:
    if not code.strip():
        raise ValueError("Сгенерированный код пустой.")

    _validate_code_ast(code)
    local_vars: dict[str, Any] = {"df": df.copy()}
    safe_globals = _build_safe_globals()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_exec_in_thread, code, safe_globals, local_vars)
    try:
        future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"Код выполнялся дольше {timeout}с") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    result = local_vars.get("result")
    if not isinstance(result, pd.DataFrame):
        raise TypeError(f"Ожидался pd.DataFrame в переменной result, получен {type(result).__name__}")
    return result


def _to_numeric_series(series: pd.Series) -> pd.Series:
    normalized = series.map(lambda value: str(value).replace(",", ".").replace(" ", ""))
    return pd.to_numeric(normalized, errors="coerce")


def validate_result_dataframe(df: pd.DataFrame, spec: TableCodeSpec) -> list[str]:
    errors: list[str] = []
    y_col = spec.y_col or "y"

    if y_col not in df.columns:
        errors.append(f"колонка y_col '{y_col}' отсутствует в result")
    if spec.x_col and spec.x_col not in df.columns:
        errors.append(f"колонка x_col '{spec.x_col}' отсутствует в result")
    if spec.series_col and spec.series_col not in df.columns:
        errors.append(f"колонка series_col '{spec.series_col}' отсутствует в result")
    if df.empty:
        errors.append("result не должен быть пустым")

    if y_col in df.columns:
        y_values = _to_numeric_series(df[y_col])
        valid_count = y_values.notna().sum()
        if valid_count == 0:
            errors.append(f"колонка y_col '{y_col}' не содержит ни одного числового значения (все NaN после приведения)")

    return errors


def _point_value(value: object) -> float | str | None:
    # When duplicate column names exist in the DataFrame, row[col] returns a Series.
    # Collapse it to a scalar by taking the first non-NaN element.
    if isinstance(value, pd.Series):
        non_na = value.dropna()
        if non_na.empty:
            return None
        value = non_na.iloc[0]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        # pd.isna can fail on unusual types; treat as a stringifiable value
        pass
    if isinstance(value, np.integer | np.floating):
        return float(value)
    return value if isinstance(value, float | int | str) else str(value)


def _build_preview_from_points(points: list[DataPoint], limit: int = 10) -> list[dict[str, str | float | None]]:
    return [point.model_dump(mode="json") for point in points[:limit]]


def _format_raw_representation(preview_rows: list[dict[str, str | float | None]]) -> str:
    if not preview_rows:
        return ""
    headers = list(preview_rows[0].keys())
    lines = [",".join(headers)]
    for row in preview_rows:
        lines.append(",".join("" if row.get(header) is None else str(row.get(header)) for header in headers))
    return "\n".join(lines)


def _build_fields_for_result(
    df: pd.DataFrame,
    spec: TableCodeSpec,
    preview_rows: list[dict[str, str | float | None]],
    column_types: dict[str, str] | None = None,
) -> list[DataFieldSpec]:
    fields: list[DataFieldSpec] = []
    if spec.x_col:
        # A type reported by the database always wins over inference from
        # values; the heuristic only runs when no source of truth exists.
        declared = (column_types or {}).get(spec.x_col)
        if declared:
            x_type = declared
        else:
            x_type = infer_column_type(df[spec.x_col]) if spec.x_col in df.columns else "categorical"
        x_role = DataFieldRole.time if x_type == "temporal" else DataFieldRole.category
        fields.append(
            DataFieldSpec(
                name=spec.x_col,
                role=x_role,
                inferred_type=x_type,
                unique_count=int(df[spec.x_col].nunique()) if spec.x_col in df.columns else None,
                non_empty_count=int(df[spec.x_col].notna().sum()) if spec.x_col in df.columns else None,
                sample_values=[str(row.get("x")) for row in preview_rows if row.get("x") is not None][:4],
            )
        )
    if spec.series_col:
        fields.append(
            DataFieldSpec(
                name=spec.series_col,
                role=DataFieldRole.series,
                inferred_type="categorical",
                unique_count=int(df[spec.series_col].nunique()) if spec.series_col in df.columns else None,
                non_empty_count=int(df[spec.series_col].notna().sum()) if spec.series_col in df.columns else None,
                sample_values=[str(row.get("series")) for row in preview_rows if row.get("series")][:4],
            )
        )
    fields.append(
        DataFieldSpec(
            name=spec.y_col or "y",
            role=DataFieldRole.value,
            inferred_type="numeric",
            unique_count=int(df[spec.y_col].nunique()) if spec.y_col in df.columns else None,
            non_empty_count=int(df[spec.y_col].notna().sum()) if spec.y_col in df.columns else None,
            sample_values=[str(row.get("y")) for row in preview_rows if row.get("y") is not None][:4],
        )
    )
    return fields


def dataframe_to_dataset_spec(
    df: pd.DataFrame,
    spec: TableCodeSpec,
    source_columns: list[str],
    column_types: dict[str, str] | None = None,
    source_type: str = "csv",
) -> tuple[DatasetSpec, ChartIntent, DataValidationReport]:
    effective_chart_type = spec.chart_type
    if effective_chart_type is None:
        logger.warning("TableCodeSpec.chart_type is None, defaulting to bar")
        effective_chart_type = ChartType.bar
    chart_type = effective_chart_type.value

    y_col = spec.y_col or "y"
    validation_errors = validate_result_dataframe(df, spec)
    if validation_errors:
        validation = DataValidationReport(
            is_valid=False,
            reason="Результат DataFrame невалиден: " + "; ".join(validation_errors),
            correction_hint="Исправьте pandas-код так, чтобы result соответствовал контракту.",
        )
        return DatasetSpec(source_type=source_type), ChartIntent(), validation

    working_df = df.copy()
    # Drop duplicate columns to avoid row[col] returning a Series — keep first occurrence.
    if working_df.columns.duplicated().any():
        logger.warning("Duplicate columns in result, dropping duplicates: %s", list(working_df.columns))
        working_df = working_df.loc[:, ~working_df.columns.duplicated()]
    working_df[y_col] = _to_numeric_series(working_df[y_col])

    points: list[DataPoint] = []
    label_col = "label" if "label" in working_df.columns else spec.x_col
    if not label_col:
        # The planner sometimes leaves x_col empty for pie charts even though the
        # result keeps a category column (often moved into the index); without a
        # label the slices are anonymous.
        if not isinstance(working_df.index, pd.RangeIndex):
            working_df = working_df.reset_index()
        for col in working_df.columns:
            if col not in {y_col, spec.series_col} and not pd.api.types.is_numeric_dtype(working_df[col]):
                label_col = col
                break
    for _, row in working_df.iterrows():
        y_raw = _point_value(row[y_col])
        if y_raw is None:
            continue
        try:
            y_value = float(y_raw)
        except (TypeError, ValueError):
            continue

        x_value = _point_value(row[spec.x_col]) if spec.x_col else None
        label_value = _point_value(row[label_col]) if label_col else x_value
        series_value = _point_value(row[spec.series_col]) if spec.series_col else None
        points.append(
            DataPoint(
                label=None if label_value is None else str(label_value),
                x=x_value,
                y=y_value,
                series=None if series_value is None else str(series_value),
            )
        )

    if not points:
        validation = DataValidationReport(
            is_valid=False,
            reason="После выполнения кода не осталось валидных точек для построения графика.",
            correction_hint="Убедитесь, что result содержит хотя бы одну строку с числовым y.",
        )
        return DatasetSpec(source_type=source_type), ChartIntent(), validation

    preview_rows = _build_preview_from_points(points)
    dataset_spec = DatasetSpec(
        source_type=source_type,
        raw_representation=_format_raw_representation(preview_rows),
        fields=_build_fields_for_result(working_df, spec, preview_rows, column_types),
        points=points,
        row_count_estimate=len(points),
        preview_rows=preview_rows,
        notes=[
            f"source_columns={', '.join(source_columns)}",
            f"chart_type={chart_type}",
            f"x_col={spec.x_col or ''}",
            f"y_col={y_col}",
            f"series_col={spec.series_col or ''}",
            f"code_reasoning={spec.reasoning}",
        ],
    )
    chart_intent = ChartIntent(
        analytical_goal=GOAL_BY_CHART_TYPE.get(chart_type, AnalyticalGoal.unknown),
        recommended_chart_type=effective_chart_type,
        title_hint=spec.title_hint.strip(),
        x_label=spec.x_label or spec.x_col or "",
        y_label=spec.y_label or spec.y_col or "",
        reasoning=spec.reasoning,
    )
    return dataset_spec, chart_intent, DataValidationReport(is_valid=True, reason="OK")
