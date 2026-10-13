"""Turn text into vectors with FastEmbed (ONNX on the CPU, keeps the GPU free for the local LLM).

Two kinds of vectors:
  - dense  (bge-small): 384 numbers capturing *meaning*; "pod keeps restarting" ~ "CrashLoopBackOff"
  - sparse (BM25):      one weight per *word* that appears; exact terms like "fsync" or "quorum"
"""
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

CACHE_DIR = ".cache/fastembed"  # keep models in the project, not in %TEMP% (Windows may clean that up)

# BGE models retrieve better when *queries* (not documents) carry this instruction.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class SparseEmbedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[tuple[list[int], list[float]]]: ...
    def embed_query(self, text: str) -> tuple[list[int], list[float]]: ...


class FastEmbedder:
    def __init__(self, model_name: str, batch_size: int = 64):
        from fastembed import TextEmbedding  # imported lazily: loading the model takes a few seconds

        self.model_name = model_name
        self.model = TextEmbedding(model_name=model_name, cache_dir=CACHE_DIR)
        self.batch_size = batch_size
        self.query_prefix = BGE_QUERY_PREFIX if "bge" in model_name.lower() and "-en" in model_name else ""
        self.dim = len(next(iter(self.model.embed(["probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self.model.embed(texts, batch_size=self.batch_size)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self.model.embed([self.query_prefix + text]))).tolist()


class FastSparseEmbedder:
    """BM25 term weights. The IDF part (how rare a word is) is computed by Qdrant at search time."""

    def __init__(self, model_name: str):
        from fastembed import SparseTextEmbedding

        self.model = SparseTextEmbedding(model_name=model_name, cache_dir=CACHE_DIR)

    def embed_documents(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        return [(v.indices.tolist(), v.values.tolist()) for v in self.model.embed(texts)]

    def embed_query(self, text: str) -> tuple[list[int], list[float]]:
        v = next(iter(self.model.query_embed(text)))
        return v.indices.tolist(), v.values.tolist()


@lru_cache
def get_embedder() -> Embedder:
    return FastEmbedder(get_settings().embedding_model)


@lru_cache
def get_sparse_embedder() -> SparseEmbedder:
    return FastSparseEmbedder(get_settings().sparse_model)
