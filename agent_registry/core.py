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
import asyncio
import json
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

from a2a.types import AgentCard
from loguru import logger

from agent_registry.config import PERSISTENCE_FILE, USE_VECTORDB, COLLECTION_NAME
from agent_registry.persistence import save_to_file, load_from_file
from agent_registry.prompts import build_agent_selection_prompt
from common.llm import get_llm_instance
from common.util.config_util import get_root_path
from common.vector_db.embedding_model.config.embedding_config import get_embedding_config_by_type, EmbeddingType
from common.vector_db.embedding_model.config.embedding_tool_registry import get_or_create_embedding_tool_instance
from common.vector_db.vector_db_client.config.vector_db_client_registry import get_or_create_vectordb_tool_instance
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType, get_vectordb_config_by_type


class RegistryCore:
    """
    Core registry that stores AgentCard instances with (name, organization) as unique key.
    Provides registration, update, deletion, exact search, and LLM-based fuzzy search.
    Supports persistence to a JSON file.
    """

    def __init__(self, persistence_file: str = PERSISTENCE_FILE, use_vectordb: bool = USE_VECTORDB):
        self.llm = get_llm_instance()
        if use_vectordb:
            self.vectordb = get_or_create_vectordb_tool_instance(get_vectordb_config_by_type(VectorDBType.Milvus))
            self.embedding_tool = get_or_create_embedding_tool_instance(
                get_embedding_config_by_type(EmbeddingType.BGELargeZH))
        else:
            data_path = Path(get_root_path()) / "data"
            data_path.mkdir(exist_ok=True)
            os.chmod(data_path, 0o700)
            self.persistence_file = str(data_path / persistence_file)
            # Internal storage of Agents: key is (name, organization) Tuple, value is AgentCard
            self._agents: Dict[Tuple[str, str], AgentCard] = {}
            self._load()  # load from file on startup

    @staticmethod
    def _make_key(name: str, organization: str) -> Tuple[str, str]:
        """Create a normalized key for indexing."""
        return name.strip(), organization.strip()

    # ---------- Public API ----------
    async def register(self, agent: AgentCard, use_vectordb: bool = USE_VECTORDB) -> bool:
        """
        Register a new agent. Returns True if successful, False if duplicate.
        Raises ValueError if agent lacks required fields (name, provider.organization).
        """
        async with asyncio.Lock():
            if not use_vectordb:
                key = self._make_key(agent.name, agent.provider.organization)
                self._agents[key] = agent
                self._save()
                logger.info(f"Registered agent: {agent.name} (org={agent.provider.organization})")
                return True
            else:
                entity_str = json.dumps(agent.model_dump())
                embedding = self.embedding_tool.get_embedding_vector(agent.description)
                id = self._make_id(agent.name,agent.provider.organization)
                insert_entity = {"embedding": embedding, "id": id, "name": agent.name, "description": agent.description,
                                 "organization": agent.provider.organization, "agent_card": entity_str}
                insert_data = {"collection_name": COLLECTION_NAME, "entity": insert_entity}
                return self.vectordb.insert_entity(insert_data)

    def find_exact(self, name: Optional[str] = None, organization: Optional[str] = None,
                   use_vectordb: bool = USE_VECTORDB) -> \
            List[AgentCard]:
        """
        Exact search based on name, organization, and provider (which is provider.organization).
        All parameters are optional; if multiple are given, they are combined with AND.
        """
        if not use_vectordb:
            result = []
            for agent in self._agents.values():
                # Check name exact match
                if name is not None and agent.name != name:
                    continue
                # Check organization exact match
                if organization is not None and agent.provider.organization != organization:
                    continue
                result.append(agent)
            return result
        else:
            if name is not None and organization is not None:
                query_data = {"collection_name": COLLECTION_NAME, "key": "id",
                              "value": self._make_id(name,organization)}
            elif name is not None:
                query_data = {"collection_name": COLLECTION_NAME, "key": "name", "value": name}
            else:
                query_data = {"collection_name": COLLECTION_NAME, "key": "organization", "value": organization}
            return self.vectordb.query_by_key(query_data)

    def get_agents(self, use_vectordb: bool = USE_VECTORDB):
        if not use_vectordb:
            return self._agents
        else:
            return self.vectordb.get_all_entities({"collection_name": COLLECTION_NAME})

    def update(self, name: str, organization: str, agent_data: Dict[str, Any],
               use_vectordb: bool = USE_VECTORDB) -> bool:
        """
        Update an existing agent.The primary key(name,organization) cannot be changed.
        Return True if successful, False if not found.
        """
        if not use_vectordb:
            key = self._make_key(name, organization)
            existing_agent = self._agents.get(key)
            if not existing_agent:
                logger.info(f"Update failed: agent not found({name},{organization})")
                return False

            updated_data = agent_data
            if updated_data.get("name") != name or updated_data.get("provider", {}).get("organization") != organization:
                raise ValueError("Cannot change primary key(name or organization) during update.")

            try:
                new_agent = AgentCard(**updated_data)
            except Exception as e:
                logger.error(f"Invalid agent data for update: {e}")
                raise ValueError(f"Invalid agent data: {e}") from e

            self._agents[key] = new_agent
            self._save()
            logger.info(f"Updated agent: {new_agent.name}(org={new_agent.provider.organization})")
            return True
        else:
            entity_str = json.dumps(agent_data)
            embedding = self.embedding_tool.get_embedding_vector(agent_data["description"])
            key = self._make_id(agent_data["name"],agent_data["provider"]["organization"])
            insert_entity = {"id": key, "embedding": embedding, "name": agent_data["name"],
                             "description": agent_data["description"],
                             "organization": agent_data["provider"]["organization"], "agent_card": entity_str}
            update_data = {"collection_name": COLLECTION_NAME, "entity": insert_entity}
            return self.vectordb.update_entity(update_data)

    def deregister(self, name: str, organization: str, use_vectordb: bool = USE_VECTORDB) -> bool:
        """
        Remove an agent. Returns True if deleted, False if not found.
        """
        if not use_vectordb:
            key = self._make_key(name, organization)
            if key not in self._agents:
                logger.info(f"Deregister failed: agent not found ({name},{organization})")
                return False
            del self._agents[key]
            self._save()
            logger.info(f"Deregistered agent: {name}({organization})")
            return True
        else:
            delete_data = {"collection_name": COLLECTION_NAME, "id": self._make_id(name,organization)}
            return self.vectordb.delete_entity(delete_data)

    def retrieve_by_task(self, task: str, top_n: int, use_vectordb: bool = USE_VECTORDB) -> List[AgentCard]:
        """
        Fuzzy retrieve using LLM to match task description with agent capabilities.
        Returns a list of candidate agents(could be empty).
        """
        agents_info = []
        if not use_vectordb:
            if not task or not self._agents:
                return []

            # prepare a summary of each agent for the LLM
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
                # Assume LLM returns a list of agent names (strings)
                _, selected_name_str = self.llm.ask_llm(prompt)
                trans_table = str.maketrans("", "", "“\"[]")
                selected_names = [n.strip().translate(trans_table) for n in selected_name_str.split(",") if n.strip()]
            except Exception as e:
                logger.error(f"LLM error during agent selection: {e}")
                return []

            result = [agent for agent in self._agents.values() if agent.name in selected_names]
            logger.info(f"LLM selected {len(result)} agents for task: {task}")
            return result
        else:
            retrieve_entity = {"collection_name": COLLECTION_NAME,
                               "embedding": self.embedding_tool.get_embedding_vector(task),
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
                # Assume LLM returns a list of agent names (strings)
                _, selected_name_str = self.llm.ask_llm(prompt)
                trans_table = str.maketrans("", "", "“\"[]")
                selected_names = [n.strip().translate(trans_table) for n in selected_name_str.split(",") if n.strip()]
            except Exception as e:
                logger.error(f"LLM error during agent selection: {e}")
                return []
            result = [agent for agent in retrieve_results if agent["name"] in selected_names]
            logger.info(f"LLM selected {len(result)} agents for task: {task}")
            return result

    def get_by_key(self, name: str, organization: str, use_vectordb: bool = USE_VECTORDB) -> Optional[AgentCard]:
        """Search a single agent by exact name and organization."""
        if not use_vectordb:
            key = self._make_key(name, organization)
            return self._agents.get(key)
        else:
            query_data = {"collection_name": COLLECTION_NAME, "key": "id", "value": self._make_id(name,organization)}
            result = self.vectordb.query_by_key(query_data)
            if len(result) > 0:
                return result[0]
            else:
                return []

    # ---------- Private helpers ----------
    def _save(self) -> None:
        """Persist current agents to file."""
        data = [agent.model_dump() for agent in self._agents.values()]
        save_to_file(self.persistence_file, data)

    def _load(self) -> None:
        """Load agents from file and populate the dictionary."""
        data_list = load_from_file(self.persistence_file)
        for item in data_list:
            try:
                agent = AgentCard(**item)
                key = self._make_key(agent.name, agent.provider.organization)
                self._agents[key] = agent
            except Exception as e:
                logger.error(f"Failed to load agent from JSON: {e}, data: {item}")
        logger.info(f"Loaded {len(self._agents)} agents from persistence.")

    def _make_id(self, name: str, organization: str):
        return name + organization
