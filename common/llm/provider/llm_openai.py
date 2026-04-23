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

from typing import Union, Tuple

import httpx
from openai import OpenAI
from openai.types.chat import ChatCompletionUserMessageParam

from common.llm.config.llm_config import LLMType, LLMConfig
from common.llm.provider.base_llm import BaseLLM
from common.llm.provider.llm_provider_registry import registry_provider


@registry_provider(LLMType.OPENAI_STYLE_LLM)
class OpenAIStyleLLM(BaseLLM):
    def __init__(self, llm_config: LLMConfig):
        super().__init__(llm_config)
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            http_client=httpx.Client(base_url=self.base_url, follow_redirects=True, verify=False),
        )

    def _ask_llm(self, prompt: str) -> Union[str, Tuple[str, str]]:
        user_message = ChatCompletionUserMessageParam(
            role="user",
            content=prompt
        )
        completion = self.client.chat.completions.create(
            model=self.llm_config.config_item.model,
            messages=[user_message],
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": self.enable_thinking
                }
            }
        )
        message = completion.choices[0].message
        reasoning = getattr(message, 'reasoning_content', '') or ''
        answer = message.content or ''
        return reasoning, answer
