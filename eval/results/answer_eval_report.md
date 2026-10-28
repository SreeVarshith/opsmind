# Answer evaluation

Questions: 40 synthetic tickets (seed 42), own ticket hidden from search. Judge: qwen3.8-27b, score 4-5 = correct. Ranges are 95% bootstrap confidence intervals.

| Configuration | n | Correct | Mean score | Runbook found | Runbook cited | Cited sentences | Verified (agent) | Median time | p95 time |
|---|---|---|---|---|---|---|---|---|---|
| Fast · gpt-oss-120b | 40 | 40% (25%-55%) | 3.30 | 75% (60%-88%) | 70% (55%-82%) | 47% | - | 2.1 s | 2.9 s |
| Agent · gpt-oss-120b (+20b checks) | 40 | 42% (28%-57%) | 3.20 | 78% (65%-90%) | 62% (48%-78%) | 66% | 69% | 8.6 s | 25.3 s |
| Fast · Llama 3.2 3B (local) | 40 | 18% (8%-30%) | 2.35 | 75% (60%-88%) | 28% (15%-42%) | 32% | - | 37.0 s | 91.3 s |

Score distribution (1 = wrong ... 5 = fully correct):

| Configuration | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Fast · gpt-oss-120b | 0 | 11 | 13 | 9 | 7 |
| Agent · gpt-oss-120b (+20b checks) | 1 | 11 | 11 | 13 | 4 |
| Fast · Llama 3.2 3B (local) | 9 | 15 | 9 | 7 | 0 |

Paired comparison on the same questions (judge score):

| A | B | Questions | B better | Same | A better |
|---|---|---|---|---|---|
| Fast · gpt-oss-120b | Agent · gpt-oss-120b (+20b checks) | 40 | 5 | 26 | 9 |
| Fast · Llama 3.2 3B (local) | Fast · gpt-oss-120b | 40 | 27 | 12 | 1 |

Agent revisions: 26 of 40 answers were revised once.
Invalid (hallucinated) citation numbers: {'fast_groq': 0, 'agent_groq': 0, 'fast_local': 0}
