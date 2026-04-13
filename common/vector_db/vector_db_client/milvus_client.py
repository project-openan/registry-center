from pymilvus import MilvusClient, DataType, MilvusException
from loguru import logger
from common.vector_db.util import restore_string_values, flatten_to_strings
from common.vector_db.vector_db_client.config.vector_db_client import VectorDBClient
from common.vector_db.vector_db_client.config.vector_db_client_registry import vectordb_tool_register
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType

VARCHAR_MAX_LENGTH = 65535
SEARCH_NUM = 5
BGE_EMBEDDING_VECTOR_DIVISION_LENGTH = 1024


@vectordb_tool_register(VectorDBType.Milvus)
class MilvusDBClient(VectorDBClient):
    def __init__(self, config: dict):
        super().__init__(config)
        client_uri = config["uri"]
        self.client = MilvusClient(uri=client_uri)

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

            schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=1024, description="vector embedding")

            for key in entity.keys():
                if key == "embedding":
                    continue
                schema.add_field(field_name=key,datatype=DataType.VARCHAR,max_length=VARCHAR_MAX_LENGTH,description=f"{key}字段")

            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist":128}
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

        except Exception as e:
            logger.error(f"Error: There is Exception in insert method: {e}")
            return None


def delete_entity(self, data):
    collection_name = data.get("collection_name")
    entity = data.get("entity")
    primary_key = entity["id"]
    self.client.delete(
        collection_name=collection_name,
        ids=[primary_key]
    )


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
    except MilvusException as e1:
        logger.error(f"Error: There is MilvusException in update method: {e1}")
    except Exception as e2:
        logger.error(f"Error: There is Exception in update method: {e2}")


def retrieve_entity(self, data):
    collection_name = data.get("collection_name")
    query_embedding = data.get("embedding")
    try:
        results = self.client.search(
            collection_name=collection_name,
            data=[query_embedding],
            anns_field="embedding",
            limit=SEARCH_NUM,
            output_fields=["id", "name", "description", "provider", "protocolVersion", "version", "url", "iconUrl",
                           "skills", "capabilities", "defaultInputModes", "defaultOutputModes"],
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
