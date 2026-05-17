# W2: Q9 free-text regression diagnosis

**Query**: `"single-center development without external test"` (`scenario_id: no_external_validation_single_center`, `h10_legacy_id: Q9_external_validation`)
**Baseline (E1)**: P@5 = 1.0
**Current main**: P@5 = 0.4 (per H14 finding)
**Repro date**: 2026-05-17 (post-Wave-2 commit `6e180d0`)

---

## Current top-5 (free-text)

| Rank | Concern ID | final | dense | mmr | E1-expected? |
|------|------------|-------|-------|-----|--------------|
| 1 | PR-EXP-0086-C06 | 0.533 | 0.714 | 0.533 | not in 3-doc list |
| 2 | PR-029-C02 | 0.490 | 0.654 | 0.133 | no |
| 3 | PR-EXP-0148-C02 | 0.498 | 0.665 | 0.133 | no |
| 4 | PR-EXP-0095-C03 | 0.528 | 0.708 | 0.124 | not in 3-doc list |
| 5 | PR-019-C02 | 0.479 | 0.638 | 0.118 | no |

`bm25_inactive_free_text` reasons present, `top1_dense=0.714 ≥ 0.70` so CP gating IS met.

## Dropouts (in current top-20)

| Concern | dense rank | final rank | dense | final | CP | tag_overlap_raw |
|---------|------------|------------|-------|-------|----|-----------------|
| PR-084-C01 | 4 | 11 | 0.675 | 0.505 | CP-029 | 0.000 |
| PR-028-C01 | 3 | 16 | 0.675 | 0.505 | CP-008 | 0.000 |
| PR-006-C04 | 14 | 19 | 0.644 | 0.494 | CP-008 | 0.000 |

All three have `tag_overlap_raw=0.000` — they receive **no CP-bonus** even though CP gating is satisfied. (CP bonus requires another candidate with same `canonical_pattern_id` AND ≥2 shared tags. PR-028-C01 and PR-006-C04 share `CP-008` but their tag sets are disjoint: `[no_external_validation, out_of_distribution]` vs `[premature_clinical_deployment, no_external_validation_for_combined, overstatement]`. So CP-corroboration doesn't fire.)

## Top-1 dense score for query

**0.714**; `CP_TAG_BOOST_DENSE_FLOOR = 0.70`; gating-met: **YES** → CP boost would apply if any pair qualified. None did. Hypothesis (a) is **REJECTED**.

## Hypothesis test — bypass MMR

Pre-MMR ranking (post-hybrid scoring, descending `_final_score`):

| Rank | Concern ID | final | dense | E1-target? |
|------|------------|-------|-------|------------|
| 1 | PR-EXP-0086-C06 | 0.533 | 0.714 | |
| 2 | PR-EXP-0095-C03 | 0.528 | 0.708 | |
| 3 | **PR-028-C01** | 0.505 | 0.675 | YES |
| 4 | **PR-084-C01** | 0.505 | 0.675 | YES |
| 5 | PR-EXP-0148-C02 | 0.498 | 0.665 | |
| 6 | PR-107-C01 | 0.495 | 0.662 | |
| 7 | **PR-006-C04** | 0.494 | 0.644 | YES |

**Without MMR**: P@5 = 0.4 (PR-028-C01, PR-084-C01 in slots 3–4; PR-006-C04 at slot 7). MMR pushes the two top-tier dropouts from #3–#4 to #11/#16. With `MMR_LAMBDA=0.85`: PR-084-C01 → #5, PR-028-C01 → #6 (P@5 = 0.4, but ranks tighten).

## Cosine evidence — MMR is over-penalizing

| Pair | Cosine |
|------|--------|
| top-1 PR-EXP-0086-C06 ↔ PR-028-C01 | 0.8169 |
| top-1 PR-EXP-0086-C06 ↔ PR-084-C01 | 0.8108 |
| top-1 PR-EXP-0086-C06 ↔ PR-006-C04 | 0.8083 |
| top-1 PR-EXP-0086-C06 ↔ PR-EXP-0095-C03 (rank-2 keeper) | 0.8187 |
| top-1 PR-EXP-0086-C06 ↔ PR-029-C02 (rank-2 winner under MMR) | 0.6979 |
| Within-dropouts cos | 0.78–0.82 |

The dropouts are NOT near-duplicates (would be > 0.95). They sit in 0.78–0.82 band — semantically related but distinct concerns. MMR `lam=0.7` penalizes them by `0.3 * 0.81 ≈ 0.243`, more than wiping out the ~0.04 relevance advantage over PR-029-C02 (cos=0.698).

The MMR math (for #2 slot competition):
- PR-028-C01: `mmr = 0.7 * 0.505 - 0.3 * 0.817 = 0.354 - 0.245 = 0.109`
- PR-029-C02: `mmr = 0.7 * 0.490 - 0.3 * 0.698 = 0.343 - 0.209 = 0.133` ← wins

A less-relevant but more-novel concern wins the diversity competition.

## Diagnosis: **(b) MMR diversity regression**

H5's MMR v2 (commit `1642f3a`, "MMR v2 — dense embedding cosine similarity for diversity") replaced v1's paper_id-only similarity with dense-embedding cosine. For free-text queries on the **external_validation** dimension, MMR now treats all on-topic concerns (cos 0.78–0.82 to top-1) as near-duplicates and demotes them in favor of off-topic but novel concerns.

**Deeper issue**: MMR's premise ("user wants topical variety") conflicts with E1's evaluation premise ("P@5 should surface multiple corroborating concerns on the same issue"). On focused thin-topic queries, diversity is the wrong objective.

Hypothesis (a) CP gating: **rejected** — gating fires correctly, but corroboration doesn't trigger because the 3 dropouts have disjoint tag sets even within shared CP-008.
Hypothesis (c) BM25 re-normalization: rejected — BM25 inactive in free-text mode; re-norm only affects scale, not order.
Hypothesis (d) KB shift: rejected — dense scores still place dropouts at ranks #3, #4, #14 in raw dense (vs. their original P@5 positions); KB embeddings still match. The ordering change happens at MMR.
Hypothesis (e) other: BM25-anchored mode (`gate=external_validation_gate`, `failure_codes=[no_external_validation, single_center_only]`) also misses PR-028-C01 and PR-006-C04 from top-5, but for a different reason: BM25 keyword-match flood (`PR-EXP-0097-C01`, `PR-001-C06`, `PR-EXP-0097-C03`, `PR-110-C05`, `PR-EXP-0185-C03` all land in top-9 with `dense=0.000`). Separate H14-followup.

## Recommended fix (NOT a one-liner — needs deliberation)

There is no safe single-line fix. The candidates are:

### Option A: raise `MMR_LAMBDA` to 0.85 (1-line in `scripts/rag/config.py`)
- **Effect on Q9**: P@5 still 0.4 (PR-084-C01 → #5, PR-028-C01 → #6, PR-006-C04 → #9). Marginal improvement.
- **Risk**: weakens MMR's intended same-paper deduplication for OTHER queries. The 2-3 other E1 queries that benefited from MMR v2 might regress.
- **Verdict**: cosmetic. Doesn't move P@5.

### Option B: raise the MMR cosine threshold (no penalty below cos < ~0.90)
- Modify `_mmr_rerank` so similarity `< MMR_COSINE_FLOOR` (e.g., 0.88) contributes zero penalty. Same-paper penalty still applies.
- Preserves MMR for actual near-duplicates (cos > 0.9), neutralizes it for semantically-related but distinct concerns.
- **Estimated effect on Q9**: PR-028-C01, PR-084-C01 lift back to #3, #4 (cos 0.81 < 0.88 → no penalty), restoring P@5 ≥ 0.6.
- **Risk**: MMR becomes very weak; cross-paper duplicates with cos 0.85–0.90 will sneak back in. Need test coverage.

### Option C: query-aware MMR (skip MMR when query is a thin "category" query)
- Detect when the user query is a topic descriptor (single dimension) vs. a multi-dimension audit question. For category queries, return pure relevance ranking.
- Hard to detect heuristically; would need a labeled query corpus.

### Option D: BM25-anchored mode IS the production path; free-text P@5 is a secondary concern
- The MLGG runtime calls `rag_query` from `gate_rag_bridge` with `gate` + `failure_codes` (BM25-anchored). The free-text path is exercised mainly by `mlgg rag "..."` CLI and E1 eval harness.
- If free-text is "demo-mode only," document the limitation in `docs/RAG_TROUBLESHOOTING.md` and lower priority.

### Recommendation
**Backlog ticket — Option B + Option D combo**:
- (B) Add `MMR_COSINE_FLOOR = 0.88` to `config.py` and gate the cosine penalty in `_mmr_rerank` on `cos >= MMR_COSINE_FLOOR`. Keep same-paper penalty unconditional.
- (D) Add a `KNOWN_LIMITATIONS.md` note: "free-text 'category' queries (Q9, Q10 type) may have lower P@5 than gate-anchored queries; production callers should pass `gate=` and `failure_codes=` for full quality."
- Re-run full E1/E2 harness after change; commit only if no other query regresses.

## Why no commit

This is not a 1-line trivial fix per the W2 plan instructions. The MMR cosine floor (Option B) is the recommended fix but introduces a new config knob (`MMR_COSINE_FLOOR`) and needs:
1. Threshold sweep on full E1 (12 queries)
2. Regression test for the case that v2 MMR was added to solve (cross-paper near-duplicates)
3. Update to `tests/test_rag_mmr.py`

Recommend handing this to a fresh agent with scoped prompt: "Add MMR_COSINE_FLOOR=0.88 to scripts/rag/config.py and gate the cosine penalty in `_mmr_rerank` (scripts/rag/retrieval/hybrid.py); run scripts/rag/evals/harness.py and report ΔP@5 per query; commit only if Q9 improves and ≥10/12 other queries are non-regressed."

---

## Files referenced
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/retrieval/hybrid.py` (MMR rerank, line 267-356)
- `/Volumes/Seagate/Skill/ml-leakage-guard/scripts/rag/config.py` (`MMR_LAMBDA=0.7`, `MMR_SAME_PAPER_PENALTY=0.5`, line 117-118)
- `/Volumes/Seagate/Skill/ml-leakage-guard/references/retrieval_eval/scenarios.json` (Q9 spec, `baseline_p5_e1=1.0`)
- Repro: `/tmp/w2_repro.py`, `/tmp/w2_mmr_probe.py`, `/tmp/w2_cos_probe.py`, `/tmp/w2_gated_probe.py`
- Outputs: `/tmp/w2_results.txt`, `/tmp/w2_mmr.txt`, `/tmp/w2_cos.txt`, `/tmp/w2_gated.txt`
