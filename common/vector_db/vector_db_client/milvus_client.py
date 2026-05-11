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

from pymilvus import MilvusClient, DataType, MilvusException
from loguru import logger

from agent_registry.config import AGENT_NUM_MAX
from common.util.config_util import get_conf
from common.vector_db.vector_db_client.config.vector_db_client import VectorDBClient
from common.vector_db.vector_db_client.config.vector_db_client_registry import vectordb_tool_register
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType

VARCHAR_MAX_LENGTH = 65535
EMBEDDING_VECTOR_DIVISION_LENGTH = 1024
output_fields = ["id", "name", "description", "organization", "agent_card"]


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

            if not collection_name:
                raise ValueError("collection_name cannot be empty")

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

            schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR,
                             dim=EMBEDDING_VECTOR_DIVISION_LENGTH,
                             description="vector embedding")

            for key in output_fields:
                if key == "id":
                    continue
                schema.add_field(field_name=key, datatype=DataType.VARCHAR, max_length=VARCHAR_MAX_LENGTH,
                                 description=f"Field: {key}")

            self.client.create_collection(
                collection_name=collection_name,
                schema=schema
            )

            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="FLAT",
                metric_type="L2",
                index_name="embedding_index",
                params={"nlist": 128}
            )
            self.client.create_index(
                collection_name=collection_name,
                index_params=index_params,
                sync=False
            )

            logger.info(f"Collection {collection_name} created")

            return self.client
        except Exception as e:
            logger.error(f"Error: There is Exception in create collection method: {e}")
            return None

    def insert_entity(self, data):
        try:
            collection_name = data.get("collection_name")
            insert_entity = data.get("entity", {})
            if not collection_name:
                raise ValueError("collection_name cannot be empty")

            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it")

            # 1. Validate embedding dimension
            embedding = insert_entity.get("embedding", [])
            if not isinstance(embedding, list) or len(embedding) != EMBEDDING_VECTOR_DIVISION_LENGTH:
                raise ValueError(f"Vector dimension must be {EMBEDDING_VECTOR_DIVISION_LENGTH}")

            # 2. Execute insert
            result = self.client.insert(
                collection_name=collection_name,
                data=insert_entity
            )

            # 3. Get inserted primary key
            insert_id = result.get("ids", [None])[0] if isinstance(result.get("ids"), list) else result.get("ids")

            logger.info(f"Insert success! insert_id:{insert_id}")
            return True

        except Exception as e:
            logger.error(f"Error: There is Exception in insert method: {e}")
            return False

    def delete_entity(self, data):
        """
        Delete entity data (with exception handling)

        Args:
            data: dict, containing collection_name and id

        Returns:
            bool: True on success, False on failure
        """
        try:
            # 1. Parameter validation
            collection_name = data.get("collection_name")
            primary_key = data.get("id")

            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it. Collection is empty, no delete needed.")
                return False

            if primary_key is None:
                logger.error("Delete failed: id cannot be empty")
                return False

            # 2. Execute delete
            self.client.delete(
                collection_name=collection_name,
                ids=[primary_key]
            )

            logger.info(f"Delete successful: collection={collection_name}, id={primary_key}")
            return True

        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False

    def update_entity(self, data):
        try:
            delete_data = {"collection_name":data.get("collection_name"),"id":data.get("entity").get("id")}
            self.delete_entity(delete_data)
            return self.insert_entity(data)
        except MilvusException as e1:
            logger.error(f"Error: There is MilvusException in update method: {e1}")
            return False
        except Exception as e2:
            logger.error(f"Error: There is Exception in update method: {e2}")
            return False

    def retrieve_entity(self, data):
        collection_name = data.get("collection_name")
        query_embedding = data.get("embedding")
        top_n = data.get("top_n",10)
        if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it")
        try:
            self.client.load_collection(collection_name=collection_name)
            results = self.client.search(
                collection_name=collection_name,
                data=[query_embedding],
                anns_field="embedding",
                limit=top_n,
                output_fields=output_fields,
                search_params={"metric_type": "L2", "param": {"nprobe": 10}}
            )
            formatted_results = []
            for result in results[0]:
                formatted_results.append(json.loads(result["entity"]["agent_card"]))
            return formatted_results
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def query_by_key(self, data):
        try:
            # Build filter expression
            collection_name = data.get("collection_name")
            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it")
            key = data.get("key")
            value = data.get("value")
            if isinstance(value, str):
                filter_expr = f'{key} == "{value}"'
            else:
                filter_expr = f'{key} == {value}'

            # Execute query
            self.client.load_collection(collection_name=collection_name)
            results = self.client.query(
                collection_name=collection_name,
                filter=filter_expr,
                output_fields=output_fields
            )
            output = []
            if len(results) > 1:
                for result in results:
                    output.append(json.loads(result["agent_card"]))
                return output
            else:
                output.append(json.loads(results[0]["agent_card"]))
                return output
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def get_all_entities(self, data):
        try:
            collection_name = data.get("collection_name")
            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it")
                return []
            self.client.load_collection(collection_name=collection_name)
            results = self.client.query(
                collection_name=collection_name,
                filter="id != \" \"",
                output_fields=output_fields,
                limit=int(get_conf().get(AGENT_NUM_MAX, 40))  # Max query count per request
            )
            output = []
            if len(results) > 0:
                for result in results:
                    output.append(json.loads(result["agent_card"]))
                return output
            else:
                logger.info("Collection is empty")
                return output
        except Exception as e:
            logger.error(f"Failed to get all entities: {e}")
            return []