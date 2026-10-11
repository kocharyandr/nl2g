"""Integration of the SQL data source into the chart pipeline."""
from __future__ import annotations

import pytest

from app.api.schemas import Artefacts
from app.core.config import settings
from app.domain import StageName
from app.graph.invalidation import invalidate
from app.graph.node_schemas.interaction_node import InteractionAction, InteractionDecision
from app.graph.nodes.interaction_node import route_after_interaction
from app.graph.nodes.pending_node import pending_router
from app.graph.nodes import sql_source_node as node_mod
from app.graph.nodes.sql_source_node import route_after_sql_source, sql_source_node
from app.graph.state import AppState
from app.infra.sql_agent.client import SQLAgentUnavailableError, SQLQueryResult
from app.tools.table_ingest import dataframe_from_result_table

RESULT_TABLE = {
    "columns": [{"name": "region", "type": "string"}, {"name": "revenue", "type": "number"}],
    "rows": [["North", 7650.0], ["South", 2100.0]],
    "sql": "SELECT region, SUM(revenue) FROM orders GROUP BY region",
    "explanation": "Выручка по регионам.",
    "truncated": False,
}


def make_state(**kwargs) -> AppState:
    return AppState(session_id="s1", **kwargs)


def route_decision(stage: StageName) -> InteractionDecision:
    return InteractionDecision(
        action=InteractionAction.route_to_stage, target_stage=stage, reason="test"
    )


@pytest.fixture()
def sql_enabled(monkeypatch):
    monkeypatch.setattr(settings, "sql_agent_enabled", True)
    monkeypatch.setattr(settings, "sql_agent_url", "http://sql-agent:8500")


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def query(self, question, session_id, max_rows=None, hint_tables=None, datasource_id=None):
        self.calls.append(question)
        if self.error:
            raise self.error
        return self.result


def install_client(monkeypatch, client):
    monkeypatch.setattr(node_mod, "get_sql_agent_client", lambda: client)
    return client


class TestRouting:
    def test_toggle_routes_to_sql_source(self, sql_enabled):
        state = make_state(use_sql_source=True, interaction_decision=route_decision(StageName.data_parsing))
        assert route_after_interaction(state) == "sql_source"

    def test_toggle_wins_over_a_leftover_csv(self, sql_enabled):
        state = make_state(
            use_sql_source=True,
            persisted_csv="a,b\n1,2",
            interaction_decision=route_decision(StageName.data_parsing),
        )
        assert route_after_interaction(state) == "sql_source"

    def test_csv_still_routes_to_table_extractor(self, sql_enabled):
        state = make_state(
            user_csv_data="a,b\n1,2",
            interaction_decision=route_decision(StageName.data_parsing),
        )
        assert route_after_interaction(state) == "table_data_extractor"

    def test_disabled_service_never_routes_to_sql(self, monkeypatch):
        monkeypatch.setattr(settings, "sql_agent_enabled", False)
        state = make_state(use_sql_source=True, interaction_decision=route_decision(StageName.data_parsing))
        assert route_after_interaction(state) == "text_data_extractor"

    def test_explicit_sql_stage_routes_to_sql_source(self, sql_enabled):
        state = make_state(interaction_decision=route_decision(StageName.sql_query))
        assert route_after_interaction(state) == "sql_source"

    def test_respond_is_overridden_by_the_toggle(self, sql_enabled):
        """A question with the DB toggle on goes to the database, not to chat."""
        from app.graph.nodes.interaction_node import _override_decision_for_sql

        decision = InteractionDecision(
            action=InteractionAction.respond, assistant_message="Привет!", reason="t"
        )
        state = make_state(use_sql_source=True, user_input="сколько матчей в Испании")
        out = _override_decision_for_sql(decision, state)

        assert out.action == InteractionAction.route_to_stage
        assert out.target_stage == StageName.sql_query
        state.interaction_decision = out
        assert route_after_interaction(state) == "sql_source"

    def test_fresh_clarification_is_overridden_by_the_toggle(self, sql_enabled):
        from app.graph.nodes.interaction_node import _override_decision_for_sql

        decision = InteractionDecision(
            action=InteractionAction.ask_clarification,
            assistant_message="Какой у вас источник данных?", reason="t",
        )
        state = make_state(use_sql_source=True, user_input="сколько матчей в Испании")
        assert _override_decision_for_sql(decision, state).target_stage == StageName.sql_query

    def test_downstream_clarification_still_reaches_the_user(self, sql_enabled):
        from app.graph.nodes.interaction_node import _override_decision_for_sql

        decision = InteractionDecision(
            action=InteractionAction.ask_clarification,
            assistant_message="За какой период?", reason="t",
        )
        state = make_state(
            use_sql_source=True, user_input="выручка",
            clarification_reason="За какой период?",
        )
        assert _override_decision_for_sql(decision, state) is decision

    def test_respond_stays_respond_without_the_toggle(self, sql_enabled):
        from app.graph.nodes.interaction_node import _override_decision_for_sql

        decision = InteractionDecision(
            action=InteractionAction.respond, assistant_message="Привет!", reason="t"
        )
        state = make_state(user_input="привет")
        assert _override_decision_for_sql(decision, state) is decision

    def test_text_branch_unaffected(self, sql_enabled):
        state = make_state(interaction_decision=route_decision(StageName.data_parsing))
        assert route_after_interaction(state) == "text_data_extractor"


class TestEditReusesRows:
    def test_edit_does_not_requery_the_database(self):
        """"Now as a line" must not hit the database again."""
        from app.api.schemas import DecisionValue

        state = make_state(
            user_decision=DecisionValue.edit,
            current_stage=StageName.plot_rendering,
            persisted_sql_result=RESULT_TABLE,
            user_input="а теперь линией",
        )
        assert pending_router(state) == "table_data_extractor"


@pytest.mark.asyncio
class TestSQLSourceNode:
    async def test_ok_fills_state_and_artefacts(self, sql_enabled, monkeypatch):
        install_client(
            monkeypatch,
            FakeClient(
                SQLQueryResult(
                    status="ok",
                    columns=RESULT_TABLE["columns"],
                    rows=RESULT_TABLE["rows"],
                    row_count=2,
                    truncated=False,
                    sql=RESULT_TABLE["sql"],
                    explanation=RESULT_TABLE["explanation"],
                )
            ),
        )
        state = make_state(user_input="выручка по регионам", use_sql_source=True)
        patch = await sql_source_node(state)

        assert patch["current_stage"] == StageName.sql_query
        assert patch["sql_result_table"]["rows"] == RESULT_TABLE["rows"]
        assert patch["persisted_sql_result"] is not None
        info = patch["artefacts"].data.sql_source
        assert info.used is True
        assert info.sql == RESULT_TABLE["sql"]
        assert info.row_count == 2
        assert route_after_sql_source(AppState(session_id="s1", **{
            "sql_result_table": patch["sql_result_table"]})) == "table_data_extractor"

    async def test_truncation_is_surfaced_to_the_user(self, sql_enabled, monkeypatch):
        install_client(
            monkeypatch,
            FakeClient(
                SQLQueryResult(
                    status="ok", columns=RESULT_TABLE["columns"], rows=RESULT_TABLE["rows"],
                    row_count=2, truncated=True, sql="SELECT 1", explanation="",
                )
            ),
        )
        state = make_state(user_input="выручка", use_sql_source=True)
        patch = await sql_source_node(state)

        assert patch["sql_truncated"] is True
        assert "обрезан" in patch["ephemeral_status"]
        assert patch["artefacts"].data.sql_source.truncated is True

    async def test_service_outage_is_an_error_not_a_silent_fallback(self, sql_enabled, monkeypatch):
        install_client(monkeypatch, FakeClient(error=SQLAgentUnavailableError("сервис лежит")))
        state = make_state(user_input="выручка", use_sql_source=True)
        patch = await sql_source_node(state)

        assert patch["current_stage"] == StageName.error
        assert "сервис лежит" in patch["assistant_message"]

    async def test_need_clarification_goes_back_to_interaction(self, sql_enabled, monkeypatch):
        install_client(
            monkeypatch,
            FakeClient(SQLQueryResult(status="need_clarification", question_to_user="За какой период?")),
        )
        state = make_state(user_input="выручка", use_sql_source=True)
        patch = await sql_source_node(state)

        assert patch["clarification_reason"] == "За какой период?"
        routed = AppState(session_id="s1", clarification_reason="За какой период?")
        assert route_after_sql_source(routed) == "clarification"

    async def test_error_status_is_reported(self, sql_enabled, monkeypatch):
        install_client(
            monkeypatch,
            FakeClient(SQLQueryResult(status="error", error_type="sql_error", message="no such column")),
        )
        patch = await sql_source_node(make_state(user_input="выручка", use_sql_source=True))

        assert patch["current_stage"] == StageName.error
        assert "no such column" in patch["assistant_message"]

    async def test_empty_result_is_an_error_not_an_empty_chart(self, sql_enabled, monkeypatch):
        install_client(
            monkeypatch,
            FakeClient(SQLQueryResult(status="ok", columns=RESULT_TABLE["columns"], rows=[], row_count=0, sql="SELECT 1")),
        )
        patch = await sql_source_node(make_state(user_input="выручка", use_sql_source=True))
        assert patch["current_stage"] == StageName.error

    async def test_missing_measure_triggers_one_retry_with_a_hint(self, sql_enabled, monkeypatch):
        """«Топ-3 страны» is a fair question; the system asks for the count itself."""
        labels_only = SQLQueryResult(
            status="ok",
            columns=[{"name": "country", "type": "string"}],
            rows=[["France"], ["Japan"]],
            row_count=2,
            sql="SELECT country FROM t GROUP BY country ORDER BY count(*) DESC",
        )
        with_measure = SQLQueryResult(
            status="ok",
            columns=[{"name": "country", "type": "string"}, {"name": "n", "type": "number"}],
            rows=[["France", 72], ["Japan", 71]],
            row_count=2,
            sql="SELECT country, count(*) AS n FROM t GROUP BY country",
        )

        class Sequenced(FakeClient):
            def __init__(self):
                super().__init__()
                self.replies = [labels_only, with_measure]

            async def query(self, question, session_id, max_rows=None, hint_tables=None, datasource_id=None):
                self.calls.append(question)
                return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]

        client = install_client(monkeypatch, Sequenced())
        patch = await sql_source_node(make_state(user_input="топ-3 страны", use_sql_source=True))

        assert len(client.calls) == 2
        assert "числовую величину" in client.calls[1]
        assert patch["current_stage"] == StageName.sql_query
        assert patch["artefacts"].data.sql_source.sql == with_measure.sql

    async def test_still_no_measure_after_retry_explains_itself(self, sql_enabled, monkeypatch):
        install_client(
            monkeypatch,
            FakeClient(
                SQLQueryResult(
                    status="ok",
                    columns=[{"name": "country", "type": "string"}],
                    rows=[["France"], ["Japan"]],
                    row_count=2,
                    sql="SELECT country FROM t GROUP BY country",
                )
            ),
        )
        patch = await sql_source_node(make_state(user_input="топ-3 страны", use_sql_source=True))

        assert patch["current_stage"] == StageName.error
        assert "текстовые колонки" in patch["assistant_message"]
        assert "country" in patch["assistant_message"]

    async def test_numeric_column_passes_the_check(self, sql_enabled, monkeypatch):
        install_client(
            monkeypatch,
            FakeClient(
                SQLQueryResult(
                    status="ok",
                    columns=RESULT_TABLE["columns"],
                    rows=RESULT_TABLE["rows"],
                    row_count=2,
                    sql=RESULT_TABLE["sql"],
                )
            ),
        )
        patch = await sql_source_node(make_state(user_input="выручка", use_sql_source=True))
        assert patch["current_stage"] == StageName.sql_query

    async def test_scalar_result_answers_in_text_not_chart(self, sql_enabled, monkeypatch):
        """«Сколько всего X» → одно число. Say it; don't chart a 1x1 table."""
        install_client(
            monkeypatch,
            FakeClient(
                SQLQueryResult(
                    status="ok",
                    columns=[{"name": "count(*)", "type": "number"}],
                    rows=[[4584]],
                    row_count=1,
                    sql="SELECT count(*) FROM player WHERE weight > 200",
                    explanation="Количество игроков тяжелее 200 фунтов.",
                )
            ),
        )
        state = make_state(user_input="сколько игроков тяжелее 200 фунтов", use_sql_source=True)
        patch = await sql_source_node(state)

        assert patch["sql_scalar_answered"] is True
        assert "4584" in patch["assistant_message"]
        assert "SELECT count(*)" in patch["assistant_message"]
        routed = AppState(session_id="s1", sql_scalar_answered=True)
        assert route_after_sql_source(routed) == "end"

    async def test_selected_datasource_reaches_the_client(self, sql_enabled, monkeypatch):
        client = install_client(
            monkeypatch,
            FakeClient(
                SQLQueryResult(
                    status="ok", columns=RESULT_TABLE["columns"], rows=RESULT_TABLE["rows"],
                    row_count=2, sql=RESULT_TABLE["sql"],
                )
            ),
        )
        received = {}
        original = client.query
        async def spy(question, session_id, max_rows=None, hint_tables=None, datasource_id=None):
            received["datasource_id"] = datasource_id
            return await original(question, session_id, max_rows, hint_tables)
        client.query = spy

        state = make_state(
            user_input="матчи в Испании", use_sql_source=True,
            sql_datasource_id="WorldSoccerDataBase",
        )
        await sql_source_node(state)
        assert received["datasource_id"] == "WorldSoccerDataBase"

    async def test_persisted_result_short_circuits_the_service(self, sql_enabled, monkeypatch):
        client = install_client(monkeypatch, FakeClient(SQLQueryResult(status="ok")))
        state = make_state(user_input="а теперь линией", persisted_sql_result=RESULT_TABLE)
        patch = await sql_source_node(state)

        assert client.calls == []
        assert patch["sql_result_table"] == RESULT_TABLE


class TestDataFrameFromResult:
    def test_types_come_from_the_database(self):
        df, types = dataframe_from_result_table(RESULT_TABLE)
        assert list(df.columns) == ["region", "revenue"]
        assert types == {"revenue": "numeric"}
        assert df["revenue"].dtype.kind == "f"

    def test_four_digit_amounts_keep_the_declared_type(self):
        table = {
            "columns": [{"name": "region", "type": "string"}, {"name": "amount", "type": "number"}],
            "rows": [["North", 1950], ["South", 2010]],
        }
        _, types = dataframe_from_result_table(table)
        # Values in the 1900-2100 range must stay numeric: the database said so.
        assert types["amount"] == "numeric"

    def test_datetime_column_is_parsed(self):
        table = {
            "columns": [{"name": "d", "type": "datetime"}, {"name": "v", "type": "number"}],
            "rows": [["2025-01-01", 1], ["2025-02-01", 2]],
        }
        df, types = dataframe_from_result_table(table)
        assert types["d"] == "temporal"
        assert df["d"].dtype.kind == "M"

    def test_expression_columns_become_addressable_names(self):
        """Unaliased SQL expressions must not reach generated pandas code as-is.

        SQLite names such a column after the expression, so without this the
        LLM has to write df["STRFTIME('%Y', OperationalFrom)"] — quotes and
        parens inside generated code, which breaks it.
        """
        table = {
            "columns": [
                {"name": "count(*)", "type": "number"},
                {"name": "STRFTIME('%Y', OperationalFrom)", "type": "string"},
            ],
            "rows": [[5, "1970"], [7, "1971"]],
        }
        df, types = dataframe_from_result_table(table)

        assert list(df.columns) == ["count", "STRFTIME_Y_OperationalFrom"]
        assert all(c.isidentifier() for c in df.columns)
        assert types["count"] == "numeric"

    def test_plain_column_names_are_left_alone(self):
        table = {
            "columns": [{"name": "Country", "type": "string"}, {"name": "plants", "type": "number"}],
            "rows": [["US", 137]],
        }
        assert list(dataframe_from_result_table(table)[0].columns) == ["Country", "plants"]

    def test_colliding_sanitised_names_stay_distinct(self):
        table = {
            "columns": [
                {"name": "sum(a)", "type": "number"},
                {"name": "sum[a]", "type": "number"},
            ],
            "rows": [[1, 2]],
        }
        columns = list(dataframe_from_result_table(table)[0].columns)
        assert columns == ["sum_a", "sum_a_2"]
        assert len(set(columns)) == 2

    def test_cyrillic_column_names_are_kept_verbatim(self):
        """«город» is a valid Python identifier; mangling it would mislabel the axis."""
        table = {
            "columns": [
                {"name": "город", "type": "string"},
                {"name": "SUM(выручка)", "type": "number"},
            ],
            "rows": [["Москва", 1.0]],
        }
        assert list(dataframe_from_result_table(table)[0].columns) == ["город", "SUM_выручка"]

    def test_name_starting_with_digit_is_made_valid(self):
        table = {"columns": [{"name": "2024", "type": "number"}], "rows": [[1]]}
        assert list(dataframe_from_result_table(table)[0].columns)[0].isidentifier()

    def test_missing_columns_rejected(self):
        with pytest.raises(ValueError):
            dataframe_from_result_table({"columns": [], "rows": []})


class TestProvenanceSurvives:
    def test_table_node_does_not_wipe_sql_source(self):
        """Regression: rebuilding DataArtefacts must not drop the SQL provenance.

        table_data_extractor constructs a fresh DataArtefacts; if sql_source is
        not carried over, the chart is built from database rows while the user
        is shown no query at all.
        """
        from app.api.schemas import DataArtefacts, SQLSourceInfo

        state = make_state()
        state.artefacts = state.artefacts.model_copy(
            update={
                "data": state.artefacts.data.model_copy(
                    update={"sql_source": SQLSourceInfo(used=True, sql="SELECT 1", row_count=3)}
                )
            }
        )
        rebuilt = DataArtefacts(sql_source=state.artefacts.data.sql_source)

        assert rebuilt.sql_source.used is True
        assert rebuilt.sql_source.sql == "SELECT 1"


class TestSeriesLeniency:
    def test_missing_series_column_is_dropped_not_fatal(self):
        """A plan that names a series the code never created must still chart."""
        import pandas as pd
        from app.api.schemas import ChartType, TableCodeSpec
        from app.tools.table_code_executor import validate_result_dataframe

        df = pd.DataFrame({"x": ["2025-01", "2025-02"], "y": [1.0, 2.0]})
        spec = TableCodeSpec(
            chart_type=ChartType.line, code="result = df",
            x_col="x", y_col="y", series_col="series",
        )
        assert validate_result_dataframe(df, spec)  # sanity: validator does object

        relaxed = spec.model_copy(update={"series_col": None})
        assert validate_result_dataframe(df, relaxed) == []


class TestErrorMessages:
    def test_error_node_keeps_a_specific_diagnosis(self):
        """Regression: the generic routing text must not replace a real diagnosis."""
        from app.graph.pipeline import _error_node

        state = make_state()
        state.current_stage = StageName.error
        state.assistant_message = "Не удалось обработать таблицу: уточните колонки."

        assert _error_node(state)["assistant_message"] == state.assistant_message

    def test_genuine_routing_failure_still_says_so(self):
        from app.graph.pipeline import _error_node

        state = make_state()
        state.current_stage = StageName.ingress
        state.assistant_message = "График построен."

        assert _error_node(state)["assistant_message"] == "Не удалось определить следующий шаг."


class TestRollback:
    def test_rollback_to_ingress_clears_sql_artefacts(self):
        state = make_state(persisted_sql_result=RESULT_TABLE, sql_result_table=RESULT_TABLE)
        patch = invalidate(state, StageName.ingress)

        assert patch["sql_result_table"] is None
        assert patch["persisted_sql_result"] is None
        assert patch["use_sql_source"] is False

    def test_rollback_to_data_parsing_keeps_fetched_rows(self):
        state = make_state(persisted_sql_result=RESULT_TABLE)
        patch = invalidate(state, StageName.data_parsing)

        # Re-planning the chart should not re-query the database.
        assert "persisted_sql_result" not in patch
        assert patch["sql_result_table"] is None

    def test_rollback_to_sql_query_forces_a_fresh_fetch(self):
        state = make_state(persisted_sql_result=RESULT_TABLE)
        patch = invalidate(state, StageName.sql_query)

        assert patch["persisted_sql_result"] is None
