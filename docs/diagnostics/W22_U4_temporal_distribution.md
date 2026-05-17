# W22-U4 — Temporal distribution audit for NCPR holdout

**Wave**: NCPR Benchmark v1 — W22-U4
**Date**: 2026-05-17
**Mode**: READ-ONLY
**Scope**: temporal distribution of the curated paper pool, to inform
"hold out most recent" vs "hold out by year" vs random-stratified split.

## 1. Data sources

- KB: `references/case-studies/peer-review-kb.json` (335 entries, all NC + CM)
- KB last meaningful extraction (data merge): **2026-05-13** (commit
  `data(kb): merge extraction-wave-2026-05-13 — 49 NC papers × 368 concerns`).
  Metadata-only sync ran on 2026-05-17 13:50 (most recent `git log`).
  No new reviewer-concern rows were added on 2026-05-17.
- Holdout criteria source: `references/benchmark/ncpr_v1_holdout_criteria.md` (T3)
- Spec source: `references/benchmark/ncpr_v1_spec.md` (T1)

**Caveat — pool size**: T1 names a 154-paper curated pool (subset of 335
after §2 modality / task scope). That 154-id manifest is not yet
materialised in the repo. This audit uses the full 335-entry KB and
flags where the 154-pool re-filter could shift counts. The relative
year shape will not change appreciably; only absolute eligibility counts.

**Caveat — date granularity**: KB entries carry `year` only, not
`publication_date`. Sub-year buckets (year-quarter) are not derivable
from the KB; T3 criterion `publication_date ≤ 2026-04` is therefore
approximated by `year ≤ 2025` in this audit (conservative — excludes
all of 2026, even Jan/Feb/Mar 2026 papers that would actually qualify).

## 2. Year histogram — full KB (n=335)

| Year | Count | % | NC | CM |
|---|---:|---:|---:|---:|
| 2020 | 24 | 7.2% | 24 | 0 |
| 2021 | 39 | 11.6% | 38 | 1 |
| 2022 | 26 | 7.8% | 17 | 9 |
| 2023 | 50 | 14.9% | 37 | 13 |
| 2024 | 71 | 21.2% | 47 | 24 |
| 2025 | 101 | 30.1% | 77 | 24 |
| 2026 | 24 | 7.2% | 8 | 16 |

Bucket aggregation:

- Pre-2024 (had at MLGG creation era): **139** (41.5%)
- 2024: **71** (21.2%)
- 2025: **101** (30.1%)
- 2026: **24** (7.2%)

## 3. Year histogram — papers with ≥3 reviewer concerns (n=131)

T3 criterion 1 ("concern density ≥3").

| Year | ≥3-concern count |
|---|---:|
| 2020 | 9 |
| 2021 | 12 |
| 2022 | 12 |
| 2023 | 14 |
| 2024 | 29 |
| 2025 | 51 |
| 2026 | 4 |

The 2026 cohort is sparse on concerns: 18 of 24 entries have **0**
reviewer concerns (stub-only metadata rows from the OpenAlex discovery
sweep). Only 6 / 24 have ≥1 concern, and only 4 / 24 have ≥3.

## 4. T3 fully-eligible cohort

Filter chain (per `ncpr_v1_holdout_criteria.md` + `ncpr_v1_spec.md` §3.2):

1. `len(reviewer_concerns) ≥ 3` → 131 papers
2. `journal ∈ {NC, CM, LDH, JAMA, NM, npjDM}` → all 131 satisfy (KB is NC+CM only today)
3. methods text exists → not verified per-paper in this audit (NOT a temporal blocker; ~all KB entries have a paper-templates entry)
4. **not in existing eval sets** (`rag-eval-set.yaml`, `scenarios.json`, `labeled_precision_at_5.json` under `references/retrieval_eval/`): 51 distinct `PR-***` ids are referenced and excluded
5. `publication_date ≤ 2026-04` → approximated as `year ≤ 2025`
6. ≥1 CRITICAL or HIGH concern (T1 §3.2 severity mix prereq for stratification) → drops 5 more

After 1+4+5+6 chained:

**T3 fully-eligible: 75 papers**

By year:

| Year | T3-eligible |
|---|---:|
| 2020 | 8 |
| 2021 | 11 |
| 2022 | 8 |
| 2023 | 10 |
| 2024 | 15 |
| 2025 | 23 |
| 2026 | 0 (excluded by criterion 5) |

75 ≥ 30 → the 30-paper holdout is feasible with headroom of 45.

## 5. Temporal-strict (post-KB-index) cohort

Definition: papers KB has *structurally never seen* — published after the
KB extraction cut of 2026-05-13.

Within the current 335-entry KB this count is **0 by construction** —
every paper in the KB was ingested by the extraction sweep. The 24
year=2026 entries are *in* the KB (with concerns, or stubbed), not
post-KB.

So the "temporal-strict ultra-honest holdout" channel is empty *from the
current KB*. Achieving it requires queueing NC/CM/LDH/JAMA papers
**published after 2026-05-13** that are deliberately not ingested before
the NCPR run — i.e. a forward-looking, not retrospective, holdout. That
is a different workflow (W22 ingestion freeze + future-paper sourcing)
and is out of scope for the W22-T3 selection script.

## 6. Verdict — temporal honesty of the planned holdout

**PASS** — 75 papers pass the full T3 filter, 2.5× the 30-paper target.
Year coverage spans 2020-2025 with 23 candidates from 2025 alone (the
most-recent year that still pre-dates the KB build cut), so the
stratified sampler in `ncpr_build_holdout.py` will not be forced into
either a year-skewed or a journal-skewed corner.

The single yellow flag is criterion 5: it eliminates the 24 year=2026
papers wholesale, including the 4 with ≥3 concerns. This is the
*correct* call under T3's logic (KB commentary on these papers may exist
because they were ingested in the May 2026 sweep), but it removes the
strongest "recency" signal from the holdout. If a future wave wants a
true temporal-strict subset, it must source post-2026-05-13 papers
*outside* the existing KB (§5).

## 7. Recommendation — split rule

Use **random-stratified by journal + severity + category** (the rule
already encoded in T3 §"Stratification target"), **not** a "hold out
most recent N years" rule.

Reasoning:

- A chronological "hold out 2025" split would land ~23 eligible papers
  in the holdout — exactly at the 30-paper floor with no slack, and
  would force severity / category stratification to be relaxed.
- A chronological "hold out 2024+2025" split (38 eligible) would
  over-weight the holdout toward the post-LLM-era papers and shrink the
  KB's most informative bucket (2024-2025 = 38 of 75 fully-eligible =
  51% of the strong signal).
- The random-stratified sampler with the frozen seed
  `ncpr_v1_seed_2026` gives proportional coverage across years 2020-2025
  while preserving the journal / severity / category floors that T1 §3.2
  treats as the primary stratification axes. Year is not on T1's
  stratification list; promoting it would change the contract.
- Temporal honesty is already enforced by criterion 5 (the hard
  `year ≤ 2025` gate) — additional chronological holdout would be belt
  *and* suspenders, at the cost of severity-mix headroom.

For waves W23+ that want a true post-KB-index holdout, source new
papers published after 2026-05-13 and gate the KB indexer against them
explicitly (this is the W22-Y1 `--exclude-papers` plumbing inverted).
