# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.

import asyncio
from typing import Dict, Any, List
from loguru import logger

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationName, OperationResult, OperatorObject


class AddTagsHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        tags = params.get('tags', [])
        user_name = params.get('user_name', 'admin')  # CLI操作默认为admin
        
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
        
        current_tags = registry.get_agent_tags(agent_name, organization) or []
        merged_tags = list(set(current_tags + tags))
        
        if len(merged_tags) > 10:
            details["current_tag_count"] = len(current_tags)
            details["new_tag_count"] = len(tags)
            details["merged_tag_count"] = len(merged_tags)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.warning(f"Tag limit exceeded: {agent_name} ({organization}) - current: {len(current_tags)}, new: {len(tags)}, merged: {len(merged_tags)}")
            return InternalResponse(
                success=False,
                error="Tag limit exceeded",
                message=f"Agent cannot have more than 10 tags. Current: {len(current_tags)}, attempting to add: {len(tags)}, would result in: {len(merged_tags)}"
            ).model_dump()
        
        try:
            registry.update_agent_tags(agent_name, organization, merged_tags)
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
            logger.info(f"Tags added to agent: {agent_name} ({organization}) -> {updated_tags}")
            
            return InternalResponse(
                success=True,
                message="Tags added successfully",
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
            logger.error(f"Failed to add tags: {e}")
            return InternalResponse(
                success=False,
                error=str(e),
                message="Failed to update tags"
            ).model_dump()