"""Turn text into vectors with FastEmbed (ONNX on the CPU, keeps the GPU free for the local LLM)."""
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

# BGE models retrieve better when *queries* (not documents) carry this instruction.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    def __init__(self, model_name: str, batch_size: int = 64):
        from fastembed import TextEmbedding  # imported lazily: loading the model takes a few seconds

        self.model_name = model_name
        # Keep the downloaded model in the project, not in %TEMP% (Windows may clean that up).
        self.model = TextEmbedding(model_name=model_name, cache_dir=".cache/fastembed")
        self.batch_size = batch_size
        self.query_prefix = BGE_QUERY_PREFIX if "bge" in model_name.lower() and "-en" in model_name else ""
        self.dim = len(next(iter(self.model.embed(["probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self.model.embed(texts, batch_size=self.batch_size)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self.model.embed([self.query_prefix + text]))).tolist()


@lru_cache
def get_embedder() -> Embedder:
    return FastEmbedder(get_settings().embedding_model)
