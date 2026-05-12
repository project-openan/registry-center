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

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from a2a.types import AgentCard
from agent_registry.model.tag import Tag


@dataclass
class AgentRecord:
    agent_card: AgentCard
    owner: Optional[str] = None
    status: str = 'published'
    created_at: str = ''
    updated_at: str = ''
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_card": self.agent_card,
            "owner": self.owner,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags
        }


class StorageBackend(ABC):
    @classmethod
    @abstractmethod
    def init(cls, config: dict) -> 'StorageBackend':
        pass

    @abstractmethod
    def create(self, agent: AgentCard, owner: Optional[str] = None, status: Optional[str] = None) -> bool:
        pass

    @abstractmethod
    def find_by_key(self, name: str, organization: str, owner: Optional[str] = None) -> Optional[AgentRecord]:
        pass

    @abstractmethod
    def find_by_name(self, name: str) -> List[AgentCard]:
        pass

    @abstractmethod
    def find_by_organization(self, organization: str) -> List[AgentCard]:
        pass

    @abstractmethod
    def find_all(self) -> List[AgentCard]:
        pass

    @abstractmethod
    def find_by_owner(self, owner: str) -> List[AgentRecord]:
        pass

    @abstractmethod
    def update(self, name: str, organization: str, agent_data: Dict[str, Any], owner: Optional[str] = None) -> bool:
        pass

    @abstractmethod
    def delete(self, name: str, organization: str, owner: Optional[str] = None) -> bool:
        pass

    @abstractmethod
    def count(self) -> int:
        pass

    # Agent tags methods
    @abstractmethod
    def get_agent_tags(self, name: str, organization: str) -> List[str]:
        """Get tags associated with an agent (from agent_card table)."""
        pass

    @abstractmethod
    def update_agent_tags(self, name: str, organization: str, tags: List[str]) -> bool:
        """Update tags for an agent (in agent_card table)."""
        pass

    # Tag entity management methods (for managing independent tag entities)
    @abstractmethod
    def create_tag(self, tag: Tag) -> bool:
        """Create a new tag entity."""
        pass

    @abstractmethod
    def get_tag(self, tag_id: str) -> Optional[Tag]:
        """Get tag by tag_id."""
        pass

    @abstractmethod
    def get_tag_by_name(self, name: str) -> Optional[Tag]:
        """Get tag by name."""
        pass

    @abstractmethod
    def update_tag(self, tag_id: str, tag: Tag) -> bool:
        """Update tag entity."""
        pass

    @abstractmethod
    def delete_tag(self, tag_id: str) -> bool:
        """Delete tag entity."""
        pass

    @abstractmethod
    def list_tags(self) -> List[Tag]:
        """List all tags."""
        pass

    @abstractmethod
    def close(self):
        pass