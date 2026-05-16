"""P0-3b migration: backfill mlgg_gates for concerns with empty arrays.

Problem: 272 of 375 concerns in peer-review-kb.json have empty mlgg_gates,
so peer_review_lookup.py --gate <name> silently misses ~72% of the KB.
See references/case-studies/peer-review-kb-audit-2026-04.md.

Approach: deterministic rule table (category + tags → gates). No LLM in the loop.
Idempotent: re-running is a no-op for already-populated concerns unless --force.

Usage:
    python3 scripts/review/backfill_peer_review_gates.py              # dry-run
    python3 scripts/review/backfill_peer_review_gates.py --apply      # write
    python3 scripts/review/backfill_peer_review_gates.py --apply --force  # re-map all
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
STATS_PATH = ROOT / "references" / "case-studies" / "peer-review-kb-stats.json"
GATES_DIR = ROOT / "scripts" / "gates"

# -------- Rule table --------
# Every category gets at least one primary gate so retrieval-by-gate never returns empty.
CATEGORY_TO_GATES: dict[str, list[str]] = {
    "data_leakage": ["leakage_gate"],
    "split_protocol": ["split_protocol_gate"],
    "preprocessing": ["feature_engineering_audit_gate"],
    "feature_selection": ["feature_engineering_audit_gate", "feature_lineage_gate"],
    "evaluation_metrics": ["evaluation_quality_gate"],
    "model_selection": ["model_selection_audit_gate"],
    "external_validation": ["external_validation_gate"],
    "reporting": ["reporting_bias_gate"],
    "interpretability": ["shap_interpretability_gate"],
    "reproducibility": ["seed_stability_gate", "execution_attestation_gate"],
    "sample_size": ["sample_size_gate"],
    "clinical_utility": ["calibration_dca_gate", "clinical_metrics_gate"],
    "study_design": ["cohort_definition_gate"],
}

# Tag substring → extra gate(s). Matched case-insensitively on tag text.
# Keep the most specific signals first; overlays add to (not replace) the category mapping.
TAG_OVERLAYS: list[tuple[str, list[str]]] = [
    # Leakage signals
    ("target_leakage", ["leakage_gate"]),
    ("future_information", ["leakage_gate"]),
    ("definition_variable", ["leakage_gate", "definition_variable_guard"]),
    ("feature_is_outcome_proxy", ["leakage_gate"]),
    ("data_leakage_via_imputation", ["leakage_gate", "missingness_policy_gate"]),
    ("data_leakage_via_tuning", ["leakage_gate", "tuning_leakage_gate"]),
    ("data_leakage_via_correlated", ["leakage_gate"]),
    ("potential_data_leakage", ["leakage_gate"]),
    ("train_test_overlap", ["leakage_gate", "split_protocol_gate"]),
    ("patient_overlap", ["leakage_gate", "split_protocol_gate"]),
    ("sample_overlap", ["leakage_gate"]),
    ("cohort_overlap", ["leakage_gate", "external_validation_gate"]),
    ("temporal_split", ["split_protocol_gate", "covariate_shift_gate"]),
    ("temporal_leakage", ["leakage_gate"]),
    ("bidirectional_rnn_leakage", ["leakage_gate"]),
    ("discovery_validation_overlap", ["leakage_gate", "external_validation_gate"]),
    ("same_data_gwas", ["leakage_gate"]),
    # Split / cohort
    ("multiple_admissions", ["split_protocol_gate"]),
    ("random_split_inappropriate", ["split_protocol_gate"]),
    ("validation_imputation", ["missingness_policy_gate", "leakage_gate"]),
    ("validation_independence", ["external_validation_gate"]),
    # Evaluation / stats
    ("calibration", ["calibration_dca_gate"]),
    ("hosmer_lemeshow", ["calibration_dca_gate"]),
    ("dca", ["calibration_dca_gate"]),
    ("decision_curve", ["calibration_dca_gate"]),
    ("net_benefit", ["calibration_dca_gate"]),
    ("bootstrap", ["ci_matrix_gate"]),
    ("confidence_interval", ["ci_matrix_gate"]),
    ("permutation_test", ["permutation_significance_gate"]),
    ("brier", ["evaluation_quality_gate"]),
    ("mcc", ["evaluation_quality_gate"]),
    ("auprc", ["evaluation_quality_gate"]),
    ("imbalanced", ["imbalance_policy_gate", "evaluation_quality_gate"]),
    ("smote", ["imbalance_policy_gate", "leakage_gate"]),
    ("class_weight", ["imbalance_policy_gate"]),
    # Fairness — narrow matches only. `subgroup` alone is too broad:
    # it also fires on clinical-interpretation subgroup analyses, confounder
    # stratification, underpowered subsets, and selective reporting — none of
    # which are fairness concerns (Codex review 2026-04-17).
    ("fairness", ["fairness_equity_gate"]),
    ("equity", ["fairness_equity_gate"]),
    ("disparate", ["fairness_equity_gate"]),
    ("equalized_odds", ["fairness_equity_gate"]),
    ("demographic_parity", ["fairness_equity_gate"]),
    ("subgroup_fairness", ["fairness_equity_gate"]),
    ("subgroup_disparity", ["fairness_equity_gate"]),
    ("gender_bias", ["fairness_equity_gate"]),
    ("racial_bias", ["fairness_equity_gate"]),
    ("ethnic_bias", ["fairness_equity_gate"]),
    # Missingness
    ("missing_data", ["missingness_policy_gate"]),
    ("imputation", ["missingness_policy_gate"]),
    ("missingness", ["missingness_policy_gate"]),
    # Threshold / clinical
    ("threshold", ["clinical_metrics_gate"]),
    ("youden", ["clinical_metrics_gate"]),
    ("confusion_matrix", ["clinical_metrics_gate"]),
    ("sensitivity", ["clinical_metrics_gate"]),
    ("specificity", ["clinical_metrics_gate"]),
    ("ppv", ["clinical_metrics_gate"]),
    ("npv", ["clinical_metrics_gate"]),
    # Sample size
    ("epv", ["sample_size_gate"]),
    ("events_per_variable", ["sample_size_gate"]),
    ("small_sample", ["sample_size_gate"]),
    ("shrinkage", ["sample_size_gate"]),
    # External validation / generalization
    ("external_validation", ["external_validation_gate"]),
    ("external_cohort", ["external_validation_gate"]),
    ("generalization", ["generalization_gap_gate", "distribution_generalization_gate"]),
    ("distribution_shift", ["distribution_generalization_gate", "covariate_shift_gate"]),
    ("out_of_distribution", ["distribution_generalization_gate"]),
    ("ood", ["distribution_generalization_gate"]),
    ("covariate_shift", ["covariate_shift_gate"]),
    ("temporal_drift", ["covariate_shift_gate"]),
    # Reporting
    ("tripod", ["reporting_bias_gate"]),
    ("probast", ["reporting_bias_gate"]),
    ("transparent_reporting", ["reporting_bias_gate"]),
    ("stard", ["reporting_bias_gate"]),
    # Robustness
    ("robustness_to", ["robustness_gate"]),
    # Permutation / statistical significance
    # Narrow needles only — generic `significance` would over-match
    # clinical_significance / clinical_significance_of_findings, which are
    # clinical-utility concerns, not falsification tests.
    ("p_value_selection", ["permutation_significance_gate"]),
    ("p_value_error", ["permutation_significance_gate"]),
    ("statistical_significance_missing", ["permutation_significance_gate"]),
    # Reproducibility
    ("seed", ["seed_stability_gate"]),
    ("random_state", ["seed_stability_gate"]),
    ("code_availability", ["execution_attestation_gate"]),
    ("version_tracking", ["execution_attestation_gate"]),
    # Interpretability
    ("shap", ["shap_interpretability_gate"]),
    ("feature_importance", ["shap_interpretability_gate"]),
    ("explainability", ["shap_interpretability_gate"]),
    ("grad_cam", ["shap_interpretability_gate"]),
    # Model selection
    ("cross_validation", ["model_selection_audit_gate"]),
    ("nested_cv", ["model_selection_audit_gate"]),
    ("hyperparameter", ["model_selection_audit_gate"]),
    ("test_peeking", ["tuning_leakage_gate", "leakage_gate"]),
    ("test_tuning", ["tuning_leakage_gate", "leakage_gate"]),
    # Cohort definition
    ("cohort_definition", ["cohort_definition_gate"]),
    ("inclusion_criteria", ["cohort_definition_gate"]),
    ("exclusion_criteria", ["cohort_definition_gate"]),
    ("case_contamination", ["cohort_definition_gate"]),
    ("cohort_contamination", ["cohort_definition_gate"]),
    ("control_matching", ["cohort_definition_gate"]),
    # Feature engineering
    ("feature_engineering", ["feature_engineering_audit_gate"]),
    ("feature_extraction", ["feature_engineering_audit_gate"]),
    ("target_encoding", ["feature_engineering_audit_gate", "leakage_gate"]),
    ("frequency_encoding", ["feature_engineering_audit_gate"]),
    # ---- QA Wave 2026-05-13 (A8) additions ----
    # Q1 audit found 234/282 empty-gate concerns received only the single
    # category-default gate because the TAG_OVERLAYS vocabulary lagged behind
    # how reviewers actually phrase issues in 2024-2026 papers. Patterns below
    # are substring needles chosen to catch tag families (e.g. all
    # `confounding_by_*`, `*_overclaim*`, `*_heterogeneity`) without
    # over-matching unrelated clinical-context tags. See
    # paper/qa-wave-2026-05-13/q-a8-tag-overlays.json for rule-by-rule rationale.

    # Causal-language overreach → cohort design + reporting bias (claims
    # outrun the observational data-generating process)
    ("causal_language", ["cohort_definition_gate", "reporting_bias_gate"]),
    ("association_not_causation", ["cohort_definition_gate", "reporting_bias_gate"]),
    ("association_vs_causation", ["cohort_definition_gate", "reporting_bias_gate"]),
    ("causal_overclaim", ["cohort_definition_gate", "reporting_bias_gate"]),
    ("causal_claim_unsupported", ["cohort_definition_gate", "reporting_bias_gate"]),
    ("causal_inference", ["cohort_definition_gate"]),

    # Acquisition / device / protocol heterogeneity → distribution shift +
    # covariate shift (different scanners, assays, sites generate distribution
    # gaps that break generalization)
    ("heterogeneity", ["distribution_generalization_gate", "covariate_shift_gate"]),

    # Confounding & demographics imbalance → fairness/equity + cohort
    # definition (most `confounding_by_*` tags concern sex/age/comorbidity
    # imbalance that drives subgroup harm)
    ("confounding", ["fairness_equity_gate", "cohort_definition_gate"]),
    ("missing_demographics", ["fairness_equity_gate", "reporting_bias_gate"]),
    ("missing_confounder", ["cohort_definition_gate", "feature_engineering_audit_gate"]),
    ("population_stratification", ["fairness_equity_gate", "cohort_definition_gate"]),
    ("ancestry", ["fairness_equity_gate", "external_validation_gate"]),
    ("fitzpatrick", ["fairness_equity_gate"]),
    ("skin_tone", ["fairness_equity_gate"]),

    # CI / DeLong / cindex_missing → CI matrix (reviewers asking for
    # uncertainty quantification across performance metrics)
    ("missing_ci", ["ci_matrix_gate", "evaluation_quality_gate"]),
    ("delong", ["ci_matrix_gate", "evaluation_quality_gate"]),
    ("cindex_missing", ["ci_matrix_gate", "evaluation_quality_gate"]),
    ("ci_methodology", ["ci_matrix_gate"]),
    ("ci_reporting", ["ci_matrix_gate"]),
    ("ci_needed", ["ci_matrix_gate"]),

    # Clinical reclassification & utility economics → clinical metrics
    # (NRI/IDI/cost-effectiveness all measure incremental clinical value)
    ("nri", ["clinical_metrics_gate", "calibration_dca_gate"]),
    ("idi", ["clinical_metrics_gate", "calibration_dca_gate"]),
    ("cost_effectiveness", ["clinical_metrics_gate"]),
    ("incremental_value", ["clinical_metrics_gate", "calibration_dca_gate"]),
    ("net_reclassification", ["clinical_metrics_gate"]),
    ("alert_fatigue", ["clinical_metrics_gate"]),
    ("alarm_fatigue", ["clinical_metrics_gate"]),

    # Multiple testing / p-hacking / selective reporting → evaluation
    # quality + permutation significance (need correction or falsification)
    ("p_hacking", ["evaluation_quality_gate", "permutation_significance_gate"]),
    ("multiple_testing", ["evaluation_quality_gate", "permutation_significance_gate"]),
    ("bonferroni", ["evaluation_quality_gate"]),
    ("fdr", ["evaluation_quality_gate"]),
    ("selective_reporting", ["reporting_bias_gate", "evaluation_quality_gate"]),
    ("cherry_pick", ["reporting_bias_gate", "evaluation_quality_gate"]),
    ("cherrypick", ["reporting_bias_gate", "evaluation_quality_gate"]),

    # PHI dates as features / temporal encoding → feature lineage + leakage
    # (date-derived features can encode outcome timing or PHI)
    ("phi_dates", ["feature_lineage_gate", "leakage_gate"]),
    ("temporal_encoding", ["feature_lineage_gate", "leakage_gate"]),
    ("feature_timing", ["feature_lineage_gate", "leakage_gate"]),
    ("date_features", ["feature_lineage_gate"]),
    ("timestamp_feature", ["feature_lineage_gate"]),

    # Label quality (noise, validity, definition drift) → feature lineage +
    # cohort definition (label_noise tags often imply outcome ascertainment
    # ambiguity that biases performance estimates)
    ("label_noise", ["feature_lineage_gate", "evaluation_quality_gate"]),
    ("label_validity", ["feature_lineage_gate", "cohort_definition_gate"]),
    ("label_definition", ["cohort_definition_gate", "feature_lineage_gate"]),
    ("noisy_labels", ["feature_lineage_gate", "evaluation_quality_gate"]),
    ("outcome_definition", ["cohort_definition_gate", "feature_lineage_gate"]),
    ("outcome_misclassification", ["evaluation_quality_gate", "cohort_definition_gate"]),
    ("outcome_ascertainment", ["cohort_definition_gate"]),
    ("case_ascertainment", ["cohort_definition_gate"]),
    ("case_definition", ["cohort_definition_gate"]),

    # Selection / verification / spectrum / prevalence / lead-time bias →
    # cohort definition + reporting bias (recruitment-level biases that
    # warrant inclusion/exclusion + flow-diagram scrutiny)
    ("selection_bias", ["cohort_definition_gate", "reporting_bias_gate"]),
    ("verification_bias", ["cohort_definition_gate", "evaluation_quality_gate"]),
    ("spectrum_bias", ["cohort_definition_gate", "distribution_generalization_gate"]),
    ("prevalence_bias", ["cohort_definition_gate", "evaluation_quality_gate"]),
    ("lead_time_bias", ["cohort_definition_gate", "evaluation_quality_gate"]),
    ("optimism_bias", ["evaluation_quality_gate", "model_selection_audit_gate"]),
    ("collider_bias", ["cohort_definition_gate", "feature_lineage_gate"]),

    # Reproducibility surface (code links, coefficients, training details) →
    # execution attestation + reporting bias
    ("reproducibility", ["seed_stability_gate", "execution_attestation_gate"]),
    ("irreproducible", ["execution_attestation_gate", "reporting_bias_gate"]),
    ("code_unavailable", ["execution_attestation_gate", "reporting_bias_gate"]),
    ("broken_code_link", ["execution_attestation_gate"]),
    ("broken_github", ["execution_attestation_gate"]),
    ("coefficients_not_provided", ["execution_attestation_gate", "reporting_bias_gate"]),
    ("training_details_missing", ["execution_attestation_gate", "reporting_bias_gate"]),
    ("model_transparency", ["execution_attestation_gate", "reporting_bias_gate"]),
    ("architecture_reproducibility", ["execution_attestation_gate"]),

    # Overclaim / overstatement / novelty inflation → reporting bias
    # (title/abstract/results overstated relative to evidence)
    ("overclaim", ["reporting_bias_gate"]),
    ("overstatement", ["reporting_bias_gate"]),
    ("overstated", ["reporting_bias_gate"]),
    ("misleading_claim", ["reporting_bias_gate"]),
    ("novelty_questioned", ["reporting_bias_gate"]),
    ("marginal_improvement", ["reporting_bias_gate", "evaluation_quality_gate"]),
    ("modest_performance", ["reporting_bias_gate", "evaluation_quality_gate"]),
    ("title_misleading", ["reporting_bias_gate"]),
    ("title_overstatement", ["reporting_bias_gate"]),
    ("abstract_mismatch", ["reporting_bias_gate"]),
    ("abstract_only_insufficient", ["reporting_bias_gate"]),
    ("no_limitations", ["reporting_bias_gate"]),

    # Reporting guideline adherence (TRIPOD/PROBAST/STARD families) +
    # completeness of methods reporting → reporting bias
    ("reporting_guideline", ["reporting_bias_gate"]),
    ("reporting_completeness", ["reporting_bias_gate"]),
    ("reporting_quality", ["reporting_bias_gate"]),
    ("metrics_in_supplement", ["reporting_bias_gate", "evaluation_quality_gate"]),
    ("calibration_in_supplement", ["reporting_bias_gate", "calibration_dca_gate"]),
    ("calibration_plot", ["calibration_dca_gate", "reporting_bias_gate"]),
    ("calibration_drift", ["calibration_dca_gate", "covariate_shift_gate"]),
    ("calibration_leakage", ["calibration_dca_gate", "leakage_gate"]),

    # Single-site / same-cohort validation / no-prospective → external
    # validation + generalization gap
    ("single_center", ["external_validation_gate", "generalization_gap_gate"]),
    ("single_site", ["external_validation_gate", "generalization_gap_gate"]),
    ("same_cohort_validation", ["external_validation_gate", "generalization_gap_gate"]),
    ("single_split", ["split_protocol_gate", "external_validation_gate"]),
    ("no_prospective", ["external_validation_gate", "generalization_gap_gate"]),
    ("prospective_vs_retrospective", ["external_validation_gate", "reporting_bias_gate"]),
    ("retrospective_vs_prospective", ["external_validation_gate", "reporting_bias_gate"]),
    ("performance_degradation_external", ["external_validation_gate", "generalization_gap_gate"]),
    ("internal_external_gap", ["external_validation_gate", "generalization_gap_gate"]),

    # Sample-size / power red flags (underpowered, small test sets, rare
    # classes) → sample-size gate + evaluation quality
    ("underpowered", ["sample_size_gate", "evaluation_quality_gate"]),
    ("small_test_set", ["sample_size_gate", "evaluation_quality_gate"]),
    ("rare_class_sample_size", ["sample_size_gate", "imbalance_policy_gate"]),
    ("extreme_class_imbalance", ["imbalance_policy_gate", "sample_size_gate"]),
    ("class_imbalance", ["imbalance_policy_gate", "evaluation_quality_gate"]),

    # Model-justification / architecture / search-space → model selection
    # audit
    ("model_justification", ["model_selection_audit_gate"]),
    ("architecture_justification", ["model_selection_audit_gate"]),
    ("model_description_unclear", ["model_selection_audit_gate", "reporting_bias_gate"]),
    ("narrow_model_search", ["model_selection_audit_gate"]),
    ("single_model_type", ["model_selection_audit_gate"]),
    ("cv_strategy_unspecified", ["model_selection_audit_gate", "split_protocol_gate"]),
    ("feature_selection_justification", ["feature_engineering_audit_gate", "model_selection_audit_gate"]),
    ("feature_selection_process", ["feature_engineering_audit_gate", "model_selection_audit_gate"]),

    # Metric panel completeness / AUC-only critique → evaluation quality +
    # clinical metrics
    ("auc_only", ["evaluation_quality_gate", "clinical_metrics_gate"]),
    ("auc_overoptimistic", ["evaluation_quality_gate", "calibration_dca_gate"]),
    ("auc_misleading", ["evaluation_quality_gate", "clinical_metrics_gate"]),
    ("auroc_misleading", ["evaluation_quality_gate", "clinical_metrics_gate"]),
    ("accuracy_misleading", ["evaluation_quality_gate", "clinical_metrics_gate"]),
    ("incomplete_metrics", ["evaluation_quality_gate", "clinical_metrics_gate"]),
    ("missing_precision_recall", ["evaluation_quality_gate"]),
    ("metric_panel_incomplete", ["evaluation_quality_gate", "clinical_metrics_gate"]),
    ("full_metric_panel", ["evaluation_quality_gate", "clinical_metrics_gate"]),
    ("clinical_metric_panel", ["clinical_metrics_gate"]),

    # Clinical-utility / workflow / deployment readiness → clinical metrics
    # + DCA (does the model produce decision-relevant value?)
    ("clinical_utility", ["clinical_metrics_gate", "calibration_dca_gate"]),
    ("clinical_actionability", ["clinical_metrics_gate"]),
    ("clinical_applicability", ["clinical_metrics_gate"]),
    ("clinical_deployment", ["clinical_metrics_gate", "calibration_dca_gate"]),
    ("clinical_workflow", ["clinical_metrics_gate"]),
    ("workflow_integration", ["clinical_metrics_gate"]),
    ("deployment_feasibility", ["clinical_metrics_gate"]),

    # EHR/claims/billing label sources → feature lineage + cohort definition
    # (billing codes drift from clinical truth and bias labels)
    ("billing_code", ["feature_lineage_gate", "cohort_definition_gate"]),
    ("billing_vs_clinical", ["feature_lineage_gate", "cohort_definition_gate"]),
    ("icd_code", ["feature_lineage_gate", "cohort_definition_gate"]),
    ("claims_data", ["feature_lineage_gate", "cohort_definition_gate"]),
    ("claims_label_noise", ["feature_lineage_gate", "evaluation_quality_gate"]),
    ("claims_vs_data", ["feature_lineage_gate", "cohort_definition_gate"]),

    # Annotation / inter-rater quality → feature lineage + sample size
    # (label-source quality bounds the achievable evaluation)
    ("inter_rater", ["feature_lineage_gate", "evaluation_quality_gate"]),
    ("annotator_count_low", ["feature_lineage_gate", "sample_size_gate"]),
    ("annotator_variance", ["feature_lineage_gate", "evaluation_quality_gate"]),
    ("annotation_quality", ["feature_lineage_gate"]),
    ("ground_truth_undefined", ["feature_lineage_gate", "cohort_definition_gate"]),

    # Tuning-leakage variants the existing rules missed
    ("tuning_leakage", ["tuning_leakage_gate", "leakage_gate"]),
    ("baseline_tuning_undocumented", ["tuning_leakage_gate", "model_selection_audit_gate"]),
    ("test_set_reuse", ["tuning_leakage_gate", "leakage_gate"]),

    # Patient/site partition reinforcement
    ("patient_level_split", ["split_protocol_gate"]),
    ("patient_level_isolation", ["split_protocol_gate"]),
    ("per_clinic_results", ["external_validation_gate", "fairness_equity_gate"]),
    ("per_center_missing", ["external_validation_gate"]),
    ("center_distribution_undocumented", ["external_validation_gate", "reporting_bias_gate"]),

    # Interpretability gaps not covered by `shap`/`grad_cam` family
    ("explainability", ["shap_interpretability_gate"]),
    ("interpretability", ["shap_interpretability_gate"]),
    ("attention_interpretation", ["shap_interpretability_gate"]),
    ("background_attention", ["shap_interpretability_gate", "leakage_gate"]),
    ("cam_on_background", ["shap_interpretability_gate", "leakage_gate"]),
    ("feature_attribution", ["shap_interpretability_gate"]),

    # Benchmarking / baseline absence (reviewers consistently ask for
    # head-to-head against an established comparator)
    ("missing_baseline_comparison", ["model_selection_audit_gate", "reporting_bias_gate"]),
    ("baseline_comparison", ["model_selection_audit_gate"]),
    ("sota_comparison", ["model_selection_audit_gate", "reporting_bias_gate"]),
    ("benchmark", ["model_selection_audit_gate"]),
    ("ablation", ["model_selection_audit_gate", "feature_engineering_audit_gate"]),
]


def _valid_gate_names() -> set[str]:
    """Discover gate names by scanning scripts/gates/*.py (excluding __init__)."""
    names = set()
    for p in GATES_DIR.glob("*.py"):
        if p.stem == "__init__":
            continue
        names.add(p.stem)
    return names


def _derive_gates(category: str, tags: list[str]) -> list[str]:
    """Apply rule table to produce a gate list. Preserves rule-table order, dedups."""
    result: list[str] = []

    def _add(gs: list[str]) -> None:
        for g in gs:
            if g not in result:
                result.append(g)

    _add(CATEGORY_TO_GATES.get(category, []))
    tag_text = " ".join(tags).lower()
    for needle, overlay_gates in TAG_OVERLAYS:
        if needle in tag_text:
            _add(overlay_gates)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes to disk")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Also re-map concerns that already have non-empty mlgg_gates",
    )
    args = parser.parse_args()

    valid = _valid_gate_names()
    kb = json.loads(KB_PATH.read_text())

    # Validate rule table against actual gate names (fail fast on typos)
    all_rule_gates = {g for gs in CATEGORY_TO_GATES.values() for g in gs}
    for _, gs in TAG_OVERLAYS:
        all_rule_gates.update(gs)
    unknown = all_rule_gates - valid
    if unknown:
        raise SystemExit(f"Rule table references unknown gates: {sorted(unknown)}")

    patched = 0
    skipped_nonempty = 0
    unchanged = 0
    patch_log: list[tuple[str, list[str], list[str]]] = []

    for entry in kb["entries"]:
        for c in entry.get("reviewer_concerns", []):
            before = list(c.get("mlgg_gates") or [])
            if before and not args.force:
                skipped_nonempty += 1
                continue
            derived = _derive_gates(c["category"], c.get("tags") or [])
            if not derived:
                # No rule matched. Fall back to a single 'publication_gate' so concern is still discoverable.
                derived = ["publication_gate"]
            if args.force:
                merged = list(dict.fromkeys(before + derived))
            else:
                merged = derived
            if merged == before:
                unchanged += 1
                continue
            c["mlgg_gates"] = merged
            patched += 1
            patch_log.append((c["concern_id"], before, merged))

    print(f"Patched: {patched}")
    print(f"Skipped (already populated, --force off): {skipped_nonempty}")
    print(f"Unchanged: {unchanged}")

    # Show a few examples
    for cid, before, after in patch_log[:10]:
        print(f"  {cid}: {before} -> {after}")
    if len(patch_log) > 10:
        print(f"  ... {len(patch_log) - 10} more")

    # Post-migration coverage summary
    all_concerns = [c for e in kb["entries"] for c in e.get("reviewer_concerns", [])]
    empty_after = sum(1 for c in all_concerns if not (c.get("mlgg_gates") or []))
    gate_counts = Counter(g for c in all_concerns for g in (c.get("mlgg_gates") or []))
    print(f"\nPost-migration empty mlgg_gates: {empty_after}/{len(all_concerns)}")
    print("Top gates by concern count:")
    for g, n in gate_counts.most_common(8):
        print(f"  {g:40s} {n}")

    if not args.apply:
        print("\n(dry-run; pass --apply to write)")
        return

    if patched == 0:
        # Idempotency guard (Codex review 2026-04-17): re-running --apply with
        # no material changes must NOT append a duplicate change_log entry.
        print("\nNothing to write (patched=0); skipping file update.")
        return

    # Bump contract version + add change log entry — only once per distinct migration.
    kb["contract_version"] = "peer_review_kb.v1.2"
    change_log = kb.setdefault("change_log", [])
    _mode = "force-re-derived" if args.force else "backfilled empty arrays"
    new_entry = {
        "version": "v1.2",
        "date": "2026-04-17",
        "change": (
            f"P0-3b: {_mode} mlgg_gates using deterministic category+tags rule table "
            f"(scripts/review/backfill_peer_review_gates.py). "
            f"Patched {patched} concerns; empty count {empty_after}/{len(all_concerns)}."
        ),
    }
    # Skip if an entry with the same version AND change text already exists.
    if not any(
        e.get("version") == new_entry["version"] and e.get("change") == new_entry["change"]
        for e in change_log
    ):
        change_log.append(new_entry)

    # Atomic write via temp file + rename (prevents partial-write corruption
    # on concurrent invocations).
    import os
    tmp_path = KB_PATH.with_suffix(KB_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp_path, KB_PATH)
    print(f"\nWrote {KB_PATH}")

    # Regenerate stats
    stats = {
        "total_papers": len(kb["entries"]),
        "total_concerns": len(all_concerns),
        "total_strengths": sum(len(e.get("reviewer_strengths", [])) for e in kb["entries"]),
        "concerns_by_category": dict(Counter(c["category"] for c in all_concerns).most_common()),
        "concerns_by_severity": dict(Counter(c["severity"] for c in all_concerns).most_common()),
        "concerns_by_dimension": dict(
            sorted(
                (str(k), v)
                for k, v in Counter(
                    c.get("mlgg_dimension") for c in all_concerns if c.get("mlgg_dimension")
                ).items()
            )
        ),
        "concerns_by_gate": dict(gate_counts.most_common()),
        "concerns_with_empty_gates": empty_after,
    }
    STATS_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {STATS_PATH}")


if __name__ == "__main__":
    main()
