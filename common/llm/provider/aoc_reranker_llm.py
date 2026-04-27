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

import json
from typing import Dict, Any, Tuple, List, Optional

from common.llm.config.llm_config import LLMType, LLMConfig
from common.llm.provider.aoc_base_llm import AOCBaseLLM
from common.llm.provider.llm_provider_registry import registry_provider


@registry_provider(LLMType.AOC_RERANKER_LLM)
class AOCRerankerLLM(AOCBaseLLM):
    """AOC reranker model (e.g., bge_reranker_v2_m3)"""

    def _build_request_body(self, prompt: str) -> Dict[str, Any]:
        # prompt here is the query; documents need to be passed separately, placeholder for now
        extra = self.llm_config.config_item.extra
        template = extra.get('request_template')
        if template and isinstance(template, str):
            template_str = template.replace('{prompt}', json.dumps(prompt)[1:-1])
            return json.loads(template_str)
        else:
            # Default format requires query and documents, but documents must be provided by the caller
            # Therefore, the reranker model is better invoked via a dedicated rerank method
            raise NotImplementedError("Please use the rerank(query, documents) method to invoke the reranker model")

    def _parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        # Not used directly
        return '', json.dumps(data)

    def rerank(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        """
        Reranker interface, returns sorted results with index and relevance_score for each item.
        """
        extra = self.llm_config.config_item.extra
        template = extra.get('request_template')
        if template and isinstance(template, str):
            # Replace {query} and {documents} placeholders (documents is a JSON array)
            template_str = template.replace('{query}', json.dumps(query)[1:-1])
            template_str = template_str.replace('{documents}', json.dumps(documents))
            body = json.loads(template_str)
        else:
            body = {
                "model": self.model,
                "query": query,
                "documents": documents
            }

        headers = self._build_headers()
        response = self.client.post(self.base_url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

        # Extract ranking results (assumed format: {"results": [{"index": 0, "relevance_score": 0.9}]})
        try:
            return data.get('results', [])
        except Exception:
            raise ValueError(f"Cannot parse reranker response: {data}")

    def _ask_llm(self, prompt: str) -> Tuple[str, str]:
        # Direct invocation not supported; use rerank method instead
        raise NotImplementedError("Please use the rerank(query, documents) method")