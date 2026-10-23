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

## Asking questions

```bash
uvicorn app.main:app --reload
python scripts/ask.py "etcd cluster reports no leader and kubectl commands time out"
python scripts/ask.py "Pods keep restarting with OOMKilled" --provider ollama
```

`POST /ask` retrieves a balanced set of sources (3 runbooks, 2 tickets, 1 postmortem), numbers
them [1]..[6], asks the LLM to answer only from them with inline citations, and checks the result:

- `invalid_citations`: numbers cited that were never provided (hallucinated sources)
- `grounded`: at least one real citation and no invalid ones
- `citation_coverage`: share of answer sentences that carry a citation

Early observations (9 Groq answers, 3 questions): no invalid citations, but mean citation coverage
is only 57% (range 15-100%), so roughly 4 in 10 sentences are not traceable to a source. gpt-oss
also often cites in its native `【1†L1-L4】` style, which is normalized to `[1]`.

## Incident agent (`POST /agent/ask`)

A LangGraph workflow that answers carefully instead of in one shot:

```
analyze -> retrieve -> generate -> verify --(>= 70% of claims supported?)--> finalize
                         ^                  |
                         +---- revise <-----+   (at most once)
```

| Step | What it does | Model (Groq) |
|---|---|---|
| analyze | Classifies the incident and writes a runbook-style search query | gpt-oss-20b |
| retrieve | Balanced sources for question + search query | - |
| generate / revise | Cited answer; on revision, gets the list of unsupported claims | gpt-oss-120b |
| verify | Labels every claim supported / partial / unsupported against the sources | gpt-oss-20b |
| finalize | Confidence (high / medium / low), flags unsupported statements | - |

Using two models doubles the free Groq budget (each model has its own 8,000 tokens/minute).

First comparison on 3 questions (Groq):

| Question | /ask coverage | /agent coverage | Agent support | Revisions | Agent time |
|---|---|---|---|---|---|
| Pods OOMKilled | 40% | 100% | 88% (draft: 62%) | 1 | 7.8 s |
| etcd no leader | 53% | 69% | 100% | 0 | 5.4 s |
| Prometheus not sending alerts | 73% | 27% | 91% | 0 | 4.7 s |

- The triage query found the exact runbook `PrometheusErrorSendingAlertsToAnyAlertmanager` for question 3.
- The revision loop lifted support from 62% to 88% on question 1.
- The verifier is imperfect: it marked "`kubectl describe pod` to confirm OOMKilled" as unsupported
  although a retrieved runbook says it (the writer had cited the wrong source). Verifier accuracy
  against human labels is measured in Step 9.

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
- [x] Step 6: `/ask` endpoint with citations
- [x] Step 7: LangGraph agent with a verification step
- [ ] Step 8: UI, auth, observability
- [ ] Step 9: Evaluation (RAGAS) and ablation studies
- [ ] Step 10: Docker, CI, deployment
