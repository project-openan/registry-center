from abc import ABC

from common.vector_db.embedding_model.config.embedding_config import EmbeddingType, EmbeddingConfig


def embedding_tool_register(keys):
    def decorator(cls):
        if isinstance(keys, list):
            for key in keys:
                EMBEDDING_TOOL_REGISTRY.register(key,cls)
        else:
            EMBEDDING_TOOL_REGISTRY.register(key,cls)
        return cls

    return decorator

class EmbeddingToolRegistry:
    def __init__(self):
        self.providers = {}

    def register(self,key,provider_cls):
        self.providers[key] = provider_cls

    def get_provider(self,embedding_type: EmbeddingType):
        return self.providers[embedding_type]

EMBEDDING_TOOL_REGISTRY = EmbeddingToolRegistry()

embedding_tool_instance = {}

def create_embedding_tool_instance(config:EmbeddingConfig):
    return EMBEDDING_TOOL_REGISTRY.get_provider(config.embedding_type)(config.__dict__)