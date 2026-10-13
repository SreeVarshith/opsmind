"""The full retrieval pipeline the rest of the app uses:

    query -> normalize -> search (dense / sparse / hybrid) -> rerank (optional) -> top_k hits
"""
from functools import lru_cache

from app.core.config import get_settings
from app.ingestion.text import normalize_text
from app.rag.reranker import Reranker
from app.rag.vector_store import SearchHit, SearchMode, VectorStore


class Retriever:
    def __init__(self, store: VectorStore, reranker: Reranker | None, mode: SearchMode = "hybrid",
                 rerank: bool = True, rerank_candidates: int = 30):
        self.store = store
        self.reranker = reranker
        self.mode = mode
        self.rerank = rerank
        self.rerank_candidates = rerank_candidates

    def retrieve(self, query: str, top_k: int = 5, source_types: list[str] | None = None,
                 service: str | None = None, mode: SearchMode | None = None,
                 rerank: bool | None = None) -> list[SearchHit]:
        query = normalize_text(query)
        mode = mode or self.mode
        use_rerank = (self.rerank if rerank is None else rerank) and self.reranker is not None

        fetch = max(top_k, self.rerank_candidates) if use_rerank else top_k
        hits = self.store.search(query, fetch, source_types, service, mode=mode)
        return self.reranker.rerank(query, hits, top_k) if use_rerank else hits


@lru_cache
def get_retriever() -> Retriever:
    from app.rag.reranker import get_reranker
    from app.rag.vector_store import get_vector_store

    s = get_settings()
    return Retriever(get_vector_store(), get_reranker() if s.rerank else None, s.retrieval_mode,
                     s.rerank, s.rerank_candidates)
