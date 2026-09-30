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
Knowledge Graph operations.

Provides methods to query nodes and relationships from the knowledge graph.
"""

import asyncio
import threading
from typing import List, Optional

from loguru import logger
from neo4j.graph import Graph, Node, Relationship


def _run_async(coro):
    """Run an async coroutine synchronously, safe when a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result = {}

    def runner():
        result["value"] = asyncio.run(coro)

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    return result["value"]


def _to_node(node: dict) -> Node:
    """Convert a node dict returned by the router to a Neo4j Node."""
    return Node(
        graph=None,
        id_=0,
        element_id=node.get("id", ""),
        n_labels=frozenset(node.get("labels", [])),
        properties=node.get("properties", {}),
    )


def _to_relationship(rel: dict) -> Relationship:
    """Convert a relationship dict returned by the router to a Neo4j Relationship."""
    graph = Graph()
    rel_type = rel.get("type", "")
    rel_cls = graph.relationship_type(rel_type)
    relationship = rel_cls(
        graph=graph,
        element_id=rel.get("id", ""),
        id_=0,
        properties=rel.get("properties", {}),
    )
    start_node_id = rel.get("startNodeId")
    end_node_id = rel.get("endNodeId")
    if start_node_id is not None:
        relationship._start_node = Node(
            graph=graph,
            id_=0,
            element_id=start_node_id,
            n_labels=frozenset(),
            properties={},
        )
    if end_node_id is not None:
        relationship._end_node = Node(
            graph=graph,
            id_=0,
            element_id=end_node_id,
            n_labels=frozenset(),
            properties={},
        )
    return relationship


def list_nodes(page: int = 1, limit: int = 100, label: Optional[str] = None) -> List[Node]:
    """
    Query the node list by directly calling the router list_nodes endpoint.

    Args:
        page: Page number (1-indexed), default 1.
        limit: Items per page, default 100.
        label: Optional filter by node label.

    Returns:
        List of Node objects, or an empty list on failure.
    """
    try:
        from agent_registry.knowledge_graph_api.router import list_nodes as router_list_nodes

        result = _run_async(router_list_nodes(page=page, limit=limit, label=label))
        nodes = result.get("data", [])
        return [_to_node(node) for node in nodes]
    except Exception as e:
        logger.error(f"Error while listing nodes: {e}")
        return []


def create_node(labels: List[str], properties: Optional[dict] = None) -> Optional[Node]:
    """
    Create a new node by directly calling the router create_node endpoint.

    Args:
        labels: List of labels for the new node. At least one label is required.
        properties: Optional properties of the new node.

    Returns:
        The created Node object, or None on failure.
    """
    if not labels:
        logger.error("Failed to create node, at least one label is required")
        return None

    try:
        from agent_registry.knowledge_graph_api.router import create_node as router_create_node

        result = _run_async(router_create_node({
            "labels": labels,
            "properties": properties or {},
        }))
        node = result.get("data", {})
        return _to_node(node)
    except Exception as e:
        logger.error(f"Error while creating node: {e}")
        return None


def update_node(id: str, properties: dict) -> Optional[Node]:
    """
    Update an existing node by directly calling the router update_node endpoint.

    Args:
        id: Node element ID.
        properties: Properties to update on the node.

    Returns:
        The updated Node object, or None on failure.
    """
    if not properties:
        logger.error("Failed to update node, properties are required")
        return None

    try:
        from agent_registry.knowledge_graph_api.router import update_node as router_update_node

        result = _run_async(router_update_node(id, {"properties": properties}))
        node = result.get("data", {})
        return _to_node(node)
    except Exception as e:
        logger.error(f"Error while updating node: {e}")
        return None


def delete_node(id: str, force: bool = False) -> bool:
    """
    Delete an existing node by directly calling the router delete_node endpoint.

    Args:
        id: Node element ID.
        force: Force delete even if node has relationships, default False.

    Returns:
        True if the node was deleted, False on failure.
    """
    try:
        from agent_registry.knowledge_graph_api.router import delete_node as router_delete_node

        _run_async(router_delete_node(id, force=force))
        return True
    except Exception as e:
        logger.error(f"Error while deleting node: {e}")
        return False


def create_relationship(
    type: str,
    start_node_id: str,
    end_node_id: str,
    properties: Optional[dict] = None,
) -> Optional[Relationship]:
    """
    Create a new relationship by directly calling the router create_relationship endpoint.

    Args:
        type: Type of the relationship.
        start_node_id: Element ID of the start node.
        end_node_id: Element ID of the end node.
        properties: Optional properties of the relationship.

    Returns:
        The created Relationship object, or None on failure.
    """
    if not type:
        logger.error("Failed to create relationship, type is required")
        return None
    if not start_node_id or not end_node_id:
        logger.error("Failed to create relationship, start and end node IDs are required")
        return None

    try:
        from agent_registry.knowledge_graph_api.router import (
            create_relationship as router_create_relationship,
        )

        result = _run_async(router_create_relationship({
            "type": type,
            "startNodeId": start_node_id,
            "endNodeId": end_node_id,
            "properties": properties or {},
        }))
        rel = result.get("data", {})
        return _to_relationship(rel)
    except Exception as e:
        logger.error(f"Error while creating relationship: {e}")
        return None


def delete_relationship(id: str) -> bool:
    """
    Delete an existing relationship by directly calling the router delete_relationship endpoint.

    Args:
        id: Relationship element ID.

    Returns:
        True if the relationship was deleted, False on failure.
    """
    if not id:
        logger.error("Failed to delete relationship, id is required")
        return False

    try:
        from agent_registry.knowledge_graph_api.router import (
            delete_relationship as router_delete_relationship,
        )

        _run_async(router_delete_relationship(id))
        return True
    except Exception as e:
        logger.error(f"Error while deleting relationship: {e}")
        return False


def list_relationships(
    page: int = 1, limit: int = 100, type: Optional[str] = None
) -> List[Relationship]:
    """
    Query the relationship list by directly calling the router list_relationships endpoint.

    Args:
        page: Page number (1-indexed), default 1.
        limit: Items per page, default 100.
        type: Optional filter by relationship type.

    Returns:
        List of Relationship objects, or an empty list on failure.
    """
    try:
        from agent_registry.knowledge_graph_api.router import (
            list_relationships as router_list_relationships,
        )

        result = _run_async(router_list_relationships(page=page, limit=limit, type=type))
        relationships = result.get("data", [])
        return [_to_relationship(rel) for rel in relationships]
    except Exception as e:
        logger.error(f"Error while listing relationships: {e}")
        return []