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

from typing import Dict, Any, List
from loguru import logger

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse
from agent_registry.internal.utils.tag_validator import TagValidator


class TagAddHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagAddHandler] Entering handle method with params: {params}")
        validator = TagValidator()
        
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        new_tags = params.get('tags', [])
        
        if not agent_name or not organization:
            return InternalResponse(
                success=False,
                error="Missing required params: agent_name or organization"
            ).model_dump()
        
        agent = registry.find_by_key(agent_name, organization)
        if not agent:
            return InternalResponse(
                success=False,
                error="Agent not found",
                message=f"Agent '{agent_name}' from organization '{organization}' not found"
            ).model_dump()
        
        if not new_tags:
            return InternalResponse(
                success=False,
                error="No tags provided"
            ).model_dump()
        
        current_tags = registry.get_tags(agent_name, organization)
        valid, error = validator.validate_add_tags(current_tags or [], new_tags)
        if not valid:
            return InternalResponse(
                success=False,
                error=error
            ).model_dump()
        
        try:
            registry.add_tags(agent_name, organization, new_tags)
            updated_tags = registry.get_tags(agent_name, organization)
            logger.info(f"Tags added to agent: {agent_name} ({organization})")
            
            return InternalResponse(
                success=True,
                message="Tags added successfully",
                data={
                    "agent_name": agent_name,
                    "organization": organization,
                    "tags": updated_tags
                }
            ).model_dump()
        except Exception as e:
            logger.error(f"Failed to add tags: {e}")
            return InternalResponse(
                success=False,
                error=str(e),
                message="Failed to add tags"
            ).model_dump()


class TagRemoveHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagRemoveHandler] Entering handle method with params: {params}")
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        tags_to_remove = params.get('tags', [])
        
        if not agent_name or not organization:
            return InternalResponse(
                success=False,
                error="Missing required params: agent_name or organization"
            ).model_dump()
        
        agent = registry.find_by_key(agent_name, organization)
        if not agent:
            return InternalResponse(
                success=False,
                error="Agent not found",
                message=f"Agent '{agent_name}' from organization '{organization}' not found"
            ).model_dump()
        
        if not tags_to_remove:
            return InternalResponse(
                success=False,
                error="No tags provided to remove"
            ).model_dump()
        
        try:
            registry.remove_tags(agent_name, organization, tags_to_remove)
            updated_tags = registry.get_tags(agent_name, organization)
            logger.info(f"Tags removed from agent: {agent_name} ({organization})")
            
            return InternalResponse(
                success=True,
                message="Tags removed successfully",
                data={
                    "agent_name": agent_name,
                    "organization": organization,
                    "tags": updated_tags
                }
            ).model_dump()
        except Exception as e:
            logger.error(f"Failed to remove tags: {e}")
            return InternalResponse(
                success=False,
                error=str(e),
                message="Failed to remove tags"
            ).model_dump()


class TagUpdateHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagUpdateHandler] Entering handle method with params: {params}")
        validator = TagValidator()
        
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        new_tags = params.get('tags', [])
        
        if not agent_name or not organization:
            return InternalResponse(
                success=False,
                error="Missing required params: agent_name or organization"
            ).model_dump()
        
        agent = registry.find_by_key(agent_name, organization)
        if not agent:
            return InternalResponse(
                success=False,
                error="Agent not found",
                message=f"Agent '{agent_name}' from organization '{organization}' not found"
            ).model_dump()
        
        valid, error = validator.validate_tags(new_tags)
        if not valid:
            return InternalResponse(
                success=False,
                error=error
            ).model_dump()
        
        try:
            registry.update_tags(agent_name, organization, new_tags)
            logger.info(f"Tags updated for agent: {agent_name} ({organization})")
            
            return InternalResponse(
                success=True,
                message="Tags updated successfully",
                data={
                    "agent_name": agent_name,
                    "organization": organization,
                    "tags": new_tags
                }
            ).model_dump()
        except Exception as e:
            logger.error(f"Failed to update tags: {e}")
            return InternalResponse(
                success=False,
                error=str(e),
                message="Failed to update tags"
            ).model_dump()


class TagGetHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagGetHandler] Entering handle method with params: {params}")
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        
        if not agent_name or not organization:
            return InternalResponse(
                success=False,
                error="Missing required params: agent_name or organization"
            ).model_dump()
        
        agent = registry.find_by_key(agent_name, organization)
        if not agent:
            return InternalResponse(
                success=False,
                error="Agent not found",
                message=f"Agent '{agent_name}' from organization '{organization}' not found"
            ).model_dump()
        
        tags = registry.get_tags(agent_name, organization)
        
        return InternalResponse(
            success=True,
            message="Tags retrieved successfully",
            data={
                "agent_name": agent_name,
                "organization": organization,
                "tags": tags or []
            }
        ).model_dump()


class TagListHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagListHandler] Entering handle method with params: {params}")
        tag = params.get('tag')
        
        if not tag:
            return InternalResponse(
                success=False,
                error="Missing required param: tag"
            ).model_dump()
        
        validator = TagValidator()
        valid, error = validator.validate_single_tag(tag)
        if not valid:
            return InternalResponse(
                success=False,
                error=f"Invalid tag '{tag}': {error}"
            ).model_dump()
        
        try:
            agents = registry.find_by_tag(tag)
            agent_list = []
            for agent in agents:
                agent_list.append({
                    "agent_name": agent.name,
                    "organization": agent.provider.organization,
                    "description": agent.description[:100] if agent.description else ""
                })
            
            logger.info(f"Found {len(agents)} agents with tag: {tag}")
            
            return InternalResponse(
                success=True,
                message=f"Found {len(agents)} agents with tag '{tag}'",
                data={
                    "tag": tag,
                    "agents": agent_list,
                    "count": len(agents)
                }
            ).model_dump()
        except Exception as e:
            logger.error(f"Failed to list agents by tag: {e}")
            return InternalResponse(
                success=False,
                error=str(e),
                message="Failed to list agents by tag"
            ).model_dump()