# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Knowledge Graph API security regression tests.

Covers the endpoint guard (per-IP rate limit + AUTHENTICATE slot) and the
Cypher identifier validation (injection guard) added after the test-
adequacy review. No live Neo4j required: injection rejections happen
before any driver interaction.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agent_registry.knowledge_graph_api import router as kg_router_module
from agent_registry.knowledge_graph_api.router import knowledge_graph_router
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType


@pytest.fixture
def client(monkeypatch):
    from limits import parse as parse_rate_limit
    from limits import storage as limit_storage, strategies as limit_strategies
    monkeypatch.setattr(kg_router_module, "_kg_rate_item",
                        parse_rate_limit("1000/second"))
    monkeypatch.setattr(kg_router_module, "_kg_strategy",
                        limit_strategies.MovingWindowRateLimiter(limit_storage.MemoryStorage()))

    app = FastAPI()
    app.include_router(knowledge_graph_router)
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    HandlerRegistry._instances.pop(InterfaceType.AUTHENTICATE.value, None)


class _EmptyFakeDriver:
    """Driver stand-in: sessions run queries that return no records and a
    zero count, enough for list/read endpoints without a live Neo4j."""

    class _FakeResult:
        def __iter__(self):
            return iter([])

        def single(self):
            return {"count": 0}

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def run(self, query, **params):
            return _EmptyFakeDriver._FakeResult()

    def session(self):
        return self._FakeSession()


def _set_auth_error(monkeypatch, error):
    """Mount an AUTHENTICATE slot handler that raises (simulates denied caller)."""

    class _DenyHandler:
        async def handle(self, client_ip, request):
            raise error

    monkeypatch.setitem(HandlerRegistry._instances,
                        InterfaceType.AUTHENTICATE.value, _DenyHandler())


class TestEndpointGuard:
    def test_rate_limit_returns_429(self, client, monkeypatch):
        from limits import parse as parse_rate_limit
        from limits import storage as limit_storage, strategies as limit_strategies
        monkeypatch.setattr(kg_router_module, "_kg_rate_item", parse_rate_limit("1/second"))
        monkeypatch.setattr(kg_router_module, "_kg_strategy",
                            limit_strategies.MovingWindowRateLimiter(limit_storage.MemoryStorage()))
        monkeypatch.setattr(kg_router_module, "get_neo4j_driver", lambda: _EmptyFakeDriver())
        first = client.get("/rest/v1/registry-center/knowledge-graph/nodes")
        assert first.status_code == 200
        second = client.get("/rest/v1/registry-center/knowledge-graph/nodes")
        assert second.status_code == 429

    def test_auth_slot_failure_returns_401(self, client, monkeypatch):
        _set_auth_error(monkeypatch, HTTPException(status_code=401, detail="denied"))
        resp = client.get("/rest/v1/registry-center/knowledge-graph/nodes")
        assert resp.status_code == 401

    def test_guard_applies_to_all_routes(self, client, monkeypatch):
        """A denied caller is rejected on every endpoint family, not just one."""
        _set_auth_error(monkeypatch, HTTPException(status_code=401, detail="denied"))
        paths = [
            ("get", "/rest/v1/registry-center/knowledge-graph/nodes"),
            ("post", "/rest/v1/registry-center/knowledge-graph/nodes"),
            ("get", "/rest/v1/registry-center/knowledge-graph/relationships"),
            ("get", "/rest/v1/registry-center/knowledge-graph/graph"),
            ("get", "/rest/v1/registry-center/knowledge-graph/export"),
        ]
        for method, path in paths:
            kwargs = {"json": {}} if method in ("post", "put") else {}
            resp = getattr(client, method)(path, **kwargs)
            assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


class TestCypherInjectionGuard:
    """User-controlled labels/types/property keys must match the strict
    identifier grammar before touching a query string."""

    def test_list_nodes_rejects_label_injection(self, client):
        resp = client.get("/rest/v1/registry-center/knowledge-graph/nodes",
                          params={"label": "Person) RETURN n DETACH DELETE n //"})
        assert resp.status_code == 422

    def test_create_node_rejects_label_injection(self, client):
        resp = client.post("/rest/v1/registry-center/knowledge-graph/nodes",
                           json={"labels": ["Person], malicious:Label"],
                                 "properties": {"a": 1}})
        assert resp.status_code == 422

    def test_create_node_accepts_valid_labels(self, client, monkeypatch):
        """A valid label passes validation and reaches the (mocked) driver."""
        class _FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def run(self, query, **params):
                class _Result:
                    def single(self):
                        return {"id": "4:x:1", "labels": ["Person"], "properties": params["properties"]}

                return _Result()

        class _FakeDriver:
            def session(self):
                return _FakeSession()

        monkeypatch.setattr(kg_router_module, "get_neo4j_driver", lambda: _FakeDriver())
        resp = client.post("/rest/v1/registry-center/knowledge-graph/nodes",
                           json={"labels": ["Person"], "properties": {"name": "x"}})
        assert resp.status_code == 201

    def test_create_relationship_rejects_backtick_injection(self, client):
        """Backtick quoting alone is not enough: an embedded backtick must be
        rejected by the identifier grammar."""
        resp = client.post("/rest/v1/registry-center/knowledge-graph/relationships",
                           json={"type": "REL`] DETACH DELETE n //",
                                 "startNodeId": "4:x:1", "endNodeId": "4:x:2"})
        assert resp.status_code == 422

    def test_export_rejects_property_key_injection(self, client):
        resp = client.get("/rest/v1/registry-center/knowledge-graph/export",
                          params={"filter": "property=secret`:1"})
        assert resp.status_code == 422

    def test_export_rejects_label_injection(self, client):
        resp = client.get("/rest/v1/registry-center/knowledge-graph/export",
                          params={"filter": "label=`Person`) RETURN n DETACH DELETE n //"})
        assert resp.status_code == 422

    def test_validate_identifier_rejects_non_string(self):
        from agent_registry.knowledge_graph_api.router import _validate_identifier
        with pytest.raises(HTTPException):
            _validate_identifier(None, "label")
        with pytest.raises(HTTPException):
            _validate_identifier("", "label")
        with pytest.raises(HTTPException):
            _validate_identifier("has space", "label")
        with pytest.raises(HTTPException):
            _validate_identifier("9starts_with_digit", "label")
