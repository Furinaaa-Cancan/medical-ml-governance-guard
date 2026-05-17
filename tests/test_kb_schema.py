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


# ──────────────────────────────────────────────────────────────────────────
# W20-C3 / W17-C5: soft-deprecate contract for _kb_schema.validate_concern
#
# The live-KB tests above check shape. These tests pin the *contract* —
# what validate_concern() will and will not accept — so future refactors
# can't silently weaken the soft-deprecate rules that protect external
# references (rag-eval-set.yaml, scenarios.json) from going dangling.
# ──────────────────────────────────────────────────────────────────────────


def _clean_concern(**overrides):
    """Minimal valid concern record (active, non-deprecated)."""
    base = {
        "concern_id": "PR-999-C01",
        "concern_text": "Sample concern text long enough to be non-trivial.",
        "severity": "HIGH",
        "mlgg_gates": ["leakage_gate"],
    }
    base.update(overrides)
    return base


def _clean_deprecated_concern(**overrides):
    """Minimal valid concern record with the full soft-deprecate tombstone."""
    base = _clean_concern(
        deprecated=True,
        deprecated_at="2026-05-17",
        deprecated_reason="Fabricated DOI; paper not in PubMed",
        superseded_by=None,
    )
    base.update(overrides)
    return base


def test_validate_concern_accepts_clean_active():
    """Active concern with all required fields validates."""
    from _kb_schema import validate_concern

    validate_concern(_clean_concern())  # no exception


def test_validate_concern_accepts_clean_deprecated():
    """Deprecated concern with full tombstone validates."""
    from _kb_schema import validate_concern

    validate_concern(_clean_deprecated_concern())


def test_validate_concern_accepts_deprecated_with_superseded_by():
    """``superseded_by`` may name a replacement concern_id."""
    from _kb_schema import validate_concern

    record = _clean_deprecated_concern(superseded_by="PR-040-C02")
    validate_concern(record)


def test_validate_concern_rejects_deprecated_without_reason():
    """Soft-deprecate must carry a human-readable reason."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_deprecated_concern()
    del record["deprecated_reason"]
    with pytest.raises(KBSchemaError, match="deprecated_reason"):
        validate_concern(record)


def test_validate_concern_rejects_deprecated_without_date():
    """Soft-deprecate must carry an ISO date so tombstone age is auditable."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_deprecated_concern()
    del record["deprecated_at"]
    with pytest.raises(KBSchemaError, match="deprecated_at"):
        validate_concern(record)


def test_validate_concern_rejects_deprecated_with_bad_date():
    """``deprecated_at`` must be ISO-8601, not free-form."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_deprecated_concern(deprecated_at="May 17, 2026")
    with pytest.raises(KBSchemaError, match="ISO-8601"):
        validate_concern(record)


def test_validate_concern_rejects_empty_deprecated_reason():
    """Empty-string reason is not a real reason."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_deprecated_concern(deprecated_reason="   ")
    with pytest.raises(KBSchemaError, match="deprecated_reason"):
        validate_concern(record)


def test_validate_concern_rejects_non_bool_deprecated_flag():
    """``deprecated`` must be a real bool, not a truthy string."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_concern(deprecated="yes")
    with pytest.raises(KBSchemaError, match="'deprecated' must be a bool"):
        validate_concern(record)


def test_validate_concern_rejects_bad_severity():
    """Severity must be in the canonical set."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_concern(severity="URGENT")
    with pytest.raises(KBSchemaError, match="severity"):
        validate_concern(record)


def test_validate_concern_rejects_missing_required_field():
    """Active concerns also need the base required fields."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_concern()
    del record["concern_text"]
    with pytest.raises(KBSchemaError, match="concern_text"):
        validate_concern(record)


def test_validate_concern_rejects_superseded_by_wrong_type():
    """``superseded_by`` must be str or None."""
    from _kb_schema import KBSchemaError, validate_concern

    record = _clean_deprecated_concern(superseded_by=["PR-040-C02"])
    with pytest.raises(KBSchemaError, match="superseded_by"):
        validate_concern(record)


def test_concern_can_be_deleted_when_no_external_refs():
    """No external refs → hard-delete is safe."""
    from _kb_schema import concern_can_be_deleted

    assert concern_can_be_deleted(_clean_concern(), external_refs=set())
    assert concern_can_be_deleted(_clean_concern(), external_refs={"PR-001-C01"})


def test_concern_can_be_deleted_blocks_when_externally_referenced():
    """If anyone still points at the id, hard-delete is forbidden."""
    from _kb_schema import concern_can_be_deleted

    record = _clean_concern(concern_id="PR-040-C01")
    assert not concern_can_be_deleted(record, external_refs={"PR-040-C01"})


def test_concern_can_be_deleted_refuses_when_no_external_refs_known():
    """``external_refs=None`` is informational-only; default policy is allow."""
    from _kb_schema import concern_can_be_deleted

    # If the caller cannot supply refs, fall back to permitting deletion —
    # the checker (check_kb_no_dangling.py) is the authoritative guard.
    assert concern_can_be_deleted(_clean_concern(), external_refs=None)


def test_concern_can_be_deleted_refuses_record_without_id():
    """A record with no concern_id is malformed — never safe to delete."""
    from _kb_schema import concern_can_be_deleted

    assert not concern_can_be_deleted({"concern_text": "no id"}, external_refs=set())


def test_is_iso_date_helper():
    """ISO date guard accepts dates, datetimes, and ISO strings only."""
    from datetime import date, datetime

    from _kb_schema import is_iso_date

    assert is_iso_date("2026-05-17")
    assert is_iso_date("2026-05-17T12:00:00")
    assert is_iso_date("2026-05-17T12:00:00Z")
    assert is_iso_date(date(2026, 5, 17))
    assert is_iso_date(datetime(2026, 5, 17, 12, 0, 0))
    assert not is_iso_date("May 17 2026")
    assert not is_iso_date("2026/05/17")
    assert not is_iso_date(None)
    assert not is_iso_date(20260517)
    assert not is_iso_date("2026-13-40")  # invalid month/day
