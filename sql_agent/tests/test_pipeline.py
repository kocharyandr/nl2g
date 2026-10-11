"""Pipeline tests with stubbed role endpoints.

The LLM is replaced, the database is real: what is under test is the wiring —
schema narrowing, the critic feedback loop, and the Variant A promise that the
result set is returned unchanged.
"""
import sqlite3

import pytest

from app.pipeline import runner
from app.pipeline.runner import ClarificationNeeded, extract_sql, run_pipeline
from app.db.connector import SQLiteConnector
from app.db.safety import UnsafeSQLError


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "shop.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE regions (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, region_id INTEGER, revenue REAL);
        CREATE TABLE unrelated_audit_log (id INTEGER PRIMARY KEY, note TEXT);
        INSERT INTO regions VALUES (1, 'North'), (2, 'South');
        INSERT INTO orders VALUES (1, 1, 7650.0), (2, 2, 2100.0);
        """
    )
    conn.commit()
    conn.close()
    return SQLiteConnector(str(path))


class FakeClient:
    """Records prompts and replays scripted answers per role."""

    def __init__(self, role, script):
        self.role = role
        self.script = script
        self.calls = []

    async def ask(self, system, user, max_tokens=None, temperature=None):
        self.calls.append(user)
        answers = self.script.get(self.role, [])
        idx = min(len(self.calls) - 1, len(answers) - 1)
        return answers[idx] if answers else ""


@pytest.fixture()
def fake_roles(monkeypatch):
    created = {}

    def install(script):
        def factory(role):
            if role not in created:
                created[role] = FakeClient(role, script)
            return created[role]

        monkeypatch.setattr(runner, "get_role_client", factory)
        return created

    return install


class TestExtractSQL:
    def test_fenced_block(self):
        assert extract_sql("noise ```sql\nSELECT 1\n``` tail") == "SELECT 1"

    def test_unclosed_fence(self):
        assert extract_sql("```sql\nSELECT 1") == "SELECT 1"

    def test_thinking_block_is_dropped(self):
        text = "<thinking>I should join</thinking>\nSELECT 1"
        assert extract_sql(text) == "SELECT 1"


@pytest.mark.asyncio
class TestPipeline:
    async def test_happy_path_returns_raw_rows(self, db, fake_roles):
        roles = fake_roles(
            {
                "schema": ["regions, orders"],
                "sql": ["```sql\nSELECT name FROM regions\n```", "Список регионов."],
                "critic": [],
            }
        )
        outcome = await run_pipeline("покажи регионы", db, max_rows=100)

        assert outcome.sql == "SELECT name FROM regions"
        assert [c.name for c in outcome.result.columns] == ["name"]
        assert sorted(outcome.result.rows) == [["North"], ["South"]]
        assert outcome.meta["critic_attempts"] == 1
        # The critic role is never even instantiated when the draft runs clean.
        assert "critic" not in roles

    async def test_schema_agent_narrows_the_prompt(self, db, fake_roles):
        roles = fake_roles(
            {
                "schema": ["regions"],
                "sql": ["```sql\nSELECT name FROM regions\n```", "Регионы."],
            }
        )
        outcome = await run_pipeline("покажи регионы", db, max_rows=100)

        assert outcome.meta["selected_tables"] == ["regions"]
        sql_prompt = roles["sql"].calls[0]
        assert "CREATE TABLE regions" in sql_prompt
        assert "unrelated_audit_log" not in sql_prompt

    async def test_critic_fixes_a_broken_query(self, db, fake_roles):
        roles = fake_roles(
            {
                "schema": ["regions"],
                "sql": ["```sql\nSELECT nmae FROM regions\n```", "Регионы."],
                "critic": ["```sql\nSELECT name FROM regions\n```"],
            }
        )
        outcome = await run_pipeline("покажи регионы", db, max_rows=100)

        assert outcome.sql == "SELECT name FROM regions"
        assert outcome.meta["critic_attempts"] == 2
        # The engine's own error text is what the critic was given.
        assert "nmae" in roles["critic"].calls[0]

    async def test_unfixable_query_never_reaches_the_caller(self, db, fake_roles):
        fake_roles(
            {
                "schema": ["regions"],
                "sql": ["```sql\nDROP TABLE regions\n```"],
                "critic": ["```sql\nDROP TABLE regions\n```"],
            }
        )
        with pytest.raises(UnsafeSQLError):
            await run_pipeline("удали всё", db, max_rows=100)

    async def test_no_table_match_falls_back_to_full_schema(self, db, fake_roles):
        roles = fake_roles(
            {
                "schema": ["I am not sure"],
                "sql": ["```sql\nSELECT name FROM regions\n```", "Регионы."],
            }
        )
        outcome = await run_pipeline("что-то непонятное", db, max_rows=100)

        assert set(outcome.meta["selected_tables"]) == {"regions", "orders", "unrelated_audit_log"}

    async def test_hints_skip_the_schema_agent(self, db, fake_roles):
        roles = fake_roles(
            {
                "schema": ["should not be called"],
                "sql": ["```sql\nSELECT name FROM regions\n```", "Регионы."],
            }
        )
        outcome = await run_pipeline(
            "покажи регионы", db, max_rows=100, hint_tables=["regions"]
        )

        assert outcome.meta["used_hint_tables"] is True
        assert "schema" not in roles

    async def test_truncation_flag_survives_to_the_outcome(self, db, fake_roles):
        fake_roles(
            {
                "schema": ["regions"],
                "sql": ["```sql\nSELECT name FROM regions\n```", "Регионы."],
            }
        )
        outcome = await run_pipeline("покажи регионы", db, max_rows=1)
        assert outcome.result.truncated is True
        assert outcome.result.row_count == 1

    async def test_clarification_when_enabled(self, db, fake_roles, monkeypatch):
        monkeypatch.setattr(runner.settings, "clarification_enabled", True)
        fake_roles({"schema": ["NEED_CLARIFICATION: За какой период?"]})

        with pytest.raises(ClarificationNeeded) as excinfo:
            await run_pipeline("выручка", db, max_rows=100)
        assert excinfo.value.question_to_user == "За какой период?"

    async def test_clarification_marker_ignored_when_disabled(self, db, fake_roles, monkeypatch):
        monkeypatch.setattr(runner.settings, "clarification_enabled", False)
        fake_roles(
            {
                "schema": ["NEED_CLARIFICATION: За какой период?"],
                "sql": ["```sql\nSELECT name FROM regions\n```", "Регионы."],
            }
        )
        outcome = await run_pipeline("выручка", db, max_rows=100)
        assert outcome.sql == "SELECT name FROM regions"
