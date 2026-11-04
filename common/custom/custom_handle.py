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

from abc import ABC, abstractmethod
from typing import Dict, Type
from functools import partial
import threading
import asyncio
import anyio

from agent_registry.registry_instance import get_registry
from agent_registry.model.agent_layer import LAYER_UNSET
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
        initial_status = kwargs.get('initial_status', 'published')
        owner = kwargs.get('owner')
        layer = kwargs.get('layer', LAYER_UNSET)
        if layer is LAYER_UNSET:
            return get_registry().register_with_status(
                *args, initial_status=initial_status, owner=owner
            )
        return get_registry().register_with_status(
            *args, initial_status=initial_status, owner=owner, layer=layer
        )


class QueryHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return get_registry().find_exact(*args, **kwargs)

class UpdateHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        owner = kwargs.get('owner')
        layer = kwargs.get('layer', LAYER_UNSET)
        if layer is LAYER_UNSET:
            return get_registry().update(*args, owner=owner)
        return get_registry().update(*args, owner=owner, layer=layer)

class GetHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        owner = kwargs.get('owner')
        return get_registry().get_by_key_with_owner(*args, owner=owner)

_retrieve_worker = threading.local()


async def run_retrieve_query(query, *args, **kwargs):
    """Run synchronous model I/O under the listener's shared worker budget."""
    loop = asyncio.get_running_loop()
    if getattr(_retrieve_worker, 'loop', None) is not loop:
        _retrieve_worker.loop = loop
        _retrieve_worker.limiter = asyncio.Semaphore(8)
    limiter = _retrieve_worker.limiter
    await limiter.acquire()

    async def run_query():
        try:
            return await anyio.to_thread.run_sync(partial(query, *args, **kwargs))
        finally:
            limiter.release()

    # Keep the slot until underlying I/O stops, even if the caller is cancelled.
    worker = loop.create_task(run_query())
    worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
    return await asyncio.shield(worker)


class RetrieveHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        return await run_retrieve_query(get_registry().retrieve_by_task, *args, **kwargs)

class DeregisterHandler(BaseHandler):
    async def handle(self, *args, **kwargs):
        owner = kwargs.get('owner')
        return get_registry().deregister(*args, owner=owner)

# ==================== Registry ====================
class HandlerRegistry:
    _registry: Dict[str, Type[BaseHandler]] = {}
    _instances: Dict[str, BaseHandler] = {}

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
        Get handler singleton instance by interface type.
        :param interface_type: Interface type identifier.
        :return: BaseHandler instance (user-defined or default).
        """
        key = interface_type.value
        if key in cls._instances:
            return cls._instances[key]

        if key in cls._registry:
            handler = cls._registry[key]()
        else:
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
            handler_class = default_map.get(key)
            if handler_class is None:
                raise ValueError(f"Unknown interface type: {interface_type}")
            handler = handler_class()
        cls._instances[key] = handler
        return handler
