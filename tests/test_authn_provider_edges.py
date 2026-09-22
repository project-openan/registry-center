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
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See
#    the License for the specific language governing permissions and limitations
#    under the License.

"""Edge cases for the integration authentication providers in
agent_registry/integration/authn.py (happy paths covered by
tests/test_integration_authn.py). No network access: JWKS lookups and the
introspection endpoint are stubbed at the provider boundary."""

import pytest
import httpx

import agent_registry.integration.authn as authn_module
from agent_registry.integration.authn import (
    AuthenticationContext, Credential, IntrospectionBearerProvider,
    JwtBearerProvider, ScopeRoleMapper, StaticBearerProvider,
    token_fingerprint,
)
from agent_registry.integration.credentials import CredentialEntry
from common.util.authenticate_util import (
    AUTH_METHOD_OAUTH2_INTROSPECTION, AuthFailureReason, AuthenticationError,
    CallerRole,
)

_FAIL_DETAIL = "Authentication failed"
ISSUER = "https://issuer.example"
AUDIENCE = "registry-center"
JWKS_URI = "https://issuer.example/jwks"
INTROSPECTION_URI = "https://issuer.example/introspect"


def _mapper():
    return ScopeRoleMapper({"registry.read": "partner_service",
                            "registry.audit": "analytics_tool"})


def _jwt_provider():
    return JwtBearerProvider(ISSUER, AUDIENCE, JWKS_URI, ["RS256"], _mapper())


def _introspection_provider(client, **overrides):
    kwargs = dict(endpoint=INTROSPECTION_URI, client_id="client",
                  client_secret="secret", issuer=ISSUER, audience=AUDIENCE,
                  mapper=_mapper(), client=client)
    kwargs.update(overrides)
    return IntrospectionBearerProvider(**kwargs)


class _FakeClock:
    """Replaces the stdlib time module reference inside authn so cache TTL
    behaviour is deterministic without sleeping."""

    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _StubIntrospectionClient:
    """Minimal stand-in for httpx.AsyncClient used by the introspection provider."""

    def __init__(self, payload=None, status_code=200):
        self.calls = 0
        self._payload = payload
        self._status_code = status_code
        # httpx >= 0.28 raise_for_status() requires the request to be attached
        self._request = httpx.Request("POST", INTROSPECTION_URI)

    async def post(self, *args, **kwargs):
        self.calls += 1
        if self._payload is None:
            return httpx.Response(self._status_code, request=self._request)
        return httpx.Response(self._status_code, json=self._payload,
                              request=self._request)


def _active_payload(clock, **overrides):
    payload = {"active": True, "sub": "analytics",
               "client_id": "analytics-client", "scope": "registry.audit",
               "iss": ISSUER, "aud": AUDIENCE, "exp": clock.now + 60}
    payload.update(overrides)
    return payload


class TestJwtBearerProviderConstruction:
    @pytest.mark.parametrize("missing", ["issuer", "audience", "jwks_uri"])
    def test_rejects_missing_issuer_audience_or_jwks_uri(self, missing):
        params = {"issuer": ISSUER, "audience": AUDIENCE, "jwks_uri": JWKS_URI,
                  "algorithms": ["RS256"], "mapper": _mapper()}
        params[missing] = ""
        with pytest.raises(ValueError):
            JwtBearerProvider(**params)

    def test_rejects_http_jwks_uri(self):
        with pytest.raises(ValueError):
            JwtBearerProvider(ISSUER, AUDIENCE, "http://issuer.example/jwks",
                              ["RS256"], _mapper())

    @pytest.mark.parametrize("algorithms", [[], ["none"], ["RS256", "NONE"]])
    def test_rejects_unsafe_algorithm_lists(self, algorithms):
        with pytest.raises(ValueError):
            JwtBearerProvider(ISSUER, AUDIENCE, JWKS_URI, algorithms, _mapper())


class TestJwtBearerProviderAuthenticate:
    @pytest.mark.asyncio
    async def test_missing_sub_claim_is_rejected(self, monkeypatch):
        provider = _jwt_provider()
        monkeypatch.setattr(provider, "_decode",
                            lambda token: {"scope": "registry.read"})
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(Credential("bearer", "jwt"),
                                        AuthenticationContext("ip"))
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_conflicting_mapped_scopes_are_rejected(self, monkeypatch):
        provider = _jwt_provider()
        monkeypatch.setattr(provider, "_decode",
                            lambda token: {"sub": "partner",
                                           "scope": "registry.read registry.audit"})
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(Credential("bearer", "jwt"),
                                        AuthenticationContext("ip"))
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_unmapped_scopes_yield_no_role_and_are_rejected(self, monkeypatch):
        provider = _jwt_provider()
        monkeypatch.setattr(provider, "_decode",
                            lambda token: {"sub": "partner",
                                           "scope": "registry.unknown"})
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(Credential("bearer", "jwt"),
                                        AuthenticationContext("ip"))
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_jwks_outage_maps_to_uniform_error_without_internals(self, monkeypatch):
        provider = _jwt_provider()

        def _outage(token):
            raise ConnectionError("jwks-endpoint-unreachable-marker")

        monkeypatch.setattr(provider._jwks, "get_signing_key_from_jwt", _outage)
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(Credential("bearer", "jwt"),
                                        AuthenticationContext("ip"))
        # uniform failure detail, never the underlying exception text
        assert exc.value.detail == _FAIL_DETAIL
        assert "jwks-endpoint-unreachable-marker" not in str(exc.value)
        assert "ConnectionError" not in str(exc.value)


class TestIntrospectionBearerProviderConstruction:
    def test_rejects_http_endpoint(self):
        with pytest.raises(ValueError):
            _introspection_provider(client=None,
                                    endpoint="http://issuer.example/introspect")

    @pytest.mark.parametrize("missing", ["client_id", "client_secret"])
    def test_rejects_missing_client_credentials(self, missing):
        with pytest.raises(ValueError):
            _introspection_provider(client=None, **{missing: ""})


class TestIntrospectionBearerProviderAuthenticate:
    @pytest.mark.asyncio
    async def test_active_token_builds_principal(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(_active_payload(clock))
        provider = _introspection_provider(client)
        p = await provider.authenticate(
            Credential("bearer", "opaque", fingerprint="fp"),
            AuthenticationContext("ip"))
        assert p.auth_method == AUTH_METHOD_OAUTH2_INTROSPECTION
        assert p.subject == "analytics"
        assert p.role == CallerRole.ANALYTICS_TOOL
        assert p.client_id == "analytics-client"
        assert p.issuer == ISSUER
        assert p.scopes == frozenset({"registry.audit"})

    @pytest.mark.asyncio
    async def test_second_call_within_cache_window_skips_endpoint(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(_active_payload(clock))
        provider = _introspection_provider(client)  # default cache_seconds=30
        credential = Credential("bearer", "opaque", fingerprint="fp")
        await provider.authenticate(credential, AuthenticationContext("ip"))
        clock.advance(5)
        await provider.authenticate(credential, AuthenticationContext("ip"))
        assert client.calls == 1

    @pytest.mark.asyncio
    async def test_cache_expiry_refetches_from_endpoint(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(_active_payload(clock))
        provider = _introspection_provider(client)  # default cache_seconds=30
        credential = Credential("bearer", "opaque", fingerprint="fp")
        await provider.authenticate(credential, AuthenticationContext("ip"))
        clock.advance(31)  # cache entry (min(now+30, exp)) is now stale
        await provider.authenticate(credential, AuthenticationContext("ip"))
        assert client.calls == 2

    @pytest.mark.asyncio
    async def test_inactive_token_is_rejected_as_invalid(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(_active_payload(clock, active=False))
        provider = _introspection_provider(client)
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(
                Credential("bearer", "opaque", fingerprint="fp"),
                AuthenticationContext("ip"))
        assert exc.value.reason == AuthFailureReason.INVALID_TOKEN
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_expired_introspection_result_is_rejected(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(_active_payload(clock, exp=clock.now - 10))
        provider = _introspection_provider(client)
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(
                Credential("bearer", "opaque", fingerprint="fp"),
                AuthenticationContext("ip"))
        assert exc.value.reason == AuthFailureReason.INVALID_TOKEN
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_not_yet_valid_result_is_rejected(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(
            _active_payload(clock, nbf=clock.now + 100, exp=clock.now + 200))
        provider = _introspection_provider(client)
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(
                Credential("bearer", "opaque", fingerprint="fp"),
                AuthenticationContext("ip"))
        assert exc.value.reason == AuthFailureReason.INVALID_TOKEN
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_issuer_mismatch_is_rejected(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(
            _active_payload(clock, iss="https://evil.example"))
        provider = _introspection_provider(client)
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(
                Credential("bearer", "opaque", fingerprint="fp"),
                AuthenticationContext("ip"))
        assert exc.value.reason == AuthFailureReason.INVALID_TOKEN
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    @pytest.mark.parametrize("aud", ["other-service", ["other-service"]])
    async def test_audience_mismatch_is_rejected(self, monkeypatch, aud):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(_active_payload(clock, aud=aud))
        provider = _introspection_provider(client)
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(
                Credential("bearer", "opaque", fingerprint="fp"),
                AuthenticationContext("ip"))
        assert exc.value.reason == AuthFailureReason.INVALID_TOKEN
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_endpoint_outage_maps_to_provider_unavailable(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(status_code=500)
        provider = _introspection_provider(client)
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(
                Credential("bearer", "opaque", fingerprint="fp"),
                AuthenticationContext("ip"))
        assert exc.value.reason == AuthFailureReason.PROVIDER_UNAVAILABLE
        assert exc.value.detail == _FAIL_DETAIL

    @pytest.mark.asyncio
    async def test_malformed_exp_is_mapped_to_authentication_error(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(authn_module, "time", clock)
        client = _StubIntrospectionClient(_active_payload(clock, exp="not-a-number"))
        provider = _introspection_provider(client)
        with pytest.raises(AuthenticationError):
            await provider.authenticate(
                Credential("bearer", "opaque", fingerprint="fp"),
                AuthenticationContext("ip"))


class TestScopeRoleMapperConstruction:
    @pytest.mark.parametrize("role", ["superuser", ""])
    def test_invalid_role_value_rejected_at_construction(self, role):
        with pytest.raises(ValueError):
            ScopeRoleMapper({"registry.read": role})


class TestStaticBearerProviderKeyMismatch:
    @pytest.mark.asyncio
    async def test_token_hash_computed_with_wrong_key_fails_closed(self):
        # Operational hazard: token_hash entries must be provisioned with the
        # SAME key as StaticBearerProvider(hmac_key=...). Entries hashed with a
        # different key (e.g. the fingerprint_key) can never authenticate, and
        # the failure is indistinguishable from an unknown token (uniform
        # detail, no key-material hints leaked).
        hashed_with_other_key = token_fingerprint("secret-token", "other-key")
        entry = CredentialEntry("cred-1", "service", CallerRole.NMS_OSS,
                                "service", token_hash=hashed_with_other_key)
        provider = StaticBearerProvider({"cred-1": entry}, "hmac-key")
        with pytest.raises(AuthenticationError) as exc:
            await provider.authenticate(Credential("bearer", "secret-token"),
                                        AuthenticationContext("ip"))
        assert exc.value.reason == AuthFailureReason.INVALID_TOKEN
        assert exc.value.detail == _FAIL_DETAIL
        assert "other-key" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_control_matching_key_authenticates(self):
        digest = token_fingerprint("secret-token", "hmac-key")
        entry = CredentialEntry("cred-1", "service", CallerRole.NMS_OSS,
                                "service", token_hash=digest)
        provider = StaticBearerProvider({"cred-1": entry}, "hmac-key")
        p = await provider.authenticate(Credential("bearer", "secret-token"),
                                        AuthenticationContext("ip"))
        assert p.subject == "service"
