from abc import ABC, abstractmethod


class EmbeddingTool(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def get_embedding_vector(self,context:str):
        pass