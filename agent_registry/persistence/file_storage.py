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

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict
from loguru import logger

from agent_registry.config import PERSISTENCE_METADATA_FILE
from .base import StorageBackend


class FileStorage(StorageBackend):
    def __init__(self, file_path: str, metadata_file: str = None, max_file_size: int = 100 * 1024 * 1024):
        self.file_path = file_path
        self.metadata_file = metadata_file or str(Path(file_path).parent / PERSISTENCE_METADATA_FILE)
        self.max_file_size = max_file_size
        self._agents: Dict[tuple, AgentCard] = {}
        self._status_map: Dict[tuple, str] = {}
        self._load()

    @classmethod
    def init(cls, config: dict) -> 'FileStorage':
        file_path = config.get('file.path', 'data/agentcard.json')
        metadata_file = config.get('metadata.file', f'data/{PERSISTENCE_METADATA_FILE}')
        max_file_size = config.get('max_file_size', 100 * 1024 * 1024)
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        instance = cls(file_path, metadata_file, max_file_size)
        logger.info(f"FileStorage initialized with path: {file_path}")
        return instance

    def create(self, agent: AgentCard) -> bool:
        key = (agent.name.strip(), agent.provider.organization.strip())
        self._agents[key] = agent
        if hasattr(agent, 'status'):
            self._status_map[key] = agent.status
        else:
            self._status_map[key] = 'published'
        self._save()
        logger.info(f"Registered agent: {agent.name} (org={agent.provider.organization})")
        return True

    def find_by_key(self, name: str, organization: str) -> Optional[AgentCard]:
        key = (name.strip(), organization.strip())
        agent = self._agents.get(key)
        if agent and key in self._status_map:
            agent.status = self._status_map[key]
        return agent

    def find_by_name(self, name: str) -> List[AgentCard]:
        result = []
        for key, agent in self._agents.items():
            if name and agent.name == name:
                if key in self._status_map:
                    agent.status = self._status_map[key]
                result.append(agent)
        return result

    def find_by_organization(self, organization: str) -> List[AgentCard]:
        result = []
        for key, agent in self._agents.items():
            if organization and agent.provider.organization == organization:
                if key in self._status_map:
                    agent.status = self._status_map[key]
                result.append(agent)
        return result

    def find_all(self) -> List[AgentCard]:
        result = []
        for key, agent in self._agents.items():
            if key in self._status_map:
                agent.status = self._status_map[key]
            result.append(agent)
        return result

    def find_by_status(self, status: str) -> List[AgentCard]:
        result = []
        for key, agent in self._agents.items():
            if key in self._status_map and self._status_map[key] == status:
                agent.status = self._status_map[key]
                result.append(agent)
        return result

    def update_status(self, name: str, organization: str, new_status: str) -> bool:
        key = (name.strip(), organization.strip())
        if key not in self._agents:
            logger.warning(f"Agent not found: {name} ({organization})")
            return False
        
        self._status_map[key] = new_status
        self._save_registry()
        logger.info(f"Agent status updated: {name} -> {new_status}")
        return True

    def update(self, name: str, organization: str, agent_data: Dict[str, Any]) -> bool:
        key = (name.strip(), organization.strip())
        existing_agent = self._agents.get(key)
        if not existing_agent:
            logger.info(f"Update failed: agent not found({name},{organization})")
            return False

        if agent_data.get("name") != name or agent_data.get("provider", {}).get("organization") != organization:
            raise ValueError("Cannot change primary key(name or organization) during update.")

        try:
            new_agent = AgentCard(**agent_data)
        except Exception as e:
            logger.error(f"Invalid agent data for update: {e}")
            raise ValueError(f"Invalid agent data: {e}") from e

        self._agents[key] = new_agent
        if 'status' in agent_data:
            self._status_map[key] = agent_data['status']
        self._save()
        logger.info(f"Updated agent: {new_agent.name}(org={new_agent.provider.organization})")
        return True

    def delete(self, name: str, organization: str) -> bool:
        key = (name.strip(), organization.strip())
        if key not in self._agents:
            logger.info(f"Deregister failed: agent not found ({name},{organization})")
            return False
        del self._agents[key]
        if key in self._status_map:
            del self._status_map[key]
        self._save()
        logger.info(f"Deregistered agent: {name}({organization})")
        return True

    def count(self) -> int:
        return len(self._agents)

    def close(self):
        self._save()
        logger.info("FileStorage closed")

    def _save(self) -> None:
        self._save_agents()
        self._save_registry()

    def _save_agents(self) -> None:
        agent_cards = []
        for agent in self._agents.values():
            agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
            agent_dict.pop('status', None)
            agent_cards.append(agent_dict)

        json_str = json.dumps(agent_cards, ensure_ascii=False, indent=2)
        data_size = len(json_str.encode('utf-8'))
        if data_size > self.max_file_size:
            error_msg = f"Data size ({data_size} bytes) exceeds maximum allowed ({self.max_file_size} bytes)"
            logger.error(error_msg)
            raise ValueError(error_msg)

        Path(self.file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        os.chmod(self.file_path, 0o600)
        logger.info(f"Saved {len(self._agents)} agents to {self.file_path} ({data_size} bytes)")

    def _save_registry(self) -> None:
        registry_data = []
        for key, status in self._status_map.items():
            registry_data.append({
                "organization": key[1],
                "agent_name": key[0],
                "status": status
            })

        json_str = json.dumps(registry_data, ensure_ascii=False, indent=2)
        Path(self.metadata_file).parent.mkdir(parents=True, exist_ok=True)
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            f.write(json_str)
        os.chmod(self.metadata_file, 0o600)
        logger.info(f"Saved {len(self._status_map)} status mappings to {self.metadata_file}")

    def _load(self) -> None:
        self._load_agents()
        self._load_registry()

    def _load_agents(self) -> None:
        if not os.path.exists(self.file_path):
            logger.warning(f"Persistence file {self.file_path} not found. Starting with empty registry.")
            return

        try:
            file_size = os.path.getsize(self.file_path)
            if file_size > self.max_file_size:
                logger.error(f"File {self.file_path} size ({file_size} bytes) exceeds maximum allowed.")
                return
        except OSError as e:
            logger.error(f"Failed to check file size for {self.file_path}: {e}")
            return

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                logger.error(f"Invalid format in {self.file_path}: expected a list")
                return
            for item in data:
                try:
                    agent = AgentCard(**item)
                    key = (agent.name.strip(), agent.provider.organization.strip())
                    self._agents[key] = agent
                except Exception as e:
                    logger.error(f"Failed to load agent from JSON: {e}, data: {item}")
            logger.info(f"Loaded {len(self._agents)} agents from {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to load agents from {self.file_path}: {e}")

    def _load_registry(self) -> None:
        if not os.path.exists(self.metadata_file):
            for key in self._agents.keys():
                self._status_map[key] = 'published'
            logger.info("No registry file found, defaulting all agents to published status")
            return

        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                registry_data = json.load(f)
            if not isinstance(registry_data, list):
                logger.error(f"Invalid format in {self.metadata_file}: expected a list")
                return
            for item in registry_data:
                try:
                    key = (item['agent_name'].strip(), item['organization'].strip())
                    self._status_map[key] = item['status']
                except Exception as e:
                    logger.error(f"Failed to load status from JSON: {e}, data: {item}")
            logger.info(f"Loaded {len(self._status_map)} status mappings from {self.metadata_file}")
        except Exception as e:
            logger.error(f"Failed to load registry from {self.metadata_file}: {e}")