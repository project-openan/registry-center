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
Tag handler tests

Tests the tag handler classes for UDS internal service:
- TagAddHandler
- TagRemoveHandler
- TagUpdateHandler
- TagGetHandler
- TagListHandler
"""

import pytest
from unittest.mock import Mock, MagicMock
from a2a.types import AgentCard

from agent_registry.internal.handlers.tag_handler import (
    TagAddHandler, TagRemoveHandler, TagUpdateHandler,
    TagGetHandler, TagListHandler
)


def create_mock_agent(name, organization):
    """Helper to create mock agent"""
    agent = Mock(spec=AgentCard)
    agent.name = name
    agent.provider = Mock()
    agent.provider.organization = organization
    agent.description = f"{name} description"
    return agent


class TestTagAddHandler:
    """Test TagAddHandler"""
    
    @pytest.fixture
    def handler(self):
        """Create TagAddHandler instance"""
        return TagAddHandler()
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock registry"""
        registry = Mock()
        registry.find_by_key = Mock(return_value=Mock(name="test_agent"))
        registry.get_tags = Mock(return_value=["existing_tag"])
        registry.add_tags = Mock(return_value=True)
        return registry
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        return Mock()
    
    def test_handle_add_tags_success(self, handler, mock_registry, mock_config):
        """Test successful tag addition"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["production", "v1.0"]
        }
        
        mock_registry.get_tags.return_value = ["production", "v1.0"]
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert result["message"] == "Tags added successfully"
        assert result["data"]["tags"] == ["production", "v1.0"]
        mock_registry.add_tags.assert_called_once()
    
    def test_handle_add_tags_missing_params(self, handler, mock_registry, mock_config):
        """Test tag addition with missing parameters"""
        params = {
            "tags": ["production"]
        }
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "Missing required params" in result["error"]
    
    def test_handle_add_tags_agent_not_found(self, handler, mock_registry, mock_config):
        """Test tag addition when agent not found"""
        params = {
            "agent_name": "unknown_agent",
            "organization": "test_org",
            "tags": ["production"]
        }
        
        mock_registry.find_by_key.return_value = None
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()
    
    def test_handle_add_tags_invalid_tag_format(self, handler, mock_registry, mock_config):
        """Test tag addition with invalid tag format"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["tag@invalid"]
        }
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "invalid" in result["error"].lower()
    
    def test_handle_add_tags_empty_tags(self, handler, mock_registry, mock_config):
        """Test tag addition with empty tags list"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": []
        }
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "No tags provided" in result["error"]


class TestTagRemoveHandler:
    """Test TagRemoveHandler"""
    
    @pytest.fixture
    def handler(self):
        """Create TagRemoveHandler instance"""
        return TagRemoveHandler()
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock registry"""
        registry = Mock()
        registry.find_by_key = Mock(return_value=Mock(name="test_agent"))
        registry.get_tags = Mock(return_value=["tag1", "tag2", "tag3"])
        registry.remove_tags = Mock(return_value=True)
        return registry
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        return Mock()
    
    def test_handle_remove_tags_success(self, handler, mock_registry, mock_config):
        """Test successful tag removal"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["tag1", "tag2"]
        }
        
        mock_registry.get_tags.return_value = ["tag3"]
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert result["message"] == "Tags removed successfully"
        assert result["data"]["tags"] == ["tag3"]
        mock_registry.remove_tags.assert_called_once()
    
    def test_handle_remove_tags_missing_params(self, handler, mock_registry, mock_config):
        """Test tag removal with missing parameters"""
        params = {
            "tags": ["tag1"]
        }
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "Missing required params" in result["error"]
    
    def test_handle_remove_tags_agent_not_found(self, handler, mock_registry, mock_config):
        """Test tag removal when agent not found"""
        params = {
            "agent_name": "unknown_agent",
            "organization": "test_org",
            "tags": ["tag1"]
        }
        
        mock_registry.find_by_key.return_value = None
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestTagUpdateHandler:
    """Test TagUpdateHandler"""
    
    @pytest.fixture
    def handler(self):
        """Create TagUpdateHandler instance"""
        return TagUpdateHandler()
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock registry"""
        registry = Mock()
        registry.find_by_key = Mock(return_value=Mock(name="test_agent"))
        registry.get_tags = Mock(return_value=["new_tag1", "new_tag2"])
        registry.update_tags = Mock(return_value=True)
        return registry
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        return Mock()
    
    def test_handle_update_tags_success(self, handler, mock_registry, mock_config):
        """Test successful tag update"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["new_tag1", "new_tag2"]
        }
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert result["message"] == "Tags updated successfully"
        assert result["data"]["tags"] == ["new_tag1", "new_tag2"]
        mock_registry.update_tags.assert_called_once()
    
    def test_handle_update_tags_clear_all(self, handler, mock_registry, mock_config):
        """Test clearing all tags with update"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": []
        }
        
        mock_registry.get_tags.return_value = []
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert result["message"] == "Tags updated successfully"
        assert result["data"]["tags"] == []


class TestTagGetHandler:
    """Test TagGetHandler"""
    
    @pytest.fixture
    def handler(self):
        """Create TagGetHandler instance"""
        return TagGetHandler()
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock registry"""
        registry = Mock()
        registry.find_by_key = Mock(return_value=Mock(name="test_agent"))
        registry.get_tags = Mock(return_value=["tag1", "tag2"])
        return registry
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        return Mock()
    
    def test_handle_get_tags_success(self, handler, mock_registry, mock_config):
        """Test successful tag retrieval"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org"
        }
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert result["message"] == "Tags retrieved successfully"
        assert result["data"]["tags"] == ["tag1", "tag2"]
    
    def test_handle_get_tags_empty(self, handler, mock_registry, mock_config):
        """Test tag retrieval when agent has no tags"""
        params = {
            "agent_name": "test_agent",
            "organization": "test_org"
        }
        
        mock_registry.get_tags.return_value = []
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert result["data"]["tags"] == []
    
    def test_handle_get_tags_agent_not_found(self, handler, mock_registry, mock_config):
        """Test tag retrieval when agent not found"""
        params = {
            "agent_name": "unknown_agent",
            "organization": "test_org"
        }
        
        mock_registry.find_by_key.return_value = None
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestTagListHandler:
    """Test TagListHandler"""
    
    @pytest.fixture
    def handler(self):
        """Create TagListHandler instance"""
        return TagListHandler()
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock registry"""
        registry = Mock()
        # Return mock AgentCard objects
        agent1 = create_mock_agent("agent1", "org1")
        agent2 = create_mock_agent("agent2", "org2")
        registry.find_by_tag = Mock(return_value=[agent1, agent2])
        return registry
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        return Mock()
    
    def test_handle_list_tags_success(self, handler, mock_registry, mock_config):
        """Test successful tag listing"""
        params = {
            "tag": "production"
        }
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert "Found 2 agents" in result["message"]
        assert result["data"]["count"] == 2
        assert len(result["data"]["agents"]) == 2
    
    def test_handle_list_tags_empty(self, handler, mock_registry, mock_config):
        """Test tag listing when no agents have the tag"""
        params = {
            "tag": "nonexistent_tag"
        }
        
        mock_registry.find_by_tag.return_value = []
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is True
        assert result["data"]["count"] == 0
        assert result["data"]["agents"] == []
    
    def test_handle_list_tags_missing_param(self, handler, mock_registry, mock_config):
        """Test tag listing with missing tag parameter"""
        params = {}
        
        result = handler.handle(params, mock_registry, mock_config)
        
        assert result["success"] is False
        assert "Missing required param" in result["error"]


class TestTagHandlerIntegration:
    """Integration tests for tag handlers"""
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock registry with all methods"""
        registry = Mock()
        registry.find_by_key = Mock(return_value=Mock(name="test_agent"))
        registry.get_tags = Mock(return_value=[])
        registry.add_tags = Mock(return_value=True)
        registry.remove_tags = Mock(return_value=True)
        registry.update_tags = Mock(return_value=True)
        registry.find_by_tag = Mock(return_value=[])
        return registry
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        return Mock()
    
    def test_add_then_get_tags(self, mock_registry, mock_config):
        """Test adding tags then retrieving them"""
        add_handler = TagAddHandler()
        get_handler = TagGetHandler()
        
        # Add tags
        add_params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["production", "v1.0"]
        }
        mock_registry.get_tags.return_value = ["production", "v1.0"]
        add_result = add_handler.handle(add_params, mock_registry, mock_config)
        assert add_result["success"] is True
        
        # Get tags
        get_params = {
            "agent_name": "test_agent",
            "organization": "test_org"
        }
        get_result = get_handler.handle(get_params, mock_registry, mock_config)
        assert get_result["success"] is True
        assert get_result["data"]["tags"] == ["production", "v1.0"]
    
    def test_update_then_remove_tags(self, mock_registry, mock_config):
        """Test updating tags then removing one"""
        update_handler = TagUpdateHandler()
        remove_handler = TagRemoveHandler()
        
        # Update tags
        update_params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["tag1", "tag2", "tag3"]
        }
        mock_registry.get_tags.return_value = ["tag1", "tag2", "tag3"]
        update_result = update_handler.handle(update_params, mock_registry, mock_config)
        assert update_result["success"] is True
        
        # Remove tag
        remove_params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["tag2"]
        }
        mock_registry.get_tags.return_value = ["tag1", "tag3"]
        remove_result = remove_handler.handle(remove_params, mock_registry, mock_config)
        assert remove_result["success"] is True
        assert "tag2" not in remove_result["data"]["tags"]