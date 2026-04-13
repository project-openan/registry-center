from common.vector_db.vector_db_client.config.vector_db_client import VectorDBClient
from common.vector_db.vector_db_client.config.vector_db_config import VectorDBType, VectorDBConfig


def vectordb_tool_register(keys):
    def decorator(cls):
        if isinstance(keys,list):
            for key in keys:
                VECTORDB_REGISTRY.register(key,cls)
        else:
            VECTORDB_REGISTRY.register(keys,cls)
        return cls

    return decorator

class VectorDBToolRegistry:
    def __init__(self):
        self.providers = {}

    def register(self,key,provider_cls):
        self.providers[key] = provider_cls

    def get_provider(self,vector_type:VectorDBType):
        return self.providers[vector_type]

VECTORDB_REGISTRY = VectorDBToolRegistry()

vectordb_tool_instance = {str:VectorDBClient}

def create_vectordb_tool_instance(config:VectorDBConfig):
    return VECTORDB_REGISTRY.get_provider(config.vectordb_type)(config.__dict__)

def get_or_create_vectordb_tool_instance(config:VectorDBConfig) -> VectorDBClient:
    if config.vectordb_type in vectordb_tool_instance:
        return vectordb_tool_instance[config.vectordb_type]
    else:
        vectordb_tool = create_vectordb_tool_instance(config)
        vectordb_tool_instance[config.vectordb_type] = vectordb_tool
        return vectordb_tool