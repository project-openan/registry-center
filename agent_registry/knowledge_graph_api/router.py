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
Knowledge Graph API Router - RESTful endpoints for generic graph operations.

Provides endpoints for:
- Node CRUD operations
- Relationship CRUD operations
- Graph queries
- Cypher query execution
- Bulk operations
- Import/Export
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Path, Depends, status
from fastapi.responses import JSONResponse, Response
from loguru import logger
from neo4j import GraphDatabase, Driver

from agent_registry.config import PERSISTENCE_CONF

knowledge_graph_router = APIRouter(prefix="/rest/v1/registry-center/knowledge-graph", tags=["Knowledge Graph"])

# Global Neo4j driver instance
_neo4j_driver: Optional[Driver] = None


def get_neo4j_driver() -> Driver:
    """Get or create Neo4j driver instance."""
    global _neo4j_driver
    if _neo4j_driver is None:
        uri = PERSISTENCE_CONF.get('neo4j.uri', 'bolt://localhost:7687')
        user = PERSISTENCE_CONF.get('neo4j.username', 'neo4j')
        password = PERSISTENCE_CONF.get('neo4j.password', 'password')
        _neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"Neo4j driver initialized for Knowledge Graph API: {uri}")
    return _neo4j_driver


def close_neo4j_driver():
    """Close Neo4j driver."""
    global _neo4j_driver
    if _neo4j_driver:
        _neo4j_driver.close()
        logger.info("Neo4j driver closed")
        _neo4j_driver = None


# Node endpoints

@knowledge_graph_router.get("/nodes", summary="List all nodes")
async def list_nodes(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(100, ge=1, le=10000, description="Items per page"),
    label: Optional[str] = Query(None, description="Filter by label")
):
    """Retrieve all nodes with optional pagination and label filtering."""
    driver = get_neo4j_driver()
    skip = (page - 1) * limit
    
    with driver.session() as session:
        if label:
            result = session.run(f"""
                MATCH (n:{label})
                RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
                SKIP $skip LIMIT $limit
            """, skip=skip, limit=limit)
        else:
            result = session.run("""
                MATCH (n)
                RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
                SKIP $skip LIMIT $limit
            """, skip=skip, limit=limit)
        
        nodes = []
        for record in result:
            nodes.append({
                "id": record['id'],
                "labels": list(record['labels']),
                "properties": dict(record['properties'])
            })
        
        # Get total count
        if label:
            count_result = session.run(f"MATCH (n:{label}) RETURN count(n) as count")
        else:
            count_result = session.run("MATCH (n) RETURN count(n) as count")
        total = count_result.single()['count']
        
        total_pages = (total + limit - 1) // limit
        
        return {
            "success": True,
            "data": nodes,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "totalPages": total_pages,
                "hasNext": page < total_pages,
                "hasPrev": page > 1
            }
        }


@knowledge_graph_router.post("/nodes", summary="Create node", status_code=status.HTTP_201_CREATED)
async def create_node(node_data: Dict[str, Any]):
    """Create a new node with specified labels and properties."""
    if 'labels' not in node_data or not node_data['labels']:
        raise HTTPException(status_code=400, detail="At least one label is required")
    
    if 'properties' not in node_data:
        raise HTTPException(status_code=400, detail="Properties are required")
    
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        labels_str = ":".join(node_data['labels'])
        query = f"""
            CREATE (n:{labels_str} $properties)
            RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
        """
        
        result = session.run(query, properties=node_data['properties'])
        record = result.single()
        
        if not record:
            raise HTTPException(status_code=500, detail="Failed to create node")
        
        return {
            "success": True,
            "data": {
                "id": record['id'],
                "labels": list(record['labels']),
                "properties": dict(record['properties'])
            }
        }


@knowledge_graph_router.get("/nodes/{id}", summary="Get node by ID")
async def get_node_by_id(id: str = Path(..., description="Node element ID")):
    """Retrieve a specific node by its element ID."""
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE elementId(n) = $id
            RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
        """, id=id)
        
        record = result.single()
        if not record:
            raise HTTPException(status_code=404, detail="Node not found")
        
        return {
            "success": True,
            "data": {
                "id": record['id'],
                "labels": list(record['labels']),
                "properties": dict(record['properties'])
            }
        }


@knowledge_graph_router.put("/nodes/{id}", summary="Update node")
async def update_node(id: str = Path(..., description="Node element ID"), 
                     update_data: Dict[str, Any] = None):
    """Update properties of an existing node."""
    if not update_data or 'properties' not in update_data:
        raise HTTPException(status_code=400, detail="Properties to update are required")
    
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        # Check if node exists
        check_result = session.run("""
            MATCH (n)
            WHERE elementId(n) = $id
            RETURN n
        """, id=id)
        
        if not check_result.single():
            raise HTTPException(status_code=404, detail="Node not found")
        
        # Update properties
        result = session.run("""
            MATCH (n)
            WHERE elementId(n) = $id
            SET n += $properties
            RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
        """, id=id, properties=update_data['properties'])
        
        record = result.single()
        return {
            "success": True,
            "data": {
                "id": record['id'],
                "labels": list(record['labels']),
                "properties": dict(record['properties'])
            }
        }


@knowledge_graph_router.delete("/nodes/{id}", summary="Delete node", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    id: str = Path(..., description="Node element ID"),
    force: bool = Query(False, description="Force delete even if node has relationships")
):
    """Delete a node. Use force=true to delete node and all its relationships."""
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        if force:
            result = session.run("""
                MATCH (n)
                WHERE elementId(n) = $id
                DETACH DELETE n
                RETURN count(n) as deleted
            """, id=id)
        else:
            result = session.run("""
                MATCH (n)
                WHERE elementId(n) = $id
                OPTIONAL MATCH (n)-[r]-()
                WITH n, count(r) as relCount
                WHERE relCount = 0
                DELETE n
                RETURN count(n) as deleted
            """, id=id)
        
        record = result.single()
        if not record or record['deleted'] == 0:
            if not force:
                # Check if node exists but has relationships
                check_result = session.run("""
                    MATCH (n)
                    WHERE elementId(n) = $id
                    OPTIONAL MATCH (n)-[r]-()
                    RETURN count(r) as relCount
                """, id=id)
                check_record = check_result.single()
                if check_record and check_record['relCount'] > 0:
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot delete node with relationships. Use force=true."
                    )
            raise HTTPException(status_code=404, detail="Node not found")
        
        return Response(status_code=status.HTTP_204_NO_CONTENT)


# Relationship endpoints

@knowledge_graph_router.get("/relationships", summary="List all relationships")
async def list_relationships(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(100, ge=1, le=10000, description="Items per page"),
    type: Optional[str] = Query(None, description="Filter by relationship type")
):
    """Retrieve all relationships with optional pagination and type filtering."""
    driver = get_neo4j_driver()
    skip = (page - 1) * limit
    
    with driver.session() as session:
        if type:
            result = session.run(f"""
                MATCH (start)-[r:{type}]->(end)
                RETURN elementId(r) as id, type(r) as type,
                       elementId(start) as startNodeId, elementId(end) as endNodeId,
                       properties(r) as properties
                SKIP $skip LIMIT $limit
            """, skip=skip, limit=limit)
        else:
            result = session.run("""
                MATCH (start)-[r]->(end)
                RETURN elementId(r) as id, type(r) as type,
                       elementId(start) as startNodeId, elementId(end) as endNodeId,
                       properties(r) as properties
                SKIP $skip LIMIT $limit
            """, skip=skip, limit=limit)
        
        relationships = []
        for record in result:
            relationships.append({
                "id": record['id'],
                "type": record['type'],
                "startNodeId": record['startNodeId'],
                "endNodeId": record['endNodeId'],
                "properties": dict(record['properties'])
            })
        
        # Get total count
        if type:
            count_result = session.run(f"MATCH ()-[r:{type}]->() RETURN count(r) as count")
        else:
            count_result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
        total = count_result.single()['count']
        
        total_pages = (total + limit - 1) // limit
        
        return {
            "success": True,
            "data": relationships,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "totalPages": total_pages,
                "hasNext": page < total_pages,
                "hasPrev": page > 1
            }
        }


@knowledge_graph_router.post("/relationships", summary="Create relationship", status_code=status.HTTP_201_CREATED)
async def create_relationship(rel_data: Dict[str, Any]):
    """Create a new relationship between two existing nodes."""
    required_fields = ['type', 'startNodeId', 'endNodeId']
    for field in required_fields:
        if field not in rel_data:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
    
    if not rel_data['type']:
        raise HTTPException(status_code=400, detail="Relationship type cannot be empty")
    
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        # Verify nodes exist
        start_check = session.run("""
            MATCH (n)
            WHERE elementId(n) = $id
            RETURN n
        """, id=rel_data['startNodeId'])
        
        if not start_check.single():
            raise HTTPException(status_code=400, detail=f"Start node not found: {rel_data['startNodeId']}")
        
        end_check = session.run("""
            MATCH (n)
            WHERE elementId(n) = $id
            RETURN n
        """, id=rel_data['endNodeId'])
        
        if not end_check.single():
            raise HTTPException(status_code=400, detail=f"End node not found: {rel_data['endNodeId']}")
        
        # Create relationship
        properties = rel_data.get('properties', {})
        query = f"""
            MATCH (start), (end)
            WHERE elementId(start) = $startId AND elementId(end) = $endId
            CREATE (start)-[r:`{rel_data['type']}` $properties]->(end)
            RETURN elementId(r) as id, type(r) as type,
                   elementId(start) as startNodeId, elementId(end) as endNodeId,
                   properties(r) as properties
        """
        
        result = session.run(query, startId=rel_data['startNodeId'], 
                           endId=rel_data['endNodeId'], properties=properties)
        record = result.single()
        
        if not record:
            raise HTTPException(status_code=500, detail="Failed to create relationship")
        
        return {
            "success": True,
            "data": {
                "id": record['id'],
                "type": record['type'],
                "startNodeId": record['startNodeId'],
                "endNodeId": record['endNodeId'],
                "properties": dict(record['properties'])
            }
        }


@knowledge_graph_router.get("/relationships/{id}", summary="Get relationship by ID")
async def get_relationship_by_id(id: str = Path(..., description="Relationship element ID")):
    """Retrieve a specific relationship by its element ID."""
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        result = session.run("""
            MATCH (start)-[r]->(end)
            WHERE elementId(r) = $id
            RETURN elementId(r) as id, type(r) as type,
                   elementId(start) as startNodeId, elementId(end) as endNodeId,
                   properties(r) as properties
        """, id=id)
        
        record = result.single()
        if not record:
            raise HTTPException(status_code=404, detail="Relationship not found")
        
        return {
            "success": True,
            "data": {
                "id": record['id'],
                "type": record['type'],
                "startNodeId": record['startNodeId'],
                "endNodeId": record['endNodeId'],
                "properties": dict(record['properties'])
            }
        }


@knowledge_graph_router.put("/relationships/{id}", summary="Update relationship")
async def update_relationship(
    id: str = Path(..., description="Relationship element ID"),
    update_data: Dict[str, Any] = None
):
    """Update properties of an existing relationship."""
    if not update_data or 'properties' not in update_data:
        raise HTTPException(status_code=400, detail="Properties to update are required")
    
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        # Check if relationship exists
        check_result = session.run("""
            MATCH ()-[r]->()
            WHERE elementId(r) = $id
            RETURN r
        """, id=id)
        
        if not check_result.single():
            raise HTTPException(status_code=404, detail="Relationship not found")
        
        # Update properties
        result = session.run("""
            MATCH (start)-[r]->(end)
            WHERE elementId(r) = $id
            SET r += $properties
            RETURN elementId(r) as id, type(r) as type,
                   elementId(start) as startNodeId, elementId(end) as endNodeId,
                   properties(r) as properties
        """, id=id, properties=update_data['properties'])
        
        record = result.single()
        return {
            "success": True,
            "data": {
                "id": record['id'],
                "type": record['type'],
                "startNodeId": record['startNodeId'],
                "endNodeId": record['endNodeId'],
                "properties": dict(record['properties'])
            }
        }


@knowledge_graph_router.delete("/relationships/{id}", summary="Delete relationship", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relationship(id: str = Path(..., description="Relationship element ID")):
    """Delete a relationship by its element ID."""
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        result = session.run("""
            MATCH ()-[r]->()
            WHERE elementId(r) = $id
            DELETE r
            RETURN count(r) as deleted
        """, id=id)
        
        record = result.single()
        if not record or record['deleted'] == 0:
            raise HTTPException(status_code=404, detail="Relationship not found")
        
        return Response(status_code=status.HTTP_204_NO_CONTENT)


# Graph endpoint

@knowledge_graph_router.get("/graph", summary="Get entire graph")
async def get_graph(limit: int = Query(1000, ge=1, le=10000, description="Maximum nodes/relationships to return")):
    """Retrieve all nodes and relationships from the graph."""
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        # Get all nodes
        node_result = session.run("""
            MATCH (n)
            RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
            LIMIT $limit
        """, limit=limit)
        
        nodes = []
        for record in node_result:
            nodes.append({
                "id": record['id'],
                "labels": list(record['labels']),
                "properties": dict(record['properties'])
            })
        
        # Get all relationships
        rel_result = session.run("""
            MATCH (start)-[r]->(end)
            RETURN elementId(r) as id, type(r) as type,
                   elementId(start) as startNodeId, elementId(end) as endNodeId,
                   properties(r) as properties
            LIMIT $limit
        """, limit=limit)
        
        relationships = []
        for record in rel_result:
            relationships.append({
                "id": record['id'],
                "type": record['type'],
                "startNodeId": record['startNodeId'],
                "endNodeId": record['endNodeId'],
                "properties": dict(record['properties'])
            })
        
        return {
            "success": True,
            "data": {
                "nodes": nodes,
                "relationships": relationships
            }
        }




# Bulk endpoints

@knowledge_graph_router.post("/bulk/nodes", summary="Bulk create nodes", status_code=status.HTTP_201_CREATED)
async def bulk_create_nodes(nodes_data: Dict[str, List[Dict[str, Any]]]):
    """Create multiple nodes in a single transaction."""
    if 'nodes' not in nodes_data or not nodes_data['nodes']:
        raise HTTPException(status_code=400, detail="Nodes array is required and cannot be empty")
    
    if len(nodes_data['nodes']) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 nodes per request")
    
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        # Prepare nodes for UNWIND
        nodes_to_create = []
        for node in nodes_data['nodes']:
            if 'labels' not in node or not node['labels']:
                raise HTTPException(status_code=400, detail="Each node must have at least one label")
            nodes_to_create.append({
                'labels': node['labels'],
                'properties': node.get('properties', {})
            })
        
        # Use UNWIND for bulk creation
        result = session.run("""
            UNWIND $nodes as node
            CREATE (n)
            SET n += node.properties
            WITH n, node.labels as labels
            CALL apoc.create.addLabels(n, labels) YIELD node as labeledNode
            RETURN elementId(labeledNode) as id, labels(labeledNode) as labels, properties(labeledNode) as properties
        """, nodes=nodes_to_create)
        
        created_nodes = []
        for record in result:
            created_nodes.append({
                "id": record['id'],
                "labels": list(record['labels']),
                "properties": dict(record['properties'])
            })
        
        return {
            "success": True,
            "data": created_nodes,
            "count": len(created_nodes)
        }


@knowledge_graph_router.post("/bulk/relationships", summary="Bulk create relationships", status_code=status.HTTP_201_CREATED)
async def bulk_create_relationships(rels_data: Dict[str, List[Dict[str, Any]]]):
    """Create multiple relationships in a single transaction."""
    if 'relationships' not in rels_data or not rels_data['relationships']:
        raise HTTPException(status_code=400, detail="Relationships array is required and cannot be empty")
    
    if len(rels_data['relationships']) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 relationships per request")
    
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        # Prepare relationships for UNWIND
        rels_to_create = []
        for rel in rels_data['relationships']:
            required = ['type', 'startNodeId', 'endNodeId']
            for field in required:
                if field not in rel:
                    raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
            rels_to_create.append({
                'type': rel['type'],
                'startNodeId': rel['startNodeId'],
                'endNodeId': rel['endNodeId'],
                'properties': rel.get('properties', {})
            })
        
        # Verify all nodes exist
        node_ids = set()
        for rel in rels_to_create:
            node_ids.add(rel['startNodeId'])
            node_ids.add(rel['endNodeId'])
        
        for node_id in node_ids:
            check_result = session.run("""
                MATCH (n)
                WHERE elementId(n) = $id
                RETURN n
            """, id=node_id)
            if not check_result.single():
                raise HTTPException(status_code=400, detail=f"Node not found: {node_id}")
        
        # Create relationships
        created_rels = []
        for rel_data in rels_to_create:
            query = f"""
                MATCH (start), (end)
                WHERE elementId(start) = $startId AND elementId(end) = $endId
                CREATE (start)-[r:`{rel_data['type']}` $properties]->(end)
                RETURN elementId(r) as id, type(r) as type,
                       elementId(start) as startNodeId, elementId(end) as endNodeId,
                       properties(r) as properties
            """
            result = session.run(query, startId=rel_data['startNodeId'],
                               endId=rel_data['endNodeId'], properties=rel_data['properties'])
            record = result.single()
            if record:
                created_rels.append({
                    "id": record['id'],
                    "type": record['type'],
                    "startNodeId": record['startNodeId'],
                    "endNodeId": record['endNodeId'],
                    "properties": dict(record['properties'])
                })
        
        return {
            "success": True,
            "data": created_rels,
            "count": len(created_rels)
        }


# Import/Export endpoints

@knowledge_graph_router.post("/import", summary="Import graph data", status_code=status.HTTP_201_CREATED)
async def import_graph(import_data: Dict[str, Any]):
    """Import graph data from JSON format."""
    if 'nodes' not in import_data:
        raise HTTPException(status_code=400, detail="Nodes array is required")
    
    if 'relationships' not in import_data:
        raise HTTPException(status_code=400, detail="Relationships array is required")
    
    driver = get_neo4j_driver()
    
    with driver.session() as session:
        nodes_created = 0
        rels_created = 0
        errors = []
        
        # Create nodes first
        for i, node_data in enumerate(import_data['nodes']):
            try:
                if 'labels' not in node_data or not node_data['labels']:
                    errors.append({"index": i, "message": "Missing labels"})
                    continue
                
                labels_str = ":".join(node_data['labels'])
                query = f"""
                    CREATE (n:{labels_str} $properties)
                    RETURN elementId(n) as id
                """
                result = session.run(query, properties=node_data.get('properties', {}))
                record = result.single()
                if record:
                    nodes_created += 1
            except Exception as e:
                errors.append({"index": i, "message": str(e)})
        
        # Create relationships
        for i, rel_data in enumerate(import_data.get('relationships', [])):
            try:
                required = ['type', 'startNodeId', 'endNodeId']
                for field in required:
                    if field not in rel_data:
                        errors.append({"index": i, "message": f"Missing field: {field}"})
                        continue
                
                query = f"""
                    MATCH (start), (end)
                    WHERE elementId(start) = $startId AND elementId(end) = $endId
                    CREATE (start)-[r:`{rel_data['type']}` $properties]->(end)
                    RETURN elementId(r) as id
                """
                result = session.run(query, startId=rel_data['startNodeId'],
                                   endId=rel_data['endNodeId'], 
                                   properties=rel_data.get('properties', {}))
                record = result.single()
                if record:
                    rels_created += 1
            except Exception as e:
                errors.append({"index": i, "message": str(e)})
        
        return {
            "success": True,
            "data": {
                "nodesCreated": nodes_created,
                "relationshipsCreated": rels_created,
                "errors": errors if errors else []
            }
        }


@knowledge_graph_router.get("/export", summary="Export graph data")
async def export_graph(
    filter: Optional[str] = Query(None, description="Filter by label or property"),
    format: str = Query("json", description="Export format", pattern="^json$")
):
    """Export graph data with optional filtering."""
    driver = get_neo4j_driver()
    
    # Parse filter parameters
    filters = {}
    if filter:
        for param in filter.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                filters[key] = value
    
    with driver.session() as session:
        nodes = []
        relationships = []
        
        # Build query based on filters
        if 'label' in filters:
            # Filter by label
            label = filters['label']
            node_query = f"""
                MATCH (n:`{label}`)
                RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
            """
            
            node_result = session.run(node_query)
            for record in node_result:
                nodes.append({
                    "id": record['id'],
                    "labels": list(record['labels']),
                    "properties": dict(record['properties'])
                })
            
            # Get relationships connected to filtered nodes
            rel_query = f"""
                MATCH (start:`{label}`)-[r]->(end)
                RETURN elementId(r) as id, type(r) as type,
                       elementId(start) as startNodeId, elementId(end) as endNodeId,
                       properties(r) as properties
                UNION
                MATCH (start)-[r]->(end:`{label}`)
                RETURN elementId(r) as id, type(r) as type,
                       elementId(start) as startNodeId, elementId(end) as endNodeId,
                       properties(r) as properties
            """
            
            rel_result = session.run(rel_query)
            for record in rel_result:
                relationships.append({
                    "id": record['id'],
                    "type": record['type'],
                    "startNodeId": record['startNodeId'],
                    "endNodeId": record['endNodeId'],
                    "properties": dict(record['properties'])
                })
                
        elif 'property' in filters:
            # Filter by property (key:value format)
            prop_parts = filters['property'].split(':', 1)
            if len(prop_parts) == 2:
                prop_key, prop_value = prop_parts
                
                node_query = f"""
                    MATCH (n)
                    WHERE n.`{prop_key}` = $propValue
                    RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
                """
                
                node_result = session.run(node_query, propValue=prop_value)
                for record in node_result:
                    nodes.append({
                        "id": record['id'],
                        "labels": list(record['labels']),
                        "properties": dict(record['properties'])
                    })
                
                # Get relationships for filtered nodes
                rel_query = """
                    MATCH (start)-[r]->(end)
                    WHERE start.`""" + prop_key + """` = $propValue OR end.`""" + prop_key + """` = $propValue
                    RETURN elementId(r) as id, type(r) as type,
                           elementId(start) as startNodeId, elementId(end) as endNodeId,
                           properties(r) as properties
                """
                
                rel_result = session.run(rel_query, propValue=prop_value)
                for record in rel_result:
                    relationships.append({
                        "id": record['id'],
                        "type": record['type'],
                        "startNodeId": record['startNodeId'],
                        "endNodeId": record['endNodeId'],
                        "properties": dict(record['properties'])
                    })
        else:
            # No filter - export full graph
            node_result = session.run("""
                MATCH (n)
                RETURN elementId(n) as id, labels(n) as labels, properties(n) as properties
            """)
            
            for record in node_result:
                nodes.append({
                    "id": record['id'],
                    "labels": list(record['labels']),
                    "properties": dict(record['properties'])
                })
            
            rel_result = session.run("""
                MATCH (start)-[r]->(end)
                RETURN elementId(r) as id, type(r) as type,
                       elementId(start) as startNodeId, elementId(end) as endNodeId,
                       properties(r) as properties
            """)
            
            for record in rel_result:
                relationships.append({
                    "id": record['id'],
                    "type": record['type'],
                    "startNodeId": record['startNodeId'],
                    "endNodeId": record['endNodeId'],
                    "properties": dict(record['properties'])
                })
        
        return {
            "success": True,
            "data": {
                "nodes": nodes,
                "relationships": relationships
            },
            "metadata": {
                "exportedAt": datetime.now(timezone.utc).isoformat(),
                "nodeCount": len(nodes),
                "relationshipCount": len(relationships),
                "format": format,
                "filter": filter
            }
        }
