# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Requirement 30 (issue #83): review state machine HTTP surface.

Covers the reject / deprecate / review-status endpoints and the manage list
status filter + per-state counts, against a real sqlite-backed core.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from a2a.types import AgentCard

from agent_registry import server
from agent_registry.broadcast.event_bus import EventBus
from agent_registry.broadcast.outbox import SqlOutbox
from agent_registry.core import RegistryCore

BASE = '/rest/v1/registry-center/agent-cards'


def card(name='pending', org='org', description='test'):
    return AgentCard(name=name, description=description, version='1',
                     provider={'organization': org, 'url': 'https://example.com'})


@pytest.fixture
def client(tmp_path, monkeypatch):
    core = RegistryCore(use_vectordb=False, persistence_mode='sqlite',
                        persistence_conf={'sqlite.path': str(tmp_path / 'registry.db')})
    bus = EventBus(SqlOutbox(core.storage))
    monkeypatch.setattr('agent_registry.core.get_event_bus', lambda: bus)
    # the manage endpoint resolves the registry through the handler singleton,
    # whose module bound `get_registry` at import time
    monkeypatch.setattr('common.custom.custom_handle.get_registry', lambda: core)
    core._llm = MagicMock()
    server.app.dependency_overrides[server.get_registry] = lambda: core
    yield TestClient(server.app), core
    server.app.dependency_overrides.clear()
    core.close()


def test_reject_requires_remark(client):
    http, core = client
    core.register_with_status(card(), initial_status='registered')
    response = http.post(f'{BASE}/org/pending/reject', json={'remark': '  '})
    assert response.status_code == 400
    assert core.get_status('pending', 'org') == 'registered'


def test_reject_unknown_agent_is_404(client):
    http, _ = client
    response = http.post(f'{BASE}/org/ghost/reject', json={'remark': 'x'})
    assert response.status_code == 404


def test_reject_publishes_feedback_via_manage_and_review_status(client):
    http, core = client
    core.register_with_status(card(), initial_status='registered')
    core.register_with_status(card(name='live'), initial_status='published')

    response = http.post(f'{BASE}/org/pending/reject',
                         json={'remark': 'missing tool input schema'})
    assert response.status_code == 200
    assert response.json() == {'status': 'success', 'publishStatus': 'rejected'}

    manage = http.get(f'{BASE}/manage').json()
    by_name = {c['name']: c['publishStatus'] for c in manage['agentCards']}
    assert by_name == {'pending': 'rejected', 'live': 'published'}
    assert manage['statusCounts'] == {'rejected': 1, 'published': 1}

    review = http.get(f'{BASE}/org/pending/review-status').json()
    assert review['status'] == 'rejected'
    assert review['last_transition']['from_status'] == 'registered'
    assert review['last_transition']['to_status'] == 'rejected'
    assert review['last_transition']['reason'] == 'missing tool input schema'


def test_manage_status_filter(client):
    http, core = client
    core.register_with_status(card(), initial_status='registered')
    core.register_with_status(card(name='live'), initial_status='published')
    core.update_status('pending', 'org', 'rejected', reason='bad schema', operator='tester')

    filtered = http.get(f'{BASE}/manage', params={'status': 'rejected'}).json()
    assert [c['name'] for c in filtered['agentCards']] == ['pending']
    assert filtered['statusCounts'] == {'rejected': 1, 'published': 1}

    published = http.get(f'{BASE}/manage', params={'status': 'published'}).json()
    assert [c['name'] for c in published['agentCards']] == ['live']

    bad = http.get(f'{BASE}/manage', params={'status': 'archived'})
    assert bad.status_code == 422


@pytest.mark.parametrize('layer', ['ServiceLayer', 'NetworkLayer', 'vendor-domain-layer', 'unknown'])
def test_manage_exposes_stored_layer_without_changing_public_cards(client, layer):
    http, core = client
    core.register_with_status(card(name='layer-agent'), initial_status='published', layer=layer)
    response = http.get(f'{BASE}/manage')
    assert response.status_code == 200
    managed = response.json()['agentCards'][0]
    assert managed['registration'] == {'layer': layer}
    assert managed['publishStatus'] == 'published'
    public = http.get(BASE, params={'name':'layer-agent', 'organization':'org'}).json()['agentCards'][0]
    assert 'registration' not in public
    assert 'layer' not in public


def test_approving_a_rejected_card_conflicts(client):
    http, core = client
    core.register_with_status(card(), initial_status='registered')
    http.post(f'{BASE}/org/pending/reject', json={'remark': 'bad'})

    response = http.post(f'{BASE}/org/pending/publish', json={'remark': 'attempt'})
    assert response.status_code == 409
    assert core.get_status('pending', 'org') == 'rejected'


def test_deprecate_removes_from_discovery_and_is_final(client):
    http, core = client
    core.register_with_status(card(name='live'), initial_status='published')

    response = http.post(f'{BASE}/org/live/deprecate', json={'remark': 'superseded by v2'})
    assert response.status_code == 200
    assert response.json()['publishStatus'] == 'deprecated'

    listing = http.get(f'{BASE}/manage', params={'status': 'deprecated'}).json()
    assert [c['name'] for c in listing['agentCards']] == ['live']

    # discovery list must not serve a deprecated card
    discovery = http.get(f'{BASE}', params={'name': 'live', 'organization': 'org'}).json()
    assert discovery.get('agentCards', []) == []

    review = http.get(f'{BASE}/org/live/review-status').json()
    assert review['status'] == 'deprecated'
    assert review['last_transition']['reason'] == 'superseded by v2'

    # deprecated is terminal: approving it back conflicts
    assert http.post(f'{BASE}/org/live/publish', json={'remark': 'undo'}).status_code == 409


def test_review_status_unknown_agent_is_404(client):
    http, _ = client
    assert http.get(f'{BASE}/org/ghost/review-status').status_code == 404
