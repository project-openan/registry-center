# agent_registry/core.py
import asyncio
from typing import List, Dict, Tuple, Optional

from a2a.types import AgentCard
from loguru import logger

from agent_registry.config import PERSISTENCE_FILE, MAX_REGISTER_NUM
from agent_registry.persistence import save_to_file, load_from_file


class RegistryCore:
    """
    Core registry that stores AgentCard instances with (name, organization) as unique key.
    Provides registration, update, deletion, exact search, and LLM-based fuzzy search.
    Supports persistence to a JSON file.
    """

    def __init__(self, persistence_file: str = PERSISTENCE_FILE):
        self.persistence_file = persistence_file
        # Internal storage of Agents: key is (name, organization) Tuple, value is AgentCard
        self._agents: Dict[Tuple[str, str], AgentCard] = {}
        self._load()  # load from file on startup

    # ---------- Private helpers ----------
    def _make_key(self, name: str, organization: str) -> Tuple[str, str]:
        """Create a normalized key for indexing."""
        return name.strip(), organization.strip()

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

    # ---------- Public API ----------
    async def register(self, agent: AgentCard) -> bool:
        """
        Register a new agent. Returns True if successful, False if duplicate.
        Raises ValueError if agent lacks required fields (name, provider.organization).
        """
        async with asyncio.Lock():
            if len(self._agents) > MAX_REGISTER_NUM:
                logger.error("Too many agents registered. Please deregister some agents.")
                return False

            key = self._make_key(agent.name, agent.provider.organization)
            if key in self._agents:
                logger.info(f"Registration skipped: duplicate agent ({agent.name}, {agent.provider.organization})")
                return False

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
