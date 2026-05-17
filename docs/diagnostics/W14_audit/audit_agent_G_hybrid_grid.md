# Audit Agent G — Hybrid fusion-weight grid search

## Fusion form & current knob

The hybrid retriever uses a **weighted-sum** fusion (not RRF). From
`scripts/rag/retrieval/hybrid.py` § "8. Combine" and `scripts/rag/config.py`:

```
final = WEIGHT_DENSE * dense_cosine
      + WEIGHT_BM25  * bm25_normalized
      + WEIGHT_TAG_OVERLAP * tag_overlap
      + WEIGHT_SEVERITY * severity_boost          # weights MUST sum to 1.0
```

**Current production weights (post-W13, 2026-05-17):**

| WEIGHT_DENSE | WEIGHT_BM25 | WEIGHT_TAG_OVERLAP | WEIGHT_SEVERITY |
|---:|---:|---:|---:|
| 0.10 | **0.45** | 0.30 | 0.15 |

The single "knob" is parameterized as `alpha := WEIGHT_BM25`. The residual
`1 − alpha` is split across the other three signals using the current
production ratios `dense : tag : sev = 2 : 6 : 3` (out of 11), so the
sweep is a straight line from "no BM25" (alpha=0) to "BM25 only"
(alpha=1) that passes through the current production point at
alpha=0.45.

## Grid table — 30 scenarios + 36 labeled queries

| alpha | hit@5 | mean_tag_precision (proxy) | mean_labeled_P@5 (ground truth) |
|---:|---:|---:|---:|
| 0.00 | 0.733 | 0.281 | 0.472 |
| 0.10 | 0.867 | 0.342 | **0.522** |
| 0.20 | 0.867 | 0.376 | 0.517 |
| 0.30 | 0.867 | 0.404 | 0.517 |
| 0.40 | 0.833 | 0.432 | 0.511 |
| **0.45 (current)** | **0.833** | **0.438** | **0.494** |
| 0.50 | 0.833 | 0.433 | 0.489 |
| 0.60 | 0.833 | 0.433 | 0.489 |
| 0.70 | 0.833 | 0.427 | 0.483 |
| 0.80 | 0.833 | 0.428 | 0.478 |
| 0.90 | 0.833 | 0.417 | 0.478 |
| 1.00 | 0.833 | 0.438 | 0.322 |

bm25_only baseline reference: hit@5=0.833, mean_tag_precision=0.436.

## Argmax under constraint (`hit@5 ≥ 0.833`)

`alpha = 0.45` and `alpha = 1.00` tie at **mean_tag_precision = 0.438** (a
tiny +0.002 over the bm25_only baseline of 0.436). Tiebreak on ground-truth
labeled_P@5 picks **alpha = 0.45** (0.494 vs 0.322 for alpha=1.00).

## Does ANY hybrid beat bm25_only on tag_precision?

Technically **yes**, but only by 0.002 (0.438 vs 0.436) — well within
labeling noise. On the audit's framing (the "0.338 hybrid drop" in
`references/retrieval_eval/post_wave7_baseline_hybrid.json` is an
**older** measurement, predating the W13 rebalance and the
`USE_DENSE_CORROBORATION` flag). The current production weights have
already largely closed that gap on the proxy metric.

## Recommendation

**Keep the current setting (`WEIGHT_BM25 = 0.45`, residual split
`DENSE/TAG/SEV = 0.10 / 0.30 / 0.15`).**

Reasoning: on the proxy tag_precision metric the current point is at the
flat top of the curve (+0.002 over bm25_only, indistinguishable from
alpha=1.0), but on the only ground-truth metric available
(mean_labeled_P@5 over 36 hand-labeled queries) the current point scores
**0.494** versus **0.322** for BM25-only — a +17pt absolute gain. The
proxy metric over-rewards BM25 because the scenarios' `expected_tags`
are tokens that BM25 directly matches, so tag_precision is partially
self-reinforcing on the lexical channel; the ground-truth labels do
**not** show that bias. Reverting to bm25_only would trade a noise-level
proxy gain for a real ground-truth loss.

A secondary candidate worth tracking is **alpha ≈ 0.10–0.30** (higher
hit@5 = 0.867 and the best mean_labeled_P@5 = 0.517–0.522) at the cost
of ~0.06 in proxy tag_precision. If the team trusts the labeled set more
than the tag-overlap proxy (which the W8-W2 / W9-A2 protocol comments
suggest they should), that range is the better answer — and it would
also explain the original audit M3 finding as a proxy-vs-truth mismatch
rather than a real fusion bug.

## Grid script

`/tmp/audit_agent_G_grid.py` (raw JSON output at
`/tmp/audit_agent_G_hybrid_grid.json`).
