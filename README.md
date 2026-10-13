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
python -m app.rag.index                            # chunk + embed (bge-small, CPU) + store in Qdrant
python -m eval.retrieval_eval --name dense_baseline
```

## Results so far

Ticket -> runbook retrieval on 212 synthetic tickets (search over 108 runbooks):

| Method | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR | p50 latency |
|---|---|---|---|---|---|---|
| Dense (bge-small-en-v1.5) | 0.481 | 0.689 | 0.764 | 0.840 | 0.608 | 60 ms |

Most errors are confusions between sibling alerts (e.g. `etcdInsufficientMembers` vs `etcdNoLeader`),
where the distinguishing signal is a specific technical term. Hypothesis for Step 5: keyword (BM25)
search and a cross-encoder reranker will fix many of these.

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
- [ ] Step 5: Hybrid retrieval and reranking
- [ ] Step 6: `/ask` endpoint with citations
- [ ] Step 7: LangGraph agent with a verification step
- [ ] Step 8: UI, auth, observability
- [ ] Step 9: Evaluation (RAGAS) and ablation studies
- [ ] Step 10: Docker, CI, deployment
