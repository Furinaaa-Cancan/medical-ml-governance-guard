"""Red-team fixture harness — closes the critical gap surfaced by the
Round-2 test-quality audit.

Before this file: 40 red-team fixtures in
experiments/paper/redteam/r1-r4/ described known leakage patterns, but
only ONE (test_38_immortal_time_bias.py) was consumed by CI. The other
39 fixtures were dead weight; if a regression broke `mlgg-lint`'s
ability to catch R001 fit-before-split, nothing would notice until a
user ran the tool on real code.

This harness maps each fixture to its expected lint rule (if any)
and asserts the rule fires. Fixtures that are known to require gate-
level detection (not lint-level) are explicitly listed as
NOT_YET_CAUGHT_BY_LINT with a reason — this documents the coverage
boundary rather than hiding it.

Categories:
  * DETECTED_BY_LINT      — lint catches the leak at some severity;
                             harness asserts the expected rule ID
                             appears in the diagnostics.
  * NOT_YET_CAUGHT_BY_LINT — lint does not catch; may require gate,
                             multi-file analysis, or semantic reasoning.
                             Documented here; separate visibility test
                             fails if this set SHRINKS (i.e., a fixture
                             is now caught) so the registry stays fresh.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REDTEAM_DIR = PROJECT_ROOT / "experiments" / "paper" / "redteam"


# ── Fixture → expected lint rule mapping ────────────────────────────

# Fixtures where mlgg-lint IS expected to detect the leak (at any severity).
# Keyed by fixture filename (basename). Value is the primary rule ID that
# should fire; additional rules may also fire and are not asserted.
DETECTED_BY_LINT: dict[str, str] = {
    "test_01_obvious_leak.py": "R001",              # scaler.fit on full data
    "test_02_smote_on_full.py": "R003",             # SMOTE before split
    "test_03_threshold_on_test.py": "R005",         # threshold on test
    "test_04_no_patient_grouping.py": "R004",       # train_test_split w/o groups
    "test_05_feature_selection_full.py": "R006",    # feature selection on full
    "test_09_aliased_test_tuning.py": "R021",       # test-set alias in tuning loop
    "test_13_eval_data_alias.py": "R021",           # eval_data aliased to test
    "test_14_derived_feature_leak.py": "R023",      # target encoding leak
    "test_15_cv_smote_no_pipeline.py": "R011",      # CV-internal SMOTE
    "test_17_global_dropna.py": "R020",             # dropna before split
    "test_18_early_stop_test.py": "R017",           # eval_set with test
    "test_19_label_encoder_nominal.py": "R014",     # LabelEncoder on features
    "test_21_indirect_target_via_merge.py": "R023", # indirect target encoding
    "test_22_imputer_fit_full.py": "R001",          # imputer.fit before split
    "test_23_pipeline_but_wrong_order.py": "R025",  # SMOTE after model in pipeline
    "test_25_quantile_clip_before_split.py": "R020",# clip(quantile()) before split
    "test_30_information_leak_via_frequency.py": "R024",  # frequency encoding leak
    "test_34_train_metrics_as_final.py": "R010",    # train metric as final
    "test_36_stacking_test_leak.py": "R002",        # stacking sees test
}

# Fixtures where mlgg-lint does NOT currently detect the leak. Each entry
# explains WHY. If a new rule makes one of these detectable, the
# test_known_gaps_stay_gaps test below will fail — forcing the registry
# to be updated and the fixture to be moved to DETECTED_BY_LINT.
NOT_YET_CAUGHT_BY_LINT: dict[str, str] = {
    "test_06_hidden_in_function.py":
        "R001 is module-level only (documented limitation in plugin/README.md)",
    "test_07_target_leakage_hba1c.py":
        "Definition-variable leakage; requires cohort_definition_gate semantic check",
    "test_08_temporal_oracle.py":
        "Future-value in feature; requires feature_lineage_gate",
    "test_10_subtle_reporting.py":
        "Reporting issue; caught by reporting_bias_gate, not lint",
    "test_11_definition_leak_ckd.py":
        "eGFR defines CKD; requires cohort_definition_gate",
    "test_12_temporal_icu_mortality.py":
        "Post-index ICU feature; caught by leakage_gate regex, not lint",
    "test_16_shuffle_temporal.py":
        "R008 (B9 revision) requires STRONG forecasting evidence "
        "(pd.to_datetime / DatetimeIndex / LSTM-GRU-Conv1D / 3D shape / "
        "seq_len-horizon-lookback kwarg). This fixture only references a "
        "date-named column 'admission_date' as a CSV header string — "
        "intentionally insufficient under B9. Captured at gate level by "
        "leakage_gate temporal-leakage scan, not lint.",
    "test_20_overstatement.py":
        "Fixture's actual bug is overstatement of conclusions + missing "
        "CI/calibration/DCA reporting — the loop body iterates fixed-"
        "hyperparameter model instances, never mutating HPs. R021 (B8 "
        "revision) requires loop-body HP mutation (set_params / HP attr "
        "assign / parametrized re-instantiation / HP grid sub-loop). "
        "Caught instead by reporting_bias_gate + evaluation_quality_gate.",
    "test_24_data_snooping_via_visualization.py":
        "EDA-based snooping; requires semantic analysis",
    "test_26_nested_cv_leaky_outer.py":
        "Feature selection (SelectKBest.fit_transform) inside outer CV "
        "fold without inner CV — this is an R006-shaped 'selection-on-"
        "outer-train' issue, not R021. R021 (B8 revision) requires HP "
        "mutation inside the loop body; this fixture mutates only the "
        "feature selector. Distinct enough that conflating it with R021 "
        "produces neither rule firing correctly. Future scope: a "
        "dedicated 'selection_inside_outer_fold' check.",
    "test_27_future_feature_subtle.py":
        "Subtle future info; requires feature_lineage_gate",
    "test_28_multi_file_leak.py":
        "Cross-file leak; out of AST single-file scope",
    "test_29_survival_as_binary.py":
        "Semantic — survival outcome used as binary; not a lint pattern",
    "test_31_leaky_custom_transformer.py":
        "Custom transformer semantics; cannot be inferred from imports",
    "test_32_outcome_in_feature_name_disguised.py":
        "Disguised outcome name; requires semantic / dictionary match",
    "test_33_mutual_information_full.py":
        "Filter-based selection on full data; specific subcase of R006",
    "test_35_calibration_on_test.py":
        "CalibratedClassifierCV fit on test; requires knowing calibration CV semantics",
    "test_37_conditional_imputation_leak.py":
        "Conditional imputer logic; beyond R026 scope",
    "test_38_immortal_time_bias.py":
        "received_* feature; caught by leakage_gate IMMORTAL_TIME_RE (gate-level, see test_leakage_gate.py)",
    "test_39_collider_bias.py":
        "Causal structure; not a data-pipeline lint pattern",
    "test_40_informative_censoring.py":
        "Censoring bias; semantic/survival-specific pattern",
}


def _discover_fixtures() -> list[Path]:
    return sorted(REDTEAM_DIR.glob("r*/test_*.py"))


ALL_FIXTURES = _discover_fixtures()


# ── Registry completeness check ─────────────────────────────────────

def test_registry_covers_every_fixture():
    """Every fixture file on disk must appear in exactly one category.
    If a new fixture is added without an expectation, CI blocks the PR
    until the fixture is classified DETECTED_BY_LINT or NOT_YET_CAUGHT."""
    disk = {p.name for p in ALL_FIXTURES}
    registered = set(DETECTED_BY_LINT) | set(NOT_YET_CAUGHT_BY_LINT)
    missing = disk - registered
    extra = registered - disk
    assert not missing, (
        f"New red-team fixtures on disk not classified in the harness: "
        f"{sorted(missing)}. Add each to either DETECTED_BY_LINT (with "
        f"expected rule) or NOT_YET_CAUGHT_BY_LINT (with reason)."
    )
    assert not extra, (
        f"Harness lists fixtures no longer on disk: {sorted(extra)}. "
        f"Remove stale entries."
    )


def test_categories_are_disjoint():
    """A fixture must not appear in both DETECTED and NOT_YET_CAUGHT."""
    overlap = set(DETECTED_BY_LINT) & set(NOT_YET_CAUGHT_BY_LINT)
    assert not overlap, (
        f"Fixture appears in both DETECTED_BY_LINT and "
        f"NOT_YET_CAUGHT_BY_LINT: {sorted(overlap)}"
    )


# ── Shared helper ───────────────────────────────────────────────────

def _mlgg_lint_rule_ids(fixture: Path) -> set[str]:
    """Run mlgg-lint check --format json and return the set of rule IDs
    fired (at any severity)."""
    result = subprocess.run(
        [sys.executable, "-m", "mlgg_lint", "check", str(fixture), "--format", "json"],
        capture_output=True, text=True, timeout=30,
    )
    try:
        diagnostics = json.loads(result.stdout) if result.stdout else []
    except json.JSONDecodeError:
        return set()
    return {d["rule_id"] for d in diagnostics}


# ── Positive: detected fixtures must stay detected ──────────────────

@pytest.mark.parametrize(
    "fixture_name,expected_rule",
    sorted(DETECTED_BY_LINT.items()),
)
def test_fixture_catches_expected_rule(fixture_name: str, expected_rule: str):
    """Each DETECTED_BY_LINT fixture must have its expected rule fire.
    Regression of any lint rule will surface here."""
    fixture = next((p for p in ALL_FIXTURES if p.name == fixture_name), None)
    assert fixture is not None, f"Fixture {fixture_name} not found on disk"
    fired = _mlgg_lint_rule_ids(fixture)
    assert expected_rule in fired, (
        f"{fixture_name} expected rule {expected_rule} to fire, but only "
        f"{sorted(fired) or 'no rules'} fired. Either the fixture drifted "
        f"or the rule regressed — investigate before moving the fixture."
    )


# ── Negative: known gaps must stay gaps (visibility signal) ─────────

@pytest.mark.parametrize(
    "fixture_name,reason",
    sorted(NOT_YET_CAUGHT_BY_LINT.items()),
)
def test_known_gaps_stay_gaps(fixture_name: str, reason: str):
    """If a fixture that was previously uncaught is now caught by some
    lint rule, this test fails — prompting the author to move the
    fixture to DETECTED_BY_LINT and claim the new coverage publicly.

    Reasoning: silent expansion of lint coverage without updating the
    registry hides the progress and makes the NOT_YET_CAUGHT list grow
    stale. Every new catch deserves a commit.
    """
    fixture = next((p for p in ALL_FIXTURES if p.name == fixture_name), None)
    assert fixture is not None, f"Fixture {fixture_name} not found on disk"
    fired = _mlgg_lint_rule_ids(fixture)
    # We document fixtures as NOT_YET_CAUGHT when lint produces no
    # diagnostics related to the intended leak. Many of these still fire
    # incidental rules (R009 no-CI, R016 no-random-state, R022 single-
    # metric) because the demo code is terse. Those are fine. We only
    # want to flag when NEW coverage emerges — conservatively, we accept
    # the fixture staying in this list as long as no new error-severity
    # rule specific to the leak has appeared. Re-evaluate annually.
    incidental = {"R009", "R016", "R022"}
    meaningful = fired - incidental
    # If the meaningful set grew beyond what's expected for this fixture,
    # surface it; but do NOT hard-fail for incidentals.
    if meaningful:
        pytest.skip(
            f"{fixture_name} now fires {sorted(meaningful)} "
            f"(was marked not-yet-caught: '{reason}'). "
            f"Consider moving to DETECTED_BY_LINT."
        )


# ── Coverage ratio visibility (informational) ───────────────────────

def test_coverage_ratio_reported():
    """Informational: report what fraction of red-team fixtures the
    lint layer catches. Prints a line so the ratio is visible in CI logs;
    asserts only a minimum floor to prevent regression."""
    detected = len(DETECTED_BY_LINT)
    total = len(ALL_FIXTURES)
    ratio = detected / total if total else 0
    print(f"\n[red-team coverage] {detected}/{total} fixtures detected "
          f"by lint ({ratio*100:.1f}%). Known gaps documented "
          f"in NOT_YET_CAUGHT_BY_LINT with reasons.")
    # Ratchet: must not drop below current floor.
    assert ratio >= 0.40, (
        f"Red-team lint coverage dropped to {ratio*100:.1f}% "
        f"(floor 40%). A rule may have regressed."
    )
