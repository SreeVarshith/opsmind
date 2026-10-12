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

## Project layout

```
app/
  api/routes/   FastAPI endpoints
  core/         config, logging
  ingestion/    parsers for runbooks, tickets and logs
  rag/          chunking, embeddings, retrieval, reranking
  agents/       LangGraph incident-resolution agent
  llm/          LLM provider router (Ollama / Claude)
data/           raw and processed datasets (not committed)
eval/           evaluation sets and benchmark scripts
infra/          docker-compose and monitoring config
tests/          pytest tests
```

## Roadmap

- [x] Step 1: Project setup and FastAPI skeleton
- [ ] Step 2: LLM router (Ollama + Claude)
- [ ] Step 3: Data collection and ingestion
- [ ] Step 4: Embeddings and Qdrant vector store
- [ ] Step 5: Hybrid retrieval and reranking
- [ ] Step 6: `/ask` endpoint with citations
- [ ] Step 7: LangGraph agent with a verification step
- [ ] Step 8: UI, auth, observability
- [ ] Step 9: Evaluation (RAGAS) and ablation studies
- [ ] Step 10: Docker, CI, deployment
