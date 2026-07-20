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
Knowledge Graph API - RESTful endpoints for Neo4j graph operations.

This module provides FastAPI endpoints for:
- Node CRUD operations
- Relationship CRUD operations  
- Full graph queries
- Cypher query execution
- Bulk operations
- Import/Export functionality
"""

from agent_registry.knowledge_graph_api.router import knowledge_graph_router, close_neo4j_driver

__all__ = ['knowledge_graph_router', 'close_neo4j_driver']
