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
Tests for agent_to_graph.watcher.agent2graph.
"""

from unittest.mock import patch

import pytest
from neo4j.graph import Graph, Node, Relationship

from agent_registry.agent_to_graph.watcher import (
    agent2graph,
    process,
    syncData,
    updateGraph,
    updateNode,
    updateRelationship,
    GOVERNANCE_T_EXTENSION_URI,
)


def _make_node(label, name, properties=None, element_id=""):
    """Build a Neo4j Node with a single label and name property."""
    props = dict(properties or {})
    props.setdefault("name", name)
    return Node(
        graph=None,
        id_=0,
        element_id=element_id,
        n_labels=frozenset({label}),
        properties=props,
    )


def _make_relationship(rel_type, start, end):
    """Build a Neo4j Relationship of the given type between start and end nodes."""
    graph = Graph()
    rel_cls = graph.relationship_type(rel_type)
    relationship = rel_cls(
        graph=graph,
        id_=0,
        element_id="",
        properties={"type": rel_type, "targetNode": end["name"]},
    )
    relationship._start_node = start
    relationship._end_node = end
    return relationship


def _governance_ext(business=None, role=None):
    ext: dict = {"uri": GOVERNANCE_T_EXTENSION_URI}
    if business is not None or role is not None:
        ext["params"] = {
            "business": business or [],
            "role": role or [],
        }
    return [ext]


def _make_agent_card(name="fault-agent-01", organization="wireless", extensions=None,
                     business=None, role=None):
    """Build an AgentCard with optional Governance-T extension and tags."""
    from a2a.types import AgentCard

    has_tags = business is not None or role is not None
    if extensions is None:
        exts = _governance_ext(business, role) if has_tags else []
    else:
        exts = [dict(e) for e in extensions]
        if has_tags:
            for e in exts:
                if e.get("uri") == GOVERNANCE_T_EXTENSION_URI:
                    e["params"] = {
                        "business": business or [],
                        "role": role or [],
                    }
                    break
    card = {
        "name": name,
        "provider": {"organization": organization, "url": "https://test.com"},
        "description": "test agent",
        "version": "1.0.0",
        "capabilities": {"extensions": exts},
    }
    return AgentCard(**card)


class TestAgent2Graph:
    def test_returns_empty_when_no_extensions(self):
        nodes, relationships = agent2graph(_make_agent_card(extensions=[]))
        assert nodes == []
        assert relationships == []

    def test_returns_empty_when_extension_absent(self):
        agent = _make_agent_card(
            extensions=[{"uri": "https://example.com/other"}],
            business=["fault_management"],
            role=["operator"],
        )
        nodes, relationships = agent2graph(agent)
        assert nodes == []
        assert relationships == []

    def test_agent_node_only_when_no_governance_tags(self):
        nodes, relationships = agent2graph(_make_agent_card(extensions=_governance_ext()))
        assert len(nodes) == 1
        assert set(nodes[0].labels) == {"agent"}
        assert nodes[0]["name"] == "fault-agent-01"
        assert nodes[0]["organization"] == "wireless"
        assert relationships == []

    def test_creates_business_and_role_nodes_and_relationships(self):
        nodes, relationships = agent2graph(
            _make_agent_card(
                extensions=_governance_ext(),
                business=["fault_management", "wireless"],
                role=["operator", "tester"],
            )
        )
        assert len(nodes) == 1 + 2 + 2
        assert len(relationships) == 4

        agent_node = nodes[0]
        assert set(agent_node.labels) == {"agent"}

        business_nodes = [n for n in nodes if "business" in n.labels]
        role_nodes = [n for n in nodes if "role" in n.labels]
        assert [n["name"] for n in business_nodes] == ["fault_management", "wireless"]
        assert [n["name"] for n in role_nodes] == ["operator", "tester"]

        rel_types = {r.type for r in relationships}
        assert rel_types == {"handles_business", "has_role"}

        for rel in relationships:
            assert rel._start_node is agent_node
            assert rel["type"] == rel.type
            assert rel["targetNode"] == rel._end_node["name"]

    def test_business_relationship_type_and_target(self):
        nodes, relationships = agent2graph(
            _make_agent_card(
                extensions=_governance_ext(),
                business=["fault_management"],
                role=[],
            )
        )
        assert len(relationships) == 1
        rel = relationships[0]
        assert rel.type == "handles_business"
        assert rel["type"] == "handles_business"
        assert rel["targetNode"] == "fault_management"
        assert rel._end_node["name"] == "fault_management"
        assert "business" in rel._end_node.labels

    def test_role_relationship_type_and_target(self):
        nodes, relationships = agent2graph(
            _make_agent_card(
                extensions=_governance_ext(),
                business=[],
                role=["operator"],
            )
        )
        assert len(relationships) == 1
        rel = relationships[0]
        assert rel.type == "has_role"
        assert rel["type"] == "has_role"
        assert rel["targetNode"] == "operator"
        assert rel._end_node["name"] == "operator"
        assert "role" in rel._end_node.labels


class TestSyncData:
    @pytest.fixture(autouse=True)
    def _mock_graph_calls(self):
        with (
            patch(
                "agent_registry.agent_to_graph.watcher.create_node",
                side_effect=lambda labels, properties: _make_node(
                    labels[0], properties.get("name"), properties
                ),
            ),
            patch("agent_registry.agent_to_graph.watcher.create_relationship"),
            patch("agent_registry.agent_to_graph.watcher.delete_relationship"),
            patch("agent_registry.agent_to_graph.watcher.delete_node"),
        ):
            yield

    def test_empty_cards_returns_empty_plan(self):
        plan = syncData(agentCards=[], existNodes=[], existRelationships=[])
        assert plan["create_nodes"] == []
        assert plan["delete_nodes"] == []
        assert plan["create_relationships"] == []
        assert plan["delete_relationships"] == []

    def test_syncs_multiple_agents_into_expected_state(self):
        cards = [
            _make_agent_card(
                name="agent-a",
                organization="wireless",
                extensions=_governance_ext(),
                business=["fault_management"],
                role=["operator"],
            ),
            _make_agent_card(
                name="agent-b",
                organization="transport",
                extensions=_governance_ext(),
                business=["wireless"],
                role=["tester"],
            ),
        ]
        plan = syncData(agentCards=cards, existNodes=[], existRelationships=[])

        assert plan["delete_nodes"] == []
        assert len(plan["delete_relationships"]) == 0

        names = {n["name"] for n in plan["create_nodes"]}
        assert names == {
            "agent-a",
            "agent-b",
            "fault_management",
            "wireless",
            "operator",
            "tester",
        }

    def test_sync_reconciles_with_existing_state(self):
        existing_agent = _make_node(
            "agent", "agent-a", {"organization": "wireless"}, element_id="n-agent-a"
        )
        existing_agent_name = existing_agent["name"]
        cards = [
            _make_agent_card(
                name="agent-a",
                organization="wireless",
                extensions=_governance_ext(),
                business=["fault_management"],
                role=["operator"],
            ),
        ]
        plan = syncData(
            agentCards=cards,
            existNodes=[existing_agent],
            existRelationships=[],
        )

        assert plan["delete_nodes"] == []
        assert existing_agent_name not in {n["name"] for n in plan["create_nodes"]}
        assert "fault_management" in {n["name"] for n in plan["create_nodes"]}
        assert "operator" in {n["name"] for n in plan["create_nodes"]}

    def test_sync_deletes_agents_not_in_cards(self):
        stale = _make_node("agent", "stale-agent", {"organization": "wireless"})
        plan = syncData(agentCards=[], existNodes=[stale], existRelationships=[])
        assert plan["delete_nodes"] == [stale]


class TestProcess:
    @pytest.fixture(autouse=True)
    def _mock_external_calls(self):
        with (
            patch(
                "agent_registry.agent_to_graph.watcher.list_nodes",
                return_value=[],
            ),
            patch(
                "agent_registry.agent_to_graph.watcher.list_relationships",
                return_value=[],
            ),
            patch(
                "agent_registry.agent_to_graph.watcher.list_agents",
                return_value=[],
            ),
            patch(
                "agent_registry.agent_to_graph.watcher.create_node",
                side_effect=lambda labels, properties: _make_node(
                    labels[0], properties.get("name"), properties
                ),
            ),
            patch("agent_registry.agent_to_graph.watcher.create_relationship"),
            patch("agent_registry.agent_to_graph.watcher.delete_relationship"),
            patch("agent_registry.agent_to_graph.watcher.delete_node"),
        ):
            yield

    def test_process_syncs_agents_into_graph(self):
        from a2a.types import AgentCard

        card = AgentCard(
            **{
                "name": "fault-agent-01",
                "description": "test agent",
                "version": "1.0.0",
                "provider": {"organization": "wireless", "url": "https://test.com"},
                "capabilities": {
                    "extensions": [
                        {
                            "uri": GOVERNANCE_T_EXTENSION_URI,
                            "params": {
                                "business": ["fault_management"],
                                "role": ["operator"],
                            },
                        }
                    ]
                },
            }
        )
        with patch(
            "agent_registry.agent_to_graph.watcher.list_agents",
            return_value=[card],
        ):
            plan = process()

        assert plan["delete_nodes"] == []
        names = {n["name"] for n in plan["create_nodes"]}
        assert names == {"fault-agent-01", "fault_management", "operator"}


class TestUpdateGraph:
    @pytest.fixture(autouse=True)
    def _mock_graph_calls(self):
        with (
            patch(
                "agent_registry.agent_to_graph.watcher.create_node",
                side_effect=lambda labels, properties: _make_node(
                    labels[0], properties.get("name"), properties
                ),
            ),
            patch("agent_registry.agent_to_graph.watcher.create_relationship"),
            patch("agent_registry.agent_to_graph.watcher.delete_relationship"),
            patch("agent_registry.agent_to_graph.watcher.delete_node"),
        ):
            yield

    def test_no_gap_returns_empty_plan(self):
        node = _make_node("agent", "fault-agent-01", {"organization": "wireless"})
        rel = _make_relationship("has_role", node, _make_node("role", "operator"))
        plan = updateGraph(
            expectNodes=[node],
            expectRelationships=[rel],
            existNodes=[node],
            existRelationships=[rel],
        )
        assert plan["create_nodes"] == []
        assert plan["delete_nodes"] == []
        assert plan["create_relationships"] == []
        assert plan["delete_relationships"] == []

    def test_creates_missing_nodes(self):
        expected = _make_node("business", "fault_management")
        plan = updateGraph(
            expectNodes=[expected],
            expectRelationships=[],
            existNodes=[],
            existRelationships=[],
        )
        assert plan["create_nodes"] == [expected]
        assert plan["delete_nodes"] == []
        assert [n["name"] for n in plan["createdNodes"]] == ["fault_management"]

    def test_created_nodes_contains_only_successful_creates(self):
        expected = _make_node("business", "fault_management")
        with patch(
            "agent_registry.agent_to_graph.watcher.create_node",
            return_value=None,
        ):
            plan = updateGraph(
                expectNodes=[expected],
                expectRelationships=[],
                existNodes=[],
                existRelationships=[],
            )
        assert plan["create_nodes"] == [expected]
        assert plan["createdNodes"] == []

    def test_skips_nodes_that_already_exist(self):
        existing = _make_node("agent", "fault-agent-01", {"organization": "wireless", "version": "1.0"})
        expected = _make_node("agent", "fault-agent-01", {"organization": "wireless", "version": "2.0"})
        plan = updateGraph(
            expectNodes=[expected],
            expectRelationships=[],
            existNodes=[existing],
            existRelationships=[],
        )
        assert plan["create_nodes"] == []
        assert plan["delete_nodes"] == []

    def test_deletes_nodes_no_longer_expected(self):
        existing = _make_node("role", "tester")
        plan = updateGraph(
            expectNodes=[],
            expectRelationships=[],
            existNodes=[existing],
            existRelationships=[],
        )
        assert plan["delete_nodes"] == [existing]
        assert plan["create_nodes"] == []

    def test_creates_and_deletes_relationships(self):
        agent = _make_node("agent", "fault-agent-01")
        expected_role = _make_node("role", "operator", element_id="n-op")
        existing_role = _make_node("role", "tester", element_id="n-test")

        expect_rel = _make_relationship("has_role", agent, expected_role)
        exist_rel = _make_relationship("has_role", agent, existing_role)

        plan = updateGraph(
            expectNodes=[agent, expected_role],
            expectRelationships=[expect_rel],
            existNodes=[agent, existing_role],
            existRelationships=[exist_rel],
        )
        assert plan["create_relationships"] == [expect_rel]
        assert plan["delete_relationships"] == [exist_rel]
        assert plan["create_nodes"] == [expected_role]
        assert plan["delete_nodes"] == [existing_role]


class TestUpdateNode:
    def test_returns_missing_nodes_as_insert(self):
        expected = _make_node("business", "fault_management")
        result = updateNode(expectNodes=[expected], existNodes=[])
        assert result == {"insert_nodes": [expected], "update_nodes": [], "delete_nodes": []}

    def test_returns_nodes_with_different_properties(self):
        existing = _make_node("agent", "fault-agent-01", {"organization": "wireless", "version": "1.0"})
        expected = _make_node("agent", "fault-agent-01", {"organization": "wireless", "version": "2.0"})
        result = updateNode(expectNodes=[expected], existNodes=[existing])
        assert result == {"insert_nodes": [], "update_nodes": [expected], "delete_nodes": []}

    def test_skips_identical_nodes(self):
        node = _make_node("role", "operator", {"organization": "wireless"})
        result = updateNode(expectNodes=[node], existNodes=[node])
        assert result == {"insert_nodes": [], "update_nodes": [], "delete_nodes": []}

    def test_returns_delete_for_nodes_with_different_identity(self):
        existing = _make_node("agent", "fault-agent-01", {"organization": "wireless"})
        expected = _make_node("agent", "fault-agent-01", {"organization": "core"})
        result = updateNode(expectNodes=[expected], existNodes=[existing])
        assert result == {"insert_nodes": [expected], "update_nodes": [], "delete_nodes": [existing]}

    def test_returns_nodes_to_delete(self):
        existing = _make_node("role", "tester")
        result = updateNode(expectNodes=[], existNodes=[existing])
        assert result == {"insert_nodes": [], "update_nodes": [], "delete_nodes": [existing]}


class TestUpdateRelationship:
    def test_no_gap_returns_empty(self):
        node = _make_node("agent", "fault-agent-01")
        rel = _make_relationship("has_role", node, _make_node("role", "operator"))
        result = updateRelationship(
            allNodes=[node],
            expectRelationships=[rel],
            existRelationships=[rel],
        )
        assert result == {"create_relationships": [], "delete_relationships": []}

    def test_creates_missing_relationships(self):
        agent = _make_node("agent", "fault-agent-01")
        role = _make_node("role", "operator")
        expect_rel = _make_relationship("has_role", agent, role)
        result = updateRelationship(
            allNodes=[agent, role],
            expectRelationships=[expect_rel],
            existRelationships=[],
        )
        assert result["create_relationships"] == [expect_rel]
        assert result["delete_relationships"] == []

    def test_deletes_relationships_no_longer_expected(self):
        agent = _make_node("agent", "fault-agent-01")
        role = _make_node("role", "operator")
        exist_rel = _make_relationship("has_role", agent, role)
        result = updateRelationship(
            allNodes=[agent, role],
            expectRelationships=[],
            existRelationships=[exist_rel],
        )
        assert result["create_relationships"] == []
        assert result["delete_relationships"] == [exist_rel]

    def test_resolves_endpoints_from_all_nodes(self):
        agent = _make_node("agent", "fault-agent-01")
        role = _make_node("role", "operator")
        rel = _make_relationship("has_role", agent, role)
        result = updateRelationship(
            allNodes=[agent, role],
            expectRelationships=[rel],
            existRelationships=[],
        )
        created = result["create_relationships"][0]
        assert created._start_node is agent
        assert created._end_node is role
