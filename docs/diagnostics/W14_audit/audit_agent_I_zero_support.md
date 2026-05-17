# Audit Agent I — Zero-Support Gates Investigation

**Date**: 2026-05-17
**Scope**: m5 finding — 2 of 33 MLGG gates have zero `gates_implementing` tags in
`references/methodology/literature-knowledge-base.json` (67 entries).
**Method**: read gate source, scan methodology KB (67) and peer-review KB (335
papers / 449 reviewer concerns), classify each gate as legit-no-lit /
missing-tag / KB-gap.

---

## Gate 1: `cohort_definition_gate`

### What it checks

Pre-split data understanding & sample adequacy (1936-line gate):

- Cohort size, class distribution, severe imbalance (>20:1) → cites van den
  Goorbergh 2022 in remediation `COHORT_SEVERE_IMBALANCE`.
- **EPV (Events Per Variable) and Riley 2019 minimum sample size** — module
  docstring lines 7, 18; functions at lines 224, 564, 1121, 1128; remediation
  `COHORT_RILEY_UNDERPOWERED` cites `Riley RD et al. Stat Med 2019;38:1276-1296`.
- Missingness profile, MCAR/MAR/MNAR documentation — remediation
  `COHORT_HIGH_MISSINGNESS` cites `Madley-Dowd 2019`.
- Cohort cascade (CONSORT-style) — remediation `COHORT_CASCADE_UNDOCUMENTED`
  cites `TRIPOD+AI 2024 Item 4a; STROBE Items 6-9`.
- Outcome-definition completeness (sources, subtype, time window, ascertainment)
  — remediations cite `TRIPOD+AI 2024 Item 6a` and `Eastwood 2016 (PLOS ONE)`
  for UKB diabetes adjudication (line 1435, 1491).
- Table 1 generation per `TRIPOD+AI 2024 Item 13a` (line 950).
- Codebook-RAG checks (PHI, embargoed fields, gated missingness, top-coding).

### In-code paper citations (verified)

Riley 2019 · Peduzzi 1996 · TRIPOD+AI 2024 (Items 4a/6a/13a) · STROBE (Items
6–9) · Madley-Dowd 2019 · van den Goorbergh 2022 · Eastwood 2016 · NHANES
analytic guidelines (CDC).

### `dimensions_affected` declarations

The gate does **not** declare a `dimensions_affected` constant in source — that
field lives only on KB entries, not on the gate side. The MLGG dimension map
(via `mlgg_dimension` in `peer-review-kb.json`) shows cohort concerns map
primarily to **dimension 1 (study design)** and **dimension 3 (missingness)** —
also 5 (sample size) and 8 (reporting).

### Cross-evidence from peer-review-kb.json

**207 of 449 reviewer concerns (46 %) are tagged to `cohort_definition_gate`**
(severity breakdown dominated by `study_design`: 172; `reporting`: 9;
`evaluation_metrics`: 7; `data_leakage`: 3; `sample_size`: 3; etc.). This is
the **most-triggered gate in the entire reviewer-concern corpus**, second only
to leakage_gate in real-world reviewer frequency. The gate is not aspirational
— it captures the single biggest class of reviewer objections.

### Verdict box

| Field | Value |
|---|---|
| **Verdict** | **MISSING-TAG** (primarily) + small KB-gap remainder |
| **Evidence** | Four KB entries directly back logic the gate operationalizes: LIT-001 (TRIPOD+AI — cited explicitly in 4 remediation strings for Items 4a/6a/13a); LIT-005 (Riley 2019 EPV — the gate runs Riley's formula in code); LIT-034 (Sterne 2009 MI/missing-data — the gate's MNAR/MCAR check); LIT-035 (van den Goorbergh 2022 — cited verbatim in `COHORT_SEVERE_IMBALANCE`). All four currently tag *only* their primary gate, never `cohort_definition_gate`. KB-gap remainder: Eastwood 2016 (UKB diabetes phenotyping) and Madley-Dowd 2019 are cited in code but absent from the KB. |
| **Proposed action** | Patch (1) tag LIT-001, LIT-005, LIT-034, LIT-035 with `cohort_definition_gate` as a secondary gate. Patch (2, separate, deferred) add Eastwood 2016 and Madley-Dowd 2019 as new LIT entries; also consider Torralbo 2025 (cited in the audit task brief) if relevant — not verified in this pass. |

---

## Gate 2: `shap_interpretability_gate`

### What it checks

Ensemble multi-model SHAP attribution (1450-line gate):

- Selects appropriate SHAP explainer per classifier family (Tree, Linear,
  Kernel, sampling fallback).
- Computes per-model `mean(|SHAP|)`, L1-normalises to proportions per model,
  averages across families → robust ensemble ranking. Cites
  **PMC11513550 (2024 SHAP practical guide)** for the proportional
  normalisation methodology.
- Cross-model rank-agreement (Kendall τ) — cites **arxiv 2505.24612**
  (multi-criteria rank-based aggregation for XAI, 2025).
- All-zero / NaN / extreme-concentration / suspicious-top-feature checks.
- Individual case explanations (Table D).
- Foundational citations: **Lundberg & Lee 2017 (NeurIPS)**, **Lundberg et al.
  2020 (Nat Mach Intell)**.

### `dimensions_affected` declarations

No source-side constant. Peer-review-KB concerns map this gate to the
`interpretability` category overwhelmingly (31 of 36 concerns).

### Cross-evidence from peer-review-kb.json

**36 reviewer concerns** tagged to `shap_interpretability_gate` — categories:
interpretability 31, reporting 2, evaluation_metrics 2, external_validation 1.
Concrete reviewer asks include SHAP summary plots across model variants,
Shapley beeswarm plots, ECG-specific SHAP interpretation with
positive/negative examples, and interpretability-vs-explainability framing.
The gate is field-grounded.

### Methodology-KB scan result

**Zero matching entries.** No KB entry contains "SHAP", "Lundberg",
"interpretab", "explain", "XAI", "feature attribution", or "black box" in
title/authors/key_concepts. The single near-hit (LIT-033 — Maier-Hein
"biomedical image analysis rankings") is *not* about SHAP and is correctly
tagged to seed/robustness/ci gates.

### Verdict box

| Field | Value |
|---|---|
| **Verdict** | **KB-GAP (true coverage gap)** |
| **Evidence** | The four papers the gate operationalises (Lundberg & Lee 2017 NeurIPS; Lundberg et al. 2020 Nat Mach Intell; PMC11513550 2024 SHAP practical guide; arXiv 2505.24612 2025 rank aggregation) are all absent from the 67-entry methodology KB. Peer-review-KB confirms 36 real reviewer concerns reference this gate, so it is not a vestigial / project-internal-rule gate. |
| **Proposed action** | No `.patch` is appropriate here — tagging is impossible until the papers exist as KB entries. Add four new entries (LIT-067 .. LIT-070): Lundberg & Lee 2017, Lundberg 2020, PMC11513550 2024, arXiv 2505.24612. Each new entry should set `gates_implementing: ["shap_interpretability_gate"]` and an appropriate `dimensions_affected` (likely dimension 8 reporting, plus a new "interpretability" dimension if the schema permits). This is a KB-growth task, not a tag fix — out of scope for the read-only audit pass. |

---

## Patch artefact

`/tmp/audit_agent_I_zero_support.patch` contains the unified diff for the four
**cohort_definition_gate** tag additions (LIT-001, LIT-005, LIT-034, LIT-035).
The SHAP gate cannot be patched in this pass because no source entries exist.

---

## Implications for audit conclusion m5 — does it stay Minor or upgrade?

**Recommend upgrading m5 from Minor to Major.**

Justification:

- The original m5 finding ("2 gates lack KB literature support") is more
  serious than the count suggests because these are not minor gates. Combined,
  the two affected gates account for **243 of 449 reviewer concerns (54 %)**
  in the peer-review case-study corpus — i.e. more than half of all real-world
  reviewer objections route through gates whose literature backing is
  currently invisible in the methodology KB.
- For `cohort_definition_gate`: the literature *does* exist but the tagging
  graph is broken — a reviewer reading the KB cannot trace the gate to its
  Riley / TRIPOD+AI / Sterne / van den Goorbergh authority. This is a
  publication-grade traceability defect (TRIPOD+AI 2024 Item 23 — model
  reporting transparency).
- For `shap_interpretability_gate`: the foundational interpretability
  literature is genuinely absent from the methodology KB. Given SHAP is now a
  near-universal reviewer ask (31 interpretability concerns in the corpus),
  publishing this gate without KB backing is a coverage gap, not a stylistic
  one.
- Both defects are individually fixable in <1 hour (one patch + four new KB
  entries), but the audit conclusion should record the gap as Major because
  it concerns *literature traceability of fail-closed gates* — the same axis
  that motivates having the methodology KB in the first place.

If the user prefers to keep m5 as Minor for scoping reasons, the minimum
acceptable mitigation is to apply the `/tmp/audit_agent_I_zero_support.patch`
for the cohort gate immediately and file the SHAP KB-gap as a tracked
follow-up issue.
