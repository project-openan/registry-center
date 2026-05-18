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

# agent_registry/core.py
import json
import os
from pathlib import Path
from threading import Lock
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict
from loguru import logger

from agent_registry.model.tag import Tag
from agent_registry.config import PERSISTENCE_FILE, PERSISTENCE_METADATA_FILE, USE_VECTORDB, COLLECTION_NAME, \
    PERSISTENCE_CONF, PERSISTENCE_MODE
from agent_registry.persistence import save_to_file, load_from_file
from agent_registry.persistence import StorageRegistry, StorageBackend
from agent_registry.persistence.base import AgentRecord
from agent_registry.prompts import build_agent_selection_prompt
from common.llm import get_llm_instance
from common.llm.config.llm_config import get_llm_config_by_type, LLMType
from common.llm.provider.llm_provider_registry import get_or_create_llm_instance
from common.util.config_util import get_root_path
from common.vector_db.vector_db_client.config.vector_db_client_registry import get_or_create_vectordb_tool_instance
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType, get_vectordb_config_by_type


def make_agent_key(name: str, organization: str) -> Tuple[str, str]:
    """Create a normalized key for indexing."""
    return name.strip(), organization.strip()


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
        self._status_map: Dict[Tuple[str, str], str] = {}
        self._registry_tags_map: Dict[Tuple[str, str], List[str]] = {}
        self._tags: Dict[str, Tag] = {}
        self._owner_map: Dict[Tuple[str, str], Optional[str]] = {}
        self._created_at_map: Dict[Tuple[str, str], str] = {}
        self._updated_at_map: Dict[Tuple[str, str], str] = {}

        if use_vectordb:
            self.vectordb = get_or_create_vectordb_tool_instance(get_vectordb_config_by_type(VectorDBType.Milvus))
            self.embedding_tool = get_or_create_llm_instance(
                get_llm_config_by_type(LLMType.AOC_EMBEDDING_LLM))
        elif persistence_mode == 'postgresql':
            self.storage = StorageRegistry.get_backend(self.persistence_mode, self.persistence_conf)
            logger.info(f"Registry initialized with {self.persistence_mode} storage")
        else:
            data_path = Path(get_root_path()) / "data"
            data_path.mkdir(exist_ok=True)
            os.chmod(data_path, 0o700)
            self.persistence_file = str(data_path / persistence_file)
            self.metadata_file = str(data_path / persistence_metadata_file)
            self.tags_file = str(data_path / "tags.json")
            self._agents: Dict[Tuple[str, str], AgentCard] = {}
            self._load_agents()
            self._load_registry()
            self._load_tags()

    def initialize(self):
        """Initialize storage backend for PostgreSQL mode."""
        if not self.use_vectordb and self.persistence_mode == 'postgresql':
            if not self.storage:
                self.storage = StorageRegistry.get_backend(self.persistence_mode, self.persistence_conf)
                logger.info(f"Registry initialized with {self.persistence_mode} storage")

    def close(self):
        """Close storage backend connection."""
        if self.storage:
            self.storage.close()

    @staticmethod
    def _make_key(name: str, organization: str) -> Tuple[str, str]:
        """Create a normalized key for indexing."""
        return name.strip(), organization.strip()

    def register(self, agent: AgentCard, use_vectordb: bool = USE_VECTORDB, owner: Optional[str] = None) -> bool:
        """
        Register a new agent. Returns True if successful, False if duplicate.
        Raises ValueError if agent lacks required fields (name, provider.organization).
        """
        with self._lock:
            if use_vectordb:
                entity_str = json.dumps(MessageToDict(agent, preserving_proto_field_name=True))
                embedding = self.embedding_tool.embed(agent.description)
                id = self._make_id(agent.name, agent.provider.organization)
                insert_entity = {"embedding": embedding, "id": id, "name": agent.name, "description": agent.description,
                                 "organization": agent.provider.organization, "agent_card": entity_str, "owner": owner}
                insert_data = {"collection_name": COLLECTION_NAME, "entity": insert_entity}
                result = self.vectordb.insert_entity(insert_data)
                logger.info(
                    f"Registered agent in vectordb: {agent.name} (org={agent.provider.organization}, owner={owner})")
                return result
            elif self.persistence_mode == 'postgresql':
                result = self.storage.create(agent, owner=owner)
                logger.info(
                    f"Registered agent in postgresql: {agent.name} (org={agent.provider.organization}, owner={owner})")
                return result
            else:
                key = self._make_key(agent.name, agent.provider.organization)
                self._agents[key] = agent
                self._status_map[key] = 'published'
                self._owner_map[key] = owner
                now = datetime.utcnow().isoformat()
                self._created_at_map[key] = now
                self._updated_at_map[key] = now
                self._save()
                logger.info(f"Registered agent: {agent.name} (org={agent.provider.organization}, owner={owner})")
                return True

    def register_with_status(self, agent: AgentCard, initial_status: str = 'published',
                             use_vectordb: bool = USE_VECTORDB, owner: Optional[str] = None) -> bool:
        """
        Register a new agent with specified initial status.
        
        Args:
            agent: Agent to register
            initial_status: Initial status ('registered' or 'published')
            use_vectordb: Whether to use vector database
            owner: Agent owner (from TLS certificate CN)
        
        Returns:
            bool: True if successful, False if duplicate
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
            elif self.persistence_mode == 'postgresql':
                return self.storage.create(agent, owner=owner, status=initial_status)
            else:
                key = self._make_key(agent.name, agent.provider.organization)
                self._agents[key] = agent
                self._status_map[key] = initial_status
                self._owner_map[key] = owner
                now = datetime.utcnow().isoformat()
                self._created_at_map[key] = now
                self._updated_at_map[key] = now
                self._save()
                logger.info(
                    f"Registered agent: {agent.name} (org={agent.provider.organization}, status={initial_status}, owner={owner})")
                return True

    def find_exact(self, name: Optional[str] = None, organization: Optional[str] = None,
                   use_vectordb: bool = USE_VECTORDB) -> List[AgentCard]:
        """
        Exact search based on name, organization, and provider (which is provider.organization).
        All parameters are optional; if multiple are given, they are combined with AND.
        """
        if use_vectordb:
            if name is not None and organization is not None:
                query_data = {"collection_name": COLLECTION_NAME, "key": "id",
                              "value": self._make_id(name, organization)}
            elif name is not None:
                query_data = {"collection_name": COLLECTION_NAME, "key": "name", "value": name}
            else:
                query_data = {"collection_name": COLLECTION_NAME, "key": "organization", "value": organization}
            return self.vectordb.query_by_key(query_data)
        elif self.persistence_mode == 'postgresql':
            if name and organization:
                result = self.storage.find_by_key(name, organization)
                return [result] if result else []
            elif name:
                return self.storage.find_by_name(name)
            elif organization:
                return self.storage.find_by_organization(organization)
            return self.storage.find_all()
        else:
            result = []
            for agent in self._agents.values():
                if name is not None and agent.name != name:
                    continue
                if organization is not None and agent.provider.organization != organization:
                    continue
                result.append(agent)
            return result

    def get_agents(self, use_vectordb: bool = USE_VECTORDB):
        if use_vectordb:
            return self.vectordb.get_all_entities({"collection_name": COLLECTION_NAME})
        elif self.persistence_mode == 'postgresql':
            agents = self.storage.find_all()
            result = {}
            for agent in agents:
                key = make_agent_key(agent.name, agent.provider.organization)
                result[key] = agent
            return result
        else:
            return self._agents

    def update(self, name: str, organization: str, agent_data: Dict[str, Any],
               use_vectordb: bool = USE_VECTORDB, owner: Optional[str] = None) -> bool:
        """
        Update an existing agent. The primary key (name, organization) cannot be changed.
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
            elif self.persistence_mode == 'postgresql':
                result = self.storage.update(name, organization, agent_data, owner=owner)
                logger.info(f"Updated agent in postgresql: {name}({organization}, owner={owner})")
                return result
            else:
                key = self._make_key(name, organization)
                existing_agent = self._agents.get(key)
                if not existing_agent:
                    logger.info(f"Update failed: agent not found({name},{organization})")
                    return False

                stored_owner = self._owner_map.get(key)
                if stored_owner is not None and stored_owner != '':
                    if owner != stored_owner:
                        logger.warning(
                            f"Update denied: owner mismatch for {name} (stored={stored_owner}, request={owner})")
                        return False

                updated_data = agent_data
                if updated_data.get("name") != name or updated_data.get("provider", {}).get(
                        "organization") != organization:
                    raise ValueError("Cannot change primary key(name or organization) during update.")

                try:
                    new_agent = AgentCard(**updated_data)
                except Exception as e:
                    logger.error(f"Invalid agent data for update: {e}")
                    raise ValueError(f"Invalid agent data: {e}") from e

                self._agents[key] = new_agent
                self._updated_at_map[key] = datetime.utcnow().isoformat()
                self._save()
                logger.info(f"Updated agent: {new_agent.name}(org={new_agent.provider.organization}, owner={owner})")
                return True

    def deregister(self, name: str, organization: str, use_vectordb: bool = USE_VECTORDB,
                   owner: Optional[str] = None) -> bool:
        """
        Remove an agent. Returns True if deleted, False if not found.
        """
        with self._lock:
            if use_vectordb:
                delete_data = {"collection_name": COLLECTION_NAME, "id": self._make_id(name, organization)}
                result = self.vectordb.delete_entity(delete_data)
                logger.info(f"Deregistered agent from vectordb: {name}({organization}, owner={owner})")
                return result
            elif self.persistence_mode == 'postgresql':
                result = self.storage.delete(name, organization, owner=owner)
                logger.info(f"Deregistered agent from postgresql: {name}({organization}, owner={owner})")
                return result
            else:
                key = self._make_key(name, organization)
                if key not in self._agents:
                    logger.info(f"Deregister failed: agent not found ({name},{organization})")
                    return False

                stored_owner = self._owner_map.get(key)
                if stored_owner is not None and stored_owner != '':
                    if owner != stored_owner:
                        logger.warning(
                            f"Deregister denied: owner mismatch for {name} (stored={stored_owner}, request={owner})")
                        return False

                del self._agents[key]
                self._status_map.pop(key, None)
                self._registry_tags_map.pop(key, None)
                self._owner_map.pop(key, None)
                self._created_at_map.pop(key, None)
                self._updated_at_map.pop(key, None)
                self._save()
                logger.info(f"Deregistered agent: {name}({organization}, owner={owner})")
                return True

    def retrieve_by_task(self, task: str, top_n: int, use_vectordb: bool = USE_VECTORDB) -> List[AgentCard]:
        """
        Fuzzy retrieve using LLM to match task description with agent capabilities.
        Returns a list of candidate agents(could be empty).
        """
        agents_info = []
        if use_vectordb:
            retrieve_entity = {"collection_name": COLLECTION_NAME,
                               "embedding": self.embedding_tool.embed(task),
                               "top_n": top_n}
            retrieve_results = self.vectordb.retrieve_entity(retrieve_entity)
            for agent in retrieve_results:
                agents_info.append({
                    "name": agent["name"],
                    "description": agent["description"],
                    "skills": [{"skill_name": s["name"], "skill_description": s["description"]} for s in
                               agent["skills"]] if agent["skills"] else []
                })

            try:
                prompt = build_agent_selection_prompt(task, json.dumps(agents_info, ensure_ascii=False, indent=2),
                                                      top_n=top_n)
                _, selected_name_str = self.llm.ask_llm(prompt)
                trans_table = str.maketrans("", "", "\"[]")
                selected_names = [n.strip().translate(trans_table) for n in selected_name_str.split(",") if n.strip()]
            except Exception as e:
                logger.error(f"LLM error during agent selection: {e}")
                return []
            result = [agent for agent in retrieve_results if agent["name"] in selected_names]
            logger.info(f"LLM selected {len(result)} agents for task: {task}")
            return result
        elif self.persistence_mode == 'postgresql':
            agents = self.storage.find_all()
            if not task or not agents:
                return []

            for agent in agents:
                agents_info.append({
                    "name": agent.name,
                    "description": agent.description,
                    "skills": [{"skill_name": s.name, "skill_description": s.description} for s in
                               agent.skills] if agent.skills else []
                })
            try:
                prompt = build_agent_selection_prompt(task, json.dumps(agents_info, ensure_ascii=False, indent=2),
                                                      top_n=top_n)
                _, selected_name_str = self.llm.ask_llm(prompt)
                trans_table = str.maketrans("", "", "\"[]")
                selected_names = [n.strip().translate(trans_table) for n in selected_name_str.split(",") if n.strip()]
            except Exception as e:
                logger.error(f"LLM error during agent selection: {e}")
                return []

            result = [agent for agent in agents if agent.name in selected_names]
            logger.info(f"LLM selected {len(result)} agents for task: {task}")
            return result
        else:
            if not task or not self._agents:
                return []

            for agent in self._agents.values():
                agents_info.append({
                    "name": agent.name,
                    "description": agent.description,
                    "skills": [{"skill_name": s.name, "skill_description": s.description} for s in
                               agent.skills] if agent.skills else []
                })
            try:
                prompt = build_agent_selection_prompt(task, json.dumps(agents_info, ensure_ascii=False, indent=2),
                                                      top_n=top_n)
                _, selected_name_str = self.llm.ask_llm(prompt)
                trans_table = str.maketrans("", "", "\"[]")
                selected_names = [n.strip().translate(trans_table) for n in selected_name_str.split(",") if n.strip()]
            except Exception as e:
                logger.error(f"LLM error during agent selection: {e}")
                return []

            result = [agent for agent in self._agents.values() if agent.name in selected_names]
            logger.info(f"LLM selected {len(result)} agents for task: {task}")
            return result

    def get_by_key(self, name: str, organization: str, use_vectordb: bool = USE_VECTORDB) -> Optional[AgentCard]:
        """Search a single agent by exact name and organization."""
        if use_vectordb:
            query_data = {"collection_name": COLLECTION_NAME, "key": "id", "value": self._make_id(name, organization)}
            result = self.vectordb.query_by_key(query_data)
            if len(result) > 0:
                return result[0]
            else:
                return None
        elif self.persistence_mode == 'postgresql':
            record = self.storage.find_by_key(name, organization)
            return record.agent_card if record else None
        else:
            key = self._make_key(name, organization)
            return self._agents.get(key)

    def get_by_key_with_owner(self, name: str, organization: str, owner: Optional[str] = None,
                              use_vectordb: bool = USE_VECTORDB) -> Optional[AgentRecord]:
        """Search a single agent by exact name and organization, returns AgentRecord with owner."""
        if use_vectordb:
            query_data = {"collection_name": COLLECTION_NAME, "key": "id", "value": self._make_id(name, organization)}
            result = self.vectordb.query_by_key(query_data)
            if len(result) > 0:
                agent_data = result[0]
                stored_owner = agent_data.get("owner")
                return AgentRecord(
                    agent_card=AgentCard(**agent_data),
                    owner=stored_owner
                )
            else:
                return None
        elif self.persistence_mode == 'postgresql':
            return self.storage.find_by_key(name, organization, owner=owner)
        else:
            key = self._make_key(name, organization)
            agent = self._agents.get(key)
            if agent:
                stored_owner = self._owner_map.get(key)
                if owner is not None and stored_owner is not None and stored_owner != '' and stored_owner != owner:
                    return None
                return AgentRecord(
                    agent_card=agent,
                    owner=stored_owner,
                    status=self._status_map.get(key, 'published'),
                    created_at=self._created_at_map.get(key, ''),
                    updated_at=self._updated_at_map.get(key, ''),
                    tags=self._registry_tags_map.get(key, [])
                )
            return None

    def find_by_owner(self, owner: str, use_vectordb: bool = USE_VECTORDB) -> List[AgentRecord]:
        """Find all agents belonging to a specific owner."""
        if use_vectordb:
            query_data = {"collection_name": COLLECTION_NAME, "key": "owner", "value": owner}
            results = self.vectordb.query_by_key(query_data)
            return [AgentRecord(agent_card=AgentCard(**r), owner=r.get("owner")) for r in results]
        elif self.persistence_mode == 'postgresql':
            return self.storage.find_by_owner(owner)
        else:
            result = []
            for key, stored_owner in self._owner_map.items():
                if stored_owner == owner:
                    agent = self._agents.get(key)
                    if agent:
                        result.append(AgentRecord(
                            agent_card=agent,
                            owner=stored_owner,
                            status=self._status_map.get(key, 'published'),
                            created_at=self._created_at_map.get(key, ''),
                            updated_at=self._updated_at_map.get(key, ''),
                            tags=self._registry_tags_map.get(key, [])
                        ))
            return result

    def _save(self) -> None:
        """Persist current agents and status map to files."""
        self._save_agents()
        self._save_registry()

    def _save_agents(self) -> None:
        """Persist agents to agentcard.json (without status)."""
        data = []
        for agent in self._agents.values():
            agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
            agent_dict.pop('status', None)
            data.append(agent_dict)
        save_to_file(self.persistence_file, data)

    def _save_registry(self) -> None:
        """Save status and tags map to agentregistry.json (file mode only)."""
        registry_data = []
        for key, status in self._status_map.items():
            tags = self._registry_tags_map.get(key, [])
            created_at = self._created_at_map.get(key, '')
            updated_at = self._updated_at_map.get(key, '')
            registry_data.append({
                "organization": key[1],
                "agent_name": key[0],
                "status": status,
                "owner": self._owner_map.get(key),
                "tags": tags,
                "created_at": created_at,
                "updated_at": updated_at
            })
        save_to_file(self.metadata_file, registry_data)

    def _load(self) -> None:
        """Load agents and status map from files."""
        self._load_agents()
        self._load_registry()
        self._load_tags()

    def _load_agents(self) -> None:
        """Load agents from agentcard.json."""
        data_list = load_from_file(self.persistence_file)
        for item in data_list:
            try:
                agent = AgentCard(**item)
                key = self._make_key(agent.name, agent.provider.organization)
                self._agents[key] = agent
            except Exception as e:
                logger.error(f"Failed to load agent from JSON: {e}, data: {item}")
        logger.info(f"Loaded {len(self._agents)} agents from persistence.")

    def _load_registry(self) -> None:
        """Load status and tags map from agentregistry.json (file mode only)."""
        if os.path.exists(self.metadata_file):
            registry_data = load_from_file(self.metadata_file)
            for item in registry_data:
                try:
                    key = self._make_key(item['agent_name'], item['organization'])
                    self._status_map[key] = item.get('status', 'published')
                    self._registry_tags_map[key] = item.get('tags', [])
                    self._owner_map[key] = item.get('owner')
                    self._created_at_map[key] = item.get('created_at', '')
                    self._updated_at_map[key] = item.get('updated_at', '')
                except Exception as e:
                    logger.error(f"Failed to load status from JSON: {e}, data: {item}")
            logger.info(f"Loaded {len(self._status_map)} status mappings from registry.")
        else:
            for key in self._agents.keys():
                self._status_map[key] = 'published'
                self._registry_tags_map[key] = []
                self._owner_map[key] = None
                self._created_at_map[key] = ''
                self._updated_at_map[key] = ''
            logger.info("No registry file found, defaulting all agents to published status")

    def _load_tags(self) -> None:
        """Load tag entities from tags.json (file mode only)."""
        if not os.path.exists(self.tags_file):
            logger.info("No tags file found, starting with empty tags")
            return
        
        try:
            with open(self.tags_file, 'r', encoding='utf-8') as f:
                tag_data = json.load(f)
            for item in tag_data:
                tag = Tag(**item)
                self._tags[tag.tag_id] = tag
            logger.info(f"Loaded {len(self._tags)} tags from {self.tags_file}")
        except Exception as e:
            logger.error(f"Failed to load tags from {self.tags_file}: {e}")

    def _save_tags(self) -> None:
        """Save tag entities to tags.json (file mode only)."""
        tag_data = []
        for tag in self._tags.values():
            tag_data.append({
                "tag_id": tag.tag_id,
                "name": tag.name,
                "created_at": tag.created_at,
                "updated_at": tag.updated_at
            })
        
        save_to_file(self.tags_file, tag_data)
        logger.info(f"Saved {len(self._tags)} tags to {self.tags_file}")

    def _make_id(self, name: str, organization: str):
        return name + organization

    def find_by_key(self, name: str, organization: str) -> Optional[AgentCard]:
        """Search a single agent by exact name and organization."""
        if self.persistence_mode == 'postgresql':
            return self.storage.find_by_key(name, organization)
        else:
            key = self._make_key(name, organization)
            return self._agents.get(key)

    def find_all(self) -> List[AgentCard]:
        """Get all agents."""
        if self.persistence_mode == 'postgresql':
            return self.storage.find_all()
        else:
            return list(self._agents.values())

    def get_status(self, name: str, organization: str) -> str:
        """Get agent status from status map."""
        if self.persistence_mode == 'postgresql':
            agent = self.storage.find_by_key(name, organization)
            if agent:
                return getattr(agent, 'status', 'published')
            return ''
        else:
            key = self._make_key(name, organization)
            return self._status_map.get(key)


    def get_metadata(self, name: str, organization: str) -> Dict[str, Any]:
        """
        Get agent metadata (agent_name, organization, status, tag).

        Args:
            name: Agent name
            organization: Organization name

        Returns:
            dict: Agent metadata
        """
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
        if self.persistence_mode == 'postgresql':
            return self.storage.get_created_at(name, organization)
        else:
            key = self._make_key(name, organization)
            return self._created_at_map.get(key, '')

    def get_updated_at(self, name: str, organization: str) -> str:
        """Get agent updated_at timestamp."""
        if self.persistence_mode == 'postgresql':
            return self.storage.get_updated_at(name, organization)
        else:
            key = self._make_key(name, organization)
            return self._updated_at_map.get(key, '')

    def update_status(self, name: str, organization: str, new_status: str) -> bool:
        """
        Update agent status.
        
        Args:
            name: Agent name
            organization: Organization name
            new_status: New status (registered/published)
        
        Returns:
            bool: Whether update was successful
        """
        with self._lock:
            if self.persistence_mode == 'postgresql':
                agent = self.storage.find_by_key(name, organization)
                if not agent:
                    logger.warning(f"Agent not found: {name} ({organization})")
                    return False

                return self.storage.update_status(name, organization, new_status)
            else:
                key = self._make_key(name, organization)
                if key not in self._agents:
                    logger.warning(f"Agent not found: {name} ({organization})")
                    return False

                self._status_map[key] = new_status
                self._updated_at_map[key] = datetime.utcnow().isoformat()
                self._save_registry()
                logger.info(f"Agent status updated: {name} -> {new_status}")
                return True

    def get_agents_by_status(self, status: str) -> List[AgentCard]:
        """
        Get agents by status.
        
        Args:
            status: Agent status (registered/published)
        
        Returns:
            List[AgentCard]: List of agents with specified status
        """
        if self.persistence_mode == 'postgresql':
            return self.storage.find_by_status(status)
        else:
            result = []
            for key, agent in self._agents.items():
                if key in self._status_map and self._status_map[key] == status:
                    result.append(agent)
            return result

    def count(self) -> int:
        """Get total number of agents."""
        if self.persistence_mode == 'postgresql':
            return self.storage.count()
        else:
            return len(self._agents)

    # Agent tags methods (for other systems)
    def get_agent_tags(self, name: str, organization: str) -> List[str]:
        """Get tags associated with an agent."""
        if self.persistence_mode == 'postgresql':
            return self.storage.get_agent_tags(name, organization)
        else:
            key = self._make_key(name, organization)
            return self._registry_tags_map.get(key, [])

    def update_agent_tags(self, name: str, organization: str, tags: List[str]) -> bool:
        """Update tags for an agent (full replacement)."""
        with self._lock:
            if self.persistence_mode == 'postgresql':
                return self.storage.update_agent_tags(name, organization, tags)
            else:
                key = self._make_key(name, organization)
                if key not in self._agents:
                    logger.warning(f"Agent not found: {name} ({organization})")
                    return False
                self._registry_tags_map[key] = tags
                self._updated_at_map[key] = datetime.utcnow().isoformat()
                self._save_registry()
                logger.info(f"Agent tags updated: {name} -> {tags}")
                return True

    def find_agents_by_tag(self, tag: str) -> List[AgentCard]:
        """Find agents that have a specific tag."""
        if self.persistence_mode == 'postgresql':
            return self.storage.find_by_tag(tag)
        else:
            result = []
            for key, agent_tags in self._registry_tags_map.items():
                if tag in agent_tags:
                    agent = self._agents.get(key)
                    if agent:
                        result.append(agent)
            return result

    # Tag entity management methods
    def create_tag(self, name: str) -> Tag:
        """Create a new tag entity."""
        with self._lock:
            if self.persistence_mode == 'postgresql':
                tag = Tag(name=name)
                if self.storage.create_tag(tag):
                    logger.info(f"Tag created: {name}")
                    return tag
                else:
                    logger.warning(f"Failed to create tag: {name}")
                    return None
            else:
                tag = Tag(name=name)
                if tag.tag_id in self._tags:
                    logger.warning(f"Tag already exists: {tag.tag_id}")
                    return None
                for existing_tag in self._tags.values():
                    if existing_tag.name == name:
                        logger.warning(f"Tag name already exists: {name}")
                        return None
                self._tags[tag.tag_id] = tag
                self._save_tags()
                logger.info(f"Tag created: {name}")
                return tag

    def get_tag(self, tag_id: str) -> Optional[Tag]:
        """Get tag by tag_id."""
        if self.persistence_mode == 'postgresql':
            return self.storage.get_tag(tag_id)
        else:
            return self._tags.get(tag_id)

    def get_tag_by_name(self, name: str) -> Optional[Tag]:
        """Get tag by name."""
        if self.persistence_mode == 'postgresql':
            return self.storage.get_tag_by_name(name)
        else:
            for tag in self._tags.values():
                if tag.name == name:
                    return tag
            return None

    def update_tag(self, tag_id: str, new_name: str) -> bool:
        """Update tag name."""
        with self._lock:
            if self.persistence_mode == 'postgresql':
                tag = self.storage.get_tag(tag_id)
                if not tag:
                    logger.warning(f"Tag not found: {tag_id}")
                    return False
                tag.name = new_name
                tag.update_timestamp()
                return self.storage.update_tag(tag_id, tag)
            else:
                if tag_id not in self._tags:
                    logger.warning(f"Tag not found: {tag_id}")
                    return False
                for existing_tag_id, existing_tag in self._tags.items():
                    if existing_tag_id != tag_id and existing_tag.name == new_name:
                        logger.warning(f"Tag name already exists: {new_name}")
                        return False
                tag = self._tags[tag_id]
                tag.name = new_name
                tag.update_timestamp()
                self._save_tags()
                logger.info(f"Tag updated: {tag_id} -> {new_name}")
                return True

    def delete_tag(self, tag_id: str) -> bool:
        """Delete a tag entity."""
        with self._lock:
            if self.persistence_mode == 'postgresql':
                return self.storage.delete_tag(tag_id)
            else:
                if tag_id not in self._tags:
                    logger.warning(f"Tag not found: {tag_id}")
                    return False
                deleted_tag = self._tags.pop(tag_id)
                self._save_tags()
                logger.info(f"Tag deleted: {tag_id}")
                return True

    def list_tags(self) -> List[Tag]:
        """List all tags."""
        if self.persistence_mode == 'postgresql':
            return self.storage.list_tags()
        else:
            return list(self._tags.values())
