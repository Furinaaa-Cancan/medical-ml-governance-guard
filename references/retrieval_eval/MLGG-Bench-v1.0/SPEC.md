# MLGG-Bench v1.0

A retrieval benchmark for the ML Governance Guard (MLGG) reviewer-concern RAG

---

## 1. Identity

| Field            | Value                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------ |
| Name             | **MLGG-Bench**                                                                                         |
| Version          | **1.0.0** (this document)                                                                              |
| Release date     | 2026-05-17                                                                                             |
| Maintainer       | ml-leakage-guard core team (Claude Code + human curators)                                              |
| Target system    | MLGG peer-review retrieval-augmented gate, `scripts/rag/` (hybrid BM25 + BGE-small + tag/severity)     |
| Knowledge base   | `references/case-studies/peer-review-kb.json`, contract `peer_review_kb.v1.4`, 335 papers / 817 concerns |
| Canonical patterns | 49 (CP-001 .. CP-049)                                                                                |
| Schema           | JSON, one file per slice; each file `{ "scenarios": [ {...}, ... ] }`                                  |
| License          | Same as parent repo (see repo `LICENSE`). Benchmark data redistributable under that license; if the repo is restricted-use, redistribute the spec text and slice manifest only, not the underlying KB. |
| Where to find it | Spec at `/tmp/mlgg_benchmark/BENCHMARK_SPEC.md`; slice files alongside (negative + distractor already materialised, others enumerated in §3). |

### 1.1 Citation block

```bibtex
@misc{mlgg_bench_v1_2026,
  title  = {MLGG-Bench v1.0: A stratified retrieval benchmark for ML
            governance review of retrospective cohort prediction studies},
  author = {{ml-leakage-guard contributors}},
  year   = {2026},
  note   = {Knowledge base: peer-review-kb v1.4 (335 papers, 817 concerns,
            49 canonical patterns). RAG: hybrid BM25 + BGE-small-en-v1.5
            (weights 0.45/0.10/0.30/0.15 BM25/dense/tag-overlap/severity).
            Eval harness: scripts/rag/evals/run_eval.py.},
  url    = {https://github.com/<org>/ml-leakage-guard}
}
```

### 1.2 Scope of the benchmark

MLGG-Bench is **not** a general medical-IR benchmark. It evaluates *one
specific retrieval task*: given a free-text peer-review-style query about
a retrospective-cohort binary-classification ML study, surface the
canonical reviewer concerns from a curated KB so that a downstream gate
can render a structured verdict.

It deliberately does not cover:

- Imaging classification / segmentation (e.g. CXR, U-Net)
- Omics (scRNA-seq, GWAS, bulk-RNA batch correction, TCGA)
- Survival / time-to-event modeling
- NLP / clinical-text generative tasks
- Prospective trials, deployment / monitoring, RCT reporting

These out-of-scope modalities appear in **slice `negative` (bench_04)**
where the correct retrieval behaviour is to retrieve **few or no**
strongly-scored hits.

---

## 2. Task definition

### 2.1 Inputs (per scenario)

A scenario is a JSON object with the following fields:

| Field                            | Required | Source / role                                                                  |
| -------------------------------- | -------- | ------------------------------------------------------------------------------ |
| `scenario_id`                    | yes      | Unique string within the benchmark.                                            |
| `description`                    | yes      | Human-readable one-liner for the slice manifest.                               |
| `query_text`                     | yes\*    | Free-text reviewer query the RAG must serve.                                   |
| `gate_name`                      | opt      | If present, name of the upstream MLGG gate that would trigger this query.      |
| `failure_codes`                  | opt      | Symbolic gate failure codes the gate would attach to the query.                |
| `expected_categories`            | opt      | High-level concern categories (e.g. `evaluation_metrics`).                     |
| `expected_tags`                  | opt      | Concern-level tags any of which counts as a tag hit.                           |
| `expected_canonical_pattern_ids` | opt      | CP IDs (e.g. `["CP-027"]`) that any retrieved concern must belong to for a CP hit. |
| `dimension`                      | opt      | Slice-internal taxonomy label (e.g. `leakage`, `evaluation_metrics`, `distractor`). |
| `expected_max_hits`              | opt      | Negative/distractor slices only: upper bound on the number of "strong" hits.   |

\* The harness accepts an empty `query_text` when `gate_name` and
`failure_codes` are present and constructs the query as
`"<gate_name> <space-joined codes>"` (see `run_eval.py:77-83`). This
mirrors the production gate-to-RAG bridge.

### 2.2 Output (what the RAG returns)

For a scenario, the RAG returns an ordered list of up to `top_k`
**concerns** (default `top_k=5`), each carrying:

- `concern_id` (provenance: `PR-<paper>-C<idx>`)
- `canonical_pattern_id` (one of CP-001 .. CP-049, or `null`)
- `tags` (list of free-form tags from the KB)
- `_final_score`, `_score` (model-internal scores, used for `top1_score`)

The retrieval pipeline:

1. **Hybrid candidate pool**: BGE-small dense cosine + Okapi BM25 over
   concern text (and tag tokens).
2. **Tag-overlap and severity boosts** with adaptive guards
   (`CP_TAG_BOOST_DENSE_FLOOR=0.70`, `SEVERITY_FULL_SPREAD=0.20`).
3. **MMR diversity rerank** (`MMR_LAMBDA=0.7`, same-paper penalty 0.5,
   cosine floor 0.88).
4. Truncate to `top_k`.

Weights (effective for v1.0, set in `scripts/rag/config.py`):

```
WEIGHT_BM25         = 0.45
WEIGHT_DENSE        = 0.10
WEIGHT_TAG_OVERLAP  = 0.30
WEIGHT_SEVERITY     = 0.15
```

### 2.3 What "correct" means

Three notions of correctness, in order of strictness:

1. **Tag hit** — at least one returned concern shares one expected tag.
2. **CP hit** — at least one returned concern's `canonical_pattern_id`
   is in `expected_canonical_pattern_ids`. (Stronger: tag overlap can be
   accidental; CP membership requires the retriever to land in the
   right reviewer pattern bucket.)
3. **Category hit** — at least one returned concern's category is in
   `expected_categories`. (Weakest; reported only as a fallback when
   tag and CP gold are absent.)

For **negative** and **distractor** slices the notion is inverted:
correct behaviour is **no strong hit**.

---

## 3. Strata

MLGG-Bench v1.0 is the union of nine slices. Each slice is a separate
JSON file and a separate row in the scoring report; the union is **not**
the headline metric. Headline numbers are reported per slice.

| Slice                       | n   | Source                                                          | Tests                                                | Has CP gold | Has tag gold |
| --------------------------- | --- | --------------------------------------------------------------- | ---------------------------------------------------- | ----------- | ------------ |
| `baseline`                  |  30 | hand-crafted 2026-04-23 (`references/retrieval_eval/scenarios.json`) | smoke regression vs `post_wave7_baseline_hybrid.json` | no          | 30/30 (15 also have `expected_relevant_tags`) |
| `in_distribution` (10-agent merged) | 155 | 10 LLM-paraphrase agents over KB concerns, `/tmp/mlgg_eval_expand/merged.json` | recall stability across paraphrase    | 136/155     | 155/155      |
| `adversarial` (agent_10 + bench_07) |  35 | cross-paper CP paraphrase, near-miss, distractor; lex / domain / length / mixed / codeswitch variants (`agent_10.json` n=20, bench_07 n=15) | robustness to surface-form drift | 35/35       | 35/35        |
| `fairness` (bench_01)       |  10 | KB fairness concerns (subgroup AUROC, calibration drift, disparate-impact) | fairness coverage (52 KB concerns, gate-thin slice)  | 10/10       | 10/10        |
| `long_tail` (bench_02)      |  15 | CP-025 .. CP-049 (tail half of CP distribution)                 | tail-CP recall                                       | 15/15       | 15/15        |
| `compound` (bench_03)       |  10 | multi-CP queries (one query maps to 2-3 expected CPs)           | multi-aspect recall, partial-credit scoring          | 10/10 (>=2 CPs each) | 10/10  |
| `negative` (bench_04)       |  10 | out-of-MLGG-scope (omics, imaging, segmentation, single-cell)   | precision (RAG should NOT match)                     | 0           | 0            |
| `distractor` (bench_05)     |  10 | methodology-flavoured non-methodology (clinical / writing / domain) | precision (lexical lure)                          | 0           | 0            |
| `ood` (ood_01..04)          | TBD pending OOD agent output (~40 planned) | Retraction Watch, OpenReview, TRIPOD+AI exemplars, open peer-review journals | generalisation to truly unseen papers | partial | partial |

Total: **315 scenarios** when OOD slice lands (currently 270
materialised across the first 8 slices).

### 3.1 Slice contracts

Each slice has a compact contract documented here so a new agent can
re-derive it without re-reading the source files.

#### baseline (n=30, version 1.1)

- File: `references/retrieval_eval/scenarios.json`
- Hand-curated 2026-04-23, augmented 2026-05-17 (H11) with H10-E1
  fields (`query_text`, `baseline_p5_e1`, `expected_relevant_tags`,
  `failure_codes_hint`, `known_weakness`).
- 19 of 30 carry no `dimension` label; 15 of 30 carry an explicit
  `query_text` (the rest exercise the gate+codes fallback path).
- **None** carry `expected_canonical_pattern_ids` — baseline pre-dates
  the CP-hit metric (commit 7fc1ca5).
- Frozen baseline numbers (mode = `hybrid`, top_k = 5, source
  `references/retrieval_eval/post_wave7_baseline_hybrid.json`):
  - `n_scenarios` = 30
  - `n_evaluable` = 26 (4 carry no `expected_tags`)
  - `coverage_rate` = 0.867
  - `mean_hit_at_k` = **1.000** (saturated on baseline)
  - `mean_tag_precision_at_k` = 0.538
  - `mean_top1_score` = 0.649
  - `n_zero_hits` = 4
  - `wall_ms_total` = 13866.5 ms (first-run dominated by embedding
    model warm-up at 13,313 ms on scenario 1)

#### in_distribution (n=155)

- File: `/tmp/mlgg_eval_expand/merged.json` (per-agent files
  `agent_01.json` .. `agent_10.json`).
- Construction: ten LLM agents each produced ~15 paraphrases of KB
  concerns, swapping clinical vocabulary while preserving the
  underlying canonical pattern (agent_10 contributed 20; see
  adversarial slice).
- Dimension distribution (from `dimension` field): evaluation 30,
  leakage 30, reporting 18, external_validation 17, model_selection
  17, study_design 15, interpretability 8, fairness 5, sample_size 3,
  evaluation_metrics 3, cohort_definition 3, reproducibility 2,
  preprocessing 2, clinical_utility 1, feature_selection 1.
- 136 of 155 carry `expected_canonical_pattern_ids` (88%); the
  remaining 19 have only tag/category gold.
- Use as: stability proxy. If the RAG's `mean_hit_at_k` on this slice
  changes by > 0.03 between releases, investigate before merging.

#### adversarial (n=35: agent_10 n=20 + bench_07 n=15)

- Files: `/tmp/mlgg_eval_expand/agent_10.json` (built against
  `peer_review_kb.v1.4`) + `bench_07_adversarial.json` (to be added,
  bench-agent 07's output).
- agent_10 sub-buckets (verified counts):
  - paraphrase (cross-paper CP): 8
  - near-miss (adjacent CPs): 6
  - distractor (looks methodological, narrow target): 6
- bench_07 sub-buckets (per task brief): lexical, domain, length,
  mixed, codeswitch (3 each = 15).
- All 35 carry `expected_canonical_pattern_ids` — this is the slice
  where `mean_cp_hit_at_k` is the primary headline.

#### fairness (bench_01, n=10)

- File: `bench_01_fairness.json` (to be assembled from KB fairness
  concerns; KB has 52 concerns tagged
  `fairness_equity_gate` per `peer-review-kb-stats.json`).
- Subgroup AUROC drift, calibration-by-subgroup, disparate-impact
  audit, missing-fairness-section reporting, etc.

#### long_tail (bench_02, n=15)

- File: `bench_02_longtail.json` (to be assembled from CP-025 .. CP-049).
- The KB's CP distribution is heavy-tailed: tail CPs may have only
  3-5 concerns each. This slice exists to expose whether MMR diversity
  is squeezing tail patterns out of the top-K when head patterns share
  surface tokens.

#### compound (bench_03, n=10)

- File: `bench_03_compound.json` (to be assembled).
- Each query has >= 2 expected CPs. **Scoring rule**: report two
  numbers — strict `cp_hit_at_k_all` (all expected CPs present in
  top-K) and lenient `cp_hit_at_k_any` (at least one). Strict is the
  headline; lenient is the diagnostic.

#### negative (bench_04, n=10, materialised)

- File: `/tmp/mlgg_benchmark/bench_04_negatives.json` (confirmed: 10
  scenarios).
- All scenarios have empty `gate_name`, `failure_codes`,
  `expected_categories`, `expected_tags`, and
  `expected_canonical_pattern_ids`. They carry `expected_max_hits` (2 or
  3) and `oos_modality` (e.g. `omics_scrnaseq`, `imaging_segmentation`).
- Scoring: see `false_strong_hit_rate` in §4.5.

#### distractor (bench_05, n=10, materialised)

- File: `/tmp/mlgg_benchmark/bench_05_distractors.json` (confirmed: 10
  scenarios).
- `distractor_type` field labels each: `clinical` (pharmacology,
  cutoffs), `writing` (table/figure readability), `domain` (clinical
  guideline disagreement).
- Each query uses methodology-adjacent vocabulary (`calibration`,
  `AUROC`, `feature engineering`, `external validation`) but the
  actual reviewer intent is non-methodological. The RAG must not
  retrieve a strong methodology concern.

#### ood (ood_01..04, n ~40, TBD)

- Sources planned:
  - Retraction Watch ML/medicine entries 2024-2026
  - OpenReview public peer reviews (NeurIPS/ICML health workshop)
  - TRIPOD+AI 2024 worked-example reports
  - Open-peer journals (BMJ, eLife) outside the 335-paper KB
- **TBD pending OOD agent output.** When materialised, splits per
  source; CP gold derived by human review.

---

## 4. Metrics

All metrics are computed by `scripts/rag/evals/run_eval.py` (`aggregate()`),
top_k = 5 unless otherwise noted. The four-tuple `(slice, mode,
coverage_rate, mean_hit_at_k)` is the minimum unit of a benchmark
claim (see §6).

### 4.1 `mean_hit_at_k` (PRIMARY)

```
mean_hit_at_k = mean over evaluable scenarios of (1 if any tag hit else 0)
```

- Binary per scenario, evaluated against the per-scenario expected-tag
  set.
- "Evaluable" = scenario carries non-empty `expected_tags` (or
  `expected_relevant_tags` / `expected_categories`) AND retrieval
  returned >= 1 hit.
- A scenario with no expected_tags is **excluded from the mean** and
  contributes to `coverage_rate` only.
- Wave-5-P2 rationale: tag-precision rewards staying inside a tag
  cluster, which conflicts with MMR diversity. hit@K is what a gate
  consumer actually cares about: "did the right concept show up at
  all".

### 4.2 `mean_tag_precision_at_k` (SECONDARY)

```
tag_precision_at_k(s) = |{h in top_k : tags(h) ∩ expected_tags(s) ≠ ∅}| / |top_k|
mean_tag_precision_at_k = mean over evaluable scenarios
```

- Diversity-aware caveat metric. Use to detect regressions where the
  RAG starts dumping the same-cluster duplicates back into the top-K.

### 4.3 `mean_cp_hit_at_k` (CP-level recall, NEW in commit 7fc1ca5)

```
cp_hit_at_k(s) = 1.0 if any retrieved canonical_pattern_id ∈ expected_canonical_pattern_ids(s) else 0.0
                (None if scenario carries no expected CP gold)
mean_cp_hit_at_k = mean over scenarios where cp_hit_at_k is not None
```

- Stricter than tag overlap. A scenario can pass tag-hit by
  accidentally matching `incomplete_metrics` while landing in the
  wrong CP; it cannot pass CP-hit unless the retriever lands in the
  pattern bucket the reviewer was reasoning in.
- Coverage on the baseline slice is 0 (no CP gold there); coverage on
  in_distribution is 136/155 = 0.877; on adversarial it is 35/35 =
  1.000. Always report the n_cp_evaluable alongside.

### 4.4 `coverage_rate`

```
coverage_rate = n_evaluable / n_scenarios
```

- Guard against ghost-improvement (Wave-A4 finding): if a future
  change shrinks the evaluable set, mean_hit and mean_tag_p can both
  rise while the system retrieves nothing on the dropped scenarios.
- **Hard rule**: any claim about `mean_hit_at_k` must cite
  `coverage_rate` in the same sentence.

### 4.5 `false_strong_hit_rate` (negative / distractor slices)

For the `negative` and `distractor` slices, a scenario has no positive
gold. The failure mode the slice is testing is **over-firing**: the
RAG returning a confident top-1 on a query that should not match
anything in the KB.

```
strong_hit(s) = 1 if top1_score(s) > 0.6 else 0
false_strong_hit_rate = mean over scenarios in slice of strong_hit(s)
```

- Threshold rationale: 0.6 is roughly the inflection where, on the
  baseline slice, top-1 hits become more often correct than not. The
  mean top-1 on baseline is 0.649 (see §3.1). Calibrate this
  threshold per release if the score distribution shifts.
- **Stricter variant** `false_max_hits_violation_rate` — for
  scenarios that carry `expected_max_hits`, fraction where the count
  of top-K hits with `_final_score > 0.6` exceeds `expected_max_hits`.

### 4.6 `mean_top1_score`

- Mean of the top-1 score across scenarios where the RAG returned >= 1
  hit. Mostly a diagnostic — useful to see whether a score
  distribution has drifted between releases (a 0.05+ shift in mean
  top-1 with stable hit@K means the calibration of the score has
  changed and downstream thresholds need to be re-validated).

### 4.7 Wall time

`wall_ms_total` is reported. The first scenario in any run dominates
because the BGE-small model loads lazily (13,313 ms on the frozen
baseline run; subsequent scenarios are 30-50 ms each). Excluding the
warm-up, expect ~50 ms / scenario on a 2023 M-series Mac.

---

## 5. Splits

### 5.1 Stratified 70/15/15 per slice

Each slice is split independently into train / dev / test with a
stratified 70/15/15 ratio. The stratification key per slice:

| Slice            | Stratify by              |
| ---------------- | ------------------------ |
| baseline         | `gate_name`              |
| in_distribution  | `_src_file` then `dimension` |
| adversarial      | sub-bucket (paraphrase / near_miss / distractor / lex / domain / length / mixed / codeswitch) |
| fairness         | concern category         |
| long_tail        | `canonical_pattern_id`   |
| compound         | number of expected CPs   |
| negative         | `oos_modality`           |
| distractor       | `distractor_type`        |
| ood              | source (Retraction / OpenReview / TRIPOD+AI / open-peer) |

Splits are **per-slice**, not global, so a published baseline number
on (say) `adversarial.test` is unambiguous.

### 5.2 Seed

```
SEED = 20260517
```

This is today's ISO date. Treat it as a frozen constant for the v1.x
line; bumping it constitutes a MAJOR version change.

### 5.3 Reference split assignment

A reference split assignment file `splits/v1.0.json` should be
materialised before any score is published. The file is a flat
`{scenario_id: "train" | "dev" | "test"}` mapping. Once published,
splits do **not** change across the v1.x line — only MAJOR version
bumps may reshuffle.

### 5.4 Reporting policy

- **Tuning** of RAG hyperparameters (e.g. WEIGHT_BM25,
  TAG_OVERLAP_MIN_SHARED) may be done on `dev` and reported.
- **Headline numbers** for a release MUST be reported on `test`.
- A run on `train ∪ dev ∪ test` (the full slice) is acceptable for
  smoke-regression checks and CI; it must be labelled
  `mode=full-slice` to distinguish it from a `test`-only claim.

---

## 6. Scoring conventions

### 6.1 Minimum claim unit

Any sentence claiming "the MLGG RAG achieves hit@K = X" MUST disclose:

1. **Slice** — exactly which slice file was run.
2. **Split** — `train`, `dev`, `test`, or `full-slice`.
3. **Mode** — `hybrid`, `bm25_only`, or `dense_only`.
4. **`coverage_rate`** — n_evaluable / n_total for that slice.
5. **`top_k`** — almost always 5; flag any deviation.
6. **Per-stratum breakdown** — for slices with internal sub-buckets
   (adversarial, distractor), report the per-bucket hit@K too.
7. **Tool version** — git SHA of `scripts/rag/` and KB SHA.

A claim missing any of (1)–(4) is rejected for documentation purposes.

### 6.2 Canonical example of a well-formed claim

> On `mlgg-bench/adversarial.test` (n = 6), mode = `hybrid`, top_k = 5,
> commit `<sha>`, KB hash `<sha>`: `mean_hit_at_k = 0.83`,
> `mean_cp_hit_at_k = 0.67`, `coverage_rate = 1.00`. Per sub-bucket:
> paraphrase 1.00 (2/2), near-miss 0.50 (1/2), distractor 1.00 (2/2).

### 6.3 Aggregating across slices

When a single headline number across the whole benchmark is desired,
report **macro-averaged** `mean_hit_at_k` across slices (equal weight
per slice, not per scenario). Rationale: the slices differ in size by
15x (10 vs 155); micro-averaging would let the in_distribution slice
dominate.

Macro headline (template):

```
macro_hit_at_k = mean over slices in {baseline, in_distribution,
                                      adversarial, fairness, long_tail,
                                      compound} of slice_mean_hit_at_k
```

Negative and distractor slices are **excluded** from the macro hit@K
(they don't measure recall) and reported as a separate
`macro_false_strong_hit_rate`.

### 6.4 What NOT to do

- Do not report `mean_tag_precision_at_k` as the headline. It is the
  secondary metric and is dominated by MMR diversity behaviour.
- Do not blend slices: "MLGG-Bench overall hit@K = 0.94" is a
  meaningless number if the slice breakdown isn't shown.
- Do not run a tuned config on `test` and report `dev` numbers as
  generalisation; that is the standard test-set-contamination
  failure.

---

## 7. Versioning

MLGG-Bench follows semantic versioning. The three components map as:

| Bump  | Trigger                                                                                       |
| ----- | --------------------------------------------------------------------------------------------- |
| MAJOR | Scenarios are removed, renamed, or have their gold (`expected_tags`, `expected_canonical_pattern_ids`) edited; splits reshuffled; SEED changed. |
| MINOR | New scenarios added; new slices added; new optional metric added; KB underneath bumped to a new contract_version. |
| PATCH | Metadata-only edits (description text, dimension labels, comments); doc-only changes; harness refactor with byte-identical scoring output. |

Rules:

- A MAJOR bump invalidates **all** previously published numbers.
- A MINOR bump invalidates **only** macro-averages and slice
  hit@K/cp_hit@K. Per-scenario rows for unchanged scenarios remain
  comparable.
- A PATCH bump invalidates **nothing**.

The version published in a paper should be the full `MAJOR.MINOR.PATCH`
plus the git SHA. Example: `MLGG-Bench v1.0.0 @ a1b2c3d`.

### 7.1 KB coupling

The KB underneath (`peer-review-kb.json`) carries its own
`contract_version` (currently `peer_review_kb.v1.4`). When the KB
contract bumps, MLGG-Bench bumps at least MINOR; if the KB drops
concerns referenced by `expected_canonical_pattern_ids`, MLGG-Bench
bumps MAJOR.

---

## 8. Known limitations

### 8.1 Internally-derived bias

155 of 270 materialised scenarios (57%) come from LLM paraphrase of
the same KB the RAG retrieves over. This is *by design* for measuring
paraphrase robustness, but it inflates hit@K versus what would be seen
on truly held-out peer reviews. The OOD slice (§3.1) exists to
disentangle this; until it lands, treat in_distribution numbers as an
upper bound.

### 8.2 KB tag-vocabulary incompleteness

A prior measurement round flagged ~24% out-of-vocabulary tags in
freshly-extracted reviewer concerns (i.e. 24% of tags an extractor
LLM proposed were not previously in the KB tag set). Tag-overlap and
hence `mean_tag_precision_at_k` are therefore intrinsically
under-counted on novel queries. The CP-hit metric (§4.3) was added
partly to mitigate this — CP membership is a more stable contract
than tag overlap.

### 8.3 No inter-rater agreement on baseline 30

The 30 baseline scenarios were curated by a single set of agents on
2026-04-23. There is no second-rater pass on whether the
`expected_tags` lists are exhaustive. A scenario that fails hit@K
under future stricter labelling cannot be distinguished from a
scenario that the rater happened to label sparsely. The labelled
P@5 set (`references/retrieval_eval/labeled_precision_at_5.json`)
addresses a subset but not all 30.

### 8.4 Score-threshold non-portability

The 0.6 threshold in `false_strong_hit_rate` is calibrated against
the v1.0 hybrid weights (BM25 0.45 / dense 0.10 / tag 0.30 /
severity 0.15). The W13-P0 rebalance shifted score distributions
substantially (the old hybrid_all configuration scored lower); the
threshold should be re-validated after any WEIGHT_* change.

### 8.5 First-scenario warm-up dominates wall time

`wall_ms_total` is dominated by the first BGE-small load on cold
runs. Single-scenario timing claims are not meaningful unless a
warm-up scenario is run first and discarded.

### 8.6 Long-tail CP coverage is thin

Per `peer-review-kb-stats.json`, the leakage and ci_matrix gates
together have 59 concerns covering 2 broad CPs; some tail CPs may
have only 3-5 concerns. The `long_tail` slice probes this but with
n=15 only — confidence intervals on tail hit@K will be wide.

### 8.7 Single language, single review style

All KB concerns and benchmark queries are in English, written in
Nature Methods / JAMA reviewer-style prose. Generalisation to
shorter / less-formal review queries (e.g. preprint comment
threads, conference reviewer rubrics) is untested.

### 8.8 Severity boost interacts with score thresholds

The severity boost can lift an off-topic CRITICAL above an on-topic
HIGH when dense-score spread is below `SEVERITY_FULL_SPREAD=0.20`.
The adaptive guard mitigates this but the negative / distractor
slices intentionally probe queries where the guard is the only
defence; expect non-zero `false_strong_hit_rate` there.

### 8.9 Compound-query scoring is partial-credit

`mean_cp_hit_at_k` on the compound slice records "any expected CP hit",
which a strict reviewer would call partial credit. The strict
`cp_hit_at_k_all` variant (§3.1, compound) is the harder metric; it
is **not** yet implemented in `run_eval.py` and would require a
small extension to `aggregate()`. Listed here so a future PR doesn't
miss it.

---

## 9. Reproducibility

### 9.1 Exact command to reproduce baseline numbers

```bash
# From the repo root /Volumes/Seagate/Skill/ml-leakage-guard
git checkout <baseline_sha>   # e.g. the sha that produced
                              # references/retrieval_eval/post_wave7_baseline_hybrid.json

# Cold (full warm-up included in wall time):
python3 scripts/rag/evals/run_eval.py \
    --mode hybrid \
    --scenarios references/retrieval_eval/scenarios.json \
    --top-k 5 \
    --output /tmp/mlgg_bench_baseline.md \
    --diff references/retrieval_eval/post_wave7_baseline_hybrid.json \
    --diff-required

# Expected output (frozen):
#   markdown: /tmp/mlgg_bench_baseline.md
#   json:     /tmp/mlgg_bench_baseline.json
#   mean hit@K (PRIMARY):       1.0
#   mean tag_precision@K (sec): 0.538
#   coverage_rate:              0.867 (n_evaluable=26/30)
```

If the printed numbers differ from the expected line, the
`--diff-required` flag will cause exit 2; investigate the per-scenario
delta table in the markdown sidecar before doing anything else.

### 9.2 Per-slice reproduction

```bash
# In-distribution (n=155)
python3 scripts/rag/evals/run_eval.py \
    --scenarios /tmp/mlgg_eval_expand/merged.json \
    --output /tmp/mlgg_bench_in_distribution.md

# Adversarial (n=20, agent_10 only as of v1.0)
python3 scripts/rag/evals/run_eval.py \
    --scenarios /tmp/mlgg_eval_expand/agent_10.json \
    --output /tmp/mlgg_bench_adversarial.md

# Negative (n=10)
python3 scripts/rag/evals/run_eval.py \
    --scenarios /tmp/mlgg_benchmark/bench_04_negatives.json \
    --output /tmp/mlgg_bench_negative.md
# NOTE: hit@K and tag_p@K will be N/A (no expected_tags). Use the
# JSON sidecar's per_scenario.top1_score to compute false_strong_hit_rate
# at threshold 0.6 manually until that metric is added to aggregate().

# Distractor (n=10)
python3 scripts/rag/evals/run_eval.py \
    --scenarios /tmp/mlgg_benchmark/bench_05_distractors.json \
    --output /tmp/mlgg_bench_distractor.md
```

### 9.3 Environment

- Python 3.11+
- `sentence_transformers` with model `BAAI/bge-small-en-v1.5`
  (downloaded once, cached under `.cache/rag/`)
- `rank_bm25` for the BM25 path
- No network access required after first model download
- KB cache invalidated automatically when KB SHA changes
  (`.cache/rag/kb_hash.txt`)

### 9.4 What to log alongside numbers

When publishing or filing a benchmark report:

1. `git rev-parse HEAD` of the repo
2. SHA256 of `references/case-studies/peer-review-kb.json`
3. SHA256 of the slice file
4. `python --version` and `pip freeze | grep -E "(sentence|torch|numpy|rank_bm25)"`
5. The full markdown + JSON output from `run_eval.py`
6. The four RAG weights and the values of
   `CP_TAG_BOOST_DENSE_FLOOR`, `SEVERITY_FULL_SPREAD`,
   `TAG_OVERLAP_MIN_SHARED`, `MMR_LAMBDA`, `MMR_COSINE_FLOOR`,
   `USE_DENSE_CORROBORATION`

### 9.5 Frozen reference numbers (v1.0)

The single source of truth for v1.0 reference numbers is this table.
Any future report that disagrees with these numbers without a MAJOR
or MINOR version bump is a regression.

| Slice            | Split      | Mode   | n   | n_evaluable | coverage_rate | mean_hit@K | mean_tag_p@K | mean_top1 | mean_cp_hit@K |
| ---------------- | ---------- | ------ | --- | ----------- | ------------- | ---------- | ------------ | --------- | ------------- |
| baseline         | full-slice | hybrid |  30 |          26 |         0.867 |      1.000 |        0.538 |     0.649 |          N/A  |
| in_distribution  | full-slice | hybrid | 155 |         TBD |           TBD |        TBD |          TBD |       TBD |           TBD |
| adversarial      | full-slice | hybrid |  20 |         TBD |           TBD |        TBD |          TBD |       TBD |           TBD |
| fairness         | full-slice | hybrid |  10 |         TBD |           TBD |        TBD |          TBD |       TBD |           TBD |
| long_tail        | full-slice | hybrid |  15 |         TBD |           TBD |        TBD |          TBD |       TBD |           TBD |
| compound         | full-slice | hybrid |  10 |         TBD |           TBD |        TBD |          TBD |       TBD |           TBD |
| negative         | full-slice | hybrid |  10 |           0 |           N/A |        N/A |          N/A |       TBD |           N/A |
| distractor       | full-slice | hybrid |  10 |           0 |           N/A |        N/A |          N/A |       TBD |           N/A |
| ood              | full-slice | hybrid | TBD |         TBD |           TBD |        TBD |          TBD |       TBD |           TBD |

TBD numbers will be filled in by the bench-agent-09/10 publication
run; until then, do not cite an MLGG-Bench v1.0 number you cannot
trace to this table.

---

## Appendix A: Slice file manifest (v1.0)

```
/tmp/mlgg_benchmark/
  BENCHMARK_SPEC.md                          (this file)
  bench_01_fairness.json                     (TBD)
  bench_02_longtail.json                     (TBD)
  bench_03_compound.json                     (TBD)
  bench_04_negatives.json                    (10 scenarios, materialised)
  bench_05_distractors.json                  (10 scenarios, materialised)
  bench_07_adversarial.json                  (TBD)
  ood_01_retraction_watch.json               (TBD)
  ood_02_openreview.json                     (TBD)
  ood_03_tripod_plus_ai.json                 (TBD)
  ood_04_open_peer_journals.json             (TBD)
  splits/
    v1.0.json                                (TBD; flat scenario_id -> split map)

references/retrieval_eval/                   (in-repo, baseline only)
  scenarios.json                             (30 scenarios, version 1.1)
  post_wave7_baseline_hybrid.json            (frozen baseline numbers)

/tmp/mlgg_eval_expand/                       (10-agent in_distribution + agent_10 adversarial)
  merged.json                                (155 scenarios)
  agent_10.json                              (20 adversarial scenarios)
```

## Appendix B: KB summary (provenance for §1)

From `references/case-studies/peer-review-kb-stats.json`
(contract `peer_review_kb.v1.4`):

- Total papers: **335**
- Total reviewer concerns: **817**
- Total reviewer strengths: 239
- Unique canonical patterns: **49** (CP-001 .. CP-049, verified)
- Top categories: evaluation_metrics 196, study_design 172,
  reporting 95, external_validation 68, model_selection 58
- Severity mix: MEDIUM 412, HIGH 304, LOW 60, CRITICAL 41
- Top gates: evaluation_quality_gate 255, cohort_definition_gate 207,
  reporting_bias_gate 195, clinical_metrics_gate 163,
  model_selection_audit_gate 108

## Appendix C: Glossary

- **CP** — canonical pattern. A reviewer-concern equivalence class
  (e.g. CP-027 = "single-split bootstrap is not model-parameter
  uncertainty"). Numbered CP-001 to CP-049 in KB v1.4.
- **Gate** — a fail-closed MLGG audit module (e.g. `leakage_gate`,
  `ci_matrix_gate`). 33 gates total in the parent project.
- **Failure code** — symbolic identifier a gate emits when it fires
  (e.g. `single_split_no_bootstrap`). Used by the production
  gate-to-RAG bridge to compose a query.
- **Hit@K** — binary per scenario: did any expected tag appear in any
  of the top-K returned concerns. Primary headline metric.
- **CP-hit@K** — binary per scenario: did any expected
  `canonical_pattern_id` appear in any top-K returned concerns.
  Stricter than hit@K.
- **Coverage rate** — fraction of scenarios in a slice that carry
  enough gold to be evaluable. Guard against ghost regressions.
- **MMR** — Maximal Marginal Relevance reranking; balances relevance
  vs intra-result diversity.
- **Strong hit** — top-1 score > 0.6 on a query that should not match
  (negative / distractor slices).

---

*End of spec, MLGG-Bench v1.0.0, 2026-05-17.*
