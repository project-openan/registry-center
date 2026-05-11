# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Tag storage tests

Tests the tag storage functionality in FileStorage:
- Tags initialization
- Tags CRUD operations
- Tags persistence
- Tags file handling
"""

import pytest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock
from a2a.types import AgentCard

from agent_registry.persistence.file_storage import FileStorage


def create_sample_agent(name="test_agent", org="test_org"):
    """Helper to create sample agent"""
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


class TestFileStorageTags:
    """Test FileStorage tags functionality"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test files"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def file_path(self, temp_dir):
        """Create file path in temporary directory"""
        return os.path.join(temp_dir, "agentcard.json")
    
    @pytest.fixture
    def tags_file(self, temp_dir):
        """Create tags file path in temporary directory"""
        return os.path.join(temp_dir, "agent_tags.json")
    
    @pytest.fixture
    def metadata_file(self, temp_dir):
        """Create metadata file path in temporary directory"""
        return os.path.join(temp_dir, "agentregistry.json")
    
    @pytest.fixture
    def storage(self, file_path, metadata_file, tags_file):
        """Create FileStorage instance with test files"""
        return FileStorage(file_path, metadata_file, tags_file)
    
    @pytest.fixture
    def sample_agent(self):
        """Create sample AgentCard"""
        return create_sample_agent()
    
    # ========== Tags Initialization Tests ==========
    
    def test_tags_initialized_empty(self, storage):
        """Test that tags are initialized as empty"""
        assert hasattr(storage, '_tags_map')
        assert storage._tags_map == {}
    
    def test_tags_file_created_on_init(self, storage, tags_file):
        """Test that tags file path is set"""
        assert storage.tags_file == tags_file
    
    # ========== Tags CRUD Tests ==========
    
    def test_create_agent_initializes_empty_tags(self, storage, sample_agent):
        """Test that creating agent initializes empty tags"""
        storage.create(sample_agent)
        
        key = (sample_agent.name, sample_agent.provider.organization)
        assert key in storage._tags_map
        assert storage._tags_map[key] == []
    
    def test_get_tags_for_existing_agent(self, storage, sample_agent):
        """Test getting tags for existing agent"""
        storage.create(sample_agent)
        
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == []
    
    def test_get_tags_for_nonexistent_agent(self, storage):
        """Test getting tags for nonexistent agent"""
        tags = storage.get_tags("unknown", "unknown_org")
        assert tags == []
    
    def test_update_tags_set_mode(self, storage, sample_agent):
        """Test updating tags (full replacement)"""
        storage.create(sample_agent)
        
        new_tags = ["production", "v1.0"]
        result = storage.update_tags(
            sample_agent.name, 
            sample_agent.provider.organization,
            new_tags
        )
        
        assert result is True
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == new_tags
    
    def test_update_tags_add_mode(self, storage, sample_agent):
        """Test updating tags by adding more (using RegistryCore logic)"""
        storage.create(sample_agent)
        
        # Set initial tags
        storage.update_tags(
            sample_agent.name,
            sample_agent.provider.organization,
            ["tag1"]
        )
        
        # Add more tags - need to get current and merge
        current_tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        merged_tags = list(set(current_tags + ["tag2", "tag3"]))
        result = storage.update_tags(
            sample_agent.name,
            sample_agent.provider.organization,
            merged_tags
        )
        
        assert result is True
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert "tag1" in tags
        assert "tag2" in tags
        assert "tag3" in tags
    
    def test_update_tags_remove_mode(self, storage, sample_agent):
        """Test updating tags by removing some (using RegistryCore logic)"""
        storage.create(sample_agent)
        
        # Set initial tags
        storage.update_tags(
            sample_agent.name,
            sample_agent.provider.organization,
            ["tag1", "tag2", "tag3"]
        )
        
        # Remove tags - need to get current and filter
        current_tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        remaining_tags = [t for t in current_tags if t not in ["tag2"]]
        result = storage.update_tags(
            sample_agent.name,
            sample_agent.provider.organization,
            remaining_tags
        )
        
        assert result is True
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == ["tag1", "tag3"]
    
    def test_update_tags_for_nonexistent_agent(self, storage):
        """Test updating tags for nonexistent agent"""
        result = storage.update_tags("unknown", "unknown_org", ["tag"])
        assert result is False
    
    def test_delete_agent_removes_tags(self, storage, sample_agent):
        """Test that deleting agent removes tags"""
        storage.create(sample_agent)
        
        # Add tags
        storage.update_tags(
            sample_agent.name,
            sample_agent.provider.organization,
            ["tag1", "tag2"]
        )
        
        # Delete agent
        storage.delete(sample_agent.name, sample_agent.provider.organization)
        
        # Check tags removed
        key = (sample_agent.name, sample_agent.provider.organization)
        assert key not in storage._tags_map
    
    # ========== Tags Persistence Tests ==========
    
    def test_tags_saved_to_file(self, storage, sample_agent, tags_file):
        """Test that tags are saved to file"""
        storage.create(sample_agent)
        
        # Add tags
        tags = ["production", "v1.0", "中文"]
        storage.update_tags(
            sample_agent.name,
            sample_agent.provider.organization,
            tags
        )
        
        # Check file exists and contains tags
        assert os.path.exists(tags_file)
        with open(tags_file, 'r', encoding='utf-8') as f:
            tags_data = json.load(f)
        
        assert len(tags_data) > 0
        found = False
        for entry in tags_data:
            if entry["agent_name"] == sample_agent.name and \
               entry["organization"] == sample_agent.provider.organization:
                assert entry["tags"] == tags
                found = True
                break
        assert found
    
    def test_tags_loaded_from_file(self, file_path, metadata_file, tags_file, sample_agent):
        """Test that tags are loaded from file on init"""
        # Create storage and add tags
        storage1 = FileStorage(file_path, metadata_file, tags_file)
        storage1.create(sample_agent)
        tags = ["tag1", "tag2"]
        storage1.update_tags(
            sample_agent.name,
            sample_agent.provider.organization,
            tags
        )
        
        # Create new storage instance (simulates restart)
        storage2 = FileStorage(file_path, metadata_file, tags_file)
        
        # Check tags loaded
        loaded_tags = storage2.get_tags(
            sample_agent.name,
            sample_agent.provider.organization
        )
        assert loaded_tags == tags
    
    def test_tags_persistence_after_multiple_operations(self, storage, sample_agent, tags_file):
        """Test tags persistence after multiple operations"""
        storage.create(sample_agent)
        
        # Multiple operations
        storage.update_tags(sample_agent.name, sample_agent.provider.organization, 
                          ["tag1", "tag2"])
        
        # Add tags manually (get current + merge)
        current = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        merged = list(set(current + ["tag3"]))
        storage.update_tags(sample_agent.name, sample_agent.provider.organization, merged)
        
        # Remove tags manually (get current + filter)
        current = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        remaining = [t for t in current if t not in ["tag1"]]
        storage.update_tags(sample_agent.name, sample_agent.provider.organization, remaining)
        
        # Reload storage
        storage2 = FileStorage(storage.file_path, storage.metadata_file, storage.tags_file)
        
        # Check final state
        tags = storage2.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == ["tag2", "tag3"]
    
    # ========== Find by Tag Tests ==========
    
    def test_find_by_tag(self, storage):
        """Test finding agents by tag"""
        # Create multiple agents
        agent1 = create_sample_agent("agent1", "org1")
        agent2 = create_sample_agent("agent2", "org2")
        
        storage.create(agent1)
        storage.create(agent2)
        
        # Add tags
        storage.update_tags(agent1.name, agent1.provider.organization, 
                          ["production", "v1.0"])
        storage.update_tags(agent2.name, agent2.provider.organization,
                          ["production", "v2.0"])
        
        # Find by tag
        agents = storage.find_by_tag("production")
        assert len(agents) == 2
        
        agents_v1 = storage.find_by_tag("v1.0")
        assert len(agents_v1) == 1
    
    def test_find_by_tag_empty_result(self, storage, sample_agent):
        """Test finding agents by nonexistent tag"""
        storage.create(sample_agent)
        storage.update_tags(sample_agent.name, sample_agent.provider.organization,
                          ["tag1"])
        
        agents = storage.find_by_tag("nonexistent_tag")
        assert agents == []
    
    # ========== Edge Cases Tests ==========
    
    def test_update_tags_duplicate_add(self, storage, sample_agent):
        """Test adding duplicate tags"""
        storage.create(sample_agent)
        
        # Set initial tags
        storage.update_tags(sample_agent.name, sample_agent.provider.organization,
                          ["tag1"])
        
        # Add duplicate - need to merge manually
        current = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        merged = list(set(current + ["tag1", "tag2"]))
        storage.update_tags(sample_agent.name, sample_agent.provider.organization, merged)
        
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        # Should have no duplicates
        assert tags.count("tag1") == 1
        assert "tag2" in tags
    
    def test_update_tags_remove_nonexistent(self, storage, sample_agent):
        """Test removing nonexistent tag"""
        storage.create(sample_agent)
        
        storage.update_tags(sample_agent.name, sample_agent.provider.organization,
                          ["tag1"])
        
        # Remove nonexistent tag manually
        current = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        remaining = [t for t in current if t not in ["tag2"]]
        storage.update_tags(sample_agent.name, sample_agent.provider.organization, remaining)
        
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == ["tag1"]
    
    def test_tags_with_chinese_characters(self, storage, sample_agent):
        """Test tags with Chinese characters"""
        storage.create(sample_agent)
        
        chinese_tags = ["生产环境", "测试.标签", "中文_Tag"]
        storage.update_tags(sample_agent.name, sample_agent.provider.organization,
                          chinese_tags)
        
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == chinese_tags
    
    def test_tags_with_dot_characters(self, storage, sample_agent):
        """Test tags with dot characters"""
        storage.create(sample_agent)
        
        dot_tags = ["v1.0", "v2.0.beta", "app.service"]
        storage.update_tags(sample_agent.name, sample_agent.provider.organization,
                          dot_tags)
        
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == dot_tags
    
    def test_clear_all_tags(self, storage, sample_agent):
        """Test clearing all tags"""
        storage.create(sample_agent)
        
        storage.update_tags(sample_agent.name, sample_agent.provider.organization,
                          ["tag1", "tag2"])
        
        # Clear
        storage.update_tags(sample_agent.name, sample_agent.provider.organization,
                          [])
        
        tags = storage.get_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == []


class TestFileStorageTagsFileFormat:
    """Test tags file format and structure"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_tags_file_format(self, temp_dir):
        """Test tags file JSON format"""
        file_path = os.path.join(temp_dir, "agentcard.json")
        tags_file = os.path.join(temp_dir, "agent_tags.json")
        metadata_file = os.path.join(temp_dir, "agentregistry.json")
        
        storage = FileStorage(file_path, metadata_file, tags_file)
        
        agent = create_sample_agent()
        
        storage.create(agent)
        storage.update_tags(agent.name, agent.provider.organization,
                          ["tag1", "tag2"])
        
        # Read file
        with open(tags_file, 'r', encoding='utf-8') as f:
            tags_data = json.load(f)
        
        # Check format
        assert isinstance(tags_data, list)
        entry = tags_data[0]
        assert "agent_name" in entry
        assert "organization" in entry
        assert "tags" in entry
        assert isinstance(entry["tags"], list)
    
    def test_tags_file_empty_initially(self, temp_dir):
        """Test tags file is empty initially"""
        file_path = os.path.join(temp_dir, "agentcard.json")
        tags_file = os.path.join(temp_dir, "agent_tags.json")
        metadata_file = os.path.join(temp_dir, "agentregistry.json")
        
        storage = FileStorage(file_path, metadata_file, tags_file)
        
        # File may not exist or be empty
        if os.path.exists(tags_file):
            with open(tags_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if content:
                    tags_data = json.load(f)
                    assert tags_data == []