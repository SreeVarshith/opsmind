"""Build the search index: documents.jsonl -> chunks -> embeddings -> Qdrant.

    python -m app.rag.index
"""
import time
from collections import Counter

from app.ingestion.pipeline import read_jsonl
from app.rag.chunking import chunk_documents
from app.rag.vector_store import get_vector_store


def main() -> None:
    docs = read_jsonl()
    chunks = chunk_documents(docs)
    print(f"{len(docs)} documents -> {len(chunks)} chunks")
    print("  chunks per type:", dict(Counter(c.source_type for c in chunks)))

    start = time.perf_counter()
    store = get_vector_store()
    print(f"Embedding model loaded ({store.embedder.dim} dimensions) in {time.perf_counter() - start:.1f}s")

    start = time.perf_counter()
    store.recreate()
    store.upsert(chunks)
    mode = "embedded" if store.is_embedded else "server"
    print(f"Indexed {store.count()} chunks into Qdrant ({mode} mode) in {time.perf_counter() - start:.1f}s")
    store.close()


if __name__ == "__main__":
    main()
