"""Store and search chunks in Qdrant."""
import uuid
from functools import lru_cache

from pydantic import BaseModel
from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.rag.chunking import Chunk
from app.rag.embeddings import Embedder

DENSE = "dense"  # named vector; Step 5 adds a sparse "bm25" vector next to it
FILTERABLE_FIELDS = ["source_type", "doc_id", "metadata.service", "metadata.component", "metadata.system"]


class SearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    score: float
    source_type: str
    title: str
    section: str | None
    source: str
    text: str
    metadata: dict


class VectorStore:
    def __init__(self, client: QdrantClient, collection: str, embedder: Embedder):
        self.client = client
        self.collection = collection
        self.embedder = embedder

    def recreate(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            self.collection,
            vectors_config={DENSE: models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE)},
        )
        if not self.is_embedded:  # payload indexes make filtered search fast (server mode only)
            for field in FILTERABLE_FIELDS:
                self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)

    @property
    def is_embedded(self) -> bool:
        return type(self.client._client).__name__ == "QdrantLocal"

    def close(self) -> None:
        self.client.close()

    def upsert(self, chunks: list[Chunk], batch_size: int = 128) -> None:
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            vectors = self.embedder.embed_documents([c.text for c in batch])
            self.client.upsert(self.collection, points=[
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, c.chunk_id)),  # Qdrant ids must be UUIDs or ints
                    vector={DENSE: v},
                    payload=c.model_dump(),
                )
                for c, v in zip(batch, vectors)
            ])

    def search(self, query: str, top_k: int = 5, source_types: list[str] | None = None,
               service: str | None = None) -> list[SearchHit]:
        conditions = []
        if source_types:
            conditions.append(models.FieldCondition(key="source_type", match=models.MatchAny(any=source_types)))
        if service:
            conditions.append(models.FieldCondition(key="metadata.service", match=models.MatchValue(value=service)))

        result = self.client.query_points(
            self.collection,
            query=self.embedder.embed_query(query),
            using=DENSE,
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=top_k,
            with_payload=True,
        )
        return [SearchHit(score=p.score, **{k: p.payload[k] for k in SearchHit.model_fields if k != "score"})
                for p in result.points]

    def count(self) -> int:
        return self.client.count(self.collection).count if self.client.collection_exists(self.collection) else 0


@lru_cache
def get_vector_store() -> VectorStore:
    from app.rag.embeddings import get_embedder

    s = get_settings()
    client = QdrantClient(path=s.qdrant_path) if s.qdrant_path else QdrantClient(url=s.qdrant_url)
    return VectorStore(client, s.qdrant_collection, get_embedder())
