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
from functools import lru_cache

from agent_registry.config import PERSISTENCE_FILE
from agent_registry.core import RegistryCore


@lru_cache(maxsize=1)
def get_registry() -> RegistryCore:
    """
    Return a singleton instance of RegistryCore.
    The @lru_cache ensures the same instance is reused across requests,
    avoiding repeated loading of the persistence file.
    """
    return RegistryCore(persistence_file=PERSISTENCE_FILE)

get_registry()
