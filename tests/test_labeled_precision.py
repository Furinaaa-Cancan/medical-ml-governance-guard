"""Smoke tests for the LLM-assisted preliminary Precision@5 baseline set.

The labeled set (`references/retrieval_eval/labeled_precision_at_5.json`,
Wave 8 / W2) addresses the P7 caveat in the eval roadmap: prior RAG eval
metrics use proxy tag-overlap signals, while this set uses per-hit
relevance judgments — albeit LLM-produced (Claude Opus 4.7 self-eval),
not independent human adjudication. See the JSON's
``labeling_protocol.circularity_warning`` for usage constraints (notably:
absolute P@5 numbers from this file are NOT suitable for external claims
without independent human re-labeling).

These tests check:

1. **Loads + schema**: the file parses, contains >=18 query entries
   (target is 20; the >=18 slack absorbs a future deprecation of 1-2
   queries without forcing test edits), and each entry has the expected
   keys.

2. **P@5 internal consistency**: each entry's recorded ``p_at_5`` matches
   the recomputed ``sum(relevant=true) / 5`` value (off-by-rounding
   tolerance 0.01). This catches manual-labeling typos.

3. **Aggregate metric computes**: mean labeled P@5 across all queries is a
   valid probability in [0, 1]. The current value is printed so the test
   log doubles as a longitudinal record (parseable by future eval tooling).

The tests deliberately do NOT call rag_query — that would couple the
ground-truth file to the live retrieval stack and defeat its purpose as a
stable longitudinal anchor. Re-labeling after a retrieval change should
produce a new file (e.g. ``labeled_precision_at_5_v2.json``) so drift is
auditable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LABELED_PATH = (
    PROJECT_ROOT / "references" / "retrieval_eval" / "labeled_precision_at_5.json"
)


@pytest.fixture(scope="module")
def labeled_data() -> dict:
    """Load the labeled P@5 set once per test module."""
    assert LABELED_PATH.exists(), (
        f"Expected labeled set at {LABELED_PATH}; "
        "regenerate via Wave-8 W2 labeling protocol if missing."
    )
    return json.loads(LABELED_PATH.read_text(encoding="utf-8"))


def test_labeled_precision_set_loads(labeled_data: dict) -> None:
    """Schema smoke test: file parses, has expected top-level keys + entries."""
    assert "schema_version" in labeled_data
    assert "labeled_queries" in labeled_data

    queries = labeled_data["labeled_queries"]
    # Post-W9-A2: 36 entries (L01-L36). W8-W2 baseline was 20 entries; W9-A2
    # added 16 in-scope queries (L21-L36) to triple coverage on the 8 highest-
    # stakes sub-dimensions (those touching MLGG non-negotiable rules).
    # >=34 floor absorbs minor future deprecations without forcing test edits.
    assert len(queries) >= 34, (
        f"Expected >=34 labeled queries (post-W9-A2 expansion); found "
        f"{len(queries)}. If a query was retired, document it in the file's "
        "`description` field and consider lowering this floor in a separate "
        "commit."
    )

    for q in queries:
        assert "id" in q, f"Missing 'id' in: {q}"
        assert "query" in q, f"Missing 'query' in {q.get('id')}"
        assert "top5_at_label_time" in q, (
            f"Missing 'top5_at_label_time' in {q.get('id')}"
        )
        assert "p_at_5" in q, f"Missing 'p_at_5' in {q.get('id')}"

        hits = q["top5_at_label_time"]
        assert isinstance(hits, list), f"hits not a list in {q.get('id')}"
        # Top-5 by definition; off-scope probes may return 0 hits.
        assert len(hits) <= 5, (
            f"{q['id']}: top5_at_label_time has {len(hits)} entries (>5)"
        )

        for hit in hits:
            assert "concern_id" in hit, (
                f"{q['id']}: hit missing 'concern_id': {hit}"
            )
            assert "relevant" in hit, (
                f"{q['id']}: hit missing 'relevant': {hit}"
            )
            assert isinstance(hit["relevant"], bool), (
                f"{q['id']}: 'relevant' must be bool, got {type(hit['relevant'])}"
            )

        # P@5 internal consistency: catches manual-labeling typos
        rel_count = sum(1 for h in hits if h.get("relevant"))
        expected_p5 = rel_count / 5
        assert abs(q["p_at_5"] - expected_p5) < 0.01, (
            f"{q['id']}: recorded p_at_5={q['p_at_5']} but "
            f"sum(relevant=true)/5 = {expected_p5}"
        )


def test_aggregate_precision_at_5_metric_computes(labeled_data: dict) -> None:
    """Aggregate mean P@5 is a valid probability in [0, 1].

    Prints the current value to the test log so longitudinal drift can be
    grepped from CI artifacts without re-running the eval suite.
    """
    queries = labeled_data["labeled_queries"]
    mean_p5 = sum(q["p_at_5"] for q in queries) / len(queries)
    print(f"current mean labeled P@5: {mean_p5:.3f}")

    # In-scope mean (excluding off-scope probes pinned at 0.0) is a more
    # actionable signal for retrieval quality.
    in_scope = [q for q in queries if q.get("dimension") != "off_scope_probe"]
    if in_scope:
        mean_in_scope = sum(q["p_at_5"] for q in in_scope) / len(in_scope)
        print(
            f"current mean labeled P@5 (in-scope only, n={len(in_scope)}): "
            f"{mean_in_scope:.3f}"
        )

    assert 0.0 <= mean_p5 <= 1.0


def test_high_stakes_dimensions_have_at_least_two_queries(
    labeled_data: dict,
) -> None:
    """The 8 highest-stakes sub-dimensions must have >=2 queries each.

    W9-A2 (2026-05-17) tripled coverage on the 8 sub-dimensions that touch
    MLGG's non-negotiable rules (S01, F01, F02, P01, M01, E01, E02). For
    publication-grade per-dimension P@5 claims, each of these requires
    multiple labeled queries — a single-query dimension can only support
    aggregate claims (W8-W2 caveat).

    The other 10 sub-dimensions (evaluation_metric_choice, ...
    covariate_shift_generalization) remain at 1 query each and continue to
    support aggregate-only claims; that floor is not enforced here so it
    can be lifted incrementally without test churn.
    """
    from collections import Counter

    high_stakes_dims = {
        "leakage_split_hygiene",
        "leakage_definition_variable",
        "leakage_temporal_future",
        "preprocessing_split_leakage",
        "split_temporal_validation",
        "model_selection_tuning_leakage",
        "evaluation_uncertainty_quantification",
        "evaluation_calibration",
    }
    dim_counts: Counter[str] = Counter()
    for q in labeled_data["labeled_queries"]:
        dim_counts[q.get("dimension", "")] += 1

    short_dims = [
        d for d in high_stakes_dims if dim_counts.get(d, 0) < 2
    ]
    assert not short_dims, (
        "High-stakes sub-dimensions with <2 labeled queries (post-W9-A2 "
        f"floor): {short_dims}. Per-dim P@5 claims for these dims need "
        "multiple queries to be statistically defensible — extend the "
        "labeled set rather than weakening this assertion."
    )


def test_off_scope_probes_return_zero(labeled_data: dict) -> None:
    """Off-scope probes (woodworking, music) must score P@5 = 0.

    If a future retrieval change makes one of these score non-zero, it is
    almost certainly a false-positive regression (the gate filter for
    free_text_probe is supposed to suppress unrelated content), and this
    test will fail to flag it for human review.
    """
    queries = labeled_data["labeled_queries"]
    off_scope = [q for q in queries if q.get("dimension") == "off_scope_probe"]
    assert len(off_scope) >= 2, (
        "Expected >=2 off-scope probes (e.g. woodworking + music) to "
        "anchor the false-positive floor; found "
        f"{len(off_scope)}."
    )
    for q in off_scope:
        assert q["p_at_5"] == 0.0, (
            f"{q['id']}: off-scope probe scored P@5={q['p_at_5']} (!= 0). "
            "Either the labeling is wrong or retrieval started returning "
            "spurious hits on unrelated queries — investigate before "
            "loosening this guard."
        )
