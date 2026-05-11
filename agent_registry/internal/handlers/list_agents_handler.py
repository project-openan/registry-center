# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.

from typing import Dict, Any
from datetime import datetime

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse


class ListAgentsHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        agents = registry.find_all()
        
        agent_list = []
        for agent in agents:
            status = registry.get_status(agent.name, agent.provider.organization)
            tags = registry.get_tags(agent.name, agent.provider.organization)
            created_at = registry.get_created_at(agent.name, agent.provider.organization)
            updated_at = registry.get_updated_at(agent.name, agent.provider.organization)
            agent_list.append({
                "agent_name": agent.name,
                "organization": agent.provider.organization,
                "status": status or "published",
                "tag": tags or [],
                "created_at": created_at or "",
                "updated_at": updated_at or ""
            })
        
        return InternalResponse(
            success=True,
            message="Agents retrieved successfully",
            data={
                "agents": agent_list,
                "count": len(agent_list)
            }
        ).model_dump()