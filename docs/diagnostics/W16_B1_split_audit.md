# W16-B1 — MLGG-S01 Split Enforcement Audit

**Wave:** 16 (Security & Unchallengeable Rules)
**Rule:** S01 — 同一患者不跨 split (patient never crosses train/test split)
**Mode:** Read-only audit
**Date:** 2026-05-17

---

## 1. Inventory: split sites + classifier

### A. Patient-grouped split producers (group-aware)

| File:line | Function | Classifier |
|-----------|----------|-----------|
| `scripts/training/split_data.py:373` | `split_grouped_temporal` | GROUP-AWARE (patient_id_col required) |
| `scripts/training/split_data.py:491` | `split_grouped_random` | GROUP-AWARE |
| `scripts/training/split_data.py:546` | `split_stratified_grouped` | GROUP-AWARE |

Dispatch at `split_data.py:941-958` rejects unknown strategy. CLI `--patient-id-col` is required.

### B. Post-split overlap validators (independent backstops)

| File:line | Check | Severity |
|-----------|-------|----------|
| `scripts/gates/split_protocol_gate.py:430-441` | `entity_overlap` across train/valid/test pairs | exit 2 (fail-closed) |
| `scripts/gates/split_protocol_gate.py:328-334` | `allow_patient_overlap=true` in spec → fail | exit 2 |
| `scripts/gates/leakage_gate.py:498-545` | `id_overlap` + `row_overlap` across all pairs | exit 2 |

Both wired into `run_dag_pipeline.py:911` and `mlgg_onboarding.py:1638` ("S01 patient isolation" gate label).

### C. `train_test_split` call sites (sklearn, no group support)

| File:line | Context | Classifier |
|-----------|---------|-----------|
| `scripts/core/_gate_utils.py:2535` | `compare_imputation_methods` — splits a pre-built X/y array for an imputation-method diagnostic | N/A (not a cohort splitter) |
| `scripts/gates/distribution_generalization_gate.py:296,328` | `build_split_classifier_auc`/`build_missingness_classifier_auc` — synthesizes a "is_train vs is_other" task on rows from already-disjoint splits | N/A (operates on already group-disjoint inputs by precondition) |
| `scripts/diagnostics/init_guide.py:651,672` | Inside a docstring literal labelled `# ❌ MLGG-S01` | N/A (pedagogical bad-example) |

### D. Test coverage that catches "same patient in both folds"

| File:line | What it asserts |
|-----------|-----------------|
| `tests/test_split_e2e.py:60,96,123` | `set(train).isdisjoint(set(valid/test))` for all 3 strategies, end-to-end |
| `tests/test_leakage_gate.py:290-303` | `test_entity_id_overlap` — injects P002 into both splits, expects `id_overlap` code |
| `tests/test_split_protocol_gate.py` | entity_overlap unit tests on the gate |
| `experiments/paper/redteam/r1/test_04_no_patient_grouping.py` | R004 canary — the exact "sklearn `train_test_split` without `groups=`" anti-pattern, used to verify the lint/audit can name it |

---

## 2. Verdict: **PASS** (one YELLOW caveat)

No path in `scripts/` produces a patient-grouped cohort split via a non-group-aware splitter. Three group-aware producers in `split_data.py` are the only cohort splitters reachable from the orchestrator; two independent post-hoc validators (`split_protocol_gate`, `leakage_gate`) fail-close on any drift; the DAG wires both in whenever a test split exists.

The two in-gate `train_test_split` calls are internal diagnostic subroutines on already-disjoint inputs — they do not partition the cohort.

Sampled fixtures (4 of authority-e2e/) — zero patient-id overlap between train/valid/test:

| Dataset | train/valid/test ids | t∩v | t∩te | v∩te |
|---------|----------------------|-----|------|------|
| uci-chronic-kidney-disease | 167/56/56 | 0 | 0 | 0 |
| uci-diabetes-130-readmission | 4800/1600/1600 | 0 | 0 | 0 |
| uci-heart-disease | 192/105/105 | 0 | 0 | 0 |
| uci-breast-cancer-wdbc | 273/91/91 | 0 | 0 | 0 |

---

## 3. Top 5 risk sites

1. **`scripts/gates/distribution_generalization_gate.py:296`** — `train_test_split` inside `build_split_classifier_auc`; on multi-visit cohorts (rows-per-patient > 1) the diagnostic AUC is mildly optimistic because both folds of the synthetic task may include rows from the same patient. Diagnostic-only, not S01 enforcement.
2. **`scripts/gates/distribution_generalization_gate.py:328`** — same pattern in `build_missingness_classifier_auc`. Same risk class.
3. **`experiments/authority-e2e/uci-diabetes-130-readmission/`** — `train_rows == train_ids` (4800 == 4800) implies one row per `patient_id`, but the source dataset is encounter-level (multiple encounters per patient). Either pre-deduplicated upstream or `patient_id` is actually `encounter_id`. **Identifier semantics question, not a splitter bug** — but if `encounter_id` is being passed as `patient_id`, the post-hoc disjoint check passes vacuously while real patient-level leakage could exist.
4. **`scripts/training/split_data.py:929`** — `n_patients = df[patient_id_col].nunique()` — accepts whatever column the caller names "patient_id" with no semantic check (e.g., no warning if `nunique == nrows` on a longitudinal dataset).
5. **`scripts/core/_gate_utils.py:2535`** — `compare_imputation_methods` splits feature arrays with no group. Internal diagnostic; not user-facing cohort split. Risk only if a downstream caller hands it patient-grouped rows expecting honest CV.

---

## 4. Wave-N+ fix candidates

- **W17 (diagnostic correctness):** Replace `train_test_split` in `distribution_generalization_gate.py` with `GroupShuffleSplit` when an `id_col` is available; document the "diagnostic operates on pre-disjoint splits" precondition explicitly.
- **W17 (cohort-identity sanity check):** In `split_data.py`, warn (not fail) when `df[patient_id_col].nunique() == len(df)` on a dataset whose `time_col` is provided — likely encounter-level masquerading as patient-level. Cross-link to a new `cohort_definition_gate` check.
- **W17 (fixture audit):** Re-derive `patient_id` for `uci-diabetes-130-readmission` from the source `encounter_id`/`patient_nbr` column to validate the disjoint property is real, not vacuous.
- **W17 (lint):** Extend `scripts/core/_audit_shared.py:52` `no_train_test_split` regex to also flag `train_test_split(...)` without `groups=` on files importing `patient_id`. Currently it only checks for missing `stratify=`.

---

## 5. Audit hard-rule compliance

- READ-ONLY: confirmed, no edits to `scripts/`, `references/`, `.github/`.
- No sub-agents; no package install.
- Outputs: `/tmp/W16_B1_split_sites.txt`, `/tmp/W16_B1_verdict.txt`, this committed file.
