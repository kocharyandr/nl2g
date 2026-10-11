import pytest

from app.db.safety import (
    UnsafeSQLError,
    apply_row_cap,
    has_limit,
    split_statements,
    validate_single_select,
)


class TestValidateSingleSelect:
    def test_plain_select_passes(self):
        validate_single_select("SELECT region, SUM(revenue) FROM orders GROUP BY region")

    def test_cte_passes(self):
        validate_single_select("WITH r AS (SELECT * FROM orders) SELECT * FROM r")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1; DROP TABLE orders",
            "SELECT 1;SELECT 2",
        ],
    )
    def test_chained_statements_rejected(self, sql):
        with pytest.raises(UnsafeSQLError, match="одно выражение"):
            validate_single_select(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM orders",
            "UPDATE orders SET revenue = 0",
            "INSERT INTO orders VALUES (1)",
            "DROP TABLE orders",
            "PRAGMA table_info('orders')",
            "ATTACH DATABASE 'x.db' AS x",
        ],
    )
    def test_non_select_rejected(self, sql):
        with pytest.raises(UnsafeSQLError):
            validate_single_select(sql)

    def test_write_hidden_in_subquery_rejected(self):
        with pytest.raises(UnsafeSQLError, match="DELETE"):
            validate_single_select("SELECT * FROM (DELETE FROM orders RETURNING *)")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM sqlite_master",
            "SELECT * FROM information_schema.tables",
        ],
    )
    def test_system_tables_rejected(self, sql):
        with pytest.raises(UnsafeSQLError, match="системной таблице"):
            validate_single_select(sql)

    def test_keyword_inside_string_literal_is_not_a_write(self):
        # A literal mentioning a keyword must not trip the check.
        validate_single_select("SELECT * FROM orders WHERE note = 'please delete me'")

    def test_semicolon_inside_literal_is_not_a_second_statement(self):
        validate_single_select("SELECT * FROM orders WHERE note = 'a;b'")

    def test_comment_cannot_hide_a_second_statement(self):
        # The comment is stripped, leaving a single SELECT.
        validate_single_select("SELECT 1 -- ; DROP TABLE orders")

    def test_empty_rejected(self):
        with pytest.raises(UnsafeSQLError, match="Пустой"):
            validate_single_select("   ")


class TestRowCap:
    def test_limit_appended_when_absent(self):
        assert apply_row_cap("SELECT * FROM t", 100) == "SELECT * FROM t LIMIT 100"

    def test_existing_limit_preserved(self):
        assert apply_row_cap("SELECT * FROM t LIMIT 5", 100) == "SELECT * FROM t LIMIT 5"

    def test_trailing_semicolon_stripped(self):
        assert apply_row_cap("SELECT * FROM t;", 10) == "SELECT * FROM t LIMIT 10"

    def test_limit_in_literal_does_not_count(self):
        assert has_limit("SELECT * FROM t WHERE note = 'limit'") is False


def test_split_statements_ignores_literals():
    assert len(split_statements("SELECT 'a;b' FROM t")) == 1
