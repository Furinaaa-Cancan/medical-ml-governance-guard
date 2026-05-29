# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 2026-05-17 session — W14 RAG audit + retroactive W7–W13 log (audit honesty)

Retroactive supplement: the W7-through-W13 RAG architecture work (the
basis for every current eval number) was never logged in CHANGELOG;
it lived only in `docs/diagnostics/W7*` and JSON `description` fields.
Audit W14-J flagged this as a documentation-honesty gap. This entry
closes it.

#### Retroactive: W7–W13 RAG work that landed without CHANGELOG entry

- **W7 (post-Wave-7)** — initial production hybrid baseline established.
  Aggregate from `references/retrieval_eval/post_wave7_baseline_hybrid.json`
  (mode=hybrid, top_k=5, 30 scenarios): coverage_rate 0.867,
  mean_hit_at_k 1.0, **mean_tag_precision_at_k 0.5385**, n_zero_hits 4.
  This file is the authoritative current-state baseline; earlier
  `baseline_hybrid.json` is W11-era and stale.
- **W8/W2** — first hand-labeled (LLM-self-eval) Precision@5 ground-truth
  set: 20 queries (1 per sub-dimension). Provides a longitudinal anchor
  independent of the proxy `expected_tags` metric.
- **W9/A2** — extended W8/W2 to **36 queries (L01–L36)**, adding 16
  in-scope queries that bring the 8 highest-stakes governance
  sub-dimensions (touching non-negotiable rules S01/F01/F02/P01/M01/E01/E02)
  to 3 queries each. Stable IDs across drift checks. Off-scope probes
  L19, L20 are pinned at P@5=0 (false-positive regression guard).
- **W11/I1** — dense-retrieval-weight demotion confirmed: dense_only
  scores mean_tag_precision 0.241 (worst of all configs); dense at
  high weight degrades hybrid. Test guardrail
  `tests/test_rag_config.py::test_dense_weight_demoted_per_w11_i1`.
- **W13** — fusion-weight rebalance to `WEIGHT_BM25=0.45` with residual
  `2:6:3` split across `DENSE:TAG:SEV` (i.e. DENSE=0.10, BM25=0.45,
  TAG=0.30, SEV=0.15). Lifts hybrid mean_tag_precision from 0.338
  (W11-era) to 0.438+ and hit@5 to 1.0. Configured in
  `scripts/rag/config.py`.
- **MMR rerank** — `MMR_COSINE_FLOOR = 0.88` and
  `CP_TAG_BOOST_DENSE_FLOOR = 0.70` set during W7/W8 retrieval-quality
  tuning; live in `scripts/rag/config.py`.
- **H1 BM25 synonym expansion** — handled in the BM25 query path; see
  `scripts/rag/retrieval/bm25.py`.

Source-of-truth files: `docs/diagnostics/W7P0_*.md`, `W7P1_*.md` …
`W7P9_*.md`, `W8W10_*.md`, plus
`references/retrieval_eval/post_wave7_baseline_hybrid.md`. CHANGELOG
should NOT duplicate those — refer to them.

#### 2026-05-17: W14 RAG audit findings + remediation

- **M1 — `labeled_precision_at_5.json` description mis-claimed
  "human-labeled ground truth"** when labels are LLM self-eval (Claude
  Opus 4.7, same model family as the retrieval pipeline → circular).
  Description rewritten + `labeling_protocol.circularity_warning`
  added; mirrored in `tests/test_labeled_precision.py` docstring
  (commit `93e6e3d`, audit W14-E). Absolute `mean_labeled_P5=0.639`
  remains internal-use-only until independent human re-labeling.
- **M2 — KB content gap, not retrieval failure.** L27 ("scaler fit
  before split") scored P@5 = 0/5 because `peer-review-kb.json` has
  zero concerns describing the canonical MLGG-P01 pattern. `MLGG-P01`
  tag occurs exactly once in the KB and is mis-applied. Curated
  fallback landed in `scripts/core/gate_rag_bridge.py` (commit
  `c8e651c`, audit W14-B) as a band-aid; long-term fix is 7-rule
  KB-coverage audit (S01/P01/F01/F02/M01/E01/E02).
- **M3 RETRACTED** — "hybrid -22% tag_precision" was based on the
  stale W11-era `baseline_hybrid.json` (0.338). Production is at
  0.438–0.538 per `post_wave7_baseline_hybrid.json`. The remaining
  substantive issue is metric disagreement between proxy
  `mean_tag_precision` and `mean_labeled_P@5`, now resolved by writing
  `references/retrieval_eval/METRIC_CONTRACT.md` (commit `49e1222`,
  audit W14-G).
- **M5 (upgraded to Major) — `cohort_definition_gate` had zero lit
  support while absorbing 46% of reviewer-concern volume** (207/449
  concerns). 38 gate-tag additions across 26 entries close it +
  12/14 fragile-gate gaps in `references/methodology/literature-
  knowledge-base.json` (commit `de27889`, audit W14-C). Residual:
  `shap_interpretability_gate` remains 0-support — real KB content
  gap (Lundberg 2017/2020 missing); content-add task tracked
  separately.
- **m4 — 14 fragile single-source gates** mostly closed via the same
  commit `de27889`: 7 lifted to ≥3 supporters, 5 to 2, 2 by design
  (`execution_attestation_gate`, `manifest_lock` are SLSA-spec
  anchored).
- **m6 — 4 "untagged" entries clarified**: LIT-004 (TRIPOD-LLM) and
  LIT-042 (multiclass) keep empty `gates_implementing` by design
  (self-declared out-of-MLGG-scope); LIT-018 (CONSORT-AI) and LIT-019
  (SPIRIT-AI) got `reporting_bias_gate` + `publication_gate` in
  `de27889`.
- **m7 — `entries[:20]` no-sort truncation in
  `scripts/reporting/export_review_prompt.py`** — fixed earlier this
  session in commit `dd7678b` with composite sort key
  `(gate/dim overlap, year DESC, IF DESC)`. 7 new tests, 361 total
  tests pass.
- **m8 RETRACTED** — `scripts/rag/retrieval/bm25.py:271` `entries[:5]`
  is intentional shape-sampling in `_validate_kb_shape()`, not a
  retrieval cap. False positive; audit-self-correction logged.
- **KB metadata honesty (audit W14-H minor)** — KB top-level
  `total_concerns: 449` was stale (actual 817); fixed to 817 in
  commit `ca1f2e3`. `peer-review-kb-stats.json` and
  `peer-review-kb-tags.json` regenerated via `parse_peer_reviews.py
  --stats`.
- **New Major (deferred)** — `baseline_hybrid.json` is W11-era stale;
  every `--strict` CI regression check has been comparing against
  2-commit-old numbers, falsely flagging the actually-improved
  hybrid as "regressing 22%". Re-baseline blocked locally on a
  `.venv` `transformers` corruption from concurrent pip races;
  rerun in a clean worktree.
- **New Major (deferred to F-01 follow-up)** — `disease-definition-
  knowledge-base.json` is LLM-compiled across all 11 entries with
  zero clinician sign-off. `cohort_definition_gate` /
  `definition_variable_guard` / `feature_lineage_gate` consume the
  un-arbitrated `definition_variables_to_exclude` as truth. PROVISIONAL
  banner work tracked separately.

#### W7–W9 documentation gap noted

Anyone reading the canonical CHANGELOG today before this entry would
not have learned that the W8-W2 labeled set, the post-W7 0.538
tag-precision, or the MMR-floor tuning exists. This is now corrected.
Future RAG work that lands without a CHANGELOG entry should be
considered "in flight" and flagged in PR review.

#### W14 self-review erratum — `d53a9e5` re-baseline attribution

The commit message of `d53a9e5` (W14 re-baseline) credited audit-W14-C
(KB tag adds) and audit-W14-B (curated MLGG-P01 fallback) for the
tag_precision lift 0.538 → 0.669. **Both attributions are wrong.**

Post-hoc A/B isolation (R3 self-review pass, 2026-05-17):
- Disabling audit-B's curated fallback via `MLGG_RAG_DISABLE_CURATED=1`
  → tag_precision unchanged at 0.6692.
- Rolling `literature-knowledge-base.json` back to pre-audit-C state
  (`de27889^`) → tag_precision unchanged at 0.6692.

The actual driver is parallel-session commit `cc3c717` (W13-P0)
demoting `WEIGHT_DENSE` from 0.5 → 0.1 and rebalancing BM25/TAG/SEV.
That landed 2 hours before the W14 re-baseline at 10:35 local; the
0.538 number was generated at 08:26 under the old DENSE=0.5 weights.

See `docs/diagnostics/W14_audit/R3_baseline_attribution_correction.md`
for the full A/B method, timeline, and the methodological reflection
on why this kind of attribution inflation is exactly what reviewer-
mode should catch.

The re-baseline operation itself is still legitimate (the on-disk
W11-era 0.338 was stale and blocked `--strict` regression detection).
Only the causal claim in `d53a9e5`'s commit message needs to be read
with this erratum attached.



Six commits narrowing MLGG's self-declared scope to retrospective-cohort
binary-classification and closing the self-flagged cohort-selection-bias
weakness.

#### Scope narrowed + omics modality guard

- **Positioning**: 能力边界 now states "retrospective cohort" (EHR / registry /
  case-control / cross-sectional) binary-classification. Removes the
  previous `医学二分类` framing that invited TCGA / scRNA-seq / GWAS users
  who hit noisy EPV failures. Synced across SKILL.md, CLAUDE.md,
  `examples/template/README.md`, `scripts/diagnostics/init_guide.py`.
- **`mlgg-lint` R028 — omics feature prefix guard** (ERROR). Rule fires
  when ≥3 feature-list literals match
  `gene_/probe_/snp_/cpg_/rs\d+/ENSG\d+/ENST\d+`; directs users to
  Scanpy / TCGAbiolinks+limma/DESeq2 / PLINK+GCTA instead of MLGG.
  +5 unit tests including rsID and Ensembl patterns. Commit `35d4d59`.

#### Documentation calibration

- **ARCHITECTURE.md** "Three Product Entry Points" was wrong — `audit-metrics`
  is a subcommand under `mlgg`, not a standalone product. Corrected to
  "Two Products + 28-subcommand CLI" with canonical-flow examples.
- **SKILL.md Quick Dispatch** previously surfaced 8/28 subcommands (28%
  coverage). Expanded to all 28 subcommands grouped by intent:
  主流程 (5) / 流水线步骤 (4) / 交互入口 (2) / 环境元数据 (3) /
  单 gate 直调 (2) / 审计外部项目 (6) / Benchmark 内部 (6). Commit `842590c`.

#### P1: cohort selection-bias controls

- **`cohort_definition_gate`** — three new structural checks closing
  the ⚠️ 弱 self-flag in SKILL.md §"能力边界":
  - `--cohort-spec` JSON declares inclusion/exclusion cascade;
    new failures: `COHORT_CASCADE_UNDOCUMENTED`
    (FAIL at `claim_tier=publication-grade`, WARN otherwise),
    `COHORT_CASCADE_MONOTONICITY` (n_after must be non-increasing),
    `COHORT_CASCADE_MISMATCH` (declared final_cohort_size vs actual
    CSV rows, >1% tolerance → FAIL).
  - **Table 1 auto-generation** per TRIPOD+AI 2024 Item 13a — emits
    `evidence/cohort_table_one.csv` with continuous features rendered
    as mean (SD), binary as n (%) per level, categorical as top-5
    levels; stratified by outcome. Zero external deps (no `tableone`
    package). Artifact-only, never triggers fail.
  - `--claim-tier` flag (`leakage-audited` default vs.
    `publication-grade`) gates cascade severity.
  - `--cohort-spec.index_date_col` existence check; actual
    immortal-time value-range detection is deferred (see below).
  - `references/templates/request-schema.example.json` gains
    `cohort_spec` block.
  +14 unit tests (cascade monotonicity, size mismatch, tier severity,
  index-date presence, Table 1 structure). Commit `538e4bc`.
- **Table 1 binary rendering fix**. Binary columns encoded as
  non-0/1 values (male/female in SUPPORT2, Yes/No, 1/2) were dropping
  to "0 (0.0%)" because the `(series == 1).sum()` shortcut returned
  zero on string-encoded data. Now enumerates both unique levels and
  renders `level_A=n (p%); level_B=n (p%)` with deterministic sort;
  +2 tests (string encoding, 0/1 regression guard). Commit `870bec5`.

#### Immortal time bias detection

- **`leakage_gate`** gains `IMMORTAL_TIME_RE` matching post-index
  treatment/intervention patterns: `received_*` / `prescribed_*` /
  `administered_*` / `treated_with_*` / `underwent_*` / `started_on_*` /
  `initiated_*` / `assigned_to_*` / `given_*`. New code
  `immortal_time_bias_pattern` (FAIL, not WARN) with Suissa 2008
  Am J Epidemiol and Hernán 2016 JCE citations in remediation.
  Closes red-team fixture
  `experiments/paper/redteam/r4/test_38_immortal_time_bias.py`
  (`received_drug_x` was previously uncaught by any gate). +12 tests
  (regex matches, benign-name non-matches, integration test
  reproducing the red-team feature set). Zero false positives across
  all 16 example CSVs. Level 1 date-value-range detection
  (column values > declared `index_date_col`) remains on the
  roadmap — name heuristic closes the concrete red-team hole; the
  value-range check requires cross-referencing cohort_spec with CSV
  values and is best done as a dedicated follow-up. Commit `22dcc42`.

#### CI infrastructure — ci-security rescue

- **`tests/conftest.py`** was eager-importing `numpy` and `pandas` at
  module load, which broke `ci-security` because that workflow
  deliberately installs only `pytest` (the five test files under test
  genuinely don't need numpy/pandas). Every push since commit `6a5b1ce`
  had been failing `ci-security` with
  `ModuleNotFoundError: No module named 'numpy'` + pytest exit code 4.
  Fix moves the imports into `make_binary_csv` (the sole fixture that
  uses them). Verified in a clean venv with only pytest installed:
  294 passed, 3 skipped across the 5 ci-security test files.
  Commit `8ce09dc`.

### 2026-04 earlier session — first-principles audit + three dogfood runs

23 commits driven by a first-principles audit plus three real-dataset
dogfood runs (NHANES 15549 rows × 14 features, diabetes_130 10000 × 19,
SUPPORT2 9105 × 46). Grouped by theme.

### Leakage detection — core capability extended

- **`leakage_gate` regex now catches post-index feature names**. Added
  five pattern groups for classic post-admission/discharge leakage that
  SKILL.md §"Feature Timeline Audit" explicitly calls out but the gate
  was previously silent on:
  - `time_in_hospital` / `length_of_stay` / `los` — stay duration
  - `num_medications` / `num_procedures` / `num_lab_procedures`
  - `discharge` / `discharged_*` — discharge disposition
  - `ventilation_hours` / `ventilation_duration` — ICU in-stay
  - `vasopressor_*` — ICU in-stay
  Verified on diabetes_130 dogfood: 5 of 6 clear post-index features
  caught in one shot (83% recall, 100% precision, `change_yes` missed
  by design — name is too generic to gate on). Under `--strict`
  (onboarding default) preflight correctly aborts before training.
- **`cohort_definition_gate` pattern list now disease-scoped**. Previous
  flat `_DEF_PATTERNS` mixed generic target-adjacent markers (mortality,
  death, readmit, surv\d) with diabetes-specific lab names (hba1c,
  glucose, fbg, ogtt), causing false positives on non-diabetes targets
  (SUPPORT2 mortality target: `glucose` was flagged as a definition
  variable). Split into `_GENERIC_PATTERNS` (always fire) and
  `_DISEASE_SPECIFIC_PATTERNS` (fire only when target-disease inferred
  matches: diabetes / ckd / heart_failure / copd). Details include
  `inferred_target_disease` and `pattern_scope` for audit.

### Peer-review KB — retrieval accuracy

- **Retrieval is now issue-code-aware, not severity-only**.
  `retrieve_by_gate(gate_name, limit=5)` sorted candidates by severity
  after filtering on `mlgg_gates`, returning CRITICAL-severity
  topically-irrelevant concerns ahead of on-target ones
  (clinical_metrics ppv failure returned target_leakage concerns first
  — ~20% precision). New `retrieve_for_failure(gate_name, issue_codes)`
  tokenizes the code list, filters stopwords, and re-ranks by
  `3 × tag_overlap + text_overlap`. Falls back to severity-only when no
  keyword hits so coverage never regresses to empty.
- **`_gate_framework` now retrieves peer-review context for
  warnings-only gates too**. The previous `if failures:` guard left
  warning-only failed gates (cohort_definition, split_protocol,
  missingness_policy under `--strict`) with empty context arrays. Fix
  triggers retrieval for `failures or warnings`.
- **KB `mlgg_gates` index rebuilt**. 276 of 375 concerns (73.6%) had
  <!-- NOTE 2026-05-29: "375" was the KB size at this wave; the KB has since grown to 817 concerns / 335 papers (154 with concerns). Historical figures below are left intact. -->

  empty `mlgg_gates` arrays — `peer_review_lookup.py --gate` silently
  missed ~75% of the KB. Added `scripts/review/backfill_peer_review_gates.py`
  (idempotent, deterministic category+tags → gates rule table);
  brought empty count to 0/375. Also corrected a `subgroup` tag
  over-match that wrongly routed 4 concerns (confounder stratification
  / clinical heterogeneity / small subgroup / selective reporting) to
  `fairness_equity_gate`.
- **Leakage coverage on existing KB bumped via surgical
  re-tagging**. 10 concerns with leakage-adjacent `tags`
  (target_leakage / data_leakage_via_imputation / patient_overlap /
  train_test_overlap / data_leakage_via_tuning / etc.) but missing
  `leakage_gate` in their `mlgg_gates` list have been augmented.
  `--gate leakage_gate` retrieval went from 3 → 13 concerns.

### Knowledge base provenance — disease definitions

- **Disease KB now declares per-entry provenance**. All 11 entries in
  `references/methodology/disease-definition-knowledge-base.json` now
  have a `provenance` block declaring `source=llm_compiled` and
  `clinician_review_status=pending`. The KB was consumed by
  `cohort_definition_gate` and `definition_variable_guard` as ground
  truth; now downstream NHANES+UKB+Registry `task_aware_validate`
  propagate `kb_provenance` into each emitted issue's details and
  append "[KB entry is LLM-compiled and not yet clinician-reviewed]"
  to messages. A shared helper
  `scripts/codebooks/_kb_provenance.extract_kb_provenance()` dedupes
  the three consumer paths.
  See `references/methodology/DISEASE_KB_REVIEW.md` for the clinician
  review checklist.

### Paper-review agent — evidence-backing audit

- **Reviewer agent now penalizes unsubstantiated methodology claims**.
  `score_paper_metadata.py` audits each positive leakage-assessment
  claim (patient_level_split / temporal_split / preprocessing_fit /
  tuning_used_test_data) against its paired `_evidence` quote field.
  Missing quotes emit `unsubstantiated_claims` findings and set
  `leakage_flags._has_unsubstantiated_claims`. `agents/extractor.yaml`
  rule #6 and `agents/reviewer.yaml` evidence-backing rule direct the
  LLMs to leave a boolean as null rather than over-claim without a
  verbatim quote. Contract version bumped to `paper_score.v1.1`.
- **Reviewer 12-dimension scoring now includes "Leakage Prevention"
  (weight 15, the maximum)**. Previous `agents/reviewer.yaml` 12-dim
  scheme had no leakage dimension at all — tool named `ml-leakage-guard`
  was scoring papers without evaluating leakage. Added
  `tests/test_scoring_consistency.py` as a drift regression guard.

### Tier and cross-sectional awareness

- **Cross-sectional dataset support**. When the request sets
  `cross_sectional: true` (auto-set by onboarding for single-CSV runs
  without a time column), `run_dag_pipeline` forwards
  `--cross-sectional` to `definition_variable_guard` (suppresses
  `temporal_spec_missing` warning because prediction_time / follow_up_window
  don't apply) and `split_protocol_gate` (treats cross_sectional as
  user-acknowledged; suppresses reminder).
- **Onboarding auto-generates outcome_definition stub** for
  exploratory runs. `configs/outcome_definition.json` is written with
  `source: "exploratory_auto_generated"` so cohort_definition_gate
  skips the publication-grade rigor checks (≥2 sources, adjudication,
  exclusions list, time_window) that would spam warnings on every
  `--input-csv` onboarding. Real rigor checks still fire on
  user-curated specs.

### `request_contract` path normalization

- **Leakage-audited tier now normalizes path fields used by Layer 5/6
  gates**. `prediction_trace_file`, `ci_matrix_report_file`, and
  `feature_engineering_report_file` were previously gated behind
  `require_lineage` (publication-grade only). For leakage-audited runs
  this left downstream gates (calibration_dca, prediction_replay,
  ci_matrix, feature_engineering_audit) crashing at argparse on
  required CLI flags. Path normalization is now unconditional for
  these fields; content-shape validation (rigid report structure
  checks) remains tier-gated.

### Gate reliability fixes

- **`distribution_generalization_gate`**: `--external-validation-report`
  is now argparse-optional. When omitted (leakage-audited tier without
  external cohort), the gate evaluates internal drift only rather than
  crashing at `Path(None)`.
- **`calibration_dca_gate` / `ci_matrix_gate`**: removed
  `no_external_validation` / `transport_ci_skipped` warnings when the
  ext report was absent-by-design (leakage-audited), which
  `--strict`-mode had promoted to false failures.
- **`self_critique_gate`**: added two argparse flags
  (`--cohort-definition-report`, `--shap-interpretability-report`)
  that run_dag_pipeline was passing per gate_registry but argparse
  didn't know.
- **`feature_engineering_audit_gate`**: selection-frequency lookup now
  falls back to longest-prefix match for one-hot encoded features
  (`race_ethnicity_nh_black` inherits its group's score from the
  pre-encoding `race_ethnicity` entry). Resolves the 8
  "feature_stability_evidence_missing" failures that were an
  interface mismatch between training and gate.
- **`shap_interpretability_gate`**: fixed stale `sys.path` pointing to
  `scripts/tools/` (refactored into `scripts/training/` in commit
  530969a); now resolves `apply_categorical_encoding_to_external`.
  Also handles `feature_lineage_spec.features` as either dict or list
  (dogfood run crashed on `'str'.get()`).
- **`missingness_policy_gate`**: accepts v2.0 policy schema
  (`tiered_mechanism_first` meta-strategy; `mechanism_assessment.methods`
  plural list alongside `method` singular string; `conclusion=None`
  for unperformed-assessment treated as warning not failure).

### Documentation consistency

- **Single source of truth for the 12-dimension scoring table**.
  SKILL.md is canonical; README.md / README_EN.md / reviewer.yaml
  were drifting (8 name mismatches: "防泄漏" vs "泄漏防护", "Leakage
  Prevention" vs "Leakage Protection", etc.). All drift resolved.
  Added `scripts/diagnostics/check_docs_consistency.py` as a CI-ready
  drift guard (exit 2 on mismatch).
- **SKILL.md updates**:
  - 3 canonical entry points (`/mlgg`, `mlgg <sub>`, `mlgg-lint`)
    promoted above the Quick Dispatch utility list
  - Decision helper "workflow vs audit vs lint" — clarifies that
    `mlgg audit` (not `mlgg workflow`) is the right entry for
    projects without MLGG-produced evidence/*.json
  - Honest capability boundary table (strong / medium / weak /
    out-of-scope) distinguishing training-pipeline governance
    (strong) from cohort selection bias (covered only superficially)
    from deployment drift (out of scope)
  - Peer-review KB section rewritten to disclose actual coverage
    (evaluation/reporting strong; leakage underrepresented due to
    publication-filter selection bias)
  - Removed references to "27 AST rules" documentation drift
    (corrected count)
- **`performance-policy.example.json`**: added `mcc` to
  `required_metrics` (clinical_metrics_gate's mandatory panel
  includes MCC; prior template was missing it).
- **`extractor.yaml` `Required Fields` JSON schema** rewritten to
  match the newer `leakage_risk_assessment` + paired `_evidence`
  fields that `score_paper_metadata.py` actually consumes.

### Pre-existing CLI fix

- **`scripts/codebooks/fetch_nhanes_2021_2023.py`** had no argparse
  so `--help` triggered network I/O and timed out in
  `tests/test_stress_gate_cli.py`. Added minimal `--help` guard.

### Tests — session total

- 29 new tests added across 6 files:
  - `test_scoring_consistency.py` (12-dim drift guard)
  - `test_disease_kb_provenance.py` (provenance schema + 3 consumer
    regression tests — Registry/NHANES/UKB)
  - `test_evidence_backing_audit.py` (positive-claim evidence check)
  - `test_kb_provenance_helper.py` (shared helper unit tests)
  - `test_peer_review_retrieval_precision.py` (issue-code keyword
    extraction + ranking)
  - `test_cohort_definition_pattern_scope.py` (disease-scope
    regression for glucose false positive)
- 4740+ pre-existing tests pass unchanged.

### Observed but not fixed (by design)

- Calibration ECE threshold (≤0.06), slope bounds ([0.8, 2.0]),
  external validation `min_cohort_count ≥ 1` and
  `require_cross_period` / `require_cross_institution` are hardcoded
  publication-grade baselines. They do not participate in the
  `profile_overrides` system. For exploratory leakage-audited runs
  on datasets where these bars are unreachable (SUPPORT2 ICU: ECE
  naturally > 0.06), the gate correctly emits hard failures. Making
  these tier-aware would require extending
  `references/standards/publication-policy-baselines.json` structure
  and removing a `value < 1.0` hardcoded check — deferred as a
  separate architectural refactor.

## [1.0.0] - 2026-04-09

### Changed

- **Project Rename**: ML Leakage Guard → **ML Governance Guard** (MLGG abbreviation unchanged)
  - 73 files updated; all code identifiers (`mlgg`) preserved
  - GitHub repo renamed to `medical-ml-governance-guard`
  - pyproject.toml description updated to "33 fail-closed governance gates"

### Fixed

- **Security**: Removed `joblib.load()` fallback in `SecureModelLoader` that bypassed `RestrictedUnpickler` (arbitrary code execution risk)
- **Security**: 3 non-atomic JSON writes in `_security.py` replaced with `_atomic_json_write()` (fsync + rename)
- **Data Integrity**: Global NaN/Infinity safety net via `_sanitize_for_json()` + `allow_nan=False` in `write_json()` — eliminates RFC 8259 violations across all gate reports
- **Data Integrity**: 10+ individual NaN/Infinity bugs fixed in gates (ci_matrix, calibration_dca, permutation_significance, sample_size, imbalance_policy)
- **Compatibility**: sklearn 1.8+ `penalty=None` deprecation — 3-level version detection using `C=np.inf` for >=1.8
- **Subprocess Safety**: Added `timeout=` to 12 subprocess calls across attestation gates, onboarding, and orchestration (30s for openssl, 3600s for pipeline steps)
- **Path Traversal**: `manifest_lock.py` and `cohort_definition_gate.py` now use `resolve_path()` for forbidden prefix checks
- **Error Handling**: `cohort_definition_gate.py` no longer silently swallows JSON parse errors — emits warning
- **Error Handling**: 8+ bare `except: pass` replaced with stderr logging in security_audit, shap_interpretability, distribution_generalization gates
- **Metric Naming**: Standardized "auroc"→"roc_auc", "auprc"→"pr_auc" in `imputation_sensitivity()` and `init_guide.py`
- **Gate Count**: Updated stale "31 gates" → "33 gates" across 13 reference/doc files + `generate_compliance_certificate.py` hardcoded bug
- **Reference KB**: `mlgg-standard-specification.json` — added missing `cohort_definition_gate` and `shap_interpretability_gate` to DAG layers; fixed `ci_matrix_gate` and `metric_consistency_gate` layer assignment (6→5)
- **Reference KB**: `gate-applicability-matrix.json` — fixed 2 gate layer mismatches to match `_gate_registry.py`
- **Tests**: Fixed `SCRIPTS_DIR` bug in `test_gate_smoke.py` and `test_split_smoke.py` (pointed to `tests/` instead of `scripts/`)
- **Tests**: Fixed stale gate count assertions in `test_evidence_digest.py` and `test_registry_cache.py`
- **Tests**: Fixed stale metric key set in `test_stress_numeric.py` (added `lr_positive`, `lr_negative`, `mcc`)
- **Tests**: Fixed stale error message regex in `test_split_data.py`
- **Packaging**: Added `dev` optional-dependencies group (pytest, pytest-cov, pytest-timeout)
- **Packaging**: Fixed `ruff.toml` target-version `py312` → `py310` to match `requires-python`
- **Packaging**: Fixed `.gitignore` missing `*.log` and `.env.local` patterns
- **Examples**: Fixed `download_nhanes.py` FILES_2020 URLs pointing to wrong year directory (/2017/ → /2019/)
- **README**: Fixed broken anchor `#19-项分析工具` → `#21-项分析工具`; updated description wording

### Enhanced

- **SKILL.md**: Added "Clinical Semantic Review Checklist" — feature timeline audit, fairness quality standards, interpretability standards (cross-model SHAP consistency), model comparison standards, calibration reporting standards (Van Calster 2019 trio)
- **SKILL.md**: Fixed hidden workflow to list all 33 gates; output contract to list all 34 report files; added 10 missing tool/orchestration script descriptions; added 4 dispatch scenarios
- **mlgg.md**: Added clinical semantic review step to Research mode Phase rhythm
- **phase-8.md**: Added explicit bootstrap CI requirement for subgroup fairness metrics
- **Demo diabetes130**: Added bootstrap 95% CI for fairness subgroup metrics (MLGG-Q02); SHAP cross-model Spearman rank correlation; TRIPOD calibration slope/intercept reference; multiple comparison caveat; data integrity SHA-256 manifest

### Added (Tests)

- `test_generate_demo_medical_dataset.py` — 9 tests (output files, schema, patient disjoint, determinism)
- `test_init_guide.py` — 18 tests (.mlgg/ directory, rules JSON, CLAUDE.md, --force, metric naming)
- `test_peer_review_lookup_cli.py` — 15 tests (--stats, --dimension, --search, output format)
- `test_fetch_papers.py` — 28 tests (deduplicate, slug, journal/disease classification, dry-run)
- `test_mlgg_web.py` — 27 tests (path traversal, CSRF, rate limiter, Flask app, security headers)
- `test_extract_paper_metadata.py` — 16 tests (Pydantic schemas, CLI, path resolution)

### Added

- **mlgg-lint Static Analysis Plugin** (`plugin/`)
  - 10 AST-based rules (R001–R010) detecting data leakage, improper preprocessing, and evaluation malpractice
  - CLI: `python3 scripts/orchestration/mlgg.py lint check <file.py>` with text/JSON/SARIF output
  - VS Code extension skeleton (SARIF-based diagnostics on save/open)
  - `# noqa: R001` inline suppression and `.mlgg-lint.toml` config auto-discovery
  - Pre-commit hook support (`.pre-commit-hooks.yaml`)
  - Detection: keyword args, chained calls, DataFrame origin tracking, Pipeline exclusion, word-boundary variable classification
  - Security: 16 MB file limit, relative path output, ANSI strip, symlink skip
  - 57 tests, 6 rounds of strict review (41 bugs/issues found and fixed)

- **4 New Model Families** (all sklearn built-in, no extra dependencies)
  - K-Nearest Neighbors (KNN) — 20 hyperparameter configs
  - Gaussian Naive Bayes — 5 configs
  - Decision Tree — 45 configs
  - MLP Neural Network — 24 configs, early stopping
  - Updated balanced preset (10 families) and comprehensive preset (16 families)
  - Total model pool: 20 families (was 16)

- **8 Real Medical Datasets** (auto-download in play mode)
  - Heart Disease (UCI, 297 rows), Breast Cancer (UCI, 569), Pima Diabetes (768)
  - Mammographic Mass (UCI, 961), Framingham Heart Study (4,240)
  - Thyroid Disease (UCI, 7,200), EEG Eye State (UCI, 14,980)
  - Diabetes 130 US Hospitals (UCI, 10,000 subsample of 101K)

- **Feature Count Safety Warnings** in play mode feature selection
  - Extreme warning (features >= rows): blocks selection
  - High warning (EPV < 5): shows overfitting risk estimate

- **Quick Results Viewer** (`quick_summary.py`)
  - One-command view of training results: `python3 scripts/reporting/quick_summary.py /path/to/output`
  - Shows key metrics with 95% CI, overfitting risk assessment, model selection top-10
  - Supports `--json` output and `--eval` direct file path
  - 21 unit tests (93% coverage)

- **9 Play Mode UX Improvements**
  - Training time estimate in confirm step (based on rows × candidates)
  - Dataset preview box for custom CSV (rows, columns, positive rate, detected columns)
  - Class distribution hint in imbalance strategy step (positive/negative ratio)
  - EPV (events per variable) hint in model selection (red/yellow/gray risk coding)
  - Elapsed time in training progress bar (real-time "45s", "2m30s")
  - Actionable next-steps when training fails (3 bilingual suggestions)
  - Data quality warning for columns with >30% missing values
  - 13 friendly error patterns (candidate_pool_too_small, MemoryError, ConvergenceWarning, ValueError, timeout + 8 existing)

- **2 Performance Optimizations**
  - Adaptive bootstrap resampling: >5000 rows uses 200/500 (was 500/2000), ~60% faster
  - Auto n_jobs: >2000 rows auto-sets min(cpu_count, 4) parallel workers

- **Remediation Plan Generator** (`remediation_plan.py`)
  - Scans all gate reports in an evidence directory, collects failures and warnings
  - Groups by root cause category (data, leakage, protocol, model, robustness, attestation, publication)
  - Orders actions by pipeline dependency and severity (CRITICAL → INFO)
  - Deduplicates repeated codes, shows occurrence counts
  - Supports `--json`, `--markdown`, and plain text output with `--output` file option
  - 25 comprehensive unit tests

- **Evidence Comparator** (`evidence_comparator.py`)
  - Compares two evidence directories (baseline vs current) side-by-side
  - Shows improved, regressed, unchanged, new, and removed gates
  - Highlights new and resolved failure codes, failure/warning count deltas
  - Supports JSON and human-readable text output with `--output` option
  - 30 comprehensive unit tests (96% coverage)

- **Gate Coverage Matrix** (`gate_coverage_matrix.py`)
  - Scans evidence directory against the full gate registry to produce a coverage matrix
  - Shows which gates have been executed, their status, and identifies missing gates
  - Per-layer breakdown with pass/fail counts and coverage percentage
  - Supports JSON and human-readable text output with `--output` option
  - 23 comprehensive unit tests (97% coverage)

- **Gate Timeline Analyzer** (`gate_timeline.py`)
  - Reads gate reports from an evidence directory, extracts execution timestamps and durations
  - Identifies bottleneck gates (slowest by duration)
  - Computes wall-clock span, total/average/min/max durations, status counts
  - Supports JSON and human-readable text output with `--output` and `--top N` options
  - 47 comprehensive unit tests (99% coverage)

- **Policy Generator** (`policy_generator.py`)
  - Scans evidence reports and generates a recommended `performance_policy.json`
  - Extracts observed metrics from evaluation, robustness, calibration, seed, and external reports
  - Derives thresholds with configurable margin (default 15% headroom)
  - Built-in presets: `lenient`, `standard`, `strict`
  - Supports JSON and human-readable text output with `--output` file option
  - 41 comprehensive unit tests (99% coverage)

- **Threshold Sensitivity Analyzer** (`threshold_sensitivity.py`)
  - Scans gate reports and analyzes how close each metric sits to its pass/fail threshold
  - Identifies fragile gates (within configurable margin %)
  - Simulates stricter (0.8x) and relaxed (1.2x) policy scenarios
  - Shows new failures and resolved failures under each simulation
  - Supports `--json`, `--markdown`, and plain text output with `--output` file option
  - 47 comprehensive unit tests (94% coverage)

- **Evidence Health Check Tool** (`report_health_check.py`)
  - Scans all 33 gate reports in an evidence directory
  - Produces completeness percentage, pass rate, per-gate status table
  - Top failure codes across all gates with counts
  - Actionable recommendations (missing gates, failing gates, publication-ready)
  - Supports `--json` for machine-readable output and `--output` for file output
  - 21 comprehensive unit tests

- **Evidence Digest Tool** (`evidence_digest.py`)
  - Generates a compact, shareable one-page summary from an evidence directory
  - Extracts pipeline status, key metrics, model info, split statistics, gate counts
  - Markdown output for paper submissions; JSON for programmatic use
  - 31 comprehensive unit tests

### Changed

- **Code Quality Cleanup**
  - Removed 33 unused imports (F401) and 9 unused variables (F841) across 39 files
  - Fixed F811 duplicate class names in test files
  - All `ruff check` passes with zero errors

- **Tightened ruff.toml Configuration**
  - Removed F401, F841, F541, F821 from global ignore list
  - Fixed 11 f-strings without placeholders (F541)
  - Added missing `typing` imports in `mlgg.py` and `test_play_smoke.py` (F821)
  - Per-line `# noqa: F821` for intentional lazy numpy/pandas type annotations in `_gate_utils.py`

- **Housekeeping**
  - Added `build/` and `dist/` to `.gitignore`, removed tracked build artifacts

### Tests

- **448 new tests across 30 files**
  - `test_report_health_check.py`: 21 tests (new tool)
  - `test_explain_gate.py`: 8 tests for `main()` CLI paths
  - `test_compare_runs.py`: 6 tests for `main()` CLI paths
  - `test_env_doctor.py`: 5 direct `main()` tests (replacing subprocess-only coverage)
  - `test_reporting_bias_gate.py`: 8 direct `main()` tests
  - `test_split_protocol_gate.py`: 7 direct `main()` tests
  - `test_gate_framework.py`: extended coverage for `wrap_legacy_report`, `load_gate_report`, `format_issue_line`
  - `test_gate_utils.py`: `install_gate_timeout` zero/negative/positive tests
  - `test_visualize_results.py`: trace-not-found warning, calibration ValueError tests
  - `test_leakage_gate.py`: 8 direct `main()` tests (pass, row/id/temporal overlap, suspicious features, strict, io error)
  - `test_publication_gate.py`: 7 direct `main()` tests (pass, component fail, manifest, attestation, metric, strict)
  - `test_self_critique_gate.py`: 6 direct `main()` tests (pass, component fail, manifest, strict, low score)
  - `test_remediation_plan.py`: 25 tests (new tool)
  - `test_robustness_gate.py`: 13 direct `main()` tests (pass, missing file, invalid JSON, metric mismatch, buckets, drops, ranges, summary, strict, policy)
  - `test_prediction_replay_gate.py`: 12 direct `main()` tests (pass, missing files, invalid JSON, columns, binary, scores, replay mismatch, strict)
  - `test_external_validation_gate.py`: 14 direct `main()` tests (pass, missing files, invalid JSON, cohorts, metrics, transport drop, strict, binary, scores)
  - `test_threshold_sensitivity.py`: 47 tests (new tool — helpers, extraction, classification, simulation, formatting, CLI)
  - `test_schema_preflight.py`: 19 direct `main()` tests (pass, missing target, non-binary, null pids, single class, auto-mapping, strict, mapping-out, split and single-file modes)
  - `test_export_latex.py`: 8 direct `main()` tests (eval-only, custom decimals, missing eval, model selection, external, CI matrix, all reports)
  - `test_policy_generator.py`: 41 tests (new tool — helpers, extractors, derivation, presets, formatting, CLI)
  - `test_manifest_lock.py`: 13 direct `main()` tests (pass, multi-file, CSV, missing input, dir, meta, invalid meta, baseline match/mismatch/missing/not-dict/corrupt)
  - `test_generalization_gap_gate.py`: 13 direct `main()` tests (pass, overfit, brier, warning, strict, missing splits, invalid eval/policy, missing metric, invalid threshold)
  - `test_permutation_significance_gate.py`: 14 direct `main()` tests (pass, not significant, missing/empty/invalid null, low perm, delta, lower-is-better, strict, invalid actual/alpha/delta/min-perm)
  - `test_gate_timeline.py`: 47 tests (new tool — helpers, extraction, scanning, sorting, summary, bottlenecks, formatting, CLI)
  - `test_render_user_summary.py`: 11 direct `main()` tests (pass, fail, request, default output, empty evidence, remediation hints, summary field, next actions)
  - `test_metric_consistency_gate.py`: 10 direct `main()` tests (pass, mismatch, missing, not found, no expected, strict, split mismatch, path mismatch, corrupt JSON)
  - `test_seed_stability_gate.py`: 11 direct `main()` tests (pass, missing, wrong primary, selection data, insufficient seeds, duplicate, threshold, summary mismatch, corrupt JSON, strict)
  - `test_calibration_dca_gate.py`: 6 direct `main()` tests (pass, missing trace, missing columns, non-binary, insufficient rows, corrupt eval JSON)
  - `test_gate_coverage_matrix.py`: 23 tests (new tool — helpers, registry, scanning, summary, formatting, CLI)
  - `test_evidence_comparator.py`: 30 tests (new tool — helpers, scanning, comparison, summary, formatting, CLI)
  - `test_evaluation_quality_gate.py`: 9 direct `main()` tests (pass, missing, corrupt, not found, mismatch, CI width, missing baseline, non-finite, strict)
  - `test_covariate_shift_gate.py`: 7 direct `main()` tests (pass, missing train, empty split, high shift, invalid threshold, strict, with valid)
  - `test_tuning_leakage_gate.py`: 10 direct `main()` tests (pass, missing/corrupt spec, test usage, unsupported search, invalid scope, seed not controlled, no valid split, cv group mismatch, strict)
  - `test_init_project.py`: 6 direct `main()` tests (basic init, custom fields, preserve, auto run_id, dirs, all templates)
  - `test_publication_gate.py`: 5 direct `main()` tests (attestation missing summary/policy/witness/role, manifest missing files)
  - `test_evaluation_quality_gate.py`: +8 more tests (CI matrix enrichment/missing/failed, insufficient resamples, baseline delta, CI bounds invalid, metric outside CI, loss metric)

- **Documentation**
  - System architecture document with Mermaid flowchart (`references/Architecture.md`) (#71)
  - Contributing guide (`CONTRIBUTING.md`) (#72)
  - CLI API Reference for all scripts (`references/API-Reference.md`) (#67)
  - Complete Google-style docstrings for `train_select_evaluate.py` (69 functions) (#68)
  - Complete Google-style docstrings for `split_data.py` (17 functions) (#69)
  - Expanded Troubleshooting with 12 new failure codes (#66)
  - Bilingual README with detailed usage guide (sections 0–11)
  - Beginner quickstart guide (`references/Beginner-Quickstart.md`)
  - PolyForm Noncommercial 1.0.0 license

- **Pixel CLI (`mlgg play`)**
  - Pixel-art interactive CLI launcher with arrow-key navigation (#56–#65)
  - Phased progress bar with percentage display (#56)
  - Export CLI Command option (#57)
  - Training results display after run (#58)
  - Page Up/Down support for select and multi_select (#59)
  - `--lang {en,zh}` bilingual support (#60)
  - Advanced settings for ignore-cols, n-jobs, max-trials (#62)
  - Friendly error messages (#63)
  - Run history recording and "Repeat last run" (#64)
  - `--dry-run` mode (#65)

- **Test Suites (1,100+ test cases)**
  - `request_contract_gate` (107 cases), `split_protocol_gate` (75),
    `covariate_shift_gate` (80), `reporting_bias_gate` (34),
    `model_selection_audit_gate` (69), `clinical_metrics_gate` (54),
    `prediction_replay_gate` (24), `distribution_generalization_gate` (24),
    `generalization_gap_gate` (18), `robustness_gate` (30),
    `seed_stability_gate` (27), `external_validation_gate` (20),
    `ci_matrix_gate` (25), `metric_consistency_gate` (45),
    `self_critique_gate` (19), `execution_attestation_gate` (41),
    `generate_execution_attestation` (27), `render_user_summary` (24),
    `env_doctor` (13), `train_select_evaluate` (67),
    `mlgg.py` routing (25), `mlgg_onboarding` (29),
    `run_strict_pipeline` (11), `run_productized_workflow` (11),
    `init_project` (12), `generate_demo_medical_dataset` (16),
    `mlgg_interactive` (33), wizard + download (16)

- **Single-CSV Auto-Split Workflow**
  - `split_data.py` with 3 strategies: grouped_temporal, grouped_random,
    stratified_grouped
  - Patient-level disjoint splits, temporal ordering, prevalence checks
  - NaN patient_id/target exclusion, row count preservation, SHA-256
    input fingerprint, atomic file writes

- **Real Data Download**
  - `examples/download_real_data.py` for UCI heart disease and breast
    cancer datasets with streaming progress display (#61)

- **Model Pool Expansion**
  - LightGBM, SVM (linear/RBF), TabPFN backends
  - Ensemble methods: soft voting, hard voting, stacking
  - Optuna hyperparameter optimization
  - Device selection (CPU/GPU/MPS)

- **Release Benchmark Suite**
  - `benchmark-suite --profile release` with multi-dataset stability matrix
  - Repeat consistency gate, JUnit output, suite timeout budget
  - Frozen benchmark registry (`benchmark_registry.v1`)
  - Observational diagnostics for non-blocking failures

- **Gate Pipeline (33 gates)**
  - Request contract validation with publication-policy anti-downgrade
  - Manifest fingerprint locking with baseline comparison
  - Signed execution attestation with witness quorum, timestamp trust,
    transparency log, execution receipt, and execution log
  - Split/temporal/ID leakage detection
  - Split protocol enforcement
  - Covariate shift and split separability risk gate
  - TRIPOD+AI / PROBAST+AI / STARD-AI reporting checklist gate
  - Disease-definition variable leakage guard
  - Feature lineage leakage gate
  - Class-imbalance policy gate (train-only resampling)
  - Missingness policy gate with MICE scale guard
  - Tuning leakage isolation gate
  - Model selection audit with one-SE replay
  - Feature engineering audit with stability evidence
  - Clinical metrics completeness gate
  - Prediction replay gate for metric reproducibility
  - Distribution generalization and transport readiness gate
  - Generalization gap overfitting detection
  - Subgroup robustness gate
  - Multi-seed stability gate
  - External validation gate (cross-period, cross-institution)
  - Calibration and decision curve analysis gate
  - Bootstrap CI matrix gate
  - Metric consistency gate
  - Evaluation quality gate with baseline improvement check
  - Permutation falsification significance gate
  - Aggregate publication gate
  - Self-critique scoring gate

- **Orchestration**
  - `run_strict_pipeline.py`: sequential 33-gate orchestrator
  - `run_productized_workflow.py`: doctor → preflight → pipeline → summary
  - `mlgg_onboarding.py`: guided 8-step novice flow with preview mode
  - `mlgg.py`: unified CLI entry point
  - `mlgg_interactive.py`: terminal wizard with profiles and command preview

- **Authority E2E**
  - CKD benchmark (stable publication-grade stress path)
  - Heart disease stress search (advanced research mode)
  - Diabetes130 large-cohort integration
  - Adversarial fail-closed validation harness
  - `authority-release` and `authority-research-heart` preset wrappers
  - Machine-readable error payloads (`--error-json`)

- **Infrastructure**
  - `pyproject.toml` with pip install support and `mlgg` console entry point
  - `_gate_utils.py` shared utilities for all gate scripts
  - `schema_preflight.py` for train/valid/test schema validation
  - `env_doctor.py` for dependency diagnostics
  - CI workflows: smoke (push/PR), full (nightly), extended (weekly)

### Fixed

- Docstring accuracy: `impute_numeric_frame` Returns, `build_imputer`
  Args, `prepare_xy` Raises, `apply_probability_calibrator` Raises
- `generalization_gap_gate.py` / `robustness_gate.py` / `seed_stability_gate.py`:
  `finish()` ignored `--strict` for warning escalation
- `feature_engineering_audit_gate.py`: wrong error code for report parse
  failure; `to_float` missing `math.isfinite` guard
- `request_contract_gate.py`: wrong error code in
  `validate_feature_engineering_report_shape`
- `train_select_evaluate.py`: misleading hard-coded CI bounds in
  `transport_drop_ci` replaced with `null`
- `distribution_generalization_gate.py`: missing `sys` import
- `feature_engineering_audit_gate.py`: missing `Set` import and constants
- Metric-name spoofing and validation-metric spoofing blocked
- Lineage normalization hardened
- Profile key leak in interactive wizard
- Onboarding hardcoded demo columns break `--input-csv` mode
- `validate_binary_target` bug in split_data.py
- Collision-safe intermediate column names in temporal split
- CKD ARFF parser, categorical encoding, lambda closure fixes
- Download error handling and temp file cleanup

### Changed

- Shared gate utilities (`add_issue`, `load_json`, `write_json`, `to_float`)
  extracted to `_gate_utils.py` and imported by all 27 gate scripts
- All `to_float` implementations reject `inf`/`nan` with `math.isfinite`
- All gate `finish()` functions use uniform strict-mode warning escalation
- README Chinese sections aligned with English (commands, bullets, terms)
- Atomic file writes for all CSV and JSON outputs
- Exit style unified across all scripts
