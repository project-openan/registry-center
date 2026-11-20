# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from typing import Dict, Any
from datetime import datetime

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.protocols.response import InternalResponse
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType


class ListAgentsHandler(BaseUDSHandler):
    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        # Administration needs approval/ownership metadata even when the index
        # currently has no candidates. Fail before querying the optional index.
        registry.require_authoritative_store('listing agents')
        query_handle = HandlerRegistry.get_handler(InterfaceType.QUERY)
        agents = asyncio.run(query_handle.handle(None, None))

        agent_list = []
        for agent in agents:
            status = registry.get_status(agent.name, agent.provider.organization)
            tags = registry.get_agent_tags(agent.name, agent.provider.organization)
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
