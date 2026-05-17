# W7-P7: E2 hybrid decomposition redo (post-fix-waves)

Diagnostic-only. Same 6 queries as E2 (2026-05-16); now exercised in BOTH
free-text and gate-anchored modes. Methodology mirrors `/tmp/e2_eval.py`
(Spearman over union-with-rank-11, Jaccard@5).

Config sampled at run: WEIGHT_DENSE=0.5, WEIGHT_BM25=0.3,
WEIGHT_TAG_OVERLAP=0.15, WEIGHT_SEVERITY=0.05; MMR_LAMBDA active;
MMR_COSINE_FLOOR=0.88; CP_TAG_BOOST_DENSE_FLOOR=0.70; free-text
re-norm path live; H1 BM25-synonym expansion live.

Harness: `/tmp/w7p7_redo.py` — raw: `/tmp/w7p7_results.json`.

## Baseline (E2, 2026-05-16)

| Metric | E2 value |
|---|---|
| Mean Spearman hybrid↔dense (free-text) | 0.279 |
| Mean Spearman hybrid↔bm25 (free-text) | -0.281 |
| Mean Jaccard@5 hybrid vs dense | 0.474 |
| Mean Jaccard@5 hybrid vs bm25 | 0.162 |
| Queries where bm25 contributed unique top-5 (free-text) | 0/6 (BM25 dead) |
| Gate-anchored mode | not measured |

## Current (post-Wave-7, 2026-05-17)

### Free-text mode

| Query (level) | hybrid top-3 | dense top-3 | bm25 top-3 | h↔d corr | h↔b corr |
|---|---|---|---|---|---|
| Brier score not reported *(easy)* | PR-EXP-0109-C03, PR-102-C01, PR-EXP-0092-C03 | PR-EXP-0109-C03, PR-102-C01, PR-024-C03 | PR-EXP-0109-C03, PR-EXP-0160-C05, PR-EXP-0209-C07 | **0.804** | -0.203 |
| AUROC 95% CI missing *(easy)* | PR-EXP-0159-C06, PR-EXP-0155-C02, PR-002-C01 | PR-011-C01, PR-010-C03, PR-004-C01 | PR-EXP-0170-C06, PR-EXP-0119-C04, PR-004-C01 | **-0.444** | -0.673 |
| selection bias retro cohort *(med)* | PR-008-C01, PR-EXP-0127-C05, PR-EXP-0197-C03 | PR-008-C01, PR-EXP-0197-C03, PR-107-C02 | PR-110-C01, PR-EXP-0197-C03, PR-EXP-0127-C05 | 0.475 | 0.174 |
| imputation fit before split *(med)* | PR-105-C02, PR-039-C03, PR-003-C02 | PR-EXP-0200-C02, PR-EXP-0160-C06, PR-035-C01 | PR-EXP-0097-C13, PR-EXP-0155-C03, PR-EXP-0200-C02 | 0.065 | -0.386 |
| uninformative baseline *(hard)* | PR-020-C01, PR-EXP-0197-C05, PR-107-C03 | PR-EXP-0086-C05, PR-EXP-0160-C08, PR-104-C02 | PR-EXP-0097-C01, PR-014-C02, PR-020-C01 | **-0.687** | -0.374 |
| data dredging subgroup *(hard)* | PR-025-C01, PR-110-C02, PR-EXP-0086-C10 | PR-EXP-0086-C10, PR-RO-07-C10, PR-EXP-0192-C05 | PR-EXP-0097-C08, PR-025-C02, PR-EXP-0194-C02 | 0.212 | -0.647 |

### Gate-anchored mode (NEW — not in E2)

| Query (level) | hybrid top-3 | dense top-3 (gate-filtered) | bm25 top-3 (real `retrieve_for_failure`) | h↔d corr | h↔b corr | bm25 nonzero in top-10 |
|---|---|---|---|---|---|---|
| Brier *(easy)* | PR-102-C01, PR-002-C01, PR-EXP-0109-C03 | PR-EXP-0109-C03, PR-102-C01, PR-EXP-0092-C03 | PR-002-C01, PR-102-C01, PR-EXP-0092-C03 | 0.389 | **0.521** | **10/10** |
| AUROC CI *(easy)* | PR-EXP-0159-C06, PR-109-C06, PR-EXP-0149-C02 | PR-035-C05, PR-EXP-0159-C06, PR-113-C02 | PR-029-C02, PR-EXP-0159-C06, PR-109-C06 | 0.547 | 0.182 | 9/10 |
| selection bias *(med)* | PR-008-C01, PR-110-C01, PR-EXP-0127-C05 | PR-008-C01, PR-EXP-0197-C03, PR-107-C02 | PR-110-C01, PR-104-C03, PR-008-C01 | 0.225 | 0.153 | 9/10 |
| imputation *(med)* | PR-113-C01, PR-003-C03, PR-072-C01 | PR-003-C03, PR-111-C01, PR-EXP-0155-C03 | PR-113-C01, PR-010-C01, PR-003-C03 | 0.527 | 0.258 | **10/10** |
| baseline *(hard)* | PR-EXP-0197-C05, PR-045-C02, PR-EXP-0105-C06 | PR-104-C02, PR-031-C01, PR-EXP-0203-C04 | PR-EXP-0205-C06, PR-EXP-0160-C05, PR-EXP-0086-C07 | -0.471 | -0.647 | 3/10 |
| dredging *(hard)* | PR-RO-07-C10, PR-111-C05, PR-EXP-0084-C14 | PR-RO-07-C10, PR-EXP-0084-C11, PR-EXP-0084-C14 | PR-111-C05, PR-RO-07-C10, PR-062-C03 | 0.482 | 0.049 | 4/10 |

## Aggregate delta

| Metric | E2 (2026-05-16) | Current free-text | Current gate-anchored | Δ vs E2 (free-text) |
|---|---|---|---|---|
| Mean Spearman hybrid↔dense | 0.279 | **0.071** | 0.283 | **-0.208** (much less dense-tied) |
| Mean Spearman hybrid↔bm25 | -0.281 | **-0.351** | **+0.086** | -0.070 ft / +0.367 ga |
| Mean Jaccard@5 hybrid vs dense | 0.474 | **0.335** | 0.455 | -0.139 |
| Mean Jaccard@5 hybrid vs bm25 | 0.162 | 0.127 | **0.268** | -0.035 ft / +0.106 ga |
| top1==dense count | 3/6 | 2/6 | 2/6 | -1 |
| bm25-unique-hit promoted into hybrid top-5 | 0/6 (BM25 dead) | **2/6** | **4/6** | +2 ft / +4 ga |
| BM25 nonzero entries in hybrid top-10 (mean) | 0.0 | 0.0 (by design) | **7.5/10** | — |
| Tag-overlap nonzero in top-10 (mean) | n/a | 4.0/10 | 2.5/10 | live |
| Severity nonzero in top-10 (mean) | n/a | 9.7/10 | 9.7/10 | live |

## Per-signal verdict

- **Dense**: no longer dominant in free-text path. h↔d Spearman collapsed
  from 0.279 → **0.071** and J@5 from 0.474 → 0.335 — the free-text
  re-normalization (BM25 0% → tag/sev weights bumped) plus MMR v2
  reshuffling is doing real, *independent* re-ranking work. The 2 easy
  queries split: Brier became *more* dense-correlated (0.80, MMR
  cooperates because top dense hits are already diverse); AUROC went
  *anti-correlated* (-0.44) because none of the dense top-3 carry the
  tag-overlap signature `no_bootstrap_ci`, so the CP+tag bonus
  promoted a different cluster.
- **BM25 (gate-anchored)**: H1's synonym expansion fires. **7.5/10 mean
  hybrid records carry a nonzero BM25 score** in gate mode (vs 0/10
  in E2). h↔b Spearman flipped from -0.281 → +0.086 — BM25 is now
  pulling in the same direction as the final ranker. **4/6 gate-anchored
  queries surface a BM25-unique top-5 hit that dense missed**, including
  PR-002-C01 for the Brier query (a real `improper_primary_metric` BM25
  hit dense ranked below 10). Earning its 0.3 weight.
- **BM25 (free-text)**: still dead by design (re-norm sets its weight to
  0 when no gate). The free-text "bm25-unique promoted: 2/6" reflects
  cases where dense+tag accidentally overlap with the BM25-flavored
  cluster, not BM25 doing work.
- **Tag overlap**: detectable — 4.0/10 mean in free-text, but `apply_tag_boost`
  gate (CP_TAG_BOOST_DENSE_FLOOR=0.70) suppresses it on hard queries
  where top dense < 0.70. Visible in baseline-comparison: dense top is
  ~0.60 so tag boost off, severity dominates → ranking goes
  anti-correlated to dense (h↔d=-0.69). Tag is no longer the runaway
  promoter E2 found; the floor curbs it on thin topics.
- **Severity**: nearly always firing (9.7/10) — but Fix-3 (severity
  scaled by `dense_spread / SEVERITY_FULL_SPREAD`) keeps the magnitude
  in check. Operates as a tie-breaker at the second decimal as before.

## Verdict

All four signals now justify their weights — **with one caveat**: BM25
only earns its 0.3 in the gate-anchored path (the production bridge
path). Free-text BM25 weight is correctly re-normalized to 0 (Wave-3
fix), so no dead weight. The post-fix system shows substantially more
**signal independence**: hybrid is no longer a near-passthrough of
dense; tag/CP and severity each shift rankings at predictable margins.

Two hard queries (uninformative-baseline, AUROC-CI free-text) show
hybrid disagreeing *strongly* with dense (h↔d <0 ). Whether that's
better or worse depends on a labeled relevance set — these decompose
into "dense missed the gate-tagged candidates so CP+severity rescued
them" rather than ranker confusion. A follow-up labeling pass on
these 2 queries would confirm whether the post-Wave-7 re-ranking is
actually improving precision@5 or just relocating noise.

**Recommendation**: keep the 0.5/0.3/0.15/0.05 weights. They were
dead-weight on paper in E2; post-fix-waves they are load-bearing in the
modes they were designed for (BM25 in gate path, tag+sev in free-text
path). No re-weighting needed. **Next eval should be a labeled
precision@5 on the 2 hard queries** to validate the new rerankings,
since the geometry is now distinct from dense but we have no ground
truth to grade it.

## Files referenced
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/retrieval/hybrid.py`
  (free-text re-norm L519-541, CP floor L549-550, severity scaling L556-567)
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/retrieval/bm25.py`
  (H1 synonym expansion L491-505, retrieve_for_failure L508)
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/config.py` (weights)
- `/tmp/w7p7_redo.py` — harness
- `/tmp/w7p7_results.json` — raw per-query rankings + meta
- `/tmp/w7p7_log.txt` — stderr trace
- `/tmp/E2_hybrid_decomposition.md` + `/tmp/e2_results.json` — E2 baseline
