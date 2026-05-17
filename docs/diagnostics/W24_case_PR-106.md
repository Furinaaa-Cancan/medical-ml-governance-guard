# W24-05 — Case Study: PR-106 Post-Fix (NCPR v2 Real-Paper Run)

**Date:** 2026-05-17 · **Wave:** W24 single-paper case studies · **Mode:** READ-ONLY for code
**Pipeline:** NCPR v2 (post-67f7492 fix to `synthesize_flags_from_rag`)
**Protocol:** W24-01 (KMI-only query → rag_query top_k=20 → match → score → card)
**Artifacts:** `/tmp/W24_05_results.json`, `/tmp/W24_05_PR106_runner.py`
**Baseline:** W23-D2 (commit 75c8d86), PR-106 F1=0.143

---

## Paper meta

| field | value |
|---|---|
| paper_id | PR-106 |
| title | Real-time prediction of intensive care unit patient acuity and therapy requirements using state-space modelling |
| journal | Nature Communications |
| year | 2025 |
| KB quality_score | 13/13 (W23-A3 top tier) |
| n_reviewer_concerns | 6 (1 HIGH / 3 MEDIUM / 2 LOW; 0 CRITICAL) |
| key_methodology_issues | model_justification, clinician_adjudication, prospective_vs_retrospective |
| rag query (KMI-derived) | `"model justification clinician adjudication prospective vs retrospective"` (71 chars) |
| top_k_flags | 20 |

---

## Match summary

| metric | W24-05 (post-fix, KMI query) | W23-D2 (pre-fix, concern-text query) | Δ |
|---|---:|---:|---:|
| weighted_f1 | **0.295** | 0.143 | **+0.152 (+106%)** |
| wPrecision | 0.184 | 0.091 | +0.093 (+102%) |
| wRecall | **0.750** | 0.333 | **+0.417 (+125%)** |
| wTP | 4.50 | — | — |
| wFN | 1.50 | — | — |
| wFP | 20.00 | — | — |
| n_flags / n_concerns | 20 / 6 | 20 / 6 | unchanged |
| matched concerns (count) | **4 / 6** | 2 / 6 | +2 |
| exact_code matches | **3** | 0 | +3 |
| semantic matches | 1 | 2 | −1 |
| code_prefix matches | 0 | 0 | 0 |
| wall (rag / match, s) | 11.8 / 2.1 | ~2.0 total | first-paper BGE load |

The fix moves PR-106 from worst-of-5 (F1=0.143) to roughly the W23-D2 macro mean (0.318). **The post-fix matcher channel mix is now 3 exact_code + 1 semantic, vs. W23-D2's 0 exact_code (all semantic).** This is the headline confirmation that 67f7492 restored the lexical fast-path that W23-D2 reported as structurally dead.

---

## Matched (4 / 6 concerns)

| concern | sev | matched-by flag | match type | score | reviewer mlgg_gates |
|---|---|---|---|---:|---|
| PR-106-C01 (model_selection) | MEDIUM | `cohort_definition_gate` (HIGH) | semantic | 0.727 | model_selection_audit_gate |
| PR-106-C02 (evaluation_metrics) | MEDIUM | `evaluation_quality_gate` (HIGH) | **exact_code** | 1.000 | ci_matrix_gate, **evaluation_quality_gate** |
| PR-106-C04 (clinical_utility) | HIGH | `clinical_metrics_gate` (HIGH) | **exact_code** | 1.000 | **clinical_metrics_gate**, calibration_dca_gate, evaluation_quality_gate |
| PR-106-C05 (reporting) | LOW | `external_validation_gate` (CRITICAL) | **exact_code** | 1.000 | reporting_bias_gate, **external_validation_gate** |

Notes:
- **C01 semantic match is suspicious**: `cohort_definition_gate` is a study-design gate; the reviewer concern is about model selection (Mamba vs APRICOT). Cosine 0.727 is just above the 0.70 threshold — this is the kind of weak semantic match the score floor was supposed to mute, but it counts toward TP here. The HIGH severity of the flag also over-weights the contribution.
- **C05 exact_code is severity-mismatched**: reviewer sev=LOW, flag sev=CRITICAL. Match is correct (the gate appears in `mlgg_gates`) but the weighted scorer credits CRITICAL weight to the TP, inflating wTP for what reviewers rated trivial.
- C02 and C04 are clean, well-aligned exact_code wins — exactly the cases the fix was designed to recover.

---

## Missed (2 / 6 concerns)

| concern | sev | category | mlgg_gates | why missed |
|---|---|---|---|---|
| PR-106-C03 | MEDIUM | model_selection | model_selection_audit_gate | Same gate as matched C01, but flag[11]'s match was already consumed by C01 (matcher's flag-to-1-concern de-dup). No other emitted flag has this code or a sufficient semantic neighbor. |
| PR-106-C06 | LOW | reproducibility | reporting_bias_gate, seed_stability_gate, execution_attestation_gate, model_selection_audit_gate | Pure reproducibility-housekeeping (README/deps); no retrieved flag carries any of the 4 listed gates, and semantic cosine to retrieved evidence falls below 0.70. |

Both misses fall in the patterns W23-D2 §4 flagged as the recall ceiling: **multi-gate housekeeping concerns** (C06) and **same-gate concerns competing for a single best-scoring flag** (C03 vs C01). The fix did not address either pattern — it only restored the lexical channel. C03 in particular shows the de-dup limit: two MEDIUM concerns both list `model_selection_audit_gate`, but only one flag can win each concern, so the second concern is structurally unrecoverable unless the synthesizer emits two `model_selection_audit_gate` flags.

---

## Over-flags (16 / 20 emitted flags unmatched, wFP=20.0)

| flag code | severity | n |
|---|---|---:|
| cohort_definition_gate | HIGH | 5 |
| cohort_definition_gate | CRITICAL | 3 |
| external_validation_gate | HIGH | 2 |
| evaluation_quality_gate | HIGH | 2 |
| split_protocol_gate | CRITICAL | 1 |
| leakage_gate | HIGH | 1 |
| clinical_metrics_gate | HIGH | 1 |
| missingness_policy_gate | HIGH | 1 |

**Pattern: a single gate (`cohort_definition_gate`) accounts for 8/16 over-flags** (50%), and 4/16 are CRITICAL-severity flags injected by retrieved KB rows from *other* papers' CRITICAL concerns. Because severity weighting is 4.0× for CRITICAL, those 4 flags alone contribute 16/20 of wFP (80% of the precision penalty). This is the same pattern W23-D2 §4 identified: **retrieval leaks high-severity concerns from neighbor papers**, and the precision floor sits at ~0.18 even when recall climbs.

The over-flag mass is *not* fixed by 67f7492 — the fix only changed how `flag.code` is filled in. Top-k=20 with cross-paper KB retrieval and no paper-specific evidence is the root cause; the cure is W23-A2 PDF methods-text extraction (giving the retriever a paper anchor) plus a precision-budget cut from top-20 to top-5–8.

---

## Narrative

PR-106 was the W23-D2 worst case (F1=0.143, all 0 exact_code matches) precisely because every emitted `flag.code` was a `concern_id` like `"PR-019-C02"`, which never lexically matches a real gate name. Patch 67f7492 swaps the fallback chain to prefer `mlgg_gates[0]`, immediately producing 3 exact_code hits on this paper, lifting matched concerns from 2 to 4 and weighted_f1 to 0.295 — a +106% relative gain and the largest improvement of any W23-D2 paper. Recall doubles (0.333 → 0.750) because the matcher can finally consume the high-precision lexical channel; precision also doubles (0.091 → 0.184) since the same fix retires several spurious semantic-only matches that previously consumed the wrong concerns. Remaining failure modes are W23-D2 patterns the fix was never meant to address: cross-paper CRITICAL leakage drives the precision floor, and multi-gate housekeeping concerns (C06) plus same-gate concern competition (C03) cap recall at ~0.75. PR-106 was correctly nominated as the most-improved-by-fix candidate.

---

## Explicit comparison to W23-D2 (F1=0.143)

| dimension | W23-D2 (pre-fix) | W24-05 (post-fix) | source of delta |
|---|---|---|---|
| `flag.code` content | `concern_id` (e.g. `PR-019-C02`) | gate name (e.g. `evaluation_quality_gate`) | 67f7492 swap in `_concern_to_flag` |
| exact_code matches | **0** | **3** | direct consequence of fix |
| semantic matches | 2 (incl. cosine=1.000 verbatim hits) | 1 | semantic channel partially displaced by lexical |
| matched concerns | 2 / 6 | 4 / 6 | +2 (C02 + C05 newly matched lexically; C04 upgraded semantic→exact_code) |
| weighted_f1 | 0.143 | 0.295 | +0.152 (+106%) |
| wRecall | 0.333 | 0.750 | +0.417 (+125%) — largest single contributor |
| wPrecision | 0.091 | 0.184 | +0.093 (+102%) — fix retires 2 wrong-concern semantic matches |
| query construction | concern-text (4 KB) | KMI tags (71 chars) | **caveat: weaker query in W24-05; gain is achieved despite shorter query** |
| n_flags (top_k) | 20 | 20 | unchanged |
| over-flag dominant gate | not analyzed at paper level | `cohort_definition_gate` (8/16 over-flags) | unchanged structural issue |
| CRITICAL leakage | flagged as inflator of wFP | persists: 4 CRITICAL extra_flags × 4.0× weight = ~16/20 of wFP | not addressed by fix |

**Two qualifications on the delta:**

1. **Query asymmetry favors W23-D2**: W23-D2 used concatenated concern texts (≤4000 chars), which is a stronger retrieval signal than the 71-char KMI string used here per W24-01. The fact that PR-106's F1 still doubled with a weaker query means the fix dominates the query-quality effect on this paper. Re-running W24-05 with concern-text would likely push F1 higher still but would re-introduce the W23-D2 §3 circularity warning (5 / 20 matches at cosine=1.000 because retrieval pulled verbatim KB rows for the same paper).

2. **The fix is necessary but not sufficient**: even at F1=0.295, PR-106 is still below the W23-D2 macro mean (0.318). The remaining gap is W23-D2 §4's structural ceiling — multi-gate housekeeping concerns, same-gate concern competition, and CRITICAL-leakage from neighbor-paper retrieval. None of those move without W23-A2 methods-text extraction and a precision-budget cut.

**Verdict:** 67f7492 closes the bug it was scoped to close — PR-106 is the most-improved paper in the W23-D2 cohort, and the channel-mix evidence (3 exact_code + 1 semantic vs. 0 exact_code + 2 semantic) is direct, not inferential. NCPR remains research-preview per ADR 0007 Amendment 1; this case study does not change that, but it does validate that 67f7492 produces honest matcher numbers downstream.
