"""
Triage: intelligent gate routing for ml-governance-guard.

Two-layer decision system:
  1. Rule layer — deterministic, zero-cost, handles clear-cut cases
  2. LLM layer  — handles ambiguous cases where rules can't decide

Mandatory gates are never skippable regardless of triage output.

Usage:
    from triage import triage_gates
    skip_list = triage_gates(normalized_request, split_paths)
    # skip_list is a list of gate names to skip
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Import gate registry
_CORE_DIR = str(Path(__file__).resolve().parent.parent / "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from _gate_registry import GATE_REGISTRY, GateSpec  # noqa: E402


# ---------------------------------------------------------------------------
# Gate classification
# ---------------------------------------------------------------------------

# These gates are NEVER skipped — compliance/integrity requirements
MANDATORY_GATES: frozenset = frozenset({
    "request_contract_gate",
    "cohort_definition_gate",
    "manifest_lock",
    "execution_attestation_gate",
    "leakage_gate",
    "split_protocol_gate",
    "publication_gate",
    "security_audit_gate",
    "self_critique_gate",
})


@dataclass
class TriageDecision:
    """Result of triage for a single gate."""
    gate: str
    action: str  # "run", "skip", "uncertain"
    reason: str
    source: str  # "mandatory", "rule", "llm"


# ---------------------------------------------------------------------------
# Layer 1: Rule-based triage
# ---------------------------------------------------------------------------

def _rule_triage(
    normalized: Dict[str, Any],
    split_paths: Dict[str, str],
) -> Dict[str, TriageDecision]:
    """Apply deterministic rules to classify gates. Fast, zero-cost."""
    decisions: Dict[str, TriageDecision] = {}

    # --- Mandatory gates: always run ---
    for gate_name in MANDATORY_GATES:
        if gate_name in GATE_REGISTRY:
            decisions[gate_name] = TriageDecision(
                gate=gate_name, action="run",
                reason="Mandatory — compliance/integrity gate",
                source="mandatory",
            )

    # --- Rule: no test split → skip split-dependent gates ---
    if "test" not in split_paths:
        no_test_gates = {
            "covariate_shift_gate", "imbalance_policy_gate",
            "missingness_policy_gate", "distribution_generalization_gate",
            "shap_interpretability_gate", "robustness_gate",
        }
        for g in no_test_gates:
            if g in GATE_REGISTRY and g not in MANDATORY_GATES:
                decisions[g] = TriageDecision(
                    gate=g, action="skip",
                    reason="No test split available",
                    source="rule",
                )

    # --- Rule: no external cohort spec → skip external validation ---
    ext_spec = normalized.get("external_cohort_spec") or normalized.get("external_validation_report_file")
    if not ext_spec:
        decisions["external_validation_gate"] = TriageDecision(
            gate="external_validation_gate", action="skip",
            reason="No external cohort spec or report provided",
            source="rule",
        )

    # --- Rule: no seed sensitivity report → skip seed stability ---
    if not normalized.get("seed_sensitivity_report_file"):
        decisions["seed_stability_gate"] = TriageDecision(
            gate="seed_stability_gate", action="skip",
            reason="No seed sensitivity report provided",
            source="rule",
        )

    # --- Rule: no robustness report → skip robustness gate ---
    if not normalized.get("robustness_report_file"):
        if "robustness_gate" not in decisions:
            decisions["robustness_gate"] = TriageDecision(
                gate="robustness_gate", action="skip",
                reason="No robustness report provided",
                source="rule",
            )

    # --- Rule: no feature engineering report → skip FE audit ---
    if not normalized.get("feature_engineering_report_file"):
        decisions["feature_engineering_audit_gate"] = TriageDecision(
            gate="feature_engineering_audit_gate", action="skip",
            reason="No feature engineering report provided",
            source="rule",
        )

    # --- Rule: no model selection report → skip model selection audit ---
    if not normalized.get("model_selection_report_file"):
        decisions["model_selection_audit_gate"] = TriageDecision(
            gate="model_selection_audit_gate", action="skip",
            reason="No model selection report provided",
            source="rule",
        )

    # --- Rule: no prediction trace → skip replay and calibration ---
    if not normalized.get("prediction_trace_file"):
        for g in ("prediction_replay_gate", "calibration_dca_gate"):
            decisions[g] = TriageDecision(
                gate=g, action="skip",
                reason="No prediction trace file provided",
                source="rule",
            )

    # --- Rule: no permutation null metrics → skip permutation test ---
    if not normalized.get("permutation_null_metrics_file"):
        decisions["permutation_significance_gate"] = TriageDecision(
            gate="permutation_significance_gate", action="skip",
            reason="No permutation null metrics file provided",
            source="rule",
        )

    # --- Rule: no CI matrix report → skip CI matrix gate ---
    if not normalized.get("ci_matrix_report_file"):
        decisions["ci_matrix_gate"] = TriageDecision(
            gate="ci_matrix_gate", action="skip",
            reason="No CI matrix report provided",
            source="rule",
        )

    # --- Rule: no model pool file → skip SHAP ---
    if not normalized.get("model_pool_file"):
        if "shap_interpretability_gate" not in decisions:
            decisions["shap_interpretability_gate"] = TriageDecision(
                gate="shap_interpretability_gate", action="skip",
                reason="No model pool file provided",
                source="rule",
            )

    # --- Rule: no distribution report → skip distribution generalization ---
    if not normalized.get("distribution_report_file"):
        if "distribution_generalization_gate" not in decisions:
            decisions["distribution_generalization_gate"] = TriageDecision(
                gate="distribution_generalization_gate", action="skip",
                reason="No distribution report provided",
                source="rule",
            )

    # All remaining gates not yet decided: mark as "run" by default
    for gate_name in GATE_REGISTRY:
        if gate_name not in decisions:
            decisions[gate_name] = TriageDecision(
                gate=gate_name, action="run",
                reason="Input artifacts available",
                source="rule",
            )

    return decisions


# ---------------------------------------------------------------------------
# Layer 2: LLM-based triage (for uncertain cases)
# ---------------------------------------------------------------------------

def _llm_triage(
    uncertain_gates: List[str],
    normalized: Dict[str, Any],
    split_paths: Dict[str, str],
) -> Dict[str, TriageDecision]:
    """Use LLM to decide ambiguous cases. Only called for gates rules can't resolve."""
    if not uncertain_gates:
        return {}

    # Build compact project profile
    profile = {
        "sample_size": normalized.get("context", {}).get("sample_size"),
        "n_features": normalized.get("context", {}).get("n_features"),
        "target": normalized.get("target_name"),
        "task_type": "binary_classification",
        "has_test_split": "test" in split_paths,
        "has_external_cohort": bool(normalized.get("external_cohort_spec")),
        "claim_tier": normalized.get("claim_tier_target"),
        "available_splits": list(split_paths.keys()),
    }

    prompt = f"""You are a medical ML methodology expert. Given this project profile,
decide for each gate whether it should run or be skipped.

Project profile:
{json.dumps(profile, indent=2)}

Gates to evaluate:
{json.dumps(uncertain_gates, indent=2)}

For each gate, output a JSON array of objects:
[{{"gate": "gate_name", "action": "run"|"skip", "reason": "one sentence"}}]

Rules:
- If statistical power is insufficient for a gate's test, skip it
- If the gate's input data type doesn't match the project, skip it
- When in doubt, say "run" (fail-safe)
- Output ONLY the JSON array, nothing else."""

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "text",
                "--max-budget-usd", "0.10",
                "--system-prompt", "You are a triage assistant. Output only valid JSON.",
                prompt,
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return {}

        raw = result.stdout.strip()
        # Extract JSON from response (handle markdown code blocks)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        items = json.loads(raw)

        decisions = {}
        for item in items:
            gate = item.get("gate", "")
            action = item.get("action", "run")
            reason = item.get("reason", "")
            if gate in GATE_REGISTRY and gate not in MANDATORY_GATES:
                decisions[gate] = TriageDecision(
                    gate=gate, action=action,
                    reason=reason, source="llm",
                )
        return decisions
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as exc:
        print(f"[TRIAGE] LLM triage failed ({exc}), falling back to run-all.", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def triage_gates(
    normalized: Dict[str, Any],
    split_paths: Dict[str, str],
    use_llm: bool = False,
    verbose: bool = True,
) -> List[str]:
    """Run triage and return a list of gate names to SKIP.

    Args:
        normalized: The normalized request dict from request_contract_gate.
        split_paths: Dict of available split names to file paths.
        use_llm: Whether to use LLM for ambiguous cases.
        verbose: Print triage summary to stderr.

    Returns:
        List of gate names that should be skipped.
    """
    decisions = _rule_triage(normalized, split_paths)

    # Optionally refine uncertain cases with LLM
    if use_llm:
        uncertain = [g for g, d in decisions.items() if d.action == "uncertain"]
        if uncertain:
            llm_decisions = _llm_triage(uncertain, normalized, split_paths)
            decisions.update(llm_decisions)

    # Collect skip list
    skip_list = sorted(
        g for g, d in decisions.items()
        if d.action == "skip" and g not in MANDATORY_GATES
    )

    if verbose and skip_list:
        total = len(GATE_REGISTRY)
        run_count = total - len(skip_list)
        print(f"\n[TRIAGE] {run_count}/{total} gates will run, {len(skip_list)} skipped:", file=sys.stderr)
        for g in skip_list:
            d = decisions[g]
            tag = f"[{d.source}]"
            print(f"  SKIP {g:45s} {tag:6s} {d.reason}", file=sys.stderr)
        print(file=sys.stderr)

    return skip_list


def triage_report(
    normalized: Dict[str, Any],
    split_paths: Dict[str, str],
    use_llm: bool = False,
) -> Dict[str, Any]:
    """Generate a full triage report as a JSON-serializable dict."""
    decisions = _rule_triage(normalized, split_paths)

    if use_llm:
        uncertain = [g for g, d in decisions.items() if d.action == "uncertain"]
        if uncertain:
            llm_decisions = _llm_triage(uncertain, normalized, split_paths)
            decisions.update(llm_decisions)

    return {
        "total_gates": len(GATE_REGISTRY),
        "gates_to_run": sorted(g for g, d in decisions.items() if d.action == "run"),
        "gates_to_skip": sorted(g for g, d in decisions.items() if d.action == "skip"),
        "mandatory_gates": sorted(MANDATORY_GATES),
        "decisions": {
            g: {"action": d.action, "reason": d.reason, "source": d.source}
            for g, d in sorted(decisions.items())
        },
    }
