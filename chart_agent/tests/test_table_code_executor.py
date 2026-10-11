import pandas as pd
import pytest

from app.api.schemas import TableCodeSpec
from app.tools.table_code_executor import (
    dataframe_to_dataset_spec,
    execute_code_safely,
    validate_result_dataframe,
)
from app.tools.table_ingest import parse_table

SAMPLE_CSV = "\n".join(
    [
        "order_date,region,channel,category,product,units,revenue,cost",
        "2025-01-05,North,Online,Electronics,Laptop,4,4800,3600",
        "2025-01-06,North,Retail,Electronics,Mouse,25,750,300",
        "2025-01-07,South,Online,Furniture,Desk,3,2100,1500",
        "2025-01-08,West,Partner,Electronics,Monitor,8,2400,1680",
        "2025-01-09,East,Retail,Office,Printer,5,1750,1200",
        "2025-02-02,North,Online,Office,Printer,6,2100,1440",
    ]
)


def test_execute_code_safely_builds_grouped_result() -> None:
    df = parse_table(SAMPLE_CSV)
    code = "\n".join(
        [
            "tmp = df.copy()",
            "tmp['revenue'] = pd.to_numeric(tmp['revenue'], errors='coerce')",
            "result = tmp.groupby('region', as_index=False)['revenue'].sum()",
            "result.columns = ['x', 'y']",
        ]
    )
    spec = TableCodeSpec(chart_type="bar", x_col="x", y_col="y", code=code)

    result_df = execute_code_safely(code, df)
    errors = validate_result_dataframe(result_df, spec)
    dataset_spec, chart_intent, validation = dataframe_to_dataset_spec(result_df, spec, list(df.columns))

    assert errors == []
    assert validation.is_valid is True
    assert chart_intent.recommended_chart_type == "bar"
    values_by_region = {point.label: point.y for point in dataset_spec.points}
    assert values_by_region == {
        "East": 1750.0,
        "North": 7650.0,
        "South": 2100.0,
        "West": 2400.0,
    }


def test_execute_code_safely_rejects_imports() -> None:
    df = pd.DataFrame({"value": [1]})

    with pytest.raises(ValueError, match="import"):
        execute_code_safely("import os\nresult = df", df)


def test_execute_code_safely_requires_result_dataframe() -> None:
    df = pd.DataFrame({"value": [1]})

    with pytest.raises(TypeError, match="pd.DataFrame"):
        execute_code_safely("result = 42", df)


def test_validate_result_dataframe_reports_non_numeric_y() -> None:
    result_df = pd.DataFrame({"x": ["A"], "y": ["not-a-number"]})
    spec = TableCodeSpec(chart_type="bar", x_col="x", y_col="y")

    assert validate_result_dataframe(result_df, spec) == [
        "колонка y_col 'y' не содержит ни одного числового значения (все NaN после приведения)"
    ]
