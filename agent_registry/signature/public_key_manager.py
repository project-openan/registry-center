import os
import json
import datetime
from typing import Optional, List
from loguru import logger

from agent_registry.signature.models import JWK, JWKS, AgentKeysStorage
from agent_registry.signature.storage import StoragePath


class PublicKeyManager:
    """Public key manager"""

    MAX_KEYS_PER_AGENT = 5

    def __init__(self):
        self._base_dir = StoragePath.BASE_DIR

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
            # Validate key count
            if len(jwks.keys) > self.MAX_KEYS_PER_AGENT:
                raise ValueError(f"At most {self.MAX_KEYS_PER_AGENT} public keys can be added at once")

            # Validate each JWK key type
            for jwk in jwks.keys:
                if jwk.kty not in ['EC', 'RSA']:
                    raise ValueError(f"Key type only supports EC or RSA, got: {jwk.kty}")

            # Get storage path
            storage_path = StoragePath.get_storage_path(organization, agent_name, provider_url)

            # Ensure directory exists
            StoragePath.ensure_directory_exists(storage_path)

            # Read existing keys (if any)
            existing_keys = self._load_keys(storage_path)
            existing_keys_dict = {key.kid: key for key in existing_keys}

            # Add or update keys
            added_kids = []
            for jwk in jwks.keys:
                existing_keys_dict[jwk.kid] = jwk
                added_kids.append(jwk.kid)

            # Build storage object
            storage_obj = AgentKeysStorage(
                organization=organization,
                agent_name=agent_name,
                keys=list(existing_keys_dict.values()),
                updated_at=datetime.utcnow()
            )

            # Save to file
            self._save_keys(storage_path, storage_obj)

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

            # Read existing keys
            storage_obj = self._load_storage_obj(storage_path)

            # Find and remove key
            key_found = False
            keys = storage_obj.keys
            for i, key in enumerate(keys):
                if key.kid == kid:
                    keys.pop(i)
                    key_found = True
                    break

            if not key_found:
                logger.warning(f"Public key not found: {kid}")
                return False

            # Update storage object
            storage_obj.keys = keys
            storage_obj.updated_at = datetime.utcnow()

            # Save to file
            self._save_keys(storage_path, storage_obj)

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

            storage_obj = self._load_storage_obj(storage_path)
            return JWKS(keys=storage_obj.keys)

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

    def _load_keys(self, storage_path: str) -> List[JWK]:
        """
        Load public keys from file.

        Args:
            storage_path: Storage file path.

        Returns:
            List[JWK]: List of public keys.
        """
        try:
            storage_obj = self._load_storage_obj(storage_path)
            return storage_obj.keys
        except Exception as e:
            logger.error(f"Failed to load public keys: {e}")
            return []

    def _load_storage_obj(self, storage_path: str) -> AgentKeysStorage:
        """
        Load storage object from file.

        Args:
            storage_path: Storage file path.

        Returns:
            AgentKeysStorage: Storage object.
        """
        try:
            base_dir = os.getcwd()
            file_path = os.path.join(base_dir, storage_path)
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return AgentKeysStorage(**data)

        except Exception as e:
            logger.error(f"Failed to load storage object: {e}")
            raise

    def _save_keys(self, storage_path: str, storage_obj: AgentKeysStorage) -> None:
        """
        Save public keys to file.

        Args:
            storage_path: Storage file path.
            storage_obj: Storage object.
        """
        try:
            # Ensure directory exists
            StoragePath.ensure_directory_exists(storage_path)

            # Save to file
            with open(storage_path, 'w', encoding='utf-8') as f:
                json.dump(storage_obj.model_dump(), f, ensure_ascii=False, indent=2)

            # Set file permissions
            StoragePath.set_file_permissions(storage_path)

            logger.info(f"Successfully saved public keys to {storage_path}")

        except Exception as e:
            logger.error(f"Failed to save public keys: {e}")
            raise