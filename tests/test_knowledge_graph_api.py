# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
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
Tests for Knowledge Graph API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import json

from agent_registry.server import app


@pytest.fixture
def client():
    """Create test client."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_neo4j_driver():
    """Mock Neo4j driver for testing."""
    with patch('agent_registry.knowledge_graph_api.router.get_neo4j_driver') as mock_get_driver:
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_driver.return_value = mock_driver
        yield mock_driver


# Optional: Real Neo4j integration tests (requires running Neo4j instance)
@pytest.fixture
def real_neo4j_driver():
    """Create a real Neo4j driver for integration tests."""
    from neo4j import GraphDatabase
    
    # Check if Neo4j is available
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        # Verify connection
        with driver.session() as session:
            session.run("RETURN 1")
        yield driver
        driver.close()
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


@pytest.fixture
def real_client_with_neo4j(real_neo4j_driver):
    """Create test client with real Neo4j connection."""
    # Patch the get_neo4j_driver to return real driver
    with patch('agent_registry.knowledge_graph_api.router.get_neo4j_driver', return_value=real_neo4j_driver):
        with TestClient(app) as client:
            yield client


class TestIntegrationWithRealNeo4j:
    """Integration tests that verify actual data writes to Neo4j.
    
    These tests require a running Neo4j instance on localhost:7687.
    Run with: pytest tests/test_knowledge_graph_api.py::TestIntegrationWithRealNeo4j -v
    """
    
    def test_create_node_actually_writes_to_neo4j(self, real_client_with_neo4j, real_neo4j_driver):
        """Test that creating a node actually persists to Neo4j database."""
        # Create a unique test node
        test_data = {
            "labels": ["IntegrationTest"],
            "properties": {"name": f"测试节点_{id(self)}", "value": 123}
        }
        
        response = real_client_with_neo4j.post(
            "/rest/v1/registry-center/knowledge-graph/nodes",
            json=test_data
        )
        assert response.status_code == 201
        node_id = response.json()["data"]["id"]
        
        # Verify by directly querying Neo4j
        with real_neo4j_driver.session() as session:
            result = session.run(
                "MATCH (n:IntegrationTest) WHERE elementId(n) = $id RETURN n.name as name, n.value as value",
                id=node_id
            )
            record = result.single()
            assert record is not None, "Node was not persisted to Neo4j"
            assert record["name"] == test_data["properties"]["name"]
            assert record["value"] == test_data["properties"]["value"]
        
        # Cleanup
        with real_neo4j_driver.session() as session:
            session.run("MATCH (n:IntegrationTest) DETACH DELETE n")
    
    def test_update_node_actually_updates_in_neo4j(self, real_client_with_neo4j, real_neo4j_driver):
        """Test that updating a node actually modifies it in Neo4j."""
        # First create a node
        test_data = {
            "labels": ["IntegrationTest"],
            "properties": {"name": "OriginalName", "version": 1}
        }
        
        create_response = real_client_with_neo4j.post(
            "/rest/v1/registry-center/knowledge-graph/nodes",
            json=test_data
        )
        assert create_response.status_code == 201
        node_id = create_response.json()["data"]["id"]
        
        # Update the node
        update_data = {
            "labels": ["IntegrationTest"],
            "properties": {"name": "UpdatedName", "version": 2, "city": "Beijing"}
        }
        
        update_response = real_client_with_neo4j.put(
            f"/rest/v1/registry-center/knowledge-graph/nodes/{node_id}",
            json=update_data
        )
        assert update_response.status_code == 200
        
        # Verify update in Neo4j
        with real_neo4j_driver.session() as session:
            result = session.run(
                "MATCH (n:IntegrationTest) WHERE elementId(n) = $id RETURN n.name as name, n.version as version, n.city as city",
                id=node_id
            )
            record = result.single()
            assert record is not None
            assert record["name"] == "UpdatedName"
            assert record["version"] == 2
            assert record["city"] == "Beijing"
        
        # Cleanup
        with real_neo4j_driver.session() as session:
            session.run("MATCH (n:IntegrationTest) DETACH DELETE n")
    
    def test_delete_node_actually_removes_from_neo4j(self, real_client_with_neo4j, real_neo4j_driver):
        """Test that deleting a node actually removes it from Neo4j."""
        # Create a node
        test_data = {
            "labels": ["IntegrationTest"],
            "properties": {"name": "ToDelete"}
        }
        
        create_response = real_client_with_neo4j.post(
            "/rest/v1/registry-center/knowledge-graph/nodes",
            json=test_data
        )
        assert create_response.status_code == 201
        node_id = create_response.json()["data"]["id"]
        
        # Delete the node
        delete_response = real_client_with_neo4j.delete(
            f"/rest/v1/registry-center/knowledge-graph/nodes/{node_id}"
        )
        assert delete_response.status_code == 204
        
        # Verify deletion in Neo4j
        with real_neo4j_driver.session() as session:
            result = session.run(
                "MATCH (n:IntegrationTest) WHERE elementId(n) = $id RETURN count(n) as count",
                id=node_id
            )
            record = result.single()
            assert record["count"] == 0, "Node was not deleted from Neo4j"
    
    def test_relationship_persists_to_neo4j(self, real_client_with_neo4j, real_neo4j_driver):
        """Test that creating a relationship actually persists to Neo4j."""
        # Create two nodes
        node1_data = {"labels": ["IntegrationTest"], "properties": {"name": "Node1"}}
        node2_data = {"labels": ["IntegrationTest"], "properties": {"name": "Node2"}}
        
        resp1 = real_client_with_neo4j.post("/rest/v1/registry-center/knowledge-graph/nodes", json=node1_data)
        resp2 = real_client_with_neo4j.post("/rest/v1/registry-center/knowledge-graph/nodes", json=node2_data)
        
        node1_id = resp1.json()["data"]["id"]
        node2_id = resp2.json()["data"]["id"]
        
        # Create relationship
        rel_data = {
            "type": "TEST_RELATIONSHIP",
            "startNodeId": node1_id,
            "endNodeId": node2_id,
            "properties": {"since": 2024}
        }
        
        rel_response = real_client_with_neo4j.post(
            "/rest/v1/registry-center/knowledge-graph/relationships",
            json=rel_data
        )
        assert rel_response.status_code == 201
        
        # Verify relationship in Neo4j
        with real_neo4j_driver.session() as session:
            result = session.run(
                """MATCH (start:IntegrationTest)-[r:TEST_RELATIONSHIP]->(end:IntegrationTest)
                   WHERE elementId(start) = $startId AND elementId(end) = $endId
                   RETURN r.since as since""",
                startId=node1_id, endId=node2_id
            )
            record = result.single()
            assert record is not None, "Relationship was not persisted to Neo4j"
            assert record["since"] == 2024
        
        # Cleanup
        with real_neo4j_driver.session() as session:
            session.run("MATCH (n:IntegrationTest) DETACH DELETE n")

class TestNodeEndpoints:
    """Test node CRUD endpoints."""
    
    def test_list_nodes(self, client, mock_neo4j_driver):
        """Test listing all nodes."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        
        # Mock node records
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: {
            'id': 'node-1',
            'labels': ['Person'],
            'properties': {'name': '张三'}
        }.get(key)
        mock_result.__iter__ = MagicMock(return_value=iter([mock_record]))
        
        # Mock count result
        mock_count_result = MagicMock()
        mock_count_result.single.return_value = {'count': 1}
        
        mock_session.run.side_effect = [mock_result, mock_count_result]
        
        response = client.get("/rest/v1/registry-center/knowledge-graph/nodes")
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'data' in data
        assert 'pagination' in data
    
    def test_create_node(self, client, mock_neo4j_driver):
        """Test creating a node."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.single.return_value = {
            'id': 'node-1',
            'labels': ['Person'],
            'properties': {'name': '张三', 'age': 30}
        }
        mock_session.run.return_value = mock_result
        
        node_data = {
            "labels": ["Person"],
            "properties": {
                "name": "张三",
                "age": 30
            }
        }
        
        response = client.post("/rest/v1/registry-center/knowledge-graph/nodes", json=node_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['data']['id'] == 'node-1'
        assert 'Person' in data['data']['labels']
    
    def test_create_node_without_labels(self, client, mock_neo4j_driver):
        """Test creating node without labels (should fail)."""
        node_data = {
            "properties": {
                "name": "张三"
            }
        }
        
        response = client.post("/rest/v1/registry-center/knowledge-graph/nodes", json=node_data)
        
        assert response.status_code == 400
    
    def test_get_node_by_id(self, client, mock_neo4j_driver):
        """Test getting a node by ID."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.single.return_value = {
            'id': 'node-1',
            'labels': ['Person'],
            'properties': {'name': '张三'}
        }
        mock_session.run.return_value = mock_result
        
        response = client.get("/rest/v1/registry-center/knowledge-graph/nodes/node-1")
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['data']['id'] == 'node-1'
    
    def test_get_node_not_found(self, client, mock_neo4j_driver):
        """Test getting non-existent node."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result
        
        response = client.get("/rest/v1/registry-center/knowledge-graph/nodes/nonexistent")
        
        assert response.status_code == 404
    
    def test_update_node(self, client, mock_neo4j_driver):
        """Test updating a node."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        
        # Mock check result
        mock_check_result = MagicMock()
        mock_check_result.single.return_value = MagicMock()
        
        # Mock update result
        mock_update_result = MagicMock()
        mock_update_result.single.return_value = {
            'id': 'node-1',
            'labels': ['Person'],
            'properties': {'name': '李四', 'age': 31}
        }
        
        mock_session.run.side_effect = [mock_check_result, mock_update_result]
        
        update_data = {
            "properties": {
                "name": "李四",
                "age": 31
            }
        }
        
        response = client.put("/rest/v1/registry-center/knowledge-graph/nodes/node-1", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
    
    def test_delete_node(self, client, mock_neo4j_driver):
        """Test deleting a node."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.single.return_value = {'deleted': 1}
        mock_session.run.return_value = mock_result
        
        response = client.delete("/rest/v1/registry-center/knowledge-graph/nodes/node-1")
        
        assert response.status_code == 204
    
    def test_delete_node_with_relationships(self, client, mock_neo4j_driver):
        """Test deleting node with relationships (should fail without force)."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        
        # First call: delete attempt returns 0 deleted
        mock_delete_result = MagicMock()
        mock_delete_result.single.return_value = {'deleted': 0}
        
        # Second call: check for relationships returns relCount > 0
        mock_check_result = MagicMock()
        mock_check_result.single.return_value = {'relCount': 5}
        
        mock_session.run.side_effect = [mock_delete_result, mock_check_result]
        
        response = client.delete("/rest/v1/registry-center/knowledge-graph/nodes/node-1")
        
        assert response.status_code == 409


class TestRelationshipEndpoints:
    """Test relationship CRUD endpoints."""
    
    def test_list_relationships(self, client, mock_neo4j_driver):
        """Test listing all relationships."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: {
            'id': 'rel-1',
            'type': 'KNOWS',
            'startNodeId': 'node-1',
            'endNodeId': 'node-2',
            'properties': {'since': 2020}
        }.get(key)
        mock_result.__iter__ = MagicMock(return_value=iter([mock_record]))
        
        mock_count_result = MagicMock()
        mock_count_result.single.return_value = {'count': 1}
        
        mock_session.run.side_effect = [mock_result, mock_count_result]
        
        response = client.get("/rest/v1/registry-center/knowledge-graph/relationships")
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['data']) >= 0
    
    def test_create_relationship(self, client, mock_neo4j_driver):
        """Test creating a relationship."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        
        # Mock node existence checks
        mock_node_result = MagicMock()
        mock_node_result.single.return_value = MagicMock()
        
        # Mock relationship creation
        mock_rel_result = MagicMock()
        mock_rel_result.single.return_value = {
            'id': 'rel-1',
            'type': 'KNOWS',
            'startNodeId': 'node-1',
            'endNodeId': 'node-2',
            'properties': {'since': 2020}
        }
        
        mock_session.run.side_effect = [mock_node_result, mock_node_result, mock_rel_result]
        
        rel_data = {
            "type": "KNOWS",
            "startNodeId": "node-1",
            "endNodeId": "node-2",
            "properties": {
                "since": 2020
            }
        }
        
        response = client.post("/rest/v1/registry-center/knowledge-graph/relationships", json=rel_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['data']['type'] == 'KNOWS'
    
    def test_create_relationship_missing_fields(self, client, mock_neo4j_driver):
        """Test creating relationship with missing fields."""
        rel_data = {
            "type": "KNOWS",
            "startNodeId": "node-1"
            # Missing endNodeId
        }
        
        response = client.post("/rest/v1/registry-center/knowledge-graph/relationships", json=rel_data)
        
        assert response.status_code == 400
    
    def test_get_relationship_by_id(self, client, mock_neo4j_driver):
        """Test getting relationship by ID."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.single.return_value = {
            'id': 'rel-1',
            'type': 'KNOWS',
            'startNodeId': 'node-1',
            'endNodeId': 'node-2',
            'properties': {}
        }
        mock_session.run.return_value = mock_result
        
        response = client.get("/rest/v1/registry-center/knowledge-graph/relationships/rel-1")
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
    
    def test_delete_relationship(self, client, mock_neo4j_driver):
        """Test deleting a relationship."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.single.return_value = {'deleted': 1}
        mock_session.run.return_value = mock_result
        
        response = client.delete("/rest/v1/registry-center/knowledge-graph/relationships/rel-1")
        
        assert response.status_code == 204


class TestGraphEndpoint:
    """Test graph endpoint."""
    
    def test_get_graph(self, client, mock_neo4j_driver):
        """Test getting entire graph."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        
        # Mock node result
        mock_node_result = MagicMock()
        mock_node_record = MagicMock()
        mock_node_record.__getitem__ = lambda self, key: {
            'id': 'node-1',
            'labels': ['Person'],
            'properties': {'name': '张三'}
        }.get(key)
        mock_node_result.__iter__ = MagicMock(return_value=iter([mock_node_record]))
        
        # Mock relationship result
        mock_rel_result = MagicMock()
        mock_rel_record = MagicMock()
        mock_rel_record.__getitem__ = lambda self, key: {
            'id': 'rel-1',
            'type': 'KNOWS',
            'startNodeId': 'node-1',
            'endNodeId': 'node-2',
            'properties': {}
        }.get(key)
        mock_rel_result.__iter__ = MagicMock(return_value=iter([mock_rel_record]))
        
        mock_session.run.side_effect = [mock_node_result, mock_rel_result]
        
        response = client.get("/rest/v1/registry-center/knowledge-graph/graph")
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'data' in data
        assert 'nodes' in data['data']
        assert 'relationships' in data['data']



class TestBulkEndpoints:
    """Test bulk operation endpoints."""
    
    def test_bulk_create_nodes(self, client, mock_neo4j_driver):
        """Test bulk creating nodes."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        mock_result = MagicMock()
        
        # Mock multiple node creations
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: {
            'id': 'node-1',
            'labels': ['Person'],
            'properties': {'name': '张三'}
        }.get(key)
        mock_result.__iter__ = MagicMock(return_value=iter([mock_record]))
        mock_session.run.return_value = mock_result
        
        nodes_data = {
            "nodes": [
                {
                    "labels": ["Person"],
                    "properties": {"name": "张三", "age": 25}
                },
                {
                    "labels": ["Person"],
                    "properties": {"name": "李四", "age": 30}
                }
            ]
        }
        
        response = client.post("/rest/v1/registry-center/knowledge-graph/bulk/nodes", json=nodes_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['count'] >= 0
    
    def test_bulk_create_relationships(self, client, mock_neo4j_driver):
        """Test bulk creating relationships."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        
        # Mock node existence checks
        mock_node_result = MagicMock()
        mock_node_result.single.return_value = MagicMock()
        
        # Mock relationship creation
        mock_rel_result = MagicMock()
        mock_rel_result.single.return_value = {
            'id': 'rel-1',
            'type': 'KNOWS',
            'startNodeId': 'node-1',
            'endNodeId': 'node-2',
            'properties': {}
        }
        
        mock_session.run.side_effect = [mock_node_result, mock_node_result, mock_rel_result]
        
        rels_data = {
            "relationships": [
                {
                    "type": "KNOWS",
                    "startNodeId": "node-1",
                    "endNodeId": "node-2",
                    "properties": {"since": 2020}
                }
            ]
        }
        
        response = client.post("/rest/v1/registry-center/knowledge-graph/bulk/relationships", json=rels_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True


class TestImportExportEndpoints:
    """Test import/export endpoints."""
    
    def test_import_graph(self, client, mock_neo4j_driver):
        """Test importing graph data."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        
        # Mock node creation result
        mock_node_result = MagicMock()
        mock_node_result.single.return_value = {'id': 'node-1'}
        
        # Mock relationship creation result
        mock_rel_result = MagicMock()
        mock_rel_result.single.return_value = {'id': 'rel-1'}
        
        mock_session.run.side_effect = [mock_node_result, mock_rel_result]
        
        import_data = {
            "nodes": [
                {
                    "labels": ["Person"],
                    "properties": {"name": "张三", "id": 1}
                }
            ],
            "relationships": [
                {
                    "type": "KNOWS",
                    "startNodeId": "node-1",
                    "endNodeId": "node-2",
                    "properties": {"since": 2020}
                }
            ]
        }
        
        response = client.post("/rest/v1/registry-center/knowledge-graph/import", json=import_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert 'data' in data
    
    def test_export_graph(self, client, mock_neo4j_driver):
        """Test exporting graph data."""
        mock_session = mock_neo4j_driver.session.return_value.__enter__.return_value
        
        # Mock node result
        mock_node_result = MagicMock()
        mock_node_record = MagicMock()
        mock_node_record.__getitem__ = lambda self, key: {
            'id': 'node-1',
            'labels': ['Person'],
            'properties': {'name': '张三'}
        }.get(key)
        mock_node_result.__iter__ = MagicMock(return_value=iter([mock_node_record]))
        
        # Mock relationship result
        mock_rel_result = MagicMock()
        mock_rel_record = MagicMock()
        mock_rel_record.__getitem__ = lambda self, key: {
            'id': 'rel-1',
            'type': 'KNOWS',
            'startNodeId': 'node-1',
            'endNodeId': 'node-2',
            'properties': {}
        }.get(key)
        mock_rel_result.__iter__ = MagicMock(return_value=iter([mock_rel_record]))
        
        mock_session.run.side_effect = [mock_node_result, mock_rel_result]
        
        response = client.get("/rest/v1/registry-center/knowledge-graph/export")
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'data' in data
        assert 'metadata' in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
