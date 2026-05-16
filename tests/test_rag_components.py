"""Per-module unit tests for the MLGG RAG layer.

These tests cover the seven modules under ``scripts/rag/``:

* ``_rag_config``  — constants, paths, weights
* ``_embeddings``  — sentence-transformer wrapper
* ``_index_builder`` — KB → npz cache, idempotent
* ``_vector_search`` — cosine search over cache
* ``_hybrid_ranker`` — vector + BM25 + gate + tag fusion
* ``_gate_integration`` — gate-failure → contextual concerns

Modules that depend on heavy sentence-transformer downloads or full index
construction are marked ``@pytest.mark.slow`` so ``ci-unit`` (which runs
``-m "not slow"``) skips them, while ``ci-overnight`` exercises them.

Modules still being authored by sibling agents are imported lazily via
``pytest.importorskip`` so that this file remains useful while the build
is in flight: missing modules cause skips, not collection errors.

See ``/tmp/mlgg_rag_design.md`` for the shared design contract.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

# Module-level skip: RAG requires sentence-transformers (listed in
# requirements-optional.txt). If the optional dep isn't installed
# (e.g., a barebones ci-security run), skip the entire file rather
# than collect-erroring on the transitive imports below. ci-unit and
# ci-overnight both install requirements-optional.txt, so this only
# guards against minimal-env runs.
pytest.importorskip("sentence_transformers")

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Module-level imports of always-present modules (A1, A2, A4 already landed).
# ---------------------------------------------------------------------------
from scripts.rag import _rag_config
from scripts.rag._embeddings import embed_texts
from scripts.rag._vector_search import vector_search


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def kb_records() -> list[dict]:
    """Load the real KB once and flatten into concern records.

    Returns:
        A list of concern dicts, each enriched with the parent paper's
        ``paper_id`` / ``paper_title`` so they look like what the index
        builder would emit. Read-only — never mutate in tests.
    """
    kb_path = _rag_config.KB_PATH
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    records: list[dict] = []
    for entry in data.get("entries", []):
        paper_id = entry.get("id")
        paper_title = entry.get("paper_title")
        for concern in entry.get("reviewer_concerns", []):
            rec = dict(concern)
            rec.setdefault("paper_id", paper_id)
            rec.setdefault("paper_title", paper_title)
            records.append(rec)
    return records


@pytest.fixture(scope="module")
def synthetic_embeddings_and_records() -> tuple[np.ndarray, list[dict]]:
    """Embed a small synthetic set of concern-like records.

    Built once per module to amortise the sentence-transformer load. Returns
    L2-normalized float32 vectors matching the synthetic records.
    """
    records = [
        {
            "concern_id": "SYN-001",
            "paper_id": "SYN-001-P",
            "severity": "HIGH",
            "mlgg_gates": ["leakage_gate"],
            "tags": ["patient_overlap", "split"],
            "concern_text": (
                "Patients appear in both training and test sets, "
                "violating patient-level split protocol."
            ),
        },
        {
            "concern_id": "SYN-002",
            "paper_id": "SYN-002-P",
            "severity": "MEDIUM",
            "mlgg_gates": ["evaluation_quality_gate"],
            "tags": ["calibration"],
            "concern_text": "No calibration plot or Brier score is reported.",
        },
        {
            "concern_id": "SYN-003",
            "paper_id": "SYN-003-P",
            "severity": "LOW",
            "mlgg_gates": ["external_validation_gate"],
            "tags": ["external_cohort"],
            "concern_text": "External validation cohort is missing entirely.",
        },
        {
            "concern_id": "SYN-004",
            "paper_id": "SYN-004-P",
            "severity": "HIGH",
            "mlgg_gates": ["tuning_leakage_gate"],
            "tags": ["hyperparameter_tuning"],
            "concern_text": "Hyperparameters were selected on the held-out test set.",
        },
    ]
    texts = [r["concern_text"] for r in records]
    embeddings = embed_texts(texts)
    return embeddings, records


# ===========================================================================
# _rag_config
# ===========================================================================

class TestRagConfig:
    """Constants, path anchoring and weight sanity for the shared config."""

    def test_embedding_constants_present(self) -> None:
        """All embedding constants exposed and well-typed."""
        assert isinstance(_rag_config.EMBEDDING_MODEL, str)
        assert _rag_config.EMBEDDING_MODEL  # non-empty
        assert isinstance(_rag_config.EMBEDDING_DIM, int)
        assert _rag_config.EMBEDDING_DIM == 384

    def test_paths_resolve_under_repo_root(self) -> None:
        """Cache and KB paths must live under the resolved repo root."""
        repo_root = _rag_config.REPO_ROOT
        assert repo_root.is_absolute()
        # All declared paths must be inside the repo root.
        for p in (
            _rag_config.CACHE_DIR,
            _rag_config.EMBEDDINGS_CACHE,
            _rag_config.KB_HASH_CACHE,
            _rag_config.KB_PATH,
        ):
            assert isinstance(p, Path)
            assert str(p).startswith(str(repo_root)), (
                f"path {p} escapes repo root {repo_root}"
            )
        # KB file must actually exist (read-only contract).
        assert _rag_config.KB_PATH.exists(), "peer-review-kb.json missing"

    def test_weights_sum_to_one(self) -> None:
        """Hybrid ranking weights must sum to ~1.0 (contract guarantee)."""
        total = (
            _rag_config.WEIGHT_DENSE
            + _rag_config.WEIGHT_BM25
            + _rag_config.WEIGHT_TAG_OVERLAP
            + _rag_config.WEIGHT_SEVERITY
        )
        assert abs(total - 1.0) < 1e-9, f"weights sum to {total}, expected 1.0"

    def test_weights_individually_in_unit_interval(self) -> None:
        """No weight should be negative or exceed 1 (sanity)."""
        for name in (
            "WEIGHT_DENSE",
            "WEIGHT_BM25",
            "WEIGHT_TAG_OVERLAP",
            "WEIGHT_SEVERITY",
        ):
            w = getattr(_rag_config, name)
            assert 0.0 <= w <= 1.0, f"{name}={w} out of [0,1]"

    def test_defaults_are_positive_ints(self) -> None:
        """``DEFAULT_TOP_K`` and the rerank cap are positive integers."""
        assert isinstance(_rag_config.DEFAULT_TOP_K, int)
        assert _rag_config.DEFAULT_TOP_K > 0
        assert isinstance(_rag_config.DEFAULT_MAX_CANDIDATES_BEFORE_RERANK, int)
        assert (
            _rag_config.DEFAULT_MAX_CANDIDATES_BEFORE_RERANK
            >= _rag_config.DEFAULT_TOP_K
        )


# ===========================================================================
# _embeddings
# ===========================================================================

class TestEmbeddings:
    """Sentence-transformer wrapper behaviour."""

    def test_empty_input_returns_empty_matrix_without_model_load(self) -> None:
        """``embed_texts([])`` must short-circuit and avoid loading the model."""
        out = embed_texts([])
        assert isinstance(out, np.ndarray)
        assert out.shape == (0, _rag_config.EMBEDDING_DIM)
        assert out.dtype == np.float32

    def test_type_validation(self) -> None:
        """Non-list / non-string inputs raise ``TypeError``."""
        with pytest.raises(TypeError):
            embed_texts("not a list")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            embed_texts([1, 2, 3])  # type: ignore[list-item]

    def test_embeddings_shape_dtype_and_normalization(self) -> None:
        """``embed_texts(["a","b"])`` returns ``(2, DIM)`` unit-norm float32."""
        out = embed_texts(["a", "b"])
        assert out.shape == (2, _rag_config.EMBEDDING_DIM)
        assert out.dtype == np.float32
        norms = np.linalg.norm(out, axis=1)
        # Allow small float32 slop around 1.0.
        np.testing.assert_allclose(norms, np.ones(2), atol=1e-4)

    def test_deterministic_for_identical_input(self) -> None:
        """Encoding the same text twice yields bit-equal output."""
        a = embed_texts(["patient overlap between train and test"])
        b = embed_texts(["patient overlap between train and test"])
        np.testing.assert_array_equal(a, b)


# ===========================================================================
# _index_builder
# ===========================================================================

class TestIndexBuilder:
    """Cache build, reload and KB-hash invalidation for the index builder."""

    @pytest.mark.slow
    def test_build_or_load_index_shapes(self) -> None:
        """First-time build returns aligned ``(embeddings, records)``.

        Marked ``slow`` because a cold build encodes 817 concerns.
        """
        mod = pytest.importorskip("scripts.rag._index_builder")
        embeddings, records = mod.build_or_load_index()
        assert isinstance(embeddings, np.ndarray)
        assert isinstance(records, list)
        assert embeddings.ndim == 2
        assert embeddings.shape[0] == len(records)
        assert embeddings.shape[1] == _rag_config.EMBEDDING_DIM
        assert embeddings.dtype == np.float32
        # Every record must expose at least the contract minimum fields.
        for r in records[:5]:
            assert "concern_id" in r
            assert "mlgg_gates" in r

    def test_cache_hit_is_fast(self, tmp_path: Path) -> None:
        """A warm cache must return in well under a second.

        We do not pre-build here — we time two consecutive calls and assert
        that the second is dramatically faster than the first (cache hit).
        If the index builder module is not yet present this test skips.
        """
        mod = pytest.importorskip("scripts.rag._index_builder")
        # First call may be cold (built once for the whole test process,
        # likely already warm from the real cache on disk).
        t0 = time.perf_counter()
        mod.build_or_load_index()
        first = time.perf_counter() - t0

        t0 = time.perf_counter()
        mod.build_or_load_index()
        second = time.perf_counter() - t0

        # Cache hit must be <1s in all environments.
        assert second < 1.0, f"warm load took {second:.3f}s (>1s)"
        # And strictly faster than (or comparable to) the first call.
        # We allow equality because both calls may already be warm on CI.
        assert second <= max(first, 1.0) + 0.01

    def test_cache_invalidates_on_kb_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Changing the KB content must force a rebuild (hash invalidation).

        Uses a tiny synthetic KB so this test is cheap and does not depend
        on the slow path. Skips if the builder is not yet authored.
        """
        mod = pytest.importorskip("scripts.rag._index_builder")

        # Synthetic KB v1
        tiny_kb_v1 = {
            "contract_version": "test.v1",
            "entries": [
                {
                    "id": "TEST-001",
                    "paper_title": "v1 paper",
                    "reviewer_concerns": [
                        {
                            "concern_id": "TEST-001-C01",
                            "severity": "HIGH",
                            "mlgg_gates": ["leakage_gate"],
                            "tags": ["x"],
                            "concern_text": "patient overlap v1",
                        }
                    ],
                }
            ],
        }
        kb_path = tmp_path / "kb.json"
        cache_dir = tmp_path / ".cache"
        cache_dir.mkdir()
        kb_path.write_text(json.dumps(tiny_kb_v1), encoding="utf-8")

        # Redirect cache locations to tmp_path so we do not touch the real cache.
        monkeypatch.setattr(_rag_config, "KB_PATH", kb_path, raising=True)
        monkeypatch.setattr(_rag_config, "CACHE_DIR", cache_dir, raising=True)
        monkeypatch.setattr(
            _rag_config,
            "EMBEDDINGS_CACHE",
            cache_dir / "concerns_embeddings.npz",
            raising=True,
        )
        monkeypatch.setattr(
            _rag_config,
            "KB_HASH_CACHE",
            cache_dir / "kb_hash.txt",
            raising=True,
        )
        # The builder module likely captured these at import time; mirror the
        # patch onto it as well if it re-exports them.
        for attr in (
            "KB_PATH",
            "CACHE_DIR",
            "EMBEDDINGS_CACHE",
            "KB_HASH_CACHE",
        ):
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, getattr(_rag_config, attr), raising=True)

        emb_v1, rec_v1 = mod.build_or_load_index(kb_path=kb_path)
        assert len(rec_v1) == 1
        v1_hash = hashlib.sha256(kb_path.read_bytes()).hexdigest()

        # Mutate the KB → new content, new hash → cache must rebuild.
        tiny_kb_v2 = json.loads(json.dumps(tiny_kb_v1))
        tiny_kb_v2["entries"].append(
            {
                "id": "TEST-002",
                "paper_title": "v2 paper",
                "reviewer_concerns": [
                    {
                        "concern_id": "TEST-002-C01",
                        "severity": "MEDIUM",
                        "mlgg_gates": ["evaluation_quality_gate"],
                        "tags": ["y"],
                        "concern_text": "calibration missing v2",
                    }
                ],
            }
        )
        kb_path.write_text(json.dumps(tiny_kb_v2), encoding="utf-8")
        v2_hash = hashlib.sha256(kb_path.read_bytes()).hexdigest()
        assert v1_hash != v2_hash, "test setup error: hashes did not change"

        emb_v2, rec_v2 = mod.build_or_load_index(kb_path=kb_path)
        assert len(rec_v2) == 2, (
            "cache did not invalidate: still saw the v1 record count"
        )
        assert emb_v2.shape[0] == 2


# ===========================================================================
# _vector_search
# ===========================================================================

class TestVectorSearch:
    """Cosine search semantics on the cached concern matrix."""

    def test_top1_dense_score_dominates_top5(
        self,
        synthetic_embeddings_and_records: tuple[np.ndarray, list[dict]],
    ) -> None:
        """The top-1 hit's ``_dense_score`` must be >= every other top-5 hit."""
        embeddings, records = synthetic_embeddings_and_records
        query = "patients appear in both train and test sets"
        results = vector_search(query, embeddings, records, top_k=5)
        assert len(results) >= 1
        top1 = results[0]["_dense_score"]
        for r in results[1:]:
            assert top1 >= r["_dense_score"]

    def test_results_are_descending(
        self,
        synthetic_embeddings_and_records: tuple[np.ndarray, list[dict]],
    ) -> None:
        """``vector_search`` returns results sorted by descending score."""
        embeddings, records = synthetic_embeddings_and_records
        results = vector_search(
            "hyperparameter tuning on test set", embeddings, records, top_k=4
        )
        scores = [r["_dense_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_input_records_not_mutated(
        self,
        synthetic_embeddings_and_records: tuple[np.ndarray, list[dict]],
    ) -> None:
        """``vector_search`` must not add ``_dense_score`` to caller records."""
        embeddings, records = synthetic_embeddings_and_records
        before = [dict(r) for r in records]  # deep-ish snapshot
        vector_search("anything", embeddings, records, top_k=2)
        assert records == before, "input records were mutated"
        for r in records:
            assert "_dense_score" not in r

    def test_top_k_capped_at_corpus_size(
        self,
        synthetic_embeddings_and_records: tuple[np.ndarray, list[dict]],
    ) -> None:
        """Requesting more than N hits returns exactly N hits, sorted."""
        embeddings, records = synthetic_embeddings_and_records
        results = vector_search("missing baseline", embeddings, records, top_k=100)
        assert len(results) == len(records)

    def test_invalid_inputs_raise(
        self,
        synthetic_embeddings_and_records: tuple[np.ndarray, list[dict]],
    ) -> None:
        """Empty query, non-positive ``top_k`` and shape mismatch each raise."""
        embeddings, records = synthetic_embeddings_and_records
        with pytest.raises(ValueError):
            vector_search("", embeddings, records)
        with pytest.raises(ValueError):
            vector_search("q", embeddings, records, top_k=0)
        with pytest.raises(ValueError):
            vector_search("q", embeddings, records[:-1])


# ===========================================================================
# _hybrid_ranker
# ===========================================================================

class TestHybridRanker:
    """Gate-filter, BM25-fusion and dense-only behaviours of the ranker."""

    def test_gate_filter_restricts_results(self) -> None:
        """With a gate filter, every returned concern lists that gate."""
        mod = pytest.importorskip("scripts.rag._hybrid_ranker")
        gate = "leakage_gate"
        results = mod.hybrid_rank(
            "patient appears in both train and test",
            gate=gate,
            top_k=5,
        )
        assert isinstance(results, list)
        assert len(results) >= 1
        for r in results:
            gates = r.get("mlgg_gates") or []
            assert gate in gates, (
                f"concern {r.get('concern_id')} returned without {gate}: "
                f"gates={gates}"
            )

    def test_failure_codes_populate_bm25_scores(self) -> None:
        """Passing ``failure_codes`` triggers the BM25 fusion path."""
        mod = pytest.importorskip("scripts.rag._hybrid_ranker")
        results = mod.hybrid_rank(
            "no calibration reported",
            gate="evaluation_quality_gate",
            failure_codes=["MLGG-E02"],
            top_k=5,
        )
        assert len(results) >= 1
        # At least one result must have a numeric BM25 score field.
        assert any(
            isinstance(r.get("_bm25_score"), (int, float)) for r in results
        ), "no result carried a _bm25_score after BM25 fusion"
        # Every result must carry the contract scoring metadata.
        for r in results:
            assert "_final_score" in r
            assert "_dense_score" in r

    def test_dense_only_path_without_gate(self) -> None:
        """Without ``gate`` and without ``failure_codes`` the dense path runs."""
        mod = pytest.importorskip("scripts.rag._hybrid_ranker")
        results = mod.hybrid_rank(
            "external validation cohort missing",
            top_k=3,
        )
        assert isinstance(results, list)
        assert 1 <= len(results) <= 3
        for r in results:
            assert "concern_id" in r
            assert "_dense_score" in r


# ===========================================================================
# _gate_integration
# ===========================================================================

class TestGateIntegration:
    """Markdown rendering hook for gate-failure reports."""

    def test_empty_input_returns_valid_markdown(self) -> None:
        """``format_for_gate_report([])`` must return a markdown string."""
        mod = pytest.importorskip("scripts.rag._gate_integration")
        if not hasattr(mod, "format_for_gate_report"):
            pytest.skip("format_for_gate_report not yet implemented")
        md = mod.format_for_gate_report([])
        assert isinstance(md, str)
        # Empty input must not blow up and must not invent fake concerns.
        assert "PR-" not in md

    def test_nonempty_input_produces_markdown_with_concern_ids(self) -> None:
        """Rendering a few concerns yields markdown that cites concern_ids."""
        mod = pytest.importorskip("scripts.rag._gate_integration")
        if not hasattr(mod, "format_for_gate_report"):
            pytest.skip("format_for_gate_report not yet implemented")
        sample: list[dict[str, Any]] = [
            {
                "concern_id": "PR-001-C01",
                "paper_id": "PR-001",
                "paper_title": "Sample paper",
                "severity": "HIGH",
                "mlgg_gates": ["leakage_gate"],
                "concern_text": "patient overlap across split",
                "_final_score": 0.81,
                "_dense_score": 0.78,
                "_bm25_score": 0.62,
                "_match_reasons": ["dense top-5", "gate match"],
            },
            {
                "concern_id": "PR-002-C03",
                "paper_id": "PR-002",
                "paper_title": "Another paper",
                "severity": "MEDIUM",
                "mlgg_gates": ["evaluation_quality_gate"],
                "concern_text": "no calibration reported",
                "_final_score": 0.55,
                "_dense_score": 0.52,
                "_bm25_score": 0.40,
                "_match_reasons": ["dense top-5"],
            },
        ]
        md = mod.format_for_gate_report(sample)
        assert isinstance(md, str)
        assert md.strip(), "markdown output was empty for non-empty input"
        for r in sample:
            assert r["concern_id"] in md, (
                f"concern_id {r['concern_id']} missing from rendered markdown"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
