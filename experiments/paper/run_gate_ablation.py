#!/usr/bin/env python3
"""
Gate Ablation Experiment — measure detection coverage per gate.

For each of the 5 leakage types (L1-L5), this script determines which
MLGG gates would detect it and computes the detection coverage when
gates are progressively removed.

This produces:
  1. Gate → Leakage-type coverage matrix
  2. Ablation curve: N gates retained vs detection rate
  3. Per-gate marginal contribution to detection

Usage:
  python3 experiments/paper/run_gate_ablation.py --output experiments/paper/output/gate_ablation.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

# ---------------------------------------------------------------------------
# Gate → Leakage-type mapping
#
# Each gate can detect one or more leakage types:
#   L1: Preprocessing leakage (fit scaler on full data)
#   L2: Resampling leakage (SMOTE on full data)
#   L3: Feature selection leakage (SelectKBest on full data)
#   L4: Patient-level leakage (random split without patient grouping)
#   L5: Threshold leakage (optimize threshold on test set)
# ---------------------------------------------------------------------------

GATE_LEAKAGE_COVERAGE: Dict[str, Dict[str, Any]] = {
    # Layer 0: Contract
    "request_contract_gate": {
        "detects": [],
        "role": "infrastructure",
        "description": "Validates request schema — does not detect leakage directly",
    },
    # Layer 1: Manifest
    "manifest_lock": {
        "detects": [],
        "role": "integrity",
        "description": "Ensures artifact integrity — does not detect leakage directly",
    },
    # Layer 2: Attestation
    "execution_attestation_gate": {
        "detects": [],
        "role": "provenance",
        "description": "Cryptographic execution proof — does not detect leakage directly",
    },
    # Layer 3: Data Validation
    "leakage_gate": {
        "detects": ["L4"],
        "role": "detection",
        "description": "Detects patient-ID overlap and row-hash duplicates across splits",
    },
    "split_protocol_gate": {
        "detects": ["L4"],
        "role": "detection",
        "description": "Validates split strategy, patient-level disjointness, stratification",
    },
    "covariate_shift_gate": {
        "detects": ["L1", "L2", "L3"],
        "role": "detection",
        "description": "Detects distribution shift — preprocessing leakage causes artificially low shift",
    },
    "reporting_bias_gate": {
        "detects": [],
        "role": "reporting",
        "description": "TRIPOD+AI/PROBAST+AI checklist — flags missing methodology reporting",
    },
    # Layer 4: Policy
    "definition_variable_guard": {
        "detects": [],
        "role": "clinical",
        "description": "Phenotype definition leakage — not tested in L1-L5 experiments",
    },
    "feature_lineage_gate": {
        "detects": ["L3"],
        "role": "detection",
        "description": "Verifies feature provenance — detects selection before split",
    },
    "imbalance_policy_gate": {
        "detects": ["L2"],
        "role": "detection",
        "description": "Validates resampling policy — detects SMOTE applied to full data",
    },
    "missingness_policy_gate": {
        "detects": ["L1"],
        "role": "detection",
        "description": "Validates imputation policy — detects imputer fit on full data",
    },
    "tuning_leakage_gate": {
        "detects": ["L5"],
        "role": "detection",
        "description": "Detects hyperparameter/threshold tuning using test data",
    },
    # Layer 5: Model Audit
    "model_selection_audit_gate": {
        "detects": ["L5"],
        "role": "detection",
        "description": "Audits model selection process — detects test-data contamination",
    },
    "feature_engineering_audit_gate": {
        "detects": ["L1", "L3"],
        "role": "detection",
        "description": "Audits feature engineering — detects preprocessing/selection leakage",
    },
    "clinical_metrics_gate": {
        "detects": [],
        "role": "clinical",
        "description": "Validates clinical metric floors — indirectly affected by leakage",
    },
    # Layer 6: Metric Validation
    "metric_consistency_gate": {
        "detects": [],
        "role": "statistical",
        "description": "Metric cross-validation — infrastructure gate",
    },
    "prediction_replay_gate": {
        "detects": [],
        "role": "reproducibility",
        "description": "Replay predictions for consistency — infrastructure gate",
    },
    "calibration_dca_gate": {
        "detects": ["L1", "L2"],
        "role": "detection",
        "description": "Poor calibration suggests data leakage (overfit to test distribution)",
    },
    "ci_matrix_gate": {
        "detects": [],
        "role": "statistical",
        "description": "Bootstrap CI — infrastructure gate",
    },
    "evaluation_quality_gate": {
        "detects": ["L1", "L2", "L3"],
        "role": "detection",
        "description": "Excessive train-test gap or suspiciously narrow CI suggests leakage",
    },
    "generalization_gap_gate": {
        "detects": ["L1", "L2", "L3", "L4"],
        "role": "detection",
        "description": "Detects inflated test performance via train-test gap analysis",
    },
    "external_validation_gate": {
        "detects": ["L1", "L2", "L3", "L4"],
        "role": "detection",
        "description": "External cohort reveals leakage-inflated performance",
    },
    "robustness_gate": {
        "detects": [],
        "role": "statistical",
        "description": "Subgroup robustness — indirectly affected",
    },
    "seed_stability_gate": {
        "detects": ["L1", "L2", "L3"],
        "role": "detection",
        "description": "Seed instability suggests overfitting due to leakage",
    },
    "distribution_generalization_gate": {
        "detects": ["L1", "L2"],
        "role": "detection",
        "description": "Cross-split distribution analysis reveals preprocessing leakage",
    },
    "permutation_significance_gate": {
        "detects": [],
        "role": "statistical",
        "description": "Permutation null test — infrastructure gate",
    },
    "fairness_equity_gate": {
        "detects": [],
        "role": "fairness",
        "description": "Fairness metrics — not directly related to L1-L5",
    },
    "sample_size_gate": {
        "detects": [],
        "role": "adequacy",
        "description": "Sample size adequacy — not directly related to L1-L5",
    },
    # Layer 7-8: Aggregation
    "publication_gate": {
        "detects": ["L1", "L2", "L3", "L4", "L5"],
        "role": "aggregation",
        "description": "Aggregates all gate results — catches anything upstream catches",
    },
    "self_critique_gate": {
        "detects": [],
        "role": "aggregation",
        "description": "Quality scoring — aggregation gate",
    },
    "security_audit_gate": {
        "detects": [],
        "role": "security",
        "description": "Security verification — not related to L1-L5",
    },
    "cohort_definition_gate": {
        "detects": [],
        "role": "clinical",
        "description": "Validates cohort definition and inclusion/exclusion criteria",
    },
    "shap_interpretability_gate": {
        "detects": [],
        "role": "interpretability",
        "description": "SHAP value consistency and interpretability checks",
    },
}

LEAKAGE_TYPES = ["L1", "L2", "L3", "L4", "L5"]
LEAKAGE_NAMES = {
    "L1": "Preprocessing (scaler on full data)",
    "L2": "Resampling (SMOTE on full data)",
    "L3": "Feature selection (on full data)",
    "L4": "Patient-level (no grouping)",
    "L5": "Threshold (optimized on test)",
}


def compute_coverage_matrix() -> Dict[str, Any]:
    """Compute which gates detect which leakage types."""
    matrix: Dict[str, Dict[str, bool]] = {}
    for gate, info in GATE_LEAKAGE_COVERAGE.items():
        matrix[gate] = {lt: lt in info["detects"] for lt in LEAKAGE_TYPES}
    return matrix


def compute_ablation_curve() -> List[Dict[str, Any]]:
    """Progressively remove gates and measure detection coverage.

    Strategy: rank gates by marginal contribution (greedy), then
    show how coverage degrades as gates are removed in reverse order.
    """
    # Identify detection gates (exclude aggregation gates — they don't
    # independently detect, they just aggregate upstream results)
    detection_gates = [
        g for g, info in GATE_LEAKAGE_COVERAGE.items()
        if info["detects"] and info["role"] != "aggregation"
    ]

    # Greedy ranking: pick gate that covers most uncovered leakage types
    remaining = set(detection_gates)
    selected_order: List[str] = []
    covered_so_far: Set[str] = set()

    while remaining:
        best_gate = None
        best_new = 0
        for g in remaining:
            new_coverage = set(GATE_LEAKAGE_COVERAGE[g]["detects"]) - covered_so_far
            if len(new_coverage) > best_new:
                best_new = len(new_coverage)
                best_gate = g
        if best_gate is None:
            # Remaining gates don't add new coverage, add them anyway
            selected_order.extend(sorted(remaining))
            break
        selected_order.append(best_gate)
        covered_so_far |= set(GATE_LEAKAGE_COVERAGE[best_gate]["detects"])
        remaining.discard(best_gate)

    # Build ablation curve: for N = 1..len(detection_gates), compute coverage
    curve: List[Dict[str, Any]] = []
    for n in range(len(selected_order) + 1):
        active = set(selected_order[:n])
        covered = set()
        for g in active:
            covered |= set(GATE_LEAKAGE_COVERAGE[g]["detects"])
        coverage_rate = len(covered) / len(LEAKAGE_TYPES) if LEAKAGE_TYPES else 0
        curve.append({
            "n_gates": n,
            "coverage_rate": round(coverage_rate, 4),
            "covered_types": sorted(covered),
            "missing_types": sorted(set(LEAKAGE_TYPES) - covered),
            "last_added": selected_order[n - 1] if n > 0 else None,
        })

    return curve


def compute_marginal_contribution() -> List[Dict[str, Any]]:
    """Compute each detection gate's unique contribution."""
    contributions: List[Dict[str, Any]] = []

    for gate, info in GATE_LEAKAGE_COVERAGE.items():
        if not info["detects"]:
            continue

        detects = set(info["detects"])

        # Check if any other gate also detects the same types
        unique_detections: Set[str] = set()
        for lt in detects:
            other_detectors = [
                g for g, i in GATE_LEAKAGE_COVERAGE.items()
                if g != gate and lt in i["detects"]
            ]
            if not other_detectors:
                unique_detections.add(lt)

        contributions.append({
            "gate": gate,
            "role": info["role"],
            "detects": sorted(detects),
            "n_detects": len(detects),
            "unique_detections": sorted(unique_detections),
            "n_unique": len(unique_detections),
            "redundancy": round(1 - len(unique_detections) / len(detects), 4) if detects else 0,
            "description": info["description"],
        })

    # Sort by unique contribution descending
    contributions.sort(key=lambda x: (-x["n_unique"], -x["n_detects"]))
    return contributions


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Gate ablation experiment.")
    parser.add_argument("--output", type=str,
                        default=str(Path(__file__).parent / "output" / "gate_ablation.json"))
    args = parser.parse_args()

    matrix = compute_coverage_matrix()
    curve = compute_ablation_curve()
    contributions = compute_marginal_contribution()

    # Summary statistics
    detection_gates = [g for g, i in GATE_LEAKAGE_COVERAGE.items() if i["detects"]]
    non_detection_gates = [g for g, i in GATE_LEAKAGE_COVERAGE.items() if not i["detects"]]

    # Per-leakage-type detector count
    type_coverage: Dict[str, List[str]] = {lt: [] for lt in LEAKAGE_TYPES}
    for g, info in GATE_LEAKAGE_COVERAGE.items():
        for lt in info["detects"]:
            type_coverage[lt].append(g)

    result = {
        "experiment": "gate_ablation",
        "total_gates": len(GATE_LEAKAGE_COVERAGE),
        "detection_gates": len(detection_gates),
        "non_detection_gates": len(non_detection_gates),
        "leakage_types": LEAKAGE_NAMES,
        "type_coverage": {
            lt: {"detectors": detectors, "n_detectors": len(detectors)}
            for lt, detectors in type_coverage.items()
        },
        "coverage_matrix": matrix,
        "ablation_curve": curve,
        "marginal_contributions": contributions,
        "minimum_gate_set": {
            "description": "Minimum gates needed for full L1-L5 coverage",
            "n_gates": next(
                (p["n_gates"] for p in curve if p["coverage_rate"] >= 1.0),
                len(detection_gates),
            ),
            "gates": [
                p["last_added"] for p in curve
                if p["last_added"] and p["coverage_rate"] <= 1.0
            ][:next(
                (p["n_gates"] for p in curve if p["coverage_rate"] >= 1.0),
                len(detection_gates),
            )],
        },
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"Gate Ablation Experiment")
    print(f"{'='*60}")
    print(f"Total gates: {result['total_gates']}")
    print(f"Detection gates: {result['detection_gates']}")
    print(f"Non-detection (infrastructure/reporting): {result['non_detection_gates']}")
    print()

    print("Per-leakage-type coverage:")
    for lt in LEAKAGE_TYPES:
        tc = type_coverage[lt]
        print(f"  {lt} ({LEAKAGE_NAMES[lt][:40]}): {len(tc)} gates")

    print()
    print("Ablation curve (greedy gate addition):")
    for p in curve:
        bar = "█" * int(p["coverage_rate"] * 20)
        if p["last_added"]:
            print(f"  {p['n_gates']:2d} gates: {p['coverage_rate']*100:5.1f}% {bar:<20} +{p['last_added']}")
        else:
            print(f"  {p['n_gates']:2d} gates:   0.0%")

    print()
    min_set = result["minimum_gate_set"]
    print(f"Minimum gate set for 100% coverage: {min_set['n_gates']} gates")
    for g in min_set["gates"]:
        print(f"  - {g}")

    print()
    print("Top gates by unique contribution:")
    for c in contributions[:8]:
        unique = ", ".join(c["unique_detections"]) if c["unique_detections"] else "(redundant)"
        print(f"  {c['gate']:<35} detects {c['n_detects']}  unique: {unique}")

    print(f"\nOutput: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
