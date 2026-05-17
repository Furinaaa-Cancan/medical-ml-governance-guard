# W23-D1: NCPR v2 Holdout Dry-Run

**Status**: blocked (partial fill, two stratification floors miss)
**Date**: 2026-05-17
**Wave**: NCPR v2 build
**Artifact**: `/tmp/W23_D1_holdout_v2_dryrun.json`

## Method

Read-only dry-run. Re-implements v2 criteria from
`references/benchmark/ncpr_v2_holdout_criteria.md` inline (W23-C3
`ncpr_quality_filter.py` does not yet exist; quality_score derived
from W23-A3 13-pt rubric, threshold ≥ 7 per v2 spec). Pool:
`peer-review-kb.json` (335 entries); excluded any PR-id appearing in
`scenarios.json`, `labeled_precision_at_5.json`, or
`rag-eval-set.yaml`.

## Result: 30 selected / 30 target, but two floors unmet

```
eligible_count : 51
n_selected     : 30
status         : feasible-by-count, blocked-by-stratification
```

Rejection histogram (cascade order):

| Reason                | N   |
|---|---:|
| not_NC                | 87  |
| in_eval               | 74  |
| stub_or_<3_concerns   | 115 |
| year>2025             | 5   |
| no_CRIT_or_HIGH       | 3   |
| quality_score<7       | 0   |
| pdf_missing           | 0   |
| sparse_severity       | 0   |

(Order matters: each row counts papers that first failed there.)

## Stratification adherence

| Floor                       | Target | Observed | Met |
|---|---:|---:|---:|
| Papers with CRITICAL        | ≥ 8    | 7        | NO  |
| Papers with HIGH            | ≥ 18   | 29       | yes |
| `evaluation` papers         | ≥ 4    | 28       | yes |
| `design` papers             | ≥ 4    | 22       | yes |
| `reporting` papers          | ≥ 4    | 23       | yes |
| `external_validation`       | ≥ 4    | 8        | yes |
| `leakage` papers            | ≥ 4    | 0        | NO  |

Year mix (selected 30): 2020=1, 2021=4, 2022=2, 2023=8, 2024=5, 2025=10.

## Binding constraints

1. **CRITICAL floor (7 < 8)**. Total NC CRITICAL papers = 31, but
   after eval-set exclusion + stub filter + quality≥7, only **7
   eligible** carry CRITICAL. Even taking all 7, we cannot reach 8.
2. **`leakage` floor (0 < 4)**. Only 9 NC papers in KB carry any
   `data_leakage` concern. **All 9 are in `labeled_precision_at_5.json`**
   (and `PR-006` / `PR-010` / `PR-072` also in `rag-eval-set.yaml`).
   The eval-set exclusion empties the leakage column to zero.

## Per-paper selected (30)

| paper_id | year | concerns | qs | sev |
|---|---:|---:|---:|---|
| PR-015 | 2023 | 3 | 11 | H |
| PR-020 | 2025 | 5 | 13 | H |
| PR-021 | 2025 | 4 | 11 | H |
| PR-043 | 2025 | 5 | 12 | H |
| PR-044 | 2024 | 3 | 11 | H |
| PR-049 | 2024 | 3 | 10 | H |
| PR-050 | 2023 | 4 | 11 | H |
| PR-051 | 2025 | 3 | 10 | H |
| PR-056 | 2025 | 4 | 10 | C+H |
| PR-058 | 2024 | 4 | 11 | H |
| PR-062 | 2023 | 3 | 11 | H |
| PR-064 | 2023 | 3 | 10 | H |
| PR-065 | 2023 | 4 | 11 | H |
| PR-067 | 2023 | 4 | 11 | H |
| PR-073 | 2022 | 3 | 11 | H |
| PR-074 | 2023 | 3 | 11 | H |
| PR-077 | 2025 | 3 | 10 | H |
| PR-106 | 2025 | 6 | 13 | H |
| PR-EXP-0101 | 2025 | 9 | 11 | H |
| PR-EXP-0105 | 2025 | 8 | 11 | C+H |
| PR-EXP-0124 | 2024 | 6 | 11 | H |
| PR-EXP-0127 | 2024 | 6 | 11 | H |
| PR-EXP-0147 | 2022 | 5 | 11 | H |
| PR-EXP-0150 | 2022 | 7 | 11 | C+H |
| PR-EXP-0170 | 2021 | 8 | 11 | C+H |
| PR-EXP-0187 | 2021 | 4 | 9 | H |
| PR-EXP-0189 | 2021 | 4 | 9 | C |
| PR-EXP-0194 | 2021 | 6 | 11 | H |
| PR-EXP-0209 | 2020 | 8 | 11 | C+H |
| PR-RO-07 | 2025 | 10 | 11 | C+H |

All 30 have a verified PDF on disk (`peer_review_pdf_path` resolved).

## Verdict: blocked

Cannot satisfy v2 stratification with current KB + eval-set scope.

## Unblock options (cheapest first)

1. **Relax `leakage` floor or accept 0**. NC + new-eval pool has zero
   `data_leakage`-tagged concerns; the v2 spec floor is structurally
   infeasible against the current corpus.
   *Cost*: ADR + benchmark loses leakage-detection signal entirely.
2. **Exempt high-value leakage papers from eval-set exclusion** (e.g.
   keep PR-006, PR-010, PR-107, PR-109 in v2 holdout despite being in
   lp5). Trades retrieval-eval purity for content coverage.
   *Cost*: cross-contamination with `labeled_precision_at_5`; needs
   matched lp5 re-sampling.
3. **Lower CRITICAL floor 8 → 6** (achievable from 7-paper pool with
   one paper carrying both bands). *Cost*: weakens "premium" claim.
4. **Re-tag NC concerns**: 9 leakage papers + 24 missing-CRITICAL NC
   papers exist outside lp5; relabel `study_design`/`preprocessing`
   concerns whose text mentions leakage. *Cost*: curation pass, ADR for
   re-tag policy, must avoid post-hoc fitting.

Recommend option 1+3 (relax leakage floor + lower CRITICAL to 6) as
the only path that keeps eval-set purity intact.
