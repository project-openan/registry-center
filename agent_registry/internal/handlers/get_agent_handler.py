# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.

from typing import Dict, Any
from google.protobuf.json_format import MessageToDict

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse


class GetAgentHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
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
        
        status = registry.get_status(agent_name, organization)
        tags = registry.get_tags(agent_name, organization)
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