# NCPR Benchmark v1 — Holdout Paper Selection Criteria

**Status**: pre-registered (W22-T3)
**Date**: 2026-05-17
**Wave**: NCPR Benchmark v1

## Goal

Pre-register the selection rules for the 30-paper holdout split **before
inspecting any individual paper's contents**. This blocks cherry-picking,
post-hoc rationalisation, and information leakage from holdout papers into
the retrieval KB used by `/mlgg` at evaluation time.

A paper is either eligible or not eligible based solely on metadata fields
that are already populated in `references/case-studies/peer-review-kb.json`
(plus existence of methods text). No reviewer judgement is applied per paper
during selection — only the deterministic filter + stratifier + tiebreaker
defined here.

## Source pool

154 curated NC / CM / LDH / JAMA papers in
`references/case-studies/peer-review-kb.json` (the W21 freeze, plus the
W22-T1 NM/npjDM extensions queued for inclusion).

## Inclusion criteria (all must hold)

A paper is **eligible** iff:

1. `paper_id` has **≥3 entries** under `reviewer_concerns` — gives a
   non-trivial statistical signal for scoring concern recall.
2. `journal ∈ {nature_communications, communications_medicine,
   lancet_digital_health, jama, nature_medicine, npj_digital_medicine}`.
3. Has `methods_text` **or** `methods_extract` populated, **or** an
   extractable methods file under `paper-templates/<paper_id>/`.
4. **Not** present in any existing eval set:
   - `scenarios.json`
   - `labeled_precision_at_5.json`
   - `rag-eval-set.yaml`
5. `publication_date ≤ 2026-04`, so the KB build cut-off does not let
   downstream commentary on the paper itself bleed into retrieval.

Criteria 1–5 are evaluated by `scripts/rag/evals/ncpr_build_holdout.py`
(W22-X7); the script writes the filtered eligible-set to stderr for audit.

## Stratification target

From the eligible set, pick **N = 30** papers such that:

- **Journals**: holdout shares per journal are proportional (±2 papers) to
  the eligible-set shares per journal. No journal contributes >40% of the
  holdout.
- **Severity mix**: every selected paper has **≥1 CRITICAL or HIGH**
  reviewer concern. Cuts trivially-easy papers.
- **Category mix**: aggregated across the 30 papers, each of the 5 NCPR
  dimensions covers **≥10%** of total concerns:
  - `evaluation`
  - `design`
  - `reporting`
  - `external_validation`
  - `leakage`

Stratification runs as a constrained sampler: enforce severity per-paper,
then greedy-fill journals proportionally, then verify category floor.

## Tie-breaking

If more eligible papers satisfy the stratification constraints than 30:

- Sort candidates by `sha256(paper_id + "ncpr_v1_seed_2026")` ascending.
- Take the lowest-hash candidate at each greedy step.
- Seed string is frozen in `scripts/rag/evals/ncpr_build_holdout.py` and
  must never be changed after first commit of `ncpr_v1_holdout.json`.

This makes the selection reproducible and auditable: anyone re-running the
script on the same KB snapshot gets bit-identical output.

## Failure modes and handling

| Failure | Handling |
|---|---|
| `<30` eligible papers after criteria 1–5 | Reduce N, write an ADR under `references/benchmark/adr/` recording the actual N + which criterion bound. Do not relax criteria silently. |
| Any category `<10%` of aggregate concerns | Augment from `communications_medicine` (broadest concern coverage in pool) one paper at a time until floor met or eligible pool exhausted. |
| Journal floor (proportional ±2) infeasible | Prefer category floor over journal floor; log deviation in `ncpr_v1_holdout.json` under `stratification_deviations`. |
| Severity floor (≥1 CRITICAL/HIGH) eliminates >50% of candidates | Pause selection, escalate — likely indicates `reviewer_concerns` severity is under-labelled and W22-T1 inventory should re-run severity pass first. |

## Implication for KB rebuild

Once `ncpr_v1_holdout.json` is committed, any KB rebuild that will be
evaluated against NCPR v1 **must** pass `--exclude-papers <holdout_ids>` to
the KB indexer. W22-Y1 implements this flag on the indexer; absence of the
flag in a rebuild invalidates the resulting NCPR v1 numbers.

Holdout paper full text, methods extracts, and reviewer-concern annotations
must not be embedded into any retrieval index, fine-tuning corpus, or
prompt few-shot pool used by `/mlgg` during evaluation.

## Validation + artefacts

- **Builder**: `scripts/rag/evals/ncpr_build_holdout.py` (W22-X7) — reads
  `peer-review-kb.json` + existing eval sets, applies criteria, stratifies,
  tiebreaks, and writes `references/benchmark/ncpr_v1_holdout.json`.
- **Validator**: same script with `--check` flag re-loads the written
  JSON and asserts every criterion + stratification floor still holds.
  CI must run `--check` on every PR that touches `peer-review-kb.json`,
  the holdout JSON, or the builder script itself.
- **Output schema** (`ncpr_v1_holdout.json`):
  - `holdout_ids: [str]` (length = N, sorted)
  - `selection_seed: "ncpr_v1_seed_2026"`
  - `kb_snapshot_sha: <git sha of peer-review-kb.json>`
  - `stratification_deviations: [{kind, journal_or_category, delta}]`
  - `eligible_count: int`
  - `built_at: ISO-8601 UTC`

The seed, snapshot sha, and built-at are sufficient to reproduce.
