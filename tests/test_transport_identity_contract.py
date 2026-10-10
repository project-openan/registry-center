# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Real main-port HTTP/HTTPS requests, standard Bearer identity and JWS."""
import asyncio
import hashlib
import hmac
import ipaddress
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
import uvicorn
from a2a.types import AgentCard
from a2a.utils.signing import create_signature_verifier
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException, Request

from agent_registry.agent_registry.agent_card_signer import AgentCardSigner
from agent_registry.identity import resolve_caller_identity
from agent_registry.main_auth import MainTokenPolicy
from agent_registry.signature.public_address import registry_jku_url
from common.util.authenticate_util import CallerRole, Principal


def _materials(tmp_path, prefix="test"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]), critical=False).sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / (prefix + ".cer"), tmp_path / (prefix + ".pem")
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    password = tmp_path / (prefix + ".pwd")
    password.write_text("")
    return cert_path, key_path, password, key


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_real_main_port_bearer_discovery_and_signed_card(protocol, tmp_path, monkeypatch):
    from agent_registry import server, main_auth
    from agent_registry.core import RegistryCore
    from agent_registry.integration import app as integration
    from agent_registry.integration.authn import ThirdPartyAuthnHandler
    from agent_registry.integration.ban import BanTracker
    from common.util import app_config
    from limits.storage import MemoryStorage
    from limits.strategies import MovingWindowRateLimiter

    token, secret = "test-only-registry-access-token", "test-only-hmac-secret"
    digest = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    credentials = tmp_path / "credentials.conf"
    credentials.write_text(
        f"credential.vendor.identity=verified-vendor\ncredential.vendor.role=vendor_agent\n"
        f"credential.vendor.owner=another-owner\ncredential.vendor.token_hash={digest}\n")
    config = {"owner.identity.mode": "token", "integration.auth.mode": "static_bearer",
              "integration.auth.fingerprint_key": "test-only-fingerprint-key",
              "integration.auth.static.hmac_key": secret,
              "integration.credential.file": str(credentials)}
    monkeypatch.setattr(server, "config", config)
    monkeypatch.setattr(app_config, "get_conf", lambda: config)
    monkeypatch.setattr(integration, "audit_integration_failure", AsyncMock())
    monkeypatch.setattr(integration, "get_ban_tracker", lambda: BanTracker(100, 300))
    monkeypatch.setattr(integration, "_tp_prerate_limiter", MovingWindowRateLimiter(MemoryStorage()))
    monkeypatch.setattr(integration, "_tp_limiter", MovingWindowRateLimiter(MemoryStorage()))
    policy = MainTokenPolicy()
    policy.handler = ThirdPartyAuthnHandler(config=config)
    monkeypatch.setattr(main_auth, "main_token_policy", policy)
    registry = RegistryCore(use_vectordb=False, persistence_mode="file",
                            persistence_file=str(tmp_path / "cards.json"),
                            persistence_metadata_file=str(tmp_path / "metadata.json"))
    registry.storage.tags_file = str(tmp_path / "tags.json")
    from common.custom import custom_handle
    monkeypatch.setattr(custom_handle, "get_registry", lambda: registry)
    registry_dependency = server.get_registry
    server.app.dependency_overrides[registry_dependency] = lambda: registry
    card = AgentCard(name="diagnostics", provider={"organization": "test-org"})
    monkeypatch.setattr(server, "get_registry", lambda: registry)
    cert, key, pwd, private_key = _materials(tmp_path)
    signer = AgentCardSigner(str(key), str(cert), str(pwd))
    assert registry.register(signer.sign_agent_card(card))
    monkeypatch.setattr(server, "_registry_signer", signer)
    monkeypatch.setattr(server, "get_registry_signer", lambda: signer)
    monkeypatch.setattr(server, "_is_hidden_unhealthy", lambda *args: False)
    options, verify = {}, True
    if protocol == "https":
        options = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        verify = ssl.create_default_context(cafile=str(cert))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    runner = uvicorn.Server(uvicorn.Config(server.app, lifespan="off", log_level="error", **options))
    thread = threading.Thread(target=runner.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not runner.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.started
        with httpx.Client(base_url=f"{protocol}://127.0.0.1:{listener.getsockname()[1]}",
                          verify=verify, trust_env=False, timeout=5) as client:
            path = "/rest/v1/registry-center/agent-cards"
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"X-SSL-Client-DN": "CN=admin"}).status_code == 401
            headers = {"Authorization": "Bearer " + token}
            response = client.get(path + "/test-org/diagnostics", headers=headers)
            assert response.status_code == 200, response.text
            payload = response.json()
            raw = payload["agentCards"][0]
            from google.protobuf.json_format import ParseDict
            signed = ParseDict(raw, AgentCard())
            create_signature_verifier(lambda kid, jku: private_key.public_key(), ["RS256"])(signed)
            assert client.get(path, headers=headers).status_code == 200
            from types import SimpleNamespace
            monkeypatch.setattr(server, "get_health_service", lambda: SimpleNamespace(enabled=False))
            assert client.post(path + "/test-org/diagnostics/heartbeat", headers=headers).status_code == 200
            # JWKS availability follows signing, not backend HTTP/HTTPS.
            monkeypatch.setitem(config, "registry.sign.enabled", "true")
            monkeypatch.setattr(server, "jwk_provider", server.JWKProvider(cert_path=str(cert)))
            assert client.get("/rest/v1/registry-center/keys").status_code == 200
            assert client.get("/health").status_code == 200
            # A discovery credential must not reach administrative metadata.
            assert client.get("/rest/v1/registry-center/registrations", headers=headers).status_code == 403
    finally:
        runner.should_exit = True
        thread.join(10)
        listener.close()
        registry.storage.close()
        server.app.dependency_overrides.pop(registry_dependency, None)
        asyncio.run(policy.close())
        assert not thread.is_alive()


def test_token_identity_uses_verified_identity_not_attribution():
    principal = Principal("127.0.0.1", identity="verified-vendor", owner="victim",
                          role=CallerRole.VENDOR_AGENT)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                       "registry_principal": principal})
    identity = resolve_caller_identity(request, {"owner.identity.mode": "token"})
    assert identity.verified and identity.owner == "verified-vendor"


def test_vendor_heartbeat_route_is_allowed_but_management_is_not():
    principal = Principal("127.0.0.1", identity="vendor", role=CallerRole.VENDOR_AGENT)
    base = "/rest/v1/registry-center/agent-cards/org/agent/"
    request = Request({"type": "http", "method": "POST", "path": base + "heartbeat", "headers": []})
    MainTokenPolicy._authorize(request, principal)
    for path in (base + "publish", base + "heartbeat/extra",
                 "/rest/v1/registry-center/agents/heartbeat"):
        request = Request({"type": "http", "method": "POST", "path": path, "headers": []})
        with pytest.raises(HTTPException) as error:
            MainTokenPolicy._authorize(request, principal)
        assert error.value.status_code == 403


@pytest.mark.parametrize("config,expected", [
    ({"ip": "0.0.0.0", "enable_https": "true"}, ""),
    ({"registry.public.base_url": "http://public.example"}, ""),
    ({"registry.public.base_url": "https://public.example/registry"},
     "https://public.example/registry/rest/v1/registry-center/keys"),
])
def test_public_jwks_address_is_not_bind_protocol(config, expected):
    assert registry_jku_url(config) == expected


@pytest.mark.parametrize("url", ["https://host:broken", "https://user:secret@host", "http://host/keys"])
def test_invalid_explicit_jwks_address_rejected(url):
    with pytest.raises(ValueError):
        registry_jku_url({"registry.sign.jwks_url": url})


def test_signer_plain_key_empty_password_and_mismatch(tmp_path):
    cert, key, pwd, private_key = _materials(tmp_path)
    signer = AgentCardSigner(str(key), str(cert), str(pwd))
    card = signer.sign_agent_card(AgentCard(name="signed"))
    signer.sign_agent_card(card)  # Existing signatures must not break canonicalization.
    create_signature_verifier(lambda kid, jku: private_key.public_key(), ["RS256"])(card)
    other_cert, _, _, _ = _materials(tmp_path, "other")
    with pytest.raises(ValueError, match="does not match"):
        AgentCardSigner(str(key), str(other_cert), str(pwd))


def test_integration_http_rejects_mtls_policy_before_tls_reads(monkeypatch):
    from agent_registry.integration import listener
    from types import SimpleNamespace
    access = listener.ThirdPartyAccessServer(
        {"integration.enabled": "true", "integration.enable_https": "false",
         "integration.auth.mode": "mtls"}, SimpleNamespace())
    with pytest.raises(ValueError, match="requires"):
        access.start()

@pytest.mark.parametrize("protocol", ["http", "https"])
def test_actual_integration_listener_retains_token_auth(protocol, tmp_path, monkeypatch):
    from agent_registry.integration import listener, app as integration
    from agent_registry.integration.ban import BanTracker
    from agent_registry.core import RegistryCore
    from common.custom import custom_handle
    from common.util.conf_obj import ConfObj
    from types import SimpleNamespace
    from common.custom.interface_type import InterfaceType
    token, secret = "integration-test-token", "integration-test-hmac"
    digest = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    credentials = tmp_path / "integration.conf"
    credentials.write_text(
        f"credential.reader.identity=verified-reader\ncredential.reader.role=partner_service\n"
        f"credential.reader.token_hash={digest}\n")
    conf = {"integration.enabled": "true", "integration.ip": "127.0.0.1", "integration.port": 0,
            "integration.enable_https": str(protocol == "https").lower(),
            "integration.auth.mode": "static_bearer", "integration.auth.fingerprint_key": "test-fingerprint",
            "integration.auth.static.hmac_key": secret, "integration.credential.file": str(credentials)}
    registry = RegistryCore(use_vectordb=False, persistence_mode="sqlite",
                            persistence_conf={"sqlite.path": str(tmp_path / "registry.db")})
    monkeypatch.setattr(custom_handle, "get_registry", lambda: registry)
    monkeypatch.setattr(integration, "get_registry_dependency", lambda: registry)
    monkeypatch.setattr(integration, "audit_integration", AsyncMock())
    monkeypatch.setattr(integration, "audit_integration_failure", AsyncMock())
    tracker = BanTracker(100, 300)
    monkeypatch.setattr(integration, "get_ban_tracker", lambda: tracker)
    # Preserve another test/application's registry slots, if present.
    monkeypatch.setattr(custom_handle.HandlerRegistry, "_instances", dict(custom_handle.HandlerRegistry._instances))
    verify = True
    tls = SimpleNamespace()  # Valid HTTP must not access even a TLS attribute.
    if protocol == "https":
        cert, key, pwd, _ = _materials(tmp_path)
        tls = ConfObj.as_object({"ssl_certfile": str(cert), "ssl_keyfile": str(key),
                                 "ssl_keyfile_password": str(pwd), "verify_client": "false"})
        verify = ssl.create_default_context(cafile=str(cert))
    access = listener.ThirdPartyAccessServer(conf, tls)
    try:
        access.start()
        port = access._server.servers[0].sockets[0].getsockname()[1]
        with httpx.Client(base_url=f"{protocol}://127.0.0.1:{port}", verify=verify,
                          trust_env=False, timeout=5) as client:
            assert client.get("/integration/v1/agent-cards").status_code == 401
            response = client.get("/integration/v1/agent-cards", headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200, response.text
            assert response.json()["agentCards"] == []
    finally:
        access.stop()
        registry.storage.close()
