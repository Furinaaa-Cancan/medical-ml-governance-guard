"""Lock the GLM7 integration-benchmark N=1 record (Tier B+, first cross-layer case).

These tests pin the *reproducible* layers (deterministic disease-KB check + RAG
retrieval) and the scoring, so a regression in the gate, the disease-KB, or the
retrieval path that changes this real-paper result fails CI. The LLM layer is
frozen and not re-run here. The metric semantics asserted below are the honest,
post-adversarial-review ones (self-consistency / self-attested, separate
reproducible verdict) — not blind recall.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_DIR = REPO_ROOT / "references" / "benchmark" / "integration" / "glm7_n1"
RUNNER = REPO_ROOT / "scripts" / "rag" / "evals" / "run_glm7_n1.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_glm7_n1", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def computed():
    return _load_runner().compute_record()


def test_record_reproduces_frozen(computed):
    """The runner recomputes deterministic + RAG layers + metrics identically to record.json."""
    frozen = json.loads((RECORD_DIR / "record.json").read_text(encoding="utf-8"))
    assert computed["layers"]["deterministic"] == frozen["layers"]["deterministic"]
    assert computed["layers"]["rag"] == frozen["layers"]["rag"]
    assert computed["metrics"] == frozen["metrics"]


def test_deterministic_floor_binds(computed):
    """The disease-KB guard deterministically FAILS the paper from the reproducible layers alone."""
    det = computed["layers"]["deterministic"]
    assert det["verdict"] == "fail"
    assert det["binding"] is True
    assert computed["metrics"]["reproducible_verdict"] == "fail"
    caught = set(det["column_level"]["caught"])
    assert {"HbA1c", "Insulin", "BUN"} <= caught  # the real, reproducible hits


def test_kb_synonym_gap_closed(computed):
    """Closed loop: the FBG/Cr abbreviation gap this N=1 first surfaced at disease-KB
    v1.1 is fixed in v1.2 (added 'fbg'/'cr' synonyms). The guard now catches all five
    definition columns, with no open synonym-gap follow-up — this is the regression
    that proves the fix and that the disease-KB the record runs against is the fixed one."""
    det = computed["layers"]["deterministic"]["column_level"]
    assert det["missed"] == []
    assert det["recall"] == "5/5"
    assert set(det["caught"]) == {"HbA1c", "FBG", "Insulin", "BUN", "Cr"}
    assert not [f for f in computed["followups"] if f["type"] == "disease_kb_synonym_gap"]
    assert computed["provenance"]["disease_kb_version"] == "1.2"


def test_metric_semantics_are_honest(computed):
    """RAG is labeled self-consistency (not recall); LLM is labeled self-attested; the
    reproducible-only union excludes the frozen LLM contribution (GT-4)."""
    layers = computed["layers"]
    assert layers["rag"]["metric_kind"] == "retrieval_self_consistency"
    assert layers["llm"]["metric_kind"] == "self_attested"
    assert layers["llm"]["reproducible"] is False
    m = computed["metrics"]
    # Without the frozen LLM, the reproducible layers reach only 5/6; GT-4 is LLM-only.
    assert m["union_reproducible_layers_only"] == "5/6"
    assert m["union_any_layer"] == "6/6"
    assert m["asymmetry"]["property"] == "structural"


def test_off_prediction_hit_is_flagged_not_hidden(computed):
    """GT-6 is caught by RAG though RAG was not in its pre-registered expected_layers;
    the runner surfaces this rather than silently inflating recall."""
    assert computed["metrics"]["off_prediction_hits"] == ["GT-6"]
    gt6 = next(a for a in computed["attribution"] if a["gt_id"] == "GT-6")
    assert "rag" in gt6["off_prediction_layers"]


def test_glm7_not_in_kb_so_lopo_is_clean(computed):
    """Validity: GLM7 is out-of-KB, so RAG cannot self-leak its own concerns."""
    assert computed["provenance"]["in_peer_review_kb"] is False


def test_rag_runner_threads_declared_lopo_exclusion(monkeypatch):
    """The provenance field must match the actual BM25 call shape."""
    mod = _load_runner()
    calls = []

    def fake_retrieve_for_failure(gate, issue_codes, limit=5, **kwargs):
        calls.append({
            "gate": gate,
            "issue_codes": issue_codes,
            "limit": limit,
            **kwargs,
        })
        return [{"concern_id": "PR-OTHER-C01"}]

    import scripts.rag.retrieval.bm25 as bm25

    monkeypatch.setattr(bm25, "retrieve_for_failure", fake_retrieve_for_failure)
    mod._run_rag(
        [
            {
                "label": "definition_leakage",
                "gate": "definition_variable_guard",
                "codes": ["hand_authored_code"],
                "source": "gate_run",
            }
        ],
        {"definition_variable_guard": ["definition_variable_leakage"]},
    )

    assert calls == [
        {
            "gate": "definition_variable_guard",
            "issue_codes": ["definition_variable_leakage"],
            "limit": 4,
            "excluded_paper_ids": [mod.GLM7_KB_ID],
        }
    ]


def test_failure_class_provenance_is_gate_derived_where_a_gate_runs(computed):
    """The one gate that runs on a paper (definition_variable_guard) feeds the
    definition_leakage RAG query from its LIVE emitted codes (gate-derived, not
    hand-authored); the three design concerns have no runnable gate on a paper and
    are honestly labeled 'analysis'."""
    prov = computed["layers"]["rag"]["failure_class_provenance"]
    assert prov["definition_leakage"]["source"] == "gate_run"
    assert prov["definition_leakage"]["codes_used"] == ["definition_variable_leakage"]
    assert computed["layers"]["rag"]["gate_derived_classes"] == ["definition_leakage"]
    for label in ("cross_sectional", "selection_leakage", "incomplete_eval"):
        assert prov[label]["source"] == "analysis"


def test_blind_adjudication_upgrades_soft_numbers(computed):
    """The blind-to-labels adjudication (control C3) validated the LLM self-attestation
    (6/6, 3-panel unanimous) and exposed the real RAG precision (8/16) that the
    self-consistency '5/6' masked — both are surfaced, not hidden."""
    adj = computed["adjudication"]
    assert adj is not None
    assert adj["llm"]["self_attestation_validated"] is True
    assert adj["llm"]["blind_adjudicated_coverage"] == "6/6"
    assert adj["rag"]["independent_precision"] == "8/16"
    m = computed["metrics"]
    assert m["rag_retrieval_self_consistency"] == "5/6"   # the soft number, kept for contrast
    assert m["rag_independent_precision"] == "8/16"        # the honest blind-judged number
    assert m["llm_blind_adjudicated_coverage"] == "6/6"
    assert m["llm_self_attestation_validated"] is True
