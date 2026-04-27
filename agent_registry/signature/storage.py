import os
import hashlib
from pathlib import Path
from typing import Optional
from loguru import logger


class StoragePath:
    """
    Storage path utility, used for backend public key file path management
    and permission configuration.
    """

    BASE_DIR = os.path.join(Path(__file__).parent.parent.parent, "etc", "sign_verify", "jwks")

    @staticmethod
    def get_storage_path(organization: Optional[str], agent_name: str, provider_url: Optional[str] = None) -> str:
        """
        Build storage path.

        Args:
            organization: Organization name (optional).
            agent_name: Agent name.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            str: Storage file path.
        """
        if organization:
            # With organization: etc/sign_verify/jwks/{organization}/{agent_name}.json
            org_dir = os.path.join(StoragePath.BASE_DIR, organization)
            return os.path.join(org_dir, f"{agent_name}.json")
        else:
            # Without organization: etc/sign_verify/jwks/{hash of name + url}.json
            if not provider_url:
                raise ValueError("provider_url is required when organization is None")

            hash_key = f"{agent_name}{provider_url}"
            hash_value = hashlib.sha256(hash_key.encode('utf-8')).hexdigest()
            return os.path.join(StoragePath.BASE_DIR, f"{hash_value}.json")

    @staticmethod
    def get_organization_dir(organization: str) -> str:
        """
        Get organization directory path.

        Args:
            organization: Organization name.

        Returns:
            str: Organization directory path.
        """
        return os.path.join(StoragePath.BASE_DIR, organization)

    @staticmethod
    def ensure_directory_exists(file_path: str) -> None:
        """
        Ensure the directory exists; create it if it doesn't.

        Args:
            file_path: File path.
        """
        file_path_obj = Path(file_path)
        file_path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Set directory permissions to 700
        os.chmod(file_path_obj.parent, 0o700)

    @staticmethod
    def set_file_permissions(file_path: str) -> None:
        """
        Set file permissions to 600.

        Args:
            file_path: File path.
        """
        if os.path.exists(file_path):
            os.chmod(file_path, 0o600)

    @staticmethod
    def is_valid_path(file_path: str) -> bool:
        """
        Validate whether the path is valid.

        Args:
            file_path: File path.

        Returns:
            bool: Whether the path is valid.
        """
        try:
            path_obj = Path(file_path)
            return path_obj.exists() and path_obj.is_file()
        except Exception:
            return False
