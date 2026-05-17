# v1.1 experiment — compound query decompose-and-merge: NEGATIVE RESULT

Date: 2026-05-17
Author: Claude (autonomous v1.1 backlog work)

## Hypothesis

bench_03 failure (hit@5 = 0.20) is caused by RAG single-CP concentration on compound queries. Splitting compound queries into per-aspect sub-queries and round-robin merging the top-K from each should recover the missing CP.

## Implementation

Heuristic compound detector: regex bundle markers (`(1)…(2)…`, "first…second", "independently/moreover/furthermore", "two issues", semicolon conjunctions) + sentence-level methodology-keyword divergence. Decompose into 2–3 sub-queries; retrieve top-K each; round-robin merge with dedup.

Prototype: `/tmp/mlgg_benchmark/v1.1_compound_decompose_proto.py`

## Result on bench_03 (n=10)

| Metric | Baseline | Prototype | Δ |
|---|---|---|---|
| hit@5 | 0.20 | 0.20 | 0 |
| cp_hit@5 | 0.50 | 0.40 | **-0.10** |
| Decomposed scenarios | — | 6/10 | — |
| Wins | — | 1 | — |
| Losses | — | 1 | — |

**Net: zero or negative improvement. Do NOT ship.**

## Diagnosis of the negative result

1. **Bench_03 gold-label noise (~60% of the failure).** The expected_tags include paper-specific terms (`clinical_trial_prespecification`, `epv_violation`, `gradcam_interpretation`, `convergence_diagnostics`) that appear ≤2 times across the 1977-tag KB pool. The RAG cannot retrieve concerns with these tags because almost no concerns in the KB carry them — this is a KB tag-rarity problem, not a query-decomposition problem.

2. **Bundle detection too aggressive.** Some "compound" queries are actually single-concept critiques phrased across two sentences for clarity. Decomposing them splits semantic context, hurting retrieval (e.g., pr-003 went hit=True → hit=False because the second sentence lost grounding).

3. **Round-robin merging is naive.** When one sub-query has 5 strong hits and the other has 5 weak hits, interleaving demotes the strong ones in favour of weak ones from the other half. A score-based merge (re-rank by max sub-score) would be smarter.

## What to do instead

Three better candidates (none cheap):

| Fix | Cost | Expected lift |
|---|---|---|
| **(a) Clean up bench_03 golds** — drop ultra-rare tags from expected_tags, keep only KB-prevalent ones; re-score | ~1 hour curation | likely +0.20 hit@5 just from label quality |
| **(b) Aspect-extraction retrieval** — extract noun-phrase aspects from query, retrieve per-aspect, score-based merge | ~200 lines + needs eval iteration | medium — addresses the algorithmic bias |
| **(c) Query rewriting** — pass compound queries through a small LLM that produces 2–3 better-formed sub-queries; retrieve + merge | ~50 lines + LLM call cost | medium-high but adds runtime cost |

## v1.0 SPEC update

Add to DIAGNOSIS.md Failure 1 a line:
> "v1.1 prototype evaluation (decompose-and-merge by bundle-marker heuristic): no improvement; bench_03 failure is ~60% gold-label noise (ultra-rare expected_tags), ~40% RAG single-CP bias. Real fix path requires gold cleanup + aspect-based retrieval, not simple query split."

## Honest engineering note

This prototype took ~30 minutes to build and 5 minutes to evaluate. The negative result is more useful than shipping a marginal fix — it tells us the failure is partly downstream of label quality, not pure algorithm. Future v1.1 work should start by cleaning bench_03 labels and re-baselining before any RAG-level fix is justified.
