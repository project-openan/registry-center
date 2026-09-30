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
Agent to Graph Watcher.

Monitors agent data changes and syncs them to the knowledge graph.
This module is initialized during system startup.
"""

from typing import Any, Dict, List, Optional, Tuple

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict
from loguru import logger
from neo4j.graph import Graph, Node, Relationship

from agent_registry.agent_to_graph.agent import list_agents
from agent_registry.agent_to_graph.graph import (
    create_node,
    create_relationship,
    delete_node,
    delete_relationship,
    list_nodes,
    list_relationships,
    update_node,
)

from agent_registry.agent_to_graph.graph_extension import extension_param_list
from common.util.app_config import get_conf


def start_watching():
    """
    Start monitoring agent data changes.

    Called during system startup to begin watching for agent data changes.
    The log is printed only when the 'agent_to_graph_enabled' config is set to true.
    """
    enabled = str(get_conf().get("agent_to_graph_enabled", "false")).lower() == 'true'
    if enabled:
        logger.info("开始监控agent 数据变化")


GOVERNANCE_T_EXTENSION_URI = (
    "https://github.com/project-openan/registry-center/extensions/knowledge-graph-agent-discovery/v1"
)


def agent2graph(agentCard: AgentCard) -> Tuple[List[Node], List[Relationship]]:
    """
    Convert an AgentCard to Neo4j nodes and relationships.

    The agentCard is an ``a2a.types.AgentCard`` object. One agent object maps
    to one node with label "agent" and properties "name" and "organization".

    When the agentCard's capabilities.extensions includes the Governance-T
    extension, the business and role tags are extracted from the extension's
    ``params`` (``params["business"]`` and ``params["role"]``), one node is
    created for each business and role, and the following relationships are
    created:
    - agent -> business with type "handles_business"
    - agent -> role with type "has_role"

    The conversion is skipped if the agentCard's capabilities.extensions does
    not include the Governance-T extension, in which case two empty lists are
    returned.

    Args:
        agentCard: The AgentCard to convert.

    Returns:
        A tuple of (nodes, relationships), where nodes is a list of Neo4j
        Node objects and relationships is a list of Neo4j Relationship objects.
    """
    extensions = (agentCard.capabilities.extensions if agentCard.capabilities else None) or []
    if not any(ext.uri == GOVERNANCE_T_EXTENSION_URI for ext in extensions):
        organization = (agentCard.provider.organization if agentCard.provider else None)
        logger.debug(f"Agent {agentCard.name} in organization {organization} does not support the Governance-T extension")
        return [], []

    agent_node = Node(
        graph=None,
        id_=0,
        element_id="",
        n_labels=frozenset({"agent"}),
        properties={
            "name": agentCard.name,
            "organization": (agentCard.provider.organization if agentCard.provider else None),
        },
    )
    nodes = [agent_node]

    params = {}
    for ext in extensions:
        if ext.uri == GOVERNANCE_T_EXTENSION_URI and ext.params:
            params = MessageToDict(ext.params, preserving_proto_field_name=True)
            break

    graph = Graph()
    relationships: List[Relationship] = []

    for param in extension_param_list:
        tags = params.get(param.key) or []
        for tag in tags:
            tag_node = Node(
                graph=None,
                id_=0,
                element_id="",
                n_labels=frozenset({param.node_label}),
                properties={"name": tag},
            )
            nodes.append(tag_node)
            rel_cls = graph.relationship_type(param.relationship_type)
            relationship = rel_cls(
                graph=graph,
                id_=0,
                element_id="",
                properties={
                    "type": param.relationship_type,
                    "targetNode": tag,
                },
            )
            relationship._start_node = agent_node
            relationship._end_node = tag_node
            relationships.append(relationship)

    return nodes, relationships


def syncData(
    agentCards: List[AgentCard],
    existNodes: List[Node],
    existRelationships: List[Relationship],
) -> Dict[str, Any]:
    """
    Synchronize agent cards to the knowledge graph.

    For each agent card in ``agentCards``, the ``agent2graph`` conversion is
    applied and the resulting nodes and relationships are merged into the
    expected state. The expected state is then reconciled with the existing
    state via ``updateGraph``.

    Args:
        agentCards: The list of AgentCard objects to synchronize.
        existNodes: The nodes currently stored in the knowledge graph.
        existRelationships: The relationships currently stored in the
            knowledge graph.

    Returns:
        The reconciliation plan returned by ``updateGraph``.
    """
    logger.info("Start to sync data")
    expectNodes: List[Node] = []
    expectRelationships: List[Relationship] = []

    for agentCard in agentCards:
        nodes, relationships = agent2graph(agentCard)
        expectNodes.extend(nodes)
        expectRelationships.extend(relationships)

    return updateGraph(
        expectNodes=expectNodes,
        expectRelationships=expectRelationships,
        existNodes=existNodes,
        existRelationships=existRelationships,
    )


def process() -> Dict[str, Any]:
    """
    Synchronize all registered agents to the knowledge graph.

    Fetches the current graph state (nodes and relationships) and the list of
    registered agent cards, then reconciles the expected state with the existing
    state via ``syncData``.

    Returns:
        The reconciliation plan returned by ``syncData``.
    """
    logger.info("Start to process agent 2 graph data")
    existNodes = list_nodes()
    existRelationships = list_relationships()
    agentCards = list_agents()
    logger.info(
        f"Fetched graph data: existNodes={len(existNodes)}, "
        f"existRelationships={len(existRelationships)}, agentCards={len(agentCards)}"
    )
    return syncData(
        agentCards=agentCards,
        existNodes=existNodes,
        existRelationships=existRelationships,
    )


def _node_key(node: Node) -> Tuple[str, str, str]:
    """Build a unique identity key for a node from its primary label, name and organization."""
    labels = list(node.labels or [])
    primary_label = labels[0] if labels else ""
    name = (node.get("name") if hasattr(node, "get") else None) or ""
    organization = (
        (node.get("organization") if hasattr(node, "get") else None) or ""
    )
    return primary_label, str(name), str(organization)


def _relationship_key(rel: Relationship, allNodes: List[Node]) -> str:
    """Build a unique identity key for a relationship based on type and endpoint node ids."""
    start_node_id = rel.get("startNodeId") or ""
    if not start_node_id:
        start_node_id = _resolve_endpoint_node_id(rel._start_node, allNodes)
    end_node_id = rel.get("endNodeId") or ""
    if not end_node_id:
        end_node_id = _resolve_endpoint_node_id(rel._end_node, allNodes)
    return f"{rel.type}{start_node_id}{end_node_id}"


def _resolve_endpoint_node_id(node: Optional[Node], allNodes: List[Node]) -> str:
    """Return the element id of a relationship endpoint.

    If the endpoint already carries an element id it is returned directly.
    Otherwise allNodes is scanned for a node whose label, ``name`` and
    ``organization`` all match the endpoint. The first such node's element id
    is returned; if no match is found an empty string is returned.
    """
    if node is None:
        return ""
    node_id = getattr(node, "element_id", "") or ""
    if node_id:
        return node_id
    for candidate in allNodes:
        if _node_key(candidate) == _node_key(node):
            return getattr(candidate, "element_id", "") or ""
    return ""


def updateRelationship(
    allNodes: List[Node],
    expectRelationships: List[Relationship],
    existRelationships: List[Relationship],
) -> Dict[str, List[Relationship]]:
    """
    Determine which relationships need to be created and which should be deleted.

    Relationships are matched by ``_relationship_key`` (type plus the names of
    their start and end nodes).

    - Relationships present in the expected state but missing from the existing
      state are returned under ``create_relationships``. When such a
      relationship is missing its endpoints, they are resolved from ``allNodes``
      using the endpoint names.
    - Relationships present in the existing state but missing from the expected
      state are returned under ``delete_relationships``.

    Args:
        allNodes: All nodes available in the knowledge graph, used to resolve
            the endpoints of relationships that need to be created.
        expectRelationships: The desired relationships.
        existRelationships: The relationships currently stored in the graph.

    Returns:
        A dict::

            {
                "create_relationships": [Relationship, ...],
                "delete_relationships": [Relationship, ...],
            }
    """
    exist_rel_map = {_relationship_key(rel, allNodes): rel for rel in existRelationships}
    expect_rel_map = {_relationship_key(rel, allNodes): rel for rel in expectRelationships}

    create_relationships: List[Relationship] = []
    delete_relationships: List[Relationship] = []

    all_node_map = {_node_key(node): node for node in allNodes}

    for key, rel in expect_rel_map.items():
        if key in exist_rel_map:
            continue
        rel = _resolve_relationship_endpoints(rel, all_node_map)
        create_relationships.append(rel)

    for key, rel in exist_rel_map.items():
        if key not in expect_rel_map:
            delete_relationships.append(rel)

    return {
        "create_relationships": create_relationships,
        "delete_relationships": delete_relationships,
    }


def _resolve_relationship_endpoints(
    rel: Relationship, all_node_map: Dict[Tuple[str, str, str], Node]
) -> Relationship:
    """Return a relationship whose start/end nodes are resolved from all_node_map."""
    if rel._start_node is not None and rel._start_node.get("name"):
        start = all_node_map.get(_node_key(rel._start_node))
        if start is not None:
            rel._start_node = start
    if rel._end_node is not None and rel._end_node.get("name"):
        end = all_node_map.get(_node_key(rel._end_node))
        if end is not None:
            rel._end_node = end
    return rel


def updateGraph(
    expectNodes: List[Node],
    expectRelationships: List[Relationship],
    existNodes: List[Node],
    existRelationships: List[Relationship],
) -> Dict[str, Any]:
    """
    Compute the gap between the desired graph state and the existing graph state.

    The desired state is described by ``expectNodes`` and ``expectRelationships``,
    while the current state stored in the knowledge graph is described by
    ``existNodes`` and ``existRelationships``. This method reconciles the two by
    producing a plan of graph operations that bring the existing state in line
    with the expected state.

    Nodes are matched by their primary label and ``name`` property. Relationships
    are matched by their type and the names of their start and end nodes.

    Returns:
        A dict describing the reconciliation plan::

            {
                "create_nodes": [Node, ...],
                "delete_nodes": [Node, ...],
                "create_relationships": [Relationship, ...],
                "delete_relationships": [Relationship, ...],
                "createdNodes": [Node, ...],
            }

        - ``create_nodes``: nodes present in the expected state but missing
          from the existing state. Nodes that already exist are skipped.
        - ``delete_nodes``: nodes present in the existing state but no longer
          expected.
        - ``create_relationships``: relationships present in the expected state
          but missing from the existing state.
        - ``delete_relationships``: relationships present in the existing state
          but no longer expected.
        - ``createdNodes``: the nodes successfully created in the knowledge
          graph by calling ``create_node`` for each entry of ``create_nodes``.
    """
    plan: Dict[str, Any] = {
        "create_nodes": [],
        "delete_nodes": [],
        "create_relationships": [],
        "delete_relationships": [],
    }

    node_plan = updateNode(expectNodes=expectNodes, existNodes=existNodes)
    plan["create_nodes"] = node_plan["insert_nodes"]
    plan["delete_nodes"] = node_plan["delete_nodes"]

    createdNodes: List[Node] = []
    for node in plan["create_nodes"]:
        created = create_node(
            labels=list(node.labels or []),
            properties=dict(node.items()),
        )
        if created is not None:
            createdNodes.append(created)

    plan["createdNodes"] = createdNodes

    rel_plan = updateRelationship(
        allNodes=createdNodes + existNodes,
        expectRelationships=expectRelationships,
        existRelationships=existRelationships,
    )
    plan["create_relationships"] = rel_plan["create_relationships"]
    plan["delete_relationships"] = rel_plan["delete_relationships"]

    for rel in plan["create_relationships"]:
        create_relationship(
            type=rel.type,
            start_node_id=rel._start_node.element_id,
            end_node_id=rel._end_node.element_id,
            properties=dict(rel.items()),
        )

    for rel in plan["delete_relationships"]:
        delete_relationship(id=rel.element_id)

    for node in plan["delete_nodes"]:
        delete_node(id=node.element_id)

    return plan


def updateNode(
    expectNodes: List[Node],
    existNodes: List[Node],
) -> Dict[str, List[Node]]:
    """
    Determine which nodes need to be inserted, updated or deleted.

    Nodes are matched by their identity key (primary label, ``name`` and
    ``organization``, computed by ``_node_key``).

    - Nodes present in the expected state but missing from the existing state
      are returned under ``insert_nodes`` so they can be created.
    - Nodes present in both states but with different properties are returned
      under ``update_nodes`` so they can be updated.
    - Nodes present in the existing state but missing from the expected state
      are returned under ``delete_nodes`` so they can be removed.

    Args:
        expectNodes: The desired nodes.
        existNodes: The nodes currently stored in the knowledge graph.

    Returns:
        A dict::

            {
                "insert_nodes": [Node, ...],
                "update_nodes": [Node, ...],
                "delete_nodes": [Node, ...],
            }
    """
    expect_node_map = {_node_key(node): node for node in expectNodes}
    exist_node_map = {_node_key(node): node for node in existNodes}

    insert_nodes: List[Node] = []
    update_nodes: List[Node] = []
    delete_nodes: List[Node] = []

    for key, node in expect_node_map.items():
        existing = exist_node_map.get(key)
        if existing is None:
            logger.info(f"expect node does not exist {key}")
            insert_nodes.append(node)
        elif dict(existing.items()) != dict(node.items()):
            update_nodes.append(node)

    for key, node in exist_node_map.items():
        if key not in expect_node_map:
            delete_nodes.append(node)
            logger.info(f"exited node is not in expeted node list {key}")

    return {
        "insert_nodes": insert_nodes,
        "update_nodes": update_nodes,
        "delete_nodes": delete_nodes,
    }