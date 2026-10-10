# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Registry signatures using the same JWS contract as A2A consumers."""

from typing import Optional

from a2a.types import AgentCard
from a2a.utils.signing import create_agent_card_signer
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class AgentCardSigner:
    def __init__(self, private_key_path: str = "", cert_path: str = "",
                 password_path: Optional[str] = None, jku_url: str = "",
                 algorithm: str = "RS256", sign_enabled: bool = True):
        self.private_key_path = private_key_path
        self.cert_path = cert_path
        self.password_path = password_path
        self.jku_url = jku_url
        self.algorithm = algorithm
        self.sign_enabled = sign_enabled
        self._private_key = None
        self._kid = None
        if sign_enabled:
            if algorithm not in {"RS256", "RS384", "RS512"}:
                raise ValueError("Unsupported registry signing algorithm")
            self._load_credentials()
            self._load_cert()

    def is_enabled(self) -> bool:
        return self.sign_enabled

    def _load_credentials(self):
        password = None
        if self.password_path:
            with open(self.password_path, encoding="utf-8") as stream:
                password = stream.read().strip().encode("utf-8") or None
        with open(self.private_key_path, "rb") as stream:
            self._private_key = serialization.load_pem_private_key(stream.read(), password)
        if not isinstance(self._private_key, rsa.RSAPrivateKey):
            raise ValueError("Registry RS signing requires an RSA private key")

    def _load_cert(self):
        with open(self.cert_path, "rb") as stream:
            certificate = x509.load_pem_x509_certificate(stream.read())
        public_key = certificate.public_key()
        if (not isinstance(public_key, rsa.RSAPublicKey)
                or public_key.public_numbers() != self._private_key.public_key().public_numbers()):
            raise ValueError("Registry signing certificate does not match its private key")
        self._kid = format(certificate.serial_number, "x")

    def sign_agent_card(self, agent_card: AgentCard) -> AgentCard:
        if not self.sign_enabled:
            return agent_card
        header = {"alg": self.algorithm, "typ": "JOSE", "kid": self._kid}
        if self.jku_url:
            header["jku"] = self.jku_url
        # The SDK excludes existing signatures, preserves list order and signs
        # HEADER.PAYLOAD. Never return an unsigned card on a signing failure.
        return create_agent_card_signer(self._private_key, header)(agent_card)
