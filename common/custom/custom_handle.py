from abc import ABC, abstractmethod
from typing import Dict, Type

from agent_registry.registry_instance import get_registry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import audit_logger
from common.util.authenticate_util import authenticate
from common.util.cipher_util import decrypt


class BaseHandler(ABC):
    """统一的抽象基类，所有接口实现必须继承此类并实现 handle 方法"""

    @abstractmethod
    async def handle(self, *args, **kwargs):
        """具体业务逻辑由子类实现"""
        pass

# ==================== 默认实现 ====================
class DecryptHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return decrypt(*args)


class AuditHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        audit_logger.audit(*args)


class AuthenticateHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return authenticate(*args)


class InsertHandler(BaseHandler):

    async def handle(self, *args, **kwargs):
        return await get_registry().register(*args)


class QueryHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return get_registry().find_exact(*args)


# ==================== 注册表 ====================
class HandlerRegistry:
    _registry: Dict[str, Type[BaseHandler]] = {}

    @classmethod
    def register(cls, interface_type: InterfaceType, handler_class: Type[BaseHandler]) -> None:
        """
        注册用户自定义实现类
        :param interface_type: 接口类型标识，例如 "decrypt", "audit", "authenticate", "insert", "query"
        :param handler_class: 继承自 BaseHandler 的自定义类
        """
        if not issubclass(handler_class, BaseHandler):
            raise TypeError("handler_class must be a subclass of BaseHandler")
        cls._registry[interface_type.value] = handler_class

    @classmethod
    def get_handler(cls, interface_type: InterfaceType) -> BaseHandler:
        """
        根据接口类型获取处理器实例
        :param interface_type: 接口类型标识
        :return: BaseHandler实例（用户自定义或默认）
        """
        # 若存在用户注册的类，则实例化并返回
        if interface_type.value in cls._registry:
            return cls._registry[interface_type.value]()

        # 否则返回对应的默认实现
        default_map = {
            "decrypt": DecryptHandler,
            "audit": AuditHandler,
            "authenticate": AuthenticateHandler,
            "insert": InsertHandler,
            "query": QueryHandler,
        }
        handler_class = default_map.get(interface_type.value)
        if handler_class is None:
            raise ValueError(f"Unknown interface type: {interface_type}")
        return handler_class()