# W22-V2 — NCPR end-to-end 1-paper profile

**Wave:** NCPR Benchmark v1 · **Agent:** W22-V2 · **Date:** 2026-05-17 · **Repo:** `ml-leakage-guard@main`

## Sample paper picked

| field | value |
|---|---|
| KB id | **PR-001** |
| DOI | `10.1038/s41467-024-46663-4` |
| Task | 5-year osteoarthritis risk prediction |
| Models | XGBoost, logistic_regression |
| Reviewer concerns | **10** (2 CRITICAL, 1 HIGH, 7 MEDIUM) |
| Key issues | future_information_leakage, target_leakage, no_external_validation |

Chosen because it sits at the top of the KB, exceeds the ≥5-concern bar, and exercises a high-severity leakage pattern (CP-002, MLGG-F02/F05). Caveat: `methods_text` is **not** stored in the KB (`peer_review_kb.v1.4` schema has no such field on any entry I sampled), so the v1 NCPR runner must synthesize a query proxy from `prediction_task` + `key_methodology_issues` + first ~120 chars of each `concern_text`. This matches what W22-X4's paper_runner would have to do; the profile below reflects that realistic path.

## Per-step timings (PR-001, single run, local Mac, BGE-small)

Measured by `/tmp/W22_V2_profile.py`. Raw JSON in `/tmp/W22_V2_timings.json`.

| step | wall ms | notes |
|---|---:|---|
| RAG retrieve — **cold** (1 query, includes BGE load + index build/load) | **12 281** | dominates by ~2 orders of magnitude |
| RAG retrieve — **warm** (same query, cache hit) | 27 | cache works |
| RAG slice queries — 10 concern-derived queries, top-k=5 | 429 total / 43 mean / 11 min / 170 max | first slice 170 ms (still warming) |
| Semantic match — 10 flags × 10 concerns via `ncpr_matcher.match_all` (BGE cosine, threshold 0.70) | **842** (warm, min-of-3) | `embed_texts` per-text call dominates |
| Aggregation (severity histogram) | 0.003 | noise |
| **Per-paper total (cold start)** | **~12.7 s** | one-time penalty |
| **Per-paper total (warm reuse)** | **~1.3 s** | 429 + 842 + agg |

## 30-paper extrapolation

* **Cold-each (no reuse):** 30 × 12.7 s = **~6.4 min**.
* **Warm-reuse (one process, index + model loaded once):** 12.7 s + 29 × 1.3 s ≈ **~50 s**.
* Even pessimistic cold-each fits the budget.

## Bottlenecks (top 3)

1. **BGE model + index load (~12 s, one-time).** 97 % of cold per-paper wall. Mitigation: keep a long-lived process / warm the cache once in CI before the loop, **not** spawn 30 sub-processes.
2. **Semantic match `embed_texts` (~840 ms / paper).** Each concern + each flag is embedded one-at-a-time. Mitigation: batch all texts for a paper into a single `embed_texts([...])` call (BGE batches ~64 cheaply); expected ≥5× speed-up.
3. **First slice query (170 ms vs ~30 ms steady-state).** Within-process warmup of the dense index reranker. Mitigation: dummy warm query before the loop.

## Verdict

**PASS — feasible for CI gate.** Even worst-case cold-each run for 30 papers is ~6.4 min, well under the 15-min PASS threshold. With trivial reuse it drops to ~50 s. Recommendation: structure the W22 benchmark as a single Python process iterating 30 papers (not a shell loop spawning subprocesses).

## Unexpected behaviour

* **`methods_text` missing from KB entries** — the task spec assumed it exists. Confirmed absent on PR-001…PR-010. Downstream impact: v1 NCPR queries are necessarily concern-text-derived; semantic-match precision will be **upward-biased** because the same surface tokens appear on both sides. Worth a pre-registered caveat in the benchmark spec.
* **`embed_query` symbol does not exist** in `scripts/rag/embeddings.py` — only `embed_texts`. If a sibling agent's runner imports `embed_query` it will silently skip semantic matching (my first profile run did exactly that). Flag for W22-X4 to audit.
* **Slice queries return 5/5 hits every time** — good coverage, but suggests the top-k=5 cap may be hiding low-confidence tails worth surfacing.

(287 words)
