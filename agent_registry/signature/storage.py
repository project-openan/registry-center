import os
import hashlib
from pathlib import Path
from typing import Optional
from loguru import logger


class StoragePath:
    """
    存储路径工具类，用于后台公钥文件路径创建，权限设置等管理
    """
    
    BASE_DIR = os.path.join(Path(__file__).parent.parent.parent, "etc", "sign_verify", "jwks")
    
    @staticmethod
    def get_storage_path(organization: Optional[str], agent_name: str, provider_url: Optional[str] = None) -> str:
        """
        构造存储路径
        
        Args:
            organization: 组织名称（可选）
            agent_name: Agent名称
            provider_url: Provider URL（可选，仅当organization为None时使用）
        
        Returns:
            str: 存储文件路径
        """
        if organization:
            # 有organization：etc/sign_verify/jwks/{organization}/{agent_name}.json
            org_dir = os.path.join(StoragePath.BASE_DIR, organization)
            return os.path.join(org_dir, f"{agent_name}.json")
        else:
            # 无organization：etc/sign_verify/jwks/{name+url的hash}.json
            if not provider_url:
                raise ValueError("provider_url is required when organization is None")
            
            hash_key = f"{agent_name}{provider_url}"
            hash_value = hashlib.sha256(hash_key.encode('utf-8')).hexdigest()
            return os.path.join(StoragePath.BASE_DIR, f"{hash_value}.json")
    
    @staticmethod
    def get_organization_dir(organization: str) -> str:
        """
        获取组织目录路径
        
        Args:
            organization: 组织名称
        
        Returns:
            str: 组织目录路径
        """
        return os.path.join(StoragePath.BASE_DIR, organization)
    
    @staticmethod
    def ensure_directory_exists(file_path: str) -> None:
        """
        确保目录存在，如果不存在则创建
        
        Args:
            file_path: 文件路径
        """
        file_path_obj = Path(file_path)
        file_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        # 设置目录权限为700
        os.chmod(file_path_obj.parent, 0o700)
    
    @staticmethod
    def set_file_permissions(file_path: str) -> None:
        """
        设置文件权限为600
        
        Args:
            file_path: 文件路径
        """
        if os.path.exists(file_path):
            os.chmod(file_path, 0o600)
    
    @staticmethod
    def is_valid_path(file_path: str) -> bool:
        """
        验证路径是否有效
        
        Args:
            file_path: 文件路径
        
        Returns:
            bool: 路径是否有效
        """
        try:
            path_obj = Path(file_path)
            return path_obj.exists() and path_obj.is_file()
        except Exception:
            return False