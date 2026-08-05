# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
GaussDB storage backend integration tests.

Uses the local PostgreSQL as a protocol-compatible surrogate (GaussDB is
PG-wire compatible). Auto-skips when the surrogate DB is unavailable.

Key difference from PostgreSQL tests: GaussDB stores JSON as TEXT (not JSONB)
for maximum portability across GaussDB versions.
"""

import pytest

from agent_registry.model.tag import Tag


pytestmark = pytest.mark.usefixtures("clean_gauss_tables")


class TestGaussDBStorageInit:
    def test_init_creates_tables(self, clean_gauss_tables):
        conn = clean_gauss_tables._acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name IN ('agent_card','tag')"
                )
                tables = {r[0] for r in cur.fetchall()}
        finally:
            clean_gauss_tables._release_conn(conn)
        assert "agent_card" in tables
        assert "tag" in tables

    def test_init_uses_text_columns_not_jsonb(self, clean_gauss_tables):
        """GaussDB stores JSON as TEXT (key portability difference from PG)."""
        conn = clean_gauss_tables._acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name='agent_card' AND column_name LIKE '%_json'"
                )
                cols = {r[0]: r[1] for r in cur.fetchall()}
        finally:
            clean_gauss_tables._release_conn(conn)
        for col_name, dtype in cols.items():
            assert dtype == "text", f"{col_name} should be TEXT, got {dtype}"

    def test_tags_column_is_text(self, clean_gauss_tables):
        conn = clean_gauss_tables._acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='agent_card' AND column_name='tags'"
                )
                row = cur.fetchone()
        finally:
            clean_gauss_tables._release_conn(conn)
        assert row is not None
        assert row[0] == "text"

    def test_no_gin_index(self, clean_gauss_tables):
        """GaussDB does not create GIN index (TEXT columns, not JSONB)."""
        conn = clean_gauss_tables._acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename='agent_card' AND indexname='idx_agent_card_json'"
                )
                assert cur.fetchone() is None
        finally:
            clean_gauss_tables._release_conn(conn)


class TestGaussDBStorageCRUD:
    def test_create_and_find_by_key(self, clean_gauss_tables, make_agent):
        agent = make_agent("gauss_agent_1", "org_1")
        assert clean_gauss_tables.create(agent) is True
        record = clean_gauss_tables.find_by_key("gauss_agent_1", "org_1")
        assert record is not None
        assert record.agent_card.name == "gauss_agent_1"
        assert record.status == "published"

    def test_create_duplicate_returns_false(self, clean_gauss_tables, make_agent):
        agent = make_agent("gauss_dup", "org")
        clean_gauss_tables.create(agent)
        assert clean_gauss_tables.create(agent) is False

    def test_create_with_owner(self, clean_gauss_tables, make_agent):
        agent = make_agent("gauss_owned", "org")
        assert clean_gauss_tables.create(agent, owner="user1") is True
        record = clean_gauss_tables.find_by_key("gauss_owned", "org", "user1")
        assert record is not None
        assert record.owner == "user1"

    def test_find_by_key_nonexistent(self, clean_gauss_tables):
        assert clean_gauss_tables.find_by_key("nope", "nope") is None

    def test_find_by_name(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gauss_alpha", "o1"))
        clean_gauss_tables.create(make_agent("gauss_beta", "o2"))
        results = clean_gauss_tables.find_by_name("gauss_alpha")
        assert len(results) == 1

    def test_find_by_organization(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("g1", "shared_org"))
        clean_gauss_tables.create(make_agent("g2", "shared_org"))
        clean_gauss_tables.create(make_agent("g3", "other_org"))
        assert len(clean_gauss_tables.find_by_organization("shared_org")) == 2

    def test_find_all(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gx1", "o1"))
        clean_gauss_tables.create(make_agent("gx2", "o2"))
        assert len(clean_gauss_tables.find_all()) == 2

    def test_find_by_owner(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("go1", "o1"), owner="u1")
        clean_gauss_tables.create(make_agent("go2", "o2"), owner="u2")
        results = clean_gauss_tables.find_by_owner("u1")
        assert len(results) == 1

    def test_find_by_status(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gpub", "o1"), status="published")
        clean_gauss_tables.create(make_agent("greg", "o2"), status="registered")
        results = clean_gauss_tables.find_by_status("published")
        assert len(results) == 1
        assert results[0].name == "gpub"

    def test_update_agent(self, clean_gauss_tables, make_agent):
        agent = make_agent("gupd", "o1", version="1.0.0")
        clean_gauss_tables.create(agent)
        agent_data = {
            "name": "gupd",
            "provider": {"organization": "o1", "url": "https://new.com"},
            "description": "updated",
            "version": "2.0.0",
            "skills": []
        }
        assert clean_gauss_tables.update("gupd", "o1", agent_data) is True
        record = clean_gauss_tables.find_by_key("gupd", "o1")
        assert record.agent_card.version == "2.0.0"

    def test_update_status(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gs1", "o1"))
        assert clean_gauss_tables.update_status("gs1", "o1", "registered") is True
        assert clean_gauss_tables.find_by_key("gs1", "o1").status == "registered"

    def test_delete(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gdel", "o1"))
        assert clean_gauss_tables.delete("gdel", "o1") is True
        assert clean_gauss_tables.find_by_key("gdel", "o1") is None

    def test_count(self, clean_gauss_tables, make_agent):
        assert clean_gauss_tables.count() == 0
        clean_gauss_tables.create(make_agent("gc1", "o1"))
        clean_gauss_tables.create(make_agent("gc2", "o2"))
        assert clean_gauss_tables.count() == 2

    def test_get_created_at(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gts", "o1"))
        assert clean_gauss_tables.get_created_at("gts", "o1") != ''

    def test_get_updated_at(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gts2", "o1"))
        assert clean_gauss_tables.get_updated_at("gts2", "o1") != ''


class TestGaussDBStorageTags:
    def test_agent_tags_crud(self, clean_gauss_tables, make_agent):
        clean_gauss_tables.create(make_agent("gtagged", "o1"))
        assert clean_gauss_tables.get_agent_tags("gtagged", "o1") == []
        clean_gauss_tables.update_agent_tags("gtagged", "o1", ["prod", "v1"])
        assert clean_gauss_tables.get_agent_tags("gtagged", "o1") == ["prod", "v1"]

    def test_find_by_tag_uses_jsonb_cast(self, clean_gauss_tables, make_agent):
        """GaussDB FIND_BY_TAG casts TEXT to jsonb for @> operator."""
        clean_gauss_tables.create(make_agent("gt1", "o1"))
        clean_gauss_tables.create(make_agent("gt2", "o2"))
        clean_gauss_tables.update_agent_tags("gt1", "o1", ["prod"])
        clean_gauss_tables.update_agent_tags("gt2", "o2", ["prod", "beta"])
        results = clean_gauss_tables.find_by_tag("prod")
        assert len(results) == 2

    def test_find_by_tag_empty(self, clean_gauss_tables):
        assert clean_gauss_tables.find_by_tag("nonexistent") == []

    def test_tag_entity_crud(self, clean_gauss_tables):
        tag = Tag(name="gauss_env")
        assert clean_gauss_tables.create_tag(tag) is True
        assert clean_gauss_tables.create_tag(Tag(name="gauss_env")) is False
        fetched = clean_gauss_tables.get_tag(tag.tag_id)
        assert fetched is not None
        assert fetched.name == "gauss_env"
        assert clean_gauss_tables.get_tag_by_name("gauss_env") is not None

        tag.name = "gauss_env_staging"
        assert clean_gauss_tables.update_tag(tag.tag_id, tag) is True
        assert clean_gauss_tables.get_tag(tag.tag_id).name == "gauss_env_staging"

        assert clean_gauss_tables.delete_tag(tag.tag_id) is True
        assert clean_gauss_tables.get_tag(tag.tag_id) is None

    def test_list_tags(self, clean_gauss_tables):
        clean_gauss_tables.create_tag(Tag(name="gt1"))
        clean_gauss_tables.create_tag(Tag(name="gt2"))
        assert len(clean_gauss_tables.list_tags()) == 2


class TestGaussDBStorageClose:
    def test_close(self, gauss_storage_config):
        from agent_registry.persistence.gaussdb_storage import GaussDBStorage
        storage = GaussDBStorage.init(gauss_storage_config)
        storage.close()
