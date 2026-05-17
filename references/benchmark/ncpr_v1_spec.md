# NCPR-Bench v1 — Specification

**Status**: Draft, established 2026-05-17 (W22-T1).
**Authoring agent**: W22-T1.
**Companion docs (sibling agents, this wave)**: T2 ADR-0005 (governance), T3 holdout-criteria, T4 matcher-spec, T5 severity-rationale.
**Scope of this file**: contract only. Quantitative thresholds, holdout enumeration, matcher implementation, and severity-weight derivation live in T2–T5.

---

## 1. Purpose

**NCPR-Bench** (Nature Communications / Communications Medicine **P**eer **R**eview Benchmark) tests **end-to-end MLGG-as-peer-reviewer effectiveness on held-out papers**. The existing `MLGG-Bench v1.0` (`references/retrieval_eval/MLGG-Bench-v1.0/`) evaluates the *retrieval* component in isolation — does the hybrid BM25 + BGE-small ranker surface the right KB entries for a given query? NCPR-Bench evaluates the *whole pipeline* — given a paper's methods text (and optionally its code), does MLGG produce a concern set a reviewer would have produced?

Origin: W22 wave plan, "we lint code well, we retrieve KB entries well, but we have no honest measurement of whether the full system would catch what a Nature Communications reviewer caught." Retrieval P@K can be high while end-to-end concern recall is low (or vice versa). NCPR-Bench is the first benchmark that closes that loop.

NCPR-Bench is **independent** of `MLGG-Bench v1.0`: a regression in NCPR can pass MLGG-Bench (and vice versa), and that disagreement is itself diagnostic.

## 2. Scope

### 2.1 In scope

- Binary classification prediction papers
- Source journals: Nature Communications (NC), Communications Medicine (CM), Lancet Digital Health (LDH), JAMA family
- Data modality: EHR, disease registry, case-control, cross-sectional
- Study design: retrospective cohort

### 2.2 Out of scope (mirrors `CLAUDE.md` modality boundary)

- Omics (TCGA / scRNA / GWAS)
- Imaging-primary studies
- Survival / time-to-event as the primary task
- Multi-class > binary, regression, generative
- Prospective trials (PROBAST-AI and CONSORT-AI apply, not MLGG)

A paper that *mentions* an out-of-scope element (e.g. a sub-analysis with a survival check) is admissible if the headline task is binary classification on tabular EHR/registry data.

## 3. Dataset design

### 3.1 Sizes

- **Curated pool**: 154 papers (subset of the 335 in `peer-review-kb.json` that satisfy §2 scope after re-filtering for modality and task)
- **Train split**: 124 papers — feed the KB / RAG index / few-shot exemplars
- **Held-out split**: **30 papers** — never seen by KB, never seen by exemplars, never seen by prompt-tuning

### 3.2 Hold-out admission criteria (a paper enters the 30 iff all hold)

1. **Concern density**: ≥ 3 distinct reviewer concerns in `peer-review-kb.json` (so recall is measurable, not a 1-or-0 coin flip)
2. **Category balance across the 30**: each of the five top-level categories has ≥ 4 papers contributing concerns in it. Categories: `evaluation`, `design`, `reporting`, `external_val`, `leakage`. (These collapse the 13 fine-grained `concerns_by_category` keys in `peer-review-kb-stats.json`; mapping table is T3's deliverable.)
3. **Temporal honesty**: paper publication date **strictly before 2026-04-01** so the KB build cutoff (audit `peer-review-kb-audit-2026-04.md`) pre-dates the paper. Papers whose own concerns made it into the KB are *excluded* from holdout, no matter how attractive. T3 owns the dedup list.
4. **Journal stratification**: holdout counts per journal are proportional to that journal's share of the curated pool, rounded to integers summing to 30. No single journal exceeds 50% of the holdout.

### 3.3 What "held-out" means operationally

- KB index rebuild excludes any concern row whose `paper_doi` is in the holdout DOI list.
- Few-shot exemplars in any prompt template exclude holdout DOIs.
- Retrieval-eval scenarios (`MLGG-Bench v1.0`) that cite a holdout `paper_id` are quarantined for the NCPR runs (and only those runs).
- The holdout DOI list is committed (T3) and treated as append-only; removing a paper requires a wave-level ADR.

## 4. Input contract (per paper, per run)

| Field | Required | Source |
|---|---|---|
| `paper_id` | yes | KB primary key |
| `methods_text` | yes | extracted from PDF or HTML, plain UTF-8, ≤ 30k chars |
| `code_repo_path` | optional | `references/case-studies/<journal>/<paper_id>/` if present, else null |
| `data_dictionary` | optional | if author published one |

`methods_text` is **mandatory**; everything else is best-effort. A run where only methods text is available is a valid run — NCPR explicitly measures how much MLGG can do without code, since most NC/CM submissions do not ship runnable code.

## 5. System under test (SUT)

The full MLGG pipeline, invoked end-to-end:

1. `mlgg lint` (static rules R001–R030) against `code_repo_path` if present
2. 33-gate dispatch (`scripts/gates/*`) against any structured artifacts (`metrics.json`, `splits.json`, …) the repo produces
3. RAG retrieval (`scripts/rag/`) over the train-split-only KB using the methods text as query
4. LLM concern synthesis (current production model per `agents/reviewer.yaml`) consuming lint output + gate output + retrieved KB entries

**SUT output schema** (one record per emitted concern):

```json
{ "code": "MLGG-F02 | gate:cohort_definition_gate | R012 | LLM-synth",
  "severity": "CRITICAL | HIGH | MEDIUM | LOW",
  "category": "evaluation | design | reporting | external_val | leakage",
  "evidence_text": "verbatim or near-verbatim quote from methods or code" }
```

The `evidence_text` is mandatory and is what the matcher (§7, T4) compares against reviewer concerns.

## 6. Ground truth

Per paper in the holdout:

- Pull every row from `references/case-studies/peer-review-kb.json` where `paper_doi` matches the paper.
- Each row contributes one ground-truth concern with fields: `concern_id`, `concern_text`, `category` (collapsed to the 5-cat scheme), `severity` (`CRITICAL | HIGH | MEDIUM | LOW` already on the row), `mlgg_rules`, `mlgg_gates`.
- A paper's ground truth is the **union** of all reviewer concerns across all rounds. Author rebuttals do not subtract concerns — a concern the author successfully rebutted is still a concern MLGG should have flagged.

## 7. Metrics

All four metrics computed per paper, then averaged over the 30 holdout papers (macro-average — every paper weighs the same, large-concern-set papers do not dominate).

Let `N` = number of ground-truth concerns on the paper, `K` = top-K MLGG output concerns under evaluation. Default `K = N` (i.e. give MLGG the same budget the reviewer had) and `K = 2N` (oracle-budget variant).

### 7.1 `concern_recall@K`

Of the `N` ground-truth concerns, fraction matched by ≥ 1 of MLGG's top-K outputs. A match is:

- **Exact code match**: the MLGG output's `code` field intersects the ground-truth row's `mlgg_rules` or `mlgg_gates`, OR
- **Semantic match**: cosine similarity between sentence-transformer embeddings (`BAAI/bge-small-en-v1.5`, same as production) of `evidence_text` and `concern_text` is ≥ **0.70**.

T4 owns the matcher implementation, the embedding-model pin, and the 0.70 threshold calibration.

### 7.2 `concern_precision@K`

Of the K MLGG outputs, fraction matching ≥ 1 ground-truth concern. Same matcher as §7.1.

### 7.3 `severity_weighted_f1`

Per paper: weight each *matched* concern by its **ground-truth** severity (`CRITICAL=4, HIGH=2, MEDIUM=1, LOW=0.5`). Compute weighted precision and weighted recall; F1 is harmonic mean. Unmatched ground-truth concerns count against weighted recall at their own severity; unmatched MLGG outputs count against weighted precision at uniform weight 1 (we cannot trust MLGG's self-assigned severity for this purpose — that would let the model game F1 by over-claiming CRITICAL on its hits). T5 owns the weight-derivation rationale and the asymmetry argument.

### 7.4 `category_coverage`

Number of the 5 categories in which MLGG produced **at least one output** that matched **at least one ground-truth concern in that category**, divided by 5. Coverage of 5/5 = 1.0. This metric penalises pipelines that are excellent on (say) leakage and blind to reporting.

## 8. Acceptance thresholds

**Initial baseline: TBD.** First calibration run scheduled for W23. Until that run produces numbers on the held-out 30, no threshold is enforced.

Process for promotion to CI gate:
1. W23 calibration run produces baseline `(recall@K, precision@K, sw-F1, cat-cov)` on holdout
2. Acceptance thresholds proposed in a follow-up ADR (T2 governs the ADR template)
3. CI gate (`.github/workflows/`) added in a *separate* PR after ADR merge
4. Until then: NCPR-Bench is **informational only** — regressions visible in dashboards, not blocking

This deferred-gating pattern matches the `MLGG-Bench v1.0` rollout (see `references/retrieval_eval/METRIC_CONTRACT.md` §3).

## 9. Forbidden

- **No holdout leakage into the KB.** A concern row whose `paper_doi` is in the holdout list must not be in the train-split KB used for SUT runs. Verified by an explicit set-difference check; T3 owns the assertion.
- **No LLM-as-judge in matching.** Matching is exact-code OR cosine-similarity. We do not ask an LLM "is this MLGG output close enough to this reviewer concern?". Reason: circularity (the labeler is in the same model family as the synthesiser). Mirrors `METRIC_CONTRACT.md` §4.
- **No post-hoc threshold tuning** of the 0.70 cosine cutoff against the holdout. The cutoff is calibrated *on the train split* (T4) and frozen before the holdout is ever scored.
- **No selective reporting**: all four metrics at both `K=N` and `K=2N` reported together. Cherry-picking the most flattering K is a forbidden tuning path.
- **No re-rolling the holdout** to improve numbers. Holdout-set changes require a wave-level ADR with an explicit reason and rotate the spec version to `v1.1`.

## 10. Sibling agents (this wave)

| Agent | Deliverable | Relation to this spec |
|---|---|---|
| W22-T2 | ADR-0005: NCPR governance & promotion process | Owns the promotion-to-CI-gate workflow §8 references |
| W22-T3 | Holdout criteria doc + DOI list | Owns the 30-paper enumeration and dedup §3 references |
| W22-T4 | Matcher spec + 0.70-cutoff calibration | Owns the semantic-match implementation §7.1 references |
| W22-T5 | Severity-weight rationale | Owns the `4/2/1/0.5` weights and asymmetric-precision argument §7.3 uses |

This spec is the **contract**. T2–T5 fill in the implementation pieces that make the contract executable. If T3–T5 disagree with a clause here, this spec gets a `v1.1` revision rather than each sibling silently drifting.

---

**Open questions for W23+**
- Single-LLM-snapshot evaluation vs. ensemble-over-temperature: §5's SUT is currently a single deterministic run. A non-determinism audit is on the W23 backlog.
- Whether `concern_recall@K` should weight by reviewer (R1 vs R2 vs R3 disagreement is itself signal).
- Cross-bench correlation: how often does MLGG-Bench-v1.0 retrieval P@5 movement predict NCPR `concern_recall@N` movement? Empirical question, answerable after the first three NCPR runs land.
