# KB Tag-Completeness Audit (Agent C) — DRAFT (not applied)

**Target file**: `references/methodology/literature-knowledge-base.json` (67 entries)
**Patch**: `/tmp/audit_agent_C_kb_tags.patch` — 27 hunks, 26 entries retagged. Dry-run verified with `git apply --check`.
**Status**: NOT applied per CLAUDE.md NEVER #1 (no agent writes to `references/*.json`).

## Audit input recap

- 4 entries with empty `gates_implementing`: LIT-004, LIT-018, LIT-019, LIT-042
- 14 gates with single-entry support
- 2 gates with zero lit support: `cohort_definition_gate`, `shap_interpretability_gate`

## Section 1 — The 4 untagged entries

| LIT-id | Title (short) | Existing gates | Proposed gates | Evidence (one-sentence) | Confidence |
|---|---|---|---|---|---|
| LIT-004 | TRIPOD-LLM | `[]` | **Keep `[]`** (already carries `applicability_note: "LLM-specific reporting standard"`) | LLM modality is out of MLGG scope per project CLAUDE.md ("不覆盖 ... 文本"); paper does not constrain binary tabular-EHR gates. | **High** (out of scope) |
| LIT-018 | CONSORT-AI | `[]` | `reporting_bias_gate`, `publication_gate` | EQUATOR-endorsed reporting checklist — even if RCT-of-AI is not a retrospective-cohort target, the checklist informs publication-grade reporting of any deployed model that downstream undergoes an RCT. | **Medium** |
| LIT-019 | SPIRIT-AI | `[]` | `reporting_bias_gate`, `publication_gate` | Same logic as CONSORT-AI; protocol pre-specification supports `publication_gate`'s requirement that analytic plans be declared. | **Medium** |
| LIT-042 | ML in Diabetes Research (multiclass) | `[]` | **Keep `[]`** (already carries `applies_to_prediction_types: ["multiclass"]` and a `note` field deferring to "planned multiclass gate pack MLGG v1.1") | Paper's substantive content is multiclass/ordinal; MLGG currently only ships binary-classification gates. Tagging it against today's binary gates would be misleading. | **High** (deferred-by-design) |

For LIT-018 / LIT-019, the patch also softens the `applicability_note` from "Not applicable to binary classification pipeline gates" to "Publication-relevant for RCT-of-AI; not consumed by binary retrospective-cohort pipeline gates" — this preserves the scope warning while removing the contradiction with the now-non-empty `gates_implementing`.

## Section 2 — Fragile gates → cross-tagged

For each of the 14 originally single-supporter gates, the patch broadens support. Resulting counts shown.

| Gate | Before | After | New supporters added | Confidence note |
|---|---|---|---|---|
| `ci_matrix_gate` | 1 (LIT-033) | **3** | LIT-036 (Ojala — null-distribution bootstrapping is a CI methodology) | High |
| `execution_attestation_gate` | 1 (LIT-023 SLSA) | **1 (unchanged)** | None — SLSA v1.0 is the canonical methodology; no peer literature supersedes a specification. | High — by design |
| `feature_engineering_audit_gate` | 1 (LIT-009) | **4** | LIT-010, LIT-025 (Deepchecks auto-leakage scans), LIT-053 (ICD temporal audit) | High |
| `feature_lineage_gate` | 1 (LIT-010) | **4** | LIT-053, LIT-054 (peer-review temporal lineage scrutiny), LIT-059 (DataSAIL declares split algorithm = lineage) | High |
| `generalization_gap_gate` | 1 (LIT-032) | **3** | LIT-009 (small samples + leakage inflate train-test gap), LIT-031 (PROGRESS-3 transport/perf-gap) | High |
| `imbalance_policy_gate` | 1 (LIT-035) | **2** | LIT-029 (Lancet DH multi-metric / prevalence-aware framework) | Medium — LIT-029 is calibration-focused, but explicitly discusses prevalence handling |
| `manifest_lock` | 1 (LIT-023 SLSA) | **1 (unchanged)** | None — SLSA L0-L4 attestation envelope is the singular standard. | High — by design |
| `metric_consistency_gate` | 1 (LIT-035) | **3** | LIT-033 (multi-metric ranking is consistency-test methodology), LIT-045 (calibration-in-the-large ideals are consistency rules) | High |
| `permutation_significance_gate` | 1 (LIT-036) | **2** | LIT-033 ("statistical significance testing required before claiming superiority") | High |
| `prediction_replay_gate` | 1 (LIT-023) | **2** | LIT-032 (continuous monitoring requires replayable predictions) | Medium |
| `publication_gate` | 1 (LIT-012) | **11** | LIT-011 (Kapoor model info sheets), LIT-018, LIT-019, LIT-026 (FDA GMLP), LIT-037 (Ioannidis pre-spec), LIT-040 (Nature Med standards), LIT-044 (multiplicity), LIT-054, LIT-062, LIT-063 | High |
| `seed_stability_gate` | 1 (LIT-033) | **2** | LIT-036 (permutation-test seed methodology) | Medium |
| `self_critique_gate` | 1 (LIT-037) | **4** | LIT-011 (reproducibility-crisis self-assessment), LIT-012 (meta-analytic biased-study exclusion), LIT-044 (pre-spec primary outcome) | High |
| `tuning_leakage_gate` | 1 (LIT-011) | **3** | LIT-009 (feature-selection-on-full-data leakage), LIT-048 ("Do NOT use stepwise / univariable selection") | High |

## Section 3 — Zero-support gates: `cohort_definition_gate`, `shap_interpretability_gate`

### `cohort_definition_gate` → propose tags

The gate header explicitly cites **Riley 2019 (BMJ)**, **Peduzzi 1996 EPV**, and **TRIPOD+AI 2024 Item 4a**. The first two are KB-resident as LIT-005 / LIT-006 / LIT-027 / LIT-058; TRIPOD+AI is LIT-001. The patch adds `cohort_definition_gate` to:

| LIT-id | Why |
|---|---|
| LIT-001 (TRIPOD+AI) | Gate header literally cites "TRIPOD+AI 2024 Item 4a — Study participants" |
| LIT-031 (PROGRESS-3) | Geographic / temporal cohort separation is a cohort-definition rule |
| LIT-041 (TRIPOD 2015) | "Patient flow diagram (CONSORT-style) required" = cohort definition |
| LIT-058 (Riley sample-size simulation) | Validates EPV/shrinkage formulae that the gate computes |

**Resulting count: 4.** Confidence: **High**.

### `shap_interpretability_gate` → recommend "no methodology lit needed"

The gate header cites **Lundberg & Lee 2017 (NeurIPS)**, **Lundberg 2020 (Nat Mach Intel)**, **PMC11513550 (2024) practical SHAP guide**, and **arxiv 2505.24612 (2025) multi-criteria rank aggregation**. None of these are present in `literature-knowledge-base.json`, and none meet the KB inclusion criteria as written:

- Lundberg & Lee — NeurIPS conference paper; KB excludes "conference abstracts without full paper" and IF gate is journal-only.
- Lundberg 2020 Nat Mach Intel — IF≈25.9, would qualify, but not yet in KB.
- PMC11513550 — review IF unknown.
- arxiv 2505.24612 — preprint without verified journal acceptance.

**Recommendation: leave `shap_interpretability_gate` with zero lit support and flag as procedural / tool-driven.** The gate computes SHAP via shipped libraries; its methodological backbone is the SHAP-library reference, not retrospective-cohort prediction methodology. A future KB curation pass could add Lundberg 2020 (Nat Mach Intel) as a new LIT entry, but that is a content-addition task (out of scope for this tag-completeness audit per "Do not invent new entries").

Confidence: **Medium** — there is a legitimate argument that interpretability is a publication-grade requirement (TRIPOD+AI Item 18 on model explainability), in which case `shap_interpretability_gate` could be tagged on LIT-001. The patch does NOT make this tag because TRIPOD+AI does not mandate SHAP specifically. Recommend follow-up with the gate owner.

## Section 4 — Summary statistics

- **Entries modified**: 26 of 67 (38.8%)
- **Total `gates_implementing` slot additions**: 38 new tags
- **Originally fragile gates (≤1 supporter)**: 14
  - Now ≥3 supporters: 8 of 14
  - Now 2 supporters: 4 of 14 (imbalance_policy_gate, prediction_replay_gate, seed_stability_gate, permutation_significance_gate)
  - Still 1 supporter (SLSA-anchored, by design): 2 of 14 (execution_attestation_gate, manifest_lock)
- **Originally zero-support gates**: 2 → cohort_definition_gate has 4; shap_interpretability_gate flagged as procedural

## Section 5 — Deep interaction (审慎挑战)

1. **The audit framed LIT-004/018/019/042 as "orphaned" but the JSON already contains explicit `applicability_note` / `applies_to_prediction_types` / `note` fields stating these are intentionally untagged.** The honest tag-completeness fix is not to force-tag them; it is to either (a) keep them as documented out-of-scope entries, or (b) decide as a project whether RCT-of-AI / LLM / multiclass papers belong in a binary-cohort KB at all. The patch takes the soft middle path for LIT-018/019 (publication-relevant tags only) and leaves LIT-004/042 untagged with explicit rationale, but the deeper question is whether the KB should partition into "in-scope" vs "future-scope" sub-collections rather than mixing them in one `entries` list. Recommend filing a separate scope-clarification task.

2. **"Fragile-gate" framing collapses two different failure modes.** A gate backed by a single methodology paper (e.g., Ojala permutation test → `permutation_significance_gate`) is not the same kind of fragility as a gate backed by a single specification (SLSA → `manifest_lock`). The former needs broader literature support; the latter is fine at N=1 because specifications don't retract. The patch handles both, but the audit metric (`≥3 supporters`) should be refined to exclude `category == "reproducibility"` SLSA-style entries.

3. **`shap_interpretability_gate` has zero support because the underlying foundational SHAP papers (Lundberg & Lee 2017, Lundberg 2020) are not in the KB at all.** This is a content-curation gap, not a tagging gap. Recommend a separate task: add LIT-067 (Lundberg 2020 Nat Mach Intel) so the gate has at least one methodology anchor. The patch does NOT do this because the audit task explicitly forbids inventing new entries.
