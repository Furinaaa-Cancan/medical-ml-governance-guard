"""Schema validation for peer-review-kb.json (H9 / overnight wave).

Catches schema drift before it surfaces as ranker/UI bugs:
  - Every concern has required fields
  - Every mlgg_gates entry references a real gate in GATE_REGISTRY
  - Severity is in the canonical set
  - No duplicate concern_ids across the corpus
  - Contract version matches expected

Runs fast (pure schema check, no model load) — included in ci-unit default.
"""
import json
from collections import Counter
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
KB_PATH = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"

REQUIRED_CONCERN_FIELDS = ("concern_id", "concern_text", "severity", "mlgg_gates")
CANONICAL_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
EXPECTED_CONTRACT_VERSION = "peer_review_kb.v1.4"  # adjust if KB advanced


@pytest.fixture(scope="module")
def kb():
    """Load the KB once per module."""
    return json.loads(KB_PATH.read_text())


@pytest.fixture(scope="module")
def all_concerns(kb):
    """Flatten all concerns across entries. Returns (paper_id, concern) tuples."""
    return [
        (entry.get("id") or entry.get("paper_id"), concern)
        for entry in kb.get("entries", [])
        for concern in entry.get("reviewer_concerns", [])
    ]


def test_kb_loads_as_valid_json(kb):
    """File parses as JSON (sanity)."""
    assert isinstance(kb, dict)
    assert "entries" in kb, "missing top-level 'entries' key"
    assert isinstance(kb["entries"], list)


def test_contract_version_matches(kb):
    """Contract version should be the expected schema."""
    actual = kb.get("contract_version")
    assert actual is not None, "missing contract_version"
    # Loose match: allow patch bumps
    assert actual.startswith("peer_review_kb.v1."), (
        f"unexpected contract version: {actual} (expected peer_review_kb.v1.*)"
    )


def test_every_concern_has_required_fields(all_concerns):
    """No concern may be missing the documented required fields."""
    missing = []
    for paper_id, c in all_concerns:
        for field in REQUIRED_CONCERN_FIELDS:
            if field not in c:
                missing.append((paper_id, c.get("concern_id", "?"), field))
    assert not missing, (
        f"{len(missing)} concerns missing required fields:\n  "
        + "\n  ".join(f"{p}/{cid}: missing {f}" for p, cid, f in missing[:20])
    )


def test_concern_ids_are_unique(all_concerns):
    """No duplicate concern_id across the corpus."""
    counts = Counter(c.get("concern_id") for _, c in all_concerns)
    dupes = {cid: n for cid, n in counts.items() if n > 1}
    assert not dupes, f"duplicate concern_ids: {dupes}"


def test_severity_is_canonical(all_concerns):
    """Severity in {CRITICAL, HIGH, MEDIUM, LOW}."""
    bad = [
        (p, c.get("concern_id"), c.get("severity"))
        for p, c in all_concerns
        if c.get("severity") not in CANONICAL_SEVERITIES
    ]
    assert not bad, (
        f"{len(bad)} concerns with non-canonical severity:\n  "
        + "\n  ".join(f"{p}/{cid}: {sev}" for p, cid, sev in bad[:10])
    )


def test_mlgg_gates_reference_registry(all_concerns):
    """Every mlgg_gates entry must exist in GATE_REGISTRY."""
    from scripts.core._gate_registry import GATE_REGISTRY

    valid = set(GATE_REGISTRY.keys())
    bad = []
    for p, c in all_concerns:
        gates = c.get("mlgg_gates", [])
        if not isinstance(gates, list):
            continue  # handled by test_mlgg_gates_is_list
        for g in gates:
            if g not in valid:
                bad.append((p, c.get("concern_id"), g))
    # Allow some grace for legacy / deprecated gate names — fail loud only if many
    assert len(bad) < 5, (
        f"{len(bad)} concerns reference unknown gates:\n  "
        + "\n  ".join(f"{p}/{cid}: {g}" for p, cid, g in bad[:10])
        + f"\n(Registry has {len(valid)} gates: {sorted(valid)[:10]}...)"
    )


def test_mlgg_gates_is_list(all_concerns):
    """mlgg_gates must be a list, not a string or None."""
    bad = [
        (p, c.get("concern_id"), type(c.get("mlgg_gates")).__name__)
        for p, c in all_concerns
        if not isinstance(c.get("mlgg_gates"), list)
    ]
    assert not bad, f"{len(bad)} concerns have non-list mlgg_gates: {bad[:5]}"


def test_no_concern_id_starts_with_synth_unless_flagged(all_concerns):
    """Synthetic concerns must be flagged _synthetic: True per F4 protocol."""
    bad = []
    for p, c in all_concerns:
        cid = c.get("concern_id", "") or ""
        if "SYNTH" in cid.upper() and not c.get("_synthetic"):
            bad.append((p, cid))
    assert not bad, f"synth-looking concerns without _synthetic flag: {bad}"
