# NCPR Benchmark v2 — Quality Floor for Held-out Papers and Concerns

**Status**: pre-registered (W23-B5)
**Date**: 2026-05-17
**Wave**: NCPR Benchmark v2 (premium tier)

## Goal

Codify what "high-quality" means for the NCPR v2 holdout, applied **before**
any holdout sampling runs. NCPR v1 admitted any paper with ≥3 reviewer
concerns; v2 raises the floor to a "premium" tier so the benchmark stresses
`/mlgg` on rich, cross-cutting peer review, not on stubs or one-line
critiques. Garbage in → the benchmark grades the corpus, not the system.

The filter is **paper-level** (does this paper belong in the pool at all?)
and **concern-level** (do this paper's concerns each carry signal?). Both
floors must hold. Auto-filter implementation is W23-C3 (`ncpr_quality_filter.py`).

## Paper-level quality criteria

A paper is **premium-eligible** iff all of the following hold:

1. **Has PDF**: a real PDF lives under `paper-templates/<paper_id>/` or is
   resolvable via `pdf_path` in `peer-review-kb.json`. KB-stub-only papers
   (where the entry exists but no PDF / methods text was ever attached)
   are rejected — they cannot support end-to-end `/mlgg` runs.
2. **≥5 reviewer concerns** (v1 required ≥3). Premium tier wants depth.
3. **≥1 CRITICAL severity concern**. Forces every premium paper to carry
   at least one fail-closed-grade methodological flaw.
4. **≥3 distinct categories represented** across that paper's concerns,
   drawn from the 5 NCPR dimensions
   (`evaluation`, `design`, `reporting`, `external_validation`, `leakage`).
   Proves the paper is cross-cutting, not a single-issue critique.
5. **`key_methodology_issues` populated** (non-empty list with ≥1 entry of
   ≥20 chars). This field is the seed query material the retrieval eval
   uses; an empty field means no extractable test signal.
6. **`author_response` text non-empty** for ≥1 concern on the paper. Rich
   author dialogue proves the critique was substantive enough to require a
   defended response, not surface nitpicking.
7. **`publication_date.year ≥ 2023`**. Methodology standards alignment:
   TRIPOD+AI (2024) and PROBAST+AI (2025) reflect modern reviewer
   expectations; pre-2023 papers were judged under looser conventions and
   skew the severity distribution.

## Concern-level quality criteria

Within a premium-eligible paper, an **individual concern** counts toward
that paper's qualifying total iff all of the following hold:

1. **`concern_text` length ≥ 30 chars** (after strip). Cuts one-liner stubs
   like "needs more data".
2. **`severity` field labelled** with one of
   `{CRITICAL, HIGH, MEDIUM, LOW}` (not null, not `unknown`).
3. **`category` field labelled** with one of the 5 NCPR dimensions
   (not null, not `other`, not `unknown`).
4. **`mlgg_gates` list ≥ 1 entry** and every listed gate ID resolves to a
   real gate in `references/gates/registry.json`. Unlinkable concerns
   cannot score against the gate system, so they cannot be measured.
5. **`author_response` matched**: text present and not the literal sentinel
   `[pending]` / `TBD` / empty string. Concerns without a matched response
   cannot validate the reviewer-author dialogue dimension of the benchmark.

A paper must retain **≥5 qualifying concerns after concern-level filtering**
(re-check criterion 2 of the paper-level floor *after* concern-level pruning,
not before). Concern-level rejection cascades up: drop concerns first, then
re-evaluate the paper.

## Auto-filter implementation (W23-C3)

`scripts/rag/evals/ncpr_quality_filter.py` (W23-C3) implements this floor.
Contract:

- **Input**: `references/case-studies/peer-review-kb.json` (full pool) and
  the W23-A1 PDF inventory (`docs/diagnostics/W23_A1_pdf_inventory.md`).
- **Per-paper score**: 1 point per paper-level criterion satisfied (max 7).
  Threshold: **score == 7** (all criteria; no partial credit at premium tier).
- **Per-concern score**: 1 point per concern-level criterion satisfied
  (max 5). Threshold: **score == 5**.
- **Output**: `references/benchmark/ncpr_v2_quality_pool.json` listing
  paper IDs and their qualifying concern IDs that passed both floors.
- **Reject log**: every rejected paper or concern is appended to
  `/tmp/W23_quality_rejects.jsonl` with `{paper_id, concern_id?, failed_criterion, observed_value}`.
  Transparency requirement: a CI job greps the reject log to ensure no
  paper was rejected on a criterion not listed in this document.

The filter runs **before** the W23-D1 v2 holdout sampler. The sampler reads
`ncpr_v2_quality_pool.json` as its source pool, never `peer-review-kb.json`
directly. This makes the quality floor a hard precondition of the holdout,
not an advisory check.

## Why this matters

- **Garbage In, garbage benchmark**: low-signal concerns inflate apparent
  recall — a 6-word "needs validation" stub is trivially matched by any
  keyword retriever, so it credits `/mlgg` without testing it.
- **Stub PDFs break end-to-end runs**: papers with no methods text cannot
  exercise the full `/mlgg` pipeline, only the retrieval head; mixing them
  with full-text papers makes per-paper scores incomparable.
- **Single-category papers are easy mode**: a paper whose 5 concerns are
  all `leakage` rewards a retriever that over-fires on one dimension.
  Requiring ≥3 categories forces the system to demonstrate breadth.
- **Pre-2023 papers under-state severity**: reviewer culture has hardened;
  including them dilutes the CRITICAL rate and makes severity-weighted F1
  optimistic relative to what current `/mlgg` users will see in practice.
- **Positioning**: the explicit target is "Nature Methods AI reviewer
  benchmark" — a corpus a methods editor would accept as representative of
  modern peer review — not "MLGG vs its own training KB". The quality floor
  is what separates those two.

## Failure modes

| Failure | Handling |
|---|---|
| `<30` papers pass the paper-level floor | Reduce N for v2 holdout, ADR under `references/benchmark/adr/` records actual N + which criterion bound. **Never** relax criteria silently. |
| Quality pool too small to satisfy v2 holdout stratification | Surface to user. Options: (a) accept smaller N, (b) extend KB with W23-T1 follow-on inventory, (c) lower one criterion **with explicit user sign-off + ADR**. Never lower silently. |
| Reject log flags a criterion not in this doc | CI fail. Either update this doc (with commit reference) or fix the filter — drift between spec and code is itself a failure. |

## Relation to v1

NCPR v1 holdout (`ncpr_v1_holdout_criteria.md`) remains the **baseline
tier** — broader pool, lower floor, used for regression tracking. NCPR v2
is the **premium tier** for publication-grade claims. The two are scored
separately and never averaged; mixing them would hide where `/mlgg`
actually performs.
