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

# ---------- Dependency: Registry Core (Singleton) ----------
_registry_instance = None


def get_registry():
    """
    Return a singleton instance of RegistryCore.
    """
    from agent_registry.core import RegistryCore
    from agent_registry.config import PERSISTENCE_FILE, PERSISTENCE_CONF, PERSISTENCE_MODE
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = RegistryCore(
            persistence_file=PERSISTENCE_FILE,
            persistence_mode=PERSISTENCE_MODE,
            persistence_conf=PERSISTENCE_CONF
        )
    return _registry_instance


def initialize_registry():
    """
    Initialize the registry with storage backend.
    Called during app startup.
    """
    registry = get_registry()
    registry.initialize()
    return registry
