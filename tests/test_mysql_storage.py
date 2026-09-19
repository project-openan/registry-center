# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
MySQL storage backend tests.

Mirrors the PostgreSQL test suite. Requires a live MySQL server (5.7+/8.0,
see MYSQL_TEST_* env vars); auto-skips when MySQL is unavailable.
"""

import pytest

from agent_registry.model.tag import Tag


pytestmark = pytest.mark.usefixtures("clean_mysql_tables")


class TestMySQLStorageInit:
    def test_init_creates_tables(self, clean_mysql_tables):
        conn = clean_mysql_tables._acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name IN ('agent_card','tag')"
                )
                tables = {r[0] for r in cur.fetchall()}
        finally:
            clean_mysql_tables._release_conn(conn)
        assert "agent_card" in tables
        assert "tag" in tables

    def test_init_uses_json_columns(self, clean_mysql_tables):
        conn = clean_mysql_tables._acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name='agent_card' AND column_name LIKE '%_json'"
                )
                cols = {r[0]: r[1] for r in cur.fetchall()}
        finally:
            clean_mysql_tables._release_conn(conn)
        for col_name, dtype in cols.items():
            assert dtype == "json", f"{col_name} should be JSON, got {dtype}"

    def test_init_uses_bin_collation_for_key_columns(self, clean_mysql_tables):
        conn = clean_mysql_tables._acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT collation_name FROM information_schema.columns "
                    "WHERE table_name='agent_card' AND column_name='name'"
                )
                row = cur.fetchone()
        finally:
            clean_mysql_tables._release_conn(conn)
        assert row is not None and row[0] == "utf8mb4_bin"


class TestMySQLStorageCRUD:
    def test_create_and_find_by_key(self, clean_mysql_tables, make_agent):
        agent = make_agent("my_agent_1", "org_1")
        assert clean_mysql_tables.create(agent) is True
        record = clean_mysql_tables.find_by_key("my_agent_1", "org_1")
        assert record is not None
        assert record.agent_card.name == "my_agent_1"
        assert record.status == "published"

    def test_create_duplicate_returns_false(self, clean_mysql_tables, make_agent):
        agent = make_agent("dup_agent", "org")
        clean_mysql_tables.create(agent)
        assert clean_mysql_tables.create(agent) is False

    def test_create_with_owner(self, clean_mysql_tables, make_agent):
        agent = make_agent("owned_agent", "org")
        assert clean_mysql_tables.create(agent, owner="user1") is True
        record = clean_mysql_tables.find_by_key("owned_agent", "org", "user1")
        assert record is not None
        assert record.owner == "user1"

    def test_find_by_key_nonexistent(self, clean_mysql_tables):
        assert clean_mysql_tables.find_by_key("nope", "nope") is None

    def test_find_by_name_case_insensitive(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("AlphaSvc", "o1"))
        results = clean_mysql_tables.find_by_name("alphasvc")
        assert len(results) == 1

    def test_find_by_organization(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("a1", "shared_org"))
        clean_mysql_tables.create(make_agent("a2", "shared_org"))
        clean_mysql_tables.create(make_agent("a3", "other_org"))
        assert len(clean_mysql_tables.find_by_organization("shared_org")) == 2

    def test_find_all(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("x1", "o1"))
        clean_mysql_tables.create(make_agent("x2", "o2"))
        assert len(clean_mysql_tables.find_all()) == 2

    def test_find_by_owner(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("a1", "o1"), owner="u1")
        clean_mysql_tables.create(make_agent("a2", "o2"), owner="u2")
        results = clean_mysql_tables.find_by_owner("u1")
        assert len(results) == 1

    def test_find_by_status(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("pub", "o1"), status="published")
        clean_mysql_tables.create(make_agent("reg", "o2"), status="registered")
        results = clean_mysql_tables.find_by_status("published")
        assert len(results) == 1
        assert results[0].name == "pub"

    def test_update_agent(self, clean_mysql_tables, make_agent):
        agent = make_agent("upd", "o1", version="1.0.0")
        clean_mysql_tables.create(agent)
        agent_data = {
            "name": "upd",
            "provider": {"organization": "o1", "url": "https://new.com"},
            "description": "updated",
            "version": "2.0.0",
            "skills": []
        }
        assert clean_mysql_tables.update("upd", "o1", agent_data) is True
        record = clean_mysql_tables.find_by_key("upd", "o1")
        assert record.agent_card.version == "2.0.0"

    def test_update_status(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("s1", "o1"))
        assert clean_mysql_tables.update_status("s1", "o1", "registered") is True
        assert clean_mysql_tables.find_by_key("s1", "o1").status == "registered"

    def test_delete(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("del", "o1"))
        assert clean_mysql_tables.delete("del", "o1") is True
        assert clean_mysql_tables.find_by_key("del", "o1") is None

    def test_delete_nonexistent(self, clean_mysql_tables):
        assert clean_mysql_tables.delete("nope", "nope") is False

    def test_count(self, clean_mysql_tables, make_agent):
        assert clean_mysql_tables.count() == 0
        clean_mysql_tables.create(make_agent("c1", "o1"))
        clean_mysql_tables.create(make_agent("c2", "o2"))
        assert clean_mysql_tables.count() == 2

    def test_get_created_at(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("ts", "o1"))
        assert clean_mysql_tables.get_created_at("ts", "o1") != ''

    def test_get_updated_at(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("ts2", "o1"))
        assert clean_mysql_tables.get_updated_at("ts2", "o1") != ''


class TestMySQLStorageTags:
    def test_agent_tags_crud(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("tagged", "o1"))
        assert clean_mysql_tables.get_agent_tags("tagged", "o1") == []
        clean_mysql_tables.update_agent_tags("tagged", "o1", ["prod", "v1"])
        assert clean_mysql_tables.get_agent_tags("tagged", "o1") == ["prod", "v1"]

    def test_find_by_tag(self, clean_mysql_tables, make_agent):
        clean_mysql_tables.create(make_agent("t1", "o1"))
        clean_mysql_tables.create(make_agent("t2", "o2"))
        clean_mysql_tables.update_agent_tags("t1", "o1", ["prod"])
        clean_mysql_tables.update_agent_tags("t2", "o2", ["prod", "beta"])
        results = clean_mysql_tables.find_by_tag("prod")
        assert len(results) == 2

    def test_find_by_tag_empty(self, clean_mysql_tables):
        assert clean_mysql_tables.find_by_tag("nonexistent") == []

    def test_tag_entity_crud(self, clean_mysql_tables):
        tag = Tag(name="env_prod")
        assert clean_mysql_tables.create_tag(tag) is True
        assert clean_mysql_tables.create_tag(Tag(name="env_prod")) is False
        fetched = clean_mysql_tables.get_tag(tag.tag_id)
        assert fetched is not None
        assert fetched.name == "env_prod"
        assert clean_mysql_tables.get_tag_by_name("env_prod") is not None

        tag.name = "env_staging"
        assert clean_mysql_tables.update_tag(tag.tag_id, tag) is True
        assert clean_mysql_tables.get_tag(tag.tag_id).name == "env_staging"

        assert clean_mysql_tables.delete_tag(tag.tag_id) is True
        assert clean_mysql_tables.get_tag(tag.tag_id) is None

    def test_list_tags(self, clean_mysql_tables):
        clean_mysql_tables.create_tag(Tag(name="t1"))
        clean_mysql_tables.create_tag(Tag(name="t2"))
        assert len(clean_mysql_tables.list_tags()) == 2


class TestMySQLStoragePrecheck:
    def test_check_connection(self, clean_mysql_tables):
        clean_mysql_tables.check_connection()  # must not raise


class TestMySQLStorageClose:
    def test_close(self, mysql_storage_config):
        from agent_registry.persistence.mysql_storage import MySQLStorage
        storage = MySQLStorage.init(mysql_storage_config)
        storage.close()
