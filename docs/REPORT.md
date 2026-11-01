# OpsMind: Evaluating Retrieval, Verification and Model Size in an Incident-Resolution RAG Assistant

*Technical report, October 2026. Code and data: this repository.*

## Abstract

On-call engineers lose time searching runbooks, past tickets and postmortems during outages. We built
OpsMind, an incident-resolution assistant that retrieves from 971 IT-operations documents and answers
with numbered citations, and we evaluated three design questions on a labelled benchmark of synthetic
incident tickets. (1) **Retrieval:** hybrid dense + BM25 search with Reciprocal Rank Fusion gives the best
ranking (MRR 0.614, Recall@10 0.915), while an off-the-shelf MS MARCO cross-encoder reranker *lowers*
quality (MRR 0.539) and adds ~5 s per query. (2) **Model size:** with identical retrieval, a 120B open
model answers correctly 40% of the time versus 18% for a local 3B model, winning 27 of 40 paired
comparisons. (3) **Self-verification:** an agent that fact-checks each sentence and revises the answer
raises the share of cited sentences from 47% to 66% but does not improve correctness (42% vs 40%) and is
4x slower; revised answers score lower than their unrevised counterparts. A cross-model audit shows the
sentence-level fact-checker agrees only moderately with a second model (binary Cohen's kappa 0.48),
suggesting over-strict verification removes correct advice. No configuration produced a hallucinated
citation number in 120 answers.

## 1. Problem

During an incident, the knowledge needed to fix it usually exists but is scattered: runbooks, previous
tickets, postmortems and log patterns. A useful assistant must (a) find the right document from a
symptom description, (b) turn it into concrete steps, and (c) show where each step comes from so an
engineer can trust it. We ask which design choices actually improve (a)-(c), measured, not assumed.

## 2. System

| Layer | Implementation |
|---|---|
| API | FastAPI; JWT login, roles (admin / sre / developer), SQLite query log |
| Knowledge base | 108 Prometheus-Operator runbooks, 239 public postmortems, 408 Loghub log-event templates, 216 synthetic tickets = 971 documents, 1,299 chunks |
| Chunking | Runbooks split by section (Meaning / Impact / Diagnosis / Mitigation); every chunk carries a context header |
| Retrieval | Qdrant; dense `bge-small-en-v1.5` + sparse BM25 (IDF in Qdrant), fused with RRF; CPU only |
| Access control | 69 control-plane chunks labelled `restricted` and filtered inside Qdrant for the `developer` role |
| Answering (`/ask`) | Balanced sources (3 runbooks, 2 tickets, 1 postmortem), numbered [1]-[6]; citation checks |
| Agent (`/agent/ask`) | LangGraph: triage -> retrieve -> draft -> sentence-level verification -> one revision if < 70% supported -> confidence |
| Models | gpt-oss-120b (writer) and gpt-oss-20b (triage, verifier) on Groq free tier; Llama 3.2 3B via Ollama on a 4 GB RTX 3050 laptop GPU |

## 3. Benchmark

**Tickets.** Real tickets are private, so gpt-oss-20b wrote two realistic tickets per runbook (216 total),
instructed to describe symptoms without naming the alert. Each ticket stores the runbook it came from,
its root cause and its resolution, giving free labels for retrieval and answer evaluation. Four tickets
that leak the alert name were excluded.

**Leakage control.** For answer evaluation, the ticket being asked about is hidden from search; its
sibling ticket (same runbook) remains, as a legitimate "similar past incident".

**Judge.** `qwen3.8-27b` (a different model family from the gpt-oss writers, to limit self-preference)
scores each answer 1-5 against the ticket's real root cause and fix; 4-5 counts as correct. All 120
answers were judged with the same setting (reasoning disabled). Intervals are 95% bootstrap CIs.

## 4. Results

### 4.1 Retrieval (212 tickets, search over 108 runbooks)

| Method | R@1 | R@3 | R@5 | R@10 | MRR | p50 latency |
|---|---|---|---|---|---|---|
| Dense (bge-small) | **0.481** | 0.689 | 0.764 | 0.840 | 0.608 | 51 ms |
| Sparse (BM25) | 0.311 | 0.585 | 0.731 | 0.854 | 0.488 | 61 ms |
| **Hybrid (RRF)** | 0.467 | **0.717** | **0.802** | **0.915** | **0.614** | 119 ms |
| Dense + MiniLM reranker | 0.387 | 0.618 | 0.741 | 0.835 | 0.538 | 4,963 ms |
| Hybrid + MiniLM reranker | 0.382 | 0.623 | 0.750 | 0.854 | 0.539 | 5,198 ms |

BM25 is weak at the top but finds different correct runbooks than dense search, so fusion lifts
Recall@10 by 7.5 points. The general-purpose reranker (trained on web search) pushed 39 correct first-place
results down: a domain-transfer failure. Remaining errors are mostly sibling alerts
(e.g. `etcdInsufficientMembers` vs `etcdNoLeader`). On the Qdrant server (approximate HNSW index) hybrid
search reaches MRR 0.608 at 79 ms.

### 4.2 Answer quality (40 tickets per configuration)

| Configuration | Correct | Mean score | Runbook retrieved | Runbook cited | Cited sentences | Median time |
|---|---|---|---|---|---|---|
| Fast, gpt-oss-120b | 40% (25-55%) | 3.30 | 75% | 70% | 47% | 2.1 s |
| Agent, gpt-oss-120b + 20b checks | 42% (28-57%) | 3.20 | 78% | 62% | 66% | 8.6 s |
| Fast, Llama 3.2 3B (local) | 18% (8-30%) | 2.35 | 75% | 28% | 32% | 37.0 s |

| Score | 1 (wrong) | 2 | 3 | 4 | 5 (fully correct) |
|---|---|---|---|---|---|
| Fast, 120B | 0 | 11 | 13 | 9 | 7 |
| Agent, 120B | 1 | 11 | 11 | 13 | 4 |
| Fast, 3B local | 9 | 15 | 9 | 7 | 0 |

Paired on the same questions: 120B beats 3B on 27, ties 12, loses 1. Agent vs fast: agent better 5,
same 26, worse 9. Hallucinated citation numbers: 0 in all three configurations.

### 4.3 Where the agent loses

The agent revised 26 of 40 answers. On revised answers the mean score fell from 3.38 (fast) to 3.19
(agent); on unrevised answers it was flat (3.14 -> 3.21). Eight of the nine paired losses were revised
answers. Judge comments on these cases describe missing operational steps that the fast answer had,
for example "misses the critical operational step" and "provides generic troubleshooting steps".

### 4.4 Fact-checker audit (cross-model)

The agent's verifier (gpt-oss-20b) labelled 411 claims; 128 (31%) were flagged partial or unsupported.
We drew a stratified sample of 50 claims (25 flagged) and had a second model (Qwen 3.8 27B) label each
claim independently with the same instructions and full source text.

| Comparison | Agreement | Cohen's kappa |
|---|---|---|
| 3 classes (supported / partial / unsupported) | 54% | 0.28 (fair) |
| Binary (supported vs flagged) | 74% | 0.48 (moderate) |

The models never agreed on a single "partial" claim, and for 5 of the 25 claims the verifier flagged,
the second model judged them supported. For "unsupported" specifically, the verifier's flags had 45%
precision and 71% recall relative to the second model. Because the sample over-represents flagged
claims, these rates describe this sample, not the full population.

### 4.5 Ranked likely causes (follow-up experiment)

Because diagnosis was the weakest step, the answer format changed from one "likely cause" to up to three ranked
causes, each with its evidence and how to confirm it. The fast configuration was rerun on the same 40 tickets with
the same judge.

| Fast, gpt-oss-120b | Correct | Mean score | Score 5 | Score 4 | Score 1-2 | Median time |
|---|---|---|---|---|---|---|
| Original prompt | 40% (25-55%) | 3.30 | 7 | 9 | 11 | 2.1 s |
| Ranked causes | 48% (32-62%) | 3.20 | 2 | 17 | 11 | 2.6 s |

The result is inconclusive. More answers reached the "correct" threshold, but the mean score fell slightly, fully
correct answers dropped from 7 to 2, and on paired questions the ranked version was better on 6, the same on 23 and
worse on 11 (two-sided sign test on the 17 differing pairs, p = 0.33). Listing several causes may make answers easier
to act on while making each less specific, but this sample cannot show that. The feature stays because engineers can
rule causes out quickly, not because it was shown to raise accuracy. The same prompt update also added rules for
follow-ups and for ignoring instructions inside documents, and the rerun used an updated citation parser, so its
cited-sentence share (61%) is not directly comparable with the earlier 47%.

## 5. Discussion

1. **Fusion beats reranking in a specialised domain.** A cheap hybrid of meaning and keyword search
   beat a heavier neural reranker that was never trained on logs and Kubernetes terminology.
2. **Model capacity is the largest lever.** With retrieval held constant, moving from 3B to 120B more
   than doubled accuracy and eliminated wrong answers. On a 4 GB laptop GPU the local model was also
   ~18x slower than the free cloud API.
3. **Traceability and correctness are different targets.** Verification and revision made answers more
   citable but not more correct. The audit suggests why: a moderately reliable, somewhat over-strict
   verifier causes rewrites that delete correct advice the sources do not state verbatim. A verifier is
   only as useful as its precision; flagging (showing warnings) without forced rewriting may be the
   better default.
4. **Diagnosis, not retrieval, is now the bottleneck.** The right runbook is retrieved in ~75% of cases,
   yet only ~40% of answers name the specific root cause. Runbooks enumerate several causes; choosing
   the right one needs more evidence (logs, metrics, recent changes) than a symptom description gives.

## 6. Limitations

- 40 questions per configuration; confidence intervals are wide and differences under ~15 points are
  not statistically resolved.
- Tickets are synthetic and written by gpt-oss-20b, the same family as the writers, which may favour
  their phrasing.
- The answer judge and the verifier audit both use an LLM (Qwen). **No human labels were collected**;
  the audit measures agreement between two models, not correctness of either.
- One run per configuration; generation is stochastic.
- Features added after this evaluation (follow-up questions, document upload) were tested for correct behaviour,
  not for answer quality.
- The local model ran on a laptop GPU that intermittently dropped to a low-power clock, inflating its latency.

## 7. Future work

- Human validation of the judge and the verifier on a labelled sample (tooling is included:
  `eval/label_app.py`, `python -m eval.verifier_audit score`).
- Flag-only verification (no forced revision) and a more precise verifier, evaluated with the same benchmark.
- Domain-adapted reranking or fine-tuned embeddings for sibling-alert disambiguation.
- Adding live signals (logs, metrics, recent deploys) to move from "possible causes" to the actual cause.
- Real, anonymised incident tickets from an operations team.

## 8. Reproducing

```bash
python scripts/download_data.py && python -m scripts.generate_tickets && python -m app.ingestion.pipeline
docker compose -f infra/docker-compose.yml up -d && python -m app.rag.index
python -m eval.retrieval_eval --ablation
python -m eval.answer_eval --config all --n 40 && python -m eval.answer_report
python -m eval.verifier_audit sample && python -m eval.verifier_audit crosscheck
python -m eval.verifier_audit score crosscheck
```

Raw results: `eval/results/` (retrieval runs, 120 judged answers with sources, verifier sample).
