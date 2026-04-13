from sentence_transformers import SentenceTransformer
from common.vector_db.embedding_model.config.embedding_config import EmbeddingType
from common.vector_db.embedding_model.config.embedding_tool import EmbeddingTool
from common.vector_db.embedding_model.config.embedding_tool_registry import embedding_tool_register


@embedding_tool_register(EmbeddingType.BGE_EMBEDDING)
class BgeLargeEmbeddingTool(EmbeddingTool):
    def __init__(self,config:dict):
        super().__init__(config)
        client_uri = config["uri"]
        self.client = SentenceTransformer(client_uri)

    def get_embedding_vector(self,context:str):
        sentences = [context]
        embeddings = self.client.encode(sentences,normalize_encoding=True)
        return embeddings.tolist()