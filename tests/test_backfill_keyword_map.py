"""Tests for the keyword map fix in backfill_peer_review_gates.py (H2 / G2 finding).

Background
----------
G2 root-cause analysis (2026-05-17) discovered that the keyword
``"reproducibility"`` in ``scripts/review/backfill_peer_review_gates.py``
mapped directly to ``seed_stability_gate`` in two places:

  * ``CATEGORY_TO_GATES["reproducibility"]`` (line ~39)
  * ``TAG_OVERLAYS`` entry ``("reproducibility", [...])`` (line ~265)

Because TAG_OVERLAYS uses substring matching against the concatenated tag
text, any tag containing ``reproducibility`` (e.g. ``architecture_reproducibility``,
``code_reproducibility``, ``irreproducibility``) would also pull in
``seed_stability_gate``. This caused 38+ code-/data-availability concerns to be
wrongly tagged with seed_stability_gate — masquerading as the F4
"prediction_replay vs seed_stability overlap" issue when it was actually a
backfill artifact.

This test file pins the fixed semantics:
  * The bare ``"reproducibility"`` token no longer maps to seed_stability_gate.
  * Seed-specific tokens (``seed``, ``random_seed``, ``seed_variance``,
    ``random_state``) still map to seed_stability_gate.
  * Code/data availability tokens route to publication_gate /
    execution_attestation_gate, NOT seed_stability_gate.
"""
from __future__ import annotations

import pytest

from scripts.review.backfill_peer_review_gates import (
    CATEGORY_TO_GATES,
    TAG_OVERLAYS,
    _derive_gates,
    _tag_matches_needle,
)


def _overlay_map() -> dict[str, list[str]]:
    """Flatten the TAG_OVERLAYS list-of-tuples into a dict for lookup tests.

    TAG_OVERLAYS preserves insertion order and may contain duplicate needles
    (the last one wins, in the sense that the rule-table iterates all entries
    and de-dupes the final gate list). For pinning purposes we collapse
    duplicates by union-of-gates, which is the strictest test.
    """
    result: dict[str, list[str]] = {}
    for needle, gates in TAG_OVERLAYS:
        merged = list(dict.fromkeys((result.get(needle) or []) + list(gates)))
        result[needle] = merged
    return result


# -------- Category-level pinning --------

def test_reproducibility_category_no_longer_seeds_seed_stability_gate():
    """G2 bug: CATEGORY_TO_GATES['reproducibility'] used to include
    seed_stability_gate, which auto-tagged every concern in that category
    with seed_stability_gate regardless of whether the concern was about
    seed variance or code availability."""
    gates = CATEGORY_TO_GATES.get("reproducibility", [])
    assert gates, "reproducibility category must map to at least one gate"
    assert "seed_stability_gate" not in gates, (
        f"CATEGORY_TO_GATES['reproducibility'] still maps to seed_stability_gate: {gates}. "
        "Seed-variance signals should come from narrow tag overlays, not the bare category."
    )


# -------- TAG_OVERLAYS pinning --------

def test_reproducibility_keyword_not_overmapped_to_seed_stability():
    """G2 bug: the bare 'reproducibility' tag-overlay needle mapped to
    seed_stability_gate AND was a substring of many specific tags
    (architecture_reproducibility, code_reproducibility, ...), spreading
    the seed_stability tag everywhere."""
    overlays = _overlay_map()
    assert "reproducibility" in overlays, (
        "Expected a TAG_OVERLAYS entry for the bare 'reproducibility' needle."
    )
    gates = overlays["reproducibility"]
    assert "seed_stability_gate" not in gates, (
        f"'reproducibility' overlay still includes seed_stability_gate: {gates}"
    )


def test_seed_specific_keywords_keep_seed_stability_gate():
    """seed_variance / seed_stability / random_seed / seed / random_state
    must still tag seed_stability_gate — these are the legitimate seed-
    variance signals after the split."""
    overlays = _overlay_map()
    seed_tokens = [
        "seed",
        "random_seed",
        "seed_variance",
        "seed_stability",
        "random_state",
    ]
    missing = []
    for tok in seed_tokens:
        if tok not in overlays:
            missing.append(f"{tok} (not in TAG_OVERLAYS at all)")
            continue
        if "seed_stability_gate" not in overlays[tok]:
            missing.append(f"{tok} -> {overlays[tok]}")
    assert not missing, (
        f"These seed-variance tokens no longer route to seed_stability_gate: {missing}"
    )


def test_code_availability_keywords_map_to_appropriate_gate():
    """code_availability / data_availability must route to
    publication_gate or execution_attestation_gate (or both), NEVER to
    seed_stability_gate."""
    overlays = _overlay_map()
    avail_tokens = ["code_availability", "data_availability"]
    for tok in avail_tokens:
        assert tok in overlays, f"Missing tag overlay for '{tok}'"
        gates = overlays[tok]
        assert "seed_stability_gate" not in gates, (
            f"'{tok}' wrongly maps to seed_stability_gate: {gates}"
        )
        assert (
            "publication_gate" in gates or "execution_attestation_gate" in gates
        ), (
            f"'{tok}' should map to publication_gate or execution_attestation_gate; got {gates}"
        )


# -------- End-to-end derivation behavior --------

def test_derive_code_availability_concern_does_not_get_seed_stability():
    """A reproducibility-category concern whose tags signal code unavailability
    must NOT receive seed_stability_gate.

    Pre-fix this scenario triggered seed_stability_gate twice (once via the
    category, once via the substring match on 'reproducibility' inside
    'code_reproducibility')."""
    gates = _derive_gates(
        "reproducibility",
        ["code_unavailable", "broken_github", "code_reproducibility"],
    )
    assert "seed_stability_gate" not in gates, (
        f"Code-availability concern derived seed_stability_gate: {gates}"
    )
    assert "execution_attestation_gate" in gates, (
        f"Expected execution_attestation_gate in derived gates: {gates}"
    )


def test_derive_seed_variance_concern_still_gets_seed_stability():
    """A reproducibility-category concern with a genuine seed-variance tag
    must still receive seed_stability_gate via the narrow tag overlay."""
    gates = _derive_gates(
        "reproducibility",
        ["seed_variance", "random_seed"],
    )
    assert "seed_stability_gate" in gates, (
        f"Seed-variance concern lost seed_stability_gate after the fix: {gates}"
    )


def test_derive_bare_reproducibility_tag_skips_seed_stability():
    """Substring trap regression: a concern whose only reproducibility-ish
    tag is e.g. 'architecture_reproducibility' must not pull in
    seed_stability_gate (this was the original G2 substring bug)."""
    gates = _derive_gates(
        "reproducibility",
        ["architecture_reproducibility"],
    )
    assert "seed_stability_gate" not in gates, (
        f"'architecture_reproducibility' tag still pulls seed_stability_gate: {gates}"
    )


# ====================================================================
# H15 — TAG_OVERLAYS substring → whole-token matching refactor
# ====================================================================
# Background
# ----------
# The fix in commit 342e70b ("split 'reproducibility' keyword") patched one
# instance of a wider class bug H2 had warned about: TAG_OVERLAYS used
# substring matching against the concatenated tag text, so any needle that
# happened to be a substring of an unrelated tag silently over-triggered.
# Examples discovered by auditing the KB on 2026-05-17:
#
#   * ``"idi"``  matched ``bidirectional_rnn_leakage``, ``label_validity``,
#                ``confounding_by_comorbidity``, ``enrichment_validity``, ...
#   * ``"ood"``  matched ``likelihood_ratios_missing``,
#                ``blood_culture_proxy``, ``blood_tests_unhelpful``, ...
#   * ``"nri"``  matched ``enrichment_validity``, ``enriched_population``
#   * ``"dca"``  matched ``gradcam``, ``gradcam_interpretation``
#   * ``"missing_ci"`` matched ``missing_citations``
#
# Fix: derive a tag-aware whole-token matcher (`_tag_matches_needle`) and
# route `_derive_gates` through it. The legitimate stem/plural matches the
# old substring matcher caught (e.g. ``benchmark`` → ``benchmarking_*``,
# ``overclaim`` → ``overclaimed_*``) are restored by adding explicit
# inflected needles to TAG_OVERLAYS.


@pytest.mark.parametrize(
    "tag,needle,should_match",
    [
        # H2 canonical example: shap must not match shapefile
        ("shap_value_missing", "shap", True),
        ("shapefile", "shap", False),
        # ci must not match civic / citation tokens
        ("missing_ci", "ci_matrix", False),       # multi-token: only "ci" present, not "matrix"
        ("ci_methodology", "ci_methodology", True),
        ("ci_matrix_required", "ci_matrix", True),
        ("civic_engagement", "ci", False),         # token "ci" is NOT a token of "civic_engagement"
        ("missing_citations", "ci", False),        # "citations" is its own token, not "ci"
        # seed must not match seeding (different token)
        ("random_seed", "seed", True),
        ("seed", "seed", True),
        ("seeding_strategy", "seed", False),
        # reproducibility: exact / token match works
        ("reproducibility", "reproducibility", True),
        ("reproducibility_unclear", "reproducibility", True),
        ("architecture_reproducibility", "reproducibility", True),
        # idi class-of-failure: must NOT match longer words containing 'idi'
        ("bidirectional_rnn_leakage", "idi", False),
        ("label_validity", "idi", False),
        ("confounding_by_comorbidity", "idi", False),
        ("idi", "idi", True),
        # ood / nri analogues
        ("likelihood_ratios_missing", "ood", False),
        ("ood", "ood", True),
        ("enrichment_validity", "nri", False),
        ("nri", "nri", True),
        # dca must not match gradcam
        ("gradcam", "dca", False),
        ("dca", "dca", True),
        ("decision_curve_analysis_dca", "dca", True),
        # Multi-token needle: ALL needle tokens must appear in tag
        ("data_leakage_via_imputation", "data_leakage_via_imputation", True),
        ("data_leakage", "data_leakage_via_imputation", False),  # missing "via", "imputation"
        # Inflectional compensators (added in same refactor) — these are the
        # legitimate substring matches the old matcher caught that we
        # preserve by spelling out the inflected forms.
        ("unfair_benchmarking", "benchmarking", True),
        ("benchmarking_missing", "benchmarking", True),
        ("overclaimed_improvement", "overclaimed", True),
        ("missing_confidence_intervals", "confidence_intervals", True),
        ("default_hyperparameters", "hyperparameters", True),
        ("biomarker_thresholding", "thresholding", True),
        ("feature_thresholds_unavailable", "thresholds", True),
        ("recalibration_needed", "recalibration", True),
        ("reporting_guidelines", "reporting_guidelines", True),
        ("cherry_picking_risk", "cherry_picking", True),
    ],
)
def test_whole_token_matching_no_false_positives(tag, needle, should_match):
    """H15: TAG_OVERLAYS lookups should match on whole tokens, not substrings.

    Each parametrised case pins one behaviour: needles must match tags only
    when every needle token appears as a complete tag token. Negative cases
    cover the historical substring false positives (shap/shapefile,
    idi/bidirectional, ci/citations, ood/likelihood, dca/gradcam, ...);
    positive cases cover the legitimate stem matches we preserved by adding
    explicit inflected needles (benchmarking, overclaimed, hyperparameters,
    ...).
    """
    actual = _tag_matches_needle(tag, needle)
    assert actual == should_match, (
        f"needle={needle!r} tag={tag!r}: expected match={should_match}, got {actual}"
    )


def test_whole_token_no_shap_shapefile_collision():
    """H2 specific example: 'shap' must not pull in shap_interpretability_gate
    for a concern whose only shap-ish tag is the geographic 'shapefile'."""
    # interpretability category default doesn't apply here — use a neutral
    # category so we test the overlay in isolation.
    derived = _derive_gates(
        "reporting",
        ["shapefile", "geographic_file_format"],
    )
    assert "shap_interpretability_gate" not in derived, (
        f"'shapefile' wrongly triggered shap_interpretability_gate: {derived}"
    )


def test_whole_token_idi_no_validity_collision():
    """H15 audit finding: the old matcher routed every '*_validity' /
    'b**idi**rectional' tag through the NRI/IDI rule. Whole-token kills it."""
    derived = _derive_gates(
        "evaluation_metrics",
        ["bidirectional_rnn_leakage", "label_validity", "comorbidity_data"],
    )
    # idi rule maps to clinical_metrics_gate + calibration_dca_gate.
    # None of the three tags are about reclassification metrics, so neither
    # of those gates should be added by the idi overlay.
    # (clinical_metrics_gate / calibration_dca_gate could still come in via
    # other overlays — assert specifically that they're absent when the only
    # routes would have been the false-positive idi/nri substring matches.)
    assert "clinical_metrics_gate" not in derived, (
        f"idi/nri substring trap re-introduced: {derived}"
    )


def test_whole_token_missing_ci_keeps_real_match():
    """The legitimate 'missing_ci' tag must still route to ci_matrix_gate
    via the existing ('missing_ci', ...) overlay."""
    derived = _derive_gates(
        "evaluation_metrics",
        ["missing_ci", "auroc_only"],
    )
    assert "ci_matrix_gate" in derived, (
        f"Legitimate 'missing_ci' tag lost its ci_matrix_gate routing: {derived}"
    )


def test_whole_token_benchmark_inflections_preserved():
    """Inflectional compensator: 'benchmarking_*' tags must still route to
    model_selection_audit_gate (previously caught by substring match on
    needle 'benchmark', now caught explicitly by needle 'benchmarking')."""
    for tag in (
        "unfair_benchmarking",
        "limited_benchmarking",
        "benchmarking_missing",
        "model_benchmarking_context",
    ):
        derived = _derive_gates("reporting", [tag])
        assert "model_selection_audit_gate" in derived, (
            f"'{tag}' lost model_selection_audit_gate after refactor: {derived}"
        )


def test_whole_token_overclaim_inflections_preserved():
    """Inflectional compensator: 'overclaimed_*' tags (verb form) must still
    route to reporting_bias_gate."""
    for tag in (
        "overclaimed",
        "overclaimed_improvement",
        "overclaimed_clinical_utility",
        "small_subgroup_overclaimed",
    ):
        derived = _derive_gates("reporting", [tag])
        assert "reporting_bias_gate" in derived, (
            f"'{tag}' lost reporting_bias_gate after refactor: {derived}"
        )
