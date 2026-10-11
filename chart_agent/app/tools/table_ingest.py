"""
Table ingest: deterministic parsing, profiling, and execution of agent-produced
table visualization plans.

Flow:
1. Parse CSV/TSV/semicolon-delimited text into a DataFrame.
2. Profile columns for agent context.
3. Let the agent choose a compact TableAnalysisPlan.
4. Deterministically execute the plan with pandas.
5. Produce a transformed DatasetSpec + ChartIntent for the chart agent.
"""
from __future__ import annotations

import csv
import re
import warnings
from io import StringIO
from typing import Literal

import pandas as pd

from app.api.schemas import (
    AnalyticalGoal,
    ChartIntent,
    DataFieldRole,
    DataFieldSpec,
    DataPoint,
    DataValidationReport,
    DatasetSpec,
    TableAggregation,
    TableAnalysisPlan,
    TimeGranularity,
)

ColumnType = Literal["numeric", "temporal", "categorical", "text"]

_DATE_PATTERN = re.compile(
    r"""
    ^\d{4}-\d{2}-\d{2}
    | ^\d{2}[./-]\d{2}[./-]\d{4}
    | ^\d{4}/\d{2}/\d{2}
    | ^\d{4}-\d{2}$
    """,
    re.VERBOSE,
)
# NB: голое четырехзначное число сюда сознательно не входит. Иначе колонка сумм
# (1000-9999) целиком распознается как даты. Годы ловит отдельная эвристика
# _looks_like_year с более строгим порогом.

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


def _sniff_separator(raw: str) -> str:
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        if dialect.delimiter:
            return dialect.delimiter
    except csv.Error:
        pass

    first_line = raw.splitlines()[0] if raw.splitlines() else raw
    if "\t" in first_line:
        return "\t"
    if ";" in first_line:
        return ";"
    return ","


def parse_table(raw: str) -> pd.DataFrame:
    stripped = raw.strip()
    if not stripped:
        raise ValueError("Пустые входные данные таблицы.")

    sep = _sniff_separator(stripped)
    df = pd.read_csv(
        StringIO(stripped),
        sep=sep,
        keep_default_na=True,
    )
    df.columns = [str(c).strip() for c in df.columns]
    return df


# Types reported by the database, mapped onto the internal vocabulary.
# `string` and `unknown` are left to inference on purpose: the database knows
# a column is text, but not whether it reads as a category or free text.
_DB_TYPE_TO_INTERNAL: dict[str, str] = {
    "datetime": "temporal",
    "number": "numeric",
    "boolean": "categorical",
}


# NB: no ASCII-only pattern here. Python identifiers are unicode-aware, and a
# column named "город" is perfectly addressable as df["город"] — mangling it to
# col_0 would put a lie on the chart axis.


def _safe_column_name(raw: str, taken: set[str], index: int) -> str:
    """Turn a SQL result column into a name generated pandas code can address.

    A plain column (`Country`) is left alone. An unaliased expression is not:
    SQLite names such a column after the expression itself, so the LLM would
    have to write `df["STRFTIME('%Y', OperationalFrom)"]` — nested quotes,
    parentheses and a percent sign inside generated code. That breaks, and it
    also makes a poor axis label.

    The original SQL is shown to the user separately, so renaming here costs
    no traceability.
    """
    name = (raw or "").strip()
    if name.isidentifier() and name not in taken:
        return name

    cleaned = re.sub(r"\W+", "_", name, flags=re.UNICODE).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"col_{index}" if not cleaned else f"col_{cleaned}"

    candidate, suffix = cleaned, 2
    while candidate in taken:
        candidate = f"{cleaned}_{suffix}"
        suffix += 1
    return candidate


def dataframe_from_result_table(table: dict) -> tuple[pd.DataFrame, dict[str, str]]:
    """Build a DataFrame from a sql_agent result table (columns + rows).

    Returns the frame plus authoritative column types. Those types come from
    the database and override `infer_column_type` for this path: guessing a
    type from values is inherently ambiguous (a four-digit number is a year or
    an amount depending on the column), and here there is nothing to guess.
    """
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    if not columns:
        raise ValueError("Ответ сервиса данных не содержит колонок.")

    names: list[str] = []
    taken: set[str] = set()
    for idx, column in enumerate(columns):
        name = _safe_column_name(str(column.get("name", "")), taken, idx)
        taken.add(name)
        names.append(name)

    df = pd.DataFrame(rows, columns=names)

    declared: dict[str, str] = {}
    for column, name in zip(columns, names):
        db_type = str(column.get("type") or "unknown").lower()
        internal = _DB_TYPE_TO_INTERNAL.get(db_type)
        if internal is None:
            # Numbers stored as TEXT (common in Spider/PAUQ schemas): treat them
            # as numeric when every non-empty value parses, otherwise leave the
            # column to the generic inference.
            non_empty = [
                v for v in df[name].tolist()
                if v is not None and str(v).strip().lower() not in {"", "null", "none", "nan", "n/a", "-"}
            ]
            if non_empty and all(_is_numeric(v) for v in non_empty):
                internal = "numeric"
            else:
                continue
        declared[name] = internal
        if internal == "numeric":
            df[name] = pd.to_numeric(df[name], errors="coerce")
        elif internal == "temporal":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                df[name] = pd.to_datetime(df[name], errors="coerce")

    return df, declared


def _is_numeric(value: str) -> bool:
    try:
        float(str(value).replace(",", ".").replace(" ", ""))
        return True
    except ValueError:
        return False


def _looks_like_date(value: str) -> bool:
    return bool(_DATE_PATTERN.match(str(value).strip()))


def _looks_like_year(value: str) -> bool:
    try:
        year = int(str(value).strip())
        return 1900 <= year <= 2100
    except ValueError:
        return False


def infer_column_type(series: pd.Series) -> ColumnType:
    non_empty = series[series != ""].dropna()
    if len(non_empty) == 0:
        return "text"

    date_hint_count = sum(1 for value in non_empty if _looks_like_date(value))
    year_count = sum(1 for value in non_empty if _looks_like_year(value))
    if date_hint_count / len(non_empty) >= 0.7 or year_count / len(non_empty) >= 0.8:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                pd.to_datetime(non_empty)
            return "temporal"
        except Exception:
            pass

    numeric_count = sum(1 for value in non_empty if _is_numeric(value))
    if numeric_count / len(non_empty) >= 0.8:
        return "numeric"

    cardinality = non_empty.nunique()
    ratio = cardinality / len(non_empty)
    if ratio <= 0.5 or cardinality <= 20:
        return "categorical"
    return "text"


def infer_column_roles(
    df: pd.DataFrame,
    col_types: dict[str, ColumnType],
) -> dict[str, DataFieldRole]:
    roles: dict[str, DataFieldRole] = {}
    category_assigned = False

    for col in df.columns:
        column_type = col_types[col]
        if column_type == "temporal":
            roles[col] = DataFieldRole.time
        elif column_type == "numeric":
            roles[col] = DataFieldRole.value
        elif column_type == "categorical":
            if not category_assigned:
                roles[col] = DataFieldRole.category
                category_assigned = True
            else:
                roles[col] = DataFieldRole.series
        elif column_type == "text":
            roles[col] = DataFieldRole.text
        else:
            roles[col] = DataFieldRole.unknown

    return roles


def detect_ambiguous_columns(
    col_types: dict[str, ColumnType],
    col_roles: dict[str, DataFieldRole],
) -> list[str]:
    has_axis = any(role in (DataFieldRole.category, DataFieldRole.time) for role in col_roles.values())
    numeric_value_cols = [name for name, role in col_roles.items() if role == DataFieldRole.value]
    if not has_axis and len(numeric_value_cols) >= 3:
        return numeric_value_cols

    categorical_cols = [name for name, col_type in col_types.items() if col_type == "categorical"]
    if len(categorical_cols) >= 3:
        return categorical_cols

    return []


def _df_to_markdown(df: pd.DataFrame) -> str:
    headers = list(df.columns)
    str_rows = [[str(v) for v in row] for row in df.values.tolist()]
    col_widths = [len(h) for h in headers]
    for row in str_rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    def fmt(values: list[str]) -> str:
        return "| " + " | ".join(v.ljust(col_widths[i]) for i, v in enumerate(values)) + " |"

    separator = "| " + " | ".join("-" * w for w in col_widths) + " |"
    lines = [fmt(headers), separator, *[fmt(r) for r in str_rows]]
    return "\n".join(lines)


def _df_info_str(df: pd.DataFrame) -> str:
    header = f"{len(df)} строк, {len(df.columns)} колонок\n"
    header += f"{'#':<4} {'Колонка':<30} {'Непустых':<12} Dtype\n"
    header += f"{'---':<4} {'-------':<30} {'--------':<12} -----"
    lines = [header]
    for i, col in enumerate(df.columns):
        non_empty = int(df[col].notna().sum())
        dtype = str(df[col].dtype)
        lines.append(f"{i:<4} {col:<30} {non_empty:<12} {dtype}")
    return "\n".join(lines)


def build_table_prompt_context(df: pd.DataFrame) -> dict[str, object]:
    preview_df = df.head(5)
    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "df_info": _df_info_str(df),
        "md_preview": _df_to_markdown(preview_df),
    }


def _match_column_name(name: str | None, available_columns: list[str]) -> str | None:
    if not name:
        return None

    stripped = str(name).strip()
    if stripped in available_columns:
        return stripped

    lowered = stripped.casefold()
    for column in available_columns:
        if column.casefold() == lowered:
            return column

    return None


def _to_numeric_series(series: pd.Series) -> pd.Series:
    normalized = series.map(lambda value: str(value).replace(",", ".").replace(" ", ""))
    return pd.to_numeric(normalized, errors="coerce")


def _to_datetime_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _bucket_time(series: pd.Series, granularity: TimeGranularity) -> pd.Series:
    dt = _to_datetime_series(series)
    if dt.isna().all():
        raise ValueError("Не удалось распознать временную колонку для группировки.")

    if granularity == TimeGranularity.day:
        return dt.dt.strftime("%Y-%m-%d")
    if granularity == TimeGranularity.week:
        return dt.dt.to_period("W").astype(str)
    if granularity == TimeGranularity.month:
        return dt.dt.to_period("M").astype(str)
    if granularity == TimeGranularity.quarter:
        return dt.dt.to_period("Q").astype(str)
    if granularity == TimeGranularity.year:
        return dt.dt.year.astype("Int64").astype(str)

    return dt.dt.strftime("%Y-%m-%d")


def _resolve_aggregation(
    plan: TableAnalysisPlan,
    working_df: pd.DataFrame,
    dimension_column: str | None,
    series_column: str | None,
    y_columns: list[str],
) -> tuple[TableAggregation, bool]:
    if plan.aggregation != TableAggregation.none:
        return plan.aggregation, False

    if dimension_column is None:
        return TableAggregation.none, False

    duplicate_subset = [dimension_column]
    if series_column:
        duplicate_subset.append(series_column)
    duplicate_key_exists = working_df.duplicated(subset=duplicate_subset).any()

    if not duplicate_key_exists and len(y_columns) <= 1:
        return TableAggregation.none, False

    if y_columns:
        return TableAggregation.sum, True
    return TableAggregation.count, True


def _aggregation_name(aggregation: TableAggregation) -> str:
    return {
        TableAggregation.sum: "sum",
        TableAggregation.avg: "mean",
        TableAggregation.count: "count",
        TableAggregation.min: "min",
        TableAggregation.max: "max",
        TableAggregation.median: "median",
        TableAggregation.none: "none",
    }[aggregation]


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


def _build_fields_for_transformed_dataset(
    x_column: str | None,
    x_type: str | None,
    uses_series: bool,
    measure_label: str,
    preview_rows: list[dict[str, str | float | None]],
) -> list[DataFieldSpec]:
    fields: list[DataFieldSpec] = []
    if x_column:
        x_role = DataFieldRole.time if x_type == "temporal" else DataFieldRole.category
        x_samples = [str(row.get("x")) for row in preview_rows if row.get("x") is not None][:4]
        fields.append(
            DataFieldSpec(
                name=x_column,
                role=x_role,
                inferred_type=x_type or "categorical",
                unique_count=None,
                non_empty_count=None,
                sample_values=x_samples,
            )
        )
    if uses_series:
        series_samples = [str(row.get("series")) for row in preview_rows if row.get("series")][:4]
        fields.append(
            DataFieldSpec(
                name="series",
                role=DataFieldRole.series,
                inferred_type="categorical",
                unique_count=None,
                non_empty_count=None,
                sample_values=series_samples,
            )
        )
    y_samples = [str(row.get("y")) for row in preview_rows if row.get("y") is not None][:4]
    fields.append(
        DataFieldSpec(
            name=measure_label,
            role=DataFieldRole.value,
            inferred_type="numeric",
            unique_count=None,
            non_empty_count=None,
            sample_values=y_samples,
        )
    )
    return fields


def _build_chart_intent(plan: TableAnalysisPlan, title_hint: str) -> ChartIntent:
    chart_type = plan.chart_type
    chart_type_value = chart_type.value if chart_type is not None else None
    goal = GOAL_BY_CHART_TYPE.get(chart_type_value or "", AnalyticalGoal.unknown)
    return ChartIntent(
        analytical_goal=goal,
        recommended_chart_type=chart_type,
        title_hint=title_hint,
        reasoning=plan.reasoning,
    )


def _default_title(
    plan: TableAnalysisPlan,
    x_column: str | None,
    y_columns: list[str],
) -> str:
    if plan.title_hint.strip():
        return plan.title_hint.strip()
    _ = x_column, y_columns
    return ""


def _validate_plan_columns(
    plan: TableAnalysisPlan,
    available_columns: list[str],
) -> tuple[str | None, list[str], str | None]:
    x_column = _match_column_name(plan.x_column, available_columns)
    if plan.x_column and x_column is None:
        raise ValueError(f"Колонка '{plan.x_column}' не найдена в таблице.")

    y_columns: list[str] = []
    for raw_name in plan.y_columns:
        matched = _match_column_name(raw_name, available_columns)
        if matched is None:
            raise ValueError(f"Колонка '{raw_name}' не найдена в таблице.")
        if matched not in y_columns:
            y_columns.append(matched)

    series_column = _match_column_name(plan.series_column, available_columns)
    if plan.series_column and series_column is None:
        raise ValueError(f"Колонка '{plan.series_column}' не найдена в таблице.")

    return x_column, y_columns, series_column


def execute_table_plan(
    df: pd.DataFrame,
    plan: TableAnalysisPlan,
) -> tuple[DatasetSpec, ChartIntent, DataValidationReport]:
    chart_type = plan.chart_type.value if plan.chart_type is not None else None
    if plan.needs_clarification:
        validation = DataValidationReport(
            is_valid=False,
            reason=plan.clarification_question.strip() or "Нужно уточнение по таблице.",
            correction_hint=plan.clarification_question.strip() or "Уточните, какие колонки использовать.",
        )
        return DatasetSpec(source_type="csv"), ChartIntent(), validation

    if not chart_type:
        validation = DataValidationReport(
            is_valid=False,
            reason="Агент не определил тип графика для таблицы.",
            correction_hint="Уточните желаемый тип графика или цель визуализации.",
        )
        return DatasetSpec(source_type="csv"), ChartIntent(), validation

    available_columns = list(df.columns)
    col_types = {col: infer_column_type(df[col]) for col in available_columns}

    try:
        x_column, y_columns, series_column = _validate_plan_columns(plan, available_columns)
    except ValueError as exc:
        validation = DataValidationReport(
            is_valid=False,
            reason=str(exc),
            correction_hint="Проверьте названия колонок в запросе.",
        )
        return DatasetSpec(source_type="csv"), ChartIntent(), validation

    working_df = df.copy()
    if x_column and plan.time_granularity != TimeGranularity.none:
        if col_types.get(x_column) != "temporal":
            validation = DataValidationReport(
                is_valid=False,
                reason=f"Колонка '{x_column}' не является временной, но запрошена time_granularity.",
                correction_hint="Выберите временную колонку или уберите time_granularity.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation
        working_df["__dimension__"] = _bucket_time(working_df[x_column], plan.time_granularity)
        dimension_column = "__dimension__"
        dimension_type = "temporal"
    else:
        dimension_column = x_column
        dimension_type = col_types.get(x_column) if x_column else None

    title_hint = _default_title(plan, x_column, y_columns)

    # Distribution charts
    if chart_type in {"histogram", "box"}:
        if not y_columns:
            validation = DataValidationReport(
                is_valid=False,
                reason=f"Для графика типа '{chart_type}' нужна хотя бы одна числовая колонка.",
                correction_hint="Укажите числовую колонку, например: 'построй гистограмму по cost'.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation

        points: list[DataPoint] = []
        for column_name in y_columns:
            if col_types.get(column_name) != "numeric":
                validation = DataValidationReport(
                    is_valid=False,
                    reason=f"Колонка '{column_name}' не является числовой.",
                    correction_hint="Для histogram/box выберите числовую колонку.",
                )
                return DatasetSpec(source_type="csv"), ChartIntent(), validation
            numeric_series = _to_numeric_series(working_df[column_name]).dropna()
            if numeric_series.empty:
                validation = DataValidationReport(
                    is_valid=False,
                    reason=f"В колонке '{column_name}' нет корректных числовых значений.",
                    correction_hint="Проверьте содержимое числовой колонки.",
                )
                return DatasetSpec(source_type="csv"), ChartIntent(), validation
            multi_series = len(y_columns) > 1
            for value in numeric_series.tolist():
                points.append(
                    DataPoint(
                        y=float(value),
                        series=column_name if multi_series else None,
                    )
                )

        preview_rows = _build_preview_from_points(points)
        measure_label = y_columns[0] if len(y_columns) == 1 else "value"
        dataset_spec = DatasetSpec(
            source_type="csv",
            raw_representation=_format_raw_representation(preview_rows),
            fields=_build_fields_for_transformed_dataset(
                x_column=None,
                x_type=None,
                uses_series=len(y_columns) > 1,
                measure_label=measure_label,
                preview_rows=preview_rows,
            ),
            points=points,
            row_count_estimate=len(points),
            preview_rows=preview_rows,
            notes=[
                f"source_columns={', '.join(available_columns)}",
                f"chart_type={chart_type}",
                f"selected_value_columns={', '.join(y_columns)}",
            ],
        )
        chart_intent = _build_chart_intent(plan, title_hint)
        return dataset_spec, chart_intent, DataValidationReport(is_valid=True, reason="OK")

    # Scatter
    if chart_type == "scatter":
        if not x_column or not y_columns:
            validation = DataValidationReport(
                is_valid=False,
                reason="Для scatter нужны x_column и одна числовая y_column.",
                correction_hint="Укажите две числовые колонки, например: 'scatter cost vs revenue'.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation
        if col_types.get(x_column) != "numeric" or col_types.get(y_columns[0]) != "numeric":
            validation = DataValidationReport(
                is_valid=False,
                reason="Для scatter обе оси должны быть числовыми.",
                correction_hint="Выберите две числовые колонки для scatter.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation

        x_values = _to_numeric_series(working_df[x_column])
        y_values = _to_numeric_series(working_df[y_columns[0]])
        points: list[DataPoint] = []
        for idx in range(len(working_df)):
            x_value = x_values.iloc[idx]
            y_value = y_values.iloc[idx]
            if pd.isna(x_value) or pd.isna(y_value):
                continue
            series_value = None
            if series_column:
                raw_series = str(working_df.iloc[idx][series_column]).strip()
                series_value = raw_series or None
            points.append(
                DataPoint(
                    x=float(x_value),
                    y=float(y_value),
                    series=series_value,
                )
            )

        if not points:
            validation = DataValidationReport(
                is_valid=False,
                reason="Не удалось собрать ни одной валидной точки для scatter.",
                correction_hint="Проверьте числовые значения выбранных колонок.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation

        preview_rows = _build_preview_from_points(points)
        dataset_spec = DatasetSpec(
            source_type="csv",
            raw_representation=_format_raw_representation(preview_rows),
            fields=_build_fields_for_transformed_dataset(
                x_column=x_column,
                x_type="numeric",
                uses_series=bool(series_column),
                measure_label=y_columns[0],
                preview_rows=preview_rows,
            ),
            points=points,
            row_count_estimate=len(points),
            preview_rows=preview_rows,
            notes=[
                f"source_columns={', '.join(available_columns)}",
                f"chart_type={chart_type}",
                f"x_column={x_column}",
                f"y_column={y_columns[0]}",
                f"series_column={series_column or ''}",
            ],
        )
        chart_intent = _build_chart_intent(plan, title_hint)
        return dataset_spec, chart_intent, DataValidationReport(is_valid=True, reason="OK")

    # Comparative / time-series charts
    if chart_type in {"pie", "doughnut"} and (series_column or len(y_columns) > 1):
        validation = DataValidationReport(
            is_valid=False,
            reason=f"График типа '{chart_type}' поддерживает только одну метрику без series_column.",
            correction_hint="Выберите одну числовую колонку или используйте bar/stacked_bar.",
        )
        return DatasetSpec(source_type="csv"), ChartIntent(), validation

    if dimension_column is None:
        validation = DataValidationReport(
            is_valid=False,
            reason=f"Для графика типа '{chart_type}' нужна x/category/time колонка.",
            correction_hint="Укажите, по какой колонке нужно строить график.",
        )
        return DatasetSpec(source_type="csv"), ChartIntent(), validation

    for column_name in y_columns:
        if col_types.get(column_name) != "numeric":
            validation = DataValidationReport(
                is_valid=False,
                reason=f"Колонка '{column_name}' не является числовой.",
                correction_hint="Выберите числовую метрику для оси Y.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation
        working_df[column_name] = _to_numeric_series(working_df[column_name])

    effective_aggregation, aggregation_was_inferred = _resolve_aggregation(
        plan=plan,
        working_df=working_df,
        dimension_column=dimension_column,
        series_column=series_column,
        y_columns=y_columns,
    )

    group_columns = [dimension_column]
    if series_column:
        group_columns.append(series_column)

    points: list[DataPoint] = []
    if effective_aggregation == TableAggregation.count and not y_columns:
        aggregated = (
            working_df.groupby(group_columns, dropna=False)
            .size()
            .reset_index(name="__count__")
        )
        for _, row in aggregated.iterrows():
            dimension_value = row[dimension_column]
            series_value = str(row[series_column]).strip() if series_column else None
            points.append(
                DataPoint(
                    label=str(dimension_value),
                    x=str(dimension_value),
                    y=float(row["__count__"]),
                    series=series_value or None,
                )
            )
        measure_label = "count"
    elif effective_aggregation == TableAggregation.none:
        if not y_columns:
            validation = DataValidationReport(
                is_valid=False,
                reason="Для построения графика не выбрана числовая метрика.",
                correction_hint="Укажите числовую колонку или запросите count по категории.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation

        required_columns = [dimension_column, *y_columns]
        if series_column:
            required_columns.append(series_column)
        numeric_rows = working_df[required_columns].dropna(subset=y_columns)
        for _, row in numeric_rows.iterrows():
            dimension_value = row[dimension_column]
            if series_column:
                series_base = str(row[series_column]).strip()
                if len(y_columns) == 1:
                    points.append(
                        DataPoint(
                            label=str(dimension_value),
                            x=str(dimension_value),
                            y=float(row[y_columns[0]]),
                            series=series_base or None,
                        )
                    )
                else:
                    for metric_name in y_columns:
                        points.append(
                            DataPoint(
                                label=str(dimension_value),
                                x=str(dimension_value),
                                y=float(row[metric_name]),
                                series=f"{series_base} · {metric_name}",
                            )
                        )
            elif len(y_columns) > 1:
                for metric_name in y_columns:
                    points.append(
                        DataPoint(
                            label=str(dimension_value),
                            x=str(dimension_value),
                            y=float(row[metric_name]),
                            series=metric_name,
                        )
                    )
            else:
                points.append(
                    DataPoint(
                        label=str(dimension_value),
                        x=str(dimension_value),
                        y=float(row[y_columns[0]]),
                    )
                )
        measure_label = y_columns[0] if len(y_columns) == 1 else "value"
    else:
        if not y_columns:
            validation = DataValidationReport(
                is_valid=False,
                reason="Не выбрана числовая метрика для агрегации.",
                correction_hint="Укажите числовую колонку или запросите count по категории.",
            )
            return DatasetSpec(source_type="csv"), ChartIntent(), validation
        agg_name = _aggregation_name(effective_aggregation)
        aggregated = (
            working_df.groupby(group_columns, dropna=False)[y_columns]
            .agg(agg_name)
            .reset_index()
        )
        for _, row in aggregated.iterrows():
            dimension_value = row[dimension_column]
            if series_column:
                series_base = str(row[series_column]).strip()
                for metric_name in y_columns:
                    point_series = series_base
                    if len(y_columns) > 1:
                        point_series = f"{series_base} · {metric_name}"
                    points.append(
                        DataPoint(
                            label=str(dimension_value),
                            x=str(dimension_value),
                            y=float(row[metric_name]),
                            series=point_series,
                        )
                    )
            elif len(y_columns) > 1:
                for metric_name in y_columns:
                    points.append(
                        DataPoint(
                            label=str(dimension_value),
                            x=str(dimension_value),
                            y=float(row[metric_name]),
                            series=metric_name,
                        )
                    )
            else:
                points.append(
                    DataPoint(
                        label=str(dimension_value),
                        x=str(dimension_value),
                        y=float(row[y_columns[0]]),
                    )
                )
        measure_label = y_columns[0] if len(y_columns) == 1 else "value"

    if not points:
        validation = DataValidationReport(
            is_valid=False,
            reason="После применения плана не осталось данных для построения графика.",
            correction_hint="Уточните колонки, тип графика или агрегацию.",
        )
        return DatasetSpec(source_type="csv"), ChartIntent(), validation

    preview_rows = _build_preview_from_points(points)
    uses_series = any(point.series for point in points)
    notes = [
        f"source_columns={', '.join(available_columns)}",
        f"chart_type={chart_type}",
        f"x_column={x_column or ''}",
        f"y_columns={', '.join(y_columns)}",
        f"series_column={series_column or ''}",
        f"aggregation={effective_aggregation.value}",
    ]
    if plan.time_granularity != TimeGranularity.none:
        notes.append(f"time_granularity={plan.time_granularity.value}")
    if aggregation_was_inferred:
        notes.append("aggregation_inferred=true")

    dataset_spec = DatasetSpec(
        source_type="csv",
        raw_representation=_format_raw_representation(preview_rows),
        fields=_build_fields_for_transformed_dataset(
            x_column=x_column,
            x_type=dimension_type,
            uses_series=uses_series,
            measure_label=measure_label,
            preview_rows=preview_rows,
        ),
        points=points,
        row_count_estimate=len(points),
        preview_rows=preview_rows,
        notes=notes,
    )
    chart_intent = _build_chart_intent(plan, title_hint)
    return dataset_spec, chart_intent, DataValidationReport(is_valid=True, reason="OK")
