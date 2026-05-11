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
from common.llm.config.llm_config import LLMType, LLMConfig
from common.llm.provider.base_llm import BaseLLM

LLM_REGISTRY = PluginRegistry()
llm_instance = {}

registry_provider = LLM_REGISTRY.make_decorator()


def get_or_create_llm_instance(config: LLMConfig) -> BaseLLM:
    import common.llm.provider.aoc_chat_llm  # noqa: F401 trigger decorator registration
    import common.llm.provider.aoc_embedding_llm  # noqa: F401
    import common.llm.provider.aoc_reranker_llm  # noqa: F401
    import common.llm.provider.llm_openai  # noqa: F401
    if config.llm_type in llm_instance:
        return llm_instance[config.llm_type]
    llm = LLM_REGISTRY.create_instance(config.llm_type, config)
    llm_instance[config.llm_type] = llm
    return llm
