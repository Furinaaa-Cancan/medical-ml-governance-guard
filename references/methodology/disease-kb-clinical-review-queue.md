# Disease-KB — clinical review queue

Candidate additions to `disease-definition-knowledge-base.json` that an automated audit
**surfaced but must NOT apply unattended**, because they cross from "synonym of an
already-represented variable" into a **new clinical defining variable / instrument**. Per
CLAUDE.md S1 and the disease-KB's own `clinician_review_status` discipline, these need a
clinician sign-off (and ideally a guideline citation) before they enter the KB.

## Pending — from the 2026-06-06 synonym-coverage audit (v1.3)

The audit added 41 unambiguous synonyms (see change_log v1.3). These 4 were **held back**:

| Disease | Candidate token | Why deferred | If approved, cite |
|---|---|---|---|
| chronic_kidney_disease | `albuminuria` | A **distinct KDIGO defining axis** (A1–A3), not literally an abbreviation of the listed `uacr`/`albumin_creatinine_ratio`. Adding it broadens the definitional net. | KDIGO 2024 CKD guideline (albuminuria staging) |
| major_depressive_disorder | `bdi` | Beck Depression Inventory — a **different instrument** from the PHQ-9 / PHQ-2 / CES-D already listed. New clinical scale, not a synonym. | DSM-5-TR; BDI-II validation |
| major_depressive_disorder | `bdiii` | BDI-II, same as above. | same |
| atrial_fibrillation | `afburden` | "AF burden" is a **severity quantity** (% time in AF), not the diagnosis variable; definitional status is ambiguous. | clarify intended use first |

**Decision needed (per item):** approve into `definition_variables_to_exclude` (and set the
disease's `clinician_review_status` accordingly), or reject as out of scope.

## Standing debt (not from this audit)

All 11 disease entries still carry `clinician_review_status = pending` (`provenance.source =
llm_compiled`, since v1.1). The synonym audit did **not** change that — it only expanded
abbreviation coverage of variables already in each list. Any publication-grade claim that
leans on the disease-KB still requires a clinician to review the entries + attach guideline
citations. See the disease-KB `provenance` fields and the project memory on KB provenance.
