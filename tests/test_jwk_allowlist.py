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

"""Tests for the JWK host allowlist (CWE-863 signer-controlled jku)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.signature.models import JWKS


def _jwks_response_body() -> dict:
    return {
        "keys": [
            {
                "kty": "EC",
                "kid": "test-key",
                "use": "sig",
                "alg": "ES256",
                "crv": "P-256",
                "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
                "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0",
            }
        ]
    }


@pytest.mark.asyncio
async def test_fetch_fails_closed_when_no_allowlist_configured():
    """No allowlist => jku path disabled, no HTTP request is made."""
    fetcher = JWKFetcher(jwk_allowlist="")
    fetcher.session.get = AsyncMock()

    result = await fetcher.fetch_jwks("https://attacker.example.com/keys")

    assert result is None
    fetcher.session.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_rejects_host_not_in_allowlist():
    """Host outside the allowlist is rejected before any HTTP request."""
    fetcher = JWKFetcher(jwk_allowlist="keys.example.com")
    fetcher.session.get = AsyncMock()

    result = await fetcher.fetch_jwks("https://attacker.example.com/keys")

    assert result is None
    fetcher.session.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_rejects_non_https_even_when_host_allowed():
    """HTTPS-only rule still applies after the allowlist check."""
    fetcher = JWKFetcher(jwk_allowlist="keys.example.com")
    fetcher.session.get = AsyncMock()

    result = await fetcher.fetch_jwks("http://keys.example.com/keys")

    assert result is None
    fetcher.session.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_allows_host_in_allowlist():
    """Allowed host => request proceeds and JWKS is parsed."""
    fetcher = JWKFetcher(jwk_allowlist="keys.example.com")

    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Length": "256"}
    response.json.return_value = _jwks_response_body()

    fetcher.session.get = AsyncMock(return_value=response)

    result = await fetcher.fetch_jwks("https://keys.example.com/jwks.json")

    assert isinstance(result, JWKS)
    assert len(result.keys) == 1
    assert result.keys[0].kid == "test-key"
    fetcher.session.get.assert_awaited_once_with("https://keys.example.com/jwks.json")


@pytest.mark.asyncio
async def test_fetch_allowlist_matches_host_only_ignoring_port_and_case():
    """Port and case are ignored; the match is on the hostname alone."""
    fetcher = JWKFetcher(jwk_allowlist="Keys.Example.COM")

    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Length": "256"}
    response.json.return_value = _jwks_response_body()

    fetcher.session.get = AsyncMock(return_value=response)

    result = await fetcher.fetch_jwks("https://keys.example.com:8443/jwks.json")

    assert isinstance(result, JWKS)
    fetcher.session.get.assert_awaited_once_with("https://keys.example.com:8443/jwks.json")


@pytest.mark.asyncio
async def test_fetch_rejects_malformed_jku():
    """A jku with no hostname is rejected."""
    fetcher = JWKFetcher(jwk_allowlist="keys.example.com")
    fetcher.session.get = AsyncMock()

    result = await fetcher.fetch_jwks("https:///missing-host")

    assert result is None
    fetcher.session.get.assert_not_called()


def test_parse_allowlist_normalizes_whitespace_and_case():
    fetcher = JWKFetcher(jwk_allowlist=" keys.example.com , Keys2.Example.org , ")

    assert fetcher.jwk_allowlist == {"keys.example.com", "keys2.example.org"}
