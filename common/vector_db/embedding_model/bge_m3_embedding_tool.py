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
import requests
from loguru import logger
from common.vector_db.embedding_model.config.embedding_config import EmbeddingType
from common.vector_db.embedding_model.config.embedding_tool import EmbeddingTool
from common.vector_db.embedding_model.config.embedding_tool_registry import embedding_tool_register


@embedding_tool_register(EmbeddingType.BGEM3)
class BgeM3EmbeddingTool(EmbeddingTool):
    def __init__(self,config:dict):
        super().__init__(config)
        self.embeeding_uri = config["uri"]

    def get_embedding_vector(self,context:str):
        data = {
            "input":[context],
            "model":"bge-m3",
            "encoding_format":"float"
        }
        responses = requests.post(self.embeeding_uri,json=data)
        if responses.status_code == 200:
            response = responses.json()
            return response["data"][0]["embedding"]
        logger.error(f"Error:{responses.status_code,responses.text}")
        return []