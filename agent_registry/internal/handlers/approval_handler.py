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

import asyncio
from typing import Dict, Any
from loguru import logger

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationName, OperationResult, OperatorObject


class ApprovalHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        user_name = params.get('user_name', 'admin')  # CLI操作默认为admin
        
        details = {
            "agentName": agent_name,
            "organization": organization
        }
        
        audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)
        
        if not agent_name or not organization:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.APPROVE_AGENT,
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
        
        approval_enabled = config.get('agent_approval_enabled', 'false')
        if approval_enabled != 'true':
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.APPROVE_AGENT,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return InternalResponse(
                success=False,
                error="Approval function is disabled",
                message="Cannot approve agent when agent_approval_enabled=false"
            ).model_dump()
        
        agent = registry.find_by_key(agent_name, organization)
        if not agent:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.APPROVE_AGENT,
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
        
        current_status = registry.get_status(agent_name, organization)
        if current_status == 'published':
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.APPROVE_AGENT,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return InternalResponse(
                success=False,
                error="Agent already published",
                message=f"Agent '{agent_name}' is already in published status"
            ).model_dump()
        
        try:
            registry.update_status(agent_name, organization, 'published')
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.APPROVE_AGENT,
                "level": LogLevel.MINOR,
                "result": OperationResult.SUCCESS,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.info(f"Agent approved: {agent_name} ({organization})")
            
            return InternalResponse(
                success=True,
                message="Agent approval successful",
                data={
                    "agent_name": agent_name,
                    "organization": organization,
                    "status": "published"
                }
            ).model_dump()
        except Exception as e:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.APPROVE_AGENT,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.error(f"Failed to approve agent: {e}")
            return InternalResponse(
                success=False,
                error=str(e),
                message="Failed to update agent status"
            ).model_dump()