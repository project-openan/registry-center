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

from sentence_transformers import SentenceTransformer
from common.vector_db.embedding_model.config.embedding_config import EmbeddingType
from common.vector_db.embedding_model.config.embedding_tool import EmbeddingTool
from common.vector_db.embedding_model.config.embedding_tool_registry import embedding_tool_register


@embedding_tool_register(EmbeddingType.BGELargeZH)
class BgeLargeEmbeddingTool(EmbeddingTool):
    def __init__(self,config:dict):
        super().__init__(config)
        client_uri = config["uri"]
        self.client = SentenceTransformer(client_uri)

    def get_embedding_vector(self,context:str):
        sentences = [context]
        embeddings = self.client.encode(sentences,normalize_embeddings=True)
        return embeddings.tolist()[0]