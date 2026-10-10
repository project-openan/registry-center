# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""`use_vectordb=true` has no authoritative record store (the R4 finding).

With a vector collection as the only store there is nowhere to answer "is this
card approved", "who owns it", "what tags does it carry" or "what must the change
feed announce". Before this change every such call silently produced an empty or
default answer: `get_status()` returned None, `_is_discoverable()` therefore said
"no", and every public read surface returned an empty list as if the registry were
empty. These tests pin the new contract: those entry points report
`AuthoritativeStoreUnavailable` (HTTP 503 on both ports, an error response on the
UDS/TCP admin surface) instead, while `use_vectordb=false` keeps behaving exactly
as before.
"""

import json
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from a2a.types import AgentCard
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict

from agent_registry.broadcast import events as events_module
from agent_registry import server as server_module
from agent_registry.core import DISCOVERABLE_STATUS, PENDING_STATUS, RegistryCore
from agent_registry.errors import AuthoritativeStoreUnavailable
from agent_registry.internal.handlers.approval_handler import ApprovalHandler
from agent_registry.internal.handlers.list_agents_handler import ListAgentsHandler
from agent_registry.server import app, get_registry
from common.custom.interface_type import InterfaceType


def make_agent(name="TestAgent", org="TestOrg", desc="Test agent"):
    return AgentCard(
        name=name,
        provider={"organization": org, "url": "https://test.org"},
        description=desc,
        version="1.0.0",
        capabilities={"streaming": False},
        default_input_modes=[],
        default_output_modes=[],
        skills=[],
    )


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, data):
        self.events.append((event_type, data))

    def persist(self, event_type, data):
        self.events.append((event_type, data))
        return SimpleNamespace(event_id=str(len(self.events)))

    @property
    def event_types(self):
        return [event_type for event_type, _ in self.events]


@pytest.fixture
def vector_db():
    fake = MagicMock()
    fake.insert_entity.return_value = True
    fake.update_entity.return_value = True
    fake.delete_entity.return_value = True
    fake.get_all_entities.return_value = []
    fake.query_by_key.return_value = []
    return fake


@pytest.fixture
def bus():
    return FakeBus()


@pytest.fixture
def vector_registry(vector_db, bus):
    """A registry built the way `use_vectordb=true` builds one: no storage."""
    with patch("agent_registry.core.get_or_create_vectordb_tool_instance",
               return_value=vector_db), \
         patch("agent_registry.core.get_embed_instance", return_value=MagicMock()), \
         patch("agent_registry.core.get_event_bus", return_value=bus):
        core = RegistryCore(use_vectordb=True)
        assert core.storage is None
        yield core


@pytest.fixture
def temp_dir():
    directory = tempfile.mkdtemp()
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def record_store_registry(temp_dir, bus):
    """The same core with a real record store, for the zero-change invariant."""
    with patch("agent_registry.core.get_llm_instance", return_value=MagicMock()), \
         patch("agent_registry.core.get_embed_instance", return_value=MagicMock()), \
         patch("agent_registry.core.get_root_path", return_value=temp_dir), \
         patch("agent_registry.core.get_event_bus", return_value=bus), \
         patch("agent_registry.config.get_conf", return_value={}), \
         patch("agent_registry.config.get_persistence_conf",
               return_value={"persistence.mode": "file"}):
        core = RegistryCore(persistence_file="agentcard.json",
                            persistence_metadata_file="agentregistry.json",
                            use_vectordb=False, persistence_mode="file",
                            persistence_conf={})
        yield core
        core.close()


class TestVectorOnlyRefusesToGuess:

    @pytest.mark.parametrize("operation", [
        lambda r: r.get_status("TestAgent", "TestOrg"),
        lambda r: r._stored_status("TestAgent", "TestOrg"),
        lambda r: r.get_metadata("TestAgent", "TestOrg"),
        lambda r: r.get_created_at("TestAgent", "TestOrg"),
        lambda r: r.get_updated_at("TestAgent", "TestOrg"),
        lambda r: r.get_agent_tags("TestAgent", "TestOrg"),
        lambda r: r.update_agent_tags("TestAgent", "TestOrg", ["tag-a"]),
        lambda r: r.find_by_owner("owner-a"),
        lambda r: r.find_agents_by_tag("tag-a"),
        lambda r: r.get_agents_by_status(DISCOVERABLE_STATUS),
        lambda r: r.update_status("TestAgent", "TestOrg", DISCOVERABLE_STATUS),
        lambda r: r.update("TestAgent", "TestOrg", {"name": "TestAgent", "description": "x",
                                                   "provider": {"organization": "TestOrg"}}),
        lambda r: r.deregister("TestAgent", "TestOrg"),
        # Listings and tag entities are record-store questions too; returning an
        # empty list here is what made an unapproved registry look like an empty one.
        lambda r: r.find_all(),
        lambda r: r.create_tag("tag-a"),
        lambda r: r.get_tag("tag-id"),
        lambda r: r.get_tag_by_name("tag-a"),
        lambda r: r.update_tag("tag-id", "tag-b"),
        lambda r: r.delete_tag("tag-id"),
        lambda r: r.list_tags(),
    ])
    def test_status_dependent_entry_point_reports_unavailable(
            self, vector_registry, operation):
        with pytest.raises(AuthoritativeStoreUnavailable) as excinfo:
            operation(vector_registry)
        message = str(excinfo.value)
        assert "use_vectordb=true" in message
        # The message must say what to do, not just that something failed.
        assert "use_vectordb=false" in message

    def test_registration_still_populates_the_index(self, vector_registry, vector_db, bus):
        """The remaining capability: cards can be put into the collection."""
        assert vector_registry.register(make_agent(), use_vectordb=True) is True
        assert vector_db.insert_entity.called
        assert bus.event_types == [events_module.EventType.AGENT_REGISTERED]

    def test_registration_helpers_stay_index_aware(self, vector_registry, vector_db):
        """The registration path itself must keep working in this mode.

        `count()` drives the registration cap and `get_agents()` drives duplicate
        detection, so both read the collection (the only store that exists here).
        Guarding them would break the one capability this mode still offers, so they
        are the documented exceptions to the 503 contract.
        """
        vector_db.get_all_entities.return_value = [
            {"name": "TestAgent", "organization": "TestOrg", "status": DISCOVERABLE_STATUS},
        ]

        assert vector_registry.count() == 1
        assert vector_registry.get_agents() == {("TestAgent", "TestOrg"): True}

    def test_exact_card_read_still_answers_from_the_index(self, vector_registry, vector_db):
        """`get_by_key` returns the stored card itself, not a status judgement."""
        vector_db.query_by_key.return_value = [
            {"agent_card": json.dumps(MessageToDict(make_agent(), preserving_proto_field_name=True))},
        ]

        card = vector_registry.get_by_key("TestAgent", "TestOrg")

        assert card is not None and card.name == "TestAgent"

    def test_semantic_selection_refuses_unverified_cards(self, vector_registry, vector_db):
        """Candidate statuses would come from the index, so selection must fail."""
        vector_db.retrieve_entity.return_value = [
            {"name": "TestAgent", "organization": "TestOrg", "status": DISCOVERABLE_STATUS,
             "agent_card": "{}"}]
        with patch.object(vector_registry, "_select_agents_by_llm", return_value=[]):
            with pytest.raises(AuthoritativeStoreUnavailable):
                vector_registry.retrieve_by_task("find agents", top_n=5, use_vectordb=True)


class TestRecordStoreBehaviourUnchanged:
    """Invariant 2: `use_vectordb=false` must not change at all."""

    def test_status_queries_answer_normally(self, record_store_registry):
        registry = record_store_registry
        registry.register(make_agent("PublishedAgent"))
        registry.register_with_status(make_agent("PendingAgent"), initial_status=PENDING_STATUS)

        assert registry.get_status("PublishedAgent", "TestOrg") == DISCOVERABLE_STATUS
        assert registry.get_status("PendingAgent", "TestOrg") == PENDING_STATUS
        assert registry.get_metadata("PublishedAgent", "TestOrg")["status"] == DISCOVERABLE_STATUS
        assert registry.get_agents_by_status(PENDING_STATUS)[0].name == "PendingAgent"
        assert registry.find_by_owner("nobody") == []
        assert registry.get_agent_tags("PublishedAgent", "TestOrg") == []

    def test_missing_record_is_not_reported_as_published(self, record_store_registry):
        """The old metadata default turned an absent record into a published card."""
        assert record_store_registry.get_status("Ghost", "TestOrg") is None
        assert record_store_registry.get_metadata("Ghost", "TestOrg")["status"] == PENDING_STATUS


def _router(cards=None, record=None, registry=None):
    """Handler router for the endpoint tests.

    Pass `registry` to route the mutation slots (INSERT/UPDATE/DEREGISTER) to the
    *real* core methods, which is what makes the missing-store error reachable:
    stubbing those slots to return None would stop at 404 before touching storage.
    """
    def dispatch(interface_type, *args, **kwargs):
        handler = MagicMock()
        handler.handle = MagicMock(return_value=None)

        async def _handle(*_args, **_kwargs):
            if interface_type == InterfaceType.QUERY:
                return list(cards or [])
            if interface_type == InterfaceType.RETRIEVE:
                return list(cards or [])
            if interface_type == InterfaceType.GET:
                return record
            if registry is not None and interface_type == InterfaceType.INSERT:
                return registry.register_with_status(*_args, **_kwargs)
            if registry is not None and interface_type == InterfaceType.UPDATE:
                return registry.update(*_args, **_kwargs)
            if registry is not None and interface_type == InterfaceType.DEREGISTER:
                return registry.deregister(*_args, **_kwargs)
            return None
        handler.handle = _handle
        return handler
    return dispatch


class TestEndpointSurfaces:

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _client(self, registry, cards=None, record=None):
        app.dependency_overrides[get_registry] = lambda: registry
        return TestClient(app), patch(
            "common.custom.custom_handle.HandlerRegistry.get_handler",
            side_effect=_router(cards=cards, record=record, registry=registry))

    def _assert_503(self, response):
        assert response.status_code == 503
        message = response.json()["errors"]["error"][0]["errorMessage"]
        assert "use_vectordb=true" in message
        assert "authoritative record store" in message

    def test_list_returns_503_instead_of_an_empty_registry(self, vector_registry):
        client, handler_patch = self._client(vector_registry, cards=[make_agent()])
        with handler_patch:
            response = client.get("/rest/v1/registry-center/agent-cards")
        self._assert_503(response)

    def test_exact_query_returns_503(self, vector_registry):
        from agent_registry.persistence.base import AgentRecord
        record = AgentRecord(agent_card=make_agent(), owner=None, status=PENDING_STATUS)
        client, handler_patch = self._client(vector_registry, record=record)
        with handler_patch:
            response = client.get("/rest/v1/registry-center/agent-cards/TestOrg/TestAgent")
        self._assert_503(response)

    def test_semantic_query_returns_503(self, vector_registry):
        client, handler_patch = self._client(vector_registry, cards=[make_agent()])
        with handler_patch:
            response = client.post(
                "/rest/v1/registry-center/agent-cards/semantic-query?top_n=5",
                json={"task": "find agents"})
        self._assert_503(response)

    def test_update_returns_503_not_500(self, vector_registry, monkeypatch):
        """The per-card update wrapper must not turn a domain 503 into a 500.

        `_perform_update` catches Exception for the handler chain, and it wraps
        `registry.update()` — which is exactly where the missing-store error is
        raised. With owner isolation disabled nothing raises earlier, so before
        this test the documented 503 became "Internal server error".
        """
        monkeypatch.setattr(server_module, 'OWNER_ISOLATION_ENABLED', False)
        from agent_registry.signature.agent_card_signature_validator import AgentCardSignatureValidator
        app.dependency_overrides[server_module.get_signature_validator] = lambda: AgentCardSignatureValidator(
            None, signature_validation_enabled=False)
        from agent_registry.agent_registry.agent_card_signer import AgentCardSigner
        app.dependency_overrides[server_module.get_registry_signer] = lambda: AgentCardSigner(sign_enabled=False)
        client, handler_patch = self._client(vector_registry)
        with handler_patch:
            response = client.put(
                "/rest/v1/registry-center/agent-cards/TestOrg/TestAgent",
                json={"agentCards": [MessageToDict(make_agent())]})
        self._assert_503(response)

    def test_update_with_owner_isolation_never_degrades_to_500(self, vector_registry):
        """Owner isolation is on in the shipped conf: the owner lookup may answer
        "not found" from the collection, but the missing store is never a 500."""
        client, handler_patch = self._client(vector_registry)
        with handler_patch:
            response = client.put(
                "/rest/v1/registry-center/agent-cards/TestOrg/TestAgent",
                json={"agentCards": [MessageToDict(make_agent())]})
        assert response.status_code in (404, 503)
        assert "Internal server error" not in response.text

    def test_deregister_returns_503_not_500(self, vector_registry, monkeypatch):
        monkeypatch.setattr(server_module, 'OWNER_ISOLATION_ENABLED', False)
        client, handler_patch = self._client(vector_registry)
        with handler_patch:
            response = client.delete("/rest/v1/registry-center/agent-cards/TestOrg/TestAgent")
        self._assert_503(response)

    def test_health_stream_refuses_before_starting_the_stream(self, vector_registry, monkeypatch):
        """SSE commits its 200 as soon as it yields, so the guard must run first.

        The stream filters events through the visibility rule; without a record
        store that filter cannot answer, and an error raised inside the generator
        would arrive too late to become a 503.
        """
        monkeypatch.setattr(server_module, 'get_health_service',
                            lambda: SimpleNamespace(enabled=True))
        client, handler_patch = self._client(vector_registry)
        with handler_patch:
            # A 5s read timeout keeps the regression fast if the guard is ever
            # removed: the endpoint would then start an endless 200 stream.
            response = client.get("/rest/v1/registry-center/agents/health/stream", timeout=5)
        self._assert_503(response)

    def test_both_ports_map_domain_errors_to_503(self):
        """Registered on the base class, so a new domain error cannot become a 500."""
        from agent_registry.errors import (
            AuthoritativeStoreUnavailable, RegistryUnavailableError, SemanticSearchUnavailable)
        from agent_registry.integration.app import integration_app

        assert issubclass(AuthoritativeStoreUnavailable, RegistryUnavailableError)
        assert issubclass(SemanticSearchUnavailable, RegistryUnavailableError)
        for application in (app, integration_app):
            assert application.exception_handlers[RegistryUnavailableError]

    def test_change_feed_and_subscriptions_stay_available(self, vector_registry):
        """The guard is scoped: surfaces that do not need the record store work."""
        client, handler_patch = self._client(vector_registry)
        with handler_patch:
            changes = client.get("/rest/v1/registry-center/changes?since=0")
        assert changes.status_code == 200
        assert "changes" in changes.json()


class TestAdminSurface:

    def test_approval_reports_the_missing_store_to_the_cli(self, vector_registry, vector_db):
        """The UDS/TCP service turns the exception into `success: false`.

        The card is in the collection, so the handler reaches the approval step
        instead of stopping at "agent not found".
        """
        card = MessageToDict(make_agent(), preserving_proto_field_name=True)
        vector_db.query_by_key.return_value = [{"agent_card": json.dumps(card), "owner": None}]
        handler = ApprovalHandler()
        with pytest.raises(AuthoritativeStoreUnavailable):
            handler.handle({"agent_name": "TestAgent", "organization": "TestOrg"},
                           vector_registry, {"agent_approval_enabled": "true"})

    def test_listing_agents_reports_the_missing_store_to_the_cli(self, vector_registry, monkeypatch):
        # The CLI uses the default QUERY handler backed by the process singleton.
        monkeypatch.setattr('agent_registry.registry_instance._registry_instance', vector_registry)
        handler = ListAgentsHandler()
        with pytest.raises(AuthoritativeStoreUnavailable):
            handler.handle({}, vector_registry, {})
