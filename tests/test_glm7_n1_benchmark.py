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


def test_known_kb_synonym_gap_is_surfaced(computed):
    """FBG and Cr are missed (disease-KB abbreviation gap) and reported as a follow-up,
    not silently dropped — and explicitly NOT auto-applied to references/*.json."""
    det = computed["layers"]["deterministic"]["column_level"]
    assert set(det["missed"]) == {"FBG", "Cr"}
    gaps = [f for f in computed["followups"] if f["type"] == "disease_kb_synonym_gap"]
    assert gaps and "human confirmation" in gaps[0]["proposed_fix"].lower()


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
