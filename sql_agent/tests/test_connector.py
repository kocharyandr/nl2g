"""Connector tests against a temporary SQLite database."""
import sqlite3

import pytest

from app.api.schemas import ColumnType
from app.db.connector import QueryTimeoutError, SQLiteConnector, map_sqlite_type
from app.db.safety import UnsafeSQLError


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "shop.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE regions (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            region_id INTEGER,
            revenue REAL,
            amount INTEGER,
            created_at DATE,
            FOREIGN KEY (region_id) REFERENCES regions(id)
        );
        INSERT INTO regions VALUES (1, 'North'), (2, 'South');
        INSERT INTO orders VALUES
            (1, 1, 7650.0, 1200, '2025-10-01'),
            (2, 2, 2100.0, 3400, '2025-10-02'),
            (3, 1, 550.5, 9999, '2025-11-15');
        """
    )
    conn.commit()
    conn.close()
    return str(path)


class TestTypes:
    @pytest.mark.parametrize(
        "declared,expected",
        [
            ("INTEGER", ColumnType.number),
            ("REAL", ColumnType.number),
            ("TEXT", ColumnType.string),
            ("DATE", ColumnType.datetime),
            ("BOOLEAN", ColumnType.boolean),
            ("", ColumnType.unknown),
        ],
    )
    def test_declared_type_mapping(self, declared, expected):
        assert map_sqlite_type(declared) == expected

    def test_four_digit_integer_stays_a_number(self, db):
        """The bug this contract exists to avoid: 1000-9999 must not read as a date."""
        result = SQLiteConnector(db).execute("SELECT amount FROM orders", 10, 5.0)
        assert result.columns[0].type == ColumnType.number


class TestExecute:
    def test_returns_columns_and_rows(self, db):
        result = SQLiteConnector(db).execute(
            "SELECT r.name, SUM(o.revenue) AS revenue "
            "FROM orders o JOIN regions r ON r.id = o.region_id GROUP BY r.name",
            100,
            5.0,
        )
        assert [c.name for c in result.columns] == ["name", "revenue"]
        assert result.row_count == 2
        assert result.truncated is False
        assert sorted(result.rows) == [["North", 8200.5], ["South", 2100.0]]

    def test_truncation_is_reported(self, db):
        result = SQLiteConnector(db).execute("SELECT * FROM orders", 2, 5.0)
        assert result.row_count == 2
        assert result.truncated is True

    def test_exact_fit_is_not_truncated(self, db):
        result = SQLiteConnector(db).execute("SELECT * FROM orders", 3, 5.0)
        assert result.row_count == 3
        assert result.truncated is False

    def test_write_is_rejected_before_reaching_the_database(self, db):
        with pytest.raises(UnsafeSQLError):
            SQLiteConnector(db).execute("DELETE FROM orders", 10, 5.0)

    def test_database_is_opened_read_only(self, db):
        conn = SQLiteConnector(db)._connect(5.0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("INSERT INTO regions VALUES (3, 'East')")
        finally:
            conn.close()


class TestProbe:
    def test_valid_query_returns_no_feedback(self, db):
        assert SQLiteConnector(db).probe("SELECT * FROM orders", 5.0) is None

    def test_sql_error_is_returned_as_feedback(self, db):
        feedback = SQLiteConnector(db).probe("SELECT revenu FROM orders", 5.0)
        assert feedback is not None and "revenu" in feedback

    def test_empty_result_is_treated_as_a_logic_error(self, db):
        feedback = SQLiteConnector(db).probe("SELECT * FROM orders WHERE id = 999", 5.0)
        assert feedback is not None and "0 rows" in feedback


class TestListTables:
    def test_lists_tables_with_columns_and_samples(self, db):
        tables = {t.name: t for t in SQLiteConnector(db).list_tables()}
        assert set(tables) == {"regions", "orders"}
        assert [c.name for c in tables["regions"].columns] == ["id", "name"]
        assert tables["orders"].ddl.startswith("CREATE TABLE orders")
        assert len(tables["orders"].sample_rows) == 3

    def test_missing_file_fails_fast(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SQLiteConnector(str(tmp_path / "nope.sqlite"))
