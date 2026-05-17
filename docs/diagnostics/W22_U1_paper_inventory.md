# W22-U1 — Paper Inventory for NCPR Holdout Selection

**Status:** PASS (104 eligible papers, well above N=30 holdout target)
**Date:** 2026-05-17
**KB:** `references/case-studies/peer-review-kb.json` (contract `peer_review_kb.v1.4`, 335 entries)
**Detail JSON:** `/tmp/W22_U1_paper_inventory.json`

## Definitions

- **Curated**: entry has non-empty `reviewer_concerns` AND no `out_of_scope_reason`. (No explicit `status` field exists in the KB.) → **154 papers** (matches task spec).
- **In eval set**: paper_id appears in `references/retrieval_eval/labeled_precision_at_5.json` or `references/case-studies/rag-eval-set.yaml`. `scenarios.json` yielded no `PR-*` references.
- **Eligible for holdout**: curated AND not in eval set AND `peer_review_pdf_path` resolves on disk.

Note: no KB entry has a `methods_text` or `methods_extract` field; the input-availability proxy used is the on-disk peer-review PDF (all 154 curated papers have one).

## Headline numbers

| Metric | Count |
|---|---|
| Curated total | 154 |
| Curated with PDF on disk | 154 (100%) |
| Curated with ≥3 concerns | 131 |
| Curated referenced in eval sets (INELIGIBLE) | 50 |
| **Eligible for holdout** | **104** |
| Eligible AND ≥3 concerns | 83 |

## Histograms

### Journal
| Journal | Curated |
|---|---|
| Nature Communications | 150 |
| Communications Medicine | 4 |

Heavy NComms skew — holdout sampling should not stratify on journal (insufficient diversity).

### Publication year
| Year | Curated |
|---|---|
| 2020 | 9 |
| 2021 | 12 |
| 2022 | 13 |
| 2023 | 19 |
| 2024 | 36 |
| 2025 | 59 |
| 2026 | 6 |

### Concern count per paper
| Bucket | Papers |
|---|---|
| 1–2 | 23 |
| 3–5 | 61 |
| 6–10 | 61 |
| 11+ | 9 |

### Severity distribution (across all concerns in curated set)
| Severity | Count |
|---|---|
| CRITICAL | 41 |
| HIGH | 304 |
| MEDIUM | 412 |
| LOW | 60 |

### Category bucket distribution
| Bucket | Count |
|---|---|
| evaluation | 264 |
| other | 197 |
| design | 172 |
| reporting | 126 |
| leakage | 58 |

`other` bucket is large because raw KB categories include `preprocessing`, `interpretability`, `study_design` (mapped → design), etc. that don't cleanly match the five task-spec buckets. Underlying raw categories retained per-paper in JSON.

## Top 5 candidate holdout papers (by concern count)

| paper_id | journal | year | # concerns | eligible |
|---|---|---|---|---|
| PR-EXP-0084 | Nature Communications | 2026 | 15 | yes |
| PR-EXP-0160 | Nature Communications | 2021 | 15 | yes |
| PR-EXP-0086 | Nature Communications | 2026 | 14 | yes |
| PR-EXP-0097 | Nature Communications | 2025 | 14 | yes |
| PR-EXP-0109 | Nature Communications | 2024 | 14 | yes |

All top-5 are eligible — none leak into existing eval sets.

## Verdict

**PASS.** 104 eligible papers gives 3.4× the N=30 holdout target with comfortable room for stratified sampling on year, concern count, and severity mix. Even after restricting to ≥3 concerns (signal-rich), 83 candidates remain.

## Risks / caveats

- Journal monoculture (96% NComms) — holdout cannot test cross-journal generalization. Flag for W22-X7.
- Severity field is heavy on MEDIUM (412/817 across curated). Holdout should up-weight CRITICAL/HIGH papers to keep failure-mode signal density high.
- No `methods_text` cached in KB — W22-X7 must extract from PDF at build time (cost: 104 PDFs × parse).

## Hand-off to W22-X7 (build_holdout)

Consumer of `/tmp/W22_U1_paper_inventory.json`:
- `records[*].eligible_for_holdout == true` → candidate pool (n=104).
- Recommend stratified sample: ≥1 concern severity CRITICAL preferred; cover year buckets 2020–2026; cover all 5 category buckets where possible.
- PDF paths under `peer_review_pdf_path` ready for methods extraction.
