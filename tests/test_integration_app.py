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

"""
Integration access plane integration tests (tasks 2.1/2.2/3.1/3.2).

Exercises the integration FastAPI app end to end with a stub authn handler
(registered through the real INTEGRATION_AUTHENTICATE slot) and an
in-memory fake registry. No database or LLM required.
"""

import pytest
from fastapi.testclient import TestClient

import agent_registry.registry_instance as registry_instance
import agent_registry.integration.app as app_module
from tests.fakes.integration import (
    FakeRecord, FakeRegistry, StubAuthnHandler, make_agent_card,
    make_third_party_principal,
)
from agent_registry.integration.app import integration_app
from common.custom.custom_handle import BaseHandler, HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.util.authenticate_util import (
    AuthFailureReason,
    AuthenticationError,
    CallerRole,
    CallerType,
    Principal,
)

_FakeRecord = FakeRecord
_FakeRegistry = FakeRegistry
_StubAuthnHandler = StubAuthnHandler


AGENT_CARD = {
    "name": "tp_agent",
    "provider": {"organization": "tp_org", "url": "https://example.com"},
    "description": "integration test agent",
    "version": "1.0.0",
    "skills": [],
}


@pytest.fixture
def client(monkeypatch):
    fake_registry = _FakeRegistry()
    stub = _StubAuthnHandler()
    monkeypatch.setattr(registry_instance, "_registry_instance", fake_registry)
    from limits import parse as parse_rate_limit
    monkeypatch.setattr(app_module, "_tp_prerate_item", parse_rate_limit("100000/second"))
    # Hermetic: do not depend on the ambient server.conf. The committed conf
    # enables JWS signature validation; tests inject a disabled validator and
    # no registry signer so cards without signatures exercise the role logic.
    from agent_registry.signature.agent_card_signature_validator import AgentCardSignatureValidator
    monkeypatch.setattr(app_module, "get_signature_validator",
                        lambda: AgentCardSignatureValidator(None, signature_validation_enabled=False))
    monkeypatch.setattr(app_module, "get_registry_signer", lambda: None)
    HandlerRegistry._instances[InterfaceType.INTEGRATION_AUTHENTICATE.value] = stub
    yield TestClient(integration_app, raise_server_exceptions=False), stub, fake_registry
    HandlerRegistry._instances.pop(InterfaceType.INTEGRATION_AUTHENTICATE.value, None)


def _principal(role, identity="svc_app", owner=None):
    from common.util.authenticate_util import AUTH_METHOD_TOKEN
    return Principal(client_ip="10.1.1.9", identity=identity,
                     caller_type=CallerType.INTEGRATION, role=role,
                     auth_method=AUTH_METHOD_TOKEN, owner=owner or identity)


def _auth_headers():
    return {"X-App-Code": "svc_app", "X-App-Secret": "x"}


def _req(c, method, url, body=None):
    kwargs = {"headers": _auth_headers()}
    if body is not None:
        kwargs["json"] = body
    return getattr(c, method)(url, **kwargs)


class TestRoleEndpointMatrix:
    """Role × endpoint authorization matrix (task 3.1)."""

    WRITE_OPERATIONS = [
        ("post", "/integration/v1/agent-cards",
         {"agentCards": [AGENT_CARD]}),
        ("put", f"/integration/v1/agent-cards/tp_org/tp_agent",
         {"agentCards": [AGENT_CARD]}),
        ("delete", "/integration/v1/agent-cards/tp_org/tp_agent", None),
    ]

    READ_OPERATIONS = [
        ("get", "/integration/v1/agent-cards", None),
        ("get", "/integration/v1/agent-cards/tp_org/tp_agent", None),
    ]

    def test_nms_oss_can_write_and_read(self, client):
        c, stub, reg = client
        stub.principal = _principal(CallerRole.NMS_OSS)
        for method, url, body in self.WRITE_OPERATIONS + self.READ_OPERATIONS:
            resp = _req(c, method, url, body)
            assert resp.status_code in (200, 201), f"{method} {url} -> {resp.status_code}"

    def test_partner_service_read_only(self, client):
        c, stub, reg = client
        stub.principal = _principal(CallerRole.PARTNER_SERVICE)
        for method, url, body in self.READ_OPERATIONS:
            resp = _req(c, method, url, body)
            assert resp.status_code == 200
        for method, url, body in self.WRITE_OPERATIONS:
            resp = _req(c, method, url, body)
            assert resp.status_code == 403

    def test_analytics_tool_read_only_no_subscribe(self, client):
        c, stub, reg = client
        stub.principal = _principal(CallerRole.ANALYTICS_TOOL)
        for method, url, body in self.READ_OPERATIONS:
            resp = _req(c, method, url, body)
            assert resp.status_code == 200
        for method, url, body in self.WRITE_OPERATIONS:
            resp = _req(c, method, url, body)
            assert resp.status_code == 403
        resp = c.post("/integration/v1/subscriptions", json={"callbackUrl": "https://a.b/c"},
                      headers=_auth_headers())
        assert resp.status_code == 403

    def test_vendor_agent_write_and_read(self, client):
        c, stub, reg = client
        stub.principal = _principal(CallerRole.VENDOR_AGENT)
        for method, url, body in self.WRITE_OPERATIONS + self.READ_OPERATIONS:
            resp = _req(c, method, url, body)
            assert resp.status_code in (200, 201), f"{method} {url} -> {resp.status_code}"


class TestVendorOwnerBinding:
    """Vendor agents may only manage their own cards (task 3.2)."""

    def test_vendor_cannot_update_foreign_card(self, client):
        c, stub, reg = client
        reg._records[("foreign", "org")] = _FakeRecord(AGENT_CARD, owner="someone_else")
        stub.principal = _principal(CallerRole.VENDOR_AGENT)
        resp = c.put("/integration/v1/agent-cards/org/foreign",
                     json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 403

    def test_vendor_cannot_delete_foreign_card(self, client):
        c, stub, reg = client
        reg._records[("foreign", "org")] = _FakeRecord(AGENT_CARD, owner="someone_else")
        stub.principal = _principal(CallerRole.VENDOR_AGENT)
        resp = c.delete("/integration/v1/agent-cards/org/foreign", headers=_auth_headers())
        assert resp.status_code == 403

    def test_vendor_can_update_own_card(self, client):
        c, stub, reg = client
        reg._records[("mine", "tp_org")] = _FakeRecord(make_agent_card("mine", "tp_org"), owner="svc_app")
        stub.principal = _principal(CallerRole.VENDOR_AGENT)
        resp = c.put("/integration/v1/agent-cards/tp_org/mine",
                     json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 200

    def test_semantic_query_topn_validation(self, client):
        """topN must be an integer within bounds (422 otherwise, no 500)."""
        c, stub, reg = client
        stub.principal = _principal(CallerRole.PARTNER_SERVICE)
        resp = c.post("/integration/v1/agent-cards/semantic-query",
                      json={"task": "x", "topN": None}, headers=_auth_headers())
        assert resp.status_code == 422
        resp = c.post("/integration/v1/agent-cards/semantic-query",
                      json={"task": "x", "topN": "abc"}, headers=_auth_headers())
        assert resp.status_code == 422

    def test_nms_can_update_foreign_card(self, client):
        c, stub, reg = client
        reg._records[("foreign", "org")] = _FakeRecord(AGENT_CARD, owner="someone_else")
        stub.principal = _principal(CallerRole.NMS_OSS)
        resp = c.put("/integration/v1/agent-cards/org/foreign",
                     json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 200


class TestRegistrationOwnership:
    def test_registered_card_owner_bound_to_credential(self, client):
        c, stub, reg = client
        stub.principal = _principal(CallerRole.VENDOR_AGENT, identity="vendor_alpha")
        resp = c.post("/integration/v1/agent-cards",
                      json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 201
        record = reg._records[("tp_agent", "tp_org")]
        assert record.owner == "vendor_alpha"


class TestAuthFailures:
    def test_missing_credentials_returns_401(self, client):
        c, stub, reg = client
        stub.error = AuthFailureReason.MISSING_CREDENTIALS
        resp = c.get("/integration/v1/agent-cards")
        assert resp.status_code == 401

    def test_bad_secret_returns_401(self, client):
        c, stub, reg = client
        stub.error = AuthFailureReason.INVALID_TOKEN
        resp = c.get("/integration/v1/agent-cards", headers=_auth_headers())
        assert resp.status_code == 401
        body = resp.json()
        assert body["errors"]["error"][0]["errorMessage"] == "Authentication failed"


class TestBanIntegration:
    """Repeated auth failures temporarily ban the credential (task 5.1)."""

    @pytest.fixture(autouse=True)
    def reset_ban_tracker(self, monkeypatch):
        import agent_registry.integration.app as tp_app
        monkeypatch.setattr(tp_app, "_ban_tracker", None)
        monkeypatch.setattr(tp_app, "_tp_rate_item", None)

    def test_repeated_failures_trigger_ban(self, client):
        from limits import parse as parse_rate_limit
        import agent_registry.integration.app as tp_app
        c, stub, reg = client
        tp_app._ban_tracker = tp_app.BanTracker(threshold=3, cooldown_seconds=60)
        tp_app._tp_rate_item = parse_rate_limit("1000/second")
        stub.error = AuthFailureReason.INVALID_TOKEN
        for _ in range(3):
            resp = c.get("/integration/v1/agent-cards", headers=_auth_headers())
            assert resp.status_code == 401
        # even with valid credentials the ban holds
        stub.error = None
        stub.principal = _principal(CallerRole.ANALYTICS_TOOL)
        resp = c.get("/integration/v1/agent-cards", headers=_auth_headers())
        assert resp.status_code == 401
        assert "banned" in resp.json()["errors"]["error"][0]["errorMessage"].lower()

    def test_success_resets_failure_count(self, client):
        """Failures under a KNOWN appcode clear on successful auth (task 5.1)."""
        from limits import parse as parse_rate_limit
        import agent_registry.integration.app as tp_app
        c, stub, reg = client
        tp_app._ban_tracker = tp_app.BanTracker(threshold=3, cooldown_seconds=60)
        tp_app._tp_rate_item = parse_rate_limit("1000/second")
        stub.credentials = {"svc_app": object()}  # claimed appcode is known
        stub.error = AuthFailureReason.INVALID_TOKEN
        c.get("/integration/v1/agent-cards", headers=_auth_headers())
        c.get("/integration/v1/agent-cards", headers=_auth_headers())
        stub.error = None
        stub.principal = _principal(CallerRole.NMS_OSS)
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
        # one more failure after a success must not ban (counter was cleared)
        stub.error = AuthFailureReason.INVALID_TOKEN
        resp = c.get("/integration/v1/agent-cards", headers=_auth_headers())
        assert resp.status_code == 401
        assert "banned" not in resp.json()["errors"]["error"][0]["errorMessage"].lower()

    def test_rotating_unknown_appcode_cannot_escape_ban(self, client):
        """Regression: rotating the client-chosen X-App-Code header must not
        give a fresh ban bucket per request — failures land on the IP bucket."""
        from limits import parse as parse_rate_limit
        import agent_registry.integration.app as tp_app
        c, stub, reg = client
        tp_app._ban_tracker = tp_app.BanTracker(threshold=3, cooldown_seconds=60)
        tp_app._tp_rate_item = parse_rate_limit("1000/second")
        tp_app._tp_prerate_item = parse_rate_limit("1000/second")
        stub.error = AuthFailureReason.INVALID_TOKEN
        for i in range(3):  # every attempt uses a different appcode
            resp = c.get("/integration/v1/agent-cards",
                         headers={"X-App-Code": f"rotated_{i}", "X-App-Secret": "x"})
            assert resp.status_code == 401
        resp = c.get("/integration/v1/agent-cards", headers=_auth_headers())
        assert resp.status_code == 401
        assert "banned" in resp.json()["errors"]["error"][0]["errorMessage"].lower()

    def test_pre_auth_rate_limit_throttles_guessing(self, client, monkeypatch):
        """Pre-auth per-IP limiter returns 429 before credentials are checked."""
        from limits import parse as parse_rate_limit
        from limits import storage as limit_storage, strategies as limit_strategies
        import agent_registry.integration.app as tp_app
        c, stub, reg = client
        tp_app._tp_prerate_item = parse_rate_limit("2/second")
        monkeypatch.setattr(tp_app, "_tp_prerate_limiter",
                            limit_strategies.MovingWindowRateLimiter(limit_storage.MemoryStorage()))
        stub.principal = _principal(CallerRole.ANALYTICS_TOOL)
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 429

    def test_handler_returning_none_is_auth_failure_not_500(self, client):
        """A misbehaving custom authn handler returning None must yield 401."""
        c, stub, reg = client
        stub.principal = None
        resp = c.get("/integration/v1/agent-cards", headers=_auth_headers())
        assert resp.status_code == 401

    def test_auth_failure_operation_attribution(self, client, monkeypatch):
        """Auth failures are audited with the ACTUAL operation, not always Register."""
        import agent_registry.integration.audit as audit_module
        entries = []

        class _Rec:
            async def handle(self, entry):
                entries.append(entry)

        monkeypatch.setattr(audit_module, "_audit_handle", _Rec())
        c, stub, reg = client
        stub.error = AuthFailureReason.MISSING_CREDENTIALS
        c.get("/integration/v1/agent-cards", headers=_auth_headers())
        assert entries[0]["operation_name"] == "Query Agent"


class TestPerCredentialRateLimit:
    """Rate limiting is per credential identity (task 5.2)."""

    @pytest.fixture(autouse=True)
    def reset_limit_state(self, monkeypatch):
        import agent_registry.integration.app as tp_app
        from limits import storage as limit_storage, strategies as limit_strategies
        monkeypatch.setattr(tp_app, "_tp_limiter",
                            limit_strategies.MovingWindowRateLimiter(limit_storage.MemoryStorage()))
        monkeypatch.setattr(tp_app, "_tp_prerate_limiter",
                            limit_strategies.MovingWindowRateLimiter(limit_storage.MemoryStorage()))
        monkeypatch.setattr(tp_app, "_ban_tracker", None)
        monkeypatch.setattr(tp_app, "_tp_rate_item", None)
        monkeypatch.setattr(tp_app, "_tp_prerate_item", None)

    def test_exceeding_limit_returns_429(self, client, monkeypatch):
        from limits import parse as parse_rate_limit
        import agent_registry.integration.app as tp_app
        c, stub, reg = client
        tp_app._tp_rate_item = parse_rate_limit("2/second")
        stub.principal = _principal(CallerRole.ANALYTICS_TOOL)
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 429

    def test_different_credentials_isolated(self, client, monkeypatch):
        from limits import parse as parse_rate_limit
        import agent_registry.integration.app as tp_app
        c, stub, reg = client
        tp_app._tp_rate_item = parse_rate_limit("2/second")
        stub.principal = _principal(CallerRole.ANALYTICS_TOOL, identity="app_one")
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 429
        # a different credential has its own budget
        stub.principal = _principal(CallerRole.ANALYTICS_TOOL, identity="app_two")
        assert c.get("/integration/v1/agent-cards", headers=_auth_headers()).status_code == 200
