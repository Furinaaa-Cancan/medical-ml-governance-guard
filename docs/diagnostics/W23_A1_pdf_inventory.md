# W23-A1: NCPR v2 PDF Inventory

**Scope.** Audit real-PDF coverage under `references/case-studies/<journal>/` and cross-check against `peer-review-kb.json` (335 entries). Goal: confirm we have ≥30 KB-matched PDFs to seed high-quality NCPR v2 methods extraction (W23-A2).

## 1. Filesystem totals

- 382 real PDF files (resource forks `._*` excluded).
- 900.3 MB on disk; min 29.5 KB, max 32.8 MB.
- Magic-number check (`file(1)`): 0 files with non-PDF magic. **0 corrupted.**
- Suspiciously small (<50 KB): 3 — review during W23-A2:
  - `communications_medicine/s43856-025-01189-8_peer_review.pdf` (29.5 KB)
  - `nature_communications/s41467-021-24485-y_peer_review.pdf` (47.9 KB)
  - `nature_communications/s41467-021-24773-7_peer_review.pdf` (40.0 KB)

## 2. Per-journal PDF counts

| Folder                  | PDFs | Sample basenames |
|-------------------------|-----:|------------------|
| nature_communications   | 291  | `02_osteoarthritis_risk_ML_peer_review.pdf`, `03_TransformEHR_peer_review.pdf`, `04_AI_sepsis_prediction_peer_review.pdf`, `08_biology_guided_DL_cancer_peer_review.pdf`, `09_colorectal_cancer_survival_peer_review.pdf` |
| communications_medicine |  82  | `s43856-021-00020-4_peer_review.pdf`, `s43856-021-00069-1_peer_review.pdf`, `s43856-022-00127-2_peer_review.pdf`, `s43856-022-00129-0_peer_review.pdf`, `s43856-022-00133-4_peer_review.pdf` |
| specialist_journals     |   8  | All under `extraction_verification/*/paper.pdf` (Pesaranghader 2026, Li 2026 MARCH, Zeba 2025, Schmidt 2024, Wang 2024 SciDaSynth, Poser 2026, Cao 2025 OttoSR, Li 2025 SciEx) |
| _quarantine             |   1  | `PR-040_sepsis_management_prediction_model_infer_peer_review.pdf` |

Note: `bmj/`, `jama/`, `lancet_digital_health/`, `nature_medicine/`, `npj_digital_medicine/` folders exist but contain **0 PDFs** (likely manifest-only or text-only sources). Confirms NCPR PDF corpus is dominated by Nature Communications + Communications Medicine — i.e. Nature-portfolio open peer review, as expected.

## 3. PDF ↔ KB cross-reference

KB entries: **335** (every entry has a `peer_review_pdf_path` field).

| Bucket                                  | Count | Notes |
|-----------------------------------------|------:|-------|
| **Matched** (FS PDF found in KB)        |  331  | 86.6% of FS PDFs are KB-curated. |
| **PDF-only** (FS PDF, no KB entry)      |   51  | 42 in `nature_communications/` (legacy `NN_*`, `CM_*`, `NC_*` slugs), 8 in `specialist_journals/extraction_verification/` (LLM-extraction lit, off-task for NCPR), 1 in `_quarantine/`. |
| **KB-only** (KB path missing on disk)   |    1  | `PR-EXP-0007` → `communications_medicine/s43856-026-01417-9_peer_review.pdf` (future-dated 2026 paper; likely embargoed or path drift). |

Artifacts: `/tmp/W23_A1_matched.txt`, `/tmp/W23_A1_pdf_only.txt`, `/tmp/W23_A1_kb_only.txt`, `/tmp/W23_A1_priority50.txt`.

## 4. Reviewer-concern distribution (KB-side richness)

Among the 335 KB entries:

| concerns | papers |
|---------:|-------:|
| 0        |  181   |
| 1–2      |   23   |
| 3–5      |   61   |
| 6–10     |   61   |
| >10      |    9   |

≥3 concerns: **131 papers**. ≥5 concerns: **90 papers**. Plenty of headroom above the 30-paper W23-A2 target — the binding constraint is reviewer-concern depth, not PDF supply.

## 5. Verdict

**Yes — sufficient PDFs for high-quality NCPR v2.** 331 KB-matched real PDFs (target was ≥30, 11× over). 0 corrupted. 1 KB-only gap (PR-EXP-0007), 3 small files worth a manual sniff in A2.

## 6. Handoff to W23-A2 (methods extraction)

**Priority list:** top-50 by reviewer-concern count saved to `/tmp/W23_A1_priority50.txt`. All 50 are Nature Communications, all KB-matched, all readable. Top 10 (concerns / size):

1. PR-EXP-0084 (15, 2.3 MB, 2026)
2. PR-EXP-0160 (15, 0.6 MB, 2021)
3. PR-EXP-0109 (14, 5.5 MB, 2024)
4. PR-EXP-0097 (14, 0.6 MB, 2025)
5. PR-EXP-0086 (14, 0.4 MB, 2026)
6. PR-EXP-0095 (12, 5.6 MB, 2025)
7. PR-EXP-0110 (11, 2.5 MB, 2024)
8. PR-003 (11, 0.9 MB, 2024)
9. PR-EXP-0212 (11, 0.3 MB, 2020)
10. PR-EXP-0106 (10, 3.9 MB, 2025)

W23-A2 recommendation: take the top 30 from this list as the NCPR v2 methods-extraction seed. Defer the 51 PDF-only files to a later curation pass (the 8 `extraction_verification/` PDFs are off-task for NCPR and belong to a separate corpus).
