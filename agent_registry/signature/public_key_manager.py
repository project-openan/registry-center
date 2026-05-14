# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.

"""
Public Key Manager

Manages backend public keys for signature validation.
Public keys are stored in files: etc/sign_verify/jwks/{organization}/{agent_name}.json
File format: only contains "keys" array, organization and agent_name are derived from path.
"""

import os
import json
from typing import Optional
from loguru import logger

from agent_registry.signature.models import JWK, JWKS
from agent_registry.signature.storage import StoragePath


class PublicKeyManager:
    """Public key manager for backend signature validation"""

    def get_public_key(
        self,
        organization: Optional[str],
        agent_name: str,
        kid: str,
        provider_url: Optional[str] = None
    ) -> Optional[JWK]:
        """
        Get a public key by kid.

        Args:
            organization: Organization name (optional).
            agent_name: Agent name.
            kid: Key ID.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            Optional[JWK]: JWK object, None if not found.
        """
        try:
            jwks = self.get_all_public_keys(organization, agent_name, provider_url)

            for key in jwks.keys:
                if key.kid == kid:
                    return key

            return None

        except Exception as e:
            logger.error(f"Failed to get public key: {e}")
            return None

    def get_all_public_keys(
        self,
        organization: Optional[str],
        agent_name: str,
        provider_url: Optional[str] = None
    ) -> JWKS:
        """
        Get all configured public keys.

        Args:
            organization: Organization name (optional).
            agent_name: Agent name.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            JWKS: JWKS object.
        """
        try:
            storage_path = StoragePath.get_storage_path(organization, agent_name, provider_url)
            if not StoragePath.is_valid_path(storage_path):
                logger.warning(f"Public key config file does not exist: {storage_path}")
                return JWKS(keys=[])

            return self._load_jwks(storage_path)

        except Exception as e:
            logger.error(f"Failed to get public keys: {e}")
            return JWKS(keys=[])

    @staticmethod
    def _load_jwks(storage_path: str) -> JWKS:
        """
        Load JWKS from file.
        
        Returns empty JWKS if file doesn't exist or loading fails.

        Args:
            storage_path: Storage file path.

        Returns:
            JWKS: JWKS object (empty if not found).
        """
        try:
            if not os.path.exists(storage_path):
                return JWKS(keys=[])

            with open(storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return JWKS(**data)

        except Exception as e:
            logger.error(f"Failed to load JWKS: {e}")
            return JWKS(keys=[])