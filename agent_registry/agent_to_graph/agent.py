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
Agent operations.

Provides methods to query agent cards from the registry center.
"""

from typing import List, Optional

from a2a.types import AgentCard
from loguru import logger


def list_agents(name: Optional[str] = None, organization: Optional[str] = None) -> List[AgentCard]:
    """
    Query the agent list by directly calling the registry instance's find_exact method.

    Args:
        name: Optional exact agent name filter.
        organization: Optional exact organization filter.

    Returns:
        List of AgentCard objects, or an empty list on failure.
    """
    try:
        from agent_registry.registry_instance import get_registry

        registry = get_registry()
        return registry.find_exact(
            name=name,
            organization=organization,
            use_vectordb=False,
        )
    except Exception as e:
        logger.error(f"Error while listing agents: {e}")
        return []