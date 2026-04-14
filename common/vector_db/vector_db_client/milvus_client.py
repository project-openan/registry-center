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

from pymilvus import MilvusClient, DataType, MilvusException
from loguru import logger

from agent_registry.config import AGENT_NUM_MAX
from common.util.config_util import get_conf
from common.vector_db.util import restore_string_values, flatten_to_strings
from common.vector_db.vector_db_client.config.vector_db_client import VectorDBClient
from common.vector_db.vector_db_client.config.vector_db_client_registry import vectordb_tool_register
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType

VARCHAR_MAX_LENGTH = 65535
SEARCH_NUM = 5
BGE_EMBEDDING_VECTOR_DIVISION_LENGTH = 1024
output_fields=["id", "name", "description", "provider", "protocolVersion", "version", "url", "iconUrl",
                               "skills", "capabilities", "defaultInputModes", "defaultOutputModes"]

@vectordb_tool_register(VectorDBType.Milvus)
class MilvusDBClient(VectorDBClient):
    def __init__(self, config: dict):
        super().__init__(config)
        client_uri = config["uri"]
        try:
            self.client = MilvusClient(uri=client_uri)
        except Exception as e:
            logger.error(f"Milvus initiation failed: {e}")

    def create_collection(self, data):
        try:
            collection_name = data.get("collection_name")
            entity = data.get("entity", {})

            if not collection_name:
                raise ValueError("collection_name 不能为空")

            if self.client.has_collection(collection_name):
                logger.info(f"Collection {collection_name} already exists")
                return self.client

            schema = self.client.create_schema(
                auto_id=False,
                enable_dynamic_fields=True,
                description=f"create collection named: {collection_name}",
            )

            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=VARCHAR_MAX_LENGTH,
                             auto_id=False, description="name of organization")

            schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=1024,
                             description="vector embedding")

            for key in entity.keys():
                if key == "embedding":
                    continue
                schema.add_field(field_name=key, datatype=DataType.VARCHAR, max_length=VARCHAR_MAX_LENGTH,
                                 description=f"{key}字段")

            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist": 128}
            )
            self.client.create_collection(
                collection_name=collection_name,
                schema=schema,
                consistency_level="Strong",
                index_params=index_params
            )

            logger.info(f"Collection {collection_name} created")

            return self.client
        except Exception as e:
            logger.error(f"Error: There is Exception in create collection method: {e}")
            return None

    def insert_entity(self, data):
        try:
            collection_name = data.get("collection_name")
            entity = data.get("entity", {})
            if len(entity) > 0:
                key_id = entity["name"] + "of" + entity["provider"]["organization"]
            else:
                logger.info("待插入数据中无entity，返回None")
                return None
            insert_entity = flatten_to_strings(entity)
            insert_entity["id"] = key_id
            if not collection_name:
                raise ValueError("collection_name 不能为空")

            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("当前数据库无此collection，已创建此collection")

            # 1. 校验 embedding 维度
            embedding = insert_entity.get("embedding", [])
            if not isinstance(embedding, list) or len(embedding) != BGE_EMBEDDING_VECTOR_DIVISION_LENGTH:
                raise ValueError(F"向量维度必须为 {BGE_EMBEDDING_VECTOR_DIVISION_LENGTH}")

            # 2. 执行插入操作
            result = self.client.insert(
                collection_name=collection_name,
                data=insert_entity
            )

            # 3. 获取插入的主键
            insert_id = result.get("ids", [None])[0] if isinstance(result.get("ids"), list) else result.get("ids")

            logger.info(f"Insert success! insert_id:{insert_id}")
            return True

        except Exception as e:
            logger.error(f"Error: There is Exception in insert method: {e}")
            return False

    def delete_entity(self, data):
        """
        删除实体数据（带异常处理）

        参数:
            data: dict, 包含 collection_name 和 id

        返回:
            bool: 删除成功返回 True，失败返回 False
        """
        try:
            # 1. 参数校验
            collection_name = data.get("collection_name")
            primary_key = data.get("id")

            if not collection_name:
                logger.error("✗ 删除失败：collection_name 不能为空")
                return False

            if primary_key is None:
                logger.error("✗ 删除失败：id 不能为空")
                return False

            # 2. 执行删除
            result = self.client.delete(
                collection_name=collection_name,
                ids=[primary_key]
            )

            # 3. 验证删除结果（可选）
            delete_count = result.get("delete_count", 0) if isinstance(result, dict) else 0
            if delete_count == 0:
                logger.error(f"⚠ 警告：未找到 ID 为 {primary_key} 的记录，可能已删除")

            logger.info(f"✓ 删除成功：collection={collection_name}, id={primary_key}")
            return True

        except Exception as e:
            print(f"✗ 删除失败：{e}")
            return False

    def update_entity(self, data):
        collection_name = data.get("collection_name")
        entity = data.get("entity")
        if not self.client.has_collection(collection_name):
            self.create_collection(data)
            logger.info("当前数据库无此collection，已创建此collection")
        try:
            self.client.upsert(
                collection_name=collection_name,
                data=entity
            )
            return True
        except MilvusException as e1:
            logger.error(f"Error: There is MilvusException in update method: {e1}")
            return False
        except Exception as e2:
            logger.error(f"Error: There is Exception in update method: {e2}")
            return False

    def retrieve_entity(self, data):
        collection_name = data.get("collection_name")
        query_embedding = data.get("embedding")
        try:
            results = self.client.search(
                collection_name=collection_name,
                data=[query_embedding],
                anns_field="embedding",
                limit=SEARCH_NUM,
                output_fields=output_fields,
                search_params={"metric_type": "COSINE", "param": {"nprobe": 10}}
            )
            formatted_results = []
            if results and len(results) > 0:
                for hit in results[0]:
                    formatted_results.append({
                        "id": hit.get("id"),
                        "distance": hit.get("distance"),
                        "entity": restore_string_values(hit.get("entity"))
                    })
            return formatted_results
        except Exception as e:
            logger.error(f"向量检索失败： {e}")
            return []

    def query_by_key(self, data):
        try:
            # 构建过滤表达式
            collection_name = data.get("collection_name")
            key = data.get("key")
            value = data.get("value")
            if isinstance(value, str):
                filter_expr = f'{key} == "{value}"'
            else:
                filter_expr = f'{key} == {value}'

            # 执行查询
            results = self.client.query(
                collection_name=collection_name,
                filter=filter_expr,
                output_fields=output_fields
            )
            formatted_results = []
            if results and len(results) > 0:
                for hit in results[0]:
                    formatted_results.append({
                        "id": hit.get("id"),
                        "distance": hit.get("distance"),
                        "entity": restore_string_values(hit.get("entity"))
                    })
            return formatted_results
        except Exception as e:
            logger.error(f"查询失败： {e}")
            return []

    def get_all_entities(self,data):
        try:
            collection_name = data.get("collection_name")
            results = self.client.query(
                collection_name=collection_name,
                filter="",
                output_fields=output_fields,
                limit=int(get_conf().get(AGENT_NUM_MAX, 40))  # 单次最大查询量
            )
            return results
        except Exception as e:
            logger.error(f"获取全部信息失败：{e}")
            return []