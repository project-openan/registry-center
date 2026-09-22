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
Regression tests for the external review fixes on PR #50
(broadcast gate A1, vendor ownership single anchor A2, ban-lift audit
format C1, subscription parity C2, pull-audit op name C4).
"""

import time

import pytest
from fastapi.testclient import TestClient

import agent_registry.registry_instance as registry_instance
import agent_registry.integration.app as app_module
from tests.fakes.integration import (
    FakeRecord, FakeRegistry, StubAuthnHandler, make_agent_card,
    make_third_party_principal,
)


class _FakeStore:
    def __init__(self):
        self.items = {}

    def create(self, subscription):
        import uuid
        subscription.subscription_id = f"sub_{uuid.uuid4().hex[:8]}"
        self.items[subscription.subscription_id] = subscription
        return subscription

    def list_all(self):
        return list(self.items.values())

    def delete(self, subscription_id):
        return self.items.pop(subscription_id, None) is not None


class _FakeDispatcher:
    def __init__(self):
        self.added = []
        self.removed = []

    def add_subscription(self, sub):
        self.added.append(sub.subscription_id)

    def remove_subscription(self, sub_id):
        self.removed.append(sub_id)


class _FakeBroadcastService:
    def __init__(self, enabled=True):
        self.broadcast_enabled = enabled
        self.subscription_store = _FakeStore()
        self.dispatcher = _FakeDispatcher()
from agent_registry.integration.app import integration_app
from common.custom.custom_handle import BaseHandler, HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.util.authenticate_util import (
    AUTH_METHOD_TOKEN,
    CallerRole,
    CallerType,
    Principal,
)

_FakeRecord = FakeRecord
_FakeRegistry = FakeRegistry
_StubAuthnHandler = StubAuthnHandler

AGENT_CARD = {
    "name": "rv_agent",
    "provider": {"organization": "rv_org", "url": "https://example.com"},
    "description": "review-fix test agent",
    "version": "1.0.0",
    "skills": [],
}

CRED_COLLISION_CONF = """
credential.va.identity=vendor_a
credential.va.token_hash=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
credential.va.role=vendor_agent
credential.va.owner=vendor_b

credential.vb.identity=vendor_b
credential.vb.token_hash=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
credential.vb.role=vendor_agent
"""


@pytest.fixture
def client(monkeypatch):
    fake_registry = _FakeRegistry()
    stub = _StubAuthnHandler()
    monkeypatch.setattr(registry_instance, "_registry_instance", fake_registry)
    from limits import parse as parse_rate_limit
    monkeypatch.setattr(app_module, "_tp_prerate_item", parse_rate_limit("100000/second"))
    from agent_registry.signature.agent_card_signature_validator import AgentCardSignatureValidator
    monkeypatch.setattr(app_module, "get_signature_validator",
                        lambda: AgentCardSignatureValidator(None, signature_validation_enabled=False))
    monkeypatch.setattr(app_module, "get_registry_signer", lambda: None)
    HandlerRegistry._instances[InterfaceType.INTEGRATION_AUTHENTICATE.value] = stub
    yield TestClient(integration_app, raise_server_exceptions=False), stub, fake_registry
    HandlerRegistry._instances.pop(InterfaceType.INTEGRATION_AUTHENTICATE.value, None)


def _vendor(identity="vendor_a", owner=None):
    return Principal(client_ip="10.1.1.9", identity=identity,
                     caller_type=CallerType.INTEGRATION,
                     role=CallerRole.VENDOR_AGENT,
                     auth_method=AUTH_METHOD_TOKEN, owner=owner or identity)


def _headers():
    return {"X-App-Code": "vendor_a", "X-App-Secret": "x"}


def _auth_headers():
    return _headers()


def _principal(role, identity="svc"):
    return Principal(client_ip="10.1.1.9", identity=identity,
                     caller_type=CallerType.INTEGRATION, role=role,
                     auth_method=AUTH_METHOD_TOKEN, owner=identity)


class TestBroadcastGate:
    """A1: subscription routes honor the broadcast-enabled gate (503)."""

    @pytest.fixture(autouse=True)
    def broadcast(self, monkeypatch):
        self.service = _FakeBroadcastService(enabled=True)
        monkeypatch.setattr(app_module, "get_broadcast_service",
                            lambda: self.service)
        return self.service

    def test_disabled_create_returns_503(self, client):
        self.service.broadcast_enabled = False
        c, stub, reg = client
        stub.principal = _vendor()
        stub.principal.role = CallerRole.NMS_OSS
        resp = c.post("/integration/v1/subscriptions",
                      json={"callbackUrl": "https://a.b/c"}, headers=_headers())
        assert resp.status_code == 503
        assert "Change broadcast is disabled" in resp.json()["errors"]["error"][0]["errorMessage"]
        assert self.service.subscription_store.items == {}  # store untouched

    def test_disabled_list_returns_503(self, client):
        self.service.broadcast_enabled = False
        c, stub, reg = client
        stub.principal = _vendor("vendor_a")
        stub.principal.role = CallerRole.NMS_OSS
        assert c.get("/integration/v1/subscriptions", headers=_headers()).status_code == 503

    def test_disabled_delete_returns_503(self, client):
        self.service.broadcast_enabled = False
        c, stub, reg = client
        stub.principal = _vendor("vendor_a")
        stub.principal.role = CallerRole.NMS_OSS
        assert c.delete("/integration/v1/subscriptions/sub_x", headers=_headers()).status_code == 503

    def test_enabled_create_wires_dispatcher(self, client):
        c, stub, reg = client
        stub.principal = _vendor(CallerRole.NMS_OSS and "vendor_a")
        stub.principal.role = CallerRole.NMS_OSS
        resp = c.post("/integration/v1/subscriptions",
                      json={"callbackUrl": "https://a.b/c"}, headers=_auth_headers())
        assert resp.status_code == 201
        assert len(self.service.dispatcher.added) == 1


class TestVendorOwnershipIdentityAnchor:
    """A2: identity is the single ownership anchor; owner is metadata only."""

    def test_owner_collision_cannot_update_foreign_card(self, client):
        c, stub, reg = client
        reg._records[("victim", "rv_org")] = _FakeRecord(make_agent_card("victim", "rv_org"), owner="vendor_b")
        stub.principal = _vendor(identity="vendor_a", owner="vendor_b")
        resp = c.put("/integration/v1/agent-cards/rv_org/victim",
                     json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 403

    def test_owner_collision_cannot_delete_foreign_card(self, client):
        c, stub, reg = client
        reg._records[("victim", "rv_org")] = _FakeRecord(make_agent_card("victim", "rv_org"), owner="vendor_b")
        stub.principal = _vendor(identity="vendor_a", owner="vendor_b")
        resp = c.delete("/integration/v1/agent-cards/rv_org/victim", headers=_auth_headers())
        assert resp.status_code == 403

    def test_identity_match_allowed(self, client):
        c, stub, reg = client
        reg._records[("own", "rv_org")] = _FakeRecord(make_agent_card("own", "rv_org"), owner="vendor_a")
        stub.principal = _vendor(identity="vendor_a", owner="vendor_a")
        resp = c.put("/integration/v1/agent-cards/rv_org/own",
                     json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 200

    def test_ownerless_card_still_operable(self, client):
        c, stub, reg = client
        reg._records[("public", "rv_org")] = _FakeRecord(AGENT_CARD, owner=None)
        stub.principal = _vendor(identity="vendor_a")
        resp = c.put("/integration/v1/agent-cards/rv_org/public",
                     json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 200

    def test_registration_binds_identity_not_owner_field(self, client):
        c, stub, reg = client
        stub.principal = _vendor(identity="vendor_a", owner="vendor_b")
        resp = c.post("/integration/v1/agent-cards",
                      json={"agentCards": [AGENT_CARD]}, headers=_auth_headers())
        assert resp.status_code == 201
        assert reg._records[("rv_agent", "rv_org")].owner == "vendor_a"


class TestCredentialOwnerCollisionWarning:
    def test_collision_warns(self, tmp_path, loguru_caplog=None):
        from loguru import logger
        from agent_registry.integration.credentials import load_credentials
        records = []
        handler_id = logger.add(records.append, format="{message}")
        try:
            conf = tmp_path / "c.conf"
            conf.write_text(CRED_COLLISION_CONF, encoding="utf-8")
            creds, _ = load_credentials(str(conf))
        finally:
            logger.remove(handler_id)
        assert set(creds.keys()) == {"va", "vb"}
        assert any("matches another" in r for r in records)

    def test_no_warning_without_collision(self, tmp_path):
        from loguru import logger
        from agent_registry.integration.credentials import load_credentials
        records = []
        handler_id = logger.add(records.append, format="{message}")
        try:
            conf = tmp_path / "c.conf"
            conf.write_text("credential.x.identity=x\n"
                            "credential.x.token_hash=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\n"
                            "credential.x.role=nms_oss\n", encoding="utf-8")
            load_credentials(str(conf))
        finally:
            logger.remove(handler_id)
        assert not any("matches another" in r for r in records)


class TestBanLiftAuditUnified:
    def test_lift_writes_snake_keys_via_audit_writer(self, monkeypatch):
        import agent_registry.integration.app as tp_app
        written = []
        from common.log import audit_logger as al_module
        monkeypatch.setattr(al_module.audit_logger, "audit",
                            lambda entry: written.append(entry))
        monkeypatch.setattr(tp_app, "_ban_tracker", None)
        tracker = tp_app.get_ban_tracker()
        key = "cred:vendor_a"
        tracker._banned_until[key] = tracker._clock() - 1  # cooldown elapsed
        assert tracker.is_banned(key) is False  # lift fires the audit
        assert len(written) == 1
        entry = written[0]
        # writer INPUT format: snake keys, normalized by AuditLogger.audit
        assert entry["operation_name"] == "Authentication Ban"
        assert entry["details"]["bannedKey"] == key


class TestSubscriptionBehaviorParity:
    def test_delete_removes_from_dispatcher(self, client):
        c, stub, reg = client
        service = _FakeBroadcastService(enabled=True)
        monkey_ref = service
        import agent_registry.integration.app as tp_app
        original = tp_app.get_broadcast_service
        created = service.subscription_store.create(
            _make_sub("sub_del"))
        service.dispatcher.add_subscription(created)
        tp_app.get_broadcast_service = lambda: service
        stub.principal = _principal(CallerRole.NMS_OSS, identity="nms")
        resp = c.delete("/integration/v1/subscriptions/" + created.subscription_id,
                        headers=_headers())
        assert resp.status_code == 200
        assert service.dispatcher.removed == [created.subscription_id]
        tp_app.get_broadcast_service = original

    def test_invalid_event_types_returns_422(self, client, monkeypatch):
        service = _FakeBroadcastService(enabled=True)
        monkeypatch.setattr(app_module, "get_broadcast_service", lambda: service)
        c, stub, reg = client
        stub.principal = _vendor(CallerRole.NMS_OSS and "vendor_a")
        stub.principal.role = CallerRole.NMS_OSS
        resp = c.post("/integration/v1/subscriptions",
                      json={"callbackUrl": "https://a.b/c",
                            "eventTypes": ["not.a.real.event"]}, headers=_auth_headers())
        assert resp.status_code == 422

    def test_caller_secret_passthrough(self, client, monkeypatch):
        service = _FakeBroadcastService(enabled=True)
        monkeypatch.setattr(app_module, "get_broadcast_service", lambda: service)
        c, stub, reg = client
        stub.principal = _vendor(CallerRole.NMS_OSS and "vendor_a")
        stub.principal.role = CallerRole.NMS_OSS
        resp = c.post("/integration/v1/subscriptions",
                      json={"callbackUrl": "https://a.b/c", "secret": "mine"},
                      headers=_auth_headers())
        assert resp.status_code == 201
        sub_id = resp.json()["subscription_id"]
        assert service.subscription_store.items[sub_id].secret == "mine"
        assert resp.json()["secret"] == "mine"  # echoed for callback signing


def _make_sub(sub_id):
    from agent_registry.broadcast.subscriptions import Subscription
    return Subscription(subscription_id=sub_id, callback_url="https://a.b/c",
                        event_types=None, organizations=None, tags=None)
