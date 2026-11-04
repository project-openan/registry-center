# SPDX-FileCopyrightText: Copyright contributors to the OpenAN project
# SPDX-License-Identifier: Apache-2.0

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock


import pytest
from a2a.types import AgentCard
from fastapi.testclient import TestClient
from starlette.requests import Request
from agent_registry import server
from agent_registry.broadcast.event_bus import EventBus
from agent_registry.broadcast.outbox import SqlOutbox
from agent_registry.core import RegistryCore
from agent_registry.integration import app as integration
from agent_registry.model.validated_agentcard import validate_agent_card


BASE = '/rest/v1/registry-center/agent-cards'


def card(org='Org-A', name='Agent-A'):
    return AgentCard(name=name, provider={'organization': org, 'url': 'https://example.test'},
                     description='Review probe agent', version='1.0.0',
                     default_input_modes=['text/plain'], default_output_modes=['text/plain'])


def request(path, body):
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}
    return Request({'type': 'http', 'method': 'POST', 'path': path, 'raw_path': path.encode(),
                    'scheme': 'http', 'headers': [], 'query_string': b'',
                    'client': ('127.0.0.1', 54321), 'server': ('test', 80)}, receive)


@pytest.fixture
def core(tmp_path, monkeypatch):
    core = RegistryCore(use_vectordb=False, persistence_mode='sqlite',
                        persistence_conf={'sqlite.path': str(tmp_path / 'registry.db')})
    bus = EventBus(SqlOutbox(core.storage))
    monkeypatch.setattr('agent_registry.core.get_event_bus', lambda: bus)
    monkeypatch.setattr('common.custom.custom_handle.get_registry', lambda: core)
    monkeypatch.setattr(integration, 'get_registry_dependency', lambda: core)
    monkeypatch.setattr(server, 'OWNER_ISOLATION_ENABLED', False)
    monkeypatch.setitem(server.config, 'owner.identity.mode', 'certificate')
    monkeypatch.setitem(server.config, 'agent_approval_enabled', 'false')
    server.app.dependency_overrides[server.get_registry] = lambda: core
    yield core
    server.app.dependency_overrides.clear()
    core.close()


def test_integration_nonempty_semantic_returns_published_agent(core, monkeypatch):
    model = MagicMock()
    model.ask_llm.return_value = ('', '[{"name":"Agent-A","organization":"Org-A"}]')
    core._llm = model
    core.register(card())
    audit = AsyncMock()
    monkeypatch.setattr(integration, 'audit_integration', audit)
    response = asyncio.run(integration.semantic_query(
        request('/integration/v1/agent-cards/semantic-query', b'{"task":"review probe"}'),
        principal=MagicMock()))
    assert [card["name"] for card in response["agentCards"]] == ["Agent-A"]
    audit.assert_awaited_once()
    assert model.ask_llm.call_count == 1


def test_integration_empty_semantic_executes_once(core, monkeypatch):
    model = MagicMock()
    model.ask_llm.return_value = ('', '[]')
    core._llm = model
    core.register(card())
    audit = AsyncMock()
    monkeypatch.setattr(integration, 'audit_integration', audit)
    response = asyncio.run(integration.semantic_query(
        request('/integration/v1/agent-cards/semantic-query', b'{"task":"review probe"}'),
        principal=MagicMock()))
    assert response['agentCards'] == []
    assert model.ask_llm.call_count == 1
    assert audit.await_count == 1


def test_integration_layer_detail_returns_existing_registration(core, monkeypatch):
    core.register(card(), layer='ServiceLayer')
    monkeypatch.setattr(integration, 'audit_integration', AsyncMock())
    paths = {'/integration/v1/agent-cards-with-layer/{organization}/{name}'}
    guards = [route.dependant.dependencies[0].call for route in integration.integration_app.routes
              if getattr(route, 'path', '') in paths]
    for guard in guards:
        integration.integration_app.dependency_overrides[guard] = lambda: MagicMock()
    try:
        response = TestClient(integration.integration_app, raise_server_exceptions=False).get(
            '/integration/v1/agent-cards-with-layer/Org-A/Agent-A')
        assert response.status_code == 200
    finally:
        for guard in guards:
            integration.integration_app.dependency_overrides.pop(guard, None)


@pytest.mark.parametrize('route', ['legacy_with_layer', 'main_with_layer', 'integration_with_layer'])
def test_layer_llm_keeps_loop_responsive(core, monkeypatch, route):
    model = MagicMock()
    def delayed_answer(_):
        time.sleep(.35)
        return '', '[{"name":"Agent-A","organization":"Org-A"}]'
    model.ask_llm.side_effect = delayed_answer
    core._llm = model
    core.register(card(), layer='ServiceLayer')
    monkeypatch.setattr(integration, 'audit_integration', AsyncMock())
    async def measure():
        ticks = []
        async def timer():
            before = time.perf_counter()
            await asyncio.sleep(.02)
            ticks.append(time.perf_counter() - before)
        observer = asyncio.create_task(timer())
        await asyncio.sleep(0)
        body = b'{"task":"review probe","layer":"ServiceLayer"}'
        if route == 'legacy_with_layer':
            await server.retrieve_agents_by_task(request(BASE+'/semantic-query', body), registry=core)
        elif route == 'main_with_layer':
            await server.query_agent_registrations(request('/rest/v1/registry-center/agent-cards-with-layer/semantic-query', body), registry=core)
        else:
            await integration.query_agent_registrations(request('/integration/v1/agent-cards-with-layer/semantic-query', body), principal=MagicMock())
        await observer
        return ticks[0]
    delay = asyncio.run(measure())
    assert delay < .30


@pytest.mark.parametrize("organization", ["Division/West", "Division\\West", ".", ".."])
def test_organization_must_fit_in_one_path_segment(organization):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        validate_agent_card(card(org=organization))
    assert error.value.status_code == 422


def test_layer_integration_malformed_json_maps_to_422(core, monkeypatch):
    # Override only the role dependency, leaving routing/body/error handling real.
    paths = {'/integration/v1/agent-cards-with-layer', '/integration/v1/agent-cards-with-layer/semantic-query'}
    guards = [route.dependant.dependencies[0].call for route in integration.integration_app.routes
              if getattr(route, 'path', '') in paths]
    for guard in guards:
        integration.integration_app.dependency_overrides[guard] = lambda: MagicMock()
    try:
        client = TestClient(integration.integration_app, raise_server_exceptions=False)
        statuses = [client.post(path, content='{', headers={'Content-Type':'application/json'}).status_code
                    for path in sorted(paths)]
        assert statuses == [422, 422]
    finally:
        for guard in guards:
            integration.integration_app.dependency_overrides.pop(guard, None)
