# H14: Post-Wave-1 E1 Re-run

**Date**: 2026-05-17
**Agent**: H14 (Wave 2, overnight loop)
**Scope**: Re-run E1's 12-query precision audit against current main (post H1/F1/H5/G1 fixes). Measure P@5 delta per query, per mode (free-text vs gate-anchored).
**Read-only**: no source changes, no commits.

## Method

Reused the verbatim 12 queries from `/tmp/E1_retrieval_precision.md` (E1, 2026-05-16).
Note: `scripts/rag/evals/scenarios.json` (planned by H10) is **not yet present** in the repo — so the 12 queries were hard-coded inline in `/tmp/h14_runner.py` from the E1 report.

For each query, called `scripts.rag.query.rag_query` twice:
1. **Free-text**: `rag_query(query, top_k=5)`
2. **Gate-anchored**: `rag_query(query, gate=<best-fit gate>, failure_codes=<best-fit codes>, top_k=5)`

Gate / code anchors were chosen from `scripts/core/_gate_registry.py` to match the query intent (e.g. Q4 → `ci_matrix_gate` + `MLGG-E01`; Q7 → `missingness_policy_gate`; Q8 → `split_protocol_gate` + `MLGG-F02`).

Top-5 results were hand-scored by the same rubric E1 used:
- **1** = clearly relevant
- **0.5** = loosely related
- **0** = irrelevant

Raw JSON dump: `/tmp/h14_raw_results.json`. Run log: `/tmp/h14_run.log`.
Total run time after model warm: ~15 s for all 24 calls (12 free + 12 gate-anchored).

## Aggregate

| Mode | Baseline E1 mean P@5 | Current mean P@5 | Δ |
|---|---|---|---|
| free-text | 0.717 † | 0.608 | **−0.108** |
| gate-anchored | (not measured by E1) | **0.792** | — |

† The E1 report quotes "Mean P@5: 0.80" in its summary, but the listed per-query values sum to 8.6 / 12 = 0.717. We use the per-query values as the authoritative baseline since the summary number is internally inconsistent with E1's own table.

**Headline finding**: gate-anchored P@5 is **+0.075 over the (corrected) E1 baseline** and **+0.184 over the current free-text mean**. The Wave-1 fixes shifted the system to one where gate-anchored is meaningfully better than free-text — the opposite of E1, where the only mode tested was free-text.

## Per-query

| Q | Dimension | E1 free P@5 | Current free P@5 | Current gate P@5 | Δ free | Δ gate vs E1 | Notes |
|---|---|---|---|---|---|---|---|
| Q1 | leakage | 1.0 | 0.8 | **1.0** | −0.2 | 0.0 | Free-text introduced PR-014-C01 ("no evidence of leakage"→0). Anchored on `leakage_gate` is clean. |
| Q2 | calibration | 1.0 | 1.0 | 0.7 | 0.0 | −0.3 | Gate-anchored pulled in 2 calibration-adjacent but off-target hits via BM25 (PR-006-C02 variance-explained, PR-105-C04 calibration intercept summary location). |
| Q3 | subgroup fairness | 0.8 | 0.7 | 0.8 | −0.1 | 0.0 | Free-text dropped PR-EXP-0119-C01; gate-anchored restored it. |
| Q4 | **AUROC-CI** | 0.2 | 0.2 | **1.0** | 0.0 | **+0.8** | H1 win: BM25 + canonical codes (`MLGG-E01`) surface CI-specific concerns (PR-EXP-0159-C06, PR-EXP-0197-C05, PR-109-C06, PR-113-C02, PR-043-C02). Every gate-anchored hit explicitly addresses CI/DeLong/95% reporting. |
| Q5 | tuning-on-test | 0.4 | 0.3 | **0.8** | −0.1 | **+0.4** | F1 boost-gating removed CP-005 noise from free-text (Q5 free is comparable to E1); gate-anchored on `tuning_leakage_gate` + `MLGG-M01` lifts to 0.8. |
| Q6 | class imbalance | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | Stable. |
| Q7 | **complete-case** | 0.2 | 0.2 | **0.9** | 0.0 | **+0.7** | Major win. F1 severity-spread scaling alone did not help free-text (still ranked 3 off-topic CRITICALs above PR-035-C01). Gate filter on `missingness_policy_gate` deterministically restricts the candidate pool to missing-data concerns → top-5 all on-topic. |
| Q8 | temporal | 0.3 | 0.4 | 0.4 | +0.1 | +0.1 | Marginal improvement free-text (CP-024 boost reduced). Gate-anchored `split_protocol_gate` + `MLGG-F02` is roughly tied with free-text — BM25 over-weights "split/data" surface tokens (PR-EXP-0185-C02 imaging-period split, PR-072-C01 UK Biobank, PR-EXP-0084-C08 hyperparam) above genuine temporal concerns. **Algorithm is no longer the bottleneck; KB is.** |
| Q9 | external validation | 1.0 | 0.4 | 0.5 | **−0.6** | −0.5 | Regression. The E1-perfect top-5 (PR-006-C04, PR-028-C01, PR-084-C01) is no longer there. Likely cause: F1 / H5 trimmed boosts that were promoting those entries. Anchored `external_validation_gate` does not recover them — those records may have been re-tagged or have dense scores just under the new candidate cutoff. **Worth triaging in Wave 3.** |
| Q10 | model spec | 0.8 | 0.6 | 0.8 | −0.2 | 0.0 | Free-text dropped PR-EXP-0191-C06; gate-anchored restored. |
| Q11 | reproducibility | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | Stable. MMR v2 (H5) note: free-text returned 5 distinct papers (no PR-003-C09/C10 cluster); cross-paper dup count = 1 — H5 success confirmed. |
| Q12 | TRIPOD | 0.9 | 0.7 | 0.6 | −0.2 | −0.3 | Lost PR-EXP-0148-C03 ("Add MI-CLAIM / TRIPOD-ML") and PR-110-C06 ("No TRIPOD / MI-CLAIM compliance") from both modes. These are exact-match TRIPOD concerns; absence suggests an upstream re-scoring (F1/H5) dropped them just out of top-5. |

## Wins (where Wave-1 helped)

1. **Q4 AUROC-CI: 0.2 → 1.0 (+0.8) gate-anchored.** H1's BM25 + canonical-codes fix is doing exactly what it was designed to do. With `ci_matrix_gate` + `MLGG-E01`, every top-5 hit explicitly mentions 95% CI / DeLong / CI estimation. Free-text P@5 = 0.2 unchanged — H1 only fires when the gate hint is provided.
2. **Q7 complete-case: 0.2 → 0.9 (+0.7) gate-anchored.** Pure mechanism: gate-filter on `missingness_policy_gate` restricts candidates so severity boost no longer flips off-topic CRITICALs above the on-topic HIGH. Free-text P@5 = 0.2 unchanged — F1 severity-spread scaling did *not* solve this for unanchored callers.
3. **Q5 tuning-on-test: 0.4 → 0.8 (+0.4) gate-anchored.** Same pattern: gate filter + BM25 keyword anchors lift the on-topic hits.
4. **MMR v2 (Q11)** confirmed working: no same-paper duplicates in Q11 free-text top-5 (previously PR-003-C09 and PR-003-C10 both appeared). Cross-paper max count = 1 across all 24 result sets.

## Persistent weaknesses

1. **Q8 temporal validation (P@5 = 0.4 in both modes)**: KB is lexically thin on time-series / temporal hold-out concerns. BM25 over-anchors on "split" and "data". Gate filter helps a little but not enough. This is now a **KB curation** problem, not an algorithm one.
2. **Q9 external validation (regression 1.0 → 0.4)**: a strict regression introduced by the Wave-1 score-fusion changes. Three of E1's perfect top-5 hits (PR-006-C04, PR-028-C01, PR-084-C01) are no longer in top-5 by any mode. Needs a targeted diff of the scoring functions touched by F1/H5 against those specific concern IDs.
3. **Q2 / Q12 mild gate-anchored regressions (−0.3, −0.3)**: BM25 anchor on common terms ("calibration", "TRIPOD") promotes loose hits over the strongest dense matches when the gate filter is broad.

## Recommendations for Wave 3

1. **Highest leverage**: KB curation for **Q7 complete-case** and **Q8 temporal** — write ~5 targeted concerns each for these two gates so that even free-text (no gate hint) callers get dense hits. Algorithm changes have hit diminishing returns here.
2. **Investigate the Q9 regression** — diff scoring of PR-006-C04 / PR-028-C01 / PR-084-C01 pre- and post-Wave-1; identify which fix dropped them and whether the trade-off is acceptable.
3. **Gate-anchored is now meaningfully better than free-text** (0.792 vs 0.608). Two follow-ups worth flagging:
   - CLI default could emit a "you may want to specify --gate" hint when invoked without one (cheap UX win).
   - The aggregator (`gate_rag_bridge`) should keep using gate hints — and the rag_query docstring should be updated to recommend gate anchoring as the production path.
4. **Land H10's `scenarios.json` fixture** so future H-series agents can use a stable harness rather than copy-pasting query strings from prose reports. Same fixture should record per-query expected gate + codes (which we had to derive by hand for this run).
5. **Q2/Q12 gate-anchored regressions** point to a BM25 over-anchoring failure mode when the keyword is common in the KB. Worth a small token-IDF-weighted BM25 tweak in Wave 3.

## Caveats

- Hand-scoring is the same single-rater protocol E1 used; some 0.5-vs-1 calls are subjective.
- Q9's regression deserves a second look — it's possible the new top-5 hits are *also* relevant in ways the E1 rubric would have credited but that this hand-score did not, since I scored only against the verbatim query intent.
- Gate / code anchors were chosen by best-fit; a different anchor choice could shift gate-anchored P@5 by ±0.1 per query. The mean is more robust than any single number.
