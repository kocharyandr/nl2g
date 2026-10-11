import base64
import io
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import routes_sessions
from app.api.schemas import (
    AnalyticalGoal,
    ChartIntent,
    DataFieldSpec,
    DataPoint,
    DatasetSpec,
    DataUnderstandingResult,
    DataValidationReport,
    TableCodeSpec,
)
from app.api.state_store import STATE
from app.core.config import settings
from app.domain import StageName
from app.graph.node_schemas.image_generation_validator import (
    ImageGenerationValidationResult,
)
from app.graph.node_schemas.interaction_node import (
    InteractionAction,
    InteractionDecision,
)
from app.graph.node_schemas.summarizing_node import SummaryAnswer
from app.main import app


@pytest.fixture()
def sample_png_base64() -> str:
    img = Image.new("RGB", (4, 4), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture()
def sample_csv_data() -> str:
    return "\n".join(
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


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    STATE.clear()
    monkeypatch.setattr(settings, "edit_use_stub", True)
    monkeypatch.setattr(settings, "image_auto_validation_enabled", True)
    monkeypatch.setattr(settings, "image_auto_validation_iters", 2)

    async def interaction_run(user_input: str, context: dict | None = None) -> InteractionDecision:
        _ = context
        text = (user_input or "").lower()
        if "изображ" in text or "картин" in text:
            return InteractionDecision(
                action=InteractionAction.route_to_stage,
                target_stage=StageName.image_generation,
                reason="image edit request",
            )
        return InteractionDecision(
            action=InteractionAction.route_to_stage,
            target_stage=StageName.data_parsing,
            reason="chart request",
        )

    async def data_parser_run(
        user_input: str,
        agent_type: str,
        context=None,
        target_plot_type: str | None = None,
    ):
        _ = user_input, context, target_plot_type
        if agent_type == "parser":
            return DataUnderstandingResult(
                dataset_spec=DatasetSpec(
                    source_type="text",
                    raw_representation="A=10 B=20 C=15",
                    fields=[
                        DataFieldSpec(name="dimension", role="category", inferred_type="string"),
                        DataFieldSpec(name="value", role="value", inferred_type="float"),
                    ],
                    points=[
                        DataPoint(label="A", y=10),
                        DataPoint(label="B", y=20),
                        DataPoint(label="C", y=15),
                    ],
                ),
                chart_intent=ChartIntent(
                    analytical_goal=AnalyticalGoal.comparison,
                    recommended_chart_type="bar",
                    title_hint="Unit Test Chart",
                    reasoning="synthetic test fixture",
                ),
            )
        if agent_type == "validator":
            return DataValidationReport(
                is_valid=True,
                reason="",
                correction_hint="",
            )
        if agent_type == "table_code_generator":
            lowered = (user_input or "").lower()
            if "гистограмм" in lowered or "histogram" in lowered:
                return TableCodeSpec(
                    chart_type="histogram",
                    y_col="y",
                    code=(
                        "result = pd.DataFrame({"
                        "'y': pd.to_numeric(df['cost'], errors='coerce')"
                        "}).dropna()"
                    ),
                    title_hint="Cost distribution",
                    reasoning="histogram by cost",
                )
            if "region" in lowered and "revenue" in lowered:
                return TableCodeSpec(
                    chart_type="bar",
                    x_col="x",
                    y_col="y",
                    code=(
                        "tmp = df.copy()\n"
                        "tmp['revenue'] = pd.to_numeric(tmp['revenue'], errors='coerce')\n"
                        "result = tmp.groupby('region', as_index=False)['revenue'].sum()\n"
                        "result.columns = ['x', 'y']"
                    ),
                    title_hint="Revenue by region",
                    reasoning="sum revenue by region",
                )
            return TableCodeSpec(
                chart_type="bar",
                x_col="x",
                y_col="y",
                code=(
                    "tmp = df.copy()\n"
                    "tmp['revenue'] = pd.to_numeric(tmp['revenue'], errors='coerce')\n"
                    "result = tmp.groupby('region', as_index=False)['revenue'].sum()\n"
                    "result.columns = ['x', 'y']"
                ),
                title_hint="Revenue by region",
                reasoning="fallback table plan",
            )
        raise ValueError(f"Unexpected agent_type: {agent_type}")

    async def plot_run(data: dict) -> dict:
        chart_type = data.get("chart_type", "bar")
        points = data.get("points", data.get("dataset_spec", {}).get("points", []))
        title = data.get("title", "Unit Test Chart")

        labels = [str(p["label"]) for p in points if p.get("label") is not None]
        values = [float(p["y"]) for p in points if p.get("y") is not None]

        if not labels:
            labels = ["A", "B", "C"]
        if not values:
            values = [10, 20, 15]

        code = f"""
labels = {labels!r}
values = {values!r}
fig, ax = plt.subplots(figsize=(9, 5))
ax.bar(labels, values, color='steelblue', alpha=0.85)
ax.set_title({title!r})
fig.tight_layout()
"""
        return {"code": code}

    async def sumup_run(summary) -> SummaryAnswer:
        return SummaryAnswer(
            current_summary=f"summary size={len(list(summary.last_messeges_for_sumup))}"
        )

    async def image_validator_run(**kwargs) -> ImageGenerationValidationResult:
        _ = kwargs
        return ImageGenerationValidationResult(
            ordering_preserved=1,
            element_count_preserved=1,
            positioning_preserved=1,
            scale_proportions_preserved=1,
            hallucinations_absent=1,
            analytical_integrity_preserved=1,
            edit_matches_request_and_reference_image=1,
            score=1.0,
            errors_summary="",
            key_issues=[],
        )

    async def llm_chat(messages: list[dict], temperature: float = 0.2, json_schema: dict | None = None):
        _ = messages, temperature, json_schema
        return '{"Rewritten":"Сделай изображение чище и контрастнее, сохрани текст и пропорции."}'

    monkeypatch.setattr(routes_sessions.registry.interaction, "run", interaction_run)
    monkeypatch.setattr(routes_sessions.registry.data_understanding, "run", data_parser_run)
    monkeypatch.setattr(routes_sessions.registry.plot_planner, "run", plot_run)
    monkeypatch.setattr(routes_sessions.registry.summary, "run", sumup_run)
    monkeypatch.setattr(
        routes_sessions.registry.image_critic,
        "run",
        image_validator_run,
    )
    monkeypatch.setattr(routes_sessions.registry.llm, "chat", llm_chat)

    with TestClient(app) as test_client:
        yield test_client

    STATE.clear()
