# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
SQL query enum integrity tests.

Verifies that all four query enums (PostgreSQL, SQLite, GaussDB, MySQL)
define the same set of operations, and that dialect-specific SQL stays
within each backend's supported syntax.
"""

import pytest

from agent_registry.persistence.sql_queries import (
    PostgreSQLQueries, SQLiteQueries, GaussDBQueries, MySQLQueries
)


# The contract: every backend must define these query names.
REQUIRED_QUERY_NAMES = {
    "CREATE_TABLE",
    "CREATE_AGENT_WITH_OWNER",
    "FIND_BY_KEY_WITH_OWNER",
    "FIND_BY_KEY_ANY_OWNER",
    "FIND_BY_NAME",
    "FIND_BY_ORG",
    "FIND_BY_STATUS",
    "FIND_BY_TAG",
    "FIND_ALL",
    "FIND_BY_OWNER",
    "UPDATE_AGENT",
    "UPDATE_AGENT_WITH_OWNER",
    "UPDATE_STATUS",
    "DELETE_AGENT",
    "DELETE_AGENT_WITH_OWNER",
    "COUNT",
    "COUNT_BY_STATUS",
    "GET_CREATED_AT",
    "GET_UPDATED_AT",
    "GET_AGENT_TAGS",
    "UPDATE_AGENT_TAGS",
    "CREATE_TAG_TABLE",
    "CREATE_TAG",
    "GET_TAG_BY_ID",
    "GET_TAG_BY_NAME",
    "UPDATE_TAG",
    "DELETE_TAG",
    "LIST_TAGS",
}

ALL_ENUMS = [PostgreSQLQueries, SQLiteQueries, GaussDBQueries, MySQLQueries]
ALL_ENUM_IDS = ["postgresql", "sqlite", "gaussdb", "mysql"]


@pytest.mark.parametrize("enum_cls", ALL_ENUMS, ids=ALL_ENUM_IDS)
def test_enum_defines_all_required_queries(enum_cls):
    actual = {member.name for member in enum_cls}
    missing = REQUIRED_QUERY_NAMES - actual
    assert not missing, f"{enum_cls.__name__} missing queries: {missing}"


def test_postgresql_find_by_tag_exists():
    """Regression: FIND_BY_TAG was missing, caused AttributeError."""
    assert hasattr(PostgreSQLQueries, "FIND_BY_TAG")
    assert "@>" in PostgreSQLQueries.FIND_BY_TAG.value


def test_sqlite_find_by_tag_uses_json_each():
    """SQLite uses json_each for tag containment, not JSONB operator."""
    q = SQLiteQueries.FIND_BY_TAG.value
    assert "json_each" in q
    assert "@" not in q


def test_gaussdb_find_by_tag_uses_jsonb_cast():
    """GaussDB casts TEXT to jsonb for containment operator."""
    q = GaussDBQueries.FIND_BY_TAG.value
    assert "::jsonb" in q
    assert "@>" in q


def test_sqlite_uses_question_mark_placeholder():
    assert "?" in SQLiteQueries.CREATE_AGENT_WITH_OWNER.value
    assert "%s" not in SQLiteQueries.CREATE_AGENT_WITH_OWNER.value


def test_postgresql_uses_percent_s_placeholder():
    assert "%s" in PostgreSQLQueries.CREATE_AGENT_WITH_OWNER.value


def test_gaussdb_uses_percent_s_placeholder():
    assert "%s" in GaussDBQueries.CREATE_AGENT_WITH_OWNER.value


def test_sqlite_table_uses_text_not_jsonb():
    """SQLite stores JSON as TEXT (no JSONB type)."""
    assert "TEXT" in SQLiteQueries.CREATE_TABLE.value
    assert "JSONB" not in SQLiteQueries.CREATE_TABLE.value.upper()


def test_postgresql_table_uses_jsonb():
    assert "JSONB" in PostgreSQLQueries.CREATE_TABLE.value.upper()


def test_gaussdb_table_uses_text_not_jsonb():
    """GaussDB stores JSON as TEXT for portability."""
    assert "TEXT" in GaussDBQueries.CREATE_TABLE.value
    assert "JSONB" not in GaussDBQueries.CREATE_TABLE.value.upper()


def test_sqlite_no_do_block():
    """SQLite must not use PG-style DO $$ blocks."""
    for member in SQLiteQueries:
        assert "DO $$" not in member.value, f"{member.name} uses DO block"


def test_gaussdb_uses_on_conflict():
    """GaussDB relies on ON CONFLICT for upsert (PG-compatible)."""
    assert "ON CONFLICT" in GaussDBQueries.CREATE_AGENT_WITH_OWNER.value


def test_sqlite_uses_autoincrement():
    assert "AUTOINCREMENT" in SQLiteQueries.CREATE_TABLE.value


def test_postgresql_uses_serial():
    assert "SERIAL" in PostgreSQLQueries.CREATE_TABLE.value


def test_gaussdb_uses_serial():
    assert "SERIAL" in GaussDBQueries.CREATE_TABLE.value


def test_mysql_uses_percent_s_placeholder():
    assert "%s" in MySQLQueries.CREATE_AGENT_WITH_OWNER.value


def test_mysql_uses_on_duplicate_key():
    """MySQL has no ON CONFLICT; upsert goes through ON DUPLICATE KEY UPDATE."""
    q = MySQLQueries.CREATE_AGENT_WITH_OWNER.value
    assert "ON DUPLICATE KEY UPDATE" in q
    assert "ON CONFLICT" not in q


def test_mysql_find_by_tag_uses_json_contains():
    q = MySQLQueries.FIND_BY_TAG.value
    assert "JSON_CONTAINS" in q
    assert "@>" not in q


def test_mysql_find_by_name_lowercases_both_sides():
    """Key columns are utf8mb4_bin, so ILIKE is replaced with LOWER() LIKE."""
    q = MySQLQueries.FIND_BY_NAME.value
    assert "LOWER(name)" in q
    assert "ILIKE" not in q


def test_mysql_no_ilike_anywhere():
    for member in MySQLQueries:
        assert "ILIKE" not in member.value, f"{member.name} uses ILIKE"


def test_mysql_no_do_block():
    """MySQL must not use PG-style DO $$ blocks."""
    for member in MySQLQueries:
        assert "DO $$" not in member.value, f"{member.name} uses DO block"


def test_mysql_no_create_index_statements():
    """MySQL has no CREATE INDEX IF NOT EXISTS; indexes are inlined in DDL."""
    for member in MySQLQueries:
        assert "CREATE INDEX" not in member.value, \
            f"{member.name} uses CREATE INDEX (unsupported syntax on MySQL)"


def test_mysql_no_nulls_last():
    for member in MySQLQueries:
        assert "NULLS LAST" not in member.value


def test_mysql_finds_any_owner_orders_nulls_last():
    assert "ORDER BY owner IS NULL, owner" in MySQLQueries.FIND_BY_KEY_ANY_OWNER.value


def test_mysql_table_uses_native_json_and_auto_increment():
    table = MySQLQueries.CREATE_TABLE.value.upper()
    assert "JSON" in table
    assert "AUTO_INCREMENT" in table
    assert "SERIAL" not in table
    assert "JSONB" not in table


def test_all_enums_define_required_queries_consistently():
    """All backends define the core required query set (verified per-enum above)."""
    for enum_cls in ALL_ENUMS:
        actual = {member.name for member in enum_cls}
        assert REQUIRED_QUERY_NAMES.issubset(actual), \
            f"{enum_cls.__name__} missing required queries"
