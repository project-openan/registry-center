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

from typing import TypeVar, Generic, Type, Dict, Any, Callable, Optional, Union, List

T = TypeVar('T')


class PluginRegistry(Generic[T]):
    """Generic plugin registry supporting registration and cached instance creation."""

    def __init__(self):
        self._providers: Dict[Any, Type[T]] = {}

    def register(self, key: Any, provider_cls: Type[T]) -> None:
        self._providers[key] = provider_cls

    def get_provider(self, key: Any) -> Type[T]:
        return self._providers[key]

    def create_instance(self, key: Any, config: dict) -> T:
        return self._providers[key](config)

    def get_or_create_instance(self, key: Any, config: dict,
                                cache: Dict[Any, T]) -> T:
        if key not in cache:
            cache[key] = self.create_instance(key, config)
        return cache[key]

    def register_decorator(self, *keys: Any) -> Callable[[Type[T]], Type[T]]:
        """Decorator that registers a class under one or more keys."""
        def decorator(cls: Type[T]) -> Type[T]:
            for key in keys:
                self._providers[key] = cls
            return cls
        return decorator

    def make_decorator(self) -> Callable[[Any], Callable[[Type[T]], Type[T]]]:
        """Create a standalone decorator function that can be imported and used
        by plugins, similar to Flask's @app.route decorator pattern."""
        def register_wrapper(*keys: Any) -> Callable[[Type[T]], Type[T]]:
            if len(keys) == 1 and isinstance(keys[0], (list, tuple)):
                keys_to_use = keys[0]
            else:
                keys_to_use = keys
            def decorator(cls: Type[T]) -> Type[T]:
                for key in keys_to_use:
                    self._providers[key] = cls
                return cls
            return decorator
        return register_wrapper
