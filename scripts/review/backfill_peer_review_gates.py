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
