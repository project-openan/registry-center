# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from typing import Dict, Any
from google.protobuf.json_format import MessageToDict

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType


class GetAgentHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        agent_name = params.get('agent_name')
        organization = params.get('organization')
        
        if not agent_name or not organization:
            return InternalResponse(
                success=False,
                error="Missing required params: agent_name or organization"
            ).model_dump()

        get_handle = HandlerRegistry.get_handler(InterfaceType.GET)
        record = asyncio.run(get_handle.handle(agent_name, organization))

        if not record:
            return InternalResponse(
                success=False,
                error="Agent not found",
                message=f"Agent '{agent_name}' from organization '{organization}' not found"
            ).model_dump()

        agent = record.agent_card
        status = registry.get_status(agent_name, organization)
        tags = registry.get_agent_tags(agent_name, organization)
        created_at = registry.get_created_at(agent_name, organization)
        updated_at = registry.get_updated_at(agent_name, organization)
        agent_dict = MessageToDict(agent, preserving_proto_field_name=True)

        return InternalResponse(
            success=True,
            message="Agent retrieved successfully",
            data={
                "agentcard": agent_dict,
                "status": status or "published",
                "tag": tags or [],
                "created_at": created_at or "",
                "updated_at": updated_at or ""
            }
        ).model_dump()