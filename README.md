# OpsMind

[![CI](https://github.com/SreeVarshith/opsmind/actions/workflows/ci.yml/badge.svg)](https://github.com/SreeVarshith/opsmind/actions/workflows/ci.yml)

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
  although a retrieved runbook says it (the writer had cited the wrong source). Step 9 audits the
  verifier against a second model (kappa 0.48); human validation is future work.

## Answer evaluation (Step 9)

```bash
python -m eval.answer_eval --config all --n 40     # resumable; free-tier paced
python -m eval.answer_report                       # tables -> eval/results/answer_eval_report.md
streamlit run eval/progress_app.py                 # live progress while it runs
```

40 synthetic tickets per configuration (seed 42). The ticket being asked about is hidden from search
(otherwise the answer leaks). Judge: `qwen3.8-27b` (different family from the gpt-oss writers), reasoning
off, score 4-5 = correct. Ranges are 95% bootstrap confidence intervals.

| Configuration | Correct | Mean score | Runbook found | Runbook cited | Cited sentences | Median time |
|---|---|---|---|---|---|---|
| Fast · gpt-oss-120b (Groq) | 40% (25-55%) | 3.30 | 75% | 70% | 47% | 2.1 s |
| Agent · gpt-oss-120b + 20b checks | 42% (28-57%) | 3.20 | 78% | 62% | 66% | 8.6 s |
| Fast · Llama 3.2 3B (local, 4 GB GPU) | 18% (8-30%) | 2.35 | 75% | 28% | 32% | 37.0 s |

Findings:
1. **Model size dominates.** Retrieval is identical (75% runbook found), yet 120B beats 3B on 27 of 40
   questions (1 loss). The 3B model gave 9 wrong answers (score 1); 120B gave none.
2. **The agent improves traceability, not correctness.** Cited sentences rise from 47% to 66%, but
   accuracy is unchanged (42% vs 40%, overlapping intervals) at 4x the latency. Paired: 5 better, 26 same,
   9 worse. The loss comes from the revision step: on the 26 revised answers the mean score drops
   3.38 -> 3.19, on unrevised ones it is flat (3.14 -> 3.21); 8 of the 9 losses were revised. Rewriting to
   satisfy the fact-checker removes correct operational advice that the sources do not state verbatim.
3. **The bottleneck is diagnosis, not retrieval.** The right runbook is retrieved 75% of the time but
   only ~40% of answers name the specific root cause. Runbooks list several possible causes; the judge
   comments show answers often pick a plausible but wrong one.
4. **Zero hallucinated citation numbers** in all 120 answers.

Limitations: 40 questions per configuration; tickets are synthetic and written by gpt-oss-20b (same
family as the writers); the LLM judge is not yet validated against human labels; single run per
configuration. The local model ran on a 4 GB laptop GPU that intermittently dropped to a low-power
clock, so its latency is pessimistic.

Fact-checker audit: 50 claims (25 flagged) were labelled independently by a second model (Qwen).
Agreement with the verifier: 74% on supported-vs-flagged (Cohen's kappa 0.48, moderate) and 54% on
three classes (kappa 0.28); the two models never agreed on a "partial" claim. This is model-vs-model
agreement, not human validation; the human labelling tool below is ready for that.

Full write-up: [docs/REPORT.md](docs/REPORT.md).

```bash
streamlit run eval/label_app.py        # label claims; the verifier's verdict is hidden
python -m eval.verifier_audit score    # agreement, confusion matrix, Cohen's kappa
```

## Web UI, login and monitoring

```bash
python -m scripts.create_user --demo        # demo users; passwords go to config/DEMO_CREDENTIALS.local.txt
uvicorn app.main:app                        # API on :8000
streamlit run ui/streamlit_app.py           # UI on http://localhost:8501
```

- **Login:** `POST /auth/login` returns a signed JWT (8-hour shift). Passwords are stored only as salted
  PBKDF2-SHA256 hashes in a git-ignored `config/users.json`.
- **Roles and document access:** every chunk is labelled `public` or `restricted` (etcd and control-plane
  runbooks, 69 chunks). Search filters on that label inside Qdrant, so restricted runbooks never reach
  the LLM for a `developer`. `admin` and `sre` see everything and can open monitoring.
- **Query log:** every `/ask` and `/agent/ask` call is stored in SQLite (user, model, confidence,
  support rate, latency, errors); `GET /metrics/summary` and the Monitoring page summarize it.

| Role | Restricted runbooks | Monitoring | Raw documents |
|---|---|---|---|
| admin, sre | yes | yes | yes |
| developer | no | no | no |

## Run everything with Docker

```bash
copy .env.example .env                                                     # then add your free Groq key as API_KEY
python -m scripts.create_user --demo                                       # users + JWT secret (needs the Python setup above)
docker compose -f infra/docker-compose.yml --profile setup run --rm indexer   # once: download data, build the index (~5 min)
docker compose -f infra/docker-compose.yml --profile app up -d --build     # start: UI on http://localhost:8501
docker compose -f infra/docker-compose.yml --profile app down              # stop (data is kept)
```

The image runs as a non-root user and contains no secrets (`.env` and `config/` are excluded); the search
models are baked in. Ports are published on 127.0.0.1 only, and the UI container gets no API keys. Ollama stays
on the host for GPU access and is reached through `host.docker.internal`. On this machine, Docker Desktop 4.34
leaves a stale socket when it closes, so start it with `scripts/start_docker.ps1`.

GitHub Actions (`.github/workflows/ci.yml`) runs lint, the tests (no API key, GPU or Docker needed) and an image
build on every push and pull request.

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
ui/             Streamlit web UI
config/         local users and demo credentials (git-ignored)
```

## Roadmap

- [x] Step 1: Project setup and FastAPI skeleton
- [x] Step 2: LLM router (Ollama + Groq, with automatic fallback)
- [x] Step 3: Data collection and ingestion
- [x] Step 4: Embeddings and Qdrant vector store
- [x] Step 5: Hybrid retrieval and reranking
- [x] Step 6: `/ask` endpoint with citations
- [x] Step 7: LangGraph agent with a verification step
- [x] Step 8: UI, auth, observability
- [x] Step 9: Evaluation, ablation studies and report ([docs/REPORT.md](docs/REPORT.md))
- [ ] Step 10: Docker and CI done; GitHub publication and deployment pending

## License

Code: [MIT](LICENSE). The downloaded runbooks, postmortems and logs belong to their original projects
(linked under Data), and excerpts of them appear in `eval/results/` and `eval/labels/`.
