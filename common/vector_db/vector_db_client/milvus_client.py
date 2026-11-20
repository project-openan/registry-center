# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
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
from agent_registry.model.agent_layer import UNKNOWN_LAYER, normalize_layer
from agent_registry.persistence.base import AgentRecord
from agent_registry.persistence.milvus_layer_migration import (
    LayerMigrationRequiredError,
    collection_schema,
    require_layer_field,
    schema_output_fields,
)
from common.util.app_config import get_conf
from common.vector_db.vector_db_client.config.vector_db_client import VectorDBClient
from common.vector_db.vector_db_client.config.vector_db_client_registry import vectordb_tool_register
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType

VARCHAR_MAX_LENGTH = 65535
EMBEDDING_VECTOR_DIVISION_LENGTH = 1024


class VectorDimensionError(ValueError):
    """Raised when an embedding does not match the collection dimension."""


output_fields = [
    "id", "name", "description", "organization", "agent_card",
    "status", "owner", "layer",
]


@vectordb_tool_register(VectorDBType.Milvus)
class MilvusDBClient(VectorDBClient):
    def __init__(self, config: dict):
        super().__init__(config)
        client_uri = config["uri"]
        # A failed connection must leave a defined state: keeping the attribute
        # unset turned every later call into AttributeError.
        self.client = None
        try:
            self.client = MilvusClient(uri=client_uri, token=config.get("token", ""))
        except Exception as e:
            logger.error(f"Milvus initiation failed: {e}")

    def _client_ready(self) -> bool:
        """Report whether the Milvus connection is usable, logging when it is not.

        Every public operation follows the same contract: when the backend is
        unavailable it logs and returns its empty result instead of raising
        AttributeError, so callers can degrade to another retrieval path.
        """

        if self.client is None:
            logger.error("Milvus client is unavailable, operation skipped")
            return False
        return True

    def _output_fields_for_collection(self, collection_name):
        """Return fields supported by the target collection schema.

        Older collections may not have the static ``layer`` field and may
        also have dynamic fields disabled.  Keep their existing queries
        usable, while allowing the layer-aware schema to return all metadata.
        """

        schema = collection_schema(self.client, collection_name)
        return schema_output_fields(schema, output_fields)

    def _require_layer_field(self, collection_name):
        """Ensure layer filtering is only used after collection migration."""

        if not self.client.has_collection(collection_name):
            self.create_collection({"collection_name": collection_name})
        require_layer_field(self.client, collection_name)

    def create_collection(self, data):
        try:
            collection_name = data.get("collection_name")

            if not collection_name:
                raise ValueError("collection_name cannot be empty")

            if not self._client_ready():
                return False

            if self.client.has_collection(collection_name):
                logger.info(f"Collection {collection_name} already exists")
                return self.client

            schema = self.client.create_schema(
                auto_id=False,
                enable_dynamic_field=True,
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
                if key in ("status", "owner", "layer"):
                    continue
                schema.add_field(field_name=key, datatype=DataType.VARCHAR, max_length=VARCHAR_MAX_LENGTH,
                                 description=f"Field: {key}")

            schema.add_field(
                field_name="layer", datatype=DataType.VARCHAR,
                max_length=64, description="Registry registration layer"
            )

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

            if not self._client_ready():
                return False

            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it")

            if insert_entity.get("layer") is not None:
                self._require_layer_field(collection_name)

            # 1. Validate embedding dimension
            embedding = insert_entity.get("embedding", [])
            if not isinstance(embedding, list) or len(embedding) != EMBEDDING_VECTOR_DIVISION_LENGTH:
                raise VectorDimensionError(
                    f"Vector dimension must be {EMBEDDING_VECTOR_DIVISION_LENGTH}")

            # 2. Execute insert
            result = self.client.insert(
                collection_name=collection_name,
                data=insert_entity
            )

            # 3. Verify insert count
            insert_count = result.get("insert_count", 0)
            if insert_count == 0:
                logger.error(f"Insert returned zero insert count: collection={collection_name}")
                return False

            insert_id = result.get("ids", [None])[0] if isinstance(result.get("ids"), list) else result.get("ids")

            logger.info(f"Insert success! insert_id:{insert_id}, insert_count:{insert_count}")
            return True

        except (LayerMigrationRequiredError, VectorDimensionError):
            raise
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

            if not self._client_ready():
                return False

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
            collection_name = data.get("collection_name")
            entity = data.get("entity", {})

            if not self._client_ready():
                return False

            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it")
                return self.insert_entity(data)

            if entity.get("layer") is not None:
                self._require_layer_field(collection_name)

            self.client.upsert(
                collection_name=collection_name,
                data=entity
            )
            logger.info(f"Upsert successful: collection={collection_name}, id={entity.get('id')}")
            return True
        except LayerMigrationRequiredError:
            raise
        except MilvusException as e1:
            logger.error(f"Error: There is MilvusException in update method: {e1}")
            return False
        except Exception as e2:
            logger.error(f"Error: There is Exception in update method: {e2}")
            return False

    def retrieve_entity(self, data):
        collection_name = data.get("collection_name")
        query_embedding = data.get("embedding")
        top_n = data.get("top_n", 10)
        if not self._client_ready():
            return []
        if not self.client.has_collection(collection_name):
            self.create_collection(data)
            logger.info("Collection does not exist in database, created it")
        if data.get("layer") is not None:
            self._require_layer_field(collection_name)
        try:
            self.client.load_collection(collection_name=collection_name)
            search_kwargs = {
                "collection_name": collection_name,
                "data": [query_embedding],
                "anns_field": "embedding",
                "limit": top_n,
                "output_fields": self._output_fields_for_collection(collection_name),
                "search_params": {"metric_type": "L2", "param": {"nprobe": 10}},
            }
            filter_expr = self._build_filter(data)
            if filter_expr:
                search_kwargs["filter"] = filter_expr
            results = self.client.search(
                **search_kwargs
            )
            formatted_results = []
            if len(results) == 0 or len(results[0]) == 0:
                return formatted_results
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
            if not self._client_ready():
                return []
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
                output_fields=self._output_fields_for_collection(collection_name)
            )
            output = []
            if len(results) == 0:
                return output
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
            if not self._client_ready():
                return []
            if not self.client.has_collection(collection_name):
                self.create_collection(data)
                logger.info("Collection does not exist in database, created it")
                return []
            self.client.load_collection(collection_name=collection_name)
            results = self.client.query(
                collection_name=collection_name,
                filter="id != \"\"",
                output_fields=self._output_fields_for_collection(collection_name),
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

    @staticmethod
    def _build_filter(data):
        """Build a Milvus expression from validated registry metadata."""

        clauses = []
        layer = data.get("layer")
        if layer is not None:
            clauses.append(f'layer == {json.dumps(normalize_layer(layer))}')
        status = data.get("status")
        if status is not None:
            clauses.append(f'status == {json.dumps(status)}')
        return " and ".join(clauses) if clauses else None

    @staticmethod
    def _entity_to_record(entity) -> AgentRecord:
        card_data = entity.get("agent_card", "{}")
        if isinstance(card_data, str):
            card_data = json.loads(card_data)
        from google.protobuf.json_format import Parse
        from a2a.types import AgentCard
        record = AgentRecord(
            agent_card=Parse(json.dumps(card_data), AgentCard()),
            owner=entity.get("owner"),
            status=entity.get("status", "published"),
            layer=entity.get("layer", UNKNOWN_LAYER),
        )
        try:
            record.layer = normalize_layer(record.layer)
        except ValueError:
            record.layer = UNKNOWN_LAYER
        return record

    def _query_records(self, collection_name, filter_expr, limit=None, offset=None):
        if not self._client_ready():
            return []
        if not self.client.has_collection(collection_name):
            self.create_collection({"collection_name": collection_name})
            return []
        self.client.load_collection(collection_name=collection_name)
        kwargs = {
            "collection_name": collection_name,
            "filter": filter_expr or 'id != ""',
            "output_fields": self._output_fields_for_collection(collection_name),
        }
        if limit is not None:
            kwargs["limit"] = limit
        if offset is not None and offset > 0:
            kwargs["offset"] = offset
        return self.client.query(**kwargs)

    def find_records(self, collection_name, name=None, organization=None,
                     layer=None, status=None, owner=None, limit=None, offset=0):
        clauses = []
        if name is not None:
            clauses.append(f'name like {json.dumps(f"%{name}%")}')
        if organization is not None:
            clauses.append(f'organization == {json.dumps(organization)}')
        if owner is not None:
            clauses.append(f'owner == {json.dumps(owner)}')
        filter_expr = self._build_filter({"layer": layer, "status": status})
        if layer is not None:
            self._require_layer_field(collection_name)
        if filter_expr:
            clauses.append(filter_expr)
        return [self._entity_to_record(entity) for entity in self._query_records(
            collection_name, " and ".join(clauses) if clauses else None,
            limit=limit,
            offset=offset,
        )]

    def find_records_by_key(self, collection_name, name, organization):
        key = f'{name}::{organization}'
        return [self._entity_to_record(entity) for entity in self._query_records(
            collection_name, f'id == {json.dumps(key)}', limit=1
        )]

    def retrieve_records(self, collection_name, embedding, top_n, layer=None,
                         status=None, selector=None, task=""):
        if not self._client_ready():
            return []
        if not self.client.has_collection(collection_name):
            self.create_collection({"collection_name": collection_name})
            return []
        self.client.load_collection(collection_name=collection_name)
        search_kwargs = {
            "collection_name": collection_name,
            "data": [embedding],
            "anns_field": "embedding",
            "limit": top_n,
            "output_fields": self._output_fields_for_collection(collection_name),
            "search_params": {"metric_type": "L2", "param": {"nprobe": 10}},
        }
        if layer is not None:
            self._require_layer_field(collection_name)
        filter_expr = self._build_filter({"layer": layer, "status": status})
        if filter_expr:
            search_kwargs["filter"] = filter_expr
        results = self.client.search(**search_kwargs)
        if not results or not results[0]:
            return []
        records = [self._entity_to_record(result["entity"]) for result in results[0]]
        if selector is None:
            return records
        agents_info = [{
            "name": r.agent_card.name,
            "description": r.agent_card.description,
            "organization": r.agent_card.provider.organization,
            "skills": [skill.name for skill in r.agent_card.skills],
        } for r in records]
        selected_pairs = selector(task, agents_info, top_n)
        return [r for r in records
                if (r.agent_card.provider.organization, r.agent_card.name) in selected_pairs]
