"""HTTP contract tests against a real KaggleDBQA database with stubbed roles."""
import os

import pytest
from fastapi.testclient import TestClient

KAGGLE = "/Users/drkocharyan/education/KaggleDBQA/databases/GeoNuclearData/GeoNuclearData.sqlite"
pytestmark = pytest.mark.skipif(not os.path.exists(KAGGLE), reason="KaggleDBQA not available")


@pytest.fixture()
def client(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "db_path", KAGGLE)
    monkeypatch.setattr(settings, "db_id", "GeoNuclearData")
    monkeypatch.setattr(settings, "use_profile", False)

    from app.api import routes
    monkeypatch.setattr(routes, "_registry", None)
    monkeypatch.setattr(routes, "_connectors", {})

    import main
    return TestClient(main.app)


def install_roles(monkeypatch, sql_text, explanation="Описание."):
    from app.pipeline import runner

    class Fake:
        def __init__(self, role):
            self.role = role
            self.n = 0

        async def ask(self, system, user, max_tokens=None, temperature=None):
            self.n += 1
            if self.role == "schema":
                return "nuclear_power_plants"
            if self.role == "sql":
                return explanation if self.n > 1 else f"```sql\n{sql_text}\n```"
            return f"```sql\n{sql_text}\n```"

    cache = {}
    monkeypatch.setattr(runner, "get_role_client", lambda role: cache.setdefault(role, Fake(role)))


class TestQuery:
    def test_ok_response_matches_the_contract(self, client, monkeypatch):
        install_roles(monkeypatch, "SELECT Country, COUNT(*) AS n FROM nuclear_power_plants GROUP BY Country")
        r = client.post("/query", json={"question": "сколько станций по странам", "session_id": "s1"})

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["sql"] == "SELECT Country, COUNT(*) AS n FROM nuclear_power_plants GROUP BY Country"
        assert body["explanation"] == "Описание."
        assert body["row_count"] == len(body["rows"])
        assert body["truncated"] is False
        assert [c["name"] for c in body["columns"]] == ["Country", "n"]
        assert all(c["type"] != "unknown" for c in body["columns"])

    def test_max_rows_is_clamped_and_truncation_reported(self, client, monkeypatch):
        install_roles(monkeypatch, "SELECT Country, COUNT(*) AS n FROM nuclear_power_plants GROUP BY Country")
        r = client.post("/query", json={"question": "станции по странам", "max_rows": 2})
        body = r.json()

        assert body["row_count"] == 2
        assert body["truncated"] is True

    def test_unsafe_sql_is_refused_not_executed(self, client, monkeypatch):
        install_roles(monkeypatch, "DROP TABLE nuclear_power_plants")
        body = client.post("/query", json={"question": "удали"}).json()

        assert body["status"] == "error"
        assert body["error_type"] == "unsafe_sql"

    def test_empty_question_rejected(self, client):
        body = client.post("/query", json={"question": "   "}).json()
        assert body["status"] == "error"

    def test_llm_outage_is_reported_as_llm_error(self, client, monkeypatch):
        from app.llm.client import LLMUnavailableError
        from app.pipeline import runner

        class Dead:
            async def ask(self, *a, **k):
                raise LLMUnavailableError("Роль 'schema' недоступна")

        monkeypatch.setattr(runner, "get_role_client", lambda role: Dead())
        body = client.post("/query", json={"question": "страны"}).json()

        assert body["status"] == "error"
        assert body["error_type"] == "llm_error"

    def test_rows_are_json_serialisable(self, client, monkeypatch):
        install_roles(monkeypatch, "SELECT * FROM nuclear_power_plants")
        body = client.post("/query", json={"question": "всё"}).json()
        assert body["status"] == "ok"
        assert isinstance(body["rows"], list)


class TestDatasources:
    def test_configured_database_is_registered(self, client):
        body = client.get("/datasources").json()
        assert body["default_id"] == "GeoNuclearData"
        assert body["count"] >= 1
        assert any(d["id"] == "GeoNuclearData" and d["is_default"] for d in body["datasources"])

    def test_unknown_datasource_is_a_clear_error(self, client, monkeypatch):
        install_roles(monkeypatch, "SELECT 1")
        body = client.post("/query", json={"question": "x", "datasource_id": "NoSuchDb"}).json()

        assert body["status"] == "error"
        assert body["error_type"] == "db_error"
        assert "NoSuchDb" in body["message"]

    def test_response_echoes_the_datasource(self, client, monkeypatch):
        install_roles(monkeypatch, "SELECT Country FROM nuclear_power_plants")
        body = client.post("/query", json={"question": "страны"}).json()
        assert body["datasource_id"] == "GeoNuclearData"


class TestSchema:
    def test_schema_lists_tables_and_columns(self, client):
        body = client.get("/schema").json()
        assert body["db_id"] == "GeoNuclearData"
        assert len(body["tables"]) > 0
        first = body["tables"][0]
        assert "name" in first and len(first["columns"]) > 0
