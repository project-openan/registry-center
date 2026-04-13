from enum import Enum

from common.llm.config.config_reader import read_config_as_json


class EmbeddingType(Enum):
    BGELargeZH = "bge-large-zh-v1.5"


def convert_embedding_type(embedding_type: str) -> EmbeddingType:
    for member in EmbeddingType:
        if member.value == embedding_type:
            return member
    return EmbeddingType.BGELargeZH


class EmbeddingConfig:
    embedding_type: EmbeddingType
    description: str
    uri: str
    version:str

    def __init__(self,embedding_type: str, config:dict):
       self.embedding_type = convert_embedding_type(embedding_type)
       self.description = config["description"]
       self.uri = config["uri"]
       self.version = config["version"]

def get_embedding_config() -> {str,EmbeddingConfig}:
    config: dict[str,dict] = read_config_as_json("../../../config/embedding_config.json.json")
    embedding_config_item = {}
    for key, value_list in config.items():
        embedding_config_item[key] = EmbeddingConfig(key,value_list)
    return embedding_config_item

embedding_config = get_embedding_config()

def get_embedding_config_by_type(embedding_type: EmbeddingType) -> EmbeddingConfig:
    return embedding_config[embedding_type.value] if embedding_type.value in embedding_config else None