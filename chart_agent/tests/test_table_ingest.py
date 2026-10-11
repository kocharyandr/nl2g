from app.api.schemas import TableAggregation, TableAnalysisPlan
from app.tools.table_ingest import execute_table_plan, infer_column_type, parse_table


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


def test_execute_table_plan_builds_histogram_dataset() -> None:
    df = parse_table(SAMPLE_CSV)
    plan = TableAnalysisPlan(
        chart_type="histogram",
        y_columns=["cost"],
        aggregation=TableAggregation.none,
        title_hint="Cost distribution",
        reasoning="histogram by cost",
    )

    dataset_spec, chart_intent, validation = execute_table_plan(df, plan)

    assert validation.is_valid is True
    assert chart_intent.recommended_chart_type == "histogram"
    assert len(dataset_spec.points) == 6
    assert all(point.series is None for point in dataset_spec.points)
    assert dataset_spec.points[0].y == 3600.0


def test_execute_table_plan_aggregates_revenue_by_region() -> None:
    df = parse_table(SAMPLE_CSV)
    plan = TableAnalysisPlan(
        chart_type="bar",
        x_column="region",
        y_columns=["revenue"],
        aggregation=TableAggregation.sum,
        title_hint="Revenue by region",
        reasoning="sum revenue by region",
    )

    dataset_spec, chart_intent, validation = execute_table_plan(df, plan)

    assert validation.is_valid is True
    assert chart_intent.recommended_chart_type == "bar"
    values_by_region = {point.label: point.y for point in dataset_spec.points}
    assert values_by_region == {
        "East": 1750.0,
        "North": 7650.0,
        "South": 2100.0,
        "West": 2400.0,
    }


def test_four_digit_amounts_are_numeric_not_temporal() -> None:
    """Регрессия: колонка сумм 1000-9999 не должна распознаваться как даты.

    Раньше _DATE_PATTERN содержал альтернативу ^\\d{4}$, из-за чего любое
    четырехзначное число считалось датой и колонка выручки уезжала в temporal,
    а построение падало на валидации "колонка не является числовой".
    """
    df = parse_table(SAMPLE_CSV)

    assert infer_column_type(df["revenue"]) == "numeric"
    assert infer_column_type(df["cost"]) == "numeric"
    assert infer_column_type(df["units"]) == "numeric"
    # Настоящие даты по-прежнему распознаются.
    assert infer_column_type(df["order_date"]) == "temporal"


def test_year_column_is_still_temporal() -> None:
    df = parse_table("year,amount\n2019,4800\n2020,5100\n2021,4300\n2022,6200")

    assert infer_column_type(df["year"]) == "temporal"
    assert infer_column_type(df["amount"]) == "numeric"
