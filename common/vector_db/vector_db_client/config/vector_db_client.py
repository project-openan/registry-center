from abc import ABC, abstractmethod

class VectorDBClient(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def create_collection(self,data):
        pass

    @abstractmethod
    def insert_entity(self,data):
        pass

    @abstractmethod
    def delete_entity(self,data):
        pass

    @abstractmethod
    def update_entity(self,data):
        pass

    @abstractmethod
    def retrieve_entity(self,data):
        pass