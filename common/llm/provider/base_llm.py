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

import time
from abc import ABC, abstractmethod
from typing import Union, Tuple

from loguru import logger

from common.llm.config.llm_config import LLMConfig


class BaseLLM(ABC):
    llm_config: LLMConfig

    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
        self.model = llm_config.config_item.model
        self.base_url = llm_config.config_item.api
        self.api_key = llm_config.config_item.apikey

    def ask_llm(self, prompt) -> Union[str, Tuple[str, str]]:
        start_time = time.time()
        try:
            result = self._ask_llm(prompt)
            duration = time.time() - start_time
            logger.info(f"ask llm cost {duration} seconds")
            return result
        except Exception as e:
            logger.error(f"ask llm exception {e}")
        return ""

    def ask_llm_with_duration(self, prompt):
        start_time = time.time()
        ans = self.ask_llm(prompt)
        duration = time.time() - start_time
        return ans, duration

    def to_dict(self):
        return {"name": self.llm_config.llm_type.value}

    @abstractmethod
    def _ask_llm(self, prompt: str) -> Union[str, Tuple[str, str]]:
        """_ask_llm function is implemented by inherited class"""
