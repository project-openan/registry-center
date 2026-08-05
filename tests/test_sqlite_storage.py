# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
SQLite storage tests

Tests the SQLite storage backend (SqlStorageBackend subclass):
- Agent CRUD operations
- Tag operations (agent tags + tag entities)
- find_by_* queries
"""

import pytest
import os
import tempfile
import shutil

from a2a.types import AgentCard

from agent_registry.persistence.sqlite_storage import SQLiteStorage
from agent_registry.model.tag import Tag


def create_sample_agent(name="test_agent", org="test_org"):
    agent_data = {
        "name": name,
        "provider": {
            "organization": org,
            "url": "https://test.com"
        },
        "description": "Test agent",
        "version": "1.0.0",
        "skills": []
    }
    return AgentCard(**agent_data)


class TestSQLiteStorage:
    """Test SQLite storage backend functionality"""

    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def db_path(self, temp_dir):
        return os.path.join(temp_dir, "agents.db")

    @pytest.fixture
    def storage(self, db_path):
        return SQLiteStorage.init({"sqlite.path": db_path})

    @pytest.fixture
    def sample_agent(self):
        return create_sample_agent()

    # ========== Init / Table Creation ==========

    def test_init_creates_db_file(self, db_path):
        SQLiteStorage.init({"sqlite.path": db_path})
        assert os.path.exists(db_path)

    def test_init_creates_tables(self, storage, db_path):
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        assert "agent_card" in tables
        assert "tag" in tables

    # ========== Create ==========

    def test_create_agent(self, storage, sample_agent):
        result = storage.create(sample_agent)
        assert result is True

    def test_create_duplicate_returns_false(self, storage, sample_agent):
        storage.create(sample_agent)
        result = storage.create(sample_agent)
        assert result is False

    def test_create_with_owner(self, storage, sample_agent):
        result = storage.create(sample_agent, owner="user1")
        assert result is True
        record = storage.find_by_key(
            sample_agent.name, sample_agent.provider.organization, "user1")
        assert record is not None
        assert record.owner == "user1"

    # ========== find_by_key ==========

    def test_find_by_key_existing(self, storage, sample_agent):
        storage.create(sample_agent)
        record = storage.find_by_key(
            sample_agent.name, sample_agent.provider.organization)
        assert record is not None
        assert record.agent_card.name == sample_agent.name
        assert record.status == 'published'

    def test_find_by_key_nonexistent(self, storage):
        record = storage.find_by_key("unknown", "unknown_org")
        assert record is None

    def test_find_by_key_with_owner(self, storage, sample_agent):
        storage.create(sample_agent, owner="user1")
        record = storage.find_by_key(
            sample_agent.name, sample_agent.provider.organization, "user1")
        assert record is not None
        assert record.owner == "user1"

    def test_find_by_key_owner_mismatch(self, storage, sample_agent):
        storage.create(sample_agent, owner="user1")
        record = storage.find_by_key(
            sample_agent.name, sample_agent.provider.organization, "user2")
        assert record is None

    # ========== find_by_name ==========

    def test_find_by_name(self, storage):
        agent1 = create_sample_agent("alpha_agent", "org1")
        agent2 = create_sample_agent("beta_agent", "org2")
        storage.create(agent1)
        storage.create(agent2)
        results = storage.find_by_name("alpha")
        assert len(results) == 1
        assert results[0].name == "alpha_agent"

    def test_find_by_name_empty_result(self, storage):
        results = storage.find_by_name("nonexistent")
        assert results == []

    # ========== find_by_organization ==========

    def test_find_by_organization(self, storage):
        agent1 = create_sample_agent("agent1", "org_a")
        agent2 = create_sample_agent("agent2", "org_a")
        agent3 = create_sample_agent("agent3", "org_b")
        storage.create(agent1)
        storage.create(agent2)
        storage.create(agent3)
        results = storage.find_by_organization("org_a")
        assert len(results) == 2

    # ========== find_all ==========

    def test_find_all(self, storage):
        storage.create(create_sample_agent("a1", "o1"))
        storage.create(create_sample_agent("a2", "o2"))
        results = storage.find_all()
        assert len(results) == 2

    def test_find_all_empty(self, storage):
        results = storage.find_all()
        assert results == []

    # ========== find_by_owner ==========

    def test_find_by_owner(self, storage):
        agent1 = create_sample_agent("a1", "o1")
        agent2 = create_sample_agent("a2", "o2")
        storage.create(agent1, owner="user1")
        storage.create(agent2, owner="user2")
        results = storage.find_by_owner("user1")
        assert len(results) == 1
        assert results[0].agent_card.name == "a1"

    # ========== find_by_status ==========

    def test_find_by_status(self, storage):
        agent1 = create_sample_agent("a1", "o1")
        agent2 = create_sample_agent("a2", "o2")
        storage.create(agent1, status="published")
        storage.create(agent2, status="registered")
        results = storage.find_by_status("published")
        assert len(results) == 1
        assert results[0].name == "a1"

    # ========== find_by_tag ==========

    def test_find_by_tag(self, storage):
        agent1 = create_sample_agent("a1", "o1")
        agent2 = create_sample_agent("a2", "o2")
        storage.create(agent1)
        storage.create(agent2)
        storage.update_agent_tags("a1", "o1", ["production", "v1.0"])
        storage.update_agent_tags("a2", "o2", ["production", "v2.0"])
        results = storage.find_by_tag("production")
        assert len(results) == 2
        results_v1 = storage.find_by_tag("v1.0")
        assert len(results_v1) == 1

    def test_find_by_tag_empty(self, storage):
        results = storage.find_by_tag("nonexistent")
        assert results == []

    # ========== update ==========

    def test_update_agent(self, storage, sample_agent):
        storage.create(sample_agent)
        agent_data = {
            "name": sample_agent.name,
            "provider": {
                "organization": sample_agent.provider.organization,
                "url": "https://updated.com"
            },
            "description": "Updated description",
            "version": "2.0.0",
            "skills": []
        }
        result = storage.update(
            sample_agent.name, sample_agent.provider.organization, agent_data)
        assert result is True
        record = storage.find_by_key(
            sample_agent.name, sample_agent.provider.organization)
        assert record.agent_card.version == "2.0.0"

    def test_update_nonexistent_returns_false(self, storage):
        result = storage.update("unknown", "unknown_org", {"name": "x"})
        assert result is False

    # ========== update_status ==========

    def test_update_status(self, storage, sample_agent):
        storage.create(sample_agent)
        result = storage.update_status(
            sample_agent.name, sample_agent.provider.organization, "registered")
        assert result is True
        record = storage.find_by_key(
            sample_agent.name, sample_agent.provider.organization)
        assert record.status == "registered"

    # ========== delete ==========

    def test_delete_agent(self, storage, sample_agent):
        storage.create(sample_agent)
        result = storage.delete(
            sample_agent.name, sample_agent.provider.organization)
        assert result is True
        record = storage.find_by_key(
            sample_agent.name, sample_agent.provider.organization)
        assert record is None

    def test_delete_nonexistent_returns_false(self, storage):
        result = storage.delete("unknown", "unknown_org")
        assert result is False

    def test_delete_with_owner(self, storage, sample_agent):
        storage.create(sample_agent, owner="user1")
        result = storage.delete(
            sample_agent.name, sample_agent.provider.organization, "user1")
        assert result is True

    def test_delete_owner_mismatch(self, storage, sample_agent):
        storage.create(sample_agent, owner="user1")
        result = storage.delete(
            sample_agent.name, sample_agent.provider.organization, "user2")
        assert result is False

    # ========== count ==========

    def test_count_empty(self, storage):
        assert storage.count() == 0

    def test_count_after_create(self, storage):
        storage.create(create_sample_agent("a1", "o1"))
        storage.create(create_sample_agent("a2", "o2"))
        assert storage.count() == 2

    # ========== timestamps ==========

    def test_get_created_at(self, storage, sample_agent):
        storage.create(sample_agent)
        created = storage.get_created_at(
            sample_agent.name, sample_agent.provider.organization)
        assert created != ''

    def test_get_updated_at(self, storage, sample_agent):
        storage.create(sample_agent)
        updated = storage.get_updated_at(
            sample_agent.name, sample_agent.provider.organization)
        assert updated != ''

    def test_get_created_at_nonexistent(self, storage):
        assert storage.get_created_at("unknown", "unknown_org") == ''

    # ========== agent tags ==========

    def test_get_agent_tags_empty(self, storage, sample_agent):
        storage.create(sample_agent)
        tags = storage.get_agent_tags(
            sample_agent.name, sample_agent.provider.organization)
        assert tags == []

    def test_update_agent_tags(self, storage, sample_agent):
        storage.create(sample_agent)
        result = storage.update_agent_tags(
            sample_agent.name, sample_agent.provider.organization,
            ["tag1", "tag2"])
        assert result is True
        tags = storage.get_agent_tags(
            sample_agent.name, sample_agent.provider.organization)
        assert tags == ["tag1", "tag2"]

    def test_get_agent_tags_nonexistent(self, storage):
        tags = storage.get_agent_tags("unknown", "unknown_org")
        assert tags == []

    # ========== tag entity CRUD ==========

    def test_create_tag(self, storage):
        tag = Tag(name="production")
        result = storage.create_tag(tag)
        assert result is True

    def test_create_duplicate_tag_returns_false(self, storage):
        tag = Tag(name="production")
        storage.create_tag(tag)
        tag2 = Tag(name="production")
        result = storage.create_tag(tag2)
        assert result is False

    def test_get_tag(self, storage):
        tag = Tag(name="production")
        storage.create_tag(tag)
        fetched = storage.get_tag(tag.tag_id)
        assert fetched is not None
        assert fetched.name == "production"

    def test_get_tag_nonexistent(self, storage):
        assert storage.get_tag("nonexistent-id") is None

    def test_get_tag_by_name(self, storage):
        tag = Tag(name="production")
        storage.create_tag(tag)
        fetched = storage.get_tag_by_name("production")
        assert fetched is not None
        assert fetched.tag_id == tag.tag_id

    def test_get_tag_by_name_nonexistent(self, storage):
        assert storage.get_tag_by_name("nonexistent") is None

    def test_update_tag(self, storage):
        tag = Tag(name="production")
        storage.create_tag(tag)
        tag.name = "staging"
        result = storage.update_tag(tag.tag_id, tag)
        assert result is True
        fetched = storage.get_tag(tag.tag_id)
        assert fetched.name == "staging"

    def test_update_tag_nonexistent(self, storage):
        tag = Tag(name="production")
        result = storage.update_tag("nonexistent-id", tag)
        assert result is False

    def test_delete_tag(self, storage):
        tag = Tag(name="production")
        storage.create_tag(tag)
        result = storage.delete_tag(tag.tag_id)
        assert result is True
        assert storage.get_tag(tag.tag_id) is None

    def test_delete_tag_nonexistent(self, storage):
        result = storage.delete_tag("nonexistent-id")
        assert result is False

    def test_list_tags(self, storage):
        storage.create_tag(Tag(name="tag1"))
        storage.create_tag(Tag(name="tag2"))
        tags = storage.list_tags()
        assert len(tags) == 2

    def test_list_tags_empty(self, storage):
        assert storage.list_tags() == []

    # ========== close ==========

    def test_close(self, storage):
        storage.close()
