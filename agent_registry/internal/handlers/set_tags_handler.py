# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from typing import Dict, Any
from loguru import logger

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse
from agent_registry.internal.utils.tag_validator import TagValidator
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationName, OperationResult, OperatorObject


class SetTagsHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        tags = params.get('tags', [])
        user_name = params.get('user_name', 'admin')
        
        details = {
            "agentName": agent_name,
            "organization": organization,
            "tags": tags
        }
        
        audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)
        
        if not agent_name or not organization:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return InternalResponse(
                success=False,
                error="Missing required params: agent_name or organization"
            ).model_dump()
        
        if not isinstance(tags, list):
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return InternalResponse(
                success=False,
                error="Invalid param type",
                message="tags must be a list"
            ).model_dump()
        
        tag_validator = TagValidator()
        valid, error = tag_validator.validate_tags(tags)
        if not valid:
            details["tag_count"] = len(tags)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.warning(f"Tag validation failed: {agent_name} ({organization}) - {error}")
            return InternalResponse(
                success=False,
                error="Tag validation failed",
                message=error
            ).model_dump()
        
        # Validate tags existence in tag library
        nonexistent_tags = []
        for tag_name in tags:
            tag_entity = registry.get_tag_by_name(tag_name)
            if not tag_entity:
                nonexistent_tags.append(tag_name)
        
        if nonexistent_tags:
            details["nonexistent_tags"] = nonexistent_tags
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.warning(f"Invalid tags: {agent_name} ({organization}) - nonexistent tags: {nonexistent_tags}")
            return InternalResponse(
                success=False,
                error="Invalid tags",
                message=f"Tags not found in tag library: {nonexistent_tags}. Only existing tags from tag library can be assigned to agents."
            ).model_dump()
        
        agent = registry.find_by_key(agent_name, organization)
        if not agent:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return InternalResponse(
                success=False,
                error="Agent not found",
                message=f"Agent '{agent_name}' from organization '{organization}' not found"
            ).model_dump()
        
        try:
            updated = registry.update_agent_tags(agent_name, organization, tags)
            if not updated:
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.UPDATE_TAGS,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.AGENT,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.error(f"Failed to set tags for agent: {agent_name} ({organization}) - update rejected")
                return InternalResponse(
                    success=False,
                    error="Failed to update tags",
                    message=f"Tags were not updated for agent '{agent_name}' from organization '{organization}'"
                ).model_dump()

            updated_tags = registry.get_agent_tags(agent_name, organization)
            
            details["updated_tags"] = updated_tags
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.SUCCESS,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.info(f"Tags set for agent: {agent_name} ({organization}) -> {updated_tags}")
            
            return InternalResponse(
                success=True,
                message="Tags set successfully",
                data={
                    "agent_name": agent_name,
                    "organization": organization,
                    "tag": updated_tags or []
                }
            ).model_dump()
        except Exception as e:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.error(f"Failed to set tags: {e}")
            return InternalResponse(
                success=False,
                error=str(e),
                message="Failed to set tags"
            ).model_dump()