"""Store and search chunks in Qdrant, with dense, sparse (BM25) or hybrid search."""
import uuid
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel
from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.rag.access import access_level
from app.rag.chunking import Chunk
from app.rag.embeddings import Embedder, SparseEmbedder

DENSE = "dense"
SPARSE = "bm25"
FILTERABLE_FIELDS = ["source_type", "access", "doc_id", "metadata.service", "metadata.component", "metadata.system"]

SearchMode = Literal["dense", "sparse", "hybrid"]


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
    def __init__(self, client: QdrantClient, collection: str, embedder: Embedder,
                 sparse_embedder: SparseEmbedder | None = None):
        self.client = client
        self.collection = collection
        self.embedder = embedder
        self.sparse_embedder = sparse_embedder

    def recreate(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            self.collection,
            vectors_config={DENSE: models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE)},
            # Modifier.IDF: Qdrant computes how rare each word is across the whole collection,
            # which completes the BM25 formula (rare words like "fsync" count more than "pod").
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)}
            if self.sparse_embedder else None,
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
            texts = [c.text for c in batch]
            dense = self.embedder.embed_documents(texts)
            sparse = self.sparse_embedder.embed_documents(texts) if self.sparse_embedder else [None] * len(batch)
            points = []
            for c, d, s in zip(batch, dense, sparse):
                vector = {DENSE: d}
                if s is not None:
                    vector[SPARSE] = models.SparseVector(indices=s[0], values=s[1])
                points.append(models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, c.chunk_id)),  # Qdrant ids must be UUIDs or ints
                    vector=vector,
                    payload={**c.model_dump(), "access": access_level(c)},
                ))
            self.client.upsert(self.collection, points=points)

    def search(self, query: str, top_k: int = 5, source_types: list[str] | None = None,
               service: str | None = None, mode: SearchMode = "dense",
               access: list[str] | None = None) -> list[SearchHit]:
        """`access`: access levels the user may see (None = no restriction, e.g. internal jobs)."""
        conditions = []
        if access is not None:
            conditions.append(models.FieldCondition(key="access", match=models.MatchAny(any=access)))
        if source_types:
            conditions.append(models.FieldCondition(key="source_type", match=models.MatchAny(any=source_types)))
        if service:
            conditions.append(models.FieldCondition(key="metadata.service", match=models.MatchValue(value=service)))
        query_filter = models.Filter(must=conditions) if conditions else None

        if mode != "dense" and not self.sparse_embedder:
            raise ValueError(f"mode '{mode}' needs a sparse embedder")

        if mode == "dense":
            result = self.client.query_points(self.collection, query=self.embedder.embed_query(query), using=DENSE,
                                              query_filter=query_filter, limit=top_k, with_payload=True)
        elif mode == "sparse":
            result = self.client.query_points(self.collection, query=self._sparse_query(query), using=SPARSE,
                                              query_filter=query_filter, limit=top_k, with_payload=True)
        else:
            # Hybrid: run both searches, then merge with Reciprocal Rank Fusion. RRF only looks at
            # *ranks* (score = sum of 1/(60 + rank)), so it needs no tuning to mix two score scales.
            candidates = max(top_k * 2, 20)
            result = self.client.query_points(
                self.collection,
                prefetch=[
                    models.Prefetch(query=self.embedder.embed_query(query), using=DENSE,
                                    filter=query_filter, limit=candidates),
                    models.Prefetch(query=self._sparse_query(query), using=SPARSE,
                                    filter=query_filter, limit=candidates),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        return [SearchHit(score=p.score, **{k: p.payload[k] for k in SearchHit.model_fields if k != "score"})
                for p in result.points]

    def _sparse_query(self, query: str) -> models.SparseVector:
        indices, values = self.sparse_embedder.embed_query(query)
        return models.SparseVector(indices=indices, values=values)

    def count(self) -> int:
        return self.client.count(self.collection).count if self.client.collection_exists(self.collection) else 0


@lru_cache
def get_vector_store() -> VectorStore:
    from app.rag.embeddings import get_embedder, get_sparse_embedder

    s = get_settings()
    client = QdrantClient(path=s.qdrant_path) if s.qdrant_path else QdrantClient(url=s.qdrant_url)
    return VectorStore(client, s.qdrant_collection, get_embedder(), get_sparse_embedder())
