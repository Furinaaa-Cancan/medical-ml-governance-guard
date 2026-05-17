# NCPR Benchmark v2 — Holdout Paper Selection Criteria

**Status**: pre-registered (W23-B3)
**Date**: 2026-05-17
**Wave**: NCPR v2
**Supersedes**: `ncpr_v1_holdout_criteria.md` (kept for audit; v1 holdout JSON
remains valid for v1 numbers only).

## Goal

Select **30 high-quality Nature Communications papers** for a held-out test
set that pressures the `/mlgg` retrieval+review stack on (a) non-trivial
concern counts, (b) at least one strong-severity concern per paper, and
(c) balanced category coverage. v2 narrows journal scope to a single venue
(NC) so that retrieval evaluation isolates concern-detection skill from
journal-style confounds present in v1's six-journal mix.

Pre-registration applies: a paper is eligible iff metadata fields and
artefacts listed below hold. No per-paper reviewer judgement during
selection — only deterministic filter + stratifier + tiebreaker.

## Source pool

`references/case-studies/peer-review-kb.json` papers with
`journal == "nature_communications"` and `status == "curated"`.

## Inclusion criteria (ALL must hold)

A paper is **eligible** iff:

1. **Curation gate**: present in KB with `status == "curated"` and
   `reviewer_concerns` non-empty.
2. **Journal**: `journal == "Nature Communications"` (normalised key
   `nature_communications`).
3. **Concern count**: `len(reviewer_concerns) >= 3`.
4. **Severity floor**: at least one concern with
   `severity in {"CRITICAL", "HIGH"}` — ensures the paper exerts a real
   test signal rather than only nits.
5. **Quality score**: `quality_score >= 7` per W23-A3 rubric (5-axis,
   0–10, validated inter-rater κ in A3 report).
6. **PDF availability**: file exists at
   `references/case-studies/<journal>/<paper_id>.pdf` per W23-A4 layout.
7. **No leakage into eval**: `paper_id` is NOT present in any of
   `scenarios.json`, `labeled_precision_at_5.json`, `rag-eval-set.yaml`,
   `ncpr_v1_holdout.json`, or any other file under
   `references/benchmark/*.json` with an `*_ids` list.
8. **Year**: `publication_year <= 2025` (cuts 2026 papers whose post-pub
   commentary cannot yet have leaked but whose review traces also have
   not yet stabilised).

Criteria 1–8 are evaluated by `scripts/rag/evals/ncpr_v2_build_holdout.py`
(W23-B6, planned); the script writes the filtered eligible set + rejection
reason histogram to stderr for audit.

## Quality enforcement (rejection sub-rules)

Applied during criterion 1 evaluation, before counting concerns:

- **Stub-text rejection**: drop any individual `reviewer_concern` whose
  `text` field has fewer than **30 characters** (likely a placeholder /
  stub left by mid-curation). If after dropping stubs the paper falls
  below criterion 3 (≥3 concerns), the paper itself is rejected.
- **Severity-coverage rejection**: if more than **50%** of a paper's
  surviving `reviewer_concerns` lack a `severity` field (or have severity
  `null`/`""`), reject the whole paper — severity stratification cannot
  be trusted on a paper whose annotation is half-blank.

Both rejections are logged with reason codes `STUB_TEXT` and
`SPARSE_SEVERITY` in the builder's stderr histogram.

## Stratification target (across the 30 selected papers)

- **Severity mix**:
  - at least **8 papers** with ≥1 `CRITICAL` concern;
  - at least **18 papers** with ≥1 `HIGH` concern (CRITICAL papers count
    toward HIGH if they also carry a HIGH concern; the two bands are
    measured independently, so a paper can satisfy both floors).
- **Category mix** (NCPR 5 dimensions): each of
  - `evaluation`
  - `design`
  - `reporting`
  - `external_validation`
  - `leakage`

  is covered by **≥4 papers** (i.e. ≥13% of the 30-paper holdout has
  at least one concern in that dimension). A single paper can satisfy
  multiple dimensions.
- **Year balance**: distribution across `publication_year` is roughly
  proportional (±2 papers) to the year distribution of the eligible pool.
  No single year >40% of the holdout.

Stratification runs as a constrained sampler: enforce per-paper severity
during filtering, then greedy-fill to meet category floors, then verify
year balance and reshuffle within-year if a band is over-quota.

## Tie-breaking

If more eligible papers satisfy the stratification constraints than 30:

- Sort candidates by `sha256(paper_id + "ncpr_v2_seed_42").hexdigest()`
  ascending (concretely: `seed=42` written into the salt as documented).
- Take the lowest-hash candidate at each greedy step.
- Salt string `ncpr_v2_seed_42` is frozen in
  `scripts/rag/evals/ncpr_v2_build_holdout.py` and must never change
  after first commit of `ncpr_v2_holdout.json`.

Reproducible: same KB snapshot + same script + same salt → bit-identical
output.

## Failure mode

If `<30` papers survive criteria 1–8 + quality enforcement, the builder
**raises `HoldoutBuilderError`** with a structured breakdown:

```
HoldoutBuilderError: only 24 / 30 eligible
  rejected_by_criterion:
    quality_score<7       : 18
    severity_floor        : 11
    sparse_severity       : 4
    stub_text             : 3
    pdf_missing           : 2
    year>2025             : 1
    already_in_eval       : 0
  remaining_eligible      : 24
```

The user (not the script) decides which floor to relax. The script must
not auto-relax — silent relaxation is the v1 bug this version explicitly
forbids.

## Comparison to v1 criteria

| Aspect | v1 | v2 |
|---|---|---|
| Journal scope | 6 journals (NC, CM, LDH, JAMA, NM, npjDM) | NC only |
| Journal stratification | proportional (±2) per journal, ≤40% cap | dropped (single venue) |
| Min concerns/paper | ≥3 | ≥3 (unchanged) |
| Severity gate | ≥1 CRITICAL **or** HIGH per paper | same per-paper gate **plus** holdout-level floors: ≥8 CRITICAL, ≥18 HIGH papers |
| Quality score floor | not used | `quality_score >= 7` (W23-A3 rubric) |
| Category floor | ≥10% of aggregate concerns per dim | ≥4 papers (≥13%) covering each dim |
| Year cut | `pub_date <= 2026-04` | `publication_year <= 2025` + ±2 proportional balance |
| Stub / sparse-severity reject | not enforced | `STUB_TEXT` + `SPARSE_SEVERITY` rules |
| Eval-set exclusion | scenarios + p@5 + rag-eval | + `ncpr_v1_holdout.json` + any `references/benchmark/*_ids` |
| Tie-break salt | `"ncpr_v1_seed_2026"` | `"ncpr_v2_seed_42"` |
| Under-eligible behaviour | reduce N + write ADR | raise `HoldoutBuilderError`, user decides |
| PDF availability | implied via methods_text | explicit: `references/case-studies/<journal>/<paper_id>.pdf` |

## Output schema (`ncpr_v2_holdout.json`)

- `holdout_ids: [str]` (length 30, sorted)
- `selection_seed: "ncpr_v2_seed_42"`
- `kb_snapshot_sha: <git sha of peer-review-kb.json>`
- `quality_rubric_version: "W23-A3"`
- `severity_band_counts: {critical_papers: int, high_papers: int}`
- `category_paper_counts: {evaluation, design, reporting, external_validation, leakage}`
- `year_distribution: {<year>: int}`
- `eligible_count: int`
- `rejection_histogram: {<reason>: int}`
- `built_at: ISO-8601 UTC`

Salt + snapshot sha + built-at are sufficient to reproduce the holdout
deterministically.
