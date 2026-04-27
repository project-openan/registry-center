# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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

from abc import ABC, abstractmethod
from typing import Dict, Type

from agent_registry.registry_instance import get_registry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import audit_logger
from common.util.authenticate_util import authenticate
from common.util.cipher_util import decrypt


class BaseHandler(ABC):
    """Abstract base class for all interface implementations. Subclasses must implement the handle method."""

    @abstractmethod
    async def handle(self, *args, **kwargs):
        """Business logic to be implemented by subclasses"""
        pass


# ==================== Default Implementations ====================
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
        return get_registry().register(*args)


class QueryHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return get_registry().find_exact(*args)

class UpdateHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return get_registry().update(*args)

class GetHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return get_registry().get_by_key(*args)

class RetrieveHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return get_registry().retrieve_by_task(*args)

class DeregisterHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return get_registry().deregister(*args)

# ==================== Registry ====================
class HandlerRegistry:
    _registry: Dict[str, Type[BaseHandler]] = {}

    @classmethod
    def register(cls, interface_type: InterfaceType, handler_class: Type[BaseHandler]) -> None:
        """
        Register a user-defined handler implementation.
        :param interface_type: Interface type identifier, e.g., "decrypt", "audit", "authenticate", "insert", "query".
        :param handler_class: Custom class inheriting from BaseHandler.
        """
        if not issubclass(handler_class, BaseHandler):
            raise TypeError("handler_class must be a subclass of BaseHandler")
        cls._registry[interface_type.value] = handler_class

    @classmethod
    def get_handler(cls, interface_type: InterfaceType) -> BaseHandler:
        """
        Get handler instance by interface type.
        :param interface_type: Interface type identifier.
        :return: BaseHandler instance (user-defined or default).
        """
        # If a user-registered class exists, instantiate and return
        if interface_type.value in cls._registry:
            return cls._registry[interface_type.value]()

        # Otherwise return the corresponding default implementation
        default_map = {
            "decrypt": DecryptHandler,
            "audit": AuditHandler,
            "authenticate": AuthenticateHandler,
            "insert": InsertHandler,
            "query": QueryHandler,
            "update": UpdateHandler,
            "get": GetHandler,
            "retrieve": RetrieveHandler,
            "deregister": DeregisterHandler,
        }
        handler_class = default_map.get(interface_type.value)
        if handler_class is None:
            raise ValueError(f"Unknown interface type: {interface_type}")
        return handler_class()