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
import pytest
from unittest.mock import Mock, patch, MagicMock
from a2a.types import AgentCard, AgentCardSignature
from agent_registry.agent_registry.agent_card_signer import AgentCardSigner


def test_is_enabled_true():
    with patch('agent_registry.agent_registry.agent_card_signer.AgentCardSigner._load_credentials'), \
         patch('agent_registry.agent_registry.agent_card_signer.AgentCardSigner._load_cert'):
        signer = AgentCardSigner(
            private_key_path="dummy_key.pem",
            cert_path="dummy_cert.pem",
            password_path=None,
            algorithm="RS256",
            sign_enabled=True
        )

        from cryptography.hazmat.primitives.asymmetric import rsa
        from a2a.utils.signing import create_signature_verifier
        signer._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signer._kid = "test_kid"

        agent_card = AgentCard()
        agent_card.name = "test_agent"
        agent_card.version = "1.0.0"

        result = signer.sign_agent_card(agent_card)

        assert result is agent_card
        assert len(result.signatures) == 1
        assert result.signatures[0].protected
        assert result.signatures[0].signature
        create_signature_verifier(lambda kid, jku: signer._private_key.public_key(), ["RS256"])(result)


def test_is_enabled_false():
    signer = AgentCardSigner(
        private_key_path="dummy_key.pem",
        cert_path="dummy_cert.pem",
        password_path=None,
        algorithm="RS256",
        sign_enabled=False
    )

    agent_card = AgentCard()
    agent_card.name = "test_agent"
    agent_card.version = "1.0.0"

    result = signer.sign_agent_card(agent_card)

    assert result is agent_card
    assert len(result.signatures) == 0


def test_is_enabled_method():
    with patch('agent_registry.agent_registry.agent_card_signer.AgentCardSigner._load_credentials'), \
         patch('agent_registry.agent_registry.agent_card_signer.AgentCardSigner._load_cert'):
        signer_enabled = AgentCardSigner(
            private_key_path="dummy_key.pem",
            cert_path="dummy_cert.pem",
            password_path=None,
            algorithm="RS256",
            sign_enabled=True
        )

        signer_disabled = AgentCardSigner(
            private_key_path="dummy_key.pem",
            cert_path="dummy_cert.pem",
            password_path=None,
            algorithm="RS256",
            sign_enabled=False
        )

        assert signer_enabled.is_enabled() is True
        assert signer_disabled.is_enabled() is False
