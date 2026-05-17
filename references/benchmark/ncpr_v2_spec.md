# NCPR-Bench v2 — Specification

**Status**: Draft, established 2026-05-17 (W23-B1).
**Supersedes**: `ncpr_v1_spec.md` (archived as data-shortage prototype).
**Authoring wave**: W23 NCPR v2 (B1 spec, A2 PDF extractor, A3/A4 quality scoring, C1 threshold sweep).
**Scope**: contract only. Implementation details (holdout enumeration, matcher, severity weights, calibration) ride on companion docs.

---

## 1. What changed from v1 (and why)

v1 was written before the W22-V1 power audit and the W22-T1 KB inventory landed. Three of its premises did not survive contact with the data; v2 fixes them and tightens one self-challenge from the v1 retro.

| v1 clause | v2 change | Reason |
|---|---|---|
| §2.1 "Source journals: NC, CM, LDH, JAMA" + §3.2.4 journal stratification | **NC-only**. JAMA / LDH / NM / npjDM dropped from v2 holdout. | KB reality: 150 NC + 4 CM rows after re-filter; other journals contribute <5 rows each. Journal stratification on n=4 is statistical theatre. v3 reopens multi-journal expansion once W23-A5 lands. |
| §3.2.4 "stratify by journal" | **Stratify by `severity` + `category`** instead. | Severity and category are what reviewers actually disagree on; journal is a label, not a failure mode. |
| §4 input contract assumes `methods_text` field on KB row | **Methods text extracted from PDF at run time** via `scripts/rag/evals/ncpr_extract_methods_from_pdf.py` (W23-A2). KB row carries only `paper_pdf_path`. | The W22-T1 inventory confirmed most rows have no `methods_text` populated; v1 silently fell back to abstract, which over-stated input fidelity. |
| §7.1 "cosine ≥ 0.70" pre-registered | **Empirical sweep first** (W23-C1) on the *train* split, then freeze the optimum before the holdout is touched. | The v1 retro flagged 0.70 as a borrowed STS heuristic that may not transfer to clinical methods snippets. T4's self-challenge stands: pre-register the *protocol*, not the *number*. |
| §7 metric set included `failure_case_count` (added in v1.0.1) | **Replaced with `tail_severity_recall`** (recall on the bottom-quartile-frequency severity × category cell). | X5's review noted `failure_case_count` is unbounded and not comparable across runs; tail recall is bounded [0,1] and stresses exactly the rare-but-costly cells. |

v1 holdout selection, matcher source, and severity weight ratios are otherwise carried forward unchanged unless explicitly noted below.

## 2. Scope

Identical to v1 §2 — binary classification, retrospective cohort, EHR/registry/case-control/cross-sectional, modality boundary per `CLAUDE.md`. Out-of-scope items unchanged (omics, imaging, survival, prospective).

## 3. Held-out set

**Size**: 30 papers, NC-only, drawn from the **top-quality pool** (W23-A3 quality scorer + W23-A4 manual confirmation, paper-level `quality_score ≥ 7` on the 0–10 rubric).

**Admission criteria** (all must hold; deterministic, pre-paper-content):

1. `journal == "nature_communications"`.
2. `quality_score ≥ 7` per the W23-A3/A4 rubric (concern density, severity coverage, reviewer-round depth, methods-text completeness, code availability).
3. `paper_pdf_path` exists on disk and the W23-A2 extractor returns ≥ 500 chars of methods text.
4. ≥ 3 distinct reviewer concerns in `peer-review-kb.json` for the paper.
5. ≥ 1 concern is `severity ∈ {CRITICAL, HIGH}` (kills trivially-easy papers).
6. `publication_date < 2026-04-01` (KB-build pre-dates paper; carried from v1 §3.2.3).
7. Paper not present in any existing eval set (`scenarios.json`, `labeled_precision_at_5.json`, `rag-eval-set.yaml`, `MLGG-Bench v1.0`).

**Stratification target** (across the 30, replaces v1 journal stratification):

- **Severity**: ≥ 1 CRITICAL-or-HIGH per paper (criterion 5 already enforces). Aggregate floor: ≥ 8 CRITICAL concerns total across the 30.
- **Category**: each of the 5 NCPR dimensions (`evaluation`, `design`, `reporting`, `external_validation`, `leakage`) covers ≥ 10 % of total reviewer concerns aggregated across the 30. Carried from v1 §3.2.2.

**Tie-breaking**: SHA-256 of `paper_id + "ncpr_v2_seed_2026"`, lowest hash wins. Seed frozen on first commit of `ncpr_v2_holdout.json`. Mirrors v1.

**Builder**: `scripts/rag/evals/ncpr_v2_build_holdout.py` (forked from W22-X7; quality-score join added). `--check` mode re-validates every criterion; CI runs `--check` on any PR touching the holdout JSON, the KB, or the builder.

## 4. Input pipeline

```
paper_pdf_path  →  W23-A2 extractor  →  methods_text (≤30k chars, UTF-8)
                                       │
                                       ▼
                              MLGG end-to-end audit
                                       │
                                       ▼
                                 flag list (§5)
```

Extractor contract (W23-A2 owns):

- Input: PDF path (absolute).
- Output: `{methods_text: str, extraction_method: "pdfplumber"|"pymupdf"|"ocr", char_count: int, warnings: [str]}`.
- Determinism: same PDF → bit-identical methods_text. No LLM rewrite in the extraction path.
- Failure mode: extractor returns `methods_text == ""` and `warnings` non-empty → paper drops out of holdout for this run, logged in `ncpr_v2_run_<sha>.json`.

Code repo path and data dictionary remain optional, same as v1 §4.

## 5. System under test

Unchanged from v1 §5 (lint → gates → RAG → LLM synth), with two clarifications:

- RAG index for this run **must** be built with `--exclude-papers <ncpr_v2_holdout.json:holdout_ids>` (W22-Y1 flag).
- LLM concern synthesiser is pinned to the model version recorded in `agents/reviewer.yaml` at the run commit SHA; the run JSON records `{model, model_version_sha, temperature, seed}`.

Output schema per emitted concern unchanged from v1 §5.

## 6. Ground truth

Per holdout paper, pull every `reviewer_concerns` row from `peer-review-kb.json` where `paper_id` matches and `concern_text` length ≥ 30 chars (no stubs). Each row contributes one ground-truth concern record (`concern_id`, `concern_text`, `category`, `severity`, `mlgg_rules`, `mlgg_gates`). Author rebuttals do not subtract concerns (v1 §6 carried).

**New v2 gate**: every held-out concern carries **≥ 1 independent severity label** (per W23-C* design). Concerns with `severity_labels == []` are excluded from the ground truth for this run and logged.

## 7. Matcher

Algorithm carried from v1 §3 (`ncpr_v1_matcher_spec.md`): four match types ranked by precision — exact code, code-prefix, semantic cosine on BGE-small-en-v1.5, category (diagnostic only).

**Change**: the semantic threshold is no longer pre-registered at 0.70. W23-C1 runs a diagnostic sweep over `[0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]` on a labelled **train-split** sample (≥ 200 flag–concern pairs). The sweep emits a precision–recall curve and a frozen optimum (point on the PR curve closest to (1.0, 1.0) in Euclidean distance). That optimum is written into `references/benchmark/ncpr_v2_threshold.json` with the train-split SHA and the sweep timestamp, and the matcher refuses to read any other threshold in v2 mode.

The optimum is frozen before any holdout paper is scored. No re-sweep after holdout numbers exist. Threshold revision requires a v2.1 spec bump and a new train-split sample.

## 8. Metrics

All metrics computed per paper, then macro-averaged over the 30 holdout papers.

| ID | Metric | Source |
|---|---|---|
| M1 | `severity_weighted_f1` | v1 §7.3 + `ncpr_v1_severity_rationale.md`. Headline. |
| M2 | `category_coverage` | v1 §7.4. Penalises categories MLGG is blind to. |
| M3 | `per_severity_recall` | New v2. Recall computed separately within each of `{CRITICAL, HIGH, MEDIUM, LOW}`. Diagnoses which severity tier the system is failing on. |
| M4 | `tail_severity_recall` | New v2, replaces v1.0.1 `failure_case_count`. Recall restricted to the bottom-quartile-frequency (severity × category) cell aggregated over the 30 papers. Bounded [0,1]; stresses rare-but-costly combinations. |

Default `K = N` and `K = 2N`; both reported (v1 §7 carried).

## 9. Quality gates (pre-run)

A run is invalid (results not published, not added to dashboards) unless every gate below passes for every holdout paper:

1. Paper has `quality_score ≥ 7` (§3 criterion 2).
2. Paper has `paper_pdf_path` and the W23-A2 extractor returns `char_count ≥ 500`.
3. Paper has ≥ 3 ground-truth concerns after the stub-filter (§6).
4. Every ground-truth concern has `len(concern_text) ≥ 30` and `len(severity_labels) ≥ 1`.

Gate failure on any paper → that paper drops out of *this run*, gate-failure summary written to the run JSON, and the run is flagged `degraded` if more than 2 papers drop out. A `degraded` run is informational only and is **not** eligible to set or move acceptance thresholds.

## 10. Acceptance threshold

**TBD after first clean run.** v2 pre-registers the calibration protocol now:

1. Execute first clean (`degraded == false`) run of v2 against the frozen holdout.
2. Record `severity_weighted_f1`, `category_coverage`, `per_severity_recall`, `tail_severity_recall` with 95 % bootstrap CIs (1000 resamples over the 30 papers).
3. Propose acceptance thresholds in a follow-up ADR; CI gate added in a *separate* PR after ADR merge. (Mirrors v1 §8 deferred-gating; mirrors `MLGG-Bench v1.0` rollout pattern.)
4. Until ADR merges: NCPR v2 is **informational only** — regressions visible in dashboards, not blocking.

## 11. Forbidden (carried from v1 §9)

- No LLM-as-judge in matching.
- No post-hoc tuning of the cosine threshold against holdout numbers. (v2 strengthens v1: the *protocol* is pre-registered, the *number* is frozen by W23-C1 before holdout scoring.)
- No selective reporting of K or metric subset — M1–M4 at both K=N and K=2N reported together.
- No holdout leakage into the KB; W22-Y1 `--exclude-papers` is mandatory.
- No re-rolling the holdout to improve numbers; holdout change requires a v2.1 spec bump and an ADR.

## 12. Versioning

- v2 **supersedes** v1. v1 is retained on record (`ncpr_v1_spec.md`) and re-labelled "data-shortage prototype" in its header — its numbers stay published for traceability, but new MLGG releases are scored against v2.
- v2.1 = same contract, threshold or holdout revised with ADR.
- v3 = scope expansion (multi-journal, omics-adjacent reviewer concerns, code-availability sub-score). See §13.

## 13. Open questions for v3

1. **Multi-journal expansion**: depends on W23-A5 (other-journal scraper backlog). Once CM ≥ 30 + LDH ≥ 30 rows land, re-introduce journal as a stratification axis and consider per-journal sub-scores.
2. **Category imbalance correction in the aggregate**: deferred from v1 §9. Open empirical question whether per-category-then-macro aggregation reduces high-base-rate dominance without inflating zero-concern-category papers.
3. **Reviewer disagreement as signal**: weight `concern_recall` by inter-reviewer agreement when ≥ 2 reviewers raised the same concern (the v1 spec flagged this as a W23+ item).
4. **Non-determinism audit**: ensemble-over-temperature variant of §5 SUT, also deferred from v1.

---

**Companion docs (this wave)**

| ID | Doc / artifact | Relation |
|---|---|---|
| W23-A2 | `scripts/rag/evals/ncpr_extract_methods_from_pdf.py` | §4 input pipeline |
| W23-A3 | `scripts/rag/evals/ncpr_quality_score.py` | §3 admission criterion 2 |
| W23-A4 | manual quality-score confirmation pass | §3 admission criterion 2 |
| W23-C1 | `scripts/rag/evals/ncpr_threshold_sweep.py` + `ncpr_v2_threshold.json` | §7 matcher threshold |
| W23-C* | per-concern severity labelling | §6 ground-truth gate |
