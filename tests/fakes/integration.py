# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Shared test fakes for the integration access plane.

These fakes mirror the REAL RegistryCore / StorageBackend contracts
(agent_registry/core.py, persistence/base.py). Every method documents the
real behavior it simulates — do not invent return shapes. When the real
contract changes, update the fake HERE (single source), not per test file.

Known real-contract facts that past fakes got wrong:
- RegistryCore.find_by_key() returns a protobuf AgentCard (NOT AgentRecord)
- RegistryCore.get_by_key_with_owner() returns an AgentRecord (has .owner)
- RegistryCore.get_agents() returns {key: True} (a membership dict)
"""

import json
from typing import Dict, Optional

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict, Parse

from common.custom.custom_handle import BaseHandler
from common.util.authenticate_util import AUTH_METHOD_TOKEN, CallerType, Principal


def make_agent_card(name: str, organization: str, **overrides) -> AgentCard:
    payload = {
        "name": name,
        "provider": {"organization": organization, "url": "https://example.com"},
        "description": f"agent {name}",
        "version": "1.0.0",
        "skills": [],
    }
    payload.update(overrides)
    return Parse(json.dumps(payload), AgentCard())


class FakeRecord:
    """Mirrors persistence.base.AgentRecord's field surface."""

    def __init__(self, agent_card: AgentCard, owner=None, status="published"):
        self.agent_card = agent_card
        self.owner = owner
        self.status = status
        self.created_at = "2026-01-01T00:00:00+00:00"
        self.updated_at = "2026-01-01T00:00:00+00:00"
        self.tags = []


class FakeRegistry:
    """In-memory RegistryCore double matching the real method contracts."""

    def __init__(self):
        self._records: Dict[tuple, FakeRecord] = {}

    # --- handler-facing methods (InterfaceType.INSERT/QUERY/UPDATE/...) ---

    def register_with_status(self, agent: AgentCard, initial_status='published', owner=None):
        """Real: storage.create(); False on duplicate (name, organization)."""
        key = (agent.name, agent.provider.organization)
        if key in self._records:
            return False
        self._records[key] = FakeRecord(MessageToDict(agent), owner, initial_status)
        return True

    def find_exact(self, name=None, organization=None):
        """Real: returns a list of published AgentCard objects."""
        return [r.agent_card for (n, o), r in self._records.items()
                if (name is None or n == name) and (organization is None or o == organization)]

    def get_by_key_with_owner(self, name, organization, owner=None):
        """Real: returns an AgentRecord (with .owner) or None."""
        return self._records.get((name, organization))

    def update(self, name, organization, data, owner=None):
        """Real: parses `data` into AgentCard; False when absent; owner param
        restricts the update to rows owned by `owner` or public rows."""
        key = (name, organization)
        if key not in self._records:
            return False
        record = self._records[key]
        if owner is not None and record.owner not in (owner, None):
            return False
        record.agent_card = Parse(json.dumps(data), AgentCard())
        return True

    def deregister(self, name, organization, owner=None):
        """Real: False when absent; owner param restricts like update()."""
        key = (name, organization)
        if key not in self._records:
            return False
        if owner is not None and self._records[key].owner not in (owner, None):
            return False
        del self._records[key]
        return True

    # --- direct route usage ---

    def count(self):
        return len(self._records)

    def get_agents(self):
        """Real: {key: True} membership dict (core.py:173-187)."""
        return {key: True for key in self._records}

    def get_status(self, name, organization):
        record = self._records.get((name, organization))
        return record.status if record else None

    def find_by_key(self, name, organization):
        """Real: returns a protobuf AgentCard or None (core.py:382-384)."""
        record = self._records.get((name, organization))
        return record.agent_card if record else None


class StubAuthnHandler(BaseHandler):
    """THIRD_PARTY_AUTHENTICATE-slot stub: returns a configured Principal or
    raises a configured error. `credentials` mirrors the real handler's
    provisioned-credential map for ban-key derivation tests."""

    def __init__(self):
        self.principal: Optional[Principal] = None
        self.error: Optional[Exception] = None
        self.credentials: dict = {}

    async def handle(self, client_ip, request):
        if self.error is not None:
            raise self.error
        return self.principal


def make_third_party_principal(role, identity="svc_app", owner=None) -> Principal:
    return Principal(client_ip="10.1.1.9", identity=identity,
                     caller_type=CallerType.THIRD_PARTY, role=role,
                     auth_method=AUTH_METHOD_TOKEN, owner=owner or identity)
