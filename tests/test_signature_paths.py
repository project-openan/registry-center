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

"""Actual signature validation paths of AgentCardSignatureValidator.

Complements tests/test_signature.py, which only covers the extraction
helpers and the disabled short-circuit. Every card below is a real protobuf
AgentCard signed with a generated RSA key via a2a.utils.signing, and every
network-dependent step (jku fetch) is stubbed, so no live network is used.

The disabled short-circuit (signature_validation_enabled=False) is already
covered by tests/test_signature.py and is intentionally not repeated here.
"""

import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.utils import base64url_encode

from a2a.types import AgentCard
from a2a.utils.signing import create_agent_card_signer

from agent_registry.signature.agent_card_signature_validator import (
    AgentCardSignatureValidator,
)
from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.signature.public_key_manager import PublicKeyManager
from agent_registry.signature.storage import StoragePath

ORG = "OrgA"
AGENT = "agent-a"
PROVIDER_URL = "https://orga.example"
BACKEND_KID = "backend-key-1"
JKU = "https://keys.example.com/jwks"


def _generate_rsa_key():
    """Return (private key PEM, modulus b64url, exponent b64url)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption())
    numbers = key.public_key().public_numbers()
    n_b64 = base64url_encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")).decode()
    e_b64 = base64url_encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")).decode()
    return pem, n_b64, e_b64


@pytest.fixture(scope="module")
def signer_keys():
    """Two independent RSA keypairs: (provisioned backend key, foreign key)."""
    return _generate_rsa_key(), _generate_rsa_key()


def _jwk(kid, n_b64, e_b64, include_x=True):
    """JWK dict matching the registry's PublicKeyManager file layout."""
    jwk = {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
           "n": n_b64, "e": e_b64}
    if include_x:
        # The registry JWK model requires `x` even for RSA keys (models.py
        # documents x as "modulus (RSA)"), so operator files must duplicate
        # the modulus into x. See TestKnownSignaturePathDefects for what
        # happens with a standard RFC 7517 RSA JWK that only carries n/e.
        jwk["x"] = n_b64
    return jwk


def _make_card():
    return AgentCard(name=AGENT,
                     provider={"organization": ORG, "url": PROVIDER_URL},
                     description="test agent", version="1.0.0")


def _sign(card, pem, kid, jku=None):
    """Append a real JWS signature over the canonical card (a2a signer)."""
    header = {"kid": kid, "alg": "RS256", "typ": "JOSE"}
    if jku:
        header["jku"] = jku
    create_agent_card_signer(signing_key=pem, protected_header=header)(card)
    return card


def _write_backend_jwks(base, jwk):
    """Write etc/sign_verify/jwks/{organization}/{agent_name}.json layout."""
    path = os.path.join(str(base), ORG, f"{AGENT}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"keys": [jwk]}, f)
    return path


@pytest.fixture
def jwks_base(tmp_path, monkeypatch):
    """Redirect StoragePath.BASE_DIR (derived from the package root) to tmp."""
    base = tmp_path / "sign_verify" / "jwks"
    monkeypatch.setattr(StoragePath, "BASE_DIR", str(base))
    return base


def _validator(with_backend=True):
    manager = PublicKeyManager() if with_backend else None
    return AgentCardSignatureValidator(
        JWKFetcher(public_key_manager=manager, jwk_allowlist=""))


class TestBackendKeyVerification:
    def test_valid_backend_signature_is_accepted(self, signer_keys, jwks_base):
        (pem, n_b64, e_b64), _ = signer_keys
        written = _write_backend_jwks(jwks_base, _jwk(BACKEND_KID, n_b64, e_b64))
        # storage resolution: etc/sign_verify/jwks/{organization}/{agent_name}.json
        assert StoragePath.get_storage_path(ORG, AGENT) == os.path.realpath(written)

        card = _sign(_make_card(), pem, BACKEND_KID)
        result = _validator().validate_agent_card(card)
        assert result.is_valid, (result.error_code, result.error_message)
        assert result.error_code is None

    def test_wrong_signature_is_rejected_with_error_message(self, signer_keys, jwks_base):
        (_, n_b64, e_b64), (foreign_pem, _, _) = signer_keys
        _write_backend_jwks(jwks_base, _jwk(BACKEND_KID, n_b64, e_b64))
        # protected header claims the provisioned kid, but the JWS was
        # produced by a foreign key the registry never provisioned
        card = _sign(_make_card(), foreign_pem, BACKEND_KID)
        result = _validator().validate_agent_card(card)
        assert not result.is_valid
        assert result.error_code == "SIG005"
        assert result.error_message

    def test_tampered_card_is_rejected(self, signer_keys, jwks_base):
        (pem, n_b64, e_b64), _ = signer_keys
        _write_backend_jwks(jwks_base, _jwk(BACKEND_KID, n_b64, e_b64))
        card = _sign(_make_card(), pem, BACKEND_KID)
        card.description = "tampered after signing"
        result = _validator().validate_agent_card(card)
        assert not result.is_valid
        assert result.error_code == "SIG005"
        assert result.error_message

    def test_unknown_kid_is_rejected_without_backend_or_jku(self, signer_keys, jwks_base):
        (pem, n_b64, e_b64), _ = signer_keys
        _write_backend_jwks(jwks_base, _jwk(BACKEND_KID, n_b64, e_b64))
        card = _sign(_make_card(), pem, "kid-nowhere")
        result = _validator().validate_agent_card(card)
        assert not result.is_valid
        assert result.error_code == "SIG005"


class TestJkuKeyPath:
    @pytest.mark.asyncio
    async def test_jwks_fetch_fails_closed_without_allowlist(self):
        fetcher = JWKFetcher(public_key_manager=None, jwk_allowlist="")
        assert await fetcher.fetch_jwks("https://keys.example.com/jwks") is None

    @pytest.mark.asyncio
    async def test_jwks_fetch_rejects_host_outside_allowlist(self):
        fetcher = JWKFetcher(public_key_manager=None,
                             jwk_allowlist="keys.trusted.example")
        assert await fetcher.fetch_jwks(JKU) is None

    def test_jku_key_success(self, signer_keys, monkeypatch):
        (pem, n_b64, e_b64), _ = signer_keys
        fetched = []

        async def fake_fetch_jku_key(self, kid, jku):
            fetched.append((kid, jku))
            return PyJWK({"kty": "RSA", "kid": BACKEND_KID, "use": "sig",
                          "alg": "RS256", "n": n_b64, "e": e_b64})

        monkeypatch.setattr(JWKFetcher, "fetch_jku_key", fake_fetch_jku_key)
        card = _sign(_make_card(), pem, BACKEND_KID, jku=JKU)
        validator = AgentCardSignatureValidator(
            JWKFetcher(public_key_manager=None, jwk_allowlist="keys.example.com"))
        result = validator.validate_agent_card(card)
        assert result.is_valid, (result.error_code, result.error_message)
        assert fetched == [(BACKEND_KID, JKU)]

    def test_jku_key_tampered_payload_is_rejected(self, signer_keys, monkeypatch):
        (pem, n_b64, e_b64), _ = signer_keys

        async def fake_fetch_jku_key(self, kid, jku):
            return PyJWK({"kty": "RSA", "kid": BACKEND_KID, "use": "sig",
                          "alg": "RS256", "n": n_b64, "e": e_b64})

        monkeypatch.setattr(JWKFetcher, "fetch_jku_key", fake_fetch_jku_key)
        card = _sign(_make_card(), pem, BACKEND_KID, jku=JKU)
        card.description = "tampered after signing"
        validator = AgentCardSignatureValidator(
            JWKFetcher(public_key_manager=None, jwk_allowlist="keys.example.com"))
        result = validator.validate_agent_card(card)
        assert not result.is_valid
        assert result.error_code == "SIG005"
        assert result.error_message


class TestUnsupportedAlgorithm:
    @pytest.mark.parametrize("alg", ["HS256", "PS256"])
    def test_disallowed_algorithm_is_rejected_with_sig005(self, alg):
        # alg outside {ES256, RS256} is rejected by the ProtectedHeader model,
        # the signature is skipped, and the jku fallback also fails closed.
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": alg, "kid": BACKEND_KID, "typ": "JOSE"}).encode()
        ).rstrip(b"=").decode()
        signature = base64.urlsafe_b64encode(b"not-a-real-signature").rstrip(b"=").decode()
        card = _make_card()
        sig = card.signatures.add()
        sig.protected = header
        sig.signature = signature
        result = _validator(with_backend=False).validate_agent_card(card)
        assert not result.is_valid
        assert result.error_code == "SIG005"
        assert result.error_message


class TestKnownSignaturePathDefects:
    """xfail-marked tests documenting source defects (do not fix here)."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="SOURCE BUG (agent_card_signature_validator.py): the jku fallback wraps "
               "fetch_jku_key in asyncio.run(), but validate_agent_card is called from the "
               "async registration flow (_process_register_cards in agent_registry/server.py) "
               "where a loop is already running, so asyncio.run() always raises RuntimeError; "
               "the validator masks it and returns SIG005, meaning jku-based verification can "
               "never succeed over the HTTP registration API.",
        strict=False)
    async def test_jku_verification_from_async_context(self, signer_keys, monkeypatch):
        (pem, n_b64, e_b64), _ = signer_keys

        async def fake_fetch_jku_key(self, kid, jku):
            return PyJWK({"kty": "RSA", "kid": BACKEND_KID, "use": "sig",
                          "alg": "RS256", "n": n_b64, "e": e_b64})

        monkeypatch.setattr(JWKFetcher, "fetch_jku_key", fake_fetch_jku_key)
        card = _sign(_make_card(), pem, BACKEND_KID, jku=JKU)
        validator = AgentCardSignatureValidator(
            JWKFetcher(public_key_manager=None, jwk_allowlist="keys.example.com"))
        # Production calls this on the event loop (async request handler);
        # a correct implementation must verify the card successfully there.
        result = validator.validate_agent_card(card)
        assert result.is_valid, (result.error_code, result.error_message)

    @pytest.mark.xfail(
        reason="SOURCE BUG: PyJWT 2.10.1 RSAAlgorithm.prepare_key(None) raises "
               "TypeError(\"Expecting a PEM-formatted key.\"), which is NOT a PyJWTError, so it "
               "escapes a2a create_signature_verifier's per-signature `except PyJWTError: "
               "continue` and aborts the whole verification loop; the validator's "
               "`except TypeError` masks it into SIG005. A card whose FIRST signature references "
               "a kid with no backend key is rejected even though a later signature verifies "
               "against a provisioned backend key.",
        strict=False)
    def test_card_with_valid_later_backend_signature_is_accepted(self, signer_keys, jwks_base):
        (backend_pem, n_b64, e_b64), (foreign_pem, _, _) = signer_keys
        _write_backend_jwks(jwks_base, _jwk("backend-key-2", n_b64, e_b64))
        card = _make_card()
        _sign(card, foreign_pem, "kid-not-provisioned")
        _sign(card, backend_pem, "backend-key-2")
        result = _validator().validate_agent_card(card)
        assert result.is_valid, (result.error_code, result.error_message)

    @pytest.mark.xfail(
        reason="SOURCE BUG: signature/models.py JWK requires `x` even for RSA keys (standard "
               "RFC 7517 RSA JWKs carry only n/e), and PublicKeyManager._load_jwks swallows the "
               "pydantic ValidationError and returns an empty JWKS, silently discarding ALL keys "
               "in the file.",
        strict=False)
    def test_standard_rsa_jwks_without_x_is_loadable(self, signer_keys, jwks_base):
        (pem, n_b64, e_b64), _ = signer_keys
        path = _write_backend_jwks(jwks_base, _jwk(BACKEND_KID, n_b64, e_b64,
                                                   include_x=False))
        assert StoragePath.is_valid_path(path)
        jwk = PublicKeyManager().get_public_key(ORG, AGENT, BACKEND_KID)
        assert jwk is not None, "standard RSA JWK (n/e only) must be loadable"
