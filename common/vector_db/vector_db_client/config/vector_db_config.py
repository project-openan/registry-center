from enum import Enum

from common.llm.config.config_reader import read_config_as_json


class VectorDBType(Enum):
    Milvus = 'milvus'

def convert_vectordb_type(vectordb_type:str)->VectorDBType:
    for member in VectorDBType:
        if member.value == vectordb_type:
            return member
    return VectorDBType.Milvus

class VectorDBConfig:
    vectordb_type:VectorDBType
    description:str
    uri:str
    version:str

    def __init__(self,vectordb_type:str,config:dict):
        self.vectordb_type = convert_vectordb_type(vectordb_type)
        self.description = config['description']
        self.uri = config['uri']
        self.version = config['version']

def get_vectordb_config() -> {str, VectorDBConfig}:
    config: dict[str,dict] = read_config_as_json("../../../config/vectordb_config.json")
    vectordb_config_item = {}
    for key, value_list in config.items():
        vectordb_config_item[key] = VectorDBConfig(key, value_list)
    return vectordb_config_item

vectordb_config = get_vectordb_config()

def get_vectordb_config_by_type(vectordb_type: VectorDBType) -> VectorDBConfig:
    return vectordb_config[vectordb_type.value] if vectordb_type.value in vectordb_config else None