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
from common.util.config_util import get_conf

conf = get_conf()
use_vector_db = str(conf.get("use_vectordb", False)).lower() == 'true'

if use_vector_db:
    from common.vector_db.embedding_model.bge_m3_embedding_tool import BgeM3EmbeddingTool
    from common.vector_db.vector_db_client.milvus_client import MilvusDBClient
    __all__ = ["MilvusDBClient", "BgeM3EmbeddingTool"]
else:
    BgeM3EmbeddingTool = None
    MilvusDBClient = None
    __all__ = []