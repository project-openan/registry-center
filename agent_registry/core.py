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

# agent_registry/core.py
import json
import os
import re
from pathlib import Path
IS_WINDOWS = os.name == 'nt'
from threading import Lock
from typing import List, Dict, Tuple, Optional, Any

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict, Parse
from loguru import logger

from agent_registry.model.tag import Tag
from agent_registry.config import PERSISTENCE_FILE, PERSISTENCE_METADATA_FILE, USE_VECTORDB, COLLECTION_NAME, \
    PERSISTENCE_CONF, PERSISTENCE_MODE
from agent_registry.persistence import StorageRegistry, StorageBackend
from agent_registry.persistence.base import AgentRecord
from agent_registry.prompts import build_agent_selection_prompt
from common.llm import get_llm_instance, get_embed_instance
from common.util.app_config import get_root_path
from common.vector_db.vector_db_client.config.vector_db_client_registry import get_or_create_vectordb_tool_instance
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType, get_vectordb_config_by_type


def make_agent_key(name: str, organization: str) -> Tuple[str, str]:
    """Create a normalized key for indexing."""
    return name.strip(), organization.strip()


def make_agent_id(name: str, organization: str) -> str:
    """Create a delimited ID for vector database indexing."""
    return f"{name}::{organization}"


class RegistryCore:
    """
    Core registry that stores AgentCard instances with (name, organization) as unique key.
    Provides registration, update, deletion, exact search, and LLM-based fuzzy search.
    Supports persistence to a JSON file, PostgreSQL, or vectordb.
    """

    def __init__(self, persistence_file: str = PERSISTENCE_FILE,
                 persistence_metadata_file: str = PERSISTENCE_METADATA_FILE,
                 use_vectordb: bool = USE_VECTORDB,
                 persistence_mode: str = PERSISTENCE_MODE, persistence_conf: dict = PERSISTENCE_CONF):
        self.llm = get_llm_instance()
        self.use_vectordb = use_vectordb
        self.persistence_mode = persistence_mode
        self.persistence_conf = persistence_conf
        self.storage: Optional[StorageBackend] = None
        self._lock = Lock()

        if use_vectordb:
            self.vectordb = get_or_create_vectordb_tool_instance(get_vectordb_config_by_type(VectorDBType.Milvus))
            self.embedding_tool = get_embed_instance()
        elif persistence_mode in ('postgresql', 'sqlite', 'gauss'):
            self.storage = StorageRegistry.get_backend(self.persistence_mode, self.persistence_conf)
            logger.info(f"Registry initialized with {self.persistence_mode} storage")
        else:
            data_path = Path(get_root_path()) / "data"
            data_path.mkdir(parents=True, exist_ok=True)
            if not IS_WINDOWS:
                os.chmod(data_path, 0o700)
            file_storage_conf = {
                'file.path': str(data_path / persistence_file),
                'metadata.file': str(data_path / persistence_metadata_file),
                'tags.file': str(data_path / "tags.json"),
            }
            self.storage = StorageRegistry.get_backend('file', file_storage_conf)
            logger.info(f"Registry initialized with file storage at {data_path}")

    def initialize(self):
        """Initialize storage backend for file or PostgreSQL mode."""
        if not self.use_vectordb and not self.storage:
            self.storage = StorageRegistry.get_backend(self.persistence_mode, self.persistence_conf)
            logger.info(f"Registry initialized with {self.persistence_mode} storage")

    def close(self):
        """Close storage backend connection."""
        if self.storage:
            self.storage.close()

    @staticmethod
    def _make_key(name: str, organization: str) -> Tuple[str, str]:
        """Create a normalized key for indexing."""
        return make_agent_key(name, organization)

    def register(self, agent: AgentCard, use_vectordb: bool = USE_VECTORDB, owner: Optional[str] = None) -> bool:
        """
        Register a new agent. Returns True if successful, False if duplicate.
        Raises ValueError if agent lacks required fields (name, provider.organization).
        """
        return self.register_with_status(agent, initial_status='published', use_vectordb=use_vectordb, owner=owner)

    def register_with_status(self, agent: AgentCard, initial_status: str = 'published',
                             use_vectordb: bool = USE_VECTORDB, owner: Optional[str] = None) -> bool:
        """
        Register a new agent with specified initial status.
        """
        with self._lock:
            if use_vectordb:
                entity_str = json.dumps(MessageToDict(agent, preserving_proto_field_name=True))
                embedding = self.embedding_tool.embed(agent.description)
                id = self._make_id(agent.name, agent.provider.organization)
                insert_entity = {"embedding": embedding, "id": id, "name": agent.name,
                                 "description": agent.description,
                                 "organization": agent.provider.organization,
                                 "agent_card": entity_str, "status": initial_status, "owner": owner}
                insert_data = {"collection_name": COLLECTION_NAME, "entity": insert_entity}
                return self.vectordb.insert_entity(insert_data)
            else:
                result = self.storage.create(agent, owner=owner, status=initial_status)
                if result:
                    logger.info(
                        f"Registered agent: {agent.name} (org={agent.provider.organization}, status={initial_status}, owner={owner})")
                return result

    def find_exact(self, name: Optional[str] = None, organization: Optional[str] = None,
                   use_vectordb: bool = USE_VECTORDB) -> List[AgentCard]:
        """
        Exact search based on name, organization.
        All parameters are optional; if multiple are given, they are combined with AND.
        """
        if use_vectordb:
            if name is not None and organization is not None:
                query_data = {"collection_name": COLLECTION_NAME, "key": "id",
                              "value": self._make_id(name, organization)}
            elif name is not None:
                query_data = {"collection_name": COLLECTION_NAME, "key": "name", "value": name}
            elif organization is not None:
                query_data = {"collection_name": COLLECTION_NAME, "key": "organization", "value": organization}
            else:
                entities = self.vectordb.get_all_entities({"collection_name": COLLECTION_NAME})
                result = []
                for agent_dict in entities:
                    agent_card_json = agent_dict.get("agent_card", "{}")
                    result.append(Parse(agent_card_json, AgentCard()))
                return result
            return self.vectordb.query_by_key(query_data)
        else:
            if name and organization:
                record = self.storage.find_by_key(name, organization)
                return [record.agent_card] if record else []
            elif name:
                return self.storage.find_by_name(name)
            elif organization:
                return self.storage.find_by_organization(organization)
            return self.storage.find_all()

    def get_agents(self, use_vectordb: bool = USE_VECTORDB):
        if use_vectordb:
            entities = self.vectordb.get_all_entities({"collection_name": COLLECTION_NAME})
            result = {}
            for agent_dict in entities:
                key = make_agent_key(agent_dict.get("name", ""), agent_dict.get("organization", ""))
                result[key] = True
            return result
        else:
            agents = self.storage.find_all()
            result = {}
            for agent in agents:
                key = make_agent_key(agent.name, agent.provider.organization)
                result[key] = True
            return result

    def update(self, name: str, organization: str, agent_data: Dict[str, Any],
               use_vectordb: bool = USE_VECTORDB, owner: Optional[str] = None) -> bool:
        """
        Update an existing agent. The primary key (name, organization) cannot be changed.
        Owner permission must be verified by the caller before invoking.
        Return True if successful, False if not found.
        """
        with self._lock:
            if use_vectordb:
                entity_str = json.dumps(agent_data)
                embedding = self.embedding_tool.embed(agent_data["description"])
                key = self._make_id(agent_data["name"], agent_data["provider"]["organization"])
                insert_entity = {"id": key, "embedding": embedding, "name": agent_data["name"],
                                 "description": agent_data["description"],
                                 "organization": agent_data["provider"]["organization"], "agent_card": entity_str,
                                 "owner": owner}
                update_data = {"collection_name": COLLECTION_NAME, "entity": insert_entity}
                result = self.vectordb.update_entity(update_data)
                logger.info(f"Updated agent in vectordb: {name}({organization}, owner={owner})")
                return result
            else:
                result = self.storage.update(name, organization, agent_data, owner=owner)
                logger.info(f"Updated agent: {name}({organization}, owner={owner})")
                return result

    def deregister(self, name: str, organization: str, use_vectordb: bool = USE_VECTORDB,
                   owner: Optional[str] = None) -> bool:
        """
        Remove an agent. Returns True if deleted, False if not found.
        Owner permission must be verified by the caller before invoking.
        """
        with self._lock:
            if use_vectordb:
                delete_data = {"collection_name": COLLECTION_NAME, "id": self._make_id(name, organization)}
                result = self.vectordb.delete_entity(delete_data)
                logger.info(f"Deregistered agent from vectordb: {name}({organization}, owner={owner})")
                return result
            else:
                result = self.storage.delete(name, organization, owner=owner)
                logger.info(f"Deregistered agent: {name}({organization}, owner={owner})")
                return result

    def _select_agents_by_llm(self, task: str, agents_info: List[dict], top_n: int) -> list:
        """Use LLM to select the most relevant agents, returning list of (org, name) tuples."""
        try:
            prompt = build_agent_selection_prompt(task, json.dumps(agents_info, ensure_ascii=False, indent=2),
                                                  top_n=top_n)
            _, selected_str = self.llm.ask_llm(prompt)
            selected = self._parse_llm_json_response(selected_str)
            return [(item.get("organization", ""), item["name"]) for item in selected
                    if isinstance(item, dict) and "name" in item]
        except Exception as e:
            logger.error(f"LLM error during agent selection: {e}")
            return []

    def _parse_llm_json_response(self, text: str) -> list:
        text = text.strip()
        if not text:
            return []
        m = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        return json.loads(text)

    def _build_agents_info(self, agents: List) -> List[dict]:
        result = []
        for agent in agents:
            if isinstance(agent, dict):
                result.append({
                    "name": agent.get("name", ""),
                    "description": agent.get("description", ""),
                    "organization": agent.get("organization", ""),
                })
            else:
                skills_list = [s.name for s in agent.skills] if agent.skills else []
                result.append({
                    "name": agent.name,
                    "description": agent.description,
                    "organization": agent.provider.organization,
                    "skills": skills_list,
                })
        return result

    def retrieve_by_task(self, task: str, top_n: int, use_vectordb: bool = USE_VECTORDB) -> List[AgentCard]:
        """
        Fuzzy retrieve using LLM to match task description with agent capabilities.
        Returns a list of candidate agents(could be empty).
        """
        if not task:
            return []

        if use_vectordb:
            retrieve_entity = {"collection_name": COLLECTION_NAME,
                               "embedding": self.embedding_tool.embed(task),
                               "top_n": top_n}
            retrieve_results = self.vectordb.retrieve_entity(retrieve_entity)
            agents_info = self._build_agents_info(retrieve_results)
            selected_pairs = self._select_agents_by_llm(task, agents_info, top_n)
            result = [agent for agent in retrieve_results
                      if (agent.get("organization", ""), agent["name"]) in selected_pairs]
        else:
            agents = self.storage.find_all()
            if not agents:
                return []
            agents_info = self._build_agents_info(agents)
            selected_pairs = self._select_agents_by_llm(task, agents_info, top_n)
            result = [agent for agent in agents
                      if (agent.provider.organization, agent.name) in selected_pairs]

        logger.info(f"LLM selected {len(result)} agents for task: {task}")
        return result

    def get_by_key(self, name: str, organization: str, use_vectordb: bool = USE_VECTORDB) -> Optional[AgentCard]:
        """Search a single agent by exact name and organization."""
        if use_vectordb:
            query_data = {"collection_name": COLLECTION_NAME, "key": "id", "value": self._make_id(name, organization)}
            result = self.vectordb.query_by_key(query_data)
            if len(result) > 0:
                agent_data = result[0]
                agent_card_json = agent_data.get("agent_card", "{}")
                return Parse(agent_card_json, AgentCard())
            else:
                return None
        else:
            record = self.storage.find_by_key(name, organization)
            return record.agent_card if record else None

    def get_by_key_with_owner(self, name: str, organization: str, owner: Optional[str] = None,
                              use_vectordb: bool = USE_VECTORDB) -> Optional[AgentRecord]:
        """Search a single agent by exact name and organization, returns AgentRecord with owner."""
        if use_vectordb:
            query_data = {"collection_name": COLLECTION_NAME, "key": "id", "value": self._make_id(name, organization)}
            result = self.vectordb.query_by_key(query_data)
            if len(result) > 0:
                agent_data = result[0]
                stored_owner = agent_data.get("owner")
                agent_card_json = agent_data.get("agent_card", "{}")
                return AgentRecord(
                    agent_card=Parse(agent_card_json, AgentCard()),
                    owner=stored_owner
                )
            else:
                return None
        else:
            return self.storage.find_by_key(name, organization, owner=owner)

    def find_by_owner(self, owner: str, use_vectordb: bool = USE_VECTORDB) -> List[AgentRecord]:
        """Find all agents belonging to a specific owner."""
        if use_vectordb:
            query_data = {"collection_name": COLLECTION_NAME, "key": "owner", "value": owner}
            results = self.vectordb.query_by_key(query_data)
            records = []
            for r in results:
                agent_card_json = r.get("agent_card", "{}")
                records.append(AgentRecord(agent_card=Parse(agent_card_json, AgentCard()), owner=r.get("owner")))
            return records
        else:
            return self.storage.find_by_owner(owner)

    def _make_id(self, name: str, organization: str):
        return make_agent_id(name, organization)

    def find_by_key(self, name: str, organization: str) -> Optional[AgentCard]:
        """Search a single agent by exact name and organization. Delegates to get_by_key."""
        return self.get_by_key(name, organization)

    def find_all(self) -> List[AgentCard]:
        """Get all agents."""
        return self.storage.find_all() if self.storage else []

    def get_status(self, name: str, organization: str) -> Optional[str]:
        """Get agent status from status map, or None if not found."""
        if not self.storage:
            return None
        record = self.storage.find_by_key(name, organization)
        return record.status if record else None

    def get_metadata(self, name: str, organization: str) -> Dict[str, Any]:
        """Get agent metadata (agent_name, organization, status, tag)."""
        status = self.get_status(name, organization) or 'published'
        tags = self.get_agent_tags(name, organization) or []
        created_at = self.get_created_at(name, organization) or ''
        updated_at = self.get_updated_at(name, organization) or ''
        return {
            "agent_name": name,
            "organization": organization,
            "status": status,
            "tag": tags,
            "created_at": created_at,
            "updated_at": updated_at
        }

    def get_created_at(self, name: str, organization: str) -> str:
        """Get agent created_at timestamp."""
        return self.storage.get_created_at(name, organization) if self.storage else ''

    def get_updated_at(self, name: str, organization: str) -> str:
        """Get agent updated_at timestamp."""
        return self.storage.get_updated_at(name, organization) if self.storage else ''

    def update_status(self, name: str, organization: str, new_status: str) -> bool:
        """Update agent status."""
        if new_status not in ('registered', 'published'):
            raise ValueError(f"Invalid status '{new_status}'. Must be 'registered' or 'published'.")
        with self._lock:
            if not self.storage:
                return False
            return self.storage.update_status(name, organization, new_status)

    def get_agents_by_status(self, status: str) -> List[AgentCard]:
        """Get agents by status."""
        return self.storage.find_by_status(status) if self.storage else []

    def count(self) -> int:
        """Get total number of agents."""
        if self.use_vectordb:
            entities = self.vectordb.get_all_entities({"collection_name": COLLECTION_NAME})
            return len(entities)
        return self.storage.count() if self.storage else 0

    # Agent tags methods (for other systems)
    def get_agent_tags(self, name: str, organization: str) -> List[str]:
        """Get tags associated with an agent."""
        return self.storage.get_agent_tags(name, organization) if self.storage else []

    def update_agent_tags(self, name: str, organization: str, tags: List[str]) -> bool:
        """Update tags for an agent (full replacement)."""
        with self._lock:
            return self.storage.update_agent_tags(name, organization, tags) if self.storage else False

    def find_agents_by_tag(self, tag: str) -> List[AgentCard]:
        """Find agents that have a specific tag."""
        return self.storage.find_by_tag(tag) if self.storage else []

    # Tag entity management methods
    def create_tag(self, name: str) -> Tag:
        """Create a new tag entity."""
        with self._lock:
            if not self.storage:
                return None
            tag = Tag(name=name)
            if self.storage.create_tag(tag):
                logger.info(f"Tag created: {name}")
                return tag
            else:
                logger.warning(f"Failed to create tag: {name}")
                return None

    def get_tag(self, tag_id: str) -> Optional[Tag]:
        """Get tag by tag_id."""
        return self.storage.get_tag(tag_id) if self.storage else None

    def get_tag_by_name(self, name: str) -> Optional[Tag]:
        """Get tag by name."""
        return self.storage.get_tag_by_name(name) if self.storage else None

    def update_tag(self, tag_id: str, new_name: str) -> bool:
        """Update tag name."""
        with self._lock:
            if not self.storage:
                return False
            tag = self.storage.get_tag(tag_id)
            if not tag:
                logger.warning(f"Tag not found: {tag_id}")
                return False
            tag.name = new_name
            tag.update_timestamp()
            return self.storage.update_tag(tag_id, tag)

    def delete_tag(self, tag_id: str) -> bool:
        """Delete a tag entity."""
        with self._lock:
            return self.storage.delete_tag(tag_id) if self.storage else False

    def list_tags(self) -> List[Tag]:
        """List all tags."""
        return self.storage.list_tags() if self.storage else []
