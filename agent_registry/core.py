# agent_registry/core.py
import asyncio
import json
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

from a2a.types import AgentCard
from loguru import logger

from agent_registry.config import PERSISTENCE_FILE
from agent_registry.persistence import save_to_file, load_from_file
from agent_registry.prompts import build_agent_selection_prompt
from common.llm import get_llm_instance
from common.util.config_util import get_root_path


class RegistryCore:
    """
    Core registry that stores AgentCard instances with (name, organization) as unique key.
    Provides registration, update, deletion, exact search, and LLM-based fuzzy search.
    Supports persistence to a JSON file.
    """

    def __init__(self, persistence_file: str = PERSISTENCE_FILE):
        data_path = Path(get_root_path()) / "data"
        data_path.mkdir(exist_ok=True)
        os.chmod(data_path, 0o700)
        self.persistence_file = str(data_path / persistence_file)
        # Internal storage of Agents: key is (name, organization) Tuple, value is AgentCard
        self._agents: Dict[Tuple[str, str], AgentCard] = {}
        self._load()  # load from file on startup
        self.llm = get_llm_instance()

    @staticmethod
    def _make_key(name: str, organization: str) -> Tuple[str, str]:
        """Create a normalized key for indexing."""
        return name.strip(), organization.strip()

    # ---------- Public API ----------
    async def register(self, agent: AgentCard) -> bool:
        """
        Register a new agent. Returns True if successful, False if duplicate.
        Raises ValueError if agent lacks required fields (name, provider.organization).
        """
        async with asyncio.Lock():
            key = self._make_key(agent.name, agent.provider.organization)
            self._agents[key] = agent
            self._save()
            logger.info(f"Registered agent: {agent.name} (org={agent.provider.organization})")
            return True

    def find_exact(self, name: Optional[str] = None, organization: Optional[str] = None) -> List[AgentCard]:
        """
        Exact search based on name, organization, and provider (which is provider.organization).
        All parameters are optional; if multiple are given, they are combined with AND.
        """
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

    def get_agents(self):
        return self._agents

    def update(self, name: str, organization: str, agent_data: Dict[str, Any]) -> bool:
        """
        Update an existing agent.The primary key(name,organization) cannot be changed.
        Return True if successful, False if not found.
        """
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

    def deregister(self,name:str,organization: str) -> bool:
        """
        Remove an agent. Returns True if deleted, False if not found.
        """
        key = self._make_key(name, organization)
        if key not in self._agents:
            logger.info(f"Deregister failed: agent not found ({name},{organization})")
            return False
        del self._agents[key]
        self._save()
        logger.info(f"Deregistered agent: {name}({organization})")
        return True

    def retrieve_by_task(self,task:str) ->List[AgentCard]:
        """
        Fuzzy retrieve using LLM to match task description with agent capabilities.
        Returns a list of candidate agents(could be empty).
        """
        if not task or not self._agents:
            return []

        # prepare a summary of each agent for the LLM
        agents_info = []
        for agent in self._agents.values():
            agents_info.append({
                "name": agent.name,
                "description": agent.description,
                "skills": [s.name for s in agent.skills] if agent.skills else []
            })

        try:
            prompt = build_agent_selection_prompt(task,json.dumps(agents_info,ensure_ascii=False,indent=2))
            # Assume LLM returns a list of agent names (strings)
            _,selected_name_str = self.llm.ask_llm(prompt)
            selected_names = [n.strip() for n in selected_name_str.split(",") if n.strip()]
        except Exception as e:
            logger.error(f"LLM error during agent selection: {e}")
            return []

        result = [agent for agent in self._agents.values() if agent.name in selected_names]
        logger.info(f"LLM selected {len(result)} agents for task: {task}")
        return result

    def get_by_key(self,name:str,organization:str) -> Optional[AgentCard]:
        """Search a single agent by exact name and organization."""
        key = self._make_key(name, organization)
        return self._agents.get(key)

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
