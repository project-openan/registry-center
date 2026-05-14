import os
import json
from typing import Optional, List
from loguru import logger

from agent_registry.signature.models import JWK, JWKS
from agent_registry.signature.storage import StoragePath


class PublicKeyManager:
    """Public key manager"""

    MAX_KEYS_PER_AGENT = 5

    def add_public_keys(
        self,
        organization: Optional[str],
        agent_name: str,
        jwks: JWKS,
        provider_url: Optional[str] = None
    ) -> List[str]:
        """
        Batch add public keys.

        Args:
            organization: Organization name (optional).
            agent_name: Agent name.
            jwks: JWKS object.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            List[str]: List of added public key IDs.
        """
        try:
            if len(jwks.keys) > self.MAX_KEYS_PER_AGENT:
                raise ValueError(f"At most {self.MAX_KEYS_PER_AGENT} public keys can be added at once")

            for jwk in jwks.keys:
                if jwk.kty not in ['EC', 'RSA']:
                    raise ValueError(f"Key type only supports EC or RSA, got: {jwk.kty}")

            storage_path = StoragePath.get_storage_path(organization, agent_name, provider_url)
            StoragePath.ensure_directory_exists(storage_path)

            existing_jwks = self.load_jwks(storage_path)
            existing_keys_dict = {key.kid: key for key in existing_jwks.keys}

            added_kids = []
            for jwk in jwks.keys:
                existing_keys_dict[jwk.kid] = jwk
                added_kids.append(jwk.kid)

            new_jwks = JWKS(keys=list(existing_keys_dict.values()))
            self.save_jwks(storage_path, new_jwks)

            logger.info(f"Successfully added {len(added_kids)} public keys to {storage_path}")
            return added_kids

        except Exception as e:
            logger.error(f"Failed to add public keys: {e}")
            raise

    def remove_public_key(
        self,
        organization: Optional[str],
        agent_name: str,
        kid: str,
        provider_url: Optional[str] = None
    ) -> bool:
        """
        Remove a public key.

        Args:
            organization: Organization name (optional).
            agent_name: Agent name.
            kid: Key ID.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            bool: Whether the key was successfully removed.
        """
        try:
            storage_path = StoragePath.get_storage_path(organization, agent_name, provider_url)

            if not StoragePath.is_valid_path(storage_path):
                logger.warning(f"Public key config file does not exist: {storage_path}")
                return False

            jwks = self.load_jwks(storage_path)

            key_found = False
            keys = jwks.keys
            for i, key in enumerate(keys):
                if key.kid == kid:
                    keys.pop(i)
                    key_found = True
                    break

            if not key_found:
                logger.warning(f"Public key not found: {kid}")
                return False

            self.save_jwks(storage_path, JWKS(keys=keys))
            logger.info(f"Successfully deleted public key: {kid}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete public key: {e}")
            return False

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

            return self.load_jwks(storage_path)

        except Exception as e:
            logger.error(f"Failed to get public keys: {e}")
            return JWKS(keys=[])

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

    @staticmethod
    def load_jwks(storage_path: str) -> JWKS:
        """
        Load JWKS from file.

        Args:
            storage_path: Storage file path.

        Returns:
            JWKS: JWKS object.
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

    @staticmethod
    def save_jwks(storage_path: str, jwks: JWKS) -> None:
        """
        Save JWKS to file (only keys array).

        Args:
            storage_path: Storage file path.
            jwks: JWKS object.
        """
        try:
            StoragePath.ensure_directory_exists(storage_path)

            with open(storage_path, 'w', encoding='utf-8') as f:
                json.dump(jwks.model_dump(), f, ensure_ascii=False, indent=2)

            StoragePath.set_file_permissions(storage_path)
            logger.info(f"Successfully saved JWKS to {storage_path}")

        except Exception as e:
            logger.error(f"Failed to save JWKS: {e}")
            raise