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

from common.plugin_framework.registry import PluginRegistry
from common.vector_db.vector_db_client.config.vector_db_client import VectorDBClient
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType, VectorDBConfig

VECTORDB_REGISTRY = PluginRegistry()
vectordb_tool_instance: dict[VectorDBType, VectorDBClient] = {}

vectordb_tool_register = VECTORDB_REGISTRY.make_decorator()


def create_vectordb_tool_instance(config: VectorDBConfig):
    return VECTORDB_REGISTRY.create_instance(config.vectordb_type, config.__dict__)


def get_or_create_vectordb_tool_instance(config: VectorDBConfig) -> VectorDBClient:
    import common.vector_db.vector_db_client.milvus_client  # noqa: F401 trigger decorator registration
    return VECTORDB_REGISTRY.get_or_create_instance(
        config.vectordb_type, config.__dict__, vectordb_tool_instance
    )
