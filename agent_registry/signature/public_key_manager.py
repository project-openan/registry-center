import os
import json
import datetime
import hashlib
from typing import Optional, List
from loguru import logger

from agent_registry.signature.models import JWK, JWKS, AgentKeysStorage
from agent_registry.signature.storage import StoragePath


class PublicKeyManager:
    """公钥管理器"""
    
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
        批量添加公钥配置
        
        Args:
            organization: 组织名称（可选）
            agent_name: Agent名称
            jwks: JWKS对象
            provider_url: Provider URL（可选，仅当organization为None时使用）
        
        Returns:
            List[str]: 添加的公钥ID列表
        """
        try:
            # 验证公钥数量
            if len(jwks.keys) > self.MAX_KEYS_PER_AGENT:
                raise ValueError(f"一次最多添加{self.MAX_KEYS_PER_AGENT}个公钥")
            
            # 验证每个JWK的密钥类型
            for jwk in jwks.keys:
                if jwk.kty not in ['EC', 'RSA']:
                    raise ValueError(f"密钥类型仅支持EC或RSA，当前: {jwk.kty}")
            
            # 获取存储路径
            storage_path = StoragePath.get_storage_path(organization, agent_name, provider_url)
            
            # 确保目录存在
            StoragePath.ensure_directory_exists(storage_path)
            
            # 读取现有公钥（如果存在）
            existing_keys = self._load_keys(storage_path)
            existing_keys_dict = {key.kid: key for key in existing_keys}
            
            # 添加或更新公钥
            added_kids = []
            for jwk in jwks.keys:
                existing_keys_dict[jwk.kid] = jwk
                added_kids.append(jwk.kid)
            
            # 构造存储对象
            storage_obj = AgentKeysStorage(
                organization=organization,
                agent_name=agent_name,
                keys=list(existing_keys_dict.values()),
                updated_at=datetime.utcnow()
            )
            
            # 保存到文件
            self._save_keys(storage_path, storage_obj)
            
            logger.info(f"成功添加 {len(added_kids)} 个公钥到 {storage_path}")
            return added_kids
            
        except Exception as e:
            logger.error(f"添加公钥失败: {e}")
            raise
    
    def remove_public_key(
        self,
        organization: Optional[str],
        agent_name: str,
        kid: str,
        provider_url: Optional[str] = None
    ) -> bool:
        """
        删除公钥配置
        
        Args:
            organization: 组织名称（可选）
            agent_name: Agent名称
            kid: 密钥ID
            provider_url: Provider URL（可选，仅当organization为None时使用）
        
        Returns:
            bool: 是否成功删除
        """
        try:
            storage_path = StoragePath.get_storage_path(organization, agent_name, provider_url)
            
            if not StoragePath.is_valid_path(storage_path):
                logger.warning(f"公钥配置文件不存在: {storage_path}")
                return False
            
            # 读取现有公钥
            storage_obj = self._load_storage_obj(storage_path)
            
            # 查找并删除公钥
            key_found = False
            keys = storage_obj.keys
            for i, key in enumerate(keys):
                if key.kid == kid:
                    keys.pop(i)
                    key_found = True
                    break
            
            if not key_found:
                logger.warning(f"公钥不存在: {kid}")
                return False
            
            # 更新存储对象
            storage_obj.keys = keys
            storage_obj.updated_at = datetime.utcnow()
            
            # 保存到文件
            self._save_keys(storage_path, storage_obj)
            
            logger.info(f"成功删除公钥: {kid}")
            return True
            
        except Exception as e:
            logger.error(f"删除公钥失败: {e}")
            return False
    
    def get_all_public_keys(
        self,
        organization: Optional[str],
        agent_name: str,
        provider_url: Optional[str] = None
    ) -> JWKS:
        """
        获取所有配置的公钥
        
        Args:
            organization: 组织名称（可选）
            agent_name: Agent名称
            provider_url: Provider URL（可选，仅当organization为None时使用）
        
        Returns:
            JWKS: JWKS对象
        """
        try:
            storage_path = StoragePath.get_storage_path(organization, agent_name, provider_url)
            if not StoragePath.is_valid_path(storage_path):
                logger.warning(f"公钥配置文件不存在: {storage_path}")
                return JWKS(keys=[])
            
            storage_obj = self._load_storage_obj(storage_path)
            return JWKS(keys=storage_obj.keys)
            
        except Exception as e:
            logger.error(f"获取公钥失败: {e}")
            return JWKS(keys=[])
    
    def get_public_key(
        self,
        organization: Optional[str],
        agent_name: str,
        kid: str,
        provider_url: Optional[str] = None
    ) -> Optional[JWK]:
        """
        根据kid获取公钥
        
        Args:
            organization: 组织名称（可选）
            agent_name: Agent名称
            kid: 密钥ID
            provider_url: Provider URL（可选，仅当organization为None时使用）
        
        Returns:
            Optional[JWK]: JWK对象，不存在返回None
        """
        try:
            jwks = self.get_all_public_keys(organization, agent_name, provider_url)
            
            for key in jwks.keys:
                if key.kid == kid:
                    return key
            
            return None
            
        except Exception as e:
            logger.error(f"获取公钥失败: {e}")
            return None
    
    def _load_keys(self, storage_path: str) -> List[JWK]:
        """
        从文件加载公钥列表
        
        Args:
            storage_path: 存储文件路径
        
        Returns:
            List[JWK]: 公钥列表
        """
        try:
            storage_obj = self._load_storage_obj(storage_path)
            return storage_obj.keys
        except Exception as e:
            logger.error(f"加载公钥失败: {e}")
            return []
    
    def _load_storage_obj(self, storage_path: str) -> AgentKeysStorage:
        """
        从文件加载存储对象
        
        Args:
            storage_path: 存储文件路径
        
        Returns:
            AgentKeysStorage: 存储对象
        """
        try:
            base_dir = os.getcwd()
            file_path = os.path.join(base_dir, storage_path)
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return AgentKeysStorage(**data)
            
        except Exception as e:
            logger.error(f"加载存储对象失败: {e}")
            raise
    
    def _save_keys(self, storage_path: str, storage_obj: AgentKeysStorage) -> None:
        """
        保存公钥到文件
        
        Args:
            storage_path: 存储文件路径
            storage_obj: 存储对象
        """
        try:
            # 确保目录存在
            StoragePath.ensure_directory_exists(storage_path)
            
            # 保存到文件
            with open(storage_path, 'w', encoding='utf-8') as f:
                json.dump(storage_obj.model_dump(), f, ensure_ascii=False, indent=2)
            
            # 设置文件权限
            StoragePath.set_file_permissions(storage_path)
            
            logger.info(f"成功保存公钥到 {storage_path}")
            
        except Exception as e:
            logger.error(f"保存公钥失败: {e}")
            raise