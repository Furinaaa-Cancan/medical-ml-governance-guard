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

from scripts.review.backfill_peer_review_gates import (
    CATEGORY_TO_GATES,
    TAG_OVERLAYS,
    _derive_gates,
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
