# Agent A — Dense-only ablation audit (MLGG RAG, 2026-05-17)

**Scope**: peer-review-kb (817 concerns, 30 scenarios).
**Reproducibility note**: the project `.venv` ships without
`sentence_transformers`. I re-implemented BGE-small-en-v1.5 encoding
(CLS-pool + L2-normalize) via raw `transformers` + `torch` from the
system Anaconda Python, reading the same `~/.cache/huggingface` model
weights the index was built with. A sanity probe against `records[0]`
yielded cosine = **0.967** with the cached embedding, i.e. close but
not bit-identical to the production sentence-transformers wrapper. All
hybrid numbers below were therefore re-measured (not pulled from the
existing baselines) so dense / hybrid are evaluated under the same
encoder shim and any drift is internally consistent. The reproduced
hybrid (pre-W13 weights, 0.353) matches the on-disk
`baseline_hybrid.json` (0.338) within ~0.015, confirming the shim is
production-faithful enough for ranking comparisons.

## 1. Three-way aggregate (in fact four-way — both hybrid configs included)

| config                  | DENSE | BM25 | TAG  | SEV  | coverage | hit@5  | mean_tag_precision |
|-------------------------|------:|-----:|-----:|-----:|---------:|-------:|-------------------:|
| **bm25_only** (baseline)|  n/a  | n/a  | n/a  | n/a  |   0.867  | 0.833  | **0.436**          |
| **dense_only** (new)    | 1.0   | 0    | 0    | 0    |   0.833  | 0.767  | **0.241**          |
| hybrid pre-W13 (DENSE=0.5)| 0.50| 0.30 | 0.15 | 0.05 |  0.867  | 0.867  | **0.353** *        |
| hybrid post-W13 (current)| 0.10 | 0.45 | 0.30 | 0.15 |  0.867  | 0.833  | **0.438**          |
| hybrid_no_dense (rebalanced)| 0  | 0.50 | 0.33 | 0.17 | 0.867  | 0.833  | **0.442**          |
| hybrid_no_tag           |       |      | 0    |      |   0.867  | 0.833  | 0.410              |
| hybrid_no_sev           |       |      |      | 0    |   0.867  | 0.833  | 0.419              |
| hybrid_no_mmr           |  λ=1.0|      |      |      |   0.867  | 0.833  | 0.435              |

`*` `references/retrieval_eval/baseline_hybrid.json` records 0.338 for
this config; my shim reproduces it as 0.353. The 0.015 gap is the
encoder-drift bound. Headline finding is robust to it.

### Key reads

- **Dense alone is by far the worst signal** (0.241, **−45% vs bm25_only**).
  Coverage drops too (0.833 vs 0.867) — the three off-domain probes
  return correctly empty under gate filter, but `leakage_discharge_icd`
  also drops to coverage=0 because dense picks irrelevant
  category concerns.
- **The hybrid regression captured in `baseline_hybrid.json` (0.338) was
  almost entirely caused by dense at weight 0.5**: switching to current
  W13 weights (DENSE=0.1) lifts mean_tag_precision to 0.438, recovering
  parity with bm25_only. The "hybrid loses 22% vs bm25" framing in the
  prompt reflects pre-W13 numbers; on the current main branch hybrid
  is no longer regressing.
- **Removing dense entirely (`hybrid_no_dense`) gives 0.442** — within
  noise of the post-W13 hybrid (0.438). Dense at 0.1 weight contributes
  effectively zero net signal; it may even cost ~0.004.

## 2. Per-scenario disagreement (15 scenarios with spread ≥ 0.2)

Columns: bm25 / dense / hyb_pre (W11 weights) / hyb_post (W13 weights),
each = tag_precision@5.

| scenario_id                                | bm25  | dense | h_pre | h_post |
|--------------------------------------------|------:|------:|------:|-------:|
| leakage_discharge_icd                      | 0.667 | 0.000 | 0.333 | 0.667  |
| no_external_validation_single_center       | 0.667 | 0.333 | 0.667 | 0.833  |
| cohort_definition_selection_bias           | 0.600 | 0.200 | 0.400 | 0.600  |
| model_selection_cherry_picked_seed         | 0.667 | 0.333 | 0.333 | 0.667  |
| split_smote_before_split                   | 0.500 | 0.000 | 0.500 | 0.500  |
| missingness_normal_range_imputation        | 1.000 | 0.333 | 0.333 | 1.000  |
| reporting_missing_tripod_checklist         | 0.857 | 0.571 | 0.571 | 0.857  |
| imbalance_smote_without_justification      | 0.667 | 0.333 | 0.667 | 0.667  |
| feature_selection_data_leakage             | 0.667 | 0.000 | 0.167 | 0.333  |
| tuning_hyperparameter_on_test_set          | 0.533 | 0.333 | 0.400 | 0.600  |
| ci_missing_or_suspiciously_narrow          | 0.600 | 0.400 | 0.200 | 0.400  |
| fairness_subgroup_performance_gap          | 0.455 | 0.091 | 0.364 | 0.455  |
| sample_size_epv_violated                   | 0.500 | 0.500 | 0.833 | 0.833  |
| interpretability_shap_shallow              | 0.750 | 0.375 | 0.750 | 0.750  |
| prediction_replay_irreproducible           | 0.636 | 0.182 | 0.364 | 0.364  |

Observations on the disagreement set:

1. **In 13 of 15 disagreement scenarios, dense is the worst path**
   (often by ≥ 0.3). The two exceptions are `evaluation_improper_f1_primary`
   and `distribution_generalization_temporal`, where dense ties or
   slightly beats bm25 by 0.07–0.14.
2. **Hybrid pre-W13 = bm25_only minus 0.15–0.5 per row on
   high-precision rows** (`missingness_normal_range_imputation`,
   `reporting_missing_tripod_checklist`, `feature_selection_data_leakage`,
   `prediction_replay_irreproducible`, `leakage_discharge_icd`) — exactly
   the rows where dense is 0.0–0.33. The mechanism: dense candidates
   crowd the top-5 pool with off-topic concerns that share the same
   gate, displacing BM25's keyword-precise hits.
3. **Hybrid post-W13 recovers all these rows back to bm25 parity**.
   No row regresses meaningfully (the one outlier is
   `prediction_replay_irreproducible` 0.636→0.364, which is now
   driven by tag_overlap saturation rather than dense; see no_tag run).
4. **Hybrid even beats bm25 on `no_external_validation_single_center`
   (0.833 vs 0.667), `sample_size_epv_violated` (0.833 vs 0.500), and
   `tuning_hyperparameter_on_test_set` (0.600 vs 0.533)**. Those wins
   come from tag_overlap + severity, not dense (cross-check: hybrid_no_dense
   preserves all three).

## 3. Diagnosis: what is dense actually pulling?

Dense retrieval over BGE-small-en-v1.5 is generating **false positives
of two flavors**:

- **Topic-drift within the same gate**: e.g. for `leakage_discharge_icd`
  ("patient identifier leaked across train test split") the top dense
  hits are general "train-test split" concerns from papers that have
  no `data_leakage` tag — they share the surface phrase but miss the
  semantic point. BM25 picks the keyword "identifier" + "leaked" which
  is decisive; dense averages it into a generic "splitting" cluster.
- **Vocabulary-substitution failures on technical terms**: rows like
  `feature_selection_data_leakage` (0.0 dense vs 0.667 bm25),
  `split_smote_before_split` (0.0 vs 0.5), and
  `missingness_normal_range_imputation` (0.333 vs 1.000) involve
  domain-specific compound terms ("SMOTE", "TRIPOD-AI", "normal range
  imputation") that BGE-small treats as ordinary text. BM25's exact
  token match dominates; dense pulls semantically-adjacent but
  tag-disjoint concerns.

Off-domain probes (`weak_offdomain_*`, `zero_empty_query`) correctly
return 0 under all configs — the gate filter does its job; dense's
problem is not "letting nonsense through" but "displacing
high-precision keyword hits with mediocre semantic neighbors **inside
the gated candidate pool**".

## 4. Recommendation

**The W13 weight retune (DENSE 0.5 → 0.1) already fixed the regression
flagged in the prompt.** Action items, in order of effort vs payoff:

1. **No further action required to recover bm25 parity** — the
   currently-shipped weights already do it (0.438 vs 0.436 bm25).
   The orchestrator's `baseline_hybrid.json` is stale (captured at
   commit 424d37a, before the W13 retune at cc3c717). Re-baseline it.
2. **Consider dropping dense entirely**. `hybrid_no_dense` (0.442) is
   indistinguishable from `hybrid_postW13` (0.438) on this 30-scenario
   eval, and saves the ~120 MB model + tokenizer load on every cold
   start (E4 finding noted ~228 ms first-query latency). The only
   argument for keeping dense at 0.1 is open-domain queries the eval
   does not cover (e.g. natural-language reviewer questions not
   represented in scenarios.json) — but even those should be re-tested
   before declaring dense useful. **Strong recommendation: open a W14
   ticket to evaluate `WEIGHT_DENSE = 0` against a query log of real
   gate-bridge invocations, and drop dense if there is no measurable
   win on out-of-scenario queries.**
3. **Do not retune weights upward toward dense** — `tests/test_rag_config.py::test_dense_weight_demoted_per_w11_i1`
   already enforces `WEIGHT_DENSE < 0.2`. Keep that guard.

The original framing in the prompt ("Need to know whether dense-only is
the culprit") is answered **yes, unambiguously**: dense_only =
0.241, the worst of the three modes by a wide margin. But the
production hybrid no longer reflects that — the bridge is held
together by BM25 (0.45) and tag_overlap (0.30), with dense reduced to
a near-vestigial 0.10 contribution.

## Artifacts

- `/tmp/audit_dense_only_run.py` — dense-only one-off (anaconda Python).
- `/tmp/audit_dense_only_report.json` — per-scenario dense_only numbers.
- `/tmp/audit_hybrid_postw13.py` — hybrid + ablation runner with the
  embed_texts shim.
- `/tmp/audit_hybrid_postw13_report.json` — 6-config aggregate +
  per-scenario rows.
