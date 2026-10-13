"""Cross-encoder reranking: the second, more careful pass over the search results.

Embedding search compares two vectors that were computed *separately*, so the model never
sees the query and the document together. A cross-encoder reads "query + chunk" as one input
and outputs a relevance score. That is far more accurate, but too slow to run on all 1,300
chunks, so we only rerank the top ~30 candidates from the fast search.
"""
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.rag.embeddings import CACHE_DIR
from app.rag.vector_store import SearchHit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model = TextCrossEncoder(model_name=model_name, cache_dir=CACHE_DIR)

    def rerank(self, query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
        if not hits:
            return []
        scores = list(self.model.rerank(query, [h.text for h in hits]))
        ranked = sorted(zip(hits, scores), key=lambda pair: pair[1], reverse=True)
        return [h.model_copy(update={"score": float(s)}) for h, s in ranked[:top_k]]


@lru_cache
def get_reranker() -> Reranker:
    return CrossEncoderReranker(get_settings().reranker_model)
