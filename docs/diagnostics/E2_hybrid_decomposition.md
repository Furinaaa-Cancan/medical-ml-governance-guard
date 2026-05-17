# E2: Hybrid Ranking Decomposition

## Summary
- Queries tested: **6** (2 easy / 2 medium / 2 hard)
- Mean Spearman hybrid <-> dense: **0.279** (over union of top-10s, with missing items pinned at rank 11)
- Mean Spearman hybrid <-> bm25: **-0.281**
- Mean Jaccard@5 hybrid vs dense: **0.474**
- Mean Jaccard@5 hybrid vs bm25: **0.162**
- Queries where hybrid top-1 == dense top-1: **3/6** (easy: 2/2, medium: 1/2, hard: 0/2)
- Queries where hybrid surfaced a BM25-unique hit dense top-10 missed: **0/6** (see Critical Finding below)
- Weight-sum invariant: `0.5 + 0.3 + 0.15 + 0.05 = 1.0` -> still asserted at import (`config.py:73-75`), confirmed live.

## Per-query comparison

| Query (level) | Hybrid top-3 | Dense top-3 | BM25 top-3 | J@5 (h vs d) | top-1 same? |
|---|---|---|---|---|---|
| Brier score not reported *(easy)* | PR-EXP-0109-C03, PR-EXP-0092-C03, PR-102-C01 | PR-EXP-0109-C03, PR-102-C01, PR-024-C03 | PR-EXP-0109-C03, PR-EXP-0160-C05, PR-EXP-0209-C07 | 0.67 | yes |
| AUROC 95% CI missing *(easy)* | PR-011-C01, PR-010-C03, PR-004-C01 | PR-011-C01, PR-010-C03, PR-004-C01 | PR-EXP-0170-C06, PR-EXP-0119-C04, PR-004-C01 | 1.00 | yes |
| selection bias in retrospective cohort... *(medium)* | PR-008-C01, PR-EXP-0197-C03, PR-006-C01 | PR-008-C01, PR-EXP-0197-C03, PR-107-C02 | PR-110-C01, PR-EXP-0197-C03, PR-EXP-0127-C05 | 0.43 | yes |
| imputation fit on full dataset before split *(medium)* | PR-105-C02, PR-003-C02, PR-EXP-0200-C02 | PR-EXP-0200-C02, PR-EXP-0160-C06, PR-035-C01 | PR-EXP-0097-C13, PR-EXP-0155-C03, PR-EXP-0200-C02 | 0.25 | **no** |
| uninformative baseline comparison *(hard)* | PR-107-C03, PR-101-C02, PR-108-C03 | PR-EXP-0086-C05, PR-EXP-0160-C08, PR-104-C02 | PR-EXP-0097-C01, PR-014-C02, PR-020-C01 | 0.25 | **no** |
| data dredging in subgroup analysis *(hard)* | PR-006-C01, PR-RO-07-C04, PR-008-C04 | PR-EXP-0086-C10, PR-RO-07-C10, PR-EXP-0192-C05 | PR-EXP-0097-C08, PR-025-C02, PR-EXP-0194-C02 | 0.25 | **no** |

## Signal contribution analysis

### Dense -- **dominant** (but only for narrow queries)

- For easy/narrow queries (Brier, AUROC CI) the top-1 is the same as dense and Jaccard@5 is 0.67-1.00. Hybrid is a near-passthrough.
- For multi-concept / abstract queries, dense top-1 disagrees with hybrid in 3/6 cases, and Jaccard@5 collapses to 0.25-0.43. That divergence is **not** caused by BM25 (see next bullet); it is caused by the **tag-overlap (CP) bonus** and severity boost reshuffling ties.

### BM25 -- **dead weight in the free-text path**

This is the headline finding. Every concern in every hybrid top-10 returned by the default `rag_query(q, top_k=10)` call has `_bm25_score == 0.000`. Reason (`hybrid.py:332`):

```python
if gate and failure_codes:
    bm25_hits = retrieve_for_failure(...)
```

`rag_query()` from a user-facing free-text query passes neither `gate` nor `failure_codes`, so **the BM25 branch is never entered**. The standalone `retrieve_for_failure` function is itself gate-anchored (`gate_name in c.get("mlgg_gates", [])` filter in `_collect_concerns`); it cannot serve a pure free-text query without a gate. Asking "does BM25 add a unique hit dense top-10 missed?" in the free-text path is a tautology: it cannot, because its 0.3 weight multiplies a constant 0.

For the bridge path (`gate + failure_codes` supplied, i.e. via `scripts/core/gate_rag_bridge`), BM25 *does* fire -- but that wasn't this evaluation's scope. In the free-text path the effective weights are **dense 0.5 / BM25 0.0 / tag 0.15 / severity 0.05** = max attainable score **0.7**, with the BM25 component pure overhead.

### Tag overlap (CP boost) -- **detectable and impactful**

Both hard-query reshuffles trace directly to the CP-overlap bonus:

- **"uninformative baseline comparison"**: top-3 (PR-107-C03, PR-101-C02, PR-108-C03) all share `canonical_pattern_id=CP-005` and pick up `tag_overlap=0.60` (i.e. 2 partner concerns each). Their dense scores (0.708, 0.701, 0.700) are *below* the dense top-1 (PR-EXP-0086-C05 at 0.758), but `0.15 * 0.60 = +0.09` overrides that gap. Net: a 3-concern CP family was promoted past higher-cosine isolated concerns.
- **"imputation fit on full dataset before split"**: PR-105-C02 (CP-015) and PR-003-C02 (CP-015) each get tag=0.30 and leapfrog the actually-stronger dense match PR-EXP-0200-C02 (dense=0.745 vs 0.713).

Whether that's a feature or a bug depends on your taste — corroboration-by-pattern is a real signal, but it can also drown out the single best textual match.

### Severity -- **flips ranks at second-decimal margins**

Within almost every query, near-tied finals (delta < 0.01) cross severity tiers. Example from "Brier score not reported": PR-EXP-0092-C03 (CRITICAL) wins rank 2 (final=0.3625) over PR-102-C01 (HIGH) at 0.3605 — a 0.002 margin manufactured by `0.05 * (1.0 - 0.66) = 0.017`. With `WEIGHT_SEVERITY=0.05` the boost is small enough that it only matters when dense scores agree to two decimals, which happens often. So yes, it is a tie-breaker — and it is also what lifted PR-111-C01 (CRITICAL, dense rank 14) into hybrid rank 4 for the imputation query, displacing two HIGH dense top-10 concerns. Severity is doing real work.

### Specific bug checks

- **Weight sum**: re-verified live; `0.5 + 0.3 + 0.15 + 0.05 = 1.0` exact, assertion fires at import.
- **BM25 normalization edge cases**: traced through `_normalize_bm25`:
  - `[]` -> `[]` (correct)
  - `[0.0]` -> `[0.0]` (correct — `hi <= 0` branch)
  - `[5.0]` -> `[1.0]` (correct — `hi == lo` branch)
  - `[3.0, 3.0, 3.0]` -> `[1.0, 1.0, 1.0]` (degenerate-batch handling per docstring)
  - **No crashes, no NaNs.** The `hi == lo` -> `1.0` branch is defensible but worth noting: when BM25 returns 50 candidates all with identical raw scores (e.g. a query that hits no tags and falls back to severity_fallback with all `_score=0`), every concern would *normalize* to 1.0 and BM25 would suddenly contribute its full 0.3 weight uniformly across all candidates. The `hi <= 0` short-circuit catches the all-zero case, but not the all-equal-positive case. Low-risk in practice because severity_fallback sets `_score=0` and `_bm25_raw_score` returns 0.0, but worth pinning in a regression test.

## Verdict

**Should we simplify to dense-only?** In the free-text path: **almost yes, but not quite.** BM25 contributes nothing (it never fires), severity contributes small reorderings, and tag-overlap (CP) contributes the visible reshuffles on hard queries. Dropping BM25 from the free-text path would change nothing observable. Dropping tag-overlap + severity would collapse to dense-only and would lose the CP-corroboration promotions on abstract queries — those are *probably* desirable, but should be benchmarked against a labeled relevance set before committing.

In the **gate-bridge** path (gate + failure_codes), BM25 is the whole point of having a hybrid — don't touch that path.

**Should we re-weight?** Two concrete proposals:

1. **Free-text path**: silently re-normalize when `gate is None`. Replace `dense:bm25:tag:severity = 0.5:0.3:0.15:0.05` with `0.71:0.0:0.21:0.07` (drop BM25, redistribute). This makes the math honest — final scores currently top out at ~0.46 instead of 1.0 because the BM25 component is dark.
2. **Or simpler**: keep weights, but skip the `_normalize_bm25` and `dict(zip(...))` work entirely when `bm25_score_by_id` is empty. The current cost is small but the semantics are misleading; users see `_final_score=0.46` and assume something is weak when really `0.5 * dense + 0.15 * tag + 0.05 * sev` *is* the whole formula.

**Most surprising finding**: a 4-signal ranker that advertises a 0.3 BM25 weight ships with BM25 silently disabled for every free-text query. The bridge path makes this load-bearing, the CLI / programmatic path does not. The recent commit log (`hybrid.py` comment "post qa-wave-2026-05-13") that wired up `_score` into BM25 results was correct — but it does not change the fact that 5 of the 6 queries an evaluator would naturally try (CLI free-text) never reach that code at all.

## Files referenced (absolute)
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/config.py` — weights, sanity assertion (L73-75)
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/retrieval/hybrid.py` — fusion logic, BM25 gating (L332)
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/retrieval/bm25.py` — `retrieve_for_failure` is gate-anchored (L444-446)
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/retrieval/dense.py` — vector_search reference
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/query.py` — `rag_query` (does not propagate gate/codes when called from CLI without `--gate` and `--codes`)
- `/tmp/e2_eval.py` — evaluation harness
- `/tmp/e2_results.json` — raw rankings + per-query metadata
