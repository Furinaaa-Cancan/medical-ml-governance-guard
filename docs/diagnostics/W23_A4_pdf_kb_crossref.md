# W23-A4: NCPR v2 PDF × KB Cross-Reference

Computes the intersection of `references/case-studies/peer-review-kb.json` (335 curated entries) and on-disk peer-review PDFs (393 files), then filters to the v2-eligible candidate pool. Read-only audit.

## Inputs

- KB snapshot: `references/case-studies/peer-review-kb.json` (335 entries, journals: Nature Communications 248, Communications Medicine 87)
- PDF inventory: 393 PDFs under `references/case-studies/` (per W23-A1)
- Existing eval-set PR-ids (excluded): 51, parsed from `references/case-studies/rag-eval-set.yaml`, `references/retrieval_eval/labeled_precision_at_5.json`, `references/retrieval_eval/scenarios.json`

## Three-set Venn

```
KB-only       PDF-only        BOTH (KB ∩ PDF)
    1            63              334
```

- **KB-only (1)**: `PR-EXP-0007` (Communications Medicine, declared path `s43856-026-01417-9_peer_review.pdf` not on disk — single missing PDF)
- **PDF-only (63)**: PDFs present but no matching KB entry. Breakdown by directory:
  - `nature_communications/`: 53 (incl. 5 in `ukb_mdrmf/`)
  - `communications_medicine/`: 1
  - `_quarantine/`: 2
  - `specialist_journals/extraction_verification/`: 8 (methodology references, not study papers)
- **BOTH (334)**: 99.7% KB coverage by on-disk PDFs. PDF readability check (`file -b`) returns "PDF document" for **334/334** — zero unreadable.

## Per-journal breakdown of BOTH set

| Journal | BOTH count | KB total | Coverage |
|---|---:|---:|---:|
| Nature Communications | 248 | 248 | 100% |
| Communications Medicine | 86 | 87 | 98.9% |
| (other journals from holdout spec: LDH, JAMA, NM, npjDM) | 0 | 0 | n/a |

**Important finding**: KB currently contains **only** Nature Communications and Communications Medicine entries, despite the W22-T3 holdout spec listing 6 eligible journals. LDH / JAMA / Nature Medicine / npj Digital Medicine are 0 in the KB. Cross-journal generalisation claims for NCPR v2 are not supportable from this KB alone.

## Filter cascade to v2 candidate pool

| Filter | Remaining |
|---|---:|
| KB entries | 335 |
| AND PDF on disk (BOTH) | 334 |
| AND PDF readable | 334 |
| AND `len(reviewer_concerns) >= 3` | 131 |
| AND NOT in existing eval sets (51 excluded PR-ids) | **83** |
| AND `>= 1` reviewer_concern with severity CRITICAL or HIGH | **79** |

**v2 candidate pool: 79 papers** (passes W22-T3 severity floor; journal floor and category floor still need to be re-checked by the stratifier).

Per-journal of v2 pool: Nature Communications 78, Communications Medicine 1. The lone CM entry survives because most CM papers were already consumed by labeled_precision_at_5 / rag-eval-set.

## Top 30 from v2 pool (quality score)

Score = `len(concerns) + 3*n_CRITICAL + 1*n_HIGH`. All from Nature Communications.

| Rank | PR-id | concerns | CRIT | HIGH | qs |
|---:|---|---:|---:|---:|---:|
| 1 | PR-EXP-0097 | 14 | 3 | 4 | 27 |
| 2 | PR-EXP-0160 | 15 | 0 | 9 | 24 |
| 3 | PR-EXP-0095 | 12 | 2 | 5 | 23 |
| 4 | PR-EXP-0084 | 15 | 0 | 5 | 20 |
| 5 | PR-EXP-0109 | 14 | 1 | 3 | 20 |
| 6 | PR-EXP-0170 | 8 | 3 | 2 | 19 |
| 7 | PR-EXP-0086 | 14 | 0 | 4 | 18 |
| 8 | PR-EXP-0110 | 11 | 1 | 4 | 18 |
| 9 | PR-RO-07 | 10 | 1 | 5 | 18 |
| 10 | PR-EXP-0105 | 8 | 1 | 4 | 15 |
| 11 | PR-EXP-0085 | 10 | 0 | 4 | 14 |
| 12 | PR-EXP-0106 | 10 | 0 | 4 | 14 |
| 13 | PR-EXP-0212 | 11 | 0 | 3 | 14 |
| 14 | PR-042 | 6 | 1 | 4 | 13 |
| 15 | PR-EXP-0119 | 9 | 0 | 4 | 13 |
| 16 | PR-EXP-0150 | 7 | 1 | 3 | 13 |
| 17 | PR-EXP-0197 | 8 | 1 | 2 | 13 |
| 18 | PR-EXP-0200 | 7 | 0 | 6 | 13 |
| 19 | PR-EXP-0209 | 8 | 1 | 2 | 13 |
| 20 | PR-EXP-0098 | 9 | 0 | 3 | 12 |
| 21 | PR-EXP-0101 | 9 | 0 | 2 | 11 |
| 22 | PR-EXP-0103 | 7 | 0 | 4 | 11 |
| 23 | PR-EXP-0112 | 9 | 0 | 2 | 11 |
| 24 | PR-EXP-0092 | 6 | 1 | 1 | 10 |
| 25 | PR-EXP-0096 | 8 | 0 | 2 | 10 |
| 26 | PR-EXP-0159 | 6 | 0 | 4 | 10 |
| 27 | PR-EXP-0205 | 6 | 1 | 1 | 10 |
| 28 | PR-056 | 4 | 1 | 2 | 9 |
| 29 | PR-EXP-0126 | 7 | 0 | 2 | 9 |
| 30 | PR-EXP-0127 | 6 | 0 | 3 | 9 |

Full ranking (79 entries): `/tmp/W23_A4_v2_pool.json`. Cross-check with W23-A3 score (max 13): all top-30 papers above score ≥10 in A3 (overlap with A3 high-quality set of 122 entries scoring ≥10).

## Verdict: PASS (with caveat)

- v2 pool size: **79** ≥ 60 → **PASS** for a 30-paper holdout.
- Severity floor (≥1 CRIT/HIGH per paper) is already satisfied by every pool entry.
- Headroom: 79 − 30 = 49 reserve for tie-breaking / category-floor adjustment.
- **W23-A5 not required for v2 feasibility**. KB + on-disk PDFs are sufficient.

### Caveat (must be recorded in v2 ADR)

- **Journal monoculture**: 78/79 pool entries are Nature Communications. The W22-T3 proportional journal-floor rule (`no journal contributes >40% of holdout`) is **infeasible** for v2. Recommended handling per W22-T3 failure table: prefer category floor over journal floor, log under `stratification_deviations`.
- v2 generalisation evidence will therefore be NC-only. If cross-journal claims are required for publication, escalate to W23-A5 to source LDH/JAMA/NM/npjDM peer-review PDFs and extend the KB before building the holdout.

## Artefacts

- `/tmp/W23_A4_summary.json` — Venn + filter counts
- `/tmp/W23_A4_both_set.json` — 334 BOTH entries
- `/tmp/W23_A4_v2_pool.json` — 79 pool entries with quality scores
- `/tmp/W23_A4_pdf_only.json` — 63 PDFs not referenced by KB
- `/tmp/W23_A4_kb_only.json` — 1 KB entry missing PDF (PR-EXP-0007)
