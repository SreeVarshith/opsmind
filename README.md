# OpsMind

An agentic RAG copilot for IT incident resolution. Paste an alert or an error log, and OpsMind returns the likely root cause, similar past incidents and fix steps, with a citation for every claim.

## Quick start (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Then open http://localhost:8000/docs.

## Data

```bash
python scripts/download_data.py          # public runbooks, postmortems and logs (~3 MB)
python -m scripts.generate_tickets       # synthetic tickets via the free Groq API (resumable)
python -m app.ingestion.pipeline         # -> data/processed/documents.jsonl
```

| Source | What it is | Documents |
|---|---|---|
| [prometheus-operator/runbooks](https://github.com/prometheus-operator/runbooks) | Real on-call runbooks for Kubernetes alerts | 108 |
| [danluu/post-mortems](https://github.com/danluu/post-mortems) | Public incident postmortems from real companies | 239 |
| [logpai/loghub](https://github.com/logpai/loghub) | Logs from 8 systems, grouped by event template | 408 |
| Synthetic tickets | LLM-written tickets, each linked to the runbook it came from (evaluation labels) | ~216 |

## Search index

```bash
docker compose -f infra/docker-compose.yml up -d   # Qdrant server (or set QDRANT_PATH in .env for no-Docker mode)
python -m app.rag.index                            # chunk + embed (dense bge-small + sparse BM25) into Qdrant
python -m eval.retrieval_eval --ablation           # benchmark every retrieval configuration
```

## Results so far

Ticket -> runbook retrieval on 212 synthetic tickets (search over 108 runbooks, CPU only, embedded Qdrant):

| Method | R@1 | R@3 | R@5 | R@10 | MRR | p50 latency |
|---|---|---|---|---|---|---|
| Dense (bge-small-en-v1.5) | **0.481** | 0.689 | 0.764 | 0.840 | 0.608 | 51 ms |
| Sparse (BM25) | 0.311 | 0.585 | 0.731 | 0.854 | 0.488 | 61 ms |
| **Hybrid (dense + BM25, RRF)** | 0.467 | **0.717** | **0.802** | **0.915** | **0.614** | 119 ms |
| Dense + MiniLM reranker | 0.387 | 0.618 | 0.741 | 0.835 | 0.538 | 4963 ms |
| Hybrid + MiniLM reranker | 0.382 | 0.623 | 0.750 | 0.854 | 0.539 | 5198 ms |

Findings:
1. **Hybrid search is the best default.** BM25 alone is weak at the top, but it finds different correct
   runbooks than dense search, so fusing them lifts Recall@10 from 0.840 to 0.915.
2. **A general-purpose reranker hurts.** `ms-marco-MiniLM-L-6-v2` (trained on web search) lowered MRR
   from 0.614 to 0.539 and pushed 39 correct #1 results down, while adding ~5 s per query on CPU.
   Domain mismatch: it was never trained on logs and Kubernetes terminology. Reranking is therefore
   off by default (`RERANK=false`).
3. The remaining errors are mostly sibling alerts (e.g. `etcdInsufficientMembers` vs `etcdNoLeader`).

## Project layout

```
app/
  api/routes/   FastAPI endpoints
  core/         config, logging
  ingestion/    parsers for runbooks, tickets and logs
  rag/          chunking, embeddings, retrieval, reranking
  agents/       LangGraph incident-resolution agent
  llm/          LLM provider router (Ollama / Groq)
data/           raw and processed datasets (only tickets are committed)
scripts/        data download, ticket generation, LLM comparison
eval/           evaluation sets and benchmark scripts
infra/          docker-compose and monitoring config
tests/          pytest tests
```

## Roadmap

- [x] Step 1: Project setup and FastAPI skeleton
- [x] Step 2: LLM router (Ollama + Groq, with automatic fallback)
- [x] Step 3: Data collection and ingestion
- [x] Step 4: Embeddings and Qdrant vector store
- [x] Step 5: Hybrid retrieval and reranking
- [ ] Step 6: `/ask` endpoint with citations
- [ ] Step 7: LangGraph agent with a verification step
- [ ] Step 8: UI, auth, observability
- [ ] Step 9: Evaluation (RAGAS) and ablation studies
- [ ] Step 10: Docker, CI, deployment
